"""Mechanical validation for involute spur gear geometry — fail-closed."""

from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.gears.standards import (
    spur_gear_reference_dimensions,
)


def validate_involute_spur_gear_result(
    params: dict,
    inspection: dict,
    metadata: dict | None = None,
    tolerance_mm: float = 0.1,
) -> dict:
    """Validate an involute spur gear build result.

    FAIL-CLOSED: all checks that were previously warnings are now errors.
    Engineering-grade gears must have complete metadata, standard involute
    geometry, and matching reference dimensions.

    Returns:
      {"ok": bool, "issues": list[dict], "reference_dimensions": dict, "kernel": str}
    """
    ref = spur_gear_reference_dimensions(params)
    issues: list[dict] = []

    # ── 1. metadata missing is a hard error ──
    if metadata is None:
        issues.append({
            "code": "gear_metadata_missing",
            "message": "Gear metadata sidecar is required for engineering validation.",
            "severity": "error",
        })
        return {
            "ok": False,
            "issues": issues,
            "reference_dimensions": ref,
            "kernel": "unknown",
        }

    kernel = metadata.get("kernel", "unknown")

    # ── 2. primitive mismatch is an error ──
    if metadata.get("primitive") != "involute_spur_gear":
        issues.append({
            "code": "primitive_mismatch",
            "message": (
                f"Metadata primitive field is '{metadata.get('primitive')}', "
                f"expected 'involute_spur_gear'."
            ),
            "severity": "error",
        })

    # ── 3. kernel unknown is an error ──
    if kernel == "unknown":
        issues.append({
            "code": "gear_kernel_unknown",
            "message": "Could not determine gear kernel from metadata.",
            "severity": "error",
        })

    # ── 4. visual fallback is an error unless explicitly allowed ──
    if kernel == "cadquery_visual_fallback":
        quality = params.get("quality_grade", "industrial_brep")
        allow_fallback = params.get("allow_visual_fallback", False)
        if quality != "visual_fallback" and not allow_fallback:
            issues.append({
                "code": "gear_visual_fallback_used",
                "message": (
                    "Visual fallback gear was used instead of CQ_Gears. "
                    "This is NOT certified involute geometry and is not "
                    "acceptable for quality_grade='{quality}'."
                ),
                "severity": "error",
            })
        else:
            issues.append({
                "code": "gear_visual_fallback_used",
                "message": (
                    "Visual fallback gear was used instead of CQ_Gears. "
                    "This is NOT certified involute geometry. "
                    "Explicitly allowed via quality_grade='visual_fallback' or allow_visual_fallback=True."
                ),
                "severity": "warning",
            })

    # ── 5. is_standard_involute must be True ──
    if metadata.get("is_standard_involute") is not True:
        issues.append({
            "code": "gear_not_standard_involute",
            "message": (
                f"Gear metadata 'is_standard_involute' is {metadata.get('is_standard_involute')}, "
                f"must be True for engineering-grade gears."
            ),
            "severity": "error",
        })

    # ── 6. reference_dimensions missing is an error ──
    ref_meta = metadata.get("reference_dimensions")
    required_keys = ["pitch_diameter_mm", "base_diameter_mm", "outer_diameter_mm", "root_diameter_mm"]
    if ref_meta is None:
        issues.append({
            "code": "reference_dimensions_missing",
            "message": "No reference_dimensions in metadata.",
            "severity": "error",
        })
    else:
        for k in required_keys:
            if k not in ref_meta:
                issues.append({
                    "code": "reference_dimension_missing",
                    "message": f"Reference dimension '{k}' missing from metadata.",
                    "severity": "error",
                })

    # ── 7. numerical comparison of reference dimensions against standard formulas ──
    if ref_meta:
        dim_tolerance_mm = max(tolerance_mm, 0.005)  # At least 5 micron tolerance
        for key, expected in [
            ("pitch_diameter_mm", ref["pitch_diameter_mm"]),
            ("base_diameter_mm", ref["base_diameter_mm"]),
            ("outer_diameter_mm", ref["outer_diameter_mm"]),
            ("root_diameter_mm", ref["root_diameter_mm"]),
        ]:
            actual = ref_meta.get(key)
            if actual is not None and expected is not None:
                if abs(actual - expected) > dim_tolerance_mm:
                    issues.append({
                        "code": f"gear_{key}_mismatch",
                        "message": (
                            f"Gear {key}: metadata={actual:.4f}, "
                            f"standard formula={expected:.4f}, "
                            f"diff={abs(actual - expected):.4f} > tolerance {dim_tolerance_mm:.4f}"
                        ),
                        "expected": expected,
                        "actual": actual,
                        "severity": "error",
                    })

    # ── 8. bbox / face_width checks ──
    bbox = inspection.get("bbox_mm")
    if bbox and len(bbox) >= 3:
        outer_d = ref["outer_diameter_mm"]
        fw = ref["face_width_mm"]

        if abs(bbox[0] - outer_d) > tolerance_mm:
            issues.append({
                "code": "gear_bbox_x_mismatch",
                "message": (
                    f"Gear bbox X ({bbox[0]:.3f}) does not match "
                    f"outer diameter ({outer_d:.3f}) within tolerance {tolerance_mm}"
                ),
                "expected": outer_d,
                "actual": bbox[0],
                "severity": "error",
            })
        if abs(bbox[1] - outer_d) > tolerance_mm:
            issues.append({
                "code": "gear_bbox_y_mismatch",
                "message": (
                    f"Gear bbox Y ({bbox[1]:.3f}) does not match "
                    f"outer diameter ({outer_d:.3f}) within tolerance {tolerance_mm}"
                ),
                "expected": outer_d,
                "actual": bbox[1],
                "severity": "error",
            })
        if abs(bbox[2] - fw) > tolerance_mm:
            issues.append({
                "code": "gear_bbox_z_mismatch",
                "message": (
                    f"Gear bbox Z ({bbox[2]:.3f}) does not match "
                    f"face width ({fw:.3f}) within tolerance {tolerance_mm}"
                ),
                "expected": fw,
                "actual": bbox[2],
                "severity": "error",
            })

    ok = not any(i["severity"] == "error" for i in issues)

    return {
        "ok": ok,
        "issues": issues,
        "reference_dimensions": ref,
        "kernel": kernel,
    }
