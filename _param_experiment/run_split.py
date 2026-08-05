"""子集切分 + ⑦c 同模型捆绑验证（基础设施，scan-dirs，不碰主流程/src）。

读 datasets/index.json + family_split.json（族→集合配置）：
  - 每模型按 design_family_id 分配集合（train/val/holdout，未配置默认 train）
  - ⑦c 捆绑验证：同 design_id 组内所有任务集合必须一致（violations 记录冲突）
输出 datasets/split_report.json。

用法:
  .conda/python.exe _param_experiment/run_split.py
  .conda/python.exe _param_experiment/run_split.py --family-split _param_experiment/family_split.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
DATASETS = _HERE / "output" / "datasets"
INDEX = DATASETS / "index.json"
SPLIT = DATASETS / "split_report.json"
DEFAULT_FAMILY_SPLIT = _HERE / "family_split.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="子集切分 + 同模型捆绑验证")
    ap.add_argument("--family-split", default=str(DEFAULT_FAMILY_SPLIT), help="族→集合配置 JSON")
    args = ap.parse_args(argv)

    if not INDEX.exists():
        print("先跑 run_index.py 生成 index.json")
        return 1
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    fs = json.loads(Path(args.family_split).read_text(encoding="utf-8")).get("family_split", {})

    models = []
    for m in idx.get("models", []):
        split = fs.get(m.get("design_family_id"), "train")
        models.append({"task_id": m["task_id"], "split": split,
                       "design_id": m.get("design_id"), "design_family_id": m.get("design_family_id"),
                       "valid": m.get("valid")})

    # ⑦c 捆绑验证：同 design_id 组内 split 一致
    groups: dict = {}
    for m in models:
        if m["design_id"]:
            groups.setdefault(m["design_id"], set()).add(m["split"])
    violations = [{"design_id": d, "splits": sorted(s)} for d, s in groups.items() if len(s) > 1]

    counts = Counter(m["split"] for m in models)
    valid_counts = Counter(m["split"] for m in models if m["valid"])
    report = {
        "schema": "split_report_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "models": models,
        "stats": {
            "total": len(models),
            "train": counts.get("train", 0), "val": counts.get("val", 0),
            "holdout": counts.get("holdout", 0),
            "valid_models": sum(1 for m in models if m["valid"]),
            "valid_train": valid_counts.get("train", 0),
            "valid_val": valid_counts.get("val", 0),
            "design_groups": len(groups),
            "bundled_ok": len(groups) - len(violations),
            "violations": violations,
        },
        "family_split": fs,
    }
    DATASETS.mkdir(parents=True, exist_ok=True)
    SPLIT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    s = report["stats"]
    print(f"split report -> {SPLIT}")
    print(f"  模型 {s['total']}（有效 {s['valid_models']}）: "
          f"train {s['train']}(valid {s['valid_train']}) / val {s['val']}(valid {s['valid_val']}) / holdout {s['holdout']}")
    print(f"  design 组 {s['design_groups']} / 捆绑一致 {s['bundled_ok']} / 跨集合冲突 {len(s['violations'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
