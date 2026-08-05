"""MCP 任务样本构造器（确定性工具序列，无 LLM，不碰主流程/src）。

对每个源任务目录生成两类 MCP 样本（single_tool / multi_tool），确定性调用
mcp_tools 工具，记录 tool_sequence + expected_args（参数绑定基准）。落盘
_param_experiment/output/datasets/mcp_tasks/<sample_id>.json。

用法:
  .conda/python.exe _param_experiment/run_mcp_tasks.py --only verify_br_c735fc40
  .conda/python.exe _param_experiment/run_mcp_tasks.py --limit 10
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
DATASETS = _HERE / "output" / "datasets" / "mcp_tasks"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from mcp_tools import TOOLS  # noqa: E402

# 确定性工具序列定义：(mcp_task_type, instruction, [(tool_name, extra_args)])
SEQUENCES = [
    ("single_tool", "对模型测量榫槽数量（count_fir_tree_slots）",
     [("count_fir_tree_slots", {})]),
    ("multi_tool", "检查榫槽节距与剩料、槽深与轮缘厚度（多工具联合检查）",
     [("count_fir_tree_slots", {}),
      ("check_slot_pitch_and_ligament", {}),
      ("check_slot_depth_and_rim", {})]),
]


def _inherit(tid: str) -> dict:
    try:
        d = json.loads((OUTPUT / tid / "dataset_enrich.json").read_text(encoding="utf-8"))
        return {"design_id": d.get("design_id"), "model_id": d.get("model_id")}
    except Exception:  # noqa: BLE001
        return {"design_id": None, "model_id": None}


def run_one(tid: str) -> list:
    base = OUTPUT / tid
    inh = _inherit(tid)
    samples = []
    for seq_idx, (mtype, instruction, tools) in enumerate(SEQUENCES):
        tool_seq, results, expected = [], {}, []
        ok = True
        for tname, extra in tools:
            tool = TOOLS.get(tname)
            if tool is None:
                ok = False
                tool_seq.append({"tool": tname, "args": None, "result": {"error": "unknown tool"}})
                continue
            args = {"base_dir": str(base)}
            args.update(extra)
            try:
                res = tool["handler"](args)
            except Exception as exc:  # noqa: BLE001
                res = {"error": str(exc)}
                ok = False
            tool_seq.append({"tool": tname, "args": args, "result": res})
            expected.append({"tool": tname, "args": args})
            results[tname] = res
        sample_id = f"{tid}_{mtype}_{seq_idx}"
        samples.append({
            "task_type": "mcp", "sample_id": sample_id, "source_task_id": tid,
            "design_id": inh["design_id"], "model_id": inh["model_id"],
            "mcp_task_type": mtype, "instruction": instruction,
            "expected_args": expected, "tool_sequence": tool_seq,
            "results": results, "validated_ok": ok,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        DATASETS.mkdir(parents=True, exist_ok=True)
        (DATASETS / f"{sample_id}.json").write_text(
            json.dumps(samples[-1], ensure_ascii=False, indent=2), encoding="utf-8")
    return samples


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MCP 任务样本构造器（确定性工具序列）")
    ap.add_argument("--only", default=None, help="只处理指定 task_id")
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
            ss = run_one(tid)
            total += len(ss)
            print(f"- {tid}  {len(ss)} samples")
        except Exception as exc:  # noqa: BLE001
            print(f"- {tid}  FAIL  {exc}")
    print(f"DONE  {total} mcp samples -> {DATASETS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
