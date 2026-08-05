"""数据集索引 + 同模型捆绑验证（基础设施，scan-dirs 模式，不碰主流程/src）。

扫描全部任务目录，聚合字段齐全性、有效模型标记、design 关联与四类任务样本，
输出 _param_experiment/output/datasets/index.json（数据集构建的清单/组织基础）。

用法:
  .conda/python.exe _param_experiment/run_index.py
  .conda/python.exe _param_experiment/run_index.py --only verify_br_c735fc40
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
DATASETS = _HERE / "output" / "datasets"
INDEX = DATASETS / "index.json"

ARTIFACTS = ["request.json", "canonical_ir.json", "raw_fixed.json", "output.step",
             "validation_report.json", "dataset_enrich.json", "descriptions.json",
             "regen_report.json", "pipeline_log.json", "tool_calls.json"]


def _task_sample_count(typ: str, tid: str) -> int:
    d = DATASETS / f"{typ}_tasks"
    if not d.exists():
        return 0
    return sum(1 for f in d.glob("*.json")
               if json.loads(f.read_text(encoding="utf-8")).get("source_task_id") == tid)


def _valid(base: Path) -> tuple[bool, dict]:
    step = (base / "output.step").exists()
    val = False
    gate = False
    try:
        vr = json.loads((base / "validation_report.json").read_text(encoding="utf-8"))
        val = bool(vr.get("ok"))
    except Exception:  # noqa: BLE001
        pass
    try:
        meta = json.loads((base / "output.metadata.json").read_text(encoding="utf-8"))
        gate = bool(((meta.get("validation") or {}).get("inspection_validation") or {}).get("ok"))
    except Exception:  # noqa: BLE001
        pass
    return step and val and gate, {"step": step, "validation_ok": val, "mcp_gate_ok": gate}


def run_one(tid: str) -> dict | None:
    base = OUTPUT / tid
    if not (base / "raw_fixed.json").exists():
        return None
    en = {}
    try:
        en = json.loads((base / "dataset_enrich.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    disk_type = None
    try:
        de = json.loads((base / "descriptions.json").read_text(encoding="utf-8"))
        disk_type = (de.get("ser") or {}).get("step1_disk_type", {}).get("disk_type")
    except Exception:  # noqa: BLE001
        pass
    valid, gate = _valid(base)
    return {
        "task_id": tid,
        "design_id": en.get("design_id"),
        "design_family_id": en.get("design_family_id"),
        "model_id": en.get("model_id"),
        "disk_type": disk_type,
        "valid": valid,
        "quality": gate,
        "artifacts": {a: (base / a).exists() for a in ARTIFACTS},
        "tasks": {"edit": _task_sample_count("edit", tid),
                  "repair": _task_sample_count("repair", tid),
                  "mcp": _task_sample_count("mcp", tid)},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="数据集索引 + 同模型捆绑验证")
    ap.add_argument("--only", default=None, help="只处理指定 task_id")
    args = ap.parse_args(argv)

    tids = ([args.only] if args.only
            else sorted(p.name for p in OUTPUT.iterdir()
                        if p.is_dir() and (p / "raw_fixed.json").exists()))
    models = [m for m in (run_one(t) for t in tids) if m]
    if not models:
        print("没有任务目录")
        return 1

    # 同模型捆绑：按 design_id 分组统计任务/样本齐全性
    groups: dict = {}
    for m in models:
        g = groups.setdefault(m["design_id"], {"design_id": m["design_id"],
                                               "models": [], "gen_tasks": 0,
                                               "edit_samples": 0, "repair_samples": 0,
                                               "mcp_samples": 0})
        g["models"].append(m["task_id"])
        g["gen_tasks"] += 1
        g["edit_samples"] += m["tasks"]["edit"]
        g["repair_samples"] += m["tasks"]["repair"]
        g["mcp_samples"] += m["tasks"]["mcp"]
    for g in groups.values():
        g["bundled"] = g["gen_tasks"] > 0 and (g["edit_samples"] > 0 or g["repair_samples"] > 0)

    idx = {
        "schema": "dataset_index_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "models": models,
        "design_groups": list(groups.values()),
        "stats": {
            "total_tasks": len(models),
            "valid_models": sum(1 for m in models if m["valid"]),
            "by_family": dict(Counter(m["design_family_id"] for m in models)),
            "by_disk_type": dict(Counter(str(m["disk_type"]) for m in models if m["disk_type"])),
            "design_groups": len(groups),
            "bundled_groups": sum(1 for g in groups.values() if g["bundled"]),
        },
    }
    DATASETS.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    s = idx["stats"]
    print(f"index -> {INDEX}")
    print(f"  任务 {s['total_tasks']} / 有效模型 {s['valid_models']} / "
          f"design 组 {s['design_groups']} / 已捆绑 {s['bundled_groups']}")
    print(f"  by_family: {s['by_family']}")
    if s["by_disk_type"]:
        print(f"  by_disk_type: {s['by_disk_type']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
