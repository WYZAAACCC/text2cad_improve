from __future__ import annotations

import math
from typing import Any

KERNEL_NAME = "cadquery_turbine_disk_reference_v2"
PRIMITIVE_NAME = "axisymmetric_turbine_disk"


# ── Parameter helpers ────────────────────────────────────────────────

def _get_float(params: dict, key: str, default: float = 0.0) -> float:
    return float(params.get(key, default))


def _get_int(params: dict, key: str, default: int = 0) -> int:
    return int(params.get(key, default))


def _get_bool(params: dict, key: str, default: bool = False) -> bool:
    return bool(params.get(key, default))


# ── Box cutter utility ───────────────────────────────────────────────

def _make_box(cq, length_x, width_y, height_z, center_tuple):
    cx, cy, cz = center_tuple
    return (
        cq.Workplane("XY")
        .box(length_x, width_y, height_z, centered=True)
        .translate((cx, cy, cz))
    )


# ── Base body ────────────────────────────────────────────────────────

def _build_base_body(cq, params):
    outer_d = _get_float(params, "outer_dia_mm")
    bore_d = _get_float(params, "bore_dia_mm")
    hub_d = _get_float(params, "hub_outer_dia_mm")
    web_d = _get_float(params, "web_outer_dia_mm")
    rim_inner_d = _get_float(params, "rim_inner_dia_mm")

    hub_w = _get_float(params, "hub_width_mm")
    web_w = _get_float(params, "web_width_mm")
    rim_w = _get_float(params, "rim_width_mm")

    r_bore = bore_d / 2.0
    r_hub = hub_d / 2.0
    r_web = web_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    r_outer = outer_d / 2.0

    t_hub = hub_w / 2.0
    t_web = web_w / 2.0
    t_rim = rim_w / 2.0

    profile_points = [
        (r_bore, -t_hub),
        (r_hub, -t_hub),
        (r_hub, -t_web),
        (r_web, -t_web),
        (r_rim_inner, -t_rim),
        (r_outer, -t_rim),
        (r_outer, t_rim),
        (r_rim_inner, t_rim),
        (r_web, t_web),
        (r_hub, t_web),
        (r_hub, t_hub),
        (r_bore, t_hub),
    ]

    result = (
        cq.Workplane("XZ")
        .polyline(profile_points)
        .close()
        .revolve()
    )

    return result, profile_points


# ── Hub sleeves ──────────────────────────────────────────────────────

def _add_front_hub_sleeve(cq, result, params):
    front_outer = _get_float(params, "front_hub_sleeve_outer_dia_mm")
    front_inner = _get_float(params, "front_hub_sleeve_inner_dia_mm")
    front_height = _get_float(params, "front_hub_sleeve_height_mm")
    front_chamfer = _get_float(params, "front_hub_sleeve_chamfer_mm")

    if front_height <= 0:
        return result

    base_front_z = _get_float(params, "axial_width_mm") / 2.0

    sleeve = (
        cq.Workplane("XY")
        .circle(front_outer / 2.0)
        .circle(front_inner / 2.0)
        .extrude(front_height)
        .translate((0, 0, base_front_z))
    )
    result = result.union(sleeve)

    if front_chamfer > 0:
        try:
            result = result.edges(">Z").chamfer(front_chamfer)
        except Exception:
            pass

    return result


def _add_rear_hub_sleeve(cq, result, params):
    rear_outer = _get_float(params, "rear_hub_sleeve_outer_dia_mm")
    rear_inner = _get_float(params, "rear_hub_sleeve_inner_dia_mm")
    rear_height = _get_float(params, "rear_hub_sleeve_height_mm")
    rear_chamfer = _get_float(params, "rear_hub_sleeve_chamfer_mm")

    if rear_height <= 0:
        return result

    base_rear_z = -_get_float(params, "axial_width_mm") / 2.0

    sleeve = (
        cq.Workplane("XY")
        .circle(rear_outer / 2.0)
        .circle(rear_inner / 2.0)
        .extrude(rear_height)
        .translate((0, 0, base_rear_z - rear_height))
    )
    result = result.union(sleeve)

    if rear_chamfer > 0:
        try:
            result = result.edges("<Z").chamfer(rear_chamfer)
        except Exception:
            pass

    return result


# ── Annular details ──────────────────────────────────────────────────

