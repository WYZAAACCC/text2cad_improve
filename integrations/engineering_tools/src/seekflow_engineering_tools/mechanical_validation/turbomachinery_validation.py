from __future__ import annotations

from typing import Any


PRIMITIVE_NAME = "axisymmetric_turbine_disk"
ALLOWED_KERNELS = {
    "cadquery_axisymmetric_revolve_v0",
    "cadquery_turbine_disk_reference_v2",
}
DEFAULT_KERNEL = "cadquery_turbine_disk_reference_v2"
ALLOWED_QUALITY_GRADES = {"concept_geometry", "engineering_reference"}


def _issue(code: str, message: str, *, expected=None, actual=None, severity: str = "error") -> dict:
    item = {"code": code, "message": message, "severity": severity}
    if expected is not None:
        item["expected"] = expected
    if actual is not None:
        item["actual"] = actual
    return item


def _float_equal(a: Any, b: Any, tol: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _expected_reference_dimensions(params: dict) -> dict[str, Any]:
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
        "coverplate_bolt_count": int(params.get("coverplate_bolt_count", 0)),
        "balance_hole_count": int(params.get("balance_hole_count", 0)),
        "rim_slot_count": int(params.get("rim_slot_count", 0)),
        "rim_slot_style": str(params.get("rim_slot_style", "none")),
        "rim_slot_depth_mm": float(params.get("rim_slot_depth_mm", 0.0)),
        "rim_slot_width_mm": float(params.get("rim_slot_width_mm", 0.0)),
        "front_hub_sleeve_height_mm": float(params.get("front_hub_sleeve_height_mm", 0.0)),
        "front_hub_sleeve_outer_dia_mm": float(params.get("front_hub_sleeve_outer_dia_mm", 0.0)),
        "front_hub_sleeve_inner_dia_mm": float(params.get("front_hub_sleeve_inner_dia_mm", 0.0)),
        "expected_periodic_slot_count": int(params.get("rim_slot_count", 0)),
        "expected_through_hole_count": (
            1
            + int(params.get("bolt_hole_count", 0))
            + int(params.get("lightening_hole_count", 0))
            + int(params.get("cooling_hole_count", 0))
            + int(params.get("coverplate_bolt_count", 0))
            + int(params.get("balance_hole_count", 0))
        ),
    }


