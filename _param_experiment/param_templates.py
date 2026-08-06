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

def disc_profile(od_mm, bore_mm, hub_half_mm, rim_half_mm, thick_mm,
                 web_inner_half=None, web_outer_half=None) -> dict:
    """盘体 12 点 R-Z 轮廓（闭合顺序，关于 y=0 对称）→ {points, params}。

    径向站：bore_r → hub_r → rim_junc → rim_r（论文轮毂/轮缘径向高度 25-100/25-95）。
    """
    bore_r = bore_mm / 2.0
    rim_r = od_mm / 2.0
    hub_radial = _clamp(0.16 * od_mm, 25.0, 100.0)
    rim_radial = _clamp(0.12 * od_mm, 25.0, 95.0)
    hub_r = bore_r + hub_radial
    rim_junc = rim_r - rim_radial
    if hub_r >= rim_junc:  # 保证腹板存在
        hub_r = (bore_r + rim_junc) / 2.0
    web_inner = web_inner_half if web_inner_half else _clamp(0.6 * hub_half_mm, 8.0, 40.0)
    web_outer = web_outer_half if web_outer_half else _clamp(0.5 * rim_half_mm, 6.0, 32.0)
    pts = [
        (round(bore_r, 3), -hub_half_mm), (round(hub_r, 3), -hub_half_mm),
        (round(hub_r, 3), -web_inner), (round(rim_junc, 3), -web_outer),
        (round(rim_junc, 3), -rim_half_mm), (round(rim_r, 3), -rim_half_mm),
        (round(rim_r, 3), rim_half_mm), (round(rim_junc, 3), rim_half_mm),
        (round(rim_junc, 3), web_outer), (round(hub_r, 3), web_inner),
        (round(hub_r, 3), hub_half_mm), (round(bore_r, 3), hub_half_mm),
    ]
    return {"points": [{"x_mm": p[0], "y_mm": p[1]} for p in pts],
            "params": {"bore_radius_mm": round(bore_r, 3), "hub_radius_mm": round(hub_r, 3),
                       "rim_web_junction_mm": round(rim_junc, 3), "rim_radius_mm": round(rim_r, 3),
                       "hub_radial_mm": round(hub_radial, 3), "rim_radial_mm": round(rim_radial, 3),
                       "web_inner_half_mm": round(web_inner, 3), "web_outer_half_mm": round(web_outer, 3)}}


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
        tooth_end = -depth_mm + 3.0  # 槽底留 3mm：台阶(-depth+3)/边(-depth+2)/根(-depth)，x 单调
        span = tooth_end - wedge  # 负值
        per = span / teeth
        lobe_min = max(neck_half + 1.0, 2.0)
        lobe_step = max((lobe_half - lobe_min) / teeth, 0.2)
        for i in range(teeth):
            lobe = lobe_half - i * lobe_step
            base = wedge + i * per
            pts.append((round(base + 0.15 * per, 3), round(lobe, 3)))      # 外斜面升
            pts.append((round(base + 0.40 * per, 3), round(lobe, 3)))      # 齿顶平台
            pts.append((round(base + 0.60 * per, 3), neck_half))           # 内斜面降
            pts.append((round(base + 0.85 * per, 3), neck_half))           # 颈部平台
        # 槽底 3 点：台阶(-depth+3) → 槽底边(-depth+2) → 根(-depth)，x 单调递减
        pts.append((round(tooth_end, 3), bottom_half))
        pts.append((round(tooth_end - 1.0, 3), bottom_half))
        pts.append((-depth_mm, round(max(bottom_half - 1.5, 1.0), 3)))
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
    # 齿根圆角（论文 2.3：齿根圆角 + 槽底圆角组合）。覆盖齿根连接处 connector 顶点
    # （平缓转角，CAD fillet 不产生小边——neck 尖角圆角会退化，经实测避免）。
    # 上侧 (i-1)%4==3 且 i<n_upper-1（排除槽底根点，由 root fillet 覆盖）+ 镜像。
    conn_idxs = [i for i in range(1, n_upper - 1) if (i - 1) % 4 == 3]
    all_conn = sorted(set(conn_idxs + [2 * n_upper - 1 - i for i in conn_idxs]))
    root_room = max(0.75 * float(throat_half) - 1.5, 0.3)  # 槽底 root 可放半宽
    neck_rad = round(min(float(fr_mm), 0.8 * float(neck), root_room), 3)  # connector 可放半径
    n_fillet_neck = _node("n_fillet_neck", "slot_cutter", "fillet_sketch",
                          [_nref("n_close_cutter", "profile")], [_out("profile", "profile")],
                          {"radius_mm": neck_rad, "at_vertex_index": all_conn},
                          "edge_treatment", "sketch_profile")
    # 槽底 root 圆角（接在齿根圆角后），半径 clamp 到 root 半宽可放空间
    root_idxs = sorted({n_upper - 1, n_upper})
    fr = min(float(fr_mm), root_room)
    n_fillet_root = _node("n_fillet_cutter_root", "slot_cutter", "fillet_sketch",
                          [_nref("n_fillet_neck", "profile")], [_out("profile", "profile")],
                          {"radius_mm": round(fr, 3), "at_vertex_index": root_idxs},
                          "edge_treatment", "sketch_profile")
    n_extrude = _node("n_cutter_extrude", "slot_cutter", "extrude_profile",
                      [_nref("n_fillet_cutter_root", "profile")], [_out("body", "solid")],
                      {"depth_mm": axial_depth_mm, "direction": "both", "taper_deg": 0},
                      "feature", "sketch_profile")
    return [n_sketch, n_polyline, n_close, n_fillet_neck, n_fillet_root, n_extrude]


