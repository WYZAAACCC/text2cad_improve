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

    return errors