def _add_annular_details(cq, result, params):
    enabled = _get_bool(params, "enable_annular_details", default=True)
    if not enabled:
        return result

    axial = _get_float(params, "axial_width_mm") / 2.0
    outer_d = _get_float(params, "outer_dia_mm")
    bore_d = _get_float(params, "bore_dia_mm")

    r_bore = bore_d / 2.0
    r_outer = outer_d / 2.0

    # inner hub step: raised ring on front face near hub
    inner_hub_step_height = _get_float(params, "inner_hub_step_height_mm")
    inner_hub_step_outer_d = _get_float(params, "inner_hub_step_outer_dia_mm")
    if inner_hub_step_height > 0 and inner_hub_step_outer_d > bore_d:
        r_step = inner_hub_step_outer_d / 2.0
        step = (
            cq.Workplane("XY")
            .circle(r_step)
            .circle(r_bore)
            .extrude(inner_hub_step_height)
            .translate((0, 0, axial))
        )
        result = result.union(step)

    # mid-web recess: annular cut on front face
    mid_web_recess_depth = _get_float(params, "mid_web_recess_depth_mm")
    mid_web_recess_inner_d = _get_float(params, "mid_web_recess_inner_dia_mm")
    mid_web_recess_outer_d = _get_float(params, "mid_web_recess_outer_dia_mm")
    if mid_web_recess_depth > 0 and mid_web_recess_outer_d > mid_web_recess_inner_d:
        r_mid_inner = mid_web_recess_inner_d / 2.0
        r_mid_outer = mid_web_recess_outer_d / 2.0
        recess = (
            cq.Workplane("XY")
            .circle(r_mid_outer)
            .circle(r_mid_inner)
            .extrude(mid_web_recess_depth)
            .translate((0, 0, axial - mid_web_recess_depth))
        )
        result = result.cut(recess)

    # outer rim recess: annular cut on front face
    outer_rim_recess_depth = _get_float(params, "outer_rim_recess_depth_mm")
    outer_rim_recess_inner_d = _get_float(params, "outer_rim_recess_inner_dia_mm")
    outer_rim_recess_outer_d = _get_float(params, "outer_rim_recess_outer_dia_mm")
    if outer_rim_recess_depth > 0 and outer_rim_recess_outer_d > outer_rim_recess_inner_d:
        r_outer_inner = outer_rim_recess_inner_d / 2.0
        r_outer_outer = outer_rim_recess_outer_d / 2.0
        recess = (
            cq.Workplane("XY")
            .circle(r_outer_outer)
            .circle(r_outer_inner)
            .extrude(outer_rim_recess_depth)
            .translate((0, 0, axial - outer_rim_recess_depth))
        )
        result = result.cut(recess)

    # seal lands: raised rings on front face
    seal_land_count = _get_int(params, "seal_land_count")
    seal_land_height = _get_float(params, "seal_land_height_mm")
    seal_land_width = _get_float(params, "seal_land_width_mm")
    seal_land_start_d = _get_float(params, "seal_land_start_dia_mm")
    seal_land_pitch = _get_float(params, "seal_land_pitch_mm")
    if seal_land_count > 0 and seal_land_height > 0 and seal_land_width > 0:
        for i in range(seal_land_count):
            z_offset = axial + i * seal_land_pitch
            r_start = seal_land_start_d / 2.0 + i * seal_land_pitch
            r_inner = r_start
            r_outer_seal = r_start + seal_land_width
            land = (
                cq.Workplane("XY")
                .circle(r_outer_seal)
                .circle(r_inner)
                .extrude(seal_land_height)
                .translate((0, 0, z_offset))
            )
            result = result.union(land)

    return result


# ── Hole pattern helpers ─────────────────────────────────────────────

def _hole_pattern_metadata(name: str, count: int, pcd_mm: float, dia_mm: float, axis: str) -> dict[str, Any]:
    return {
        "name": name,
        "count": int(count),
        "pcd_mm": float(pcd_mm),
        "hole_dia_mm": float(dia_mm),
        "axis": axis,
    }


def _cut_hole_ring(result, count: int, pcd_mm: float, hole_dia_mm: float, axis: str):
    if count <= 0:
        return result

    if axis != "Z":
        raise ValueError(f"Only Z-axis through holes are supported, got {axis!r}")

    radius = pcd_mm / 2.0

    return (
        result.faces(">Z")
        .workplane(centerOption="CenterOfBoundBox")
        .polarArray(radius, 0, 360, count)
        .hole(hole_dia_mm)
    )


# ── Coverplate bolt ring ─────────────────────────────────────────────

def _cut_coverplate_bolt_ring(result, params):
    count = _get_int(params, "coverplate_bolt_count")
    pcd = _get_float(params, "coverplate_bolt_pcd_mm")
    dia = _get_float(params, "coverplate_bolt_dia_mm")
    axis = str(params.get("coverplate_bolt_axis", "Z"))
    return _cut_hole_ring(result, count=count, pcd_mm=pcd, hole_dia_mm=dia, axis=axis)