# ═══════════════════════════════════════════════════════════════════════════════
# 榫槽盘模板（sketch_profile 盘体 + slot_cutter + composition 布尔）
# ═══════════════════════════════════════════════════════════════════════════════

def build_slot_disc(params: dict) -> dict:
    """榫槽盘 llm_raw。params 键：od_mm/bore_mm/thick_mm/hub_mm/rim_mm +
    slots/teeth/R_mm/depth_mm/throat_half_width_mm/fr_mm。"""
    dp = disc_profile(params["od_mm"], params["bore_mm"], params["hub_mm"], params["rim_mm"],
                      params["thick_mm"])
    teeth = int(params.get("teeth", 2))
    slots = int(params.get("slots", 60))
    depth = params.get("depth_mm", 24.0)
    # pattern radius 尊重采样 R_mm（论文分布半径）；但保证 cutter 槽底不穿出轮缘且剩料 ≥3mm
    # （R - depth >= rim_junc + 3，rim_junc = 0.38·od）。采样器 check_slot_bottom 已保证
    # R_mm 合法；此处 clamp 兜底（不超 rim_r）。
    rim_r = params["od_mm"] / 2.0
    R = params.get("R_mm", rim_r)
    R = max(float(R), max(0.38 * params["od_mm"] + depth + 3.0, 180.0))  # 槽底剩料≥3 + 论文下限
    R = min(R, min(rim_r, 300.0))  # 论文 R 上限 300
    throat = params.get("throat_half_width_mm", 4.0)
    fr = params.get("fr_mm", 1.0)
    neck = max(throat * 0.7, 1.5)
    lobe = throat * 1.8
    bottom = throat * 0.75

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
    # 盘体 4 个过渡圆角（顶点 2/3/8/9，hub-web 与 web-rim）
    disc_fillets = []
    cur = "n_close_disc"
    for i, vidx in enumerate((2, 3, 8, 9)):
        fid = f"n_fillet_disc_{i}"
        fil = _node(fid, "disc_body", "fillet_sketch", [_nref(cur, "profile")],
                    [_out("profile", "profile")],
                    {"radius_mm": params.get("disc_fillet_mm", 10.0), "at_vertex_index": [vidx]},
                    "edge_treatment", "sketch_profile")
        disc_fillets.append(fil)
        cur = fid
    n_disc_revolve = _node("n_disc_revolve", "disc_body", "revolve_profile",
                           [_nref(cur, "profile")], [_out("body", "solid")],
                           {"axis": "Z", "angle_deg": 360}, "feature", "sketch_profile")

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
        "nodes": ([n_sketch_disc, n_polyline_disc, n_close_disc] + disc_fillets
                  + [n_disc_revolve] + cutter_nodes + [n_pattern, n_final_cut]),
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


