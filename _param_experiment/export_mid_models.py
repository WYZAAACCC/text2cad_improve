"""导出含榫槽模型的中间模型（论文"含榫槽模型额外保存"）。

对有效榫槽盘任务，从 IR 确定性导出到任务目录 mid_models/：
  - slot_profile_2d.json  单榫槽二维参数化轮廓（cutter add_polyline points）
  - single_slot_tool.step  单榫槽工具体（沿轴向拉伸的切割实体）
  - slot_array.step        周向完整榫槽阵列（工具体旋转复制）

独立于主流程/src；用 CadQuery 从 IR 参数确定性重建（不改主流程）。

用法:
  .conda/python.exe _param_experiment/export_mid_models.py            # 全部有效任务
  .conda/python.exe _param_experiment/export_mid_models.py --only cand_D15_feasible_0
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))


def _cutter_geometry(ir: dict) -> dict | None:
    """从 IR 提取单槽工具体几何：轮廓点、轴向深度、阵列参数。"""
    cutter_comp = None
    for n in ir.get("nodes", []):
        if n.get("op") == "extrude_profile":
            cutter_comp = n.get("component")
            break
    if not cutter_comp:
        return None
    points = None
    for n in ir.get("nodes", []):
        if n.get("op") == "add_polyline" and n.get("component") == cutter_comp:
            pts = (n.get("params") or {}).get("points") or []
            if len(pts) >= 3:
                points = [(p.get("x_mm", 0), p.get("y_mm", 0)) for p in pts]
            break
    depth = 80.0
    for n in ir.get("nodes", []):
        if n.get("op") == "extrude_profile" and n.get("component") == cutter_comp:
            d = (n.get("params") or {}).get("depth_mm")
            if isinstance(d, (int, float)):
                depth = float(d)
            break
    pattern = {"count": None, "radius_mm": None}
    for n in ir.get("nodes", []):
        if n.get("op") == "circular_pattern_component":
            p = n.get("params") or {}
            if isinstance(p.get("count"), (int, float)):
                pattern["count"] = int(p["count"])
            if isinstance(p.get("radius_mm"), (int, float)):
                pattern["radius_mm"] = float(p["radius_mm"])
            break
    if not points:
        return None
    return {"points": points, "depth": depth, "pattern": pattern}


def export_one(task_id: str) -> dict:
    """导出单任务的中间模型到 mid_models/。返回报告。"""
    base = OUTPUT / task_id
    mid = base / "mid_models"
    report = {"task_id": task_id, "ok": False, "error": None, "files": []}
    raw_path = base / "raw_fixed.json"
    if not raw_path.exists():
        report["error"] = "无 raw_fixed.json"
        return report
    ir = json.loads(raw_path.read_text(encoding="utf-8"))
    geo = _cutter_geometry(ir)
    if not geo:
        report["error"] = "无榫槽工具体（非榫槽盘或结构异常）"
        return report
    try:
        import cadquery as cq
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"cadquery 不可用: {exc}"
        return report
    try:
        mid.mkdir(parents=True, exist_ok=True)
        # 1. 单槽轮廓点
        (mid / "slot_profile_2d.json").write_text(
            json.dumps({"task_id": task_id, "points": geo["points"], "schema": "slot_profile_2d_v1"},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        report["files"].append("slot_profile_2d.json")
        # 2. 单槽工具体（XY 平面闭合轮廓，双向拉伸）
        pts = geo["points"]
        w = cq.Workplane("XY").polyline(pts).close()
        tool = w.extrude(geo["depth"] / 2.0, both=True)
        cq.exporters.export(tool, str(mid / "single_slot_tool.step"))
        report["files"].append("single_slot_tool.step")
        # 3. 周向阵列
        n, r = geo["pattern"]["count"], geo["pattern"]["radius_mm"]
        if n and r:
            array = None
            for i in range(n):
                ang = 360.0 * i / n
                item = tool.rotate((0, 0, 0), (0, 0, 1), ang)
                array = item if array is None else array.union(item)
            cq.exporters.export(array, str(mid / "slot_array.step"))
            report["files"].append("slot_array.step")
        report["ok"] = True
    except Exception as exc:  # noqa: BLE001
        report["error"] = str(exc)[:200]
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="导出含榫槽模型中间模型")
    ap.add_argument("--only", default=None, help="只处理指定 task_id")
    args = ap.parse_args(argv)
    if args.only:
        tasks = [args.only]
    else:
        tasks = sorted(p.name for p in OUTPUT.iterdir()
                       if p.is_dir() and (p / "raw_fixed.json").exists())
    ok = 0
    for tid in tasks:
        r = export_one(tid)
        if r["ok"]:
            ok += 1
            print(f"- {tid}  OK  {r['files']}")
        else:
            print(f"- {tid}  SKIP  {r['error']}")
    print(f"DONE  {ok}/{len(tasks)} 导出中间模型")
    return 0


if __name__ == "__main__":
    sys.exit(main())