def validate_axisymmetric_turbine_disk_result(
    params: dict,
    inspection: dict,
    metadata: dict | None = None,
    tolerance_mm: float = 0.5,
    expected: dict | None = None,
    raw_metadata: dict | None = None,
) -> dict:
    expected = expected or {}
    issues: list[dict] = []

    ref = _expected_reference_dimensions(params)

    # ── metadata missing ──
    if metadata is None:
        issues.append(_issue(
            "turbine_disk_metadata_missing",
            "Turbine disk metadata sidecar is required for mechanical validation.",
        ))
        return {
            "ok": False, "primitive": PRIMITIVE_NAME,
            "issues": issues, "reference_dimensions": ref, "kernel": "unknown",
        }

    kernel = metadata.get("kernel", "unknown")

    # ── primitive name match ──
    if metadata.get("primitive") != PRIMITIVE_NAME:
        issues.append(_issue(
            "primitive_mismatch",
            f"Metadata primitive field is {metadata.get('primitive')!r}, expected {PRIMITIVE_NAME!r}.",
            expected=PRIMITIVE_NAME, actual=metadata.get("primitive"),
        ))

    # ── kernel check (allow both v0 and v2) ──
    if kernel not in ALLOWED_KERNELS:
        issues.append(_issue(
            "turbine_disk_kernel_mismatch",
            f"Expected kernel one of {sorted(ALLOWED_KERNELS)}, got {kernel!r}.",
            expected=sorted(ALLOWED_KERNELS), actual=kernel,
        ))

    # ── quality grade ──
    quality = params.get("quality_grade", "concept_geometry")
    if quality not in ALLOWED_QUALITY_GRADES:
        issues.append(_issue(
            "turbine_disk_quality_grade_invalid",
            f"quality_grade must be one of {sorted(ALLOWED_QUALITY_GRADES)}, got {quality!r}.",
            expected=sorted(ALLOWED_QUALITY_GRADES), actual=quality,
        ))

    # ── non_flight_reference_only ──
    if params.get("non_flight_reference_only") is not True:
        issues.append(_issue(
            "turbine_disk_non_flight_flag_missing",
            "CAD-IR parameter non_flight_reference_only must be True.",
            expected=True, actual=params.get("non_flight_reference_only"),
        ))

    # ── safety flags ──
    safety = metadata.get("safety") or {}
    for key in ["non_flight_reference_only", "not_for_manufacturing", "not_airworthy", "not_certified"]:
        if safety.get(key) is not True:
            issues.append(_issue(
                f"turbine_disk_safety_{key}_missing",
                f"Metadata safety.{key} must be True.",
                expected=True, actual=safety.get(key),
            ))

    # ── v0.2: geometry_family ──
    gf = metadata.get("geometry_family")
    if gf != "axisymmetric_base_with_cyclic_rim_features":
        issues.append(_issue(
            "turbine_disk_geometry_family_mismatch",
            "Metadata geometry_family must be 'axisymmetric_base_with_cyclic_rim_features'.",
            expected="axisymmetric_base_with_cyclic_rim_features", actual=gf,
        ))

    # ── v0.2: visual_fidelity ──
    visual = metadata.get("visual_fidelity") or {}
    if visual.get("contains_real_blade_attachment") is not False:
        issues.append(_issue(
            "turbine_disk_real_blade_attachment_flag",
            "visual_fidelity.contains_real_blade_attachment must be False.",
            expected=False, actual=visual.get("contains_real_blade_attachment"),
        ))

    # ── v0.2: rim_features consistency ──
    if int(params.get("rim_slot_count", 0)) > 0:
        rim = metadata.get("rim_features") or {}
        if int(rim.get("slot_count", -1)) != int(params["rim_slot_count"]):
            issues.append(_issue(
                "turbine_disk_rim_slot_count_mismatch",
                "rim_features.slot_count does not match params.rim_slot_count.",
                expected=int(params["rim_slot_count"]), actual=rim.get("slot_count"),
            ))
        if visual.get("contains_cyclic_rim_slots") is not True:
            issues.append(_issue(
                "turbine_disk_visual_fidelity_slots",
                "visual_fidelity.contains_cyclic_rim_slots must be True when rim_slot_count > 0.",
                expected=True, actual=visual.get("contains_cyclic_rim_slots"),
            ))

    # ── v0.2: hub_sleeve consistency ──
    front_height = float(params.get("front_hub_sleeve_height_mm", 0.0))
    if front_height > 0:
        sleeve = metadata.get("hub_sleeve") or {}
        s_height = float(sleeve.get("front_height_mm", -1.0))
        if not _float_equal(s_height, front_height, 0.1):
            issues.append(_issue(
                "turbine_disk_hub_sleeve_height_mismatch",
                "Metadata hub_sleeve.front_height_mm does not match params.",
                expected=front_height, actual=s_height,
            ))

    # ── v0.2: expected_kernel check ──
    if expected:
        expected_kernel = expected.get("expected_kernel")
        if expected_kernel and kernel != expected_kernel:
            issues.append(_issue(
                "turbine_disk_expected_kernel_mismatch",
                "Expected kernel mismatch.",
                expected=expected_kernel, actual=kernel,
            ))

    # ── parameter consistency ──
    meta_params = metadata.get("parameters") or {}
    # Only check essential v0.2 params (skip float equality for all)
    for key in ["rim_slot_count", "rim_slot_style", "front_hub_sleeve_height_mm"]:
        if key in params:
            pv = params[key]
            mv = meta_params.get(key)
            if isinstance(pv, float):
                if not _float_equal(mv, pv, tolerance_mm):
                    issues.append(_issue(
                        f"turbine_disk_parameter_mismatch_{key}",
                        f"Metadata parameter {key} does not match.",
                        expected=pv, actual=mv,
                    ))
            elif mv != pv:
                issues.append(_issue(
                    f"turbine_disk_parameter_mismatch_{key}",
                    f"Metadata parameter {key} does not match.",
                    expected=pv, actual=mv,
                ))

    # ── reference dimensions check ──
    ref_meta = metadata.get("reference_dimensions") or {}
    for key in ["rim_slot_count", "rim_slot_style", "front_hub_sleeve_height_mm", "expected_periodic_slot_count"]:
        if key in ref:
            ev = ref[key]
            av = ref_meta.get(key)
            if isinstance(ev, float):
                if not _float_equal(av, ev, tolerance_mm):
                    issues.append(_issue(
                        f"turbine_disk_reference_dimension_mismatch_{key}",
                        f"Reference dimension {key} mismatch.",
                        expected=ev, actual=av,
                    ))
            elif av != ev:
                issues.append(_issue(
                    f"turbine_disk_reference_dimension_mismatch_{key}",
                    f"Reference dimension {key} mismatch.",
                    expected=ev, actual=av,
                ))

    # ── bbox ──
    bbox = inspection.get("bbox_mm")
    if bbox and len(bbox) >= 3:
        expected_z = (
            float(params["axial_width_mm"])
            + float(params.get("front_hub_sleeve_height_mm", 0.0))
            + float(params.get("rear_hub_sleeve_height_mm", 0.0))
        )
        if abs(float(bbox[0]) - ref["outer_dia_mm"]) > tolerance_mm:
            issues.append(_issue(
                "turbine_disk_bbox_x_mismatch",
                "BBox X does not match outer_dia_mm.",
                expected=ref["outer_dia_mm"], actual=bbox[0],
            ))
        if abs(float(bbox[1]) - ref["outer_dia_mm"]) > tolerance_mm:
            issues.append(_issue(
                "turbine_disk_bbox_y_mismatch",
                "BBox Y does not match outer_dia_mm.",
                expected=ref["outer_dia_mm"], actual=bbox[1],
            ))
        if abs(float(bbox[2]) - expected_z) > tolerance_mm:
            issues.append(_issue(
                "turbine_disk_bbox_z_mismatch",
                "BBox Z does not match axial_width + hub_sleeve heights.",
                expected=expected_z, actual=bbox[2],
            ))
    else:
        issues.append(_issue("turbine_disk_bbox_missing", "Inspection did not provide bbox_mm."))

    # ── body count ──
    actual_body = inspection.get("solid_count") or inspection.get("body_count")
    if actual_body is None:
        issues.append(_issue("turbine_disk_body_count_missing", "Inspection did not report body/solid count."))
    elif int(actual_body) != 1:
        issues.append(_issue(
            "turbine_disk_body_count_mismatch",
            "Turbine disk primitive must produce exactly one solid body.",
            expected=1, actual=actual_body,
        ))

    ok = not any(i["severity"] == "error" for i in issues)
    return {
        "ok": ok,
        "primitive": PRIMITIVE_NAME,
        "issues": issues,
        "reference_dimensions": ref,
        "kernel": kernel,
    }
