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
import math
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
    "grooves": (1, 3), "gw_mm": (2, 10), "gd_mm": (6, 22),  # gw 上限 10：环槽轴向高度与轮缘整体（2×rim_half）适配；gd 下限 6：径向切除厚度适配
    "slots": (24, 96), "teeth": (2, 4), "R_mm": (180, 300),
    "depth_mm": (12, 60), "throat_half_width_mm": (2, 9), "fr_mm": (0.5, 4.0),
    # 减重结构（论文 2.2）：减重孔/冷却孔复用孔阵列范围；切槽/环形腔为新增特征
    "lh_holes": (6, 36), "lh_pcd_mm": (80, 310), "lh_hdia_mm": (4, 26),
    "cl_holes": (6, 36), "cl_pcd_mm": (80, 310), "cl_hdia_mm": (4, 26),
    "rs_count": (12, 96), "rs_depth_mm": (4, 20), "rs_half_width_mm": (1, 6),
    "cavity_width_mm": (8, 60), "cavity_depth_mm": (2, 6),  # 下限 8：环形腔避开孔后可能较窄（guideline）
    "rim_arc_radius_mm": (12, 30),
}
BOUNDARY_MARGIN = 5.0  # 剩料 margin < 5mm 视为边界区（真实贴近约束边界）

# design_families.features 键 → 模板参数键（_mm 后缀）。族名义特征经此转换落到采样/生成。
_FEAT_KEY_MAP = {
    "R": "R_mm", "depth": "depth_mm", "throat": "throat_half_width_mm", "fr": "fr_mm",
    "pcd": "pcd_mm", "hdia": "hdia_mm",
    "gw": "gw_mm", "gd": "gd_mm",
    "lh_pcd": "lh_pcd_mm", "lh_hdia": "lh_hdia_mm",
    "cl_pcd": "cl_pcd_mm", "cl_hdia": "cl_hdia_mm", "cl_pcd2": "cl_pcd2_mm",
    "rs_depth": "rs_depth_mm", "rs_half_width": "rs_half_width_mm",
    "cavity_width": "cavity_width_mm", "cavity_depth": "cavity_depth_mm",
    "rim_arc_radius": "rim_arc_radius_mm",
}


def fam_features(fam: dict) -> dict:
    """设计族定义的 features → 模板参数键（族名义特征，candidate_sampler 优先采用）。

    保证每族第一个候选 = 设计族定义的真实结构组合（D14 双排冷却孔 /
    D19 三齿 / D23 榫槽+孔+环槽），而非通用变体的低端组合。
    """
    return {_FEAT_KEY_MAP.get(k, k): v for k, v in (fam.get("features") or {}).items()}


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
    # rim_radial 按 form 系数（thick_rim=0.17 等，与盘体 _disc_radii 一致）——
    # 此前固定 0.12 使 thick_rim 盘 rim_radial 低估（64.8 vs 实际 91.8）→ depth 约束误判。
    from sampling_constraints import _axisym_radii
    _r = _axisym_radii(od, bore, fam.get("form", "standard"))
    return {"od_mm": od, "bore_mm": bore, "thick_mm": thick,
            "hub_mm": hub, "rim_mm": rim,
            "rim_radial_mm": round(_r["rim_r"] - _r["rim_junc"], 1),
            "form": fam.get("form", "standard")}


