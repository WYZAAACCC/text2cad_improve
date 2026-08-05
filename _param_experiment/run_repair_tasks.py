"""Repair 任务样本构造器（真实 attempt 提取 + 受控错误注入，不碰主流程/src）。

来源 A 真实 attempt：扫描任务 repair/{validation,runtime}/attempt_NN，用 reverse patch
（apply_repair_patch_v2）从 candidate_raw 反解错误 IR。
来源 B 受控注入：fillet radius=0 / op_version 错 / llm_validation_hints=null，
run_validation 验证错误码 → repair_documents 确定性修复。
样本（wrong_ir/right_ir 内联）落盘 _param_experiment/output/datasets/repair_tasks/。

用法:
  .conda/python.exe _param_experiment/run_repair_tasks.py --only mon_sweep_g5_3tooth_depth
  .conda/python.exe _param_experiment/run_repair_tasks.py --inject-only --limit 5
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
DATASETS = _HERE / "output" / "datasets" / "repair_tasks"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from seekflow_engineering_tools.generative_cad.repair.patch import (  # noqa: E402
    RepairPatchV2, apply_repair_patch_v2,
)
from seekflow_engineering_tools.generative_cad.repair_kernel.engine import repair_documents  # noqa: E402
from seekflow_engineering_tools.generative_cad.validation_kernel.executor import run_validation  # noqa: E402


def _inherit(tid: str) -> dict:
    try:
        d = json.loads((OUTPUT / tid / "dataset_enrich.json").read_text(encoding="utf-8"))
        return {"design_id": d.get("design_id"), "model_id": d.get("model_id")}
    except Exception:  # noqa: BLE001
        return {"design_id": None, "model_id": None}


# ── 来源 A：真实 attempt 反解 ───────────────────────────────────────────
def _infer_rule_id(patch: dict) -> str:
    reason = " ".join(c.get("reason", "") for c in patch.get("changes", []))
    rl = reason.lower()
    if "brep_api" in rl or "command not done" in rl or "fillet" in rl and "radius" in rl:
        return "runtime_geometry_inferred"
    if "pydantic" in rl or "validation" in rl or "null" in rl:
        return "validation_schema_inferred"
    return "repair_inferred"


def _extract_real_attempts(tid: str) -> list:
    samples = []
    base = OUTPUT / tid
    inh = _inherit(tid)
    repair_root = base / "repair"
    if not repair_root.exists():
        return samples
    for phase_dir in sorted(repair_root.iterdir()):
        if not phase_dir.is_dir():
            continue
        for attempt_dir in sorted(phase_dir.glob("attempt_*")):
            patch_path = attempt_dir / "patch.json"
            cand_path = attempt_dir / "candidate_raw.json"
            if not (patch_path.exists() and cand_path.exists()):
                continue
            try:
                patch = json.loads(patch_path.read_text(encoding="utf-8"))
                candidate = json.loads(cand_path.read_text(encoding="utf-8"))
                if not patch.get("changes"):
                    continue
                reverse = RepairPatchV2(
                    target_node=patch.get("target_node"),
                    target_component=patch.get("target_component"),
                    changes=[{"path": c["path"], "old_value": c.get("new_value"),
                              "new_value": c.get("old_value"),
                              "reason": c.get("reason", "reverse")}
                             for c in patch["changes"]],
                    reason="reverse of real attempt", give_up=False)
                wrong_ir = apply_repair_patch_v2(copy.deepcopy(candidate), reverse)
            except Exception as exc:  # noqa: BLE001
                print(f"    [skip] {tid}/{phase_dir.name}/{attempt_dir.name}: {exc}")
                continue
            sample_id = f"{tid}_{phase_dir.name}_{attempt_dir.name}"
            samples.append({
                "task_type": "repair", "sample_id": sample_id, "source_task_id": tid,
                "design_id": inh["design_id"], "model_id": inh["model_id"],
                "error_source": "real_llm_attempt", "phase": phase_dir.name,
                "rule_id": _infer_rule_id(patch), "rule_id_source": "inferred",
                "wrong_ir": wrong_ir, "right_ir": candidate, "patch": patch,
                "repair_ok": True,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            })
    return samples


# ── 来源 B：受控注入 ────────────────────────────────────────────────────
def _inject_fillet_zero(ir: dict):
    for n in ir.get("nodes", []):
        if n.get("op") == "fillet_sketch" and isinstance(n.get("params"), dict):
            if isinstance(n["params"].get("radius_mm"), (int, float)):
                n["params"]["radius_mm"] = 0.0
                return
    return


def _inject_bad_op_version(ir: dict):
    # 0.1.0（合法格式但非当前方言版本）→ unknown_op，且能被确定性链修复（9.9.9 不可修复）
    for n in ir.get("nodes", []):
        if "op_version" in n:
            n["op_version"] = "0.1.0"
            return
    return


def _inject_hints_null(ir: dict):
    ir["llm_validation_hints"] = None


def _inject_pitch_ligament(ir: dict):
    # 使 pitch=2πr/N < 槽宽 → 最小剩料 ≤0（类⑤，MCP check_slot_pitch_and_ligament 检测）
    for n in ir.get("nodes", []):
        if n.get("op") == "circular_pattern_component":
            n["params"]["count"] = 240
            return


def _inject_bool_fillet(ir: dict):
    # 使 fillet 半径远超邻边 → runtime BRep_API（类⑥；检测在 runtime 层，repair 在验证层不触发）
    for n in ir.get("nodes", []):
        if n.get("op") == "fillet_sketch" and isinstance(n.get("params"), dict):
            if isinstance(n["params"].get("radius_mm"), (int, float)):
                n["params"]["radius_mm"] = 30.0
                return


INJECTIONS = [
    # (id, rule_id, check 层, apply)
    ("fillet_zero", "fix_fillet_zero_radius", "validation", _inject_fillet_zero),
    ("op_version", "fix_op_versions", "validation", _inject_bad_op_version),
    ("hints_null", "fix_null_hints", "validation", _inject_hints_null),
    ("pitch_ligament", "slot_pitch_ligament", "mcp", _inject_pitch_ligament),
    ("bool_fillet", "boolean_runtime_geometry", "runtime", _inject_bool_fillet),
]


def _inject_samples(tid: str) -> list:
    samples = []
    base = OUTPUT / tid
    inh = _inherit(tid)
    raw = json.loads((base / "raw_fixed.json").read_text(encoding="utf-8"))
    for inj_id, rule_id, check, apply in INJECTIONS:
        wrong = copy.deepcopy(raw)
        apply(wrong)
        try:
            vrun = run_validation(wrong)
            err_codes = [i.code for i in vrun.report.issues if i.severity == "error"]
            mcp_failed = []
            runtime_failed = None
            if check == "mcp":
                from mcp_tools import generate_quality_report
                tmp = base / f"_inj_{inj_id}"
                tmp.mkdir(parents=True, exist_ok=True)
                (tmp / "raw_fixed.json").write_text(
                    json.dumps(wrong, ensure_ascii=False), encoding="utf-8")
                gr = generate_quality_report({"base_dir": str(tmp),
                                              "tool_subset": ["check_slot_pitch_and_ligament"]})
                mcp_failed = gr.get("failed_checks", [])
            elif check == "runtime":
                # runtime 布尔/几何错误：验证层不检测，记录注入目标（确定性复现需 run_gcad_core，本轮不做）
                runtime_failed = f"injected fillet radius 30mm (expect BRep_API at runtime)"
            res = repair_documents(wrong, vrun)
            right = res.document
            repair_ok = bool(res.outcome.final_ok)
        except Exception as exc:  # noqa: BLE001
            print(f"    [skip] {tid}/{inj_id}: {exc}")
            continue
        sample_id = f"{tid}_inject_{inj_id}"
        samples.append({
            "task_type": "repair", "sample_id": sample_id, "source_task_id": tid,
            "design_id": inh["design_id"], "model_id": inh["model_id"],
            "error_source": "controlled_injection", "phase": None,
            "rule_id": rule_id, "rule_id_source": "known",
            "wrong_ir": wrong, "right_ir": right,
            "validation_error_codes": err_codes, "mcp_failed_checks": mcp_failed,
            "runtime_failed": runtime_failed, "repair_ok": repair_ok,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
    return samples


def _save(samples: list):
    DATASETS.mkdir(parents=True, exist_ok=True)
    for s in samples:
        (DATASETS / f"{s['sample_id']}.json").write_text(
            json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Repair 任务样本构造器（真实提取 + 受控注入）")
    ap.add_argument("--only", default=None, help="只处理指定 task_id")
    ap.add_argument("--inject-only", action="store_true", help="只做受控注入（跳过真实 attempt）")
    ap.add_argument("--limit", type=int, default=None, help="最多处理前 N 个任务")
    args = ap.parse_args(argv)

    if args.only:
        tasks = [args.only]
    else:
        tasks = sorted(p.name for p in OUTPUT.iterdir()
                       if p.is_dir() and (p / "raw_fixed.json").exists())
    if args.limit:
        tasks = tasks[:args.limit]
    if not tasks:
        print("没有任务目录")
        return 1

    total = 0
    for tid in tasks:
        try:
            ss = []
            if not args.inject_only:
                ss += _extract_real_attempts(tid)
            ss += _inject_samples(tid)
            _save(ss)
            total += len(ss)
            print(f"- {tid}  {len(ss)} samples")
        except Exception as exc:  # noqa: BLE001
            print(f"- {tid}  FAIL  {exc}")
    print(f"DONE  {total} repair samples -> {DATASETS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
