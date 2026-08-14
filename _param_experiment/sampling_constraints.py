"""论文几何约束纯函数（采样前筛查用）。

输入 **参数向量**（非 IR/STEP 后置测量），输出该参数组合是否满足论文几何约束
（论文附件五：孔阵列外边界、相邻孔间距、榫槽周向节距、榫槽深度与轮缘厚度）。
全部确定性、无副作用，可单测。

对应论文公式：
  (1) rp + dh/2 + cb <= rb           孔越界（外边界）＋ 孔不交中心孔（内边界）
  (2) 2·rp·sin(pi/nh) − dh >= ch     相邻孔最小间距
  (3) ws + 2·cs <= ps = 2πRs/Ns     榫槽周向节距（两侧安全裕度）
  (4) hs + mr <= tr                  榫槽深度与轮缘可用径向厚度

几何量推导（从盘体主体参数 od/bore/rim_radial）：
  - rim_radius = od / 2                   轮缘外半径
  - bore_radius = bore / 2                中心孔半径
  - rim_radial（轮缘可用径向厚度 tr）由设计族显式给出（采样参数，论文 25-95mm）
  - slot_width（单槽最大切向宽度 ws）由喉部半宽推导（外宽内窄，lobe≈throat×1.8，
    最大切向宽 ≈ 2×lobe ≈ 3.6×throat；论文 8-32mm）
"""

from __future__ import annotations

import math


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def rim_radius_mm(od_mm: float) -> float:
    return od_mm / 2.0


def bore_radius_mm(bore_mm: float) -> float:
    return bore_mm / 2.0


def slot_width_mm(throat_half_width_mm: float) -> float:
    """单槽最大切向宽度 ws（论文 8-32）。外宽内窄，lobe≈throat×1.8。"""
    return 3.6 * throat_half_width_mm


def check_hole_bounds(pcd_mm: float, hdia_mm: float, od_mm: float,
                      bore_mm: float, cb_mm: float = 2.0) -> dict:
    """孔越界（论文 5.1）：rp + d/2 + cb <= rb，且孔不交中心孔、不越中心孔内边界。

    返回 {ok, outer_ok, inner_ok, min_pcd_mm, max_pcd_mm}。
    """
    r_outer = rim_radius_mm(od_mm)
    r_inner = bore_radius_mm(bore_mm)
    outer_ok = pcd_mm + hdia_mm / 2.0 + cb_mm <= r_outer
    inner_ok = pcd_mm - hdia_mm / 2.0 - cb_mm >= r_inner
    return {
        "ok": outer_ok and inner_ok,
        "outer_ok": outer_ok, "inner_ok": inner_ok,
        "min_pcd_mm": r_inner + hdia_mm / 2.0 + cb_mm,
        "max_pcd_mm": r_outer - hdia_mm / 2.0 - cb_mm,
    }


def check_hole_spacing(count: int, pcd_mm: float, hdia_mm: float, ch_mm: float = 2.0) -> dict:
    """相邻孔最小间距（论文 5.1）：2·rp·sin(pi/nh) − dh >= ch。"""
    if count < 2:
        return {"ok": False, "chord": 0.0, "ligament": -hdia_mm}
    chord = 2.0 * pcd_mm * math.sin(math.pi / count)
    lig = chord - hdia_mm
    return {"ok": lig >= ch_mm, "chord": chord, "ligament": lig}


def check_slot_pitch(slots: int, R_mm: float, throat_half_width_mm: float,
                     cs_mm: float = 2.0) -> dict:
    """榫槽周向节距（论文 5.2）：ws + 2·cs <= ps = 2πR/slots。"""
    if slots < 1:
        return {"ok": False, "pitch": 0.0, "width": slot_width_mm(throat_half_width_mm)}
    pitch = 2.0 * math.pi * R_mm / slots
    ws = slot_width_mm(throat_half_width_mm)
    return {"ok": ws + 2.0 * cs_mm <= pitch, "pitch": pitch, "width": ws}


def check_slot_depth(depth_mm: float, rim_radial_mm: float, mr_mm: float = 3.0) -> dict:
    """榫槽深度与轮缘厚度（论文 5.3）：hs + mr <= tr。"""
    return {"ok": depth_mm + mr_mm <= rim_radial_mm, "tr": rim_radial_mm}