def build_axisym_disc(params: dict) -> dict:
    """盘型（孔/环槽/基础盘）llm_raw，axisymmetric 单组件。
    params 键：od_mm/bore_mm/thick_mm + 可选 holes/pcd_mm/hdia_mm、grooves/gw_mm/gd_mm。"""
    od, bore, thick = params["od_mm"], params["bore_mm"], params["thick_mm"]
    rim_r = od / 2.0
    stations = params.get("profile_stations") or _axisym_stations(od, bore, thick)
    nodes = []
    nodes.append(_node("node_revolve", "disc_body", "revolve_profile", [],
                       [_out("body", "solid"), _out("outer_frame", "frame")],
                       {"axis": "Z", "profile_stations": stations},
                       "base_solid", "axisymmetric"))
    nodes.append(_node("node_center_bore", "disc_body", "cut_center_bore",
                       [_nref("node_revolve", "body")], [_out("body", "solid")],
                       {"diameter_mm": bore, "axis": "Z", "through_all": True},
                       "primary_cut", "axisymmetric"))
    cur = "node_center_bore"
    # 环槽（可选）：在轮缘内壁（rim_junc）处，inner/outer 由槽宽 gw 决定
    rim_junc = rim_r - _clamp(0.12 * od, 25.0, 95.0)
    for gi in range(int(params.get("grooves", 0))):
        gid = f"node_groove_{gi}"
        gw = params.get("gw_mm", 14.0)
        nodes.append(_node(gid, "disc_body", "cut_annular_groove",
                           [_nref(cur, "body")], [_out("body", "solid")],
                           {"side": "front",
                            "inner_dia_mm": round(2 * rim_junc - gw, 3),
                            "outer_dia_mm": round(2 * rim_junc + gw, 3),
                            "depth_mm": params.get("gd_mm", 8.0)},
                           "annular_detail", "axisymmetric"))
        cur = gid
    # 孔（可选）。注意：axisym 方言的 pcd_mm 是【直径】语义（handler/preflight 均 pcd/2），
    # 而采样/文本/约束用【半径】（论文 rp 分布半径）。故模板补偿 ×2，使几何孔环半径=采样半径。
    if params.get("holes"):
        hid = "node_hole_pattern"
        nodes.append(_node(hid, "disc_body", "cut_circular_hole_pattern",
                           [_nref(cur, "body")], [_out("body", "solid")],
                           {"count": int(params["holes"]), "pcd_mm": round(params["pcd_mm"] * 2, 3),
                            "hole_dia_mm": params["hdia_mm"], "axis": "Z", "through_all": True},
                           "pattern_cut", "axisymmetric"))
        cur = hid
    nodes.append(_node("node_chamfer", "disc_body", "apply_safe_chamfer",
                       [_nref(cur, "body")], [_out("body", "solid")],
                       {"distance_mm": 1.0, "target": "all_external_edges"},
                       "edge_treatment", "axisymmetric"))
    return {
        "document_id": f"tpl_axisym_{params.get('_tag', 'ref')}",
        "part_name": "Reference_Axisymmetric_Disc",
        "schema_version": "g_cad_core_v0.2", "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0"}],
        "components": [{"id": "disc_body", "owner_dialect": "axisymmetric",
                        "root_node": "node_chamfer"}],
        "nodes": nodes,
        "constraints": {"require_step_file": True, "require_metadata_sidecar": True,
                        "require_closed_solid": True, "expected_body_count": 1},
        "safety": dict(_SAFETY),
        "llm_validation_hints": {"_": f"tpl_axisym_{params.get('_tag', 'ref')}"},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 耦合盘模板（axisym 盘体含孔/环槽 + 榫槽 cutter + composition 布尔，s14 混合架构）
# ═══════════════════════════════════════════════════════════════════════════════

