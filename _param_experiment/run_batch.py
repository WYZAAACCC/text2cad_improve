"""批量构建管线框架：设计族候选生成 + 批量执行（基础设施，不碰主流程/src）。

设计族 = COMBINATIONS A-D（param_prompts）映射 _text 11 参数 + 槽数扫参 → 候选需求文本。
--no-run（默认）只生成 datasets/candidates.json；--run --limit N 小规模真实跑（LLM）。

用法:
  .conda/python.exe _param_experiment/run_batch.py                 # 只生成候选清单
  .conda/python.exe _param_experiment/run_batch.py --run --limit 1  # 小规模验证（LLM）
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
CAND = DATASETS / "candidates.json"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from param_prompts import COMBINATIONS  # noqa: E402
from param_sweep_test import _text  # noqa: E402

SLOTS_LIST = [24, 36, 48, 60, 72, 84, 96]


def _gen_candidates() -> list:
    cands = []
    for fam_key, combo in COMBINATIONS.items():
        d, s = combo["disc"], combo["slot"]
        od = 2 * d["rim_radius_mm"]
        bore = 2 * d["bore_radius_mm"]
        thick = 2 * max(d["hub_half_thickness_mm"], d["rim_half_thickness_mm"])
        hub, rim = d["hub_half_thickness_mm"], d["rim_half_thickness_mm"]
        teeth, R = s["teeth_count"], d["rim_radius_mm"]
        depth, throat, fr = s["slot_depth_mm"], s["mouth_half_width_mm"], s["root_fillet_mm"]
        short = fam_key.split("_")[0]
        for slots in SLOTS_LIST:
            text = _text(od, bore, thick, hub, rim, slots, teeth, R, depth, throat, fr)
            cands.append({
                "family": fam_key, "short": short, "slots": slots,
                "params": {"od": od, "bore": bore, "thick": thick, "hub": hub, "rim": rim,
                           "teeth": teeth, "R": R, "depth": depth, "throat": throat, "fr": fr},
                "text": text, "task_id": f"cand_{short}_{slots}_{teeth}tooth",
            })
    return cands


def _run_one(cand: dict) -> str:
    import main
    tid = cand["task_id"]
    main._tasks[tid] = {"taskId": tid, "status": "pending", "progress": 0, "result": None, "error": None}
    main._run_pipeline(tid, cand["text"], force_route="generative_cad_ir")
    return main._tasks[tid].get("status", "?")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="批量构建管线：候选生成 + 批量执行")
    ap.add_argument("--run", action="store_true", help="实际跑 pipeline（LLM）；默认只生成候选清单")
    ap.add_argument("--limit", type=int, default=None, help="--run 时最多跑前 N 个候选")
    args = ap.parse_args(argv)

    cands = _gen_candidates()
    DATASETS.mkdir(parents=True, exist_ok=True)
    CAND.write_text(json.dumps({"schema": "candidates_v1", "count": len(cands),
                                "candidates": cands}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"候选清单 -> {CAND}  ({len(cands)} 个: {len(COMBINATIONS)} 族 × {len(SLOTS_LIST)} 槽数)")
    for c in cands[:5]:
        print(f"  {c['task_id']:24s} {c['text'][:55]}")

    if not args.run:
        print("\n[--no-run] 未触发 LLM 生成（基础设施验证）")
        return 0

    sel = cands[:args.limit] if args.limit else cands
    print(f"\n批量执行 {len(sel)} 个候选（LLM）:")
    for i, c in enumerate(sel, 1):
        print(f"  [{i}/{len(sel)}] {c['task_id']} ...", end=" ", flush=True)
        try:
            status = _run_one(c)
            print(f"{status}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {exc}")
    print("\n生成后可跑 run_enrich → run_filter → run_index 完成入库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
