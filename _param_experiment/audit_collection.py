"""数据采集正确性核查（采集基础设施，scan-dirs 只读，不碰主流程/src）。

对任务目录逐项核查：
  - S/Y 元组字段覆盖（T/Dg/Gf+CCAD/MSTEP/MBRep/Rquality/Rregen/L → 落盘文件）
  - dataset_enrich 自洽（design_id/model_id/labels.feasible 与落盘产物一致）
  - SER 七步与 IR 一致性（descriptions.json 是否存在、结构是否与 raw_fixed 匹配）
  - 隔离正确性（design_id 去重、同 design 组内 split 一致性、捆绑完整性）

输出 datasets/audit_report.json（schema audit_collection_v1）+ 控制台摘要。

用法:
  .conda/python.exe _param_experiment/audit_collection.py
  .conda/python.exe _param_experiment/audit_collection.py --only verify_br_c735fc40
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
DATASETS = _HERE / "output" / "datasets"
REPORT = DATASETS / "audit_report.json"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(_HERE))

# S/Y 元组字段 → 落盘文件名
FIELD_FILES = {
    "T": "request.json", "Dg": "raw_fixed.json", "Gf+CCAD": "canonical_ir.json",
    "MSTEP": "output.step", "MBRep": "output.brep", "Rquality": "validation_report.json",
    "Rregen": "regen_report.json", "L_log": "pipeline_log.json", "L_tools": "tool_calls.json",
    "enrich": "dataset_enrich.json", "descriptions": "descriptions.json",
}


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _audit_one(base: Path) -> dict:
    rec = {"task_id": base.name, "fields": {}, "problems": [], "design_id": None,
           "model_id": None, "valid": False}
    for fname, f in FIELD_FILES.items():
        ok = (base / f).exists()
        rec["fields"][fname] = ok
        if fname in ("T", "Dg", "MSTEP", "MBRep") and not ok:
            rec["problems"].append(f"缺 {fname}（{f}）")
    # enrich 自洽
    en = _read_json(base / "dataset_enrich.json")
    if en:
        rec["design_id"] = en.get("design_id")
        rec["model_id"] = en.get("model_id")
        ir_hash = en.get("ir_doc_hash")
        # model_id 一致性仅对非继承任务检查（gen 变体经 source_ref 继承源 model_id 是设计使然）
        has_src = (base / "source_ref.json").exists()
        if not has_src and en.get("model_id") and ir_hash \
                and not str(en["model_id"]).startswith(str(ir_hash)[:12]):
            rec["problems"].append("model_id 与 ir_doc_hash 不一致")
        labels = en.get("labels") or {}
        rec["valid"] = bool(labels.get("feasible"))
        step_ok = (base / "output.step").exists()
        if labels.get("feasible") is True and not step_ok:
            rec["problems"].append("labels.feasible=True 但无 output.step")
        if not en.get("design_id"):
            rec["problems"].append("dataset_enrich.design_id 缺失")
    elif not (base / "request.json").exists():
        rec["problems"].append("非任务目录（无 request/enrich）")
    else:
        rec["problems"].append("dataset_enrich.json 缺失（未入库）")
    # SER 一致性（descriptions 存在 + 七步结构）
    desc = _read_json(base / "descriptions.json")
    if desc:
        ser = desc.get("ser")
        steps = [k for k in (ser or {}).keys() if k.startswith("step")]
        if len(steps) != 7:
            rec["problems"].append(f"SER 步数 {len(steps)} != 7")
    # validation 判定
    vr = _read_json(base / "validation_report.json")
    if vr and not vr.get("ok"):
        rec["problems"].append(f"validation 未过: {str(vr.get('issues'))[:120]}")
    return rec


def _audit_isolation(recs: list) -> dict:
    """按 design_id 分组核查：跨 split 冲突（捆绑违规）、重复设计。"""
    groups = defaultdict(lambda: {"tasks": [], "splits": set(), "families": set()})
    for r in recs:
        if r["design_id"]:
            g = groups[r["design_id"]]
            g["tasks"].append(r["task_id"])
            g["splits"].update({r.get("split") or "unknown"})
    violations = []
    for did, g in groups.items():
        if len(g["splits"]) > 1:
            violations.append({"design_id": did, "tasks": g["tasks"],
                               "splits": sorted(g["splits"])})
    dup_designs = {did for did, g in groups.items() if len(g["tasks"]) > 1}
    return {"design_groups": len(groups),
            "bundled_groups": len(dup_designs),
            "cross_split_violations": violations,
            "dup_design_ids": sorted(dup_designs)[:50]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="数据采集正确性核查")
    ap.add_argument("--only", default=None, help="只核查指定 task_id")
    args = ap.parse_args(argv)

    if args.only:
        dirs = [Path(args.only)]
    else:
        dirs = sorted(p for p in OUTPUT.iterdir() if p.is_dir() and (p / "raw_fixed.json").exists())
    if not dirs:
        print("没有任务目录")
        return 1

    # split 依据 family_split.json（design_family_id → train/val/holdout），
    # 而非 family_ref.json（mon_sweep 等早期任务无 family_ref，但 design_family_id 由 run_enrich 标注）
    fs_path = _HERE / "family_split.json"
    fs = {}
    if fs_path.exists():
        fs = (json.loads(fs_path.read_text(encoding="utf-8")).get("family_split") or {})
    recs = []
    for d in dirs:
        rec = _audit_one(d)
        en = _read_json(d / "dataset_enrich.json")
        fam_id = (en or {}).get("design_family_id")
        rec["family"] = fam_id
        rec["split"] = fs.get(fam_id) if fam_id else None
        fam_ref = _read_json(d / "family_ref.json")
        if fam_ref and not rec["split"]:
            rec["split"] = fam_ref.get("split")
        recs.append(rec)

    # 字段覆盖汇总
    field_stats = {f: sum(1 for r in recs if r["fields"].get(f)) for f in FIELD_FILES}
    # 隔离
    iso = _audit_isolation(recs)
    # labels 判定 vs filter 有效
    n_valid = sum(1 for r in recs if r["valid"])
    n_problems = sum(len(r["problems"]) for r in recs)

    report = {
        "schema": "audit_collection_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_tasks": len(recs),
        "valid_by_enrich": n_valid,
        "field_coverage": field_stats,
        "problem_count": n_problems,
        "isolation": iso,
        "records": recs,
    }
    DATASETS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"数据采集核查 -> {REPORT}")
    print(f"  任务数: {len(recs)}  有效(labels.feasible): {n_valid}  问题数: {n_problems}")
    print(f"  字段覆盖:")
    for f, c in field_stats.items():
        mark = "OK " if c == len(recs) else ("-- " if c == 0 else "part")
        print(f"    [{mark}] {f:12s} {c}/{len(recs)}")
    print(f"  隔离: design 组 {iso['design_groups']}  重复组 {iso['bundled_groups']}  "
          f"跨 split 违规 {len(iso['cross_split_violations'])}")
    for r in recs:
        if r["problems"]:
            print(f"  ! {r['task_id']}: {'; '.join(r['problems'][:3])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