# ── Balance hole ring ────────────────────────────────────────────────

def _cut_balance_hole_ring(result, params):
    count = _get_int(params, "balance_hole_count")
    pcd = _get_float(params, "balance_hole_pcd_mm")
    dia = _get_float(params, "balance_hole_dia_mm")
    axis = str(params.get("balance_hole_axis", "Z"))
    return _cut_hole_ring(result, count=count, pcd_mm=pcd, hole_dia_mm=dia, axis=axis)


# ── Rim slot cutters ─────────────────────────────────────────────────

def _make_rectangular_rim_slot_cutter(cq, params):
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    width = _get_float(params, "rim_slot_width_mm")
    axial = _get_float(params, "rim_width_mm") - 2.0 * _get_float(params, "rim_slot_axial_margin_mm")

    return _make_box(cq, depth, width, axial, (r_outer - depth / 2.0, 0.0, 0.0))


def _make_fir_tree_like_slot_cutter(cq, params):
    r_outer = _get_float(params, "outer_dia_mm") / 2.0
    depth = _get_float(params, "rim_slot_depth_mm")
    mouth_w = _get_float(params, "rim_slot_width_mm")
    neck_w = _get_float(params, "rim_slot_neck_width_mm")
    lobe_w = _get_float(params, "rim_slot_lobe_width_mm")
    lobe_depth = _get_float(params, "rim_slot_lobe_depth_mm")
    axial = _get_float(params, "rim_width_mm") - 2.0 * _get_float(params, "rim_slot_axial_margin_mm")

    pieces = []
    # mouth near outer radius
    pieces.append(_make_box(cq, depth * 0.25, mouth_w, axial, (r_outer - depth * 0.125, 0.0, 0.0)))
    # narrow neck
    pieces.append(_make_box(cq, depth * 0.45, neck_w, axial, (r_outer - depth * 0.42, 0.0, 0.0)))
    # first lobe
    pieces.append(_make_box(cq, lobe_depth, lobe_w, axial, (r_outer - depth * 0.58, 0.0, 0.0)))
    # second inner pocket
    pieces.append(_make_box(cq, lobe_depth, lobe_w * 0.9, axial, (r_outer - depth * 0.78, 0.0, 0.0)))
    # root pocket
    pieces.append(_make_box(cq, depth * 0.18, neck_w * 1.15, axial, (r_outer - depth * 0.93, 0.0, 0.0)))

    cutter = pieces[0]
    for piece in pieces[1:]:
        cutter = cutter.union(piece)
    return cutter


def _cut_rim_slots(cq, result, params):
    count = _get_int(params, "rim_slot_count")
    style = str(params.get("rim_slot_style", "none"))
    if count <= 0 or style == "none":
        return result

    if style == "rectangular":
        cutter = _make_rectangular_rim_slot_cutter(cq, params)
    elif style in {"dovetail", "fir_tree_like"}:
        cutter = _make_fir_tree_like_slot_cutter(cq, params)
    else:
        raise ValueError(f"Unsupported rim_slot_style: {style!r}")

    for i in range(count):
        angle = 360.0 * i / count
        rotated = cutter.rotate((0, 0, 0), (0, 0, 1), angle)
        result = result.cut(rotated)
    return result


# ── Reference dimensions ─────────────────────────────────────────────

