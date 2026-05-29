"""Artifact validation — validates generative STEP output against contract.

Separate from the CADPartSpec validation path.
"""

from __future__ import annotations


def validate_artifact_against_generative_contract(
    inspection: dict,
    spec,  # GenerativeCADSpec
) -> dict:
    """Validate inspection results against a GenerativeCADSpec contract.

    Returns {"ok": bool, "issues": [...]}.
    """
    issues: list[dict] = []
    contract = spec.system_validation_contract

    # Check for inspection errors
    if inspection.get("error"):
        issues.append({
            "code": "inspection_error",
            "message": f"Inspection failed: {inspection['error']}",
            "severity": "error",
        })
        return {"ok": False, "issues": issues}

    # Solid count
    solid_count = inspection.get("solid_count")
    if solid_count is not None:
        if solid_count != contract.expected_body_count:
            issues.append({
                "code": "body_count_mismatch",
                "message": (
                    f"Expected {contract.expected_body_count} body(s), "
                    f"got {solid_count}."
                ),
                "expected": contract.expected_body_count,
                "actual": solid_count,
                "severity": "error",
            })

    # Bbox check
    if contract.expected_bbox_mm is not None:
        bbox = inspection.get("bbox_mm")
        if bbox is not None:
            for i, (exp, act) in enumerate(zip(contract.expected_bbox_mm, bbox)):
                if abs(exp - act) > contract.bbox_tolerance_mm:
                    axis = ["X", "Y", "Z"][i]
                    issues.append({
                        "code": "bbox_mismatch",
                        "message": (
                            f"Bbox {axis}: expected {exp} ± {contract.bbox_tolerance_mm}, "
                            f"got {act}."
                        ),
                        "expected": exp,
                        "actual": act,
                        "severity": "error",
                    })

    return {"ok": len(issues) == 0, "issues": issues}