def _subj_variants(subj: dict) -> list:
    """主体变体：base + od ±20% + bore ±20%（落范围），供少量覆盖。"""
    from sampling_constraints import _axisym_radii
    base = dict(subj)
    out = [base]
    for key, scale in (("od_mm", 0.8), ("od_mm", 1.2), ("bore_mm", 0.7), ("bore_mm", 1.5)):
        v = dict(base)
        v[key] = round(_clamp(base[key] * scale, *RANGES[key]), 1)
        _rv = _axisym_radii(v["od_mm"], v["bore_mm"], subj.get("form", "standard"))
        v["rim_radial_mm"] = round(_rv["rim_r"] - _rv["rim_junc"], 1)
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
    {"grooves": 1, "gw_mm": 6, "gd_mm": 7},                            # 低端（仅环槽）
    {"grooves": 2, "gw_mm": 7, "gd_mm": 9},                            # 中（仅环槽）
    {"grooves": 1, "gw_mm": 7, "gd_mm": 8, "lh_holes": 12,
     "lh_hdia_mm": 16, "lh_pcd_frac": 0.35},                           # 环槽+减重孔
    {"grooves": 2, "gw_mm": 7, "gd_mm": 9, "cl_holes": 24,
     "cl_hdia_mm": 6, "cl_pcd_frac": 0.65},                            # 环槽+冷却孔
    {"grooves": 1, "gw_mm": 8, "gd_mm": 12, "rs_count": 60,
     "rs_depth_mm": 10, "rs_half_width_mm": 3},                        # 环槽+径向切槽
    {"grooves": 2, "gw_mm": 8, "gd_mm": 12, "lh_holes": 16, "lh_hdia_mm": 14,
     "lh_pcd_frac": 0.4, "cl_holes": 30, "cl_hdia_mm": 5,
     "cl_pcd_frac": 0.75},                                             # 环槽+减重孔+冷却孔
    {"grooves": 2, "gw_mm": 7, "gd_mm": 8, "lh_holes": 24, "lh_hdia_mm": 12,
     "lh_pcd_frac": 0.45, "cl_holes": 36, "cl_hdia_mm": 5,
     "cl_pcd_frac": 0.3, "cl_pcd2_frac": 0.8},                        # 环槽+减重孔+双排冷却孔
]


def _resolve_groove_feats(subj: dict, tpl: dict) -> dict:
    """groove 减重模板：把 pcd_frac（腹板段比例）解析为绝对 pcd_mm（_axisym_radii）。"""
    from sampling_constraints import _axisym_radii
    r = _axisym_radii(subj["od_mm"], subj["bore_mm"], subj.get("form", "standard"))
    f = dict(tpl)

    def _resolve(key: str, frac_key: str):
        if frac_key in f:
            fr = f.pop(frac_key)
            f[key] = round(r["hub_r"] + fr * (r["rim_junc"] - r["hub_r"]), 1)

    _resolve("lh_pcd_mm", "lh_pcd_frac")
    _resolve("cl_pcd_mm", "cl_pcd_frac")
    _resolve("cl_pcd2_mm", "cl_pcd2_frac")
    return f
# 榫槽变体：深度与轮缘径向高匹配（depth ≈ 0.55-0.85×rim_radial，深窄型槽切透轮缘，
# 论文 5.3 depth+mr<=tr；实例深 53/窄 12.3/深宽比 4.3）；throat 3.5-5；fr 2-2.5。
_SLOT_VARIANTS = [
    {"slots": 48, "teeth": 2, "R_mm": 220, "depth_mm": 36, "throat_half_width_mm": 4.0, "fr_mm": 2.0},
    {"slots": 60, "teeth": 3, "R_mm": 230, "depth_mm": 42, "throat_half_width_mm": 4.0, "fr_mm": 2.0},
    {"slots": 72, "teeth": 3, "R_mm": 240, "depth_mm": 48, "throat_half_width_mm": 4.5, "fr_mm": 2.5},
    {"slots": 90, "teeth": 4, "R_mm": 250, "depth_mm": 54, "throat_half_width_mm": 5.0, "fr_mm": 2.5},
]

