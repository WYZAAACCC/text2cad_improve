"""Validate model inspection results against CAD-IR expectations."""

from __future__ import annotations

from seekflow_engineering_tools.inspection.common import (
    ModelInspection,
    ValidationIssue,
    ValidationReport,
)
from seekflow_engineering_tools.ir.cad import CADPartSpec


def validate_inspection_against_spec(
    inspection: ModelInspection, spec: CADPartSpec
) -> ValidationReport:
    """Compare a ModelInspection to the ValidationSpec in a CAD-IR.

    Rules (per v3):
    - expected_bbox_mm present but bbox_mm missing → error
    - expected_body_count present but body_count missing → error
    - expected_hole_count / expected_through_hole_count present but cannot estimate → warning
    - ok is True ONLY when no issues with severity="error" exist.
    """
    issues: list[ValidationIssue] = []
    vs = spec.validation

    # Bbox check
    if vs.expected_bbox_mm:
        if inspection.bbox_mm is None:
            issues.append(
                ValidationIssue(
                    code="bbox_missing",
                    message="expected_bbox_mm specified but bbox could not be inspected.",
                    severity="error",
                )
            )
        else:
            tol = vs.tolerance_mm
            for axis, exp, act in zip("XYZ", vs.expected_bbox_mm, inspection.bbox_mm):
                if abs(exp - act) > tol:
                    issues.append(
                        ValidationIssue(
                            code="bbox_mismatch",
                            message=f"BBox {axis} mismatch: expected {exp}, got {act:.3f}",
                            expected=exp,
                            actual=act,
                            severity="error",
                        )
                    )

    # Body count check
    if vs.expected_body_count is not None:
        if inspection.body_count is None:
            issues.append(
                ValidationIssue(
                    code="body_count_missing",
                    message="expected_body_count specified but body_count could not be inspected.",
                    severity="error",
                )
            )
        elif vs.expected_body_count != inspection.body_count:
            issues.append(
                ValidationIssue(
                    code="body_count_mismatch",
                    message=f"Body count mismatch: expected {vs.expected_body_count}, got {inspection.body_count}",
                    expected=vs.expected_body_count,
                    actual=inspection.body_count,
                    severity="error",
                )
            )

    # Hole count check
    if vs.expected_hole_count is not None:
        if inspection.hole_count_estimate is None:
            issues.append(
                ValidationIssue(
                    code="hole_count_unavailable",
                    message="expected_hole_count specified but hole_count_estimate is not available.",
                    severity="warning",
                )
            )
        elif vs.expected_hole_count != inspection.hole_count_estimate:
            issues.append(
                ValidationIssue(
                    code="hole_count_mismatch",
                    message=f"Hole count mismatch: expected {vs.expected_hole_count}, got {inspection.hole_count_estimate}",
                    expected=vs.expected_hole_count,
                    actual=inspection.hole_count_estimate,
                    severity="error",
                )
            )

    # Through hole count check
    if vs.expected_through_hole_count is not None:
        if inspection.through_hole_count_estimate is None:
            issues.append(
                ValidationIssue(
                    code="through_hole_count_unavailable",
                    message="expected_through_hole_count specified but through_hole_count_estimate is not available.",
                    severity="warning",
                )
            )
        elif vs.expected_through_hole_count != inspection.through_hole_count_estimate:
            issues.append(
                ValidationIssue(
                    code="through_hole_count_mismatch",
                    message=f"Through hole count mismatch: expected {vs.expected_through_hole_count}, got {inspection.through_hole_count_estimate}",
                    expected=vs.expected_through_hole_count,
                    actual=inspection.through_hole_count_estimate,
                    severity="error",
                )
            )

    # Feature count check
    if vs.expected_feature_count_min is not None:
        actual_count = len(inspection.feature_names) if inspection.feature_names else 0
        if actual_count < vs.expected_feature_count_min:
            issues.append(
                ValidationIssue(
                    code="feature_count_insufficient",
                    message=f"Feature count too low: expected >= {vs.expected_feature_count_min}, got {actual_count}",
                    expected=vs.expected_feature_count_min,
                    actual=actual_count,
                    severity="warning",
                )
            )

    ok = not any(i.severity == "error" for i in issues)

    return ValidationReport(
        ok=ok,
        issues=issues,
        inspection=inspection,
    )