def check_groove_depth(gd_mm: float, rim_radial_mm: float, mg_mm: float = 3.0) -> dict:
    """环槽深度受轮缘可用径向厚度限制（论文 5.4 同类约束）：gd + 剩料 <= tr。"""
    return {"ok": gd_mm + mg_mm <= rim_radial_mm, "tr": rim_radial_mm}


def check_slot_root_fillet(fr_mm: float, throat_half_width_mm: float) -> dict:
    """槽底圆角可放空间：卡榫收窄后平底半宽 = 0.24×throat（fir_tree_slot2d 磨好比例）。

    槽底圆角须 ≤ 平底半宽（否则圆角超出槽底 → BRep_API fillet 失败）。
    保守约束 fr ≤ 平底半宽 − 0.1（磨好 rad_tip 系数 0.3×fr）。
    """
    root_half = 0.24 * throat_half_width_mm
    # 槽底收窄圆角 rad_tip = min(fr×0.5, 1.0) 须 ≤ 平底半宽 → fr ≤ root_half/0.5
    max_fr = max(root_half / 0.5 - 0.1, 0.15)
    return {"ok": fr_mm <= max_fr + 0.05, "root_half_width_mm": round(root_half, 3),
            "max_fr_mm": round(max_fr, 3)}


def check_slot_fillet_space(fr_mm, teeth, depth_mm, throat_half_width_mm,
                            tfa_deg=45.0, ufa_deg=75.0) -> dict:
    """7 组 fillet 全组切线空间约束（OCC fillet2D 失败判据：r·tan(θ/2) > min(L1,L2)）。

    与 param_templates.slot_fillet_fr_limit 同一几何真源（函数内 import 避免模块级循环）。
    """
    from param_templates import slot_fillet_fr_limit
    limit = slot_fillet_fr_limit(teeth, depth_mm, throat_half_width_mm, tfa_deg, ufa_deg)
    return {"ok": fr_mm <= limit + 1e-9, "max_fr_mm": limit}


def check_slot_teeth_space(teeth, depth_mm, throat_half_width_mm,
                           tfa_deg=45.0, ufa_deg=75.0, spare_mm=0.0) -> dict:
    """深度可行范围：槽深须在连接线 neck_platform 可填范围内 [min, max]。

    新几何（fir_tree_slot2d 磨好比例）：深度 = H_neck + 齿区占用 + n×neck_platform + 卡榫底；
    neck_platform 可调 [0.3, 15] 填满深度 → 深度精确匹配（slot_profile._slot2d_solve_depth）。
    超出范围则槽深无法达到 depth_mm → 不可行。与 _slot2d_params 同源。
    """
    m = float(throat_half_width_mm)
    n = int(teeth)
    beta = 90.0 - tfa_deg
    gamma = 90.0 - ufa_deg
    tanb = math.tan(math.radians(beta))
    tang = math.tan(math.radians(gamma))
    h = [(0.36 - 0.08 * i / max(n - 1, 1)) * m for i in range(n)]
    thick = 0.30 * m
    occ = sum(x * tanb + thick + x * tang for x in h)     # 齿区固定占用（不含连接线）
    H_neck = 0.6 * m
    bd = 0.24 * m + 0.16 * m + (0.44 * m - 0.2 * m) / math.tan(math.radians(60.0))
    min_depth = H_neck + occ + n * 0.3 + bd
    max_depth = H_neck + occ + n * 15.0 + bd
    ok = (min_depth - 0.05) <= depth_mm <= (max_depth + 0.05)
    return {"ok": ok, "min_depth_mm": round(min_depth, 3), "max_depth_mm": round(max_depth, 3),
            "used_mm": round(H_neck + occ + n * 0.8 + bd, 3), "avail_mm": depth_mm}


# 盘体形态系数（与 param_templates._RADIAL_FAC 一致，唯一真源在 param_templates；
# 此处副本避免循环 import，改动须同步两边）。
_RADIAL_FAC = {"standard": (0.16, 0.12), "thin_web": (0.16, 0.12),
               "thick_rim": (0.14, 0.17), "large_hub": (0.22, 0.10),
               "conical": (0.16, 0.12)}


