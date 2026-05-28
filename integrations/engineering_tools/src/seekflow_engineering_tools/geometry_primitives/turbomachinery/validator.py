from __future__ import annotations

import math


ALLOWED_QUALITY_GRADES = {"concept_geometry", "engineering_reference"}
FORBIDDEN_QUALITY_GRADES = {
    "flight_ready",
    "airworthy",
    "certified",
    "manufacturing_ready",
    "production_ready",
    "installable",
}

ALLOWED_RIM_SLOT_STYLES = {"none", "rectangular", "dovetail", "fir_tree_like"}
ALLOWED_RIM_SLOT_ORIENTATIONS = {"axial_through", "side_groove"}
ALLOWED_RIM_SLOT_SOCKET_MODES = {"simple_open_slot", "internal_lobes"}
ALLOWED_RIM_SLOT_PROFILE_SYMMETRIES = {"mirror_y"}
ALLOWED_RIM_SLOT_STAGE_DISTRIBUTIONS = {"uniform", "progressive"}


def _f(params: dict, key: str) -> float:
    return float(params.get(key, 0.0))


def _i(params: dict, key: str) -> int:
    return int(params.get(key, 0))


def _validate_hole_ring(
    errors: list[str],
    *,
    name: str,
    count: int,
    pcd_mm: float,
    hole_dia_mm: float,
    axis: str,
    min_radius_mm: float,
    max_radius_mm: float,
    radial_margin_mm: float,
) -> None:
    if count == 0:
        if pcd_mm != 0:
            errors.append(f"{name}_pcd_mm must be 0 when {name}_hole_count is 0")
        if hole_dia_mm != 0:
            errors.append(f"{name}_hole_dia_mm must be 0 when {name}_hole_count is 0")
        return

    if count < 2:
        errors.append(f"{name}_hole_count must be 0 or >= 2")
        return

    if axis != "Z":
        errors.append(f"{name}_hole_axis must be 'Z' in v0.1")

    if pcd_mm <= 0:
        errors.append(f"{name}_pcd_mm must be > 0 when {name}_hole_count > 0")
        return

    if hole_dia_mm <= 0:
        errors.append(f"{name}_hole_dia_mm must be > 0 when {name}_hole_count > 0")
        return

    ring_radius = pcd_mm / 2.0
    hole_radius = hole_dia_mm / 2.0

    if ring_radius - hole_radius - radial_margin_mm <= min_radius_mm:
        errors.append(
            f"{name} hole ring intrudes inward: "
            f"ring_radius({ring_radius}) - hole_radius({hole_radius}) - margin({radial_margin_mm}) "
            f"must be > min_radius({min_radius_mm})"
        )

    if ring_radius + hole_radius + radial_margin_mm >= max_radius_mm:
        errors.append(
            f"{name} hole ring intrudes outward: "
            f"ring_radius({ring_radius}) + hole_radius({hole_radius}) + margin({radial_margin_mm}) "
            f"must be < max_radius({max_radius_mm})"
        )

    chord_spacing = 2.0 * ring_radius * math.sin(math.pi / count)
    if chord_spacing <= hole_dia_mm * 1.25:
        errors.append(
            f"{name} holes are too close: chord spacing {chord_spacing:.3f} mm "
            f"must be > 1.25 * hole_dia_mm ({hole_dia_mm * 1.25:.3f} mm)"
        )


