"""Common inspection and validation data models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelInspection(BaseModel):
    bbox_mm: list[float] | None = None
    volume_mm3: float | None = None
    mass_g: float | None = None
    body_count: int | None = None
    face_count: int | None = None
    edge_count: int | None = None
    hole_count_estimate: int | None = None
    through_hole_count_estimate: int | None = None
    feature_names: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    code: str
    message: str
    expected: object | None = None
    actual: object | None = None
    severity: str = "error"


class ValidationReport(BaseModel):
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    inspection: ModelInspection | None = None