def build_coupled_disc(params: dict) -> dict:
    """榫槽+孔阵列+环槽耦合盘 llm_raw。params 键：榫槽族参数 + 可选 holes/pcd/hdia、grooves/gw/gd。"""
    # 1. axisym 盘体（revolve → bore → 环槽 → 孔）
    disc_ir = build_axisym_disc(params)
    disc_nodes = disc_ir["nodes"]
    disc_final = disc_nodes[-1]["id"]  # node_chamfer
    # 2. 榫槽 cutter（pattern radius 尊重采样 R_mm，槽底剩料 ≥3mm 兜底）
    teeth = int(params.get("teeth", 2))
    slots = int(params.get("slots", 60))
    depth = params.get("depth_mm", 24.0)
    throat = params.get("throat_half_width_mm", 4.0)
    fr = params.get("fr_mm", 1.0)
    rim_r = params["od_mm"] / 2.0
    R = params.get("R_mm", rim_r)
    R = max(float(R), max(0.38 * params["od_mm"] + depth + 3.0, 180.0))  # 槽底剩料≥3 + 论文下限
    R = min(R, min(rim_r, 300.0))  # 论文 R 上限 300
    cutter_nodes = _slot_cutter_nodes(teeth, slots, depth, throat, fr, R,
                                      params.get("axial_depth_mm", 80.0))
    # 3. assembly：周向阵列 + 布尔切除（target=axisym 盘体，tool=榫槽阵列）
    n_pattern = _node("n_pattern_cutters", "__assembly__", "circular_pattern_component",
                      [_nref("n_cutter_extrude", "body")], [_out("body", "solid")],
                      {"count": slots, "radius_mm": R, "axis": "Z",
                       "start_angle_deg": 0, "rotate_copies": True},
                      "pattern", "composition")
    n_final_cut = _node("n_final_cut", "__assembly__", "boolean_cut",
                        [_nref(disc_final, "body"), _nref("n_pattern_cutters", "body")],
                        [_out("body", "solid")],
                        {"clean_after": True}, "boolean", "composition")
    return {
        "document_id": f"tpl_coupled_{params.get('_tag', 'ref')}",
        "part_name": "HP_Turbine_Disc_Coupled",
        "schema_version": "g_cad_core_v0.2", "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0"},
                              {"dialect": "sketch_profile", "version": "0.2.0"},
                              {"dialect": "composition", "version": "0.2.0"}],
        "components": [
            {"id": "disc_body", "owner_dialect": "axisymmetric", "root_node": disc_final},
            {"id": "slot_cutter", "owner_dialect": "sketch_profile",
             "kind_hint": "fir_tree_slot_cutter", "root_node": "n_cutter_extrude"},
            {"id": "__assembly__", "owner_dialect": "composition",
             "kind_hint": "assembly", "root_node": "n_final_cut"},
        ],
        "nodes": disc_nodes + cutter_nodes + [n_pattern, n_final_cut],
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
    add_polyline.points 占位 2 点；kind_hint 改 agentic_l2 契约（turbine_disc/fir_tree_cutter）。"""
    skel = copy.deepcopy(raw)
    for c in skel.get("components", []):
        kh = c.get("kind_hint")
        c["kind_hint"] = _KIND_HINT_MAP.get(kh, kh)
    for n in skel.get("nodes", []):
        if n.get("op") == "add_polyline":
            n["params"]["points"] = [{"x_mm": 0, "y_mm": 0}, {"x_mm": 1, "y_mm": 1}]
    return skel


def _disc_params(params: dict) -> dict:
    """候选参数 → Agent A disc profile 参数（AGENT_A_ADDENDUM 契约）。"""
    return {
        "outer_diameter_mm": params.get("od_mm"), "bore_diameter_mm": params.get("bore_mm"),
        "axial_thickness_mm": params.get("thick_mm"),
        "hub_half_thickness_mm": params.get("hub_mm"), "rim_half_thickness_mm": params.get("rim_mm"),
        "hub_web_fillet_mm": params.get("disc_fillet_mm", 10.0),
        "web_rim_fillet_mm": params.get("disc_fillet_mm", 10.0),
    }


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

    - 榫槽类（slot/coupled/complex_rim）：骨架含 add_polyline（盘体 12 点 + 榫槽轮廓），
      assemble 按 kind_hint（turbine_disc/fir_tree_cutter）填充 points。
    - axisym 类（basic/hole/groove）：盘体为 revolve profile_stations（无 add_polyline），
      骨架已含完整几何，直接返回。
    """
    from agentic_l2 import assemble
    ap = plan(params)
    cat = params.get("category")
    if cat not in SLOT_CATS:
        return ap["gcad_skeleton"]  # axisym 骨架已含 profile_stations
    points = {}
    for prof in ap["profiles"]:
        pid = prof["profile_id"]
        if prof["kind"] == "disc":
            points[pid] = disc_profile(params["od_mm"], params["bore_mm"],
                                       params.get("hub_mm", 38), params.get("rim_mm", 30),
                                       params["thick_mm"])["points"]
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


if __name__ == "__main__":
    for name, p in (("slot", DEMO_SLOT), ("hole", DEMO_HOLE), ("groove", DEMO_GROOVE)):
        doc = build(p)
        print(f"[{name}] nodes={len(doc['nodes'])} comps={len(doc['components'])} OK")