def _axisym_radii(od_mm: float, bore_mm: float, form: str = "standard") -> dict:
    """盘体半径推导（与 param_templates._disc_radii 完全一致，按 form 系数）。

    返回 {rim_r, hub_r, rim_junc, web_r}。hub_r 保证腹板存在（hub_r < rim_junc）。
    """
    rim_r = od_mm / 2.0
    h_fac, r_fac = _RADIAL_FAC.get(form, (0.16, 0.12))
    hub_r = bore_mm / 2.0 + _clamp(h_fac * od_mm, 25.0, 100.0)
    rim_junc = rim_r - _clamp(r_fac * od_mm, 25.0, 95.0)
    if hub_r >= rim_junc:
        hub_r = (bore_mm / 2.0 + rim_junc) / 2.0
    return {"rim_r": rim_r, "hub_r": hub_r, "rim_junc": rim_junc,
            "web_r": (hub_r + rim_junc) / 2.0}


def check_lightening_hole_bounds(pcd_mm: float, hdia_mm: float, od_mm: float,
                                 bore_mm: float, cb_mm: float = 2.0,
                                 form: str = "standard") -> dict:
    """减重/冷却孔整体落在腹板段（论文 2.2 减重孔/冷却孔，通孔贯穿腹板）。

    内边界：rp − d/2 − cb ≥ hub_r（不穿轮毂）；外边界：rp + d/2 + cb ≤ rim_junc（不穿轮缘）。
    比 check_hole_bounds（相对中心孔/外径）更严——限死在腹板径向区间内。
    """
    r = _axisym_radii(od_mm, bore_mm, form)
    inner_ok = pcd_mm - hdia_mm / 2.0 - cb_mm >= r["hub_r"]
    outer_ok = pcd_mm + hdia_mm / 2.0 + cb_mm <= r["rim_junc"]
    return {
        "ok": inner_ok and outer_ok, "inner_ok": inner_ok, "outer_ok": outer_ok,
        "min_pcd_mm": r["hub_r"] + hdia_mm / 2.0 + cb_mm,
        "max_pcd_mm": r["rim_junc"] - hdia_mm / 2.0 - cb_mm,
        "hub_r_mm": round(r["hub_r"], 3), "rim_junc_mm": round(r["rim_junc"], 3),
    }


def check_rim_slot_pitch(rs_count: int, rs_half_width_mm: float, od_mm: float,
                         cs_mm: float = 2.0) -> dict:
    """径向局部切槽周向节距：槽宽(2×半宽) + 2·cs ≤ 节距 = 2π·rim_r/rs_count。

    （论文 5.2 榫槽节距同类约束；切槽在轮缘外表面，rim_r = od/2。）
    """
    if rs_count < 2:
        return {"ok": False, "pitch": 0.0, "width": 2 * rs_half_width_mm}
    pitch = 2.0 * math.pi * (od_mm / 2.0) / rs_count
    return {"ok": 2.0 * rs_half_width_mm + 2.0 * cs_mm <= pitch,
            "pitch": pitch, "width": 2 * rs_half_width_mm}


def check_annular_cavity(cavity_width_mm: float, cavity_depth_mm: float, od_mm: float,
                         bore_mm: float, thick_mm: float, m: float = 2.0,
                         form: str = "standard") -> dict:
    """腹板环形腔（论文 2.2 局部减重结构）：径向落在腹板段、轴向不切穿。

    径向：web_r ± cw/2 须在 hub_r 与 rim_junc 之间留剩料 m；
    轴向：腔深 ≤ 腹板轴向厚的一半（腹板 z 区间 z_web1→z_web2 = 0.2·thick→0.35·thick，
    轴向厚 0.15·thick，从端面切入 depth，留剩料 → depth ≤ 0.075·thick）。
    """
    r = _axisym_radii(od_mm, bore_mm, form)
    max_width = 2.0 * min(r["web_r"] - r["hub_r"] - m, r["rim_junc"] - r["web_r"] - m)
    max_depth = 0.075 * thick_mm
    return {"ok": cavity_width_mm <= max_width + 1e-9 and cavity_depth_mm <= max_depth + 1e-9,
            "max_width_mm": round(max(max_width, 0), 3),
            "max_depth_mm": round(max_depth, 3),
            "web_r_mm": round(r["web_r"], 3)}


