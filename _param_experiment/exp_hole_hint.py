"""实验（F17 诊断）：需求文本只"提一下可能需要打孔"，不教任何操作，观察 LLM 能否自主生成 cut_circular_hole_pattern。

对照：D05 原文本（无提示，实测 LLM 生成榫槽盘、无孔 op）。
假设：L2 tool schema 已枚举 cut_circular_hole_pattern（含参数说明），LLM 只需被提醒"可能需要孔"即可自行反应。

用法:
  .conda/python.exe _param_experiment/exp_hole_hint.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from design_families import DESIGN_FAMILIES, build_text  # noqa: E402

BASE = build_text(DESIGN_FAMILIES["D05"])

# 提示措辞变体（只提"可能需要打孔"，不出现操作名/参数，不教结构）
HINTS = [
    " 提示：本盘为带周向安装孔的涡轮盘，可能需要在盘体上构造周向孔阵列，请勿忽略孔类特征。",
]


def run(tid: str, text: str) -> tuple[str, bool]:
    import main
    main._tasks[tid] = {"taskId": tid, "status": "pending", "progress": 0,
                        "result": None, "error": None}
    main._run_pipeline(tid, text, force_route="generative_cad_ir")
    st = main._tasks[tid].get("status", "?")
    raw_path = ROOT / "app" / "text-to-cad" / "server" / "output" / tid / "raw_fixed.json"
    has_hole = False
    ops = []
    if raw_path.exists():
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        ops = sorted({n.get("op") for n in raw.get("nodes", [])})
        has_hole = any(n.get("op") == "cut_circular_hole_pattern" for n in raw.get("nodes", []))
        if has_hole:
            for n in raw.get("nodes", []):
                if n.get("op") == "cut_circular_hole_pattern":
                    print(f"  cut_circular_hole_pattern params: {n.get('params')}")
    print(f"[{tid}] status={st}  has_cut_circular_hole_pattern={has_hole}")
    print(f"  ops={ops}")
    return st, has_hole


if __name__ == "__main__":
    print("baseline (无提示，历史对照): D05 → 榫槽盘，无孔 op")
    for i, h in enumerate(HINTS):
        tid = f"exp_hole_hint{i}"
        print(f"\n=== 实验文本 = {BASE}{h} ===")
        run(tid, BASE + h)
