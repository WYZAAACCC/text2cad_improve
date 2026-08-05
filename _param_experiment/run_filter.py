"""论文 5 级执行过滤编排（基础设施，scan-dirs，不碰主流程/src）。

对任务目录用落盘产物判定 5 级（不重新执行）：
  L1 Schema/图结构   validation_report.ok + canonical_ir.json
  L2 参数几何预检    generate_quality_report(IR 类检查) ok
  L3 Compiler/CAD     output.step 存在
  L4 几何质量        check_solid_validity + check_degenerate_geometry ok
  L5 再生/STEP        regen_report.ok（无则 validate_slot_step_roundtrip ok）
输出 datasets/filter_report.json（每任务各级 + 保留率）。

用法:
  .conda/python.exe _param_experiment/run_filter.py
  .conda/python.exe _param_experiment/run_filter.py --only verify_br_c735fc40
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
DATASETS = _HERE / "output" / "datasets"
FILTER = DATASETS / "filter_report.json"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from mcp_tools import (  # noqa: E402
    check_degenerate_geometry, check_slot_pitch_and_ligament,
    check_solid_validity, generate_quality_report, validate_slot_pattern_periodicity,
    validate_slot_step_roundtrip,
)

# 级2 IR 类检查（不含 STEP 相关；check_slot_depth_and_rim 硬编码 x>150 跨族不可靠，排除）
L2_TOOLS = ["check_slot_pitch_and_ligament", "check_adjacent_feature_clearance",
            "validate_slot_pattern_periodicity"]


def _levels(base: Path) -> dict:
    base_s = str(base)
    l1 = l2 = l3 = l4 = l5 = None
    # L1 Schema/图结构（run_validation 结果；canonical_ir.json 为衍生产物，旧任务缺失不判失败）
    try:
        vr = json.loads((base / "validation_report.json").read_text(encoding="utf-8"))
        l1 = bool(vr.get("ok"))
    except Exception:  # noqa: BLE001
        l1 = False
    # L2 参数几何预检（IR 类）
    try:
        gr = generate_quality_report({"base_dir": base_s, "tool_subset": L2_TOOLS})
        l2 = bool(gr.get("ok"))
    except Exception:  # noqa: BLE001
        l2 = False
    # L3 Compiler/CAD 执行（step 存在）
    l3 = (base / "output.step").exists()
    # L4 几何质量（STEP 实体）
    try:
        sv = check_solid_validity({"base_dir": base_s})
        dg = check_degenerate_geometry({"base_dir": base_s})
        l4 = bool(sv.get("ok")) and bool(dg.get("ok"))
    except Exception:  # noqa: BLE001
        l4 = False
    # L5 再生/STEP（regen_report 或 STEP 回读）
    try:
        rr = json.loads((base / "regen_report.json").read_text(encoding="utf-8"))
        l5 = bool(rr.get("regenerated_ok"))
    except Exception:  # noqa: BLE001
        try:
            rt = validate_slot_step_roundtrip({"base_dir": base_s})
            l5 = bool(rt.get("ok"))
        except Exception:  # noqa: BLE001
            l5 = None
    return {"L1": l1, "L2": l2, "L3": l3, "L4": l4, "L5": l5}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="论文 5 级执行过滤编排")
    ap.add_argument("--only", default=None, help="只处理指定 task_id")
    args = ap.parse_args(argv)

    tids = ([args.only] if args.only
            else sorted(p.name for p in OUTPUT.iterdir()
                        if p.is_dir() and (p / "raw_fixed.json").exists()))
    if not tids:
        print("没有任务目录")
        return 1

    models = []
    for tid in tids:
        lv = _levels(OUTPUT / tid)
        models.append({"task_id": tid, "levels": lv})
        passed = sum(1 for k in ("L1", "L2", "L3", "L4") if lv[k] is True)
        print(f"- {tid}  {'OK ' if passed == 4 else '    '} L1={lv['L1']} L2={lv['L2']} "
              f"L3={lv['L3']} L4={lv['L4']} L5={lv['L5']}")

    n = len(models)
    retention = {}
    prev = n
    for lvl in ("L1", "L2", "L3", "L4", "L5"):
        passed = sum(1 for m in models if m["levels"][lvl] is True)
        retention[lvl] = {"passed": passed, "of_total": n,
                          "rel_initial_pct": round(passed / n * 100, 2) if n else 0,
                          "rel_prev_pct": round(passed / prev * 100, 2) if prev else 0}
        prev = passed

    report = {"schema": "filter_report_v1", "generated_at": datetime.now().isoformat(timespec="seconds"),
              "models": models, "retention": retention}
    DATASETS.mkdir(parents=True, exist_ok=True)
    FILTER.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保留率（{n} 候选）:")
    for lvl, r in retention.items():
        print(f"  {lvl}: {r['passed']}/{r['of_total']} = {r['rel_initial_pct']}% "
              f"(相对上一级 {r['rel_prev_pct']}%)")
    print(f"filter report -> {FILTER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