def check_double_row_spacing(pcd1_mm: float, pcd2_mm: float, hdia_mm: float,
                             ch_mm: float = 2.0) -> dict:
    """双排孔阵列径向间距：两排孔不重叠（|rp1−rp2| ≥ hdia + ch）。"""
    sep = abs(pcd1_mm - pcd2_mm)
    return {"ok": sep >= hdia_mm + ch_mm, "sep_mm": round(sep, 3),
            "min_sep_mm": hdia_mm + ch_mm}


def check_slot_bottom(depth_mm: float, od_mm: float, mr_mm: float = 3.0,
                      form: str = "standard") -> dict:
    """榫槽 cutter 槽底不穿出轮缘（pattern radius = rim_r，槽口在轮缘外表面）。

    cutter 槽口在轮缘外表面 rim_r = od/2，槽底在 rim_r − depth；
    轮缘内壁半径 rim_junc 按 form 系数（与盘体轮廓一致）。
    要求 rim_r − depth ≥ rim_junc + mr（槽底剩料 ≥ mr，论文 5.3 hs+mr<=tr 的镜像），
    否则 cutter 切穿轮缘进入腹板、或槽底剩料为 0 导致布尔退化。
    """
    rim_r = od_mm / 2.0
    _, r_fac = _RADIAL_FAC.get(form, (0.16, 0.12))
    rim_junc = max(rim_r - _clamp(r_fac * od_mm, 25.0, 95.0), 0.38 * od_mm)
    return {"ok": rim_r - depth_mm >= rim_junc + mr_mm, "rim_junc_mm": round(rim_junc, 3),
            "bottom_ligament_mm": round(rim_r - depth_mm - rim_junc, 3)}


