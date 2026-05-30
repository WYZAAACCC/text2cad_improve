"""Structured parse layer for RawGcadDocument — pre-Pydantic missing key detection.

Provides path-aware errors usable by repair loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "document_id",
    "part_name",
    "units",
    "trust_level",
    "selected_dialects",
    "components",
    "nodes",
    "constraints",
    "safety",
}

REQUIRED_SAFETY_KEYS = {
    "non_flight_reference_only",
    "not_airworthy",
    "not_certified",
    "not_for_manufacturing",
    "not_for_installation",
    "no_structural_validation",
    "no_life_prediction",
}

REQUIRED_CONSTRAINT_KEYS = {
    "require_step_file",
    "require_metadata_sidecar",
    "require_closed_solid",
    "expected_body_count",
}


@dataclass(frozen=True)
class RawParseIssue:
    code: str
    message: str
    path: str
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True)
class RawParseResult:
    ok: bool
    document: "RawGcadDocument | None" = None  # noqa: F821
    issues: list[RawParseIssue] = field(default_factory=list)


def parse_raw_gcad_document(data: dict) -> RawParseResult:
    """Parse a dict into RawGcadDocument with structured missing-key errors.

    1. Check top-level required keys.
    2. Check nested safety keys.
    3. Check nested constraint keys.
    4. Attempt Pydantic model_validate, mapping ValidationError to structured issues.
    """
    from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument

    issues: list[RawParseIssue] = []

    # 1. Top-level required keys
    if not isinstance(data, dict):
        return RawParseResult(
            ok=False,
            issues=[RawParseIssue(
                code="not_a_dict",
                message="Input must be a JSON object (dict).",
                path="/",
            )],
        )

    for key in sorted(REQUIRED_TOP_LEVEL_KEYS):
        if key not in data:
            issues.append(RawParseIssue(
                code="missing_required_field",
                message=f"RawGcadDocument.{key} is required and must be explicit.",
                path=f"/{key}",
            ))

    if issues:
        return RawParseResult(ok=False, issues=issues)

    # 2. Nested safety keys
    safety = data.get("safety")
    if isinstance(safety, dict):
        for key in sorted(REQUIRED_SAFETY_KEYS):
            if key not in safety:
                issues.append(RawParseIssue(
                    code="missing_required_field",
                    message=f"RawGcadDocument.safety.{key} is required and must be explicit.",
                    path=f"/safety/{key}",
                ))
    elif safety is not None:
        issues.append(RawParseIssue(
            code="invalid_safety_type",
            message="RawGcadDocument.safety must be a JSON object.",
            path="/safety",
        ))

    # 3. Nested constraint keys
    constraints = data.get("constraints")
    if isinstance(constraints, dict):
        for key in sorted(REQUIRED_CONSTRAINT_KEYS):
            if key not in constraints:
                issues.append(RawParseIssue(
                    code="missing_required_field",
                    message=f"RawGcadDocument.constraints.{key} is required and must be explicit.",
                    path=f"/constraints/{key}",
                ))
    elif constraints is not None:
        issues.append(RawParseIssue(
            code="invalid_constraints_type",
            message="RawGcadDocument.constraints must be a JSON object.",
            path="/constraints",
        ))

    if issues:
        return RawParseResult(ok=False, issues=issues)

    # 4. Pydantic model_validate
    try:
        document = RawGcadDocument.model_validate(data)
    except Exception as exc:
        return RawParseResult(
            ok=False,
            issues=[RawParseIssue(
                code="pydantic_validation_failed",
                message=str(exc),
                path="/",
            )],
        )

    return RawParseResult(ok=True, document=document)
