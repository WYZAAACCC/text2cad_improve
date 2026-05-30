"""ValidationReport and ValidationIssue models — v0.7: explicit fail/ok_report parameters."""

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
    stages_run: list[str] = Field(default_factory=list)

    @classmethod
    def ok_report(
        cls,
        stage: str,
        stages_run: list[str] | None = None,
    ) -> "ValidationReport":
        return cls(
            ok=True,
            stage=stage,
            issues=[],
            stages_run=stages_run or [stage],
        )

    @classmethod
    def fail(
        cls,
        stage: str,
        code: str,
        message: str,
        stages_run: list[str] | None = None,
        severity: Severity = "error",
        node_id: str | None = None,
        component_id: str | None = None,
        path: str | None = None,
        expected: Any | None = None,
        actual: Any | None = None,
    ) -> "ValidationReport":
        return cls(
            ok=False,
            stage=stage,
            stages_run=stages_run or [stage],
            issues=[
                ValidationIssue(
                    stage=stage,
                    code=code,
                    message=message,
                    severity=severity,
                    node_id=node_id,
                    component_id=component_id,
                    path=path,
                    expected=expected,
                    actual=actual,
                )
            ],
        )
