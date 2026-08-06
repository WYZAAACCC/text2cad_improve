"""确定性参数化模板：设计族参数 → 合法 RawGcadDocument（llm_raw）。

用户流程：llm_raw 由确定性参数化模板生成（非 LLM），同族种子改参数得不同 llm_raw，
经 validation/repair/runtime/MCP 门采集数据；LLM 只用于生成三种描述。

蓝本：
  - 榫槽盘（sketch_profile 盘体 + slot_cutter + composition 布尔）：
    app/text-to-cad/server/output/mon_sweep_g1_baseline/raw_fixed.json
  - 盘型（axisymmetric 单组件）：
    demo_output_v5/v6_full35_output/tm01_flange_cover/raw_fixed.json

模板函数输入 design_families 风格参数，输出 RawGcadDocument dict（结构固定，参数可替换）。
独立于主流程/src；生成结果用 run_gcad_core_from_files 验证（validation+runtime）。

用法:
  .conda/python.exe -c "import param_templates as pt; doc=pt.build(pt.DEMO_SLOT); print('OK', len(doc['nodes']))"
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ═══════════════════════════════════════════════════════════════════════════════
# 盘体几何推导（od/bore/thick/hub/rim → 12 点 R-Z 轮廓）
# ═══════════════════════════════════════════════════════════════════════════════

# 盘体形态（几何结构差异——族间不只是参数不同，论文泛化/丰富性要求）
#   standard    标准 hub-web-rim（hub 径向 0.16od，rim 径向 0.12od，web 厚 0.5-0.6×半厚）
#   thin_web    薄腹板（web 轴向厚仅 0.3-0.35×半厚，腹板更轻）
#   thick_rim   厚轮缘（rim 径向高 0.17od，轮缘更厚重）
#   large_hub   大轮毂（hub 径向高 0.22od，轮毂更大）
#   conical      锥形腹板（web 斜面更陡，腹板呈锥形）
DISC_FORMS = ("standard", "thin_web", "thick_rim", "large_hub", "conical")
_RADIAL_FAC = {"standard": (0.16, 0.12), "thin_web": (0.16, 0.12),
               "thick_rim": (0.14, 0.17), "large_hub": (0.22, 0.10),
               "conical": (0.16, 0.12)}


def _disc_radii(od_mm, bore_mm, form="standard") -> dict:
    """盘体半径推导唯一真源——disc_profile 轮廓、build_axisym_disc 特征、
    sampling_constraints 约束全部用同一组半径（消除此前 build_axisym 硬编码
    0.12 系数导致的 rim_junc 偏差，如 thick_rim 偏差 -27mm）。

    返回 {bore_r, rim_r, hub_r, rim_junc, web_r, hub_radial, rim_radial}。
    """
    bore_r = bore_mm / 2.0
    rim_r = od_mm / 2.0
    h_fac, r_fac = _RADIAL_FAC.get(form, (0.16, 0.12))
    hub_radial = _clamp(h_fac * od_mm, 25.0, 100.0)
    rim_radial = _clamp(r_fac * od_mm, 25.0, 95.0)
    hub_r = bore_r + hub_radial
    rim_junc = rim_r - rim_radial
    if hub_r >= rim_junc:  # 保证腹板存在
        hub_r = (bore_r + rim_junc) / 2.0
    return {"bore_r": bore_r, "rim_r": rim_r, "hub_r": hub_r, "rim_junc": rim_junc,
            "web_r": (hub_r + rim_junc) / 2.0,
            "hub_radial": hub_radial, "rim_radial": rim_radial}


def _transition_pts(rim_junc, z0, z1, t, kind, n=4) -> list:
    """轮缘内壁 (rim_junc, z0)→(rim_junc, z1) 垂直台阶间插入过渡点（z 单调）。

    complex_rim 族用多点逼近曲线过渡（取代单一 fillet 圆弧，满足论文"丰富过渡"）。
    kind：linear=无插入 / arc_in=内凹弧 / arc_out=外凸弧 / s_curve=S形 /
    power=幂曲线 / ellipse=椭圆弧。返回 [(r, z), ...]（不含两端）。
    """
    if t <= 0 or kind == "linear":
        return []
    out = []
    for i in range(1, n + 1):
        u = i / (n + 1)
        z = z0 + (z1 - z0) * u
        if kind == "arc_in":
            r = rim_junc - t * math.sin(math.pi * u)
        elif kind == "arc_out":
            r = rim_junc + 0.5 * t * math.sin(math.pi * u)
        elif kind == "s_curve":
            r = rim_junc - t * math.sin(2 * math.pi * u)
        elif kind == "power":
            r = rim_junc - t * (1.0 - u) ** 1.5
        elif kind == "ellipse":
            r = rim_junc - t * math.cos(math.pi * u / 2.0)
        else:
            r = rim_junc
        out.append((round(r, 3), round(z, 3)))
    return out


def disc_profile(od_mm, bore_mm, hub_half_mm, rim_half_mm, thick_mm,
                 web_inner_half=None, web_outer_half=None, form="standard",
                 transition="linear") -> dict:
    """盘体 R-Z 轮廓（闭合顺序，关于 y=0 对称）→ {points, params}。

    径向站：bore_r → hub_r → rim_junc → rim_r。形态决定 hub/rim 径向高度与 web 厚度，
    使不同设计族（薄腹板/厚轮缘/大毂/锥形）轮廓结构可区分，而非仅尺寸参数不同。
    """
    _r = _disc_radii(od_mm, bore_mm, form)
    bore_r, rim_r = _r["bore_r"], _r["rim_r"]
    hub_r, rim_junc = _r["hub_r"], _r["rim_junc"]
    hub_radial, rim_radial = _r["hub_radial"], _r["rim_radial"]
    if form == "thin_web":
        web_inner = web_inner_half if web_inner_half else _clamp(0.35 * hub_half_mm, 5.0, 22.0)
        web_outer = web_outer_half if web_outer_half else _clamp(0.3 * rim_half_mm, 4.0, 18.0)
    else:
        web_inner = web_inner_half if web_inner_half else _clamp(0.6 * hub_half_mm, 8.0, 40.0)
        web_outer = web_outer_half if web_outer_half else _clamp(0.5 * rim_half_mm, 6.0, 32.0)
    # 复杂轮缘曲线过渡（transition != linear）：web-rim 台阶插入过渡点逼近曲线。
    # 幅度 ≤6mm（0.06×rim_radial）：过渡点 r 限制在 rim_junc±6 内，不深入腹板
    # （此前 0.2×rim_radial 使 D29 s_curve 点 r_min=148.8 深陷腹板 → 过渡完全错误）。
    trans_t = 0.0
    if transition != "linear":
        trans_t = _clamp(0.06 * rim_radial, 2.0, 6.0)

    def _wr(z0, z1):
        return _transition_pts(rim_junc, z0, z1, trans_t, transition)

    if form == "conical":
        # 锥形腹板：web 下表面从 hub 顶（z=-wi）连到 rim 内壁更高处（z=-wo_cone），斜面更陡
        wo_cone = _clamp(0.85 * rim_half_mm, 12.0, 40.0)
        lo_ins = _wr(-wo_cone, -rim_half_mm)              # 下半过渡点（z 递减）
        hi_ins = [(r, -z) for r, z in reversed(lo_ins)]    # 上半镜像（z 取正 + 反转，保证轮廓对称）
        pts = [
            (round(bore_r, 3), -hub_half_mm), (round(hub_r, 3), -hub_half_mm),
            (round(hub_r, 3), -web_inner), (round(rim_junc, 3), -wo_cone),
            *lo_ins,
            (round(rim_junc, 3), -rim_half_mm), (round(rim_r, 3), -rim_half_mm),
            (round(rim_r, 3), rim_half_mm), (round(rim_junc, 3), rim_half_mm),
            *hi_ins,
            (round(rim_junc, 3), wo_cone), (round(hub_r, 3), web_inner),
            (round(hub_r, 3), hub_half_mm), (round(bore_r, 3), hub_half_mm),
        ]
    else:
        lo_ins = _wr(-web_outer, -rim_half_mm)
        hi_ins = [(r, -z) for r, z in reversed(lo_ins)]
        pts = [
            (round(bore_r, 3), -hub_half_mm), (round(hub_r, 3), -hub_half_mm),
            (round(hub_r, 3), -web_inner), (round(rim_junc, 3), -web_outer),
            *lo_ins,
            (round(rim_junc, 3), -rim_half_mm), (round(rim_r, 3), -rim_half_mm),
            (round(rim_r, 3), rim_half_mm), (round(rim_junc, 3), rim_half_mm),
            *hi_ins,
            (round(rim_junc, 3), web_outer), (round(hub_r, 3), web_inner),
            (round(hub_r, 3), hub_half_mm), (round(bore_r, 3), hub_half_mm),
        ]
    return {"points": [{"x_mm": p[0], "y_mm": p[1]} for p in pts],
            "params": {"bore_radius_mm": round(bore_r, 3), "hub_radius_mm": round(hub_r, 3),
                       "rim_web_junction_mm": round(rim_junc, 3), "rim_radius_mm": round(rim_r, 3),
                       "hub_radial_mm": round(hub_radial, 3), "rim_radial_mm": round(rim_radial, 3),
                       "web_inner_half_mm": round(web_inner, 3), "web_outer_half_mm": round(web_outer, 3),
                       "form": form}}


# ═══════════════════════════════════════════════════════════════════════════════
# 榫槽轮廓（2×(2+4×teeth+3) 点，XY 平面，x 0→-depth）
# ═══════════════════════════════════════════════════════════════════════════════

def slot_profile(teeth, depth_mm, mouth_half, neck_half, lobe_half,
                 bottom_half, flank_angle_deg=45.0) -> list:
    """榫槽轮廓点（上侧 2+4×teeth+3 点 + 下侧镜像）。复刻 mon_sweep 验证结构。

    硬性要求（保证无退化）：
      - x 单调递减到 -depth（槽底根点正好在 -depth，不回退）
      - lobe 从外到内递减（外宽内窄：lobe1 > lobe2 > ... > neck > bottom）
      - 相邻点距离 >= 1mm
    """
    def upper():
        # x 单调递减到 -depth（槽底根点锁在 -depth，不回退）；齿区 x 均分，lobe 递减
        pts = [(0.0, mouth_half)]
        wedge = -3.0
        pts.append((wedge, neck_half))
        tooth_end = -depth_mm + 3.0  # 槽底留 3mm：喇叭口/斜面/平底，x 单调
        span = tooth_end - wedge  # 负值
        per = span / teeth
        # lobe 从外到内递减，最后一齿 lobe ≥ neck+2.0（枞树形齿清晰可见，齿不淹没在颈部——
        # 此前衰减到 lobe_min=neck+1 导致 teeth≥3 时后几齿视觉上像两齿）。
        final_lobe = max(neck_half + 2.0, lobe_half * 0.6)
        lobe_step = max((lobe_half - final_lobe) / max(teeth - 1, 1), 0.5)
        for i in range(teeth):
            lobe = lobe_half - i * lobe_step
            base = wedge + i * per
            pts.append((round(base + 0.15 * per, 3), round(lobe, 3)))      # 外斜面升
            pts.append((round(base + 0.40 * per, 3), round(lobe, 3)))      # 齿顶平台
            pts.append((round(base + 0.60 * per, 3), neck_half))           # 内斜面降
            pts.append((round(base + 0.85 * per, 3), neck_half))           # 颈部平台
        # 槽底：圆弧底（90° 半圆扇逼近，圆心 (−depth+bottom_half, 0)，半径 bottom_half）。
        # 参考枞树形标准"齿底圆弧"（HB 5965-2002）+ 动力涡轮榫接"齿底圆弧"设计——
        # 最靠近圆心的槽底是圆润弧，替代平底/尖底的生硬过渡，第一齿（近圆心）形状自然。
        r_arc = bottom_half
        cx = -depth_mm + r_arc
        pts.append((round(cx, 3), round(r_arc, 3)))                          # 弧起点（喇叭口上沿）
        pts.append((round(cx - 0.5 * r_arc, 3), round(0.866 * r_arc, 3)))    # 120°
        pts.append((round(cx - 0.866 * r_arc, 3), round(0.5 * r_arc, 3)))    # 150°
        pts.append((round(cx - r_arc, 3), 0.0))                              # 底点（最深处，y=0）
        return pts
    upper_pts = upper()
    # 迭代短边修正（仅上侧）：相邻点距离 <1mm 时把后一点沿 x 外推到前一点左侧 dx 处，
    # 迭代至全部 ≥1mm（处理连锁——齿区/槽底台阶/边/根逐点外推，允许槽底外推超过齿区终点）。
    # 下侧对称继承。首点 (0, mouth) 固定不修正。
    pts = list(upper_pts)
    for _ in range(60):
        changed = False
        for i in range(1, len(pts)):
            px, py = pts[i - 1]
            x, y = pts[i]
            d = math.hypot(x - px, y - py)
            if d < 1.0:
                dx = math.sqrt(max(1.0 - (y - py) ** 2, 0.0))
                nx = px - dx
                if nx < x:  # 外推到更左（增大与前置点的距离）
                    pts[i] = (nx, y)
                    changed = True
        if not changed:
            break
    lower = [(p[0], -p[1]) for p in pts]
    return [{"x_mm": round(p[0], 3), "y_mm": round(p[1], 3)}
            for p in pts + list(reversed(lower))]


# ═══════════════════════════════════════════════════════════════════════════════
# RawGcadDocument 节点构造 helper
# ═══════════════════════════════════════════════════════════════════════════════

def _node(nid, comp, op, inputs, outputs, params, phase, dialect):
    return {"id": nid, "component": comp, "dialect": dialect, "op": op,
            "op_version": "1.0.0", "phase": phase, "inputs": inputs,
            "outputs": outputs, "params": params, "required": True,
            "degradation_policy": "fail"}


def _nref(nid, out):
    return {"node": nid, "output": out}


def _out(name, typ):
    return {"name": name, "type": typ}


_SAFETY = {
    "non_flight_reference_only": True, "not_airworthy": True, "not_certified": True,
    "not_for_manufacturing": True, "not_for_installation": True,
    "no_structural_validation": True, "no_life_prediction": True,
}


# ═══════════════════════════════════════════════════════════════════════════════
# 榫槽 cutter 节点（sketch_profile：create_2d_sketch → polyline → close → fillet → extrude）
# 供 build_slot_disc / build_coupled_disc 复用（cutter 从轮缘外表面 rim_r 处切入）
# ═══════════════════════════════════════════════════════════════════════════════

def _slot_cutter_nodes(teeth, slots, depth_mm, throat_half, fr_mm, rim_r,
                       axial_depth_mm=80.0) -> list:
    neck = max(throat_half * 0.7, 1.5)
    lobe = throat_half * 1.8
    bottom = throat_half * 0.75
    sp = slot_profile(int(teeth), depth_mm, throat_half, neck, lobe, bottom)
    n_sketch = _node("n_sketch_cutter", "slot_cutter", "create_2d_sketch", [],
                     [_out("sketch", "sketch")],
                     {"plane": "XY", "origin_x_mm": 0, "origin_y_mm": 0},
                     "sketch", "sketch_profile")
    n_polyline = _node("n_polyline_cutter", "slot_cutter", "add_polyline",
                       [_nref("n_sketch_cutter", "sketch")], [_out("profile", "profile")],
                       {"points": sp}, "profile", "sketch_profile")
    n_close = _node("n_close_cutter", "slot_cutter", "close_profile",
                    [_nref("n_polyline_cutter", "profile")], [_out("profile", "profile")],
                    {}, "profile", "sketch_profile")
    n_upper = 2 + 4 * int(teeth) + 3
    n_teeth = int(teeth)

    # 齿根圆角（论文 2.3：齿根圆角 + 槽底圆角组合）。
    # 只在平缓 connector 顶点（每齿颈部平台点，连接内斜面降与颈部平台）与槽底圆角——
    # 避免在 lobe 尖角/齿面斜面上 fillet（CAD 在尖角圆角会批量产生 <0.25mm 小边，过不了 degenerate 门）。
    def _mirror(idxs):
        return sorted({int(i) for i in idxs} | {2 * n_upper - 1 - int(i) for i in idxs})

    conn_idxs = [i for i in range(1, n_upper - 1) if (i - 1) % 4 == 3]
    all_conn = _mirror(conn_idxs)
    root_idxs = sorted({n_upper - 1, n_upper})  # 仅槽底根点（对称 2 点），避免台阶点圆角产生小边

    # 槽底圆弧底（slot_profile 90° 半圆扇）已圆润，槽底圆角取小值防弧端退化
    root_room = max(bottom * 0.4, 0.4)
    # 齿根（connector）圆角：fr_mm 为齿根圆角参数，clamp 到 neck 可放空间 + 2.5 上限
    # （可见圆角；此前 cap 到 1.2 且 root_room 过小 → R0.75 在整盘上不可见）
    neck_rad = round(min(float(fr_mm), 0.8 * float(neck), 2.5), 3)

    cur = "n_close_cutter"
    fillet_nodes = []
    n_fillet_neck = _node("n_fillet_neck", "slot_cutter", "fillet_sketch",
                          [_nref(cur, "profile")], [_out("profile", "profile")],
                          {"radius_mm": max(neck_rad, 0.3), "at_vertex_index": all_conn},
                          "edge_treatment", "sketch_profile")
    fillet_nodes.append(n_fillet_neck)
    cur = "n_fillet_neck"
    fr = min(float(fr_mm), root_room)  # 槽底圆弧处小圆角
    n_fillet_root = _node("n_fillet_cutter_root", "slot_cutter", "fillet_sketch",
                          [_nref(cur, "profile")], [_out("profile", "profile")],
                          {"radius_mm": round(max(fr, 0.3), 3), "at_vertex_index": root_idxs},
                          "edge_treatment", "sketch_profile")
    fillet_nodes.append(n_fillet_root)
    cur = "n_fillet_cutter_root"
    n_extrude = _node("n_cutter_extrude", "slot_cutter", "extrude_profile",
                      [_nref(cur, "profile")], [_out("body", "solid")],
                      {"depth_mm": axial_depth_mm, "direction": "both", "taper_deg": 0},
                      "feature", "sketch_profile")
    return [n_sketch, n_polyline, n_close] + fillet_nodes + [n_extrude]



# ═══════════════════════════════════════════════════════════════════════════════
# 榫槽盘模板（sketch_profile 盘体 + slot_cutter + composition 布尔）
# ═══════════════════════════════════════════════════════════════════════════════

def build_slot_disc(params: dict) -> dict:
    """榫槽盘 llm_raw。params 键：od_mm/bore_mm/thick_mm/hub_mm/rim_mm +
    slots/teeth/R_mm/depth_mm/throat_half_width_mm/fr_mm。"""
    dp = disc_profile(params["od_mm"], params["bore_mm"], params["hub_mm"], params["rim_mm"],
                      params["thick_mm"], form=params.get("form", "standard"),
                      transition=params.get("transition", "linear"))
    teeth = int(params.get("teeth", 2))
    slots = int(params.get("slots", 60))
    depth = params.get("depth_mm", 24.0)
    # 榫槽 cutter 从轮缘外表面(rim_r = od/2)切入（参考 mon_e2b035beb218 pattern radius=rim_r）。
    # circular_pattern 把 cutter 槽口(x=0)平移到 radius 处 → 槽口贴轮缘外表面，槽深 depth 切入轮缘。
    # 槽底剩料由 check_slot_depth 保证（depth + mr ≤ rim_radial，论文 5.3）。
    rim_r = params["od_mm"] / 2.0
    R = rim_r  # pattern radius（cutter 定位）；R_mm 采样参数仅作论文标注（enrich/文本）
    throat = params.get("throat_half_width_mm", 4.0)
    fr = params.get("fr_mm", 1.0)
    neck = max(throat * 0.7, 1.5)
    lobe = throat * 1.8
    bottom = throat * 0.75

    # 盘体统一 sketch_profile 轮廓 + fillet + revolve（与参考 mon_e2b035beb218 同架构）。
    # complex_rim 的曲线过渡由 disc_profile 插入点表达（transition 类型），不再用单一
    # fillet_sketch 圆弧（圆弧无法表达 S/双圆弧/幂曲线等丰富过渡）。
    n_sketch_disc = _node("n_sketch_disc", "disc_body", "create_2d_sketch", [],
                          [_out("sketch", "sketch")],
                          {"plane": "XZ", "origin_x_mm": 0, "origin_y_mm": 0},
                          "sketch", "sketch_profile")
    n_polyline_disc = _node("n_polyline_disc", "disc_body", "add_polyline",
                            [_nref("n_sketch_disc", "sketch")], [_out("profile", "profile")],
                            {"points": dp["points"]}, "profile", "sketch_profile")
    n_close_disc = _node("n_close_disc", "disc_body", "close_profile",
                         [_nref("n_polyline_disc", "profile")], [_out("profile", "profile")],
                         {}, "profile", "sketch_profile")
    # 盘体过渡圆角：complex_rim 的 web-rim 过渡由插入点表达 → 仅 hub-web 圆角（索引 2/n_pts-3）；
    # 非 complex_rim 保持 4 圆角（hub-web 2 处 + web-rim 2 处，索引 2/3/n_pts-4/n_pts-3）。
    is_complex = params.get("category") == "complex_rim"
    n_pts = len(dp["points"])
    fillet_vidx = (2, n_pts - 3) if is_complex else (2, 3, n_pts - 4, n_pts - 3)
    disc_fillets = []
    cur = "n_close_disc"
    for i, vidx in enumerate(fillet_vidx):
        fid = f"n_fillet_disc_{i}"
        radius = 12.0 if is_complex else params.get("disc_fillet_mm", 10.0)
        fil = _node(fid, "disc_body", "fillet_sketch", [_nref(cur, "profile")],
                    [_out("profile", "profile")],
                    {"radius_mm": radius, "at_vertex_index": [vidx]},
                    "edge_treatment", "sketch_profile")
        disc_fillets.append(fil)
        cur = fid
    n_disc_revolve = _node("n_disc_revolve", "disc_body", "revolve_profile",
                           [_nref(cur, "profile")], [_out("body", "solid")],
                           {"axis": "Z", "angle_deg": 360}, "feature", "sketch_profile")
    disc_nodes = ([n_sketch_disc, n_polyline_disc, n_close_disc] + disc_fillets
                  + [n_disc_revolve])

    cutter_nodes = _slot_cutter_nodes(teeth, slots, depth, throat, fr, R,
                                      params.get("axial_depth_mm", 80.0))
    n_cutter_extrude = cutter_nodes[-1]

    # assembly：周向阵列 + 布尔切除
    n_pattern = _node("n_pattern_cutters", "__assembly__", "circular_pattern_component",
                      [_nref("n_cutter_extrude", "body")], [_out("body", "solid")],
                      {"count": slots, "radius_mm": R, "axis": "Z",
                       "start_angle_deg": 0, "rotate_copies": True},
                      "pattern", "composition")
    n_final_cut = _node("n_final_cut", "__assembly__", "boolean_cut",
                        [_nref("n_disc_revolve", "body"), _nref("n_pattern_cutters", "body")],
                        [_out("body", "solid")],
                        {"clean_after": True}, "boolean", "composition")

    return {
        "document_id": f"tpl_slot_{params.get('_tag', 'ref')}",
        "part_name": "HP_Turbine_Disc_RefGeo",
        "schema_version": "g_cad_core_v0.2", "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "sketch_profile", "version": "0.2.0"},
                              {"dialect": "composition", "version": "0.2.0"}],
        "components": [
            {"id": "disc_body", "owner_dialect": "sketch_profile",
             "kind_hint": "axisymmetric_disc", "root_node": "n_disc_revolve"},
            {"id": "slot_cutter", "owner_dialect": "sketch_profile",
             "kind_hint": "fir_tree_slot_cutter", "root_node": "n_cutter_extrude"},
            {"id": "__assembly__", "owner_dialect": "composition",
             "kind_hint": "assembly", "root_node": "n_final_cut"},
        ],
        "nodes": (disc_nodes + cutter_nodes + [n_pattern, n_final_cut]),
        "constraints": {"require_step_file": True, "require_metadata_sidecar": True,
                        "require_closed_solid": True, "expected_body_count": 1},
        "safety": dict(_SAFETY),
        "llm_validation_hints": {"_": f"tpl_slot_{teeth}tooth_{slots}slots"},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 盘型模板（axisymmetric 单组件：revolve → bore → groove/hole pattern → chamfer）
# ═══════════════════════════════════════════════════════════════════════════════

def _axisym_stations(od_mm, bore_mm, thick_mm) -> list:
    """盘体 profile_stations（3 站 hub/web/rim，Z 区间相接不重叠——axisymmetric 要求）。

    每站恒定 r：hub 段 r=hub_r、web 段 r=(hub_r+rim_junc)/2、rim 段 r=rim_r。
    """
    rim_r = od_mm / 2.0
    bore_r = bore_mm / 2.0
    hub_r = bore_r + _clamp(0.16 * od_mm, 25.0, 100.0)
    rim_junc = rim_r - _clamp(0.12 * od_mm, 25.0, 95.0)
    if hub_r >= rim_junc:
        hub_r = (bore_r + rim_junc) / 2.0
    web_r = (hub_r + rim_junc) / 2.0
    z = thick_mm / 2.0
    z1 = round(z * 0.4, 3)
    z2 = round(z * 0.7, 3)
    return [
        {"r_mm": round(hub_r, 3), "z_front_mm": 0.0, "z_rear_mm": z1},
        {"r_mm": round(web_r, 3), "z_front_mm": z1, "z_rear_mm": z2},
        {"r_mm": round(rim_r, 3), "z_front_mm": z2, "z_rear_mm": z},
    ]


def _sketch_disc_body(params: dict) -> list:
    """sketch_profile 盘体组件：12 点轮廓 + 4 fillet + revolve（参考 mon_e2b035beb218）。
    顶点 2/9(hub-web) fillet r=12，3/8(web-rim) fillet r=10。
    """
    thick = params["thick_mm"]
    hub_half = params.get("hub_mm", round(thick * 0.5, 1))
    rim_half = params.get("rim_mm", round(thick * 0.4, 1))
    dp = disc_profile(params["od_mm"], params["bore_mm"], hub_half, rim_half, thick,
                      form=params.get("form", "standard"))
    nodes = [
        _node("n_disc_sketch", "disc_body", "create_2d_sketch", [], [_out("sketch", "sketch")],
              {"plane": "XZ", "origin_x_mm": 0, "origin_y_mm": 0}, "sketch", "sketch_profile"),
        _node("n_disc_polyline", "disc_body", "add_polyline", [_nref("n_disc_sketch", "sketch")],
              [_out("profile", "profile")], {"points": dp["points"]}, "profile", "sketch_profile"),
        _node("n_disc_close", "disc_body", "close_profile",
              [_nref("n_disc_polyline", "profile")], [_out("profile", "profile")],
              {}, "profile", "sketch_profile"),
    ]
    cur = "n_disc_close"
    for i, (vidx, r) in enumerate(((2, 12.0), (3, 10.0), (8, 10.0), (9, 12.0))):
        fid = f"n_disc_fillet_{i}"
        nodes.append(_node(fid, "disc_body", "fillet_sketch", [_nref(cur, "profile")],
                          [_out("profile", "profile")],
                          {"radius_mm": r, "at_vertex_index": [vidx]},
                          "edge_treatment", "sketch_profile"))
        cur = fid
    nodes.append(_node("n_disc_revolve", "disc_body", "revolve_profile",
                      [_nref(cur, "profile")], [_out("body", "solid")],
                      {"axis": "Z", "angle_deg": 360}, "feature", "sketch_profile"))
    return nodes


def _hole_cutter(comp_id: str, hole_dia_mm: float) -> list:
    """孔切割组件：XY 正 16 边形(近似圆) polyline → close → extrude（单孔；周向阵列在 assembly）。

    用 add_polyline 多边形近似圆（add_circle 的 spec input_types=["profile"] 与 sketch 输入不匹配，
    会被 strip_passthrough_nodes 误删）。16 边形对孔径 4-26mm 误差 <2%，足够。
    """
    r = hole_dia_mm / 2.0
    n_sides = 16
    pts = [{"x_mm": round(r * math.cos(2 * math.pi * i / n_sides), 3),
            "y_mm": round(r * math.sin(2 * math.pi * i / n_sides), 3)}
           for i in range(n_sides)]
    return [
        _node(f"{comp_id}_sketch", comp_id, "create_2d_sketch", [], [_out("sketch", "sketch")],
              {"plane": "XY", "origin_x_mm": 0, "origin_y_mm": 0}, "sketch", "sketch_profile"),
        _node(f"{comp_id}_poly", comp_id, "add_polyline", [_nref(f"{comp_id}_sketch", "sketch")],
              [_out("profile", "profile")], {"points": pts}, "profile", "sketch_profile"),
        _node(f"{comp_id}_close", comp_id, "close_profile",
              [_nref(f"{comp_id}_poly", "profile")], [_out("profile", "profile")],
              {}, "profile", "sketch_profile"),
        _node(f"{comp_id}_extrude", comp_id, "extrude_profile",
              [_nref(f"{comp_id}_close", "profile")], [_out("body", "solid")],
              {"depth_mm": 800.0, "direction": "both"}, "feature", "sketch_profile"),
    ]


def _ring_cutter(comp_id: str, inner_dia_mm: float, outer_dia_mm: float,
                 depth_mm: float, z_base_mm: float) -> list:
    """环形切割组件（环槽/环形腔，旋转切除）：XZ 矩形环截面 revolve → 环形切割体。"""
    r_in, r_out = inner_dia_mm / 2.0, outer_dia_mm / 2.0
    pts = [{"x_mm": round(r_in, 3), "y_mm": round(z_base_mm, 3)},
           {"x_mm": round(r_out, 3), "y_mm": round(z_base_mm, 3)},
           {"x_mm": round(r_out, 3), "y_mm": round(z_base_mm + depth_mm, 3)},
           {"x_mm": round(r_in, 3), "y_mm": round(z_base_mm + depth_mm, 3)}]
    return [
        _node(f"{comp_id}_sketch", comp_id, "create_2d_sketch", [], [_out("sketch", "sketch")],
              {"plane": "XZ", "origin_x_mm": 0, "origin_y_mm": 0}, "sketch", "sketch_profile"),
        _node(f"{comp_id}_poly", comp_id, "add_polyline", [_nref(f"{comp_id}_sketch", "sketch")],
              [_out("profile", "profile")], {"points": pts}, "profile", "sketch_profile"),
        _node(f"{comp_id}_close", comp_id, "close_profile",
              [_nref(f"{comp_id}_poly", "profile")], [_out("profile", "profile")],
              {}, "profile", "sketch_profile"),
        _node(f"{comp_id}_revolve", comp_id, "revolve_profile",
              [_nref(f"{comp_id}_close", "profile")], [_out("body", "solid")],
              {"axis": "Z", "angle_deg": 360}, "feature", "sketch_profile"),
    ]


def _rim_slot_cutter(comp_id: str, rim_r: float, rs_depth_mm: float,
                     rs_half_width_mm: float) -> list:
    """径向切槽切割组件：XY 槽截面 polyline + extrude（槽口在轮缘外表面 rim_r）。

    U 形槽底（半圆弧逼近，替代矩形尖底——用户反馈"直接用矩形切的槽"不真实）：
    直壁到 rim_r−rs_depth，底部圆弧下沉 arc_r（圆心向盘内），截面 5 点。
    """
    w = rs_half_width_mm
    arc_r = min(max(w * 0.6, 1.0), 0.4 * rs_depth_mm)  # 槽底圆弧半径（计入总深）
    pts = [{"x_mm": round(rim_r, 3), "y_mm": round(w, 3)},
           {"x_mm": round(rim_r - rs_depth_mm, 3), "y_mm": round(w, 3)},
           {"x_mm": round(rim_r - rs_depth_mm - arc_r, 3), "y_mm": 0.0},
           {"x_mm": round(rim_r - rs_depth_mm, 3), "y_mm": round(-w, 3)},
           {"x_mm": round(rim_r, 3), "y_mm": round(-w, 3)}]
    return [
        _node(f"{comp_id}_sketch", comp_id, "create_2d_sketch", [], [_out("sketch", "sketch")],
              {"plane": "XY", "origin_x_mm": 0, "origin_y_mm": 0}, "sketch", "sketch_profile"),
        _node(f"{comp_id}_poly", comp_id, "add_polyline", [_nref(f"{comp_id}_sketch", "sketch")],
              [_out("profile", "profile")], {"points": pts}, "profile", "sketch_profile"),
        _node(f"{comp_id}_close", comp_id, "close_profile",
              [_nref(f"{comp_id}_poly", "profile")], [_out("profile", "profile")],
              {}, "profile", "sketch_profile"),
        _node(f"{comp_id}_extrude", comp_id, "extrude_profile",
              [_nref(f"{comp_id}_close", "profile")], [_out("body", "solid")],
              {"depth_mm": 800.0, "direction": "both"}, "feature", "sketch_profile"),
    ]


def _asm_pattern(nid: str, cutter_body: str, count: int, radius_mm: float, asm_nodes: list) -> str:
    """composition circular_pattern（周向阵列），返回 pattern 节点 id。"""
    asm_nodes.append(_node(nid, "__assembly__", "circular_pattern_component",
                          [_nref(cutter_body, "body")], [_out("body", "solid")],
                          {"count": count, "radius_mm": round(radius_mm, 3), "axis": "Z",
                           "start_angle_deg": 0, "rotate_copies": True},
                          "pattern", "composition"))
    return nid


def _asm_bool(nid: str, target_body: str, tool_body: str, asm_nodes: list) -> str:
    """composition boolean_cut（target - tool），返回新 body 节点 id。"""
    asm_nodes.append(_node(nid, "__assembly__", "boolean_cut",
                          [_nref(target_body, "body"), _nref(tool_body, "body")],
                          [_out("body", "solid")], {"clean_after": True},
                          "boolean", "composition"))
    return nid


def build_axisym_disc(params: dict) -> dict:
    """盘型（基础/孔/环槽减重）llm_raw — sketch_profile 盘体 + 特征切割组件 + composition。

    与参考 mon_e2b035beb218 同架构：盘体 12 点轮廓 + fillet + revolve；
    孔/环槽/减重孔/冷却孔/切槽/环形腔用独立 sketch_profile 切割组件（切除/旋转切除）+ composition 布尔。
    """
    od, bore = params["od_mm"], params["bore_mm"]
    _r = _disc_radii(od, bore, params.get("form", "standard"))
    rim_r, rim_junc, hub_r, web_r = _r["rim_r"], _r["rim_junc"], _r["hub_r"], _r["web_r"]
    rim_half = params.get("rim_mm", 30.0)

    disc_nodes = _sketch_disc_body(params)
    comps = [{"id": "disc_body", "owner_dialect": "sketch_profile",
              "kind_hint": "turbine_disc", "root_node": "n_disc_revolve"}]
    all_nodes = list(disc_nodes)
    asm_nodes = []
    cur_body = "n_disc_revolve"

    def feat_comp(cid: str, root: str):
        comps.append({"id": cid, "owner_dialect": "sketch_profile",
                      "kind_hint": None, "root_node": root})

    # 安装孔阵列（XY 单孔 cutter + 周向 pattern + 布尔）
    if params.get("holes"):
        cid = "feat_holes"
        feat_comp(cid, f"{cid}_extrude")
        all_nodes += _hole_cutter(cid, params["hdia_mm"])
        n_pat = _asm_pattern("n_pat_holes", f"{cid}_extrude", int(params["holes"]),
                             params["pcd_mm"], asm_nodes)
        cur_body = _asm_bool("n_bool_holes", cur_body, n_pat, asm_nodes)
    # 减重孔阵列（腹板大孔）
    if params.get("lh_holes"):
        cid = "feat_lh"
        feat_comp(cid, f"{cid}_extrude")
        all_nodes += _hole_cutter(cid, params["lh_hdia_mm"])
        n_pat = _asm_pattern("n_pat_lh", f"{cid}_extrude", int(params["lh_holes"]),
                             params["lh_pcd_mm"], asm_nodes)
        cur_body = _asm_bool("n_bool_lh", cur_body, n_pat, asm_nodes)
    # 冷却孔阵列（小孔，支持双排）
    if params.get("cl_holes"):
        for k, cl_pcd in enumerate((params["cl_pcd_mm"], params.get("cl_pcd2_mm"))):
            if not cl_pcd:
                break
            cid = f"feat_cl_{k}"
            feat_comp(cid, f"{cid}_extrude")
            all_nodes += _hole_cutter(cid, params["cl_hdia_mm"])
            n_pat = _asm_pattern(f"n_pat_cl_{k}", f"{cid}_extrude", int(params["cl_holes"]),
                                 cl_pcd, asm_nodes)
            cur_body = _asm_bool(f"n_bool_cl_{k}", cur_body, n_pat, asm_nodes)
    # 环槽（collar 卡环槽 / mid 中段集气环槽——旋转切除，从轮缘内壁向实体 +r 方向挖 gd 深）。
    # 起点 rim_junc+12：避开盘体 web-rim fillet 弧（r=10 + 2 余量），消除"先圆角再切除"的
    # 圆角旋转成形残留（D11/D13/D23-D28 用户反馈）。
    # 截面 [r ∈ g_inner, g_inner+gd] × [z ∈ z_c−gw/2, z_c+gw/2]。
    # collar（卡环/封严槽，US4247257）z_c 靠轮缘端面；mid（冷却集气）z_c 中段。
    if params.get("grooves"):
        n = int(params["grooves"])
        gw = params.get("gw_mm", 14.0)
        gd = params.get("gd_mm", 8.0)
        gtype = params.get("groove_type", "mid")
        margin = 3.0  # 端面剩料
        limit = max(rim_half - margin - gw / 2.0, 0.0)
        if gtype == "collar":
            z_cs = [-0.7 * limit] if n == 1 \
                else [-0.7 * limit + (1.0 * limit) * i / (n - 1) for i in range(n)]
        else:
            z_cs = [0.0] if n == 1 \
                else [-limit + 2.0 * limit * i / (n - 1) for i in range(n)]
        g_inner = rim_junc + 12.0  # 避开 web-rim fillet 弧
        for i, z_c in enumerate(z_cs):
            cid = f"feat_groove_{i}"
            feat_comp(cid, f"{cid}_revolve")
            all_nodes += _ring_cutter(cid, 2.0 * g_inner, 2.0 * (g_inner + gd),
                                      gw, z_c - gw / 2.0)
            cur_body = _asm_bool(f"n_bool_groove_{i}", cur_body, f"{cid}_revolve", asm_nodes)
    # 径向局部切槽（轮缘外表面周向矩形槽）
    if params.get("rs_count"):
        cid = "feat_rimslot"
        feat_comp(cid, f"{cid}_extrude")
        all_nodes += _rim_slot_cutter(cid, rim_r, params["rs_depth_mm"], params["rs_half_width_mm"])
        n_pat = _asm_pattern("n_pat_rimslot", f"{cid}_extrude", int(params["rs_count"]),
                             rim_r, asm_nodes)
        cur_body = _asm_bool("n_bool_rimslot", cur_body, n_pat, asm_nodes)
    # 腹板环形腔（旋转切除：从腹板中心面向 +Z 切 cavity_depth，不切穿）
    if params.get("cavity_width_mm") and params.get("cavity_depth_mm"):
        cid = "feat_cavity"
        feat_comp(cid, f"{cid}_revolve")
        cw = params["cavity_width_mm"]
        cd = params["cavity_depth_mm"]
        cav_inner = max(2.0 * (web_r - cw / 2.0), bore + 2.0)
        cav_outer = min(2.0 * (web_r + cw / 2.0), 2.0 * rim_junc - 2.0)
        if cav_outer > cav_inner:
            all_nodes += _ring_cutter(cid, cav_inner, cav_outer, cd, 0.0)
            cur_body = _asm_bool("n_bool_cavity", cur_body, f"{cid}_revolve", asm_nodes)

    final = cur_body
    if asm_nodes:
        comps.append({"id": "__assembly__", "owner_dialect": "composition",
                      "kind_hint": "assembly", "root_node": final})
    all_nodes += asm_nodes
    return {
        "document_id": f"tpl_axisym_{params.get('_tag', 'ref')}",
        "part_name": "Reference_Disc",
        "schema_version": "g_cad_core_v0.2", "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "sketch_profile", "version": "0.2.0"},
                              {"dialect": "composition", "version": "0.2.0"}],
        "components": comps, "nodes": all_nodes,
        "constraints": {"require_step_file": True, "require_metadata_sidecar": True,
                        "require_closed_solid": True, "expected_body_count": 1},
        "safety": dict(_SAFETY),
        "llm_validation_hints": {"_": f"tpl_axisym_{params.get('_tag', 'ref')}"},
    }


def build_coupled_disc(params: dict) -> dict:
    """榫槽+孔阵列+环槽耦合盘：sketch 盘体+特征（build_axisym_disc）+ 榫槽 cutter + composition。"""
    disc = build_axisym_disc(params)
    all_nodes = list(disc["nodes"])
    comps = list(disc["components"])
    # 盘体+特征布尔后的 final body = assembly 组件 root_node；无特征（无 assembly）时 = 盘体 revolve
    disc_final = next((c["root_node"] for c in comps if c["id"] == "__assembly__"),
                      "n_disc_revolve")
    teeth = int(params.get("teeth", 2))
    slots = int(params.get("slots", 60))
    depth = params.get("depth_mm", 24.0)
    throat = params.get("throat_half_width_mm", 4.0)
    fr = params.get("fr_mm", 1.0)
    rim_r = params["od_mm"] / 2.0
    cutter_nodes = _slot_cutter_nodes(teeth, slots, depth, throat, fr, rim_r,
                                      params.get("axial_depth_mm", 80.0))
    all_nodes += cutter_nodes
    n_pattern = _node("n_pattern_cutters", "__assembly__", "circular_pattern_component",
                      [_nref("n_cutter_extrude", "body")], [_out("body", "solid")],
                      {"count": slots, "radius_mm": rim_r, "axis": "Z",
                       "start_angle_deg": 0, "rotate_copies": True},
                      "pattern", "composition")
    n_final_cut = _node("n_final_cut", "__assembly__", "boolean_cut",
                        [_nref(disc_final, "body"), _nref("n_pattern_cutters", "body")],
                        [_out("body", "solid")], {"clean_after": True},
                        "boolean", "composition")
    all_nodes += [n_pattern, n_final_cut]
    comps.append({"id": "slot_cutter", "owner_dialect": "sketch_profile",
                  "kind_hint": "fir_tree_slot_cutter", "root_node": "n_cutter_extrude"})
    asm = next((c for c in comps if c["id"] == "__assembly__"), None)
    if asm is None:
        # 盘体无孔/环槽特征时 build_axisym_disc 不建 assembly → 补建
        comps.append({"id": "__assembly__", "owner_dialect": "composition",
                      "kind_hint": "assembly", "root_node": "n_final_cut"})
    else:
        asm["root_node"] = "n_final_cut"
    return {
        "document_id": f"tpl_coupled_{params.get('_tag', 'ref')}",
        "part_name": "HP_Turbine_Disc_Coupled",
        "schema_version": "g_cad_core_v0.2", "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "sketch_profile", "version": "0.2.0"},
                              {"dialect": "composition", "version": "0.2.0"}],
        "components": comps, "nodes": all_nodes,
        "constraints": {"require_step_file": True, "require_metadata_sidecar": True,
                        "require_closed_solid": True, "expected_body_count": 1},
        "safety": dict(_SAFETY),
        "llm_validation_hints": {"_": f"tpl_coupled_{teeth}tooth_{slots}slots"},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 分发
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# 原生两阶段：plan()（Agent A 规划）→ disc_profile/slot_profile（B/C 轮廓）→ assemble
# ═══════════════════════════════════════════════════════════════════════════════

_KIND_HINT_MAP = {"axisymmetric_disc": "turbine_disc", "fir_tree_slot_cutter": "fir_tree_cutter"}
SLOT_CATS = ("slot", "coupled", "complex_rim")


def _skeletonize(raw: dict) -> dict:
    """完整 llm_raw → 骨架（Agent A 的 gcad_skeleton）：
    kind_hint 组件（盘体/榫槽 cutter）的 add_polyline 占位 2 点（由 assemble 按 B/C 轮廓填充）；
    无 kind_hint 的特征切割组件（孔/环槽/切槽）保留模板算好的最终坐标。
    kind_hint 改 agentic_l2 契约（turbine_disc/fir_tree_cutter）。"""
    skel = copy.deepcopy(raw)
    comp_hints = {}
    for c in skel.get("components", []):
        kh = c.get("kind_hint")
        c["kind_hint"] = _KIND_HINT_MAP.get(kh, kh)
        comp_hints[c.get("id")] = c["kind_hint"]
    for n in skel.get("nodes", []):
        if n.get("op") == "add_polyline" and comp_hints.get(n.get("component")):
            n["params"]["points"] = [{"x_mm": 0, "y_mm": 0}, {"x_mm": 1, "y_mm": 1}]
    return skel


def _disc_params(params: dict) -> dict:
    """候选参数 → Agent A disc profile 参数（AGENT_A_ADDENDUM 契约）。"""
    d = {
        "outer_diameter_mm": params.get("od_mm"), "bore_diameter_mm": params.get("bore_mm"),
        "axial_thickness_mm": params.get("thick_mm"),
        "hub_half_thickness_mm": params.get("hub_mm"), "rim_half_thickness_mm": params.get("rim_mm"),
        "hub_web_fillet_mm": params.get("disc_fillet_mm", 10.0),
        "web_rim_fillet_mm": params.get("disc_fillet_mm", 10.0),
    }
    if params.get("category") == "complex_rim":
        # 复杂轮缘：曲线过渡由 disc_profile 插入点表达（论文 2.1，transition 类型族间不同）
        d["rim_transition_radius_mm"] = params.get("rim_arc_radius_mm", 20.0)
        d["rim_transition_type"] = params.get("transition", "s_curve")
    return d


def _slot_params(params: dict) -> dict:
    """候选参数 → Agent C slot profile 参数（AGENT_A_ADDENDUM 契约）。"""
    throat = params.get("throat_half_width_mm", 4.0)
    fr = params.get("fr_mm", 1.0)
    return {
        "teeth_count": params.get("teeth"), "slots": params.get("slots"),
        "slot_depth_mm": params.get("depth_mm"),
        "mouth_half_width_mm": throat, "neck_half_width_mm": round(0.7 * throat, 3),
        "lobe_half_width_mm": round(1.8 * throat, 3),
        "bottom_half_width_mm": round(0.75 * throat, 3),
        "flank_angle_deg": 45.0, "root_fillet_mm": fr,
        "bottom_fillet_mm": round(0.8 * fr, 3),
    }


def _skeleton(params: dict) -> dict:
    """Agent A 的 gcad_skeleton：按 category 生成骨架节点（points 占位 + kind_hint 契约）。"""
    cat = params.get("category")
    if cat == "coupled":
        raw = build_coupled_disc(params)
    elif cat in ("slot", "complex_rim"):
        raw = build_slot_disc(params)
    else:
        raw = build_axisym_disc(params)
    return _skeletonize(raw)


def plan(params: dict) -> dict:
    """Agent A 输出：AgentDesignPlan（gcad_skeleton 骨架 + profiles 参数声明）。

    build() 的第一阶段。profiles 参数是 Agent B/C 的输入（参数 → 轮廓点）。
    """
    cat = params.get("category")
    skel = _skeleton(params)
    profiles = [{"profile_id": "disc_polyline", "kind": "disc",
                 "params": _disc_params(params)}]
    if cat in SLOT_CATS:
        profiles.append({"profile_id": "cutter_polyline", "kind": "slot",
                         "params": _slot_params(params)})
    return {"gcad_skeleton": skel, "profiles": profiles}


def build(params: dict) -> dict:
    """原生两阶段：plan()（Agent A）→ disc_profile/slot_profile（B/C）→ assemble。

    所有盘类盘体统一 sketch_profile add_polyline（12 点），assemble 按 kind_hint
    （turbine_disc/fir_tree_cutter）填充 points；特征切割组件的 add_polyline（kind_hint=None）
    保留模板坐标。不再区分 SLOT_CATS（axisym profile_stations 已废弃）。
    """
    from agentic_l2 import assemble
    ap = plan(params)
    points = {}
    for prof in ap["profiles"]:
        pid = prof["profile_id"]
        if prof["kind"] == "disc":
            points[pid] = disc_profile(params["od_mm"], params["bore_mm"],
                                       params.get("hub_mm", 38), params.get("rim_mm", 30),
                                       params["thick_mm"],
                                       form=params.get("form", "standard"),
                                       transition=params.get("transition", "linear"))["points"]
        elif prof["kind"] == "slot":
            teeth = int(params.get("teeth", 2))
            depth = params.get("depth_mm", 24.0)
            throat = params.get("throat_half_width_mm", 4.0)
            neck = max(throat * 0.7, 1.5)
            lobe = throat * 1.8
            bottom = throat * 0.75
            points[pid] = slot_profile(teeth, depth, throat, neck, lobe, bottom)
    return assemble(ap["gcad_skeleton"], ap["profiles"], points)


# 演示参数
DEMO_SLOT = {"category": "slot", "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
             "hub_mm": 38, "rim_mm": 30, "slots": 60, "teeth": 2, "R_mm": 215,
             "depth_mm": 24, "throat_half_width_mm": 4.0, "fr_mm": 1.0, "_tag": "demo"}
DEMO_HOLE = {"category": "hole", "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
             "holes": 16, "pcd_mm": 180, "hdia_mm": 14, "_tag": "demo_hole"}
DEMO_GROOVE = {"category": "groove", "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
               "grooves": 2, "gw_mm": 14, "gd_mm": 8, "_tag": "demo_groove"}
DEMO_GROOVE_LH = {"category": "groove", "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
                  "grooves": 1, "gw_mm": 12, "gd_mm": 8,
                  "lh_holes": 12, "lh_pcd_mm": 175, "lh_hdia_mm": 16,
                  "cl_holes": 24, "cl_pcd_mm": 225, "cl_hdia_mm": 6, "cl_pcd2_mm": 240,
                  "rs_count": 60, "rs_depth_mm": 10, "rs_half_width_mm": 3.0,
                  "cavity_width_mm": 40, "cavity_depth_mm": 4.0, "_tag": "demo_groove_lh"}
DEMO_COMPLEX = {"category": "complex_rim", "od_mm": 500, "bore_mm": 120, "thick_mm": 76,
                "hub_mm": 38, "rim_mm": 30, "slots": 60, "teeth": 3, "R_mm": 225,
                "depth_mm": 32, "throat_half_width_mm": 4.0, "fr_mm": 1.0,
                "rim_arc_radius_mm": 20.0, "_tag": "demo_complex"}


if __name__ == "__main__":
    for name, p in (("slot", DEMO_SLOT), ("hole", DEMO_HOLE), ("groove", DEMO_GROOVE),
                    ("groove_lh", DEMO_GROOVE_LH), ("complex", DEMO_COMPLEX)):
        doc = build(p)
        print(f"[{name}] nodes={len(doc['nodes'])} comps={len(doc['components'])} OK")
