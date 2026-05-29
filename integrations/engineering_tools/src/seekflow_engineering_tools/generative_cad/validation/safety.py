"""Safety validation — all safety flags must be True."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_safety(raw: RawGcadDocument) -> ValidationReport:
    issues = []
    # Safety flags are validated by RawSafety Pydantic model, but we double-check here
    for key, value in raw.safety.model_dump().items():
        if value is not True:
            issues.append(ValidationReport.fail(
                "safety", f"safety_{key}_false",
                f"safety flag {key} must be true, got {value!r}",
            ).issues[0])

    if issues:
        return ValidationReport(ok=False, stage="safety", issues=issues)
    return ValidationReport.ok_report("safety")