def _validate_rim_slots(errors: list[str], params: dict) -> None:
    style = str(params.get("rim_slot_style", "none"))
    orientation = str(params.get("rim_slot_orientation", "axial_through"))
    socket_mode = str(params.get("rim_slot_socket_mode", "internal_lobes"))
    sym = str(params.get("rim_slot_profile_symmetry", "mirror_y"))
    dist_mode = str(params.get("rim_slot_stage_depth_distribution", "uniform"))
    count = int(params.get("rim_slot_count", 0))
    expose_od = params.get("rim_slot_expose_lobes_on_od", False)
    require_stages = params.get("rim_slot_require_multiple_stages", True)
    stage_count = int(params.get("rim_slot_stage_count", 3))

    if style not in ALLOWED_RIM_SLOT_STYLES:
        errors.append(f"rim_slot_style must be one of {sorted(ALLOWED_RIM_SLOT_STYLES)}, got {style!r}")
        return
    if orientation not in ALLOWED_RIM_SLOT_ORIENTATIONS:
        errors.append(f"rim_slot_orientation must be one of {sorted(ALLOWED_RIM_SLOT_ORIENTATIONS)}, got {orientation!r}")
        return
    if socket_mode not in ALLOWED_RIM_SLOT_SOCKET_MODES:
        errors.append(f"rim_slot_socket_mode must be one of {sorted(ALLOWED_RIM_SLOT_SOCKET_MODES)}, got {socket_mode!r}")
        return
    if sym not in ALLOWED_RIM_SLOT_PROFILE_SYMMETRIES:
        errors.append(f"rim_slot_profile_symmetry must be one of {sorted(ALLOWED_RIM_SLOT_PROFILE_SYMMETRIES)}, got {sym!r}")
        return
    if dist_mode not in ALLOWED_RIM_SLOT_STAGE_DISTRIBUTIONS:
        errors.append(f"rim_slot_stage_depth_distribution must be one of {sorted(ALLOWED_RIM_SLOT_STAGE_DISTRIBUTIONS)}, got {dist_mode!r}")
        return

    if style == "none":
        if count != 0:
            errors.append("rim_slot_count must be 0 when rim_slot_style='none'")
        return

    outer_d = float(params["outer_dia_mm"])
    rim_inner_d = float(params["rim_inner_dia_mm"])
    r_outer = outer_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    rim_radial = r_outer - r_rim_inner

    depth = float(params.get("rim_slot_depth_mm", 0.0))
    axial_margin = float(params.get("rim_slot_axial_margin_mm", 0.0))
    through_clearance = float(params.get("rim_slot_through_clearance_mm", 0.0))

    if count < 12:
        errors.append("rim_slot_count must be >= 12 when enabled")
    if depth <= 0:
        errors.append("rim_slot_depth_mm must be > 0")
    if depth >= rim_radial * 0.85:
        errors.append("rim_slot_depth_mm too large; would cut too deeply")

    if orientation == "axial_through":
        if axial_margin != 0:
            errors.append("axial_through requires rim_slot_axial_margin_mm == 0")
        if through_clearance <= 0:
            errors.append("axial_through requires rim_slot_through_clearance_mm > 0")

    mouth_w = float(params.get("rim_slot_mouth_width_mm", 0.0))
    throat_w = float(params.get("rim_slot_throat_width_mm", 0.0))
    stage_neck_w = float(params.get("rim_slot_stage_neck_width_mm", 0.0))
    stage_lobe_w = float(params.get("rim_slot_stage_lobe_width_mm", 0.0))
    root_w = float(params.get("rim_slot_root_width_mm", 0.0))
    stage_pitch = float(params.get("rim_slot_stage_pitch_mm", 0.0))
    stage_lobe_h = float(params.get("rim_slot_stage_lobe_height_mm", 0.0))
    width_growth = float(params.get("rim_slot_stage_width_growth", 0.0))

    if sym != "mirror_y":
        errors.append(f"rim_slot_profile_symmetry must be mirror_y, got {sym!r}")

    if require_stages and stage_count < 2:
        errors.append(f"rim_slot_require_multiple_stages=True needs stage_count>=2, got {stage_count}")
    if style == "fir_tree_like" and stage_count < 2:
        errors.append("fir_tree_like requires rim_slot_stage_count >= 2 for symmetric multistage")

    if stage_pitch <= 0: errors.append("rim_slot_stage_pitch_mm must be > 0")
    if stage_neck_w <= 0: errors.append("rim_slot_stage_neck_width_mm must be > 0")
    if stage_lobe_w <= stage_neck_w:
        errors.append(f"rim_slot_stage_lobe_width_mm ({stage_lobe_w}) must be > stage_neck_width ({stage_neck_w})")
    if stage_lobe_h <= 0: errors.append("rim_slot_stage_lobe_height_mm must be > 0")
    if width_growth < 0: errors.append("rim_slot_stage_width_growth must be >= 0")

    if mouth_w <= 0: errors.append("rim_slot_mouth_width_mm must be > 0")
    if throat_w <= 0: errors.append("rim_slot_throat_width_mm must be > 0")
    if root_w <= 0: errors.append("rim_slot_root_width_mm must be > 0")

    if mouth_w >= stage_lobe_w:
        errors.append(f"mouth_width ({mouth_w}) must be < stage_lobe_width ({stage_lobe_w})")
    if throat_w >= stage_lobe_w:
        errors.append(f"throat_width ({throat_w}) must be < stage_lobe_width ({stage_lobe_w})")
    if root_w > stage_lobe_w:
        errors.append(f"root_width ({root_w}) must be <= stage_lobe_width ({stage_lobe_w})")

    if socket_mode == "internal_lobes" and expose_od is not False:
        errors.append("rim_slot_expose_lobes_on_od must be False for internal_lobes")

    if stage_count * stage_pitch >= depth * 0.85:
        errors.append("stage_count * stage_pitch must be < rim_slot_depth_mm * 0.85")

    pitch = 2.0 * math.pi * r_outer / max(count, 1)
    max_lobe = stage_lobe_w * (1.0 + width_growth * (stage_count - 1)) if stage_count > 1 else stage_lobe_w
    if pitch <= max_lobe * 1.25:
        errors.append(f"slot pitch ({pitch:.1f}) must be > 1.25 * max_stage_lobe_width ({max_lobe * 1.25:.1f})")