def check_all(params: dict, cb: float = 2.0, ch: float = 2.0,
              cs: float = 2.0, mr: float = 3.0) -> dict:
    """对一个采样参数向量做全部相关约束，返回 {ok, checks:[{name, ok, ...}]}。

    params 键：od_mm/bore_mm（主体必填）+ 特征键（holes/pcd_mm/hdia_mm / slots/R_mm/
    throat_half_width_mm/depth_mm/rim_radial_mm）。不存在的特征键跳过（无该特征则视为满足）。
    """
    checks = []
    od = params.get("od_mm")
    bore = params.get("bore_mm")
    form = params.get("form", "standard")
    if od is None or bore is None:
        return {"ok": False, "checks": checks, "error": "缺 od_mm/bore_mm"}
    # 孔
    if params.get("holes") is not None and params.get("pcd_mm") is not None \
            and params.get("hdia_mm") is not None:
        checks.append({"name": "hole_bounds",
                       **check_hole_bounds(params["pcd_mm"], params["hdia_mm"], od, bore, cb)})
        checks.append({"name": "hole_spacing",
                       **check_hole_spacing(int(params["holes"]), params["pcd_mm"], params["hdia_mm"], ch)})
    # 榫槽
    if params.get("slots") is not None and params.get("R_mm") is not None \
            and params.get("throat_half_width_mm") is not None:
        checks.append({"name": "slot_pitch",
                       **check_slot_pitch(int(params["slots"]), params["R_mm"],
                                          params["throat_half_width_mm"], cs)})
        if params.get("depth_mm") is not None and params.get("rim_radial_mm") is not None:
            checks.append({"name": "slot_depth",
                           **check_slot_depth(params["depth_mm"], params["rim_radial_mm"], mr)})
            # 深窄型：槽深 ≥ 0.55×rim_radial（槽切透轮缘，参考实例深/轮缘高 60-70%）
            checks.append({"name": "slot_depth_ratio",
                           "ok": params["depth_mm"] >= 0.55 * params["rim_radial_mm"] - 1e-9,
                           "min_depth_mm": round(0.55 * params["rim_radial_mm"], 3)})
        if params.get("depth_mm") is not None:
            checks.append({"name": "slot_bottom",
                           **check_slot_bottom(params["depth_mm"], od, form=form)})
        if params.get("fr_mm") is not None:
            checks.append({"name": "slot_root_fillet",
                           **check_slot_root_fillet(params["fr_mm"], params["throat_half_width_mm"])})
        if params.get("fr_mm") is not None and params.get("teeth") is not None \
                and params.get("depth_mm") is not None:
            # P6：5 组 fillet 切线空间 + 角度驱动齿区占用（与 slot_fillet_fr_limit 同源）
            checks.append({"name": "slot_fillet_space",
                           **check_slot_fillet_space(params["fr_mm"], params["teeth"],
                                                     params["depth_mm"],
                                                     params["throat_half_width_mm"],
                                                     params.get("tfa_deg", 80.0),
                                                     params.get("ufa_deg", 70.0))})
            checks.append({"name": "slot_teeth_space",
                           **check_slot_teeth_space(params["teeth"], params["depth_mm"],
                                                    params["throat_half_width_mm"],
                                                    params.get("tfa_deg", 80.0),
                                                    params.get("ufa_deg", 70.0))})
    # 环槽（起点=rim_junc 轮缘内壁表面，web-rim fillet 已减到 r=4 释放空间）
    if params.get("gd_mm") is not None and params.get("rim_radial_mm") is not None:
        checks.append({"name": "groove_depth",
                       **check_groove_depth(params["gd_mm"], params["rim_radial_mm"], mr)})
    # 环槽-孔径向间隙：孔/冷却孔整体落在 rim_junc−gd−gap 内侧（不碰轮缘内壁环槽）。
    # 否则孔 16 边形边与环槽台阶曲面布尔产生 <0.25mm 退化小边（MCP check_degenerate_geometry 拦截）。
    if params.get("grooves") and params.get("gd_mm") is not None:
        rim_junc = _axisym_radii(od, bore, form)["rim_junc"]
        for key, dia_key in (("pcd_mm", "hdia_mm"), ("lh_pcd_mm", "lh_hdia_mm"),
                             ("cl_pcd_mm", "cl_hdia_mm"), ("cl_pcd2_mm", "cl_hdia_mm")):
            if params.get(key) is not None and params.get(dia_key):
                dia = params[dia_key]
                limit = rim_junc - params["gd_mm"] - dia / 2.0 - 2.0
                checks.append({"name": f"{key}_groove_clearance",
                               "ok": params[key] <= limit + 1e-9,
                               "limit_mm": round(limit, 3)})
    # 孔边避开 web-rim fillet 弧（r∈[rim_junc−12, rim_junc]，盘体 _sketch_disc_body 顶点 3/8
    # r=10 fillet + 2 余量）。16 边形孔边与 fillet 曲面布尔产生 <0.25mm 退化小边
    # （D23 孔 pcd=176 边缘 182 入弧 → 96 微边；pcd=170 边缘 176 无）。孔边缘 < rim_junc
    # （腹板/轮缘内侧孔）时须 ≤ rim_junc−12；完全在轮缘的孔（inner ≥ rim_junc）不受限。
    for key, dia_key in (("pcd_mm", "hdia_mm"), ("lh_pcd_mm", "lh_hdia_mm"),
                         ("cl_pcd_mm", "cl_hdia_mm"), ("cl_pcd2_mm", "cl_hdia_mm")):
        if params.get(key) is not None and params.get(dia_key):
            rim_junc = _axisym_radii(od, bore, form)["rim_junc"]
            outer = params[key] + params[dia_key] / 2.0
            inner = params[key] - params[dia_key] / 2.0
            ok = outer <= rim_junc - 12.0 or inner >= rim_junc
            checks.append({"name": f"{key}_fillet_clearance", "ok": ok,
                           "limit_mm": round(rim_junc - 12.0, 3)})
    # 减重孔/冷却孔（腹板段，论文 2.2）
    if params.get("lh_holes") is not None and params.get("lh_pcd_mm") is not None \
            and params.get("lh_hdia_mm") is not None:
        checks.append({"name": "lh_hole_bounds",
                       **check_lightening_hole_bounds(params["lh_pcd_mm"], params["lh_hdia_mm"], od, bore, cb, form)})
        checks.append({"name": "lh_hole_spacing",
                       **check_hole_spacing(int(params["lh_holes"]), params["lh_pcd_mm"],
                                            params["lh_hdia_mm"], ch)})
    if params.get("cl_holes") is not None and params.get("cl_pcd_mm") is not None \
            and params.get("cl_hdia_mm") is not None:
        checks.append({"name": "cl_hole_bounds",
                       **check_lightening_hole_bounds(params["cl_pcd_mm"], params["cl_hdia_mm"], od, bore, cb, form)})
        checks.append({"name": "cl_hole_spacing",
                       **check_hole_spacing(int(params["cl_holes"]), params["cl_pcd_mm"],
                                            params["cl_hdia_mm"], ch)})
        if params.get("cl_pcd2_mm") is not None:
            checks.append({"name": "cl_double_row_spacing",
                           **check_double_row_spacing(params["cl_pcd_mm"], params["cl_pcd2_mm"],
                                                      params["cl_hdia_mm"], ch)})
    # 减重孔与冷却孔径向分开（D14 曾 lh_pcd=200 与 cl_pcd=202.9 边缘重叠）
    if params.get("lh_pcd_mm") is not None and params.get("cl_pcd_mm") is not None \
            and params.get("lh_hdia_mm") is not None and params.get("cl_hdia_mm") is not None:
        dia = max(params["lh_hdia_mm"], params["cl_hdia_mm"])
        checks.append({"name": "lh_cl_spacing",
                       **check_double_row_spacing(params["lh_pcd_mm"], params["cl_pcd_mm"], dia, ch)})
    # 径向局部切槽（轮缘外表面）
    if params.get("rs_count") is not None and params.get("rs_depth_mm") is not None:
        rim_rad = params.get("rim_radial_mm") or _clamp(0.12 * od, 25.0, 95.0)
        # U 形槽底圆弧计入总深（_rim_slot_cutter arc_r = min(0.6w, 0.4×depth)）
        arc = min(max(0.6 * (params.get("rs_half_width_mm") or 2.0), 1.0),
                  0.4 * params["rs_depth_mm"])
        checks.append({"name": "rim_slot_depth",
                       **check_groove_depth(params["rs_depth_mm"] + arc, rim_rad, mr)})
        if params.get("rs_half_width_mm") is not None:
            checks.append({"name": "rim_slot_pitch",
                           **check_rim_slot_pitch(int(params["rs_count"]), params["rs_half_width_mm"], od, cs)})
    # 腹板环形腔（局部减重结构）
    if params.get("cavity_width_mm") is not None and params.get("cavity_depth_mm") is not None:
        checks.append({"name": "annular_cavity",
                       **check_annular_cavity(params["cavity_width_mm"], params["cavity_depth_mm"],
                                              od, bore, params.get("thick_mm", 76.0), form=form)})
        # 环形腔避开孔（孔轴向贯穿，腔为半深环形槽，二者重叠会互相打断 → 腔形状破碎）。
        # 腔外径 ≤ 最内孔内缘 − gap（腔整体在孔内侧）。
        _pcds = [params[k] for k in ("pcd_mm", "lh_pcd_mm", "cl_pcd_mm", "cl_pcd2_mm")
                 if params.get(k) is not None]
        _dias = [params[k] for k in ("hdia_mm", "lh_hdia_mm", "cl_hdia_mm", "cl_hdia_mm")
                 if params.get(k) is not None]
        if _pcds and _dias:
            inner = min(_pcds) - max(_dias) / 2.0 - 2.0
            cav_r = _axisym_radii(od, bore, form)["web_r"] + params["cavity_width_mm"] / 2.0
            checks.append({"name": "cavity_hole_clearance",
                           "ok": cav_r <= inner + 1e-9, "limit_mm": round(inner, 3)})
    # 基础盘无任何特征 → 无约束 → 视为可行（而非 bool([])=False 误判）
    if not checks:
        return {"ok": True, "checks": checks}
    return {"ok": all(c.get("ok") for c in checks), "checks": checks}
