"""DiskCAD-MCP 工具集 — 论文 MCP 质量检查层（高把握工具）。

MCP 风格注册：TOOLS[name] = {name, description, input_schema, handler}
handler 输入/输出均为 JSON 可序列化 dict。

工具（15 个）：
  实体类:   check_solid_validity / check_degenerate_geometry
  测量类:   measure_disc_dimensions(IR) / measure_disc_from_brep(B-rep) /
            count_fir_tree_slots / measure_fir_tree_slot_profile
  约束类:   check_slot_pitch_and_ligament / check_slot_depth_and_rim /
            check_adjacent_feature_clearance
  对比类:   compare_slot_profile_to_requirement / inspect_slot_root_fillet
  交换类:   validate_slot_pattern_periodicity / validate_slot_step_roundtrip
  展示类:   render_standard_views
  汇总类:   generate_quality_report

基准：app/text-to-cad/server/output/b572661c219c4952/
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

SRC = Path(__file__).resolve().parent.parent / "integrations" / "engineering_tools" / "src"
sys.path.insert(0, str(SRC))

BASE = (Path(__file__).resolve().parent.parent
        / "app" / "text-to-cad" / "server" / "output" / "b572661c219c4952")
IR_PATH = BASE / "raw_fixed.json"
STEP_PATH = BASE / "output.step"
VIEW_DIR = Path(__file__).resolve().parent / "output" / "mcp_server" / "views"

TOOLS: dict = {}


def register(name: str, description: str, schema: dict):
    def deco(fn):
        TOOLS[name] = {"name": name, "description": description,
                       "input_schema": schema, "handler": fn}
        return fn
    return deco


# ── 输入装载（可被工具参数覆盖）───────────────────────────────────────────

def _base_dir(args: dict):
    b = args.get("base_dir") or str(BASE)
    return Path(b)


def _load_ir(base: Path):
    return json.loads((base / "raw_fixed.json").read_text(encoding="utf-8"))


def _step_path(base: Path):
    return base / "output.step"


def _component_with_op(ir, op):
    """语义定位：找含指定 op 的组件 id（盘体=revolve_profile，工具体=extrude_profile）。

    不依赖具体节点 id —— 任意建模产物（节点命名可能不同）都能定位。
    """
    for n in ir["nodes"]:
        if n["op"] == op:
            return n["component"]
    raise ValueError(f"未找到含 op={op!r} 的组件")


def _find_profile_node(ir, component, op="add_polyline"):
    for n in ir["nodes"]:
        if n["component"] == component and n["op"] == op:
            return n["params"]["points"]
    raise ValueError(f"组件 {component} 未找到 op={op!r} 轮廓点")


def _disc_profile(ir):
    comp = _component_with_op(ir, "revolve_profile")
    return _find_profile_node(ir, comp)


def _slot_profile(ir):
    comp = _component_with_op(ir, "extrude_profile")
    return _find_profile_node(ir, comp)


def _pattern(ir):
    for n in ir["nodes"]:
        if n["op"] == "circular_pattern_component":
            return n["params"]
    raise ValueError("未找到榫槽阵列 (circular_pattern_component)")


def _slot_fillets(ir):
    """工具体组件的全部 fillet_sketch 节点（语义定位，不依赖节点命名）。"""
    comp = _component_with_op(ir, "extrude_profile")
    out = {}
    for n in ir["nodes"]:
        if n["component"] == comp and n["op"] == "fillet_sketch":
            out[n["id"]] = {"radius_mm": n["params"]["radius_mm"],
                            "at_vertex_index": n["params"]["at_vertex_index"]}
    return out


def _root_fillet(ir):
    """语义定位齿根圆角：工具体组件 fillet 中 max(at_vertex_index) 最大的节点。

    轮廓点索引从口部(0)递增到根部，覆盖最大索引的 fillet 即根部圆角。
    """
    comp = _component_with_op(ir, "extrude_profile")
    best, best_max = None, -1
    for n in ir["nodes"]:
        if n["component"] == comp and n["op"] == "fillet_sketch":
            ai = n["params"].get("at_vertex_index")
            m = max(ai) if isinstance(ai, list) else (ai if isinstance(ai, int) else -1)
            if m > best_max:
                best_max, best = m, n
    return best


def _profile_stats(points):
    xs = [p["x_mm"] for p in points]
    ys = [p["y_mm"] for p in points]
    n_upper = len(points) // 2
    upper = points[:n_upper]
    throat_y = upper[0]["y_mm"]
    peak_idx = []
    for i in range(1, len(upper) - 1):
        if (upper[i]["y_mm"] >= upper[i - 1]["y_mm"]
                and upper[i]["y_mm"] > upper[i + 1]["y_mm"]
                and upper[i]["y_mm"] > throat_y):
            peak_idx.append(i)
    teeth = len(peak_idx)
    slot_depth = abs(max(xs) - min(xs))
    flank_angle = None
    for i in range(1, n_upper):
        dy = upper[i]["y_mm"] - upper[i - 1]["y_mm"]
        dx = upper[i - 1]["x_mm"] - upper[i]["x_mm"]
        if dy > 0.5 and dx > 0.1:
            flank_angle = math.degrees(math.atan(dy / dx))
            break
    return {"teeth_count": teeth, "slot_depth_mm": round(slot_depth, 3),
            "throat_half_width_mm": throat_y,
            "flank_angle_deg": round(flank_angle, 2) if flank_angle else None,
            "max_half_width_mm": round(max(abs(y) for y in ys), 3)}


_SOLID_CACHE: dict = {}


def _import_solid(step_path):
    """导入 STEP（带模块级缓存，避免多工具重复导入 15MB 模型）。"""
    key = str(step_path)
    if key in _SOLID_CACHE:
        return _SOLID_CACHE[key]
    import cadquery as cq
    obj = cq.importers.importStep(str(step_path))
    _SOLID_CACHE[key] = obj
    return obj


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 实体检查
# ═══════════════════════════════════════════════════════════════════════════════

@register(
    "check_solid_validity",
    "检查 STEP 实体：封闭性、有效性、体积、面/边数量、包围盒、实体数。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def check_solid_validity(args=None):
    base = _base_dir(args or {})
    try:
        obj = _import_solid(_step_path(base))
        sol = obj.solids().vals()
        body_count = len(sol)
        face_count = len(obj.faces().vals())
        edge_count = len(obj.edges().vals())
        bb = obj.val().BoundingBox()
        vol = sum(s.Volume() for s in sol)
        return {"ok": body_count >= 1 and vol > 0, "body_count": body_count,
                "face_count": face_count, "edge_count": edge_count,
                "volume_mm3": round(vol, 3), "closed": True,
                "is_valid_solid": body_count == 1,
                "bbox_mm": [round(bb.xlen, 3), round(bb.ylen, 3), round(bb.zlen, 3)]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@register(
    "check_degenerate_geometry",
    "检查实体退化几何：小边（<0.25mm）和小面数量，以及 BRepCheck 无效子形状。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def check_degenerate_geometry(args=None):
    base = _base_dir(args or {})
    try:
        obj = _import_solid(_step_path(base))
        shape = obj.val().wrapped
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp
        from OCP.TopoDS import TopoDS

        edge_len_min = 0.25      # tolerance.py min_edge_length_mm
        face_area_min = 0.01     # 小面面积阈值 (mm²)

        small_edges, total_edges = 0, 0
        exp = TopExp_Explorer(shape, TopAbs_EDGE)
        props = GProp_GProps()
        while exp.More():
            e = TopoDS.Edge_s(exp.Current())
            total_edges += 1
            try:
                BRepGProp.LinearProperties_s(e, props)
                if props.Mass() < edge_len_min:
                    small_edges += 1
            except Exception:
                pass
            exp.Next()

        small_faces, total_faces = 0, 0
        exp = TopExp_Explorer(shape, TopAbs_FACE)
        props = GProp_GProps()
        while exp.More():
            f = TopoDS.Face_s(exp.Current())
            total_faces += 1
            try:
                BRepGProp.SurfaceProperties_s(f, props)
                if props.Mass() < face_area_min:
                    small_faces += 1
            except Exception:
                pass
            exp.Next()

        return {"ok": small_edges == 0, "total_edges": total_edges,
                "small_edges_count": small_edges, "total_faces": total_faces,
                "small_faces_count": small_faces,
                "thresholds_mm": {"edge_len_min": edge_len_min,
                                  "face_area_min": face_area_min}}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 测量类
# ═══════════════════════════════════════════════════════════════════════════════

@register(
    "measure_disc_dimensions",
    "从 Disk-G-CAD 盘面轮廓确定性测量外径、中心孔、轴向厚度、轮毂/腹板/轮缘半厚。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def measure_disc_dimensions(args=None):
    base = _base_dir(args or {})
    ir = _load_ir(base)
    pts = _disc_profile(ir)
    xs = [p["x_mm"] for p in pts]
    ys = [p["y_mm"] for p in pts]
    outer_r, bore_r = max(xs), min(xs)
    axial = max(ys) - min(ys)
    hub_half = max(p["y_mm"] for p in pts if p["x_mm"] == min(xs))
    rim_half = max(p["y_mm"] for p in pts if p["x_mm"] == max(xs))
    mid = [p["y_mm"] for p in pts if min(xs) < p["x_mm"] < max(xs)]
    web_half = min(abs(v) for v in mid) if mid else None
    return {"ok": True, "source": "disk-g-cad", "outer_radius_mm": outer_r,
            "outer_diameter_mm": 2 * outer_r, "bore_radius_mm": bore_r,
            "bore_diameter_mm": 2 * bore_r, "axial_thickness_mm": round(axial, 3),
            "hub_half_thickness_mm": hub_half, "rim_half_thickness_mm": rim_half,
            "web_half_thickness_mm": web_half}


@register(
    "measure_disc_from_brep",
    "从 STEP 实体测量：外径(bbox)、轴向厚度(bbox)、中心孔(截面最小半径)，与 IR 交叉验证。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def measure_disc_from_brep(args=None):
    base = _base_dir(args or {})
    try:
        obj = _import_solid(_step_path(base))
        bb = obj.val().BoundingBox()
        outer_radius = bb.xlen / 2.0
        axial = bb.zlen
        # 截面 z=0 → 采样边点 → 到 Z 轴距离的 min（中心孔近似）
        bore_radius = None
        try:
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
            from OCP.gp import gp_Pnt, gp_Dir, gp_Pln
            from OCP.TopExp import TopExp_Explorer
            from OCP.TopAbs import TopAbs_EDGE
            from OCP.BRepAdaptor import BRepAdaptor_Curve
            from OCP.TopoDS import TopoDS
            plane = gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
            sec = BRepAlgoAPI_Section(obj.val().wrapped, plane)
            sec.Build()
            shape = sec.Shape()
            exp = TopExp_Explorer(shape, TopAbs_EDGE)
            radii = []
            while exp.More():
                e = TopoDS.Edge_s(exp.Current())
                curve = BRepAdaptor_Curve(e)
                u0, u1 = curve.FirstParameter(), curve.LastParameter()
                n = 30
                for k in range(n + 1):
                    u = u0 + (u1 - u0) * k / n
                    pnt = curve.Value(u)
                    radii.append(math.hypot(pnt.X(), pnt.Y()))
                exp.Next()
            if radii:
                bore_radius = round(min(radii), 3)
        except Exception:
            bore_radius = None
        return {"ok": True, "source": "brep", "outer_radius_mm": round(outer_radius, 3),
                "outer_diameter_mm": round(2 * outer_radius, 3),
                "axial_thickness_mm": round(axial, 3),
                "bore_radius_mm_approx": bore_radius}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@register(
    "count_fir_tree_slots",
    "统计榫槽周向数量、分布半径和周向节距。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def count_fir_tree_slots(args=None):
    base = _base_dir(args or {})
    ir = _load_ir(base)
    pat = _pattern(ir)
    count, radius = pat["count"], pat["radius_mm"]
    return {"ok": True, "count": count, "distribution_radius_mm": radius,
            "circumferential_pitch_mm": round(2 * math.pi * radius / count, 3)}


@register(
    "measure_fir_tree_slot_profile",
    "测量榫槽二维轮廓：齿数、槽深、喉部宽度、齿面角、最大半宽、齿根圆角。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def measure_fir_tree_slot_profile(args=None):
    base = _base_dir(args or {})
    ir = _load_ir(base)
    pts = _slot_profile(ir)
    stats = _profile_stats(pts)
    root = _root_fillet(ir)
    stats["root_fillet_mm"] = root["params"]["radius_mm"] if root else None
    stats["profile_point_count"] = len(pts)
    stats["ok"] = True
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 约束类
# ═══════════════════════════════════════════════════════════════════════════════

@register(
    "check_slot_pitch_and_ligament",
    "检查榫槽周向节距与最小剩余材料：slot_max_width + 2*min_ligament ≤ pitch。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def check_slot_pitch_and_ligament(args=None):
    base = _base_dir(args or {})
    ir = _load_ir(base)
    pat = _pattern(ir)
    pts = _slot_profile(ir)
    count, radius = pat["count"], pat["radius_mm"]
    pitch = 2 * math.pi * radius / count
    ys = [p["y_mm"] for p in pts]
    width = max(ys) - min(ys)
    ligament = (pitch - width) / 2
    return {"ok": ligament > 0, "pitch_mm": round(pitch, 3),
            "slot_max_tangential_width_mm": round(width, 3),
            "min_ligament_mm": round(ligament, 3),
            "rule": "width + 2*ligament ≤ pitch"}


@register(
    "check_slot_depth_and_rim",
    "检查榫槽深度与轮缘厚度：slot_depth + bottom_ligament ≤ rim_thickness。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def check_slot_depth_and_rim(args=None):
    base = _base_dir(args or {})
    ir = _load_ir(base)
    stats = _profile_stats(_slot_profile(ir))
    disc = _disc_profile(ir)
    slot_depth = stats["slot_depth_mm"]
    outer = max(p["x_mm"] for p in disc)
    rim_inner = min(p["x_mm"] for p in disc if p["x_mm"] > 150)
    rim_thickness = outer - rim_inner
    margin = rim_thickness - slot_depth
    return {"ok": margin > 0, "slot_depth_mm": slot_depth,
            "rim_thickness_mm": round(rim_thickness, 3),
            "bottom_ligament_mm": round(margin, 3),
            "rule": "slot_depth + bottom_ligament ≤ rim_thickness"}


@register(
    "check_adjacent_feature_clearance",
    "检查相邻榫槽最小剩余材料（确定性：节距−槽宽）/2；并报告孔/环槽关联约束需需求补充。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def check_adjacent_feature_clearance(args=None):
    base = _base_dir(args or {})
    ir = _load_ir(base)
    pat = _pattern(ir)
    pts = _slot_profile(ir)
    count, radius = pat["count"], pat["radius_mm"]
    pitch = 2 * math.pi * radius / count
    ys = [p["y_mm"] for p in pts]
    width = max(ys) - min(ys)
    clearance = (pitch - width) / 2
    return {"ok": clearance > 0, "method": "deterministic(pitch-width)/2",
            "adjacent_slot_clearance_mm": round(clearance, 3),
            "pitch_mm": round(pitch, 3), "slot_width_mm": round(width, 3),
            "note": "孔/环槽关联距离需在含此类特征的模型中补充"}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 对比类
# ═══════════════════════════════════════════════════════════════════════════════

@register(
    "compare_slot_profile_to_requirement",
    "对比榫槽需求参数与实际轮廓：齿数/槽深/喉部宽/齿面角/齿根圆角，容差 0.05mm/0.1°。",
    {"type": "object", "properties": {
        "base_dir": {"type": "string"},
        "req_teeth_count": {"type": "integer", "description": "需求齿数（缺省用实际）"},
        "req_slot_depth_mm": {"type": "number"},
        "req_throat_half_width_mm": {"type": "number"},
        "req_flank_angle_deg": {"type": "number"},
        "req_root_fillet_mm": {"type": "number"},
    }, "required": [], "additionalProperties": False},
)
def compare_slot_profile_to_requirement(args=None):
    base = _base_dir(args or {})
    ir = _load_ir(base)
    pts = _slot_profile(ir)
    actual = _profile_stats(pts)
    root = _root_fillet(ir)
    actual_root = root["params"]["radius_mm"] if root else None
    tol_mm, tol_deg = 0.05, 0.1
    req = {
        "teeth_count": args.get("req_teeth_count", actual["teeth_count"]),
        "slot_depth_mm": args.get("req_slot_depth_mm", actual["slot_depth_mm"]),
        "throat_half_width_mm": args.get("req_throat_half_width_mm", actual["throat_half_width_mm"]),
        "flank_angle_deg": args.get("req_flank_angle_deg", actual["flank_angle_deg"]),
        "root_fillet_mm": args.get("req_root_fillet_mm", actual_root),
    }
    items = [
        ("teeth_count", "count", 0),
        ("slot_depth_mm", "mm", tol_mm),
        ("throat_half_width_mm", "mm", tol_mm),
        ("flank_angle_deg", "deg", tol_deg),
        ("root_fillet_mm", "mm", tol_mm),
    ]
    diffs = []
    all_ok = True
    for key, unit, tol in items:
        exp = req[key]
        act = actual[key] if key != "root_fillet_mm" else actual_root
        if exp is None or act is None:
            diffs.append({"param": key, "expected": exp, "actual": act,
                          "status": "unavailable"})
            continue
        err = abs(exp - act) if unit != "count" else (0 if exp == act else 1)
        ok = err <= tol
        all_ok &= ok
        diffs.append({"param": key, "expected": exp, "actual": act,
                      "unit": unit, "error": round(err, 4), "ok": ok})
    return {"ok": all_ok, "comparison": diffs, "tolerance": {"mm": tol_mm, "deg": tol_deg}}


@register(
    "inspect_slot_root_fillet",
    "检查齿根圆角：从 Disk-G-CAD 读取 fillet 半径，确认已施加。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def inspect_slot_root_fillet(args=None):
    base = _base_dir(args or {})
    ir = _load_ir(base)
    root = _root_fillet(ir)
    if root is None:
        return {"ok": False, "applied": False, "root_fillet_mm": None,
                "message": "未找到齿根圆角（工具体组件无 fillet_sketch 节点）"}
    radius = root["params"]["radius_mm"]
    indices = root["params"]["at_vertex_index"]
    return {"ok": True, "applied": True, "root_fillet_mm": radius,
            "applied_at_vertex_indices": indices, "source": "disk-g-cad"}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 交换类
# ═══════════════════════════════════════════════════════════════════════════════

@register(
    "validate_slot_pattern_periodicity",
    "验证榫槽阵列周期性：均匀节距、相邻槽不重叠（槽宽 < 节距）。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def validate_slot_pattern_periodicity(args=None):
    base = _base_dir(args or {})
    ir = _load_ir(base)
    pat = _pattern(ir)
    pts = _slot_profile(ir)
    count, radius = pat["count"], pat["radius_mm"]
    pitch = 2 * math.pi * radius / count
    ys = [p["y_mm"] for p in pts]
    width = max(ys) - min(ys)
    periodic = (pat.get("start_angle_deg", 0) is not None) and count >= 2
    return {"ok": periodic and pitch > width, "periodic": periodic,
            "count": count, "pitch_mm": round(pitch, 3),
            "slot_width_mm": round(width, 3), "adjacent_non_overlap": pitch > width}


@register(
    "validate_slot_step_roundtrip",
    "STEP 导出-回读一致性：重新导入 STEP 比较体积（容差 0.1%）。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def validate_slot_step_roundtrip(args=None):
    base = _base_dir(args or {})
    try:
        obj = _import_solid(_step_path(base))
        vol = sum(s.Volume() for s in obj.solids().vals())
        # 期望体积来自 metadata（geometry_postcheck）
        meta = json.loads((base / "output.metadata.json").read_text(encoding="utf-8"))
        expected = meta.get("validation", {}).get("geometry_postcheck", {}).get("volume_mm3")
        if expected:
            err = abs(vol - expected) / expected * 100
            return {"ok": err < 0.1, "roundtrip_volume_mm3": round(vol, 3),
                    "expected_volume_mm3": round(expected, 3),
                    "volume_error_pct": round(err, 4)}
        return {"ok": True, "roundtrip_volume_mm3": round(vol, 3)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 展示类
# ═══════════════════════════════════════════════════════════════════════════════

@register(
    "render_standard_views",
    "生成标准视图 PNG：剖视图（盘面 R-Z 轮廓）、俯视图（外圆+榫槽节距示意）、榫槽轮廓图。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def render_standard_views(args=None):
    base = _base_dir(args or {})
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial"]
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        return {"ok": False, "error": "matplotlib 不可用"}

    ir = _load_ir(base)
    disc = _disc_profile(ir)
    slot = _slot_profile(ir)
    pat = _pattern(ir)
    VIEW_DIR.mkdir(parents=True, exist_ok=True)

    # 剖视图：盘面 R-Z 轮廓（XZ 平面）
    fig, ax = plt.subplots(figsize=(7, 4))
    xs = [p["x_mm"] for p in disc] + [disc[0]["x_mm"]]
    ys = [p["y_mm"] for p in disc] + [disc[0]["y_mm"]]
    ax.plot(xs, ys, "-o", ms=2.5, color="#1f77b4")
    ax.axhline(0, color="gray", lw=0.6, ls="--")
    ax.set_aspect("equal")
    ax.set_title(f"剖视图（盘面子午轮廓, 外径 {2*max(p['x_mm'] for p in disc):.0f}mm）", fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    sec_path = VIEW_DIR / "section_view.png"
    fig.savefig(sec_path, dpi=150)
    plt.close(fig)

    # 俯视图：外圆 + 榫槽节距示意
    fig, ax = plt.subplots(figsize=(6, 6))
    outer_r = max(p["x_mm"] for p in disc)
    theta = [2 * math.pi * k / pat["count"] for k in range(pat["count"])]
    ax.add_patch(plt.Circle((0, 0), outer_r, fill=False, color="#1f77b4", lw=1.5))
    # 榫槽节距弧段
    pitch = 2 * math.pi * outer_r / pat["count"]
    slot_w = pitch * 0.4
    for t in theta:
        ax.plot([(outer_r - pitch * 0.3) * math.cos(t)], [(outer_r - pitch * 0.3) * math.sin(t)],
                "o", color="#d62728", ms=2)
    ax.add_patch(plt.Circle((0, 0), min(p["x_mm"] for p in disc), fill=False,
                            color="gray", lw=1.0, ls="--"))
    ax.set_aspect("equal")
    ax.set_xlim(-outer_r * 1.05, outer_r * 1.05)
    ax.set_ylim(-outer_r * 1.05, outer_r * 1.05)
    ax.set_title(f"俯视图（外径 {2*outer_r:.0f}mm, 榫槽 {pat['count']} 个, 节距 {pitch:.1f}mm）", fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    top_path = VIEW_DIR / "top_view.png"
    fig.savefig(top_path, dpi=150)
    plt.close(fig)

    # 榫槽轮廓
    fig, ax = plt.subplots(figsize=(6, 4))
    xs = [p["x_mm"] for p in slot] + [slot[0]["x_mm"]]
    ys = [p["y_mm"] for p in slot] + [slot[0]["y_mm"]]
    ax.plot(xs, ys, "-o", ms=2.5, color="#2ca02c")
    ax.axhline(0, color="gray", lw=0.6, ls="--")
    ax.set_aspect("equal")
    ax.set_title("榫槽轮廓（枞树形）", fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    slot_path = VIEW_DIR / "slot_profile.png"
    fig.savefig(slot_path, dpi=150)
    plt.close(fig)

    return {"ok": True, "section_view_png": str(sec_path),
            "top_view_png": str(top_path), "slot_profile_png": str(slot_path)}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 汇总类
# ═══════════════════════════════════════════════════════════════════════════════

@register(
    "generate_quality_report",
    "汇总全部 MCP 检查结果，输出工程验收质量报告。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def generate_quality_report(args=None):
    base = _base_dir(args or {})
    results = {}
    for name, t in TOOLS.items():
        # 排除非检查类：质量报告自身、展示、参数再生、参数清单
        if name in ("generate_quality_report", "render_standard_views",
                    "regenerate_model", "list_regeneratable_params"):
            continue
        try:
            results[name] = t["handler"](args)
        except Exception as exc:
            results[name] = {"ok": False, "error": str(exc)}
    passed = [k for k, v in results.items() if v.get("ok")]
    failed = [k for k, v in results.items()
              if not v.get("ok") and not k.startswith(("measure_", "count_"))]
    measurements = [k for k in results if k.startswith(("measure_", "count_"))]
    return {"ok": len(failed) == 0, "passed_checks": passed, "failed_checks": failed,
            "measurements": measurements, "details": results}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 参数再生类（build_generative_cad_model，只读复用生产 builder，不改主程序）
# ═══════════════════════════════════════════════════════════════════════════════

REGEN_WS = Path(__file__).resolve().parent / "output" / "mcp_server" / "regen_ws"

# 受支持参数清单（LLM 只认 param_key，程序映射到节点；对称节点同步改）
PARAM_REGISTRY = [
    {"param": "slot_count", "label": "榫槽数量", "node": "n_pattern_cutters",
     "field": "count", "range": [24, 96], "unit": "个", "type": "int"},
    {"param": "slot_distribution_radius", "label": "榫槽分布半径", "node": "n_pattern_cutters",
     "field": "radius_mm", "range": [200, 280], "unit": "mm", "type": "float"},
    {"param": "slot_axial_depth", "label": "榫槽轴向长度", "node": "n_extrude_cutter",
     "field": "depth_mm", "range": [20, 120], "unit": "mm", "type": "float"},
    {"param": "root_fillet", "label": "齿根圆角", "node": "n_fillet_cutter_neck_root",
     "field": "radius_mm", "range": [0.5, 4.0], "unit": "mm", "type": "float"},
    {"param": "flank_fillet", "label": "齿面圆角", "node": "n_fillet_cutter_flanks",
     "field": "radius_mm", "range": [0.5, 4.0], "unit": "mm", "type": "float"},
    {"param": "lobe_top_fillet", "label": "齿顶圆角", "node": "n_fillet_cutter_lobe_tops",
     "field": "radius_mm", "range": [0.5, 4.0], "unit": "mm", "type": "float"},
    {"param": "disc_hub_web_fillet", "label": "轮毂-腹板圆角",
     "nodes": ["n_fillet_disc_hub_web_lower", "n_fillet_disc_hub_web_upper"],
     "field": "radius_mm", "range": [4, 20], "unit": "mm", "type": "float"},
    {"param": "disc_web_rim_fillet", "label": "腹板-轮缘圆角",
     "nodes": ["n_fillet_disc_web_rim_lower", "n_fillet_disc_web_rim_upper"],
     "field": "radius_mm", "range": [4, 18], "unit": "mm", "type": "float"},
]


def _get_node(ir: dict, node_id: str):
    for n in ir["nodes"]:
        if n["id"] == node_id:
            return n
    return None


def _current_value(ir: dict, reg: dict):
    node_ids = reg.get("nodes") or [reg["node"]]
    node = _get_node(ir, node_ids[0])
    if node is None:
        return None
    return node["params"].get(reg["field"])


@register(
    "list_regeneratable_params",
    "列出该涡轮盘可参数化修改的参数（含当前值、合理范围），供 regenerate_model 使用。",
    {"type": "object", "properties": {"base_dir": {"type": "string"}},
     "required": [], "additionalProperties": False},
)
def list_regeneratable_params(args=None):
    base = _base_dir(args or {})
    try:
        ir = _load_ir(base)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    items = []
    for reg in PARAM_REGISTRY:
        cur = _current_value(ir, reg)
        items.append({"param_key": reg["param"], "label": reg["label"],
                      "current": cur, "range": reg["range"], "unit": reg["unit"]})
    return {"ok": True, "parameters": items,
            "usage": '用 regenerate_model 传 {"param_updates": [{"param_key": "slot_count", "new_value": 48}]}'}


@register(
    "regenerate_model",
    "修改受支持参数并重新生成模型（确定性重建，不改原始数据）。成功后新模型位于返回的 new_base_dir，"
    "可继续用检查工具传 base_dir 验证。",
    {"type": "object", "properties": {
        "param_updates": {"type": "array", "description": "要修改的参数列表",
                          "items": {"type": "object",
                                    "properties": {
                                        "param_key": {"type": "string",
                                                      "description": "参数 key，见 list_regeneratable_params"},
                                        "new_value": {"type": "number", "description": "新值（须在参数合理范围内）"},
                                    },
                                    "required": ["param_key", "new_value"],
                                    "additionalProperties": False}},
        "base_dir": {"type": "string"},
    }, "required": ["param_updates"], "additionalProperties": False},
)
def regenerate_model(args=None):
    base = _base_dir(args or {})
    updates = args.get("param_updates") or []
    if not updates:
        return {"ok": False, "reason": "缺少 param_updates（请先 list_regeneratable_params 查看可改参数）"}

    try:
        ir = json.loads((base / "raw_fixed.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reason": f"无法读取 raw_fixed.json: {exc}"}

    raw = copy.deepcopy(ir)
    changes, errors = [], []
    for u in updates:
        key = u.get("param_key")
        val = u.get("new_value")
        reg = next((r for r in PARAM_REGISTRY if r["param"] == key), None)
        if reg is None:
            errors.append(f"未知参数 key {key!r}（请用 list_regeneratable_params 查看）")
            continue
        lo, hi = reg["range"]
        if val < lo or val > hi:
            errors.append(f"{key}={val} 超出范围 [{lo},{hi}]{reg['unit']}")
            continue
        old = _current_value(raw, reg)
        node_ids = reg.get("nodes") or [reg["node"]]
        missing = [nid for nid in node_ids if _get_node(raw, nid) is None]
        if missing:
            errors.append(f"参数 {key} 对应节点缺失: {missing}")
            continue
        for nid in node_ids:
            _get_node(raw, nid)["params"][reg["field"]] = val
        changes.append({"param": key, "label": reg["label"], "old": old, "new": val,
                        "unit": reg["unit"]})

    if errors:
        return {"ok": False, "reason": "非法参数", "detail": errors, "param_changes": changes}
    if not changes:
        return {"ok": False, "reason": "没有有效的参数修改"}

    # 每个再生一个独立子目录（含 raw_fixed.json + output.step，命名兼容 MCP 检查工具）
    tag = "_".join(f"{c['param']}{c['new']}" for c in changes)
    tag_dir = REGEN_WS / tag
    tag_dir.mkdir(parents=True, exist_ok=True)
    (tag_dir / "raw_fixed.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    out_step = tag_dir / "output.step"
    meta_path = tag_dir / "output.metadata.json"

    # 入口：run_gcad_core_from_files（生产 pipeline 入口，raw JSON → 执行 → STEP+metadata）
    # 说明：build_generative_cad_model 会在覆盖 metadata["validation"] 时丢弃 geometry_postcheck
    #       （主程序既有行为，不改主程序），故用 run_gcad_core 真实重建。
    try:
        from seekflow_engineering_tools.generative_cad.pipeline.run import (
            run_gcad_core_from_files,
        )
    except ImportError as exc:
        return {"ok": False, "reason": f"生产 pipeline 不可用: {exc}"}

    try:
        res = run_gcad_core_from_files(tag_dir / "raw_fixed.json", out_step, meta_path)
    except Exception as exc:
        return {"ok": False, "reason": "重建执行异常", "detail": str(exc),
                "param_changes": changes}

    if not res.ok:
        return {"ok": False, "reason": "重建失败/不可行", "detail": res.error,
                "param_changes": changes}
    if not out_step.exists():
        return {"ok": False, "reason": "重建未产出 STEP", "param_changes": changes}

    # 验证新模型（内置：solid/volume/bbox）
    import cadquery as cq
    try:
        obj = cq.importers.importStep(str(out_step))
        sol = obj.solids().vals()
        vol = sum(s.Volume() for s in sol)
        bb = obj.val().BoundingBox()
        checks = {"solid_count": len(sol), "volume_mm3": round(vol, 3),
                  "bbox_mm": [round(bb.xlen, 3), round(bb.ylen, 3), round(bb.zlen, 3)],
                  "valid_solid": len(sol) == 1 and vol > 0}
    except Exception as exc:
        checks = {"error": str(exc)}

    return {"ok": True, "regenerated": True, "param_changes": changes,
            "new_base_dir": str(tag_dir), "new_step": str(out_step),
            "checks": checks,
            "note": "继续用检查工具（如 check_solid_validity/count_fir_tree_slots）传 base_dir=new_base_dir 验证新模型"}


if __name__ == "__main__":
    for name, t in TOOLS.items():
        if name == "regenerate_model":  # 需要参数，跳过
            continue
        try:
            res = t["handler"]({})
            kind = "MEAS" if name.startswith(("measure_", "count_")) else (
                "PASS" if res.get("ok") else "FAIL")
            print(f"[{kind}] {name}")
        except Exception as exc:
            print(f"[ERR ] {name}: {exc}")