def _validate_hub_sleeve(errors: list[str], params: dict) -> None:
    front_height = float(params.get("front_hub_sleeve_height_mm", 0.0))
    if front_height < 0:
        errors.append("front_hub_sleeve_height_mm must be >= 0")

    if front_height > 0:
        front_outer = float(params.get("front_hub_sleeve_outer_dia_mm", 0.0))
        front_inner = float(params.get("front_hub_sleeve_inner_dia_mm", 0.0))
        if front_outer <= front_inner:
            errors.append("front_hub_sleeve_outer_dia_mm must be > front_hub_sleeve_inner_dia_mm")
        bore_d = float(params["bore_dia_mm"])
        if front_inner < bore_d:
            errors.append("front_hub_sleeve_inner_dia_mm must be >= bore_dia_mm")

    rear_height = float(params.get("rear_hub_sleeve_height_mm", 0.0))
    if rear_height < 0:
        errors.append("rear_hub_sleeve_height_mm must be >= 0")
    if rear_height > 0:
        rear_outer = float(params.get("rear_hub_sleeve_outer_dia_mm", 0.0))
        rear_inner = float(params.get("rear_hub_sleeve_inner_dia_mm", 0.0))
        if rear_outer <= rear_inner:
            errors.append("rear_hub_sleeve_outer_dia_mm must be > rear_hub_sleeve_inner_dia_mm")


def _validate_annular_details(errors: list[str], params: dict) -> None:
    enabled = params.get("enable_annular_details", True)
    if not enabled:
        return

    # Check recess diameter ordering
    mid_inner = float(params.get("mid_web_recess_inner_dia_mm", 0.0))
    mid_outer = float(params.get("mid_web_recess_outer_dia_mm", 0.0))
    if mid_inner > 0 and mid_outer > 0 and mid_inner >= mid_outer:
        errors.append("mid_web_recess_inner_dia_mm must be < mid_web_recess_outer_dia_mm")

    outer_inner = float(params.get("outer_rim_recess_inner_dia_mm", 0.0))
    outer_outer = float(params.get("outer_rim_recess_outer_dia_mm", 0.0))
    if outer_inner > 0 and outer_outer > 0 and outer_inner >= outer_outer:
        errors.append("outer_rim_recess_inner_dia_mm must be < outer_rim_recess_outer_dia_mm")

    mid_depth = float(params.get("mid_web_recess_depth_mm", 0.0))
    outer_depth = float(params.get("outer_rim_recess_depth_mm", 0.0))
    if mid_depth < 0:
        errors.append("mid_web_recess_depth_mm must be >= 0")
    if outer_depth < 0:
        errors.append("outer_rim_recess_depth_mm must be >= 0")

    seal_count = int(params.get("seal_land_count", 0))
    if seal_count < 0:
        errors.append("seal_land_count must be >= 0")


def _validate_coverplate_balance_holes(errors: list[str], params: dict) -> None:
    for name in ["coverplate_bolt", "balance_hole"]:
        count = int(params.get(f"{name}_count", 0))
        pcd = float(params.get(f"{name}_pcd_mm", 0.0))
        dia = float(params.get(f"{name}_dia_mm", 0.0))
        if count == 0:
            if pcd != 0:
                errors.append(f"{name}_pcd_mm must be 0 when {name}_count is 0")
            if dia != 0:
                errors.append(f"{name}_dia_mm must be 0 when {name}_count is 0")
        else:
            if count < 2:
                errors.append(f"{name}_count must be 0 or >= 2")
            if pcd <= 0:
                errors.append(f"{name}_pcd_mm must be > 0 when {name}_count > 0")
            if dia <= 0:
                errors.append(f"{name}_dia_mm must be > 0 when {name}_count > 0")


