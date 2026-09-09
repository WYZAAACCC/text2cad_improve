"""Golden IR extraction and comparison helpers for agentic parity tests."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from design_families import DESIGN_FAMILIES  # noqa: E402
import param_templates as pt  # noqa: E402


def family_params(family_id: str) -> dict[str, Any]:
    fam = DESIGN_FAMILIES[family_id]
    features = fam.get("features") or {}
    params: dict[str, Any] = {
        "category": fam["category"],
        "form": fam.get("form", "standard"),
        "od_mm": fam["od"],
        "bore_mm": fam["bore"],
        "thick_mm": fam["thick"],
        "hub_mm": fam["hub"],
        "rim_mm": fam["rim"],
        "slots": features.get("slots", 60),
        "teeth": features.get("teeth", 2),
        "R_mm": features.get("R", fam["od"] / 2),
        "depth_mm": features.get("depth", 24),
        "throat_half_width_mm": features.get("throat", 4.0),
        "fr_mm": features.get("fr", 1.0),
        "holes": features.get("holes"),
        "pcd_mm": features.get("pcd"),
        "hdia_mm": features.get("hdia"),
        "grooves": features.get("grooves"),
        "gw_mm": features.get("gw"),
        "gd_mm": features.get("gd"),
        "lh_holes": features.get("lh_holes"),
        "lh_pcd_mm": features.get("lh_pcd"),
        "lh_hdia_mm": features.get("lh_hdia"),
        "cl_holes": features.get("cl_holes"),
        "cl_pcd_mm": features.get("cl_pcd"),
        "cl_hdia_mm": features.get("cl_hdia"),
        "cl_pcd2_mm": features.get("cl_pcd2"),
        "rs_count": features.get("rs_count"),
        "rs_depth_mm": features.get("rs_depth"),
        "rs_half_width_mm": features.get("rs_half_width"),
        "cavity_width_mm": features.get("cavity_width"),
        "cavity_depth_mm": features.get("cavity_depth"),
        "rim_arc_radius_mm": features.get("rim_arc_radius"),
        "transition": features.get("transition", "linear"),
    }
    return {k: v for k, v in params.items() if v is not None}


def build_golden_ir(family_id: str) -> dict[str, Any]:
    return pt.build(family_params(family_id))


def _component_kind_hint(raw: dict[str, Any], component_id: str) -> str:
    for comp in raw.get("components", []):
        if comp.get("id") == component_id:
            return str(comp.get("kind_hint") or "")
    return ""


def _component_points(raw: dict[str, Any], component_id: str) -> list[dict[str, float]]:
    for node in raw.get("nodes", []):
        if node.get("component") == component_id and node.get("op") == "add_polyline":
            points = (node.get("params") or {}).get("points") or []
            return [{"x_mm": float(p["x_mm"]), "y_mm": float(p["y_mm"])} for p in points]
    return []


def extract_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "components": [],
        "op_sequence": [],
        "patterns": [],
        "boolean_cuts": 0,
        "disc_points": [],
        "slot_points": [],
        "feature_cutters": {},
    }
    components = raw.get("components", [])
    metrics["components"] = [
        {
            "id": c.get("id"),
            "owner_dialect": c.get("owner_dialect"),
            "kind_hint": c.get("kind_hint"),
            "root_node": c.get("root_node"),
        }
        for c in components
    ]

    for node in raw.get("nodes", []):
        cid = node.get("component")
        op = node.get("op")
        metrics["op_sequence"].append((cid, op))
        if op == "circular_pattern_component":
            metrics["patterns"].append(dict((node.get("params") or {})))
        elif op == "boolean_cut":
            metrics["boolean_cuts"] += 1
        elif op != "add_polyline":
            continue

        kind = _component_kind_hint(raw, cid)
        points = _component_points(raw, cid)
        if not points:
            continue
        if any(k in kind for k in ("disc", "turbine_disc", "axisymmetric_disc")):
            metrics["disc_points"] = points
        elif any(k in kind for k in ("slot", "fir_tree")):
            metrics["slot_points"] = points
        else:
            metrics["feature_cutters"][str(cid)] = points

    return metrics


def circle_error(points: list[dict[str, float]], diameter_mm: float) -> float:
    if not points:
        return float("inf")
    radius = diameter_mm / 2.0
    errors = []
    for p in points:
        errors.append(abs(math.hypot(p["x_mm"], p["y_mm"]) - radius))
    return max(errors) if errors else float("inf")


def points_match(
    a: list[dict[str, float]],
    b: list[dict[str, float]],
    *,
    tol: float = 0.05,
) -> bool:
    if len(a) != len(b):
        return False
    return all(
        abs(p["x_mm"] - q["x_mm"]) <= tol and abs(p["y_mm"] - q["y_mm"]) <= tol
        for p, q in zip(a, b)
    )


# ── 测试/诊断辅助：确定性轮廓生成（仅供 golden 对比，运行时 agent 不使用）──

def circle_polygon_points(center_x, center_y, diameter_mm, n_sides=16) -> list:
    r = diameter_mm / 2.0
    return [
        {"x_mm": round(center_x + r * math.cos(2 * math.pi * i / n_sides), 3),
         "y_mm": round(center_y + r * math.sin(2 * math.pi * i / n_sides), 3)}
        for i in range(n_sides)
    ]


def ring_rect_points(inner_radius_mm, outer_radius_mm,
                     z_base_mm, depth_mm) -> list:
    return [
        {"x_mm": round(inner_radius_mm, 3), "y_mm": round(z_base_mm, 3)},
        {"x_mm": round(outer_radius_mm, 3), "y_mm": round(z_base_mm, 3)},
        {"x_mm": round(outer_radius_mm, 3), "y_mm": round(z_base_mm + depth_mm, 3)},
        {"x_mm": round(inner_radius_mm, 3), "y_mm": round(z_base_mm + depth_mm, 3)},
    ]


def fallback_slot_profile(teeth, depth_mm, mouth_half, neck_half, lobe_half,
                          bottom_half, tfa_deg=45.0, ufa_deg=75.0) -> list:
    n = int(teeth)
    m = float(mouth_half)
    depth = float(depth_mm)
    neck = float(neck_half)
    lobe = float(lobe_half)
    bottom = float(bottom_half)
    ext = 0.15 * m
    plat = 0.1875 * m
    inn = 0.05 * m
    conn = 0.1875 * m
    shoulder = 0.26625 * m
    bottom_span = 0.1875 * m

    def _upper(scale):
        pts = [(0.0, m), (-3.0, neck)]
        x = -3.0
        for _ in range(n):
            x_tip = x - ext * scale
            x_plat = x_tip - plat * scale
            x_neck = x_plat - inn * scale
            x_conn = x_neck - conn * scale
            pts += [(x_tip, lobe), (x_plat, lobe), (x_neck, neck), (x_conn, neck)]
            x = x_conn
        x_b1 = x - shoulder * scale
        x_b2 = x_b1 - bottom_span * scale
        pts += [(x_b1, bottom), (x_b2, bottom)]
        return pts, x_b2

    pts, x_end = _upper(1.0)
    limit = -depth + 1.5
    if x_end < limit:
        scale = limit / x_end if x_end < 0 else 1.0
        pts, x_end = _upper(scale)
    pts.append((-depth, bottom - 1.5))

    for _ in range(60):
        changed = False
        for i in range(1, len(pts)):
            x1, y1 = pts[i - 1]
            x2, y2 = pts[i]
            d = math.hypot(x2 - x1, y2 - y1)
            if d < 0.5:
                dx = math.sqrt(max(0.25 - (y2 - y1) ** 2, 0.0))
                nx = x1 - dx
                if nx < x2 and nx > -depth:
                    pts[i] = (nx, y2)
                    changed = True
        if not changed:
            break

    lower = [(px, -py) for px, py in pts if abs(py) > 1e-6]
    return [{"x_mm": round(px, 3), "y_mm": round(py, 3)}
            for px, py in pts + list(reversed(lower))]


def deterministic_slot_points(params: dict) -> list:
    try:
        teeth = int(params.get("teeth_count") or 2)
        depth = float(params.get("slot_depth_mm") or 24.0)
        mouth = float(params.get("mouth_half_width_mm")
                      or params.get("throat_half_width_mm") or 8.0)
        neck = float(params.get("neck_half_width_mm") or 1.1 * mouth)
        lobe = float(params.get("lobe_half_width_mm") or 2.25 * mouth)
        bottom = float(params.get("bottom_half_width_mm") or 0.875 * mouth)
        tfa = float(params.get("tfa_deg") or params.get("flank_angle_deg") or 45.0)
        ufa = float(params.get("ufa_deg") or 75.0)
        return fallback_slot_profile(teeth, depth, mouth, neck, lobe, bottom, tfa, ufa)
    except Exception:  # noqa: BLE001
        return []


def deterministic_disc_points(params: dict) -> list:
    def _f(key, default):
        try:
            return float(params.get(key) or default)
        except (TypeError, ValueError):
            return default
    bore = _f("bore_radius_mm", 60.0)
    hub = _f("hub_radius_mm", 140.0)
    junc = _f("rim_web_junction_mm", 190.0)
    rim = _f("rim_radius_mm", 250.0)
    hub_half = _f("hub_half_thickness_mm", 38.0)
    web_in = _f("web_inner_half_thickness_mm", _f("web_inner_half_mm", 22.8))
    web_out = _f("web_outer_half_thickness_mm", _f("web_outer_half_mm", 15.0))
    rim_half = _f("rim_half_thickness_mm", 30.0)
    raw = [
        (bore, -hub_half), (hub, -hub_half), (hub, -web_in),
        (junc, -web_out), (junc, -rim_half), (rim, -rim_half),
        (rim, rim_half), (junc, rim_half), (junc, web_out),
        (hub, web_in), (hub, hub_half), (bore, hub_half),
    ]
    return [{"x_mm": round(x, 3), "y_mm": round(y, 3)} for x, y in raw]


def deterministic_profile_points(kind: str, params: dict) -> list:
    if kind == "disc":
        return deterministic_disc_points(params)
    if kind == "slot":
        return deterministic_slot_points(params)
    if kind == "hole":
        return circle_polygon_points(
            float(params.get("center_x_mm", 0.0)),
            float(params.get("center_y_mm", 0.0)),
            float(params.get("diameter_mm") or params.get("hole_dia_mm") or 14.0),
        )
    if kind == "groove":
        return ring_rect_points(
            float(params.get("inner_radius_mm", 0.0)),
            float(params.get("outer_radius_mm", 0.0)),
            float(params.get("z_base_mm", 0.0)),
            float(params.get("depth_mm", 0.0)),
        )
    return []


def authoritative_profile_params(text: str) -> dict:
    """测试/诊断辅助：需求文本 → 模板权威轮廓参数（与 param_templates 同公式）。

    仅供 golden 对比与离线诊断；agent 运行时禁止使用。
    """
    from validate_req_params import extract_requirements
    req = extract_requirements(text)
    od = req.get("outer_diameter_mm")
    bore = req.get("bore_diameter_mm")
    hub = req.get("hub_half_mm")
    rim = req.get("rim_half_mm")
    if not all(x is not None for x in (od, bore, hub, rim)):
        return {}

    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    bore_r = bore / 2.0
    rim_r = od / 2.0
    if any(k in text for k in ("厚轮缘", "thick_rim")):
        h_fac, r_fac = 0.14, 0.17
    elif any(k in text for k in ("大轮毂", "large_hub")):
        h_fac, r_fac = 0.22, 0.10
    else:
        h_fac, r_fac = 0.16, 0.12
    hub_h = req.get("hub_radial_height_mm")
    web_len = req.get("web_radial_length_mm")
    hub_r = bore_r + (float(hub_h) if hub_h is not None
                      else _clamp(h_fac * od, 25.0, 100.0))
    if web_len is not None:
        rim_junc = hub_r + float(web_len)
        if rim_junc >= rim_r:
            rim_junc = rim_r - 1.0
    else:
        rim_junc = rim_r - _clamp(r_fac * od, 25.0, 95.0)
    if hub_r >= rim_junc:
        hub_r = (bore_r + rim_junc) / 2.0
    if any(k in text for k in ("薄腹板", "thin_web")):
        web_in = _clamp(0.35 * hub, 5.0, 22.0)
        web_out = _clamp(0.3 * rim, 4.0, 18.0)
    else:
        web_in = _clamp(0.6 * hub, 8.0, 40.0)
        web_out = _clamp(0.5 * rim, 6.0, 32.0)

    out = {
        "disc": {
            "bore_radius_mm": bore_r,
            "hub_radius_mm": hub_r,
            "rim_web_junction_mm": rim_junc,
            "rim_radius_mm": rim_r,
            "hub_half_thickness_mm": hub,
            "web_inner_half_thickness_mm": web_in,
            "web_outer_half_thickness_mm": web_out,
            "rim_half_thickness_mm": rim,
            "hub_web_fillet_mm": 10.0,
            "web_rim_fillet_mm": 8.0,
        },
    }
    import re
    n = int(req.get("grooves") or 0)
    groove_m = re.search(
        r"(\d+)道环槽[^。；]*?槽宽([\d.]+)mm[^。；]*?槽深([\d.]+)mm", text)
    gw = float(groove_m.group(2)) if groove_m else None
    gd = float(groove_m.group(3)) if groove_m else None
    if n and gw and gd:
        if any(k in text for k in ("锥形腹板", "conical")):
            wb = _clamp(0.4 * rim, 8.0, 24.0)
        else:
            wb = web_out
        a = wb + gw / 2.0
        z_cs = [-a] if n == 1 else [a * (2.0 * i / (n - 1) - 1.0)
                                    for i in range(n)]
        out["grooves"] = [
            {"inner_radius_mm": rim_junc, "outer_radius_mm": rim_junc + gd,
             "z_base_mm": z_c - gw / 2.0, "depth_mm": gw}
            for z_c in z_cs
        ]
    holes = []
    if req.get("lh_holes") and req.get("lh_hdia_mm"):
        holes.append({"profile_id": "feat_lh_profile",
                      "diameter_mm": req["lh_hdia_mm"]})
    if req.get("holes") and req.get("hdia_mm"):
        holes.append({"profile_id": "feat_holes_profile",
                      "diameter_mm": req["hdia_mm"]})
    cl_rows = 1 + (1 if req.get("cl_pcd2_mm") else 0)
    for i in range(cl_rows):
        if req.get("cl_hdia_mm"):
            holes.append({"profile_id": f"feat_cl_{i}_profile",
                          "diameter_mm": req["cl_hdia_mm"]})
    if holes:
        out["holes"] = holes
    return out
