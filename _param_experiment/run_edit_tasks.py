"""Edit 任务样本构造器（对源模型改参重生成，确定性 NL 指令，不碰主流程/src）。

对每个源任务目录选一个可用参数（PARAM_REGISTRY 语义定位），生成编辑指令
（中文 label 模板）→ regenerate_model 重建 → before/after 对比。落盘
_param_experiment/output/datasets/edit_tasks/<sample_id>.json。

用法:
  .conda/python.exe _param_experiment/run_edit_tasks.py --only mon_sweep_q2_slots_96
  .conda/python.exe _param_experiment/run_edit_tasks.py --limit 5
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
DATASETS = _HERE / "output" / "datasets" / "edit_tasks"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

from mcp_tools import (  # noqa: E402
    PARAM_REGISTRY, _current_value, _resolve_param_nodes, regenerate_model,
)
import run_enrich  # noqa: E402

# 参数优先级（定位稳定性排序；圆角类可能不可用，靠 _resolve_param_nodes 过滤）
_PRIORITY = ["slot_count", "slot_distribution_radius", "slot_axial_depth",
             "root_fillet", "disc_hub_web_fillet", "disc_web_rim_fillet"]


def _inherit(tid: str) -> dict:
    try:
        d = json.loads((OUTPUT / tid / "dataset_enrich.json").read_text(encoding="utf-8"))
        return {"design_id": d.get("design_id"), "model_id": d.get("model_id")}
    except Exception:  # noqa: BLE001
        return {"design_id": None, "model_id": None}


def _pick_param(ir: dict):
    """按优先级选第一个定位可用的参数，返回 (reg, cur)。"""
    for pk in _PRIORITY:
        reg = next((r for r in PARAM_REGISTRY if r["param"] == pk), None)
        if reg is None:
            continue
        if _resolve_param_nodes(ir, pk):
            cur = _current_value(ir, reg)
            if cur is not None:
                return reg, cur
    return None, None


def _new_value(reg: dict, cur):
    lo, hi = reg["range"]
    v = float(cur) * 0.6
    v = max(float(lo), min(float(hi), v))
    return int(round(v)) if reg["type"] == "int" else round(v, 3)


def _delta(before: dict, after: dict) -> dict:
    d = {}
    for k in ("outer_diameter_mm", "outer_radius_mm", "axial_thickness_mm",
              "count", "distribution_radius_mm", "circumferential_pitch_mm",
              "slot_depth_mm", "throat_half_width_mm"):
        b, a = before.get(k), after.get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            d[k] = round(a - b, 4)
    return d


def run_one(tid: str) -> dict | None:
    base = OUTPUT / tid
    raw_path = base / "raw_fixed.json"
    if not raw_path.exists():
        return None
    ir = json.loads(raw_path.read_text(encoding="utf-8"))
    reg, cur = _pick_param(ir)
    if reg is None:
        print(f"- {tid}  SKIP  无可用参数")
        return None
    new = _new_value(reg, cur)
    inh = _inherit(tid)
    instruction = f"请将{reg['label']}从 {cur} 调整为 {new}{reg['unit']}"

    before = run_enrich._measure_all(str(base))
    res = regenerate_model({"base_dir": str(base),
                            "param_updates": [{"param_key": reg["param"], "new_value": new}]})
    if not res.get("ok"):
        print(f"- {tid}  FAIL  {res.get('reason')}")
        return None
    after = run_enrich._measure_all(res["new_base_dir"])
    sample_id = f"{tid}_{reg['param']}{new}"
    sample = {
        "task_type": "edit", "sample_id": sample_id, "source_task_id": tid,
        "design_id": inh["design_id"], "model_id": inh["model_id"],
        "instruction": instruction,
        "param_updates": [{"param_key": reg["param"], "label": reg["label"],
                           "old": cur, "new": new, "unit": reg["unit"]}],
        "before": before, "after": after, "delta": _delta(before, after),
        "new_base_dir": res.get("new_base_dir"), "checks": res.get("checks"),
        "validated_ok": bool(res.get("ok") and res.get("checks", {}).get("valid_solid")),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    DATASETS.mkdir(parents=True, exist_ok=True)
    (DATASETS / f"{sample_id}.json").write_text(
        json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    return sample


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Edit 任务样本构造器（改参重生成）")
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

    done = 0
    for tid in tasks:
        try:
            s = run_one(tid)
            if s:
                done += 1
                print(f"- {tid}  OK  {s['instruction'][:50]}  "
                      f"count {s['before'].get('count')}->{s['after'].get('count')}")
        except Exception as exc:  # noqa: BLE001
            print(f"- {tid}  FAIL  {exc}")
    print(f"DONE  {done} edit samples -> {DATASETS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