# 不可行变体（参数落论文范围但普遍违反几何约束；zone 由 check_all 判定）
_INFEASIBLE = {
    "hole": [
        {"holes": 36, "pcd_mm": 80, "hdia_mm": 26},      # 孔间剩料必负（pcd 下限+hdia 上限+n 上限）
    ],
    "groove": [
        # 减重孔 pcd 过低（落在轮毂段，check_lightening_hole_bounds 内边界必违，参数仍在论文范围）
        {"grooves": 1, "gw_mm": 4, "gd_mm": 8, "lh_holes": 24,
         "lh_pcd_mm": 80, "lh_hdia_mm": 20},
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
        # 补全"榫槽+孔+环槽"完整耦合变体（此前无同时含 holes+grooves 的 → D23-D28 无环槽）
        return list(_SLOT_VARIANTS) + [
            {"slots": 48, "teeth": 2, "R_mm": 220, "depth_mm": 24,
             "throat_half_width_mm": 4.0, "fr_mm": 1.5,
             "holes": 12, "pcd_mm": 200, "hdia_mm": 12},
            {"slots": 60, "teeth": 3, "R_mm": 240, "depth_mm": 30,
             "throat_half_width_mm": 4.0, "fr_mm": 2.0,
             "grooves": 1, "gw_mm": 4, "gd_mm": 6},
            {"slots": 60, "teeth": 2, "R_mm": 230, "depth_mm": 28,
             "throat_half_width_mm": 4.0, "fr_mm": 2.0,
             "holes": 16, "pcd_mm": 210, "hdia_mm": 12,
             "grooves": 1, "gw_mm": 4, "gd_mm": 6},
        ]
    if cat == "complex_rim":
        # 曲线过渡盘体（论文 2.1）：各槽参数变体 + 过渡类型/幅度（族间曲线结构不同）
        out = []
        for t in _SLOT_VARIANTS + [
                {"slots": 84, "teeth": 3, "R_mm": 250, "depth_mm": 36,
                 "throat_half_width_mm": 5.0, "fr_mm": 2.0}]:
            for arc, tr in ((12.0, "s_curve"), (20.0, "ellipse"), (28.0, "power")):
                out.append({**t, "rim_arc_radius_mm": arc, "transition": tr})
        return out
    return []  # basic


_AXISYM_CATS = ("basic", "hole", "groove")  # axisym 盘体（3 段轴向近似）不承诺精确半厚


_FORM_LABEL = {"standard": "标准", "thin_web": "薄腹板", "thick_rim": "厚轮缘",
               "large_hub": "大轮毂", "conical": "锥形腹板"}


def _make_text(params: dict, cat: str) -> str:
    """采样参数向量 → 需求文本（措辞对齐 RE_PARAMS 正则）。

    axisym 盘（basic/hole/groove）几何为 3 段轴向近似，不表达精确轮毂/轮缘半厚，
    故文本不承诺 hub/rim（避免文本↔几何不一致）；sketch_profile 榫槽盘保留。
    """
    form = params.get("form", "standard")
    p = [f"生成一个{_FORM_LABEL.get(form, '')}高压涡轮盘参考几何：{CATEGORY_LABEL[cat]}",
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
        # 槽底剩料≥3：R−depth ≥ rim_junc+3。rim_junc 按 form 系数（large_hub=0.40od > standard 0.38od，
        # 否则 D21/D27 槽底穿轮缘内壁 → 布尔退化）。论文 R 下限 180。
        from sampling_constraints import _axisym_radii
        _r = _axisym_radii(p["od_mm"], p["bore_mm"], p.get("form", "standard"))
        lo = max(_r["rim_junc"] + p["depth_mm"] + 3.0, 180.0)
        hi = min(p["od_mm"] / 2.0, 300.0)  # 论文 R 上限 300
        # min(max(v,lo),hi)：lo<=hi 时正常 clamp；lo>hi（无法同时满足剩料与论文 R 上限）→ 取 hi，
        # 由 check_slot_bottom 判该候选不可行（不产生超论文范围的 R）
        p["R_mm"] = round(min(max(p["R_mm"], lo), hi), 3)
    if p.get("slots") and p.get("fr_mm") is not None and p.get("throat_half_width_mm") is not None:
        # 槽底平底半宽 = 0.875×throat（mon 基准），圆角上限 = root_half−0.3（与模板一致）
        root_half = 0.875 * p["throat_half_width_mm"]
        p["fr_mm"] = round(min(p["fr_mm"], max(root_half - 0.3, 0.3)), 3)
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
    # 0. 族名义候选（优先）：设计族定义的真实特征组合 → 每族第一个候选 = 完整结构
    #    （D14 双排冷却孔 / D19 三齿 / D23 榫槽+孔+环槽），preview 取第一候选时即展示完整特征。
    fam_feat = fam_features(fam)
    if fam_feat and cat in ("groove", "coupled"):
        # 族名义孔 pcd 固定值可能越腹板段/碰轮缘内壁环槽 → clamp 到 rim_junc−gd−gap 内侧
        # （结构不变，避免孔 16 边形边与环槽台阶曲面布尔产生 <0.25mm 退化小边）。
        # cl 双排先定外排 cl_pcd2 再定内排 cl_pcd（保双排间距 ≥ hdia + ch）。
        from sampling_constraints import _axisym_radii
        _r = _axisym_radii(subj["od_mm"], subj["bore_mm"], subj.get("form", "standard"))
        gd = fam_feat.get("gd_mm", 0.0)  # 环槽深，孔须在其内侧留间隙

        # 孔/冷却孔避开 web-rim fillet 弧（rim_junc−12）+ 环槽（gd+2）——取较严边界，
        # 避免 16 边形孔边与 fillet/环槽曲面布尔退化小边。
        # gap≥14：孔外缘距 rim_junc ≥14mm。原 gap=12 时 outer=rim_junc−12 恰为
        # fillet_clearance 精确边界 → D26 孔边与上端面 fillet 弧边界布尔产生 0.2mm 微边。
        gap = max(gd + 2.0, 14.0)

        def _clamp_pcd(key, dia):
            if fam_feat.get(key) is not None and dia:
                hi = _r["rim_junc"] - gap - dia / 2.0
                fam_feat[key] = round(min(fam_feat[key], max(hi, 0.0)), 1)

        _clamp_pcd("pcd_mm", fam_feat.get("hdia_mm"))
        cdia = fam_feat.get("cl_hdia_mm")
        _clamp_pcd("cl_pcd2_mm", cdia)
        if fam_feat.get("cl_pcd_mm") is not None and cdia:
            hi = _r["rim_junc"] - gap - cdia / 2.0
            if fam_feat.get("cl_pcd2_mm") is not None:
                hi = min(hi, fam_feat["cl_pcd2_mm"] - cdia - 2.0)  # 保双排间距
            fam_feat["cl_pcd_mm"] = round(min(fam_feat["cl_pcd_mm"], max(hi, 0.0)), 1)
        # 减重孔在冷却孔内侧（cl 外侧优先），间距 ≥ max(hdia, cdia)+2（避免 D14 孔重叠）
        if fam_feat.get("lh_pcd_mm") is not None and fam_feat.get("cl_pcd_mm") is not None \
                and fam_feat.get("lh_hdia_mm") and cdia:
            spacing = max(fam_feat["lh_hdia_mm"], cdia) + 2.0
            hi_lh = fam_feat["cl_pcd_mm"] - spacing
            fam_feat["lh_pcd_mm"] = round(min(fam_feat["lh_pcd_mm"], max(hi_lh, 0.0)), 1)
        else:
            _clamp_pcd("lh_pcd_mm", fam_feat.get("lh_hdia_mm"))
        # 环形腔避开孔（腔外径 ≤ 最内孔内缘 − gap → 收缩腔宽）
        if fam_feat.get("cavity_width_mm") is not None:
            _pc = [fam_feat[k] for k in ("pcd_mm", "lh_pcd_mm", "cl_pcd_mm", "cl_pcd2_mm")
                   if fam_feat.get(k) is not None]
            _dia = [fam_feat[k] for k in ("hdia_mm", "lh_hdia_mm", "cl_hdia_mm", "cl_hdia_mm")
                    if fam_feat.get(k) is not None]
            if _pc and _dia:
                inner = min(_pc) - max(_dia) / 2.0 - 2.0
                max_w = 2.0 * (inner - _r["web_r"])
                fam_feat["cavity_width_mm"] = round(min(fam_feat["cavity_width_mm"],
                                                        max(max_w, 0.0)), 1)
    if fam_feat:
        # 族名义榫槽深度提高：≥ 0.55×rim_radial（深窄型，槽切透轮缘；上限 rim_radial−3）。
        # 用 ceil 到 0.1 避免舍入后 < 0.55×rim_radial（D24 34.32→round 34.3 < 34.32 被 slot_depth_ratio 拒）。
        if fam_feat.get("depth_mm") and subj.get("rim_radial_mm"):
            rr = subj["rim_radial_mm"]
            d = max(0.55 * rr, min(fam_feat["depth_mm"], rr - 3.0))
            fam_feat["depth_mm"] = math.ceil(round(d * 10, 3)) / 10.0
        zone, _ch = _classify(subj, fam_feat)
        if zone == "infeasible" and fam_feat.get("slots"):
            # 族名义不可行（如 96 槽节距不足）：递减 slots 到可行，保持 teeth/depth 族名义
            for ns in (int(fam_feat["slots"]), 90, 84, 72, 60, 48, 36, 24):
                fam_feat["slots"] = ns
                zone, _ch = _classify(subj, fam_feat)
                if zone != "infeasible":
                    break
        if zone != "infeasible":
            params = dict(subj)
            params.update(fam_feat)
            push(params, zone)
            used += 1
        else:
            print(f"  [{fid}] 族名义特征不可行，回退通用变体")
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
