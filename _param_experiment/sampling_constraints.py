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
    """齿根圆角可放空间：root 半宽 = bottom − 1.5 = 0.75×throat − 1.5（模板 slot_profile 槽底根点）。

    圆角半径须 ≤ root 半宽（否则圆角超出槽底可放空间 → BRep_API fillet 失败）。
    模板 bottom = 0.75×throat，root 点半宽 = bottom − 1.5。
    """
    root_half = 0.75 * throat_half_width_mm - 1.5
    return {"ok": fr_mm <= root_half + 0.05, "root_half_width_mm": round(root_half, 3),
            "max_fr_mm": round(max(root_half, 0.3), 3)}


def check_slot_bottom(R_mm: float, depth_mm: float, od_mm: float, mr_mm: float = 3.0) -> dict:
    """榫槽 cutter 槽底不穿出轮缘（模板 pattern radius 用 R_mm 时的几何约束）。

    cutter 从分布半径 R 切入到槽底 R-depth；轮缘内壁半径 rim_junc = od/2 − rim_radial，
    其中 rim_radial ≈ 0.12·od（与模板 disc_profile/_axisym_stations 一致）→ rim_junc = 0.38·od。
    要求 R − depth ≥ rim_junc + mr（槽底剩料 ≥ mr，论文 5.3 hs+mr<=tr 的镜像），
    否则 cutter 切穿轮缘进入腹板、或槽底剩料为 0 导致布尔退化。
    """
    rim_junc = 0.38 * od_mm
    return {"ok": R_mm - depth_mm >= rim_junc + mr_mm, "rim_junc_mm": round(rim_junc, 3),
            "bottom_ligament_mm": round(R_mm - depth_mm - rim_junc, 3)}


def check_all(params: dict, cb: float = 2.0, ch: float = 2.0,
              cs: float = 2.0, mr: float = 3.0) -> dict:
    """对一个采样参数向量做全部相关约束，返回 {ok, checks:[{name, ok, ...}]}。

    params 键：od_mm/bore_mm（主体必填）+ 特征键（holes/pcd_mm/hdia_mm / slots/R_mm/
    throat_half_width_mm/depth_mm/rim_radial_mm）。不存在的特征键跳过（无该特征则视为满足）。
    """
    checks = []
    od = params.get("od_mm")
    bore = params.get("bore_mm")
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
        if params.get("depth_mm") is not None:
            checks.append({"name": "slot_bottom",
                           **check_slot_bottom(params["R_mm"], params["depth_mm"], od)})
        if params.get("fr_mm") is not None:
            checks.append({"name": "slot_root_fillet",
                           **check_slot_root_fillet(params["fr_mm"], params["throat_half_width_mm"])})
    # 环槽
    if params.get("gd_mm") is not None and params.get("rim_radial_mm") is not None:
        checks.append({"name": "groove_depth",
                       **check_groove_depth(params["gd_mm"], params["rim_radial_mm"], mr)})
    # 基础盘无任何特征 → 无约束 → 视为可行（而非 bool([])=False 误判）
    if not checks:
        return {"ok": True, "checks": checks}
    return {"ok": all(c.get("ok") for c in checks), "checks": checks}
