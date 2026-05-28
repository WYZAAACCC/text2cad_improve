from __future__ import annotations

from typing import Any


PRIMITIVE_NAME = "axisymmetric_turbine_disk"
KERNEL_NAME = "cadquery_axisymmetric_revolve_v0"
ALLOWED_QUALITY_GRADES = {"concept_geometry", "engineering_reference"}


def _issue(code: str, message: str, *, expected=None, actual=None, severity: str = "error") -> dict:
    item = {
        "code": code,
        "message": message,
        "severity": severity,
    }
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
        "bolt_hole_count": int(params["bolt_hole_count"]),
        "lightening_hole_count": int(params["lightening_hole_count"]),
        "cooling_hole_count": int(params["cooling_hole_count"]),
        "expected_through_hole_count": (
            1
            + int(params["bolt_hole_count"])
            + int(params["lightening_hole_count"])
            + int(params["cooling_hole_count"])
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

    if metadata is None:
        issues.append(
            _issue(
                "turbine_disk_metadata_missing",
                "Turbine disk metadata sidecar is required for mechanical validation.",
            )
        )
        return {
            "ok": False,
            "primitive": PRIMITIVE_NAME,
            "issues": issues,
            "reference_dimensions": ref,
            "kernel": "unknown",
        }

    kernel = metadata.get("kernel", "unknown")

    if metadata.get("primitive") != PRIMITIVE_NAME:
        issues.append(
            _issue(
                "primitive_mismatch",
                f"Metadata primitive field is {metadata.get('primitive')!r}, expected {PRIMITIVE_NAME!r}.",
                expected=PRIMITIVE_NAME,
                actual=metadata.get("primitive"),
            )
        )

    if kernel != KERNEL_NAME:
        issues.append(
            _issue(
                "turbine_disk_kernel_mismatch",
                f"Expected kernel {KERNEL_NAME!r}, got {kernel!r}.",
                expected=KERNEL_NAME,
                actual=kernel,
            )
        )

    quality = params.get("quality_grade", "concept_geometry")
    if quality not in ALLOWED_QUALITY_GRADES:
        issues.append(
            _issue(
                "turbine_disk_quality_grade_invalid",
                f"quality_grade must be one of {sorted(ALLOWED_QUALITY_GRADES)}, got {quality!r}.",
                expected=sorted(ALLOWED_QUALITY_GRADES),
                actual=quality,
            )
        )

    if params.get("non_flight_reference_only") is not True:
        issues.append(
            _issue(
                "turbine_disk_non_flight_flag_missing",
                "CAD-IR parameter non_flight_reference_only must be True.",
                expected=True,
                actual=params.get("non_flight_reference_only"),
            )
        )

    safety = metadata.get("safety") or {}
    for key in [
        "non_flight_reference_only",
        "not_for_manufacturing",
        "not_airworthy",
        "not_certified",
    ]:
        if safety.get(key) is not True:
            issues.append(
                _issue(
                    f"turbine_disk_safety_{key}_missing",
                    f"Metadata safety.{key} must be True.",
                    expected=True,
                    actual=safety.get(key),
                )
            )

    meta_params = metadata.get("parameters") or {}
    for key, expected_value in params.items():
        actual_value = meta_params.get(key)
        if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            if not _float_equal(actual_value, expected_value, tolerance_mm):
                issues.append(
                    _issue(
                        f"turbine_disk_parameter_mismatch_{key}",
                        f"Metadata parameter {key} does not match CAD-IR parameter.",
                        expected=expected_value,
                        actual=actual_value,
                    )
                )
        else:
            if actual_value != expected_value:
                issues.append(
                    _issue(
                        f"turbine_disk_parameter_mismatch_{key}",
                        f"Metadata parameter {key} does not match CAD-IR parameter.",
                        expected=expected_value,
                        actual=actual_value,
                    )
                )

    ref_meta = metadata.get("reference_dimensions") or {}
    for key, expected_value in ref.items():
        actual_value = ref_meta.get(key)
        if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            if not _float_equal(actual_value, expected_value, tolerance_mm):
                issues.append(
                    _issue(
                        f"turbine_disk_reference_dimension_mismatch_{key}",
                        f"Reference dimension {key} mismatch.",
                        expected=expected_value,
                        actual=actual_value,
                    )
                )
        else:
            if actual_value != expected_value:
                issues.append(
                    _issue(
                        f"turbine_disk_reference_dimension_mismatch_{key}",
                        f"Reference dimension {key} mismatch.",
                        expected=expected_value,
                        actual=actual_value,
                    )
                )

    bbox = inspection.get("bbox_mm")
    if bbox and len(bbox) >= 3:
        if abs(float(bbox[0]) - ref["outer_dia_mm"]) > tolerance_mm:
            issues.append(
                _issue(
                    "turbine_disk_bbox_x_mismatch",
                    "BBox X does not match outer_dia_mm.",
                    expected=ref["outer_dia_mm"],
                    actual=bbox[0],
                )
            )
        if abs(float(bbox[1]) - ref["outer_dia_mm"]) > tolerance_mm:
            issues.append(
                _issue(
                    "turbine_disk_bbox_y_mismatch",
                    "BBox Y does not match outer_dia_mm.",
                    expected=ref["outer_dia_mm"],
                    actual=bbox[1],
                )
            )
        if abs(float(bbox[2]) - ref["axial_width_mm"]) > tolerance_mm:
            issues.append(
                _issue(
                    "turbine_disk_bbox_z_mismatch",
                    "BBox Z does not match axial_width_mm.",
                    expected=ref["axial_width_mm"],
                    actual=bbox[2],
                )
            )
    else:
        issues.append(
            _issue(
                "turbine_disk_bbox_missing",
                "Inspection did not provide bbox_mm.",
            )
        )

    actual_body = inspection.get("solid_count") or inspection.get("body_count")
    if actual_body is None:
        issues.append(
            _issue(
                "turbine_disk_body_count_missing",
                "Inspection did not report body/solid count.",
            )
        )
    elif int(actual_body) != 1:
        issues.append(
            _issue(
                "turbine_disk_body_count_mismatch",
                "Turbine disk primitive must produce exactly one solid body.",
                expected=1,
                actual=actual_body,
            )
        )

    if expected:
        expected_kernel = expected.get("expected_kernel")
        if expected_kernel and kernel != expected_kernel:
            issues.append(
                _issue(
                    "turbine_disk_expected_kernel_mismatch",
                    "Expected kernel mismatch.",
                    expected=expected_kernel,
                    actual=kernel,
                )
            )

        expected_holes = expected.get("expected_through_hole_count")
        if expected_holes is not None and int(expected_holes) != int(ref["expected_through_hole_count"]):
            issues.append(
                _issue(
                    "turbine_disk_expected_hole_count_mismatch",
                    "Expected through hole count mismatch.",
                    expected=expected_holes,
                    actual=ref["expected_through_hole_count"],
                )
            )

    ok = not any(i["severity"] == "error" for i in issues)

    return {
        "ok": ok,
        "primitive": PRIMITIVE_NAME,
        "issues": issues,
        "reference_dimensions": ref,
        "kernel": kernel,
    }
