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

    Returns a ValidationReport with all issues found.
    """
    issues: list[ValidationIssue] = []

    # Bbox check
    if spec.validation.expected_bbox_mm and inspection.bbox_mm:
        tol = spec.validation.tolerance_mm
        for axis, exp, act in zip(
            "XYZ",
            spec.validation.expected_bbox_mm,
            inspection.bbox_mm,
        ):
            if abs(exp - act) > tol:
                issues.append(
                    ValidationIssue(
                        code="bbox_mismatch",
                        message=f"BBox {axis} mismatch",
                        expected=exp,
                        actual=act,
                    )
                )

    # Body count check
    if (
        spec.validation.expected_body_count is not None
        and inspection.body_count is not None
    ):
        if spec.validation.expected_body_count != inspection.body_count:
            issues.append(
                ValidationIssue(
                    code="body_count_mismatch",
                    message="Body count mismatch",
                    expected=spec.validation.expected_body_count,
                    actual=inspection.body_count,
                )
            )

    # Through hole count check
    if (
        spec.validation.expected_through_hole_count is not None
        and inspection.through_hole_count_estimate is not None
    ):
        if (
            spec.validation.expected_through_hole_count
            != inspection.through_hole_count_estimate
        ):
            issues.append(
                ValidationIssue(
                    code="through_hole_count_mismatch",
                    message="Through hole count mismatch",
                    expected=spec.validation.expected_through_hole_count,
                    actual=inspection.through_hole_count_estimate,
                )
            )

    return ValidationReport(
        ok=not bool(issues),
        issues=issues,
        inspection=inspection,
    )
