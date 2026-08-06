"""需求参数一致性校验 — 供数据构建过滤坏样本（LLM 参数未生效检测）。

从需求文本正则提取期望参数 → 复用 mcp_tools 测量 IR 实际值 → 输出一致性报告。
G1/G2 基准与简单变体一致；G4/G5（喉部/齿数/槽深未生效）应被检出。

用法:
  .conda/python.exe -c "import validate_req_params as v; print(v.validate_ir(TEXT, 'output/mon_sweep_g4_throat_fillet'))"
  .conda/python.exe _param_experiment/validate_req_params.py [--dir <任务目录>] [--text <需求文本>]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "integrations" / "engineering_tools" / "src"))

# (param_key, 正则, 类型, 容差)
# 注意：环槽用"环槽槽宽/环槽槽深"措辞（candidate_sampler 文本一致），避免与榫槽"槽深"冲突。
# 减重孔/冷却孔用"减重孔/冷却孔，孔径"限定，避免与安装孔"孔径"（hdia_mm）冲突。
RE_PARAMS = [
    ("outer_diameter_mm",    r"外径[Φ]?(\d+)",        float, 5.0),
    ("bore_diameter_mm",     r"中心孔直径[Φ]?(\d+)",  float, 5.0),
    ("axial_thickness_mm",   r"轴向最大厚度[Φ]?(\d+)", float, 3.0),
    ("slots",                r"轮缘上(\d+)个",        int,   0),
    ("teeth_count",          r"(\d)齿枞树形",         int,   0),
    ("slot_depth_mm",        r"(?<!环槽)槽深(\d+)",   float, 2.0),
    ("throat_half_width_mm", r"喉部半宽([\d.]+)",     float, 0.5),
    ("root_fillet_mm",       r"齿根圆角([\d.]+)",     float, 0.3),
    ("R_mm",                 r"枞树形榫槽.*?分布半径([\d.]+)", float, 2.0),
    # 主体：轮毂/轮缘半厚
    ("hub_half_mm",          r"轮毂半厚([\d.]+)",    float, 3.0),
    ("rim_half_mm",          r"轮缘半厚([\d.]+)",    float, 3.0),
    # 孔阵列（"安装孔"限定避免与减重/冷却孔"孔径"冲突）
    ("holes",                r"(\d+)个安装孔",       int,   0),
    ("hdia_mm",              r"安装孔，孔径([\d.]+)", float, 0.5),
    ("pcd_mm",               r"安装孔.*?分布半径([\d.]+)", float, 2.0),
    # 环槽
    ("grooves",              r"(\d+)道环槽",         int,   0),
    ("gw_mm",                r"环槽槽宽([\d.]+)",    float, 0.5),
    ("gd_mm",                r"环槽槽深([\d.]+)",    float, 0.5),
    # 减重结构（论文 2.2）
    ("lh_holes",             r"(\d+)个减重孔",       int,   0),
    ("lh_hdia_mm",           r"减重孔，孔径([\d.]+)", float, 0.5),
    ("lh_pcd_mm",            r"减重孔，孔径[\d.]+mm，分布半径([\d.]+)", float, 2.0),
    ("cl_holes",             r"(\d+)个冷却孔",       int,   0),
    ("cl_hdia_mm",           r"冷却孔，孔径([\d.]+)", float, 0.5),
    ("cl_pcd_mm",            r"冷却孔，孔径[\d.]+mm，分布半径([\d.]+)", float, 2.0),
    ("cl_pcd2_mm",           r"第二排分布半径([\d.]+)", float, 2.0),
    ("rs_count",             r"(\d+)个径向局部切槽", int,   0),
    ("rs_depth_mm",          r"切槽深度([\d.]+)",    float, 1.0),
    ("cavity_width_mm",      r"环形减重腔，腔宽([\d.]+)", float, 1.0),
    ("cavity_depth_mm",      r"环形减重腔，腔宽[\d.]+mm，腔深([\d.]+)", float, 0.5),
    ("rim_arc_radius_mm",    r"过渡半径([\d.]+)",    float, 1.0),
]

LABELS = {
    "outer_diameter_mm": "外径", "bore_diameter_mm": "中心孔",
    "axial_thickness_mm": "轴厚", "slots": "榫槽数量", "teeth_count": "齿数",
    "slot_depth_mm": "槽深", "throat_half_width_mm": "喉部半宽", "root_fillet_mm": "齿根圆角",
    "hub_half_mm": "轮毂半厚", "rim_half_mm": "轮缘半厚",
    "holes": "孔数量", "hdia_mm": "孔径", "pcd_mm": "孔分布半径",
    "grooves": "环槽数量", "gw_mm": "环槽槽宽", "gd_mm": "环槽槽深",
    "R_mm": "榫槽分布半径",
    "lh_holes": "减重孔数", "lh_hdia_mm": "减重孔径", "lh_pcd_mm": "减重孔分布半径",
    "cl_holes": "冷却孔数", "cl_hdia_mm": "冷却孔径", "cl_pcd_mm": "冷却孔分布半径",
    "cl_pcd2_mm": "第二排冷却孔分布半径",
    "rs_count": "径向切槽数", "rs_depth_mm": "切槽深度",
    "cavity_width_mm": "环形腔宽", "cavity_depth_mm": "环形腔深",
    "rim_arc_radius_mm": "轮缘过渡半径",
}


def extract_requirements(text: str) -> dict:
    """从需求文本正则提取期望参数。返回 {param_key: expected_value}。"""
    out = {}
    for key, pat, typ, _tol in RE_PARAMS:
        m = re.search(pat, text)
        if m:
            try:
                out[key] = typ(m.group(1))
            except ValueError:
                pass
    return out


def validate_ir(text: str, base_dir) -> dict:
    """需求文本 vs 任务目录 IR 的一致性校验。

    返回 {ok, checks:[{param,label,expected,actual,tol,ok}], missing_params, extracted}。
    """
    req = extract_requirements(text)
    import mcp_tools as mt
    dm = mt.measure_disc_dimensions({"base_dir": str(base_dir)})
    sp = mt.measure_fir_tree_slot_profile({"base_dir": str(base_dir)})
    cnt = mt.count_fir_tree_slots({"base_dir": str(base_dir)})
    actuals = {
        "outer_diameter_mm": dm.get("outer_diameter_mm"),
        "bore_diameter_mm": dm.get("bore_diameter_mm"),
        "axial_thickness_mm": dm.get("axial_thickness_mm"),
        "slots": cnt.get("count"),
        "teeth_count": sp.get("teeth_count"),
        "slot_depth_mm": sp.get("slot_depth_mm"),
        "throat_half_width_mm": sp.get("throat_half_width_mm"),
        "root_fillet_mm": sp.get("root_fillet_mm"),
        # 孔/环槽/轮毂轮缘：无专用测量工具（盘型数据暂缓），actual=None → 跳过验证
        "hub_half_mm": None, "rim_half_mm": None,
        "holes": None, "hdia_mm": None, "pcd_mm": None,
        "grooves": None, "gw_mm": None, "gd_mm": None,
    }
    checks = []
    for key, _pat, _typ, tol in RE_PARAMS:
        if key not in req:
            continue
        expected, actual = req[key], actuals.get(key)
        if actual is None:
            continue  # 无测量工具（孔/环槽等），跳过验证不误判
        if key in ("slots", "teeth_count", "holes", "grooves"):
            ok = int(actual) == int(expected)
        else:
            ok = abs(actual - expected) <= tol
        checks.append({"param": key, "label": LABELS[key], "expected": expected,
                       "actual": actual, "tol": tol, "ok": bool(ok)})
    return {"ok": bool(checks) and all(c["ok"] for c in checks),
            "checks": checks, "extracted": req,
            "missing_params": [k for k, _p, _t, _l in RE_PARAMS if k not in req]}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="任务目录（含 raw_fixed.json）")
    ap.add_argument("--text", required=True, help="需求文本")
    args = ap.parse_args(argv)
    r = validate_ir(args.text, args.dir)
    print(f"需求参数一致性: {'PASS' if r['ok'] else 'FAIL'}")
    for c in r["checks"]:
        mark = "PASS" if c["ok"] else "FAIL"
        print(f"  [{mark}] {c['label']}: 期望={c['expected']} 实际={c['actual']} ±{c['tol']}")
    if r["missing_params"]:
        print(f"  未提取参数: {r['missing_params']}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
