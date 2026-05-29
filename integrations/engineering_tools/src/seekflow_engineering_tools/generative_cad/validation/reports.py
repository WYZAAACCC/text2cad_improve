"""ValidationReport and ValidationIssue models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["error", "warning"]


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    severity: Severity = "error"
    stage: str
    node_id: str | None = None
    component_id: str | None = None
    path: str | None = None
    expected: Any | None = None
    actual: Any | None = None


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    stage: str
    issues: list[ValidationIssue] = Field(default_factory=list)

    @classmethod
    def ok_report(cls, stage: str) -> "ValidationReport":
        return cls(ok=True, stage=stage, issues=[])

    @classmethod
    def fail(cls, stage: str, code: str, message: str, **kwargs) -> "ValidationReport":
        return cls(
            ok=False,
            stage=stage,
            issues=[
                ValidationIssue(
                    stage=stage,
                    code=code,
                    message=message,
                    **kwargs,
                )
            ],
        )
