"""Mechanical validation for involute spur gear geometry."""

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

    Checks:
      - bbox roughly matches outer diameter and face width
      - kernel is not fallback (warns if fallback)
      - metadata contains primitive info
      - reference dimensions are computed and reasonable

    Returns:
      {"ok": bool, "issues": list[dict], "reference_dimensions": dict, "kernel": str}
    """
    ref = spur_gear_reference_dimensions(params)
    issues: list[dict] = []

    kernel = "unknown"
    if metadata:
        kernel = metadata.get("kernel", "unknown")
        if metadata.get("primitive") != "involute_spur_gear":
            issues.append({
                "code": "primitive_mismatch",
                "message": "Metadata primitive field is not 'involute_spur_gear'.",
                "severity": "warning",
            })

    # Check kernel
    if kernel == "cadquery_visual_fallback":
        issues.append({
            "code": "gear_visual_fallback_used",
            "message": (
                "Visual fallback gear was used instead of CQ_Gears. "
                "This is NOT certified involute geometry."
            ),
            "severity": "warning",
        })
    elif kernel == "unknown":
        issues.append({
            "code": "gear_kernel_unknown",
            "message": "Could not determine gear kernel from metadata.",
            "severity": "warning",
        })

    # Bbox checks
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

    # Check reference dimensions keys
    required_keys = ["pitch_diameter_mm", "base_diameter_mm", "outer_diameter_mm", "root_diameter_mm"]
    if metadata and "reference_dimensions" in metadata:
        for k in required_keys:
            if k not in metadata["reference_dimensions"]:
                issues.append({
                    "code": "reference_dimension_missing",
                    "message": f"Reference dimension '{k}' missing from metadata.",
                    "severity": "warning",
                })
    else:
        issues.append({
            "code": "reference_dimensions_missing",
            "message": "No reference_dimensions in metadata.",
            "severity": "warning",
        })

    ok = not any(i["severity"] == "error" for i in issues)

    return {
        "ok": ok,
        "issues": issues,
        "reference_dimensions": ref,
        "kernel": kernel,
    }
