"""Experiment pipeline executor that stays isolated from the server entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapters import build_template_document, call_mcp_tool
from .config import ExperimentConfig
from .llm import BenchLlmClient, LlmCallError, OpenAICompatToolClient
from .paths import run_dir
from .schemas import MethodSpec, RunResult, RunStatus, TaskSpec
from .utils import atomic_write_json, utc_now_iso

CORE_MCP_SUBSET = [
    "check_solid_validity",
    "check_degenerate_geometry",
    "validate_slot_step_roundtrip",
    "check_slot_pitch_and_ligament",
    "check_adjacent_feature_clearance",
    "validate_slot_pattern_periodicity",
]


class BenchLlmCaller:
    """Adapts BenchLlmClient to the repair-kernel LlmToolCaller protocol."""

    def __init__(self, client: BenchLlmClient, config, usage: dict[str, int]):
        self.client = client
        self.config = config
        self.usage = usage

    def call_strict_tool(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        model_config: Any = None,
    ):
        result = self.client.call_strict_tool(
            messages=messages,
            tool_name=tool_name,
            tool_description=tool_description,
            tool_schema=tool_schema,
            config=self.config,
        )
        if result.usage is not None:
            self.usage["prompt_tokens"] += result.usage.prompt_tokens
            self.usage["completion_tokens"] += result.usage.completion_tokens
            self.usage["total_tokens"] += result.usage.total_tokens
        return result

    def call_with_tools(self):
        """Marker so agentic_l2 enables its tool-loop path with this caller."""
        return None


def _run_agentic_l2(task_spec, llm_cfg, caller, run_path, usage=None):
    import sys
    from pathlib import Path as _P
    server = _P(__file__).resolve().parents[1] / "app" / "text-to-cad" / "server"
    param_experiment = _P(__file__).resolve().parents[1] / "_param_experiment"
    if str(server) not in sys.path:
        sys.path.insert(0, str(server))
    if str(param_experiment) not in sys.path:
        sys.path.insert(0, str(param_experiment))
    from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
    import agentic_l2
    llm_cfg = LlmModelConfig(
        model=llm_cfg.model,
        base_url=llm_cfg.base_url,
        timeout_s=llm_cfg.timeout_s,
        temperature=llm_cfg.temperature if llm_cfg.temperature is not None else 0.3,
        seed=llm_cfg.seed,
        api_key_env=llm_cfg.api_key_env,
        thinking=llm_cfg.thinking,
    )
    params = task_spec.normalized_params or {}
    explicit = []
    if params.get("form"):
        explicit.append(f"盘体形态={params['form']}")
    if params.get("category") == "complex_rim":
        if params.get("transition"):
            explicit.append(f"轮缘过渡类型={params['transition']}")
        if params.get("rim_arc_radius_mm") is not None:
            explicit.append(f"轮缘过渡幅度={params['rim_arc_radius_mm']}mm")
    if params.get("hub_radial_height_mm") is not None:
        explicit.append(f"hub径向高度={params['hub_radial_height_mm']}mm")
    if params.get("web_radial_length_mm") is not None:
        explicit.append(f"web径向长度={params['web_radial_length_mm']}mm")
    if params.get("cl_holes"):
        explicit.append(
            f"每道冷却孔数量必须严格等于 {params['cl_holes']}（两道共 {params['cl_holes'] * 2}，"
            f"禁止取半或按其它规则改），孔径={params.get('cl_hdia_mm')}mm，"
            f"第一道分布半径={params.get('cl_pcd_mm')}mm，第二道分布半径={params.get('cl_pcd2_mm')}mm"
        )
    if params.get("lh_holes"):
        explicit.append(
            f"减重孔数量={params['lh_holes']}，孔径={params.get('lh_hdia_mm')}mm，"
            f"分布半径={params.get('lh_pcd_mm')}mm"
        )
    if params.get("hdia_mm"):
        explicit.append(
            f"安装孔孔径={params['hdia_mm']}mm，数量={params.get('pcd_count') or params.get('holes')}，"
            f"分布半径={params.get('pcd_mm')}mm"
        )
    if params.get("grooves"):
        explicit.append(
            f"环槽数量={params['grooves']}，槽宽={params.get('gw_mm')}mm，"
            f"槽深={params.get('gd_mm')}mm"
        )
    if params.get("slots"):
        explicit.append(
            f"榫槽 cutter 拉伸深度={params.get('axial_depth_mm', 80.0)}mm"
            f"（direction=both，切透轮缘即可，禁止用轴向最大厚度代替）"
        )
    if params.get("fr_mm") is not None:
        explicit.append(
            f"榫槽圆角比例 fr_mm={params['fr_mm']}"
            f"（fillet 半径 = 分组系数 × 喉部半宽 × fr_mm）"
        )
    prompt = task_spec.prompt
    if explicit:
        prompt = prompt.rstrip() + "\n\n显式设计参数（必须严格采用）：" + "；".join(explicit)
    raw = agentic_l2.run_agentic_l2(
        prompt, None, caller=caller,
        llm_model_config=llm_cfg, out_dir=run_path, usage=usage,
        explicit_req={"fr_mm": params.get("fr_mm")},
    )
    return raw


def _repair_config_from_flags(method_spec: MethodSpec):
    """Build RepairLoopConfig from method flags (ablation switches)."""
    from seekflow_engineering_tools.generative_cad.repair_kernel.config import (
        RepairLoopConfig,
    )

    flags = method_spec.flags or {}
    max_repairs = max(0, method_spec.runner.max_repair_attempts)
    enabled = bool(flags.get("repair_enabled", True))
    autofix = bool(flags.get("deterministic_autofix_enabled", True))
    return RepairLoopConfig(
        enabled=enabled,
        validation_repair_enabled=enabled,
        runtime_repair_enabled=enabled,
        deterministic_autofix_enabled=autofix,
        max_validation_llm_attempts=max_repairs,
        max_runtime_llm_attempts=max(1, max_repairs - 1),
        max_total_llm_attempts=max_repairs,
    )


def _write_json(path: Path, value: Any) -> None:
    atomic_write_json(path, value)


def _run_level1(
    caller: BenchLlmCaller,
    task_spec: TaskSpec,
    method_spec: MethodSpec,
) -> dict[str, Any]:
    from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
        build_level1_routing_prompt,
        build_level1_tool,
    )
    from seekflow_engineering_tools.generative_cad.dialects.registry import (
        export_dialect_catalog,
    )

    prompt = build_level1_routing_prompt(
        user_request=task_spec.prompt,
        dialect_catalog=export_dialect_catalog(),
    )
    tool = build_level1_tool()
    result = caller.call_strict_tool(
        messages=[
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": prompt["user"]},
        ],
        tool_name=tool["function"]["name"],
        tool_description=tool["function"]["description"],
        tool_schema=tool["function"]["parameters"],
    )
    args = dict(result.arguments)
    if method_spec.flags.get("force_generative", True):
        args["route_decision"] = "generative_cad_ir"
    return args


def _self_correction_prompt(
    task_spec: TaskSpec,
    previous_raw: dict[str, Any],
    parse_errors: str,
) -> str:
    return (
        f"你的上一份 RawGcadDocument 存在解析错误。\n"
        f"用户需求：{task_spec.prompt}\n"
        f"解析错误：{parse_errors}\n"
        f"上一份输出（截断）：{json.dumps(previous_raw, ensure_ascii=False)[:4000]}\n"
        "请修复错误并输出完整、可解析的 RawGcadDocument JSON。"
    )


def _run_level2(
    caller: BenchLlmCaller,
    task_spec: TaskSpec,
    route_args: dict[str, Any],
    method_spec: MethodSpec,
) -> tuple[dict[str, Any], int]:
    from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
        build_level2_authoring_prompt,
        build_level2_tool,
    )
    from seekflow_engineering_tools.generative_cad.skills.schemas import (
        DialectSelectionPlan,
    )
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )
    from seekflow_engineering_tools.generative_cad.ir.parse import (
        parse_raw_gcad_document,
    )

    plan = DialectSelectionPlan.model_validate(route_args)
    registry = default_registry()
    contracts = {}
    for item in plan.selected_dialects:
        dialect = registry.get(item.dialect)
        if dialect is not None:
            contracts[item.dialect] = dialect.contract()

    prompt = build_level2_authoring_prompt(
        user_request=task_spec.prompt,
        selection_plan=plan,
        contracts=contracts,
    )
    tool = build_level2_tool(contracts=contracts)
    max_self_correct = max(0, method_spec.runner.max_repair_attempts)

    for attempt in range(max_self_correct + 1):
        user_message = prompt["user"] if attempt == 0 else _self_correction_prompt(
            task_spec,
            previous_raw,
            last_error,
        )
        result = caller.call_strict_tool(
            messages=[
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": user_message},
            ],
            tool_name=tool["function"]["name"],
            tool_description=tool["function"]["description"],
            tool_schema=tool["function"]["parameters"],
        )
        raw = dict(result.arguments)
        parse = parse_raw_gcad_document(raw)
        if parse.ok:
            return raw, attempt + 1
        previous_raw = raw
        last_error = "; ".join(
            f"[{i.code}] {i.message}" for i in parse.issues
        )

    raise RuntimeError("RawGcadDocument parse failed after self-correction")


def _run_with_repair(
    raw: dict[str, Any],
    *,
    task_spec: TaskSpec,
    method_spec: MethodSpec,
    run_path: Path,
    caller: BenchLlmCaller,
    llm_config,
    repair_config=None,
) -> Any:
    from seekflow_engineering_tools.generative_cad.repair_kernel.config import (
        RepairLoopConfig,
    )
    from seekflow_engineering_tools.generative_cad.repair_kernel.orchestrator import (
        run_generation_loop,
    )
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )

    cfg = repair_config or _repair_config_from_flags(method_spec)
    return run_generation_loop(
        raw,
        out_step=run_path / "output.step",
        metadata_path=run_path / "output.metadata.json",
        dialect_registry=default_registry(),
        config=cfg,
        validation_repair_caller=caller,
        runtime_repair_caller=caller,
        llm_model_config=llm_config,
        audit_dir=run_path,
        user_request=task_spec.prompt,
    )


OUTER_FEEDBACK_SYSTEM_PROMPT = """你是 CAD 工程验证修复智能体。
当前 CAD 建模规范已通过建模规范校验并成功执行生成实体，但独立工程验证工具发现质量问题。
你必须基于工程验证失败详情输出一个最小修复补丁（RepairPatchV2）：
- 只修改与失败检查直接相关的节点字段及其必要依赖；
- 禁止修改 required / degradation_policy 来掩盖失败；
- 若无法定位或无法修复，明确 give_up=true，不得提交无意义补丁。
"""


def _build_outer_feedback_user_prompt(
    task_spec: TaskSpec,
    document: dict[str, Any],
    gate: dict[str, Any],
) -> str:
    payload = {
        "user_request": task_spec.prompt,
        "failed_checks": gate.get("summary", {}).get("failed_checks", []),
        "details": gate.get("details", {}),
        "current_document": document,
    }
    return json.dumps(payload, ensure_ascii=False)[:9000]


def _run_outer_feedback_loop(
    *,
    raw_document: dict[str, Any],
    current_loop,
    task_spec: TaskSpec,
    method_spec: MethodSpec,
    run_path: Path,
    caller: BenchLlmCaller,
    llm_config,
) -> tuple[Any, dict[str, Any], int]:
    """Outer engineering-verification feedback repair (full framework only)."""
    from seekflow_engineering_tools.generative_cad.authoring.tool_schemas import (
        build_repair_patch_tool_schema,
    )
    from seekflow_engineering_tools.generative_cad.repair.patch import (
        apply_repair_patch_v2,
    )
    from seekflow_engineering_tools.generative_cad.repair_kernel.config import (
        RepairLoopConfig,
    )
    from seekflow_engineering_tools.generative_cad.repair.patch import (
        RepairPatchV2,
    )
    from seekflow_engineering_tools.generative_cad.repair_kernel.orchestrator import (
        run_generation_loop,
    )
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )

    max_total = max(0, method_spec.runner.max_repair_attempts)
    outcome = getattr(current_loop, "outcome", None)
    inner_used = 0
    if outcome is not None:
        inner_used = (getattr(outcome, "validation_llm_attempts", 0)
                      + getattr(outcome, "runtime_llm_attempts", 0))
    remaining = max(0, max_total - inner_used)
    document = dict(raw_document)
    gate = run_mcp_quality_gate(run_path)
    loop = current_loop
    outer_attempts = 0
    _write_json(run_path / "outer_feedback_start.json", {
        "gate_before": {
            "ok": gate["summary"]["ok"],
            "failed_checks": gate["summary"].get("failed_checks", []),
            "details": gate.get("details", {}),
        },
        "inner_llm_attempts": inner_used,
        "remaining_budget": remaining,
    })
    while not gate["summary"]["ok"] and remaining > 0:
        attempt_marker = outer_attempts + 1
        try:
            patch_result = caller.call_strict_tool(
                messages=[
                    {"role": "system", "content": OUTER_FEEDBACK_SYSTEM_PROMPT},
                    {"role": "user", "content": _build_outer_feedback_user_prompt(
                        task_spec, document, gate)},
                ],
                tool_name="emit_repair_patch",
                tool_description="输出基于工程验证反馈的修复补丁",
                tool_schema=build_repair_patch_tool_schema(),
                model_config=llm_config,
            )
            patch = RepairPatchV2.model_validate(patch_result.arguments)
        except Exception as exc:  # noqa: BLE001
            _write_json(run_path / f"outer_feedback_attempt_{attempt_marker:02d}.json", {
                "ok": False,
                "error": str(exc)[:500],
            })
            break
        _write_json(run_path / f"outer_feedback_attempt_{attempt_marker:02d}.json", {
            "ok": not patch.give_up,
            "give_up": patch.give_up,
            "change_count": len(patch.changes),
            "patch": patch.model_dump(mode="json"),
        })
        if patch.give_up or not patch.changes:
            break
        try:
            document = apply_repair_patch_v2(document, patch)
        except Exception:
            break
        outer_attempts += 1
        remaining -= 1
        _write_json(run_path / f"outer_repair_attempt_{outer_attempts:02d}.json", {
            "patch": patch.model_dump(mode="json"),
            "gate_before": {
                "ok": gate["summary"]["ok"],
                "failed_checks": gate["summary"].get("failed_checks", []),
            },
        })
        cfg = RepairLoopConfig(
            enabled=True,
            validation_repair_enabled=True,
            runtime_repair_enabled=True,
            deterministic_autofix_enabled=True,
            max_validation_llm_attempts=remaining,
            max_runtime_llm_attempts=remaining,
            max_total_llm_attempts=remaining,
        )
        loop = run_generation_loop(
            document,
            out_step=run_path / "output.step",
            metadata_path=run_path / "output.metadata.json",
            dialect_registry=default_registry(),
            config=cfg,
            validation_repair_caller=caller,
            runtime_repair_caller=caller,
            llm_model_config=llm_config,
            audit_dir=run_path,
            user_request=task_spec.prompt,
        )
        if loop.document:
            document = loop.document
        gate = run_mcp_quality_gate(run_path)
        if loop.outcome is not None:
            consumed = (getattr(loop.outcome, "validation_llm_attempts", 0)
                        + getattr(loop.outcome, "runtime_llm_attempts", 0))
            remaining = max(0, remaining - consumed)
    return loop, gate, outer_attempts


def run_mcp_quality_gate(run_path: Path) -> dict[str, Any]:
    try:
        report = call_mcp_tool("generate_quality_report", {
            "base_dir": str(run_path),
            "tool_subset": CORE_MCP_SUBSET,
        })
        summary = {
            "ok": bool(report.get("ok")),
            "passed_checks": report.get("passed_checks", []),
            "failed_checks": report.get("failed_checks", []),
            "measurements": report.get("measurements", []),
            "ran_checks": len(report.get("passed_checks", [])) + len(report.get("failed_checks", [])),
        }
        return {**report, "summary": summary}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "passed_checks": [],
            "failed_checks": [],
            "measurements": [],
            "ran_checks": 0,
            "error": str(exc),
            "summary": {"ok": False, "passed_checks": [], "failed_checks": [], "ran_checks": 0},
        }


def run_experiment_task(
    task_spec: TaskSpec,
    method_spec: MethodSpec,
    seed: int,
    config: ExperimentConfig,
    client: BenchLlmClient | None = None,
) -> RunResult:
    run_path = run_dir(method_spec.method_id, task_spec.task_id, seed, config=config)
    run_path.mkdir(parents=True, exist_ok=True)
    run_id = f"{method_spec.method_id}__{task_spec.task_id}__seed{seed}"
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    result = RunResult(
        run_id=run_id,
        method_id=method_spec.method_id,
        task_id=task_spec.task_id,
        seed=seed,
        started_at=utc_now_iso(),
    )
    llm_cfg = method_spec.llm.model_copy(update={"seed": seed})
    caller = BenchLlmCaller(client or OpenAICompatToolClient(), llm_cfg, usage)

    try:
        if method_spec.flags.get("template"):
            raw = build_template_document(task_spec.normalized_params)
            result.attempts_used = 1
            _write_json(run_path / "llm_raw.json", raw)
            loop = _run_with_repair(
                raw,
                task_spec=task_spec,
                method_spec=method_spec,
                run_path=run_path,
                caller=caller,
                llm_config=llm_cfg,
            )
        elif method_spec.flags.get("agentic"):
            route_args = _run_level1(caller, task_spec, method_spec)
            _write_json(run_path / "route_plan.json", route_args)
            raw = _run_agentic_l2(task_spec, llm_cfg, caller, run_path, usage)
            result.attempts_used = 1
            _write_json(run_path / "llm_raw.json", raw)
            from seekflow_engineering_tools.generative_cad.validation_kernel import (
                run_validation,
            )
            initial_run = run_validation(raw)
            _write_json(run_path / "validation_initial.json", {
                "ok": bool(initial_run.report.ok),
                "stage": initial_run.report.stage,
                "issues": [i.model_dump(mode="json") for i in initial_run.report.issues],
            })
            loop = _run_with_repair(
                raw,
                task_spec=task_spec,
                method_spec=method_spec,
                run_path=run_path,
                caller=caller,
                llm_config=llm_cfg,
            )
        else:
            route_args = _run_level1(caller, task_spec, method_spec)
            _write_json(run_path / "route_plan.json", route_args)
            if route_args.get("route_decision") == "unsupported":
                raise RuntimeError("L1 route returned unsupported")
            raw, attempts = _run_level2(caller, task_spec, route_args, method_spec)
            result.attempts_used = attempts
            _write_json(run_path / "llm_raw.json", raw)

            from seekflow_engineering_tools.generative_cad.validation_kernel import (
                run_validation,
            )
            initial_run = run_validation(raw)
            _write_json(run_path / "validation_initial.json", {
                "ok": bool(initial_run.report.ok),
                "stage": initial_run.report.stage,
                "issues": [i.model_dump(mode="json") for i in initial_run.report.issues],
            })
            loop = _run_with_repair(
                raw,
                task_spec=task_spec,
                method_spec=method_spec,
                run_path=run_path,
                caller=caller,
                llm_config=llm_cfg,
            )

        result.repair_rounds = loop.repair_outcome.attempts if loop.repair_outcome else 0
        result.ok = bool(loop.outcome.ok) and bool(
            loop.run_result is not None and loop.run_result.ok
        )
        if not result.ok:
            result.error_stage = "runtime" if loop.run_result is not None and not loop.run_result.ok else "validation"
            result.error_code = getattr(loop.run_result, "error", "") or loop.outcome.stop_reason
            result.error_message = getattr(loop.run_result, "error", "") or loop.outcome.stop_reason

        if loop.document:
            _write_json(run_path / "raw_fixed.json", loop.document)
        if getattr(loop.vrun, "canonical", None) is not None:
            run_path.joinpath("canonical_ir.json").write_text(
                loop.vrun.canonical.model_dump_json(indent=2),
                encoding="utf-8",
            )

        gate = run_mcp_quality_gate(run_path)
        outer_attempts = 0
        if (method_spec.flags.get("outer_feedback_repair")
                and result.ok and not gate["summary"]["ok"]):
            loop, gate, outer_attempts = _run_outer_feedback_loop(
                raw_document=loop.document if loop.document else raw,
                current_loop=loop,
                task_spec=task_spec,
                method_spec=method_spec,
                run_path=run_path,
                caller=caller,
                llm_config=llm_cfg,
            )
            if loop.document:
                _write_json(run_path / "raw_fixed.json", loop.document)
            result.repair_rounds = (loop.repair_outcome.attempts
                                    if loop.repair_outcome else 0) + outer_attempts
        _write_json(run_path / "mcp_gate.json", gate)
        result.ok = bool(loop.outcome.ok) and bool(
            loop.run_result is not None and loop.run_result.ok
        ) and bool(gate["summary"]["ok"])
        if not result.ok:
            if not gate["summary"]["ok"]:
                result.error_stage = "mcp_gate"
                result.error_code = ", ".join(gate["summary"]["failed_checks"])
                result.error_message = result.error_code or "MCP quality gate failed"
            else:
                result.error_stage = ("runtime" if loop.run_result is not None
                                      and not loop.run_result.ok else "validation")
                result.error_code = getattr(loop.run_result, "error", "") or loop.outcome.stop_reason
                result.error_message = result.error_code or loop.outcome.stop_reason

        result.status = RunStatus.COMPLETED
        result.outputs = {
            "step": str(run_path / "output.step"),
            "metadata": str(run_path / "output.metadata.json"),
            "raw_fixed": str(run_path / "raw_fixed.json"),
            "canonical_ir": str(run_path / "canonical_ir.json"),
            "mcp_gate": str(run_path / "mcp_gate.json"),
            "repair_summary": str(run_path / "repair_summary.json"),
        }
        _write_json(run_path / "pipeline_log.json", {
            "run_id": run_id,
            "ok": result.ok,
            "task_id": task_spec.task_id,
            "seed": seed,
            "attempts_used": result.attempts_used,
            "repair_rounds": result.repair_rounds,
            "usage": usage,
            "mcp_gate_ok": gate["summary"]["ok"],
            "outer_repair_attempts": outer_attempts,
        })
    except LlmCallError as exc:
        result.status = RunStatus.FAILED
        result.error_stage = "llm"
        result.error_code = exc.code
        result.error_message = str(exc)
    except Exception as exc:  # noqa: BLE001
        result.status = RunStatus.FAILED
        result.ok = False
        result.error_stage = "pipeline"
        result.error_code = type(exc).__name__
        result.error_message = str(exc)[:2000]

    result.usage = usage
    result.finished_at = utc_now_iso()
    _write_json(run_path / "run.json", result.model_dump(mode="json"))
    return result
