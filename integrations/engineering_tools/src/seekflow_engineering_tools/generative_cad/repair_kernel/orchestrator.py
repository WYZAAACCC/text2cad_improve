"""Repair Loop Orchestrator (repair_loop.md §2.1/§16, Stage D).

run_generation_loop 是完整流程中 current_raw_document 的**唯一所有者**:
validation → 确定性 repair (repair_kernel.engine 原样复用) → LLM validation
repair (复用 RepairPatchV2 + governor 原语) → runtime → 失败分类 (fail-closed)
→ runtime LLM patch (params-only 策略 + 数值预算) → **完整重验证** → commit
→ 用新 canonical 重跑 runtime。旧 canonical 永不复用 (§2.2)。

其他组件保持纯粹: Validator 不重试, Runtime 不修 IR, Agent 只产局部 Patch。
全部尝试审计落盘 (§17), 不可修类别不消耗预算 (§6.3)。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from pydantic import BaseModel, Field

from seekflow_engineering_tools.generative_cad.repair_kernel.config import RepairLoopConfig
from seekflow_engineering_tools.generative_cad.repair_kernel.classifier import (
    RuntimeFailureClass,
    classify_runtime_failure,
)
from seekflow_engineering_tools.generative_cad.repair_kernel.models import (
    QualityVector,
    RepairOutcome,
    is_strict_improvement,
)


class RepairLoopOutcome(BaseModel):
    """落盘为 repair_summary.json — 停止原因必须可完整解释 (§17)."""

    ok: bool = False
    stop_code: str = ""
    stop_reason: str = ""
    autofix_accepted: bool = False
    validation_llm_attempts: int = 0
    runtime_llm_attempts: int = 0
    accepted_patches: list[dict] = Field(default_factory=list)
    rejected_patches: list[dict] = Field(default_factory=list)
    raw_hashes: list[str] = Field(default_factory=list)
    error_signatures: list[str] = Field(default_factory=list)


class RepairLoopResult:
    """run_generation_loop 的完整返回 — document 与 vrun 恒为同快照."""

    def __init__(self, *, document: dict, vrun, run_result,
                 repair_outcome: RepairOutcome | None,
                 autofix_provider, outcome: RepairLoopOutcome) -> None:
        self.document = document
        self.vrun = vrun
        self.run_result = run_result
        self.repair_outcome = repair_outcome
        self.autofix_provider = autofix_provider
        self.outcome = outcome


_REPEAT_GUIDANCE_TMPL = (
    "The repair is not making progress: the same {kind} has already been "
    "submitted and rejected without changing the document. You MUST either "
    "propose a genuinely different patch that is not identical to any previous "
    "attempt, or set give_up=true. Repeating an already-submitted patch is "
    "forbidden."
)


def check_patch_common(patch, *, cfg: RepairLoopConfig) -> tuple[bool, str]:
    """两阶段共用的补丁硬规则 (§8.1/§10.4/§4).

    - 字节上限 (max_absolute_patch_bytes);
    - 默认禁止改 required/degradation_policy — LLM 不得用降级掩盖失败
      (§10.4; 确定性策略降级不走本路径, 不受影响)。
    """
    import re
    if patch.give_up:
        return True, ""
    size = len(json.dumps(patch.model_dump(), default=str).encode("utf-8"))
    if size > cfg.max_absolute_patch_bytes:
        return False, f"patch size {size}B exceeds limit {cfg.max_absolute_patch_bytes}B"
    if not cfg.allow_degradation_change:
        gate = re.compile(r"^/nodes/[^/]+/(required|degradation_policy)$")
        for ch in patch.changes:
            if gate.match(ch.path):
                return False, (f"path {ch.path!r} forbidden: LLM repair must not "
                               f"weaken required/degradation to mask failures (§10.4)")
    return True, ""


def _numeric(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def check_runtime_patch(patch, *, target_node_id: str,
                        allowed_paths: list[str],
                        cfg: RepairLoopConfig) -> tuple[bool, str]:
    """runtime patch 策略 (§8.1 硬规则 + §10.3 数值预算) — 比 validation 严.

    路径必须落在分类器给出的目标节点 params 内; old_value 必填 (锚定);
    数值改动 ≤ max_relative_numeric_change、不变号、不换类型。
    """
    import re
    if patch.give_up:
        return True, ""
    if not patch.changes:
        return False, "empty runtime patch"
    if len(patch.changes) > cfg.max_changes_per_patch:
        return False, f"too many changes: {len(patch.changes)} > {cfg.max_changes_per_patch}"
    def _allowed_regex(p):
        m = re.match(r"^/nodes/([^/]+)/params", p)
        if not m:
            return None
        return re.compile(rf"^/nodes/{re.escape(m.group(1))}/params(/.+)?$")
    allowed_regexes = [r for r in (_allowed_regex(p) for p in allowed_paths) if r]
    if not allowed_regexes:
        allowed_regexes = [re.compile(rf"^/nodes/{re.escape(target_node_id)}/params/.+$")]
    allowed_prefixes = tuple(allowed_paths)
    for ch in patch.changes:
        if not any(r.match(ch.path) for r in allowed_regexes):
            return False, f"path {ch.path!r} outside allowed repair node params"
        if allowed_prefixes and not any(
                ch.path == p or ch.path.startswith(p.rstrip("/") + "/")
                or p == f"/nodes/{target_node_id}/params"
                for p in allowed_prefixes):
            return False, f"path {ch.path!r} not in classifier allowed paths"
        if ch.old_value is None:
            return False, f"runtime change at {ch.path!r} must anchor exact old_value"
        old_n, new_n = _numeric(ch.old_value), _numeric(ch.new_value)
        if old_n is not None:
            if new_n is None:
                return False, f"numeric→non-numeric swap at {ch.path!r}"
            if old_n * new_n < 0:
                return False, f"sign flip at {ch.path!r}"
            rel = abs(new_n - old_n) / max(abs(old_n), 1e-9)
            if rel > cfg.max_relative_numeric_change:
                return False, (f"numeric change {rel:.2f} exceeds budget "
                               f"{cfg.max_relative_numeric_change} at {ch.path!r}")
        elif new_n is not None:
            return False, f"non-numeric→numeric swap at {ch.path!r}"
    return True, ""


def _runtime_error_signature(report) -> str:
    """§11.5: 强错误签名 (stage/code/node/path), 非仅 code."""
    from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash
    return stable_hash(sorted(
        [i.stage, i.code, i.node_id or "", i.path or ""] for i in report.issues))


def _validation_error_signature(report) -> str:
    """§11.5: validation 侧同用强签名 — code-only 无法区分不同节点的同类错."""
    from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash
    return stable_hash(sorted(
        [getattr(i, "stage", "") or "", getattr(i, "code", "") or "",
         getattr(i, "node_id", "") or "", getattr(i, "path", "") or ""]
        for i in report.issues))


def _write_json(path: Path, obj: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(obj, "model_dump_json"):
            path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
        else:
            path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                            encoding="utf-8")
    except Exception:
        pass  # 审计写盘失败不得中断修复流程


def _merge_outcome(total: RepairOutcome | None, new: RepairOutcome) -> RepairOutcome:
    if total is None:
        return new
    total.attempts += new.attempts
    total.accepted = total.accepted or new.accepted
    total.final_ok = new.final_ok
    total.records.extend(new.records)
    return total


def run_generation_loop(
    raw_doc: dict,
    *,
    out_step: Path,
    metadata_path: Path,
    dialect_registry=None,
    config: RepairLoopConfig | None = None,
    validation_repair_caller=None,
    runtime_repair_caller=None,
    llm_model_config=None,
    audit_dir: Path | None = None,
    on_stage: Callable[[str, int], None] | None = None,
    user_request: str = "",
    runtime_runner=None,
) -> RepairLoopResult:
    """统一 Repair Loop (validation + runtime 双环, §16).

    runtime_runner: 测试注入点 — 默认 pipeline.run.run_canonical_gcad。
    """
    from seekflow_engineering_tools.generative_cad.validation_kernel import run_validation
    from seekflow_engineering_tools.generative_cad.repair_kernel.engine import repair_documents
    from seekflow_engineering_tools.generative_cad.repair.governor import (
        RepairStateV2,
        can_repair_v2,
        stage_rank_for,
        update_repair_state_v2,
    )
    from seekflow_engineering_tools.generative_cad.repair.patch import (
        RepairPatchV2,
        apply_repair_patch_v2,
    )
    from seekflow_engineering_tools.generative_cad.repair.hashes import repair_patch_hash
    from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash
    from seekflow_engineering_tools.generative_cad.authoring.prompt_builders import (
        REPAIR_SYSTEM_PROMPT,
        RUNTIME_REPAIR_SYSTEM_PROMPT,
        _build_op_contract,
        build_repair_user_prompt,
        build_runtime_repair_user_prompt,
    )
    from seekflow_engineering_tools.generative_cad.authoring.tool_schemas import (
        build_repair_patch_tool_schema,
    )

    if runtime_runner is None:
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        runtime_runner = run_canonical_gcad

    # RepairPatchV2 合法路径语法 (patch.py ALLOWED_PATH_PATTERNS 的人类可读形式) —
    # 不传则 LLM 常臆造深子路径 (如 /nodes/x/inputs/0/node) 被白名单拒绝空耗预算
    _V2_PATH_GRAMMAR = [
        "/nodes/<node_id>/params/<field>",
        "/nodes/<node_id>/inputs   (replace the ENTIRE inputs array, anchored by old_value)",
        "/nodes/<node_id>/outputs  (replace the ENTIRE outputs array)",
        "/nodes/<node_id>/required",
        "/nodes/<node_id>/degradation_policy",
        "/components/<component_id>/root_node",
        "/llm_validation_hints",
    ]

    cfg = config or RepairLoopConfig()
    outcome = RepairLoopOutcome()
    state = RepairStateV2(max_attempts=max(1, cfg.max_total_llm_attempts))
    current: dict = raw_doc
    vrun = None
    rr = None
    repair_outcome: RepairOutcome | None = None
    autofix_provider = None
    prior_runtime_attempts: list[dict] = []
    prior_validation_attempts: list[dict] = []
    repeated_raw_seen: dict[str, int] = {}

    def _stage(label: str, pct: int) -> None:
        if on_stage is not None:
            try:
                on_stage(label, pct)
            except Exception:
                pass

    def _finish(stop_code: str, reason: str = "", *, ok: bool = False) -> RepairLoopResult:
        outcome.ok = ok
        outcome.stop_code = stop_code
        outcome.stop_reason = reason
        if audit_dir is not None:
            _write_json(Path(audit_dir) / "repair_summary.json", {
                "outcome": outcome.model_dump(mode="json"),
                "config": cfg.model_dump(mode="json"),
            })
        return RepairLoopResult(
            document=current, vrun=vrun, run_result=rr,
            repair_outcome=repair_outcome, autofix_provider=autofix_provider,
            outcome=outcome,
        )

    def _call_patch_llm(caller, system_prompt: str, user_prompt: str,
                        guidance: str = ""):
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}]
        if guidance:
            messages.append({"role": "user", "content": guidance})
        def _call_once(msgs):
            tc = caller.call_strict_tool(
                messages=msgs,
                tool_name="emit_repair_patch",
                tool_description="Local repair patch",
                tool_schema=build_repair_patch_tool_schema(),
                model_config=llm_model_config,
            )
            if tc.arguments.get("give_up"):
                return None
            return RepairPatchV2.model_validate(tc.arguments)

        try:
            return _call_once(messages)
        except Exception as exc:
            retry_messages = messages + [
                {"role": "assistant", "content": "The previous repair patch was rejected by the patch schema."},
                {"role": "user", "content": f"Schema validation failed: {exc}. Re-emit a COMPLETE repair patch that satisfies the schema."},
            ]
            return _call_once(retry_messages)

    def _repeat_handling(raw_hash: str, kind: str):
        """Give one explicit change-or-give-up chance, then stop cleanly.

        Pure repair-loop logic: identical submissions mean the LLM is not
        making progress, so the loop must end with an auditable give_up instead
        of silently spinning until a generic governor stop.

        Returns (stop_reason, guidance, allow_new_attempt).  On the first
        repeat the caller must bypass the governor (its raw-hash guard would
        otherwise stop before the guidance reaches the LLM) and call the LLM
        with the guidance message.
        """
        seen = repeated_raw_seen.get(raw_hash, 0)
        repeated_raw_seen[raw_hash] = seen + 1
        if seen == 0:
            return "", "", True
        if seen == 1:
            return "", _REPEAT_GUIDANCE_TMPL.format(kind=kind), False
        return (f"repair agent repeated the same {kind} after guidance "
                "to change or give up"), "", False

    def _check_contract_changes(patch, current):
        # phase/op_version repairs must resolve to registered op contract values.
        import re as _re
        if dialect_registry is None:
            for ch in patch.changes:
                if _re.match(r"^/nodes/[^/]+/(phase|op_version)$", ch.path):
                    return False, "phase/op_version repair requires dialect_registry",
            return True, ""
        for ch in patch.changes:
            m = _re.match(r"^/nodes/([^/]+)/(phase|op_version)$", ch.path)
            if not m:
                continue
            node = next((n for n in current.get("nodes", [])
                         if n.get("id") == m.group(1)), None)
            if node is None:
                return False, "target node not found: " + m.group(1)
            d = dialect_registry.get(node.get("dialect", ""))
            if d is None:
                return False, "unknown dialect: " + str(node.get("dialect", ""))
            op = node.get("op", "")
            new_ver = None
            for ch2 in patch.changes:
                m2 = _re.match(r"^/nodes/([^/]+)/op_version$", ch2.path)
                if m2 and m2.group(1) == m.group(1):
                    new_ver = ch2.new_value
                    break
            try:
                resolved_v = new_ver or node.get("op_version") or d.default_op_version(op)
                spec = d.get_op_spec(op, resolved_v)
            except (KeyError, ValueError):
                spec = None
            if m.group(2) == "phase":
                if spec is None:
                    return False, "cannot resolve op contract for phase"
                if ch.new_value != spec.phase:
                    return False, "phase must be %r, got %r" % (spec.phase, ch.new_value)
            else:
                default_v = d.default_op_version(op)
                if ch.new_value != default_v:
                    return False, "op_version must be %r, got %r" % (default_v, ch.new_value)
        return True, ""

    def _audit_attempt(phase: str, idx: int, files: dict[str, Any]) -> None:
        if audit_dir is None:
            return
        base = Path(audit_dir) / "repair" / phase / f"attempt_{idx:02d}"
        for name, obj in files.items():
            _write_json(base / f"{name}.json", obj)

    total_llm = 0

    while True:
        # ── Validation (+ deterministic repair) ──
        _stage("Validation", 65)
        vrun = run_validation(current)
        if not vrun.report.ok and cfg.deterministic_autofix_enabled:
            rres = repair_documents(current, vrun, dialect_registry=dialect_registry)
            repair_outcome = _merge_outcome(repair_outcome, rres.outcome)
            provider = getattr(rres, "provider", None)
            if provider is not None:
                autofix_provider = provider
            if rres.outcome.accepted:
                outcome.autofix_accepted = True
            current, vrun = rres.document, rres.run

        # ── Validation LLM repair loop ──
        while not vrun.report.ok:
            if not (cfg.enabled and cfg.validation_repair_enabled):
                return _finish("validation_failed", "validation repair disabled")
            if validation_repair_caller is None:
                # §4.1: 不得在报告中声称 LLM repair 已启用
                return _finish("repair_unavailable",
                               "validation failed and no repair caller configured")
            if outcome.validation_llm_attempts >= cfg.max_validation_llm_attempts:
                return _finish("validation_attempts_exhausted",
                               f"{outcome.validation_llm_attempts} attempts used")
            if total_llm >= cfg.max_total_llm_attempts:
                return _finish("total_attempts_exhausted", f"{total_llm} LLM attempts used")

            raw_hash = stable_hash(current)
            error_sig = _validation_error_signature(vrun.report)
            stage_rank = stage_rank_for(getattr(vrun.report, "stage", "") or "")
            stop_why, guidance, allow_new = _repeat_handling(raw_hash, "raw graph")
            if stop_why:
                return _finish("give_up", stop_why)
            if allow_new:
                can, why = can_repair_v2(state, raw_graph_hash=raw_hash,
                                         error_sig_hash=error_sig,
                                         current_stage_rank=stage_rank)
                if not can:
                    return _finish("governor_stop", why)

            _stage("LLM validation repair", 68)
            outcome.validation_llm_attempts += 1
            total_llm += 1
            attempt_idx = outcome.validation_llm_attempts
            issues = [i.model_dump(mode="json") for i in vrun.report.issues]
            try:
                patch = _call_patch_llm(validation_repair_caller, REPAIR_SYSTEM_PROMPT,
                                        build_repair_user_prompt(
                                            current, issues,
                                            repairable_paths=_V2_PATH_GRAMMAR,
                                            prior_attempts=prior_validation_attempts),
                                        guidance=guidance)
            except Exception as exc:
                return _finish("repair_caller_error", str(exc)[:500])
            if patch is None:
                return _finish("give_up", "validation repair agent gave up")

            patch_hash = repair_patch_hash(patch)
            if patch_hash in state.repair_patch_hashes:
                return _finish(
                    "give_up",
                    "validation repair repeated an already-submitted patch "
                    "instead of changing it or giving up")
            can, why = can_repair_v2(state, patch_hash=patch_hash)
            if not can:
                return _finish("governor_stop", why)

            audit: dict[str, Any] = {"patch": patch.model_dump(mode="json")}

            # 两阶段共用硬规则: 字节上限 + 禁止降级掩盖 (§10.4/§4)
            ok_common, why = check_patch_common(patch, cfg=cfg)
            if not ok_common:
                audit["apply_report"] = {"ok": False, "rejection_reason": why}
                _audit_attempt("validation", attempt_idx, audit)
                outcome.rejected_patches.append({"phase": "validation",
                                                 "patch_hash": patch_hash,
                                                 "reason": why[:200]})
                prior_validation_attempts.append(
                    {"patch": patch.model_dump(mode="json"), "rejected": why[:200]})
                state = update_repair_state_v2(state, raw_graph_hash=raw_hash,
                                               error_sig_hash=error_sig,
                                               patch_hash=patch_hash,
                                               stage_rank=stage_rank)
                continue

            ok_contract, contract_why = _check_contract_changes(patch, current)
            if not ok_contract:
                audit["apply_report"] = {"ok": False, "rejection_reason": contract_why}
                _audit_attempt("validation", attempt_idx, audit)
                outcome.rejected_patches.append({"phase": "validation",
                                                 "patch_hash": patch_hash,
                                                 "reason": contract_why[:200]})
                prior_validation_attempts.append(
                    {"patch": patch.model_dump(mode="json"), "rejected": contract_why[:200]})
                state = update_repair_state_v2(state, raw_graph_hash=raw_hash,
                                               error_sig_hash=error_sig,
                                               patch_hash=patch_hash,
                                               stage_rank=stage_rank)
                continue

            try:
                candidate = apply_repair_patch_v2(current, patch)
            except Exception as exc:
                audit["apply_report"] = {"ok": False, "rejection_reason": str(exc)[:500]}
                _audit_attempt("validation", attempt_idx, audit)
                outcome.rejected_patches.append({"phase": "validation",
                                                 "reason": str(exc)[:200]})
                prior_validation_attempts.append(
                    {"patch": patch.model_dump(mode="json"),
                     "rejected": str(exc)[:200]})
                state = update_repair_state_v2(state, raw_graph_hash=raw_hash,
                                               error_sig_hash=error_sig,
                                               patch_hash=patch_hash,
                                               stage_rank=stage_rank)
                continue

            cvrun = run_validation(candidate)
            q_before = QualityVector.from_report(vrun.report)
            baseline = {getattr(i, "code", "") for i in vrun.report.issues
                        if getattr(i, "severity", "") == "error"}
            q_after = QualityVector.from_report(cvrun.report, baseline_error_codes=baseline)
            cand_hash = stable_hash(candidate)
            audit["candidate_raw"] = candidate
            audit["validation_report"] = cvrun.report
            audit["progress"] = {
                "before": list(q_before.key()), "after": list(q_after.key()),
                "candidate_hash": cand_hash,   # §1.3: 记录候选状态
            }
            accepted = cvrun.report.ok or is_strict_improvement(q_before, q_after)
            audit["apply_report"] = {"ok": True, "base_hash": raw_hash,
                                     "candidate_hash": cand_hash, "accepted": accepted}
            _audit_attempt("validation", attempt_idx, audit)
            outcome.raw_hashes.append(cand_hash)
            outcome.error_signatures.append(error_sig)

            if accepted:
                outcome.accepted_patches.append(
                    {"phase": "validation", "patch_hash": patch_hash})
                current, vrun = candidate, cvrun
            else:
                reject_why = (f"quality not strictly improved: "
                              f"before={q_before.key()} after={q_after.key()}")
                outcome.rejected_patches.append({
                    "phase": "validation", "patch_hash": patch_hash,
                    "reason": reject_why})
                prior_validation_attempts.append(
                    {"patch": patch.model_dump(mode="json"),
                     "rejected": reject_why[:200]})
            state = update_repair_state_v2(state, raw_graph_hash=raw_hash,
                                           error_sig_hash=error_sig,
                                           patch_hash=patch_hash,
                                           stage_rank=stage_rank)

        # ── Runtime ──
        _stage("Runtime", 85)
        rr = runtime_runner(
            vrun.canonical, out_step=out_step, metadata_path=metadata_path,
            validation_seed=vrun.bundle.to_metadata_dict() if vrun.bundle else {},
            require_full_validation_seed=False,
        )
        if rr.ok:
            return _finish("success", ok=True)

        # ── Runtime failure classification (fail-closed, §6) ──
        report = rr.runtime_report
        if report is None:
            return _finish("non_repairable:unproven_causality",
                           "runtime produced no structured report")
        cls: RuntimeFailureClass = classify_runtime_failure(report)
        if audit_dir is not None:
            _write_json(Path(audit_dir) / "repair" / "runtime"
                        / f"attempt_{outcome.runtime_llm_attempts + 1:02d}"
                        / "runtime_report.json", report)
        if not cls.repairable:
            # §6.3: 不消耗 repair 预算
            return _finish(f"non_repairable:{cls.class_code}", cls.reason)
        if not (cfg.enabled and cfg.runtime_repair_enabled):
            return _finish("runtime_repair_disabled", cls.reason)
        if runtime_repair_caller is None:
            return _finish("runtime_repair_unavailable",
                           "runtime failure repairable but no runtime repair caller")

        # ── Runtime LLM repair (一次接受 → 回到外层完整重验证+重跑) ──
        committed = False
        while not committed:
            if outcome.runtime_llm_attempts >= cfg.max_runtime_llm_attempts:
                return _finish("runtime_attempts_exhausted",
                               f"{outcome.runtime_llm_attempts} attempts used")
            if total_llm >= cfg.max_total_llm_attempts:
                return _finish("total_attempts_exhausted", f"{total_llm} LLM attempts used")

            raw_hash = stable_hash(current)
            rt_sig = _runtime_error_signature(report)
            # current_stage_rank=0: runtime→validation 回跳不是 stage 回归 (§19 #47)
            stop_why, guidance, allow_new = _repeat_handling(raw_hash, "raw graph")
            if stop_why:
                return _finish("give_up", stop_why)
            if allow_new:
                can, why = can_repair_v2(state, raw_graph_hash=raw_hash,
                                         error_sig_hash=rt_sig, current_stage_rank=0)
                if not can:
                    return _finish("governor_stop", why)

            _stage("LLM runtime repair", 88)
            outcome.runtime_llm_attempts += 1
            total_llm += 1
            attempt_idx = outcome.runtime_llm_attempts
            failing_node = next(
                (n for n in current.get("nodes", [])
                 if n.get("id") == cls.target_node_id), None)
            op_contract = "(unavailable)"
            if failing_node is not None and dialect_registry is not None:
                plan = SimpleNamespace(dialect=failing_node.get("dialect", ""),
                                       op=failing_node.get("op", ""),
                                       op_version=failing_node.get("op_version", "1.0.0"))
                op_contract = _build_op_contract(plan, dialect_registry)
            allowed_paths = list(cls.allowed_paths)
            related_contracts: list[str] = []
            if failing_node is not None and dialect_registry is not None:
                collected: set[str] = set()

                def _collect_input_nodes(node_id: str, depth: int) -> None:
                    if node_id in collected or depth > 8:
                        return
                    collected.add(node_id)
                    node = next((n for n in current.get("nodes", [])
                                 if n.get("id") == node_id), None)
                    if node is None:
                        return
                    allowed_paths.append(f"/nodes/{node_id}/params")
                    plan = SimpleNamespace(dialect=node.get("dialect", ""),
                                           op=node.get("op", ""),
                                           op_version=node.get("op_version", "1.0.0"))
                    related_contracts.append(_build_op_contract(plan, dialect_registry))
                    for inp in node.get("inputs", []):
                        _collect_input_nodes(inp.get("node", ""), depth + 1)

                _collect_input_nodes(cls.target_node_id or "", 0)

            prompt = build_runtime_repair_user_prompt(
                current_doc=current,
                runtime_issues=[i.model_dump(mode="json") for i in report.issues],
                failing_node=failing_node,
                op_contract=op_contract,
                related_contracts=related_contracts,
                geometry_health=report.geometry_health,
                allowed_paths=allowed_paths,
                prior_attempts=prior_runtime_attempts,
                user_request=user_request,
            )
            try:
                patch = _call_patch_llm(runtime_repair_caller,
                                        RUNTIME_REPAIR_SYSTEM_PROMPT, prompt,
                                        guidance=guidance)
            except Exception as exc:
                return _finish("repair_caller_error", str(exc)[:500])
            if patch is None:
                return _finish("give_up", "runtime repair agent gave up")

            patch_hash = repair_patch_hash(patch)
            if patch_hash in state.repair_patch_hashes:
                return _finish(
                    "give_up",
                    "runtime repair repeated an already-submitted patch "
                    "instead of changing it or giving up")
            can, why = can_repair_v2(state, patch_hash=patch_hash)
            if not can:
                return _finish("governor_stop", why)

            audit = {"patch": patch.model_dump(mode="json")}
            patch_dump = patch.model_dump(mode="json")

            def _reject(reason: str) -> None:
                nonlocal state
                audit["apply_report"] = {"ok": False, "rejection_reason": reason}
                _audit_attempt("runtime", attempt_idx, audit)
                outcome.rejected_patches.append(
                    {"phase": "runtime", "patch_hash": patch_hash, "reason": reason[:200]})
                prior_runtime_attempts.append(
                    {"patch": patch_dump, "rejected": reason[:200]})
                state = update_repair_state_v2(state, raw_graph_hash=raw_hash,
                                               error_sig_hash=rt_sig,
                                               patch_hash=patch_hash, stage_rank=0)

            ok_common, why = check_patch_common(patch, cfg=cfg)
            if not ok_common:
                _reject(f"policy: {why}")
                continue
            ok_policy, why = check_runtime_patch(
                patch, target_node_id=cls.target_node_id or "",
                allowed_paths=allowed_paths, cfg=cfg)
            if not ok_policy:
                _reject(f"policy: {why}")
                continue
            try:
                candidate = apply_repair_patch_v2(current, patch)
            except Exception as exc:
                _reject(f"apply: {exc}")
                continue

            # §2.2: runtime patch 后必须完整重验证, 禁止旧 canonical 重试
            cvrun = run_validation(candidate)
            cand_hash = stable_hash(candidate)
            audit["candidate_raw"] = candidate
            audit["validation_after_patch"] = cvrun.report
            audit["progress"] = {"candidate_hash": cand_hash,
                                 "validation_ok": cvrun.report.ok}
            if not cvrun.report.ok:
                _reject("runtime patch broke validation")
                continue

            audit["apply_report"] = {"ok": True, "base_hash": raw_hash,
                                     "candidate_hash": cand_hash, "accepted": True}
            _audit_attempt("runtime", attempt_idx, audit)
            outcome.accepted_patches.append(
                {"phase": "runtime", "patch_hash": patch_hash})
            outcome.raw_hashes.append(cand_hash)
            outcome.error_signatures.append(rt_sig)
            state = update_repair_state_v2(state, raw_graph_hash=raw_hash,
                                           error_sig_hash=rt_sig,
                                           patch_hash=patch_hash, stage_rank=0)
            current, vrun = candidate, cvrun
            committed = True
        # 外层 while 重入: 完整 validation → 新 canonical → runtime 重跑
