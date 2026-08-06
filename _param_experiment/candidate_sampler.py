"""三区候选参数采样器（采集基础设施，独立，不碰主流程/src）。

对 32 设计族生成落在论文参数范围（附件四/五）的候选参数配置，并按论文几何约束
（sampling_constraints.check_all）分为三区：
  - feasible   可行区：约束全过，最小剩料 margin >= BOUNDARY_MARGIN
  - boundary   边界区：约束全过，但某剩料 margin < BOUNDARY_MARGIN（接近几何边界）
  - infeasible 不可行区：参数落在论文范围但违反几何约束（供"拒绝"标注）

输出 datasets/candidates.json（schema candidates_v3，每条含 zone 标记）。
文本生成沿用 design_families 措辞（外径/中心孔/轴向最大厚度/轮毂半厚/轮缘半厚 +
榫槽/孔/环槽特征句；环槽用"环槽槽宽/环槽槽深"避免与榫槽"槽深"提取冲突）。

用法:
  .conda/python.exe _param_experiment/candidate_sampler.py                # 默认每族 12 候选
  .conda/python.exe _param_experiment/candidate_sampler.py --per-family 12 --family D05
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
CAND = DATASETS / "candidates.json"
sys.path.insert(0, str(_HERE))

from design_families import DESIGN_FAMILIES, CATEGORY_LABEL  # noqa: E402
from sampling_constraints import check_all  # noqa: E402

# 论文参数范围（附件四/五），hub/rim 为轴向半厚（现有体系语义，约为轴向最大厚度 1/3）
RANGES = {
    "od_mm": (360, 760), "bore_mm": (50, 200), "thick_mm": (30, 130),
    "hub_mm": (12, 65), "rim_mm": (10, 65),
    "holes": (6, 36), "hdia_mm": (4, 26), "pcd_mm": (80, 310),
    "grooves": (1, 3), "gw_mm": (4, 28), "gd_mm": (2, 20),
    "slots": (24, 96), "teeth": (2, 4), "R_mm": (180, 300),
    "depth_mm": (12, 45), "throat_half_width_mm": (2, 9), "fr_mm": (0.5, 4.0),
    # 减重结构（论文 2.2）：减重孔/冷却孔复用孔阵列范围；切槽/环形腔为新增特征
    "lh_holes": (6, 36), "lh_pcd_mm": (80, 310), "lh_hdia_mm": (4, 26),
    "cl_holes": (6, 36), "cl_pcd_mm": (80, 310), "cl_hdia_mm": (4, 26),
    "rs_count": (12, 96), "rs_depth_mm": (4, 20), "rs_half_width_mm": (1, 6),
    "cavity_width_mm": (16, 60), "cavity_depth_mm": (2, 6),
    "rim_arc_radius_mm": (12, 30),
}
BOUNDARY_MARGIN = 5.0  # 剩料 margin < 5mm 视为边界区（真实贴近约束边界）


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _rim_radial(od_mm: float) -> float:
    """轮缘可用径向厚度 tr（论文 25-95）≈ 0.12×od，供槽深/环槽深约束。"""
    return _clamp(0.12 * od_mm, 25.0, 95.0)


def _subject(fam: dict) -> dict:
    """设计族 → 主体采样参数（采样键，落在论文范围）。"""
    od = _clamp(fam.get("od", 500), *RANGES["od_mm"])
    bore = _clamp(fam.get("bore", 120), *RANGES["bore_mm"])
    thick = _clamp(fam.get("thick", 76), *RANGES["thick_mm"])
    hub = _clamp(fam.get("hub", 38), *RANGES["hub_mm"])
    rim = _clamp(fam.get("rim", 30), *RANGES["rim_mm"])
    return {"od_mm": od, "bore_mm": bore, "thick_mm": thick,
            "hub_mm": hub, "rim_mm": rim,
            "rim_radial_mm": _rim_radial(od)}


def _subj_variants(subj: dict) -> list:
    """主体变体：base + od ±20% + bore ±20%（落范围），供少量覆盖。"""
    base = dict(subj)
    out = [base]
    for key, scale in (("od_mm", 0.8), ("od_mm", 1.2), ("bore_mm", 0.7), ("bore_mm", 1.5)):
        v = dict(base)
        v[key] = round(_clamp(base[key] * scale, *RANGES[key]), 1)
        v["rim_radial_mm"] = _rim_radial(v["od_mm"])
        if v not in out:
            out.append(v)
    return out


# ── 特征变体（参数全落论文范围；zone 由 check_all + margin 判定，随族主体不同而异）──
_HOLE_VARIANTS = [
    {"holes": 8, "pcd_mm": 110, "hdia_mm": 6},       # 低端（margin 大 → feasible）
    {"holes": 16, "pcd_mm": 180, "hdia_mm": 14},     # 中（margin 大 → feasible）
    {"holes": 30, "pcd_mm": 220, "hdia_mm": 16},     # 中高（margin 大 → feasible）
    {"holes": 24, "pcd_mm": 240, "hdia_mm": 12},     # 外边界（od 500: margin≈2 → boundary）
]
# groove 减重结构变体模板：环槽 + 减重孔/冷却孔/径向切槽/环形腔组合（论文 2.2）。
# 减重孔/冷却孔 pcd 用"腹板段比例"（pcd_frac：hub_r + frac×(rim_junc−hub_r)），
# 由 _resolve_groove_feats 按 subj 动态解析为绝对 pcd_mm —— 避免固定 pcd 对不同 od 越界。
_GROOVE_LH_TEMPLATES = [
    {"grooves": 1, "gw_mm": 6, "gd_mm": 4},                            # 低端（仅环槽）
    {"grooves": 2, "gw_mm": 14, "gd_mm": 10},                          # 中（仅环槽）
    {"grooves": 1, "gw_mm": 12, "gd_mm": 8, "lh_holes": 12,
     "lh_hdia_mm": 16, "lh_pcd_frac": 0.35},                           # 环槽+减重孔
    {"grooves": 2, "gw_mm": 16, "gd_mm": 10, "cl_holes": 24,
     "cl_hdia_mm": 6, "cl_pcd_frac": 0.65},                            # 环槽+冷却孔
    {"grooves": 1, "gw_mm": 20, "gd_mm": 12, "rs_count": 60,
     "rs_depth_mm": 10, "rs_half_width_mm": 3},                        # 环槽+径向切槽
    {"grooves": 2, "gw_mm": 24, "gd_mm": 14, "lh_holes": 16, "lh_hdia_mm": 14,
     "lh_pcd_frac": 0.4, "cl_holes": 30, "cl_hdia_mm": 5,
     "cl_pcd_frac": 0.75},                                             # 环槽+减重孔+冷却孔
    {"grooves": 3, "gw_mm": 8, "gd_mm": 6, "lh_holes": 24, "lh_hdia_mm": 12,
     "lh_pcd_frac": 0.45, "cl_holes": 36, "cl_hdia_mm": 5,
     "cl_pcd_frac": 0.3, "cl_pcd2_frac": 0.8, "cavity_width_mm": 44,
     "cavity_depth_mm": 4},                                            # 双环槽+双排孔+环形腔
]


def _resolve_groove_feats(subj: dict, tpl: dict) -> dict:
    """groove 减重模板：把 pcd_frac（腹板段比例）解析为绝对 pcd_mm（_axisym_radii）。"""
    from sampling_constraints import _axisym_radii
    r = _axisym_radii(subj["od_mm"], subj["bore_mm"])
    f = dict(tpl)

    def _resolve(key: str, frac_key: str):
        if frac_key in f:
            fr = f.pop(frac_key)
            f[key] = round(r["hub_r"] + fr * (r["rim_junc"] - r["hub_r"]), 1)

    _resolve("lh_pcd_mm", "lh_pcd_frac")
    _resolve("cl_pcd_mm", "cl_pcd_frac")
    _resolve("cl_pcd2_mm", "cl_pcd2_frac")
    return f
_SLOT_VARIANTS = [
    {"slots": 30, "teeth": 2, "R_mm": 210, "depth_mm": 15, "throat_half_width_mm": 3.0, "fr_mm": 1.0},
    {"slots": 48, "teeth": 2, "R_mm": 220, "depth_mm": 24, "throat_half_width_mm": 4.0, "fr_mm": 1.0},
    {"slots": 90, "teeth": 3, "R_mm": 240, "depth_mm": 40, "throat_half_width_mm": 3.0, "fr_mm": 2.0},  # 节距边界
    {"slots": 90, "teeth": 3, "R_mm": 260, "depth_mm": 40, "throat_half_width_mm": 3.5, "fr_mm": 2.0},
]

# 不可行变体（参数落论文范围但普遍违反几何约束；zone 由 check_all 判定）
_INFEASIBLE = {
    "hole": [
        {"holes": 36, "pcd_mm": 80, "hdia_mm": 26},      # 孔间剩料必负（pcd 下限+hdia 上限+n 上限）
    ],
    "groove": [
        # 减重孔 pcd 过低（落在轮毂段，check_lightening_hole_bounds 内边界必违，参数仍在论文范围）
        {"grooves": 1, "gw_mm": 12, "gd_mm": 8, "lh_holes": 24,
         "lh_pcd_mm": 80, "lh_hdia_mm": 20},
        # 环形腔超宽（腹板径向放不下，check_annular_cavity 必违，cavity_width 在范围上限内）
        {"grooves": 2, "gw_mm": 16, "gd_mm": 10, "cavity_width_mm": 60,
         "cavity_depth_mm": 6},
    ],
    "slot": [
        {"slots": 96, "teeth": 4, "R_mm": 200, "depth_mm": 24,
         "throat_half_width_mm": 6.0, "fr_mm": 2.0},     # 节距必不足（R 下限+throat 上限+slots 上限）
        {"slots": 60, "teeth": 2, "R_mm": 200, "depth_mm": 45,
         "throat_half_width_mm": 6.0, "fr_mm": 1.0},     # 槽深超轮缘（depth 上限）
    ],
    "coupled": [
        {"slots": 96, "teeth": 4, "R_mm": 200, "depth_mm": 24,
         "throat_half_width_mm": 6.0, "fr_mm": 2.0,
         "holes": 36, "pcd_mm": 80, "hdia_mm": 26},      # 榫槽节距 + 孔间剩料双违
    ],
    "complex_rim": [
        {"slots": 96, "teeth": 4, "R_mm": 200, "depth_mm": 24,
         "throat_half_width_mm": 6.0, "fr_mm": 2.0},
    ],
    "basic": [],  # 基础盘无特征约束，无不不可行
}


def _feat_variants(cat: str) -> list:
    """类别 → 特征变体列表（不含不可行）。"""
    if cat == "hole":
        return list(_HOLE_VARIANTS)
    if cat == "groove":
        return list(_GROOVE_LH_TEMPLATES)
    if cat == "slot":
        return list(_SLOT_VARIANTS)
    if cat == "coupled":
        return list(_SLOT_VARIANTS) + [
            {"slots": 48, "teeth": 2, "R_mm": 220, "depth_mm": 24,
             "throat_half_width_mm": 4.0, "fr_mm": 1.0,
             "holes": 12, "pcd_mm": 200, "hdia_mm": 12},
            {"slots": 60, "teeth": 3, "R_mm": 240, "depth_mm": 30,
             "throat_half_width_mm": 4.0, "fr_mm": 2.0,
             "grooves": 1, "gw_mm": 12, "gd_mm": 8},
        ]
    if cat == "complex_rim":
        # 圆弧曲线过渡盘体（论文 2.1）：各槽参数变体 + 圆弧过渡半径（12/20/28）
        out = []
        for t in _SLOT_VARIANTS + [
                {"slots": 84, "teeth": 3, "R_mm": 250, "depth_mm": 36,
                 "throat_half_width_mm": 5.0, "fr_mm": 2.0}]:
            for arc in (12.0, 20.0, 28.0):
                out.append({**t, "rim_arc_radius_mm": arc})
        return out
    return []  # basic


_AXISYM_CATS = ("basic", "hole", "groove")  # axisym 盘体（3 段轴向近似）不承诺精确半厚


def _make_text(params: dict, cat: str) -> str:
    """采样参数向量 → 需求文本（措辞对齐 RE_PARAMS 正则）。

    axisym 盘（basic/hole/groove）几何为 3 段轴向近似，不表达精确轮毂/轮缘半厚，
    故文本不承诺 hub/rim（避免文本↔几何不一致）；sketch_profile 榫槽盘保留。
    """
    p = [f"生成一个高压涡轮盘参考几何：{CATEGORY_LABEL[cat]}",
         f"外径{params['od_mm']}mm，中心孔直径{params['bore_mm']}mm，"
         f"轴向最大厚度{params['thick_mm']}mm"]
    if cat not in _AXISYM_CATS:
        p.append(f"轮毂半厚{params['hub_mm']}mm，轮缘半厚{params['rim_mm']}mm")
    f = params
    if f.get("slots"):
        p.append(f"轮缘上{f['slots']}个{f['teeth']}齿枞树形榫槽，分布半径{f['R_mm']}mm，"
                 f"槽深{f['depth_mm']}mm，喉部半宽{f['throat_half_width_mm']}mm，"
                 f"齿根圆角{f['fr_mm']}mm")
    if f.get("holes"):
        p.append(f"周向均布{f['holes']}个安装孔，孔径{f['hdia_mm']}mm，"
                 f"分布半径{f['pcd_mm']}mm")
    if f.get("grooves"):
        p.append(f"轮缘内侧{f['grooves']}道环槽，环槽槽宽{f['gw_mm']}mm，"
                 f"环槽槽深{f['gd_mm']}mm")
    if f.get("lh_holes"):
        p.append(f"腹板上{f['lh_holes']}个减重孔，孔径{f['lh_hdia_mm']}mm，"
                 f"分布半径{f['lh_pcd_mm']}mm")
    if f.get("cl_holes"):
        p.append(f"腹板上{f['cl_holes']}个冷却孔，孔径{f['cl_hdia_mm']}mm，"
                 f"分布半径{f['cl_pcd_mm']}mm"
                 + (f"，第二排分布半径{f['cl_pcd2_mm']}mm" if f.get("cl_pcd2_mm") else ""))
    if f.get("rs_count"):
        p.append(f"轮缘外表面{f['rs_count']}个径向局部切槽，切槽深度{f['rs_depth_mm']}mm，"
                 f"槽宽{int(2 * f['rs_half_width_mm'])}mm")
    if f.get("cavity_width_mm"):
        p.append(f"腹板处环形减重腔，腔宽{f['cavity_width_mm']}mm，"
                 f"腔深{f['cavity_depth_mm']}mm")
    if f.get("rim_arc_radius_mm"):
        p.append(f"轮缘与腹板交界采用圆弧曲线过渡，过渡半径{f['rim_arc_radius_mm']}mm")
    return "，".join(p) + "。参考几何，非适航件。"


def _margin(subj: dict, feat: dict | None) -> float:
    """最小剩料 margin（mm）。无约束特征 → inf。"""
    params = dict(subj)
    if feat:
        params.update(feat)
    r = check_all(params)
    if not r["ok"]:
        return -1.0
    margins = []
    for c in r["checks"]:
        n = c["name"]
        if n == "hole_bounds":
            margins.append(min(c["max_pcd_mm"] - params["pcd_mm"],
                               params["pcd_mm"] - c["min_pcd_mm"]))
        elif n == "hole_spacing":
            margins.append(c["ligament"])
        elif n == "slot_pitch":
            margins.append(c["pitch"] - c["width"])
        elif n == "slot_depth":
            margins.append(c["tr"] - params["depth_mm"])
        elif n == "groove_depth":
            margins.append(c["tr"] - params["gd_mm"])
        elif n in ("lh_hole_bounds", "cl_hole_bounds"):
            key = {"lh_hole_bounds": "lh_pcd_mm", "cl_hole_bounds": "cl_pcd_mm"}[n]
            margins.append(min(c["max_pcd_mm"] - params[key],
                               params[key] - c["min_pcd_mm"]))
        elif n in ("lh_hole_spacing", "cl_hole_spacing"):
            margins.append(c["ligament"])
        elif n == "cl_double_row_spacing":
            margins.append(c["sep_mm"] - c["min_sep_mm"])
        elif n == "rim_slot_depth":
            margins.append(c["tr"] - params["rs_depth_mm"])
        elif n == "rim_slot_pitch":
            margins.append(c["pitch"] - c["width"])
        elif n == "annular_cavity":
            margins.append(min(c["max_width_mm"] - params["cavity_width_mm"],
                               c["max_depth_mm"] - params["cavity_depth_mm"]))
    return min(margins) if margins else float("inf")


def _normalize_slot(p: dict) -> dict:
    """槽类候选参数规范化：R clamp 到 [0.38·od+depth+3, od/2]（槽底剩料≥3）、
    fr clamp 到 root 半宽（0.75×throat−1.5）可放空间。保证 classify/生成/文本一致。"""
    p = dict(p)
    if p.get("slots") and p.get("R_mm") is not None and p.get("depth_mm") is not None:
        lo = max(0.38 * p["od_mm"] + p["depth_mm"] + 3.0, 180.0)  # 槽底剩料≥3，且论文 R 下限 180
        hi = min(p["od_mm"] / 2.0, 300.0)  # 论文 R 上限 300
        # min(max(v,lo),hi)：lo<=hi 时正常 clamp；lo>hi（无法同时满足剩料与论文 R 上限）→ 取 hi，
        # 由 check_slot_bottom 判该候选不可行（不产生超论文范围的 R）
        p["R_mm"] = round(min(max(p["R_mm"], lo), hi), 3)
    if p.get("slots") and p.get("fr_mm") is not None and p.get("throat_half_width_mm") is not None:
        root_half = 0.75 * p["throat_half_width_mm"] - 1.5
        p["fr_mm"] = round(min(p["fr_mm"], max(root_half, 0.3)), 3)
    return p


def _classify(subj: dict, feat: dict | None) -> tuple:
    """约束分类 → (zone, checks)。不可行由 check_all 判定；可行按最小剩料 margin 分界。"""
    params = dict(subj)
    if feat:
        params.update(feat)
        if params.get("slots"):
            params = _normalize_slot(params)  # 先用规范化后的 R/fr 判定（与生成/文本一致）
    if feat is None or params.get("_none"):
        return "feasible", []
    r = check_all(params)
    if not r["ok"]:
        return "infeasible", r["checks"]
    m = _margin(params, None) if params.get("slots") else _margin(subj, feat)
    if m < BOUNDARY_MARGIN:
        return "boundary", r["checks"]
    return "feasible", r["checks"]


def _sample_family(fid: str, fam: dict, per_family: int) -> list:
    subj = _subject(fam)
    subj_variants = _subj_variants(subj)
    cat = fam["category"]
    out = []
    seq = 0

    def push(params: dict, zone: str):
        nonlocal seq
        p = _normalize_slot(params) if params.get("slots") else dict(params)
        out.append({"family": fid, "category": cat, "split": fam.get("split"),
                    "zone": zone, "params": p,
                    "text": _make_text(p, cat),
                    "task_id": f"cand_{fid}_{zone}_{seq}"})
        seq += 1

    # 可行/边界：主体变体 × 特征变体（控制数量 ≤ per_family - 不可行数 - 基础盘）
    feats = _feat_variants(cat)
    if not feats:  # basic 族：无特征约束，生成 1 个基础主体候选
        push(subj, "feasible")
        return out
    infeas_n = len(_INFEASIBLE.get(cat, []))
    budget = max(per_family - infeas_n - 1, 2)
    used = 0
    for s in subj_variants:
        if used >= budget:
            break
        for f in feats:
            if used >= budget:
                break
            resolved = _resolve_groove_feats(s, f) if cat == "groove" else f
            zone, _ch = _classify(s, resolved)
            if zone == "infeasible":
                continue  # 不可行单独构造
            params = dict(s)
            params.update(resolved)
            push(params, zone)
            used += 1
    # 不可行（不再强制重标 boundary——边界区只保留真实 margin < BOUNDARY_MARGIN 的候选，
    # 避免 margin 大的候选被虚假标为 boundary）
    for iv in _INFEASIBLE.get(cat, []):
        params = dict(subj)
        params.update(iv)
        push(params, "infeasible")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="三区候选采样器 → candidates.json")
    ap.add_argument("--per-family", type=int, default=12, help="每族候选数（含不可行）")
    ap.add_argument("--family", default=None, help="只采样指定设计族")
    args = ap.parse_args(argv)

    all_cands = []
    for fid, fam in DESIGN_FAMILIES.items():
        if args.family and fid != args.family:
            continue
        all_cands.extend(_sample_family(fid, fam, args.per_family))

    DATASETS.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "candidates_v3", "generated_at": datetime.now().isoformat(timespec="seconds"),
           "per_family": args.per_family, "count": len(all_cands), "candidates": all_cands}
    CAND.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    zc = Counter(c["zone"] for c in all_cands)
    fc = Counter(c["category"] for c in all_cands)
    print(f"候选清单 -> {CAND}  ({len(all_cands)} 个)")
    print(f"  三区分布: {dict(zc)}")
    print(f"  类别分布: {dict(fc)}")
    bad = []
    for c in all_cands:
        for k, (lo, hi) in RANGES.items():
            v = c["params"].get(k)
            if v is not None and not (lo <= v <= hi):
                bad.append((c["task_id"], k, v))
    if bad:
        print(f"  越界参数: {bad[:5]}")
    else:
        print("  参数范围核查: 全部在论文范围内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