def _reference_dimensions(params: dict) -> dict[str, Any]:
    total_hole_count = (
        1
        + int(params.get("bolt_hole_count", 0))
        + int(params.get("lightening_hole_count", 0))
        + int(params.get("cooling_hole_count", 0))
        + int(params.get("coverplate_bolt_count", 0))
        + int(params.get("balance_hole_count", 0))
    )
    visual_feature_count = total_hole_count + int(params.get("rim_slot_count", 0))

    return {
        "outer_dia_mm": float(params["outer_dia_mm"]),
        "bore_dia_mm": float(params["bore_dia_mm"]),
        "axial_width_mm": float(params["axial_width_mm"]),
        "hub_outer_dia_mm": float(params["hub_outer_dia_mm"]),
        "web_outer_dia_mm": float(params["web_outer_dia_mm"]),
        "rim_inner_dia_mm": float(params["rim_inner_dia_mm"]),
        "hub_width_mm": float(params["hub_width_mm"]),
        "web_width_mm": float(params["web_width_mm"]),
        "rim_width_mm": float(params["rim_width_mm"]),
        "bolt_hole_count": int(params.get("bolt_hole_count", 0)),
        "lightening_hole_count": int(params.get("lightening_hole_count", 0)),
        "cooling_hole_count": int(params.get("cooling_hole_count", 0)),
        "rim_slot_count": int(params.get("rim_slot_count", 0)),
        "rim_slot_style": str(params.get("rim_slot_style", "none")),
        "rim_slot_depth_mm": float(params.get("rim_slot_depth_mm", 0)),
        "rim_slot_width_mm": float(params.get("rim_slot_width_mm", 0)),
        "front_hub_sleeve_outer_dia_mm": float(params.get("front_hub_sleeve_outer_dia_mm", 0)),
        "front_hub_sleeve_inner_dia_mm": float(params.get("front_hub_sleeve_inner_dia_mm", 0)),
        "front_hub_sleeve_height_mm": float(params.get("front_hub_sleeve_height_mm", 0)),
        "coverplate_bolt_count": int(params.get("coverplate_bolt_count", 0)),
        "balance_hole_count": int(params.get("balance_hole_count", 0)),
        "visual_feature_count": visual_feature_count,
        "expected_periodic_slot_count": int(params.get("rim_slot_count", 0)),
        "total_hole_count": total_hole_count,
        "expected_through_hole_count": total_hole_count,
    }


# ── Metadata ─────────────────────────────────────────────────────────

def _metadata(params, profile_points, warnings):
    outer_d = float(params["outer_dia_mm"])
    bore_d = float(params["bore_dia_mm"])
    hub_d = float(params["hub_outer_dia_mm"])
    web_d = float(params["web_outer_dia_mm"])
    rim_inner_d = float(params["rim_inner_dia_mm"])

    r_bore = bore_d / 2.0
    r_hub = hub_d / 2.0
    r_web = web_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    r_outer = outer_d / 2.0

    ref_dims = _reference_dimensions(params)

    hole_patterns = [
        _hole_pattern_metadata(
            "bolt",
            int(params.get("bolt_hole_count", 0)),
            float(params.get("bolt_pcd_mm", 0)),
            float(params.get("bolt_hole_dia_mm", 0)),
            str(params.get("bolt_hole_axis", "Z")),
        ),
        _hole_pattern_metadata(
            "lightening",
            int(params.get("lightening_hole_count", 0)),
            float(params.get("lightening_hole_pcd_mm", 0)),
            float(params.get("lightening_hole_dia_mm", 0)),
            str(params.get("lightening_hole_axis", "Z")),
        ),
        _hole_pattern_metadata(
            "cooling",
            int(params.get("cooling_hole_count", 0)),
            float(params.get("cooling_hole_pcd_mm", 0)),
            float(params.get("cooling_hole_dia_mm", 0)),
            str(params.get("cooling_hole_axis", "Z")),
        ),
        _hole_pattern_metadata(
            "coverplate_bolt",
            int(params.get("coverplate_bolt_count", 0)),
            float(params.get("coverplate_bolt_pcd_mm", 0)),
            float(params.get("coverplate_bolt_dia_mm", 0)),
            str(params.get("coverplate_bolt_axis", "Z")),
        ),
        _hole_pattern_metadata(
            "balance",
            int(params.get("balance_hole_count", 0)),
            float(params.get("balance_hole_pcd_mm", 0)),
            float(params.get("balance_hole_dia_mm", 0)),
            str(params.get("balance_hole_axis", "Z")),
        ),
    ]

    return {
        "primitive": PRIMITIVE_NAME,
        "metadata_version": "primitive_metadata_v1",
        "kernel": KERNEL_NAME,
        "geometry_family": "axisymmetric_base_with_cyclic_rim_features",
        "parameters": dict(params),
        "reference_dimensions": ref_dims,
        "warnings": warnings,
        "radial_zones": {
            "bore_radius_mm": r_bore,
            "hub_outer_radius_mm": r_hub,
            "web_outer_radius_mm": r_web,
            "rim_inner_radius_mm": r_rim_inner,
            "outer_radius_mm": r_outer,
        },
        "profile_points": [[float(r), float(z)] for r, z in profile_points],
        "hole_patterns": hole_patterns,
        "visual_fidelity": {
            "target": "reference_visual_only",
            "contains_cyclic_rim_slots": int(params.get("rim_slot_count", 0)) > 0,
            "contains_hub_sleeve": (
                float(params.get("front_hub_sleeve_height_mm", 0)) > 0
                or float(params.get("rear_hub_sleeve_height_mm", 0)) > 0
            ),
            "contains_annular_details": (
                float(params.get("inner_hub_step_height_mm", 0)) > 0
                or float(params.get("mid_web_recess_depth_mm", 0)) > 0
                or float(params.get("outer_rim_recess_depth_mm", 0)) > 0
                or int(params.get("seal_land_count", 0)) > 0
            ),
            "contains_coverplate_interface": int(params.get("coverplate_bolt_count", 0)) > 0,
            "contains_real_blade_attachment": False,
        },
        "rim_features": {
            "slot_count": int(params.get("rim_slot_count", 0)),
            "slot_style": str(params.get("rim_slot_style", "none")),
            "slot_depth_mm": float(params.get("rim_slot_depth_mm", 0)),
            "slot_width_mm": float(params.get("rim_slot_width_mm", 0)),
            "reference_only": True,
        },
        "hub_sleeve": {
            "front_enabled": float(params.get("front_hub_sleeve_height_mm", 0)) > 0,
            "rear_enabled": float(params.get("rear_hub_sleeve_height_mm", 0)) > 0,
            "front_outer_dia_mm": float(params.get("front_hub_sleeve_outer_dia_mm", 0)),
            "front_inner_dia_mm": float(params.get("front_hub_sleeve_inner_dia_mm", 0)),
            "front_height_mm": float(params.get("front_hub_sleeve_height_mm", 0)),
        },
        "annular_details": {
            "enabled": (
                float(params.get("inner_hub_step_height_mm", 0)) > 0
                or float(params.get("mid_web_recess_depth_mm", 0)) > 0
                or float(params.get("outer_rim_recess_depth_mm", 0)) > 0
                or int(params.get("seal_land_count", 0)) > 0
            ),
            "mid_web_recess": float(params.get("mid_web_recess_depth_mm", 0)) > 0,
            "outer_rim_recess": float(params.get("outer_rim_recess_depth_mm", 0)) > 0,
            "seal_lands": int(params.get("seal_land_count", 0)),
        },
        "safety": {
            "non_flight_reference_only": True,
            "not_for_manufacturing": True,
            "not_airworthy": True,
            "not_certified": True,
        },
    }