def validate_axisymmetric_turbine_disk_parameters(params: dict) -> list[str]:
    errors: list[str] = []

    outer_d = _f(params, "outer_dia_mm")
    bore_d = _f(params, "bore_dia_mm")
    axial_w = _f(params, "axial_width_mm")

    hub_d = _f(params, "hub_outer_dia_mm")
    web_d = _f(params, "web_outer_dia_mm")
    rim_inner_d = _f(params, "rim_inner_dia_mm")

    hub_w = _f(params, "hub_width_mm")
    web_w = _f(params, "web_width_mm")
    rim_w = _f(params, "rim_width_mm")

    quality = str(params.get("quality_grade", "concept_geometry"))
    non_flight = params.get("non_flight_reference_only")

    if quality not in ALLOWED_QUALITY_GRADES:
        errors.append(
            f"quality_grade must be one of {sorted(ALLOWED_QUALITY_GRADES)}, got {quality!r}"
        )

    if quality in FORBIDDEN_QUALITY_GRADES:
        errors.append(
            f"quality_grade={quality!r} is forbidden for axisymmetric_turbine_disk"
        )

    if non_flight is not True:
        errors.append(
            "axisymmetric_turbine_disk requires non_flight_reference_only=True; "
            "this primitive is reference geometry only"
        )

    if outer_d <= 0:
        errors.append("outer_dia_mm must be > 0")
    if bore_d < 0:
        errors.append("bore_dia_mm must be >= 0")
    if axial_w <= 0:
        errors.append("axial_width_mm must be > 0")

    if not (bore_d < hub_d < web_d <= rim_inner_d < outer_d):
        errors.append(
            "Diameter ordering must satisfy: "
            "bore_dia_mm < hub_outer_dia_mm < web_outer_dia_mm "
            "<= rim_inner_dia_mm < outer_dia_mm"
        )

    if bore_d > 0 and bore_d >= 0.75 * hub_d:
        errors.append(
            "bore_dia_mm must be < 0.75 * hub_outer_dia_mm for stable reference geometry"
        )

    for key, value in [
        ("hub_width_mm", hub_w),
        ("web_width_mm", web_w),
        ("rim_width_mm", rim_w),
    ]:
        if value <= 0:
            errors.append(f"{key} must be > 0")
        if axial_w > 0 and value > axial_w:
            errors.append(f"{key} must be <= axial_width_mm")

    if web_w > hub_w:
        errors.append("web_width_mm must be <= hub_width_mm")
    if web_w > rim_w:
        errors.append("web_width_mm must be <= rim_width_mm")

    for key in [
        "hub_fillet_radius_mm",
        "web_fillet_radius_mm",
        "rim_fillet_radius_mm",
        "edge_chamfer_mm",
    ]:
        value = _f(params, key)
        if value < 0:
            errors.append(f"{key} must be >= 0")
        if axial_w > 0 and value > axial_w * 0.2:
            errors.append(f"{key} must be <= 0.2 * axial_width_mm in v0.1")

    r_bore = bore_d / 2.0
    r_hub = hub_d / 2.0
    r_web = web_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    r_outer = outer_d / 2.0
    radial_margin = max(1.0, outer_d * 0.005)

    _validate_hole_ring(
        errors,
        name="bolt",
        count=_i(params, "bolt_hole_count"),
        pcd_mm=_f(params, "bolt_pcd_mm"),
        hole_dia_mm=_f(params, "bolt_hole_dia_mm"),
        axis=str(params.get("bolt_hole_axis", "Z")),
        min_radius_mm=r_bore,
        max_radius_mm=r_hub,
        radial_margin_mm=radial_margin,
    )

    _validate_hole_ring(
        errors,
        name="lightening",
        count=_i(params, "lightening_hole_count"),
        pcd_mm=_f(params, "lightening_hole_pcd_mm"),
        hole_dia_mm=_f(params, "lightening_hole_dia_mm"),
        axis=str(params.get("lightening_hole_axis", "Z")),
        min_radius_mm=r_hub,
        max_radius_mm=r_rim_inner,
        radial_margin_mm=radial_margin,
    )

    _validate_hole_ring(
        errors,
        name="cooling",
        count=_i(params, "cooling_hole_count"),
        pcd_mm=_f(params, "cooling_hole_pcd_mm"),
        hole_dia_mm=_f(params, "cooling_hole_dia_mm"),
        axis=str(params.get("cooling_hole_axis", "Z")),
        min_radius_mm=r_web,
        max_radius_mm=r_outer,
        radial_margin_mm=radial_margin,
    )

    _validate_rim_slots(errors, params)
    _validate_hub_sleeve(errors, params)
    _validate_annular_details(errors, params)
    _validate_coverplate_balance_holes(errors, params)

    return errors