# ── Main entry point ─────────────────────────────────────────────────

def build_axisymmetric_turbine_disk_cadquery(params: dict):
    import cadquery as cq

    # 1. Build revolved base body
    result, profile_points = _build_base_body(cq, params)

    # 2. Add front hub sleeve
    result = _add_front_hub_sleeve(cq, result, params)

    # 3. Add rear hub sleeve
    result = _add_rear_hub_sleeve(cq, result, params)

    # 4. Add annular details
    result = _add_annular_details(cq, result, params)

    # 5. Cut legacy hole rings
    result = _cut_hole_ring(
        result,
        count=int(params.get("bolt_hole_count", 0)),
        pcd_mm=float(params.get("bolt_pcd_mm", 0)),
        hole_dia_mm=float(params.get("bolt_hole_dia_mm", 0)),
        axis=str(params.get("bolt_hole_axis", "Z")),
    )

    result = _cut_hole_ring(
        result,
        count=int(params.get("lightening_hole_count", 0)),
        pcd_mm=float(params.get("lightening_hole_pcd_mm", 0)),
        hole_dia_mm=float(params.get("lightening_hole_dia_mm", 0)),
        axis=str(params.get("lightening_hole_axis", "Z")),
    )

    result = _cut_hole_ring(
        result,
        count=int(params.get("cooling_hole_count", 0)),
        pcd_mm=float(params.get("cooling_hole_pcd_mm", 0)),
        hole_dia_mm=float(params.get("cooling_hole_dia_mm", 0)),
        axis=str(params.get("cooling_hole_axis", "Z")),
    )

    # 6. Cut coverplate bolt ring
    result = _cut_coverplate_bolt_ring(result, params)

    # 7. Cut balance hole ring
    result = _cut_balance_hole_ring(result, params)

    # 8. Cut rim slots
    result = _cut_rim_slots(cq, result, params)

    # 9. Build metadata
    warnings: list[str] = [
        "axisymmetric_turbine_disk is non-flight reference geometry only.",
        "Not airworthy, not certified, not manufacturing-ready.",
        "No real fir-tree slots, blade attachment, material, stress, life, or cooling-flow validation is performed.",
        "Rim slots are visual/reference fir-tree-like features only.",
        "They are not certified blade attachment geometry.",
        "No contact stress, centrifugal load path, fatigue life, or burst margin is validated.",
    ]

    metadata = _metadata(params, profile_points, warnings)

    return result, metadata
