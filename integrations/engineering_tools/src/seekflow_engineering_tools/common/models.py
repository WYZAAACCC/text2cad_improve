"""Unified return types for all engineering tool actions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EngineeringActionResult(BaseModel):
    """Every engineering tool returns this structure – never raw objects."""

    ok: bool
    software: Literal["solidworks", "nx", "ansys"]
    action: str

    message: str = ""
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)

    log_path: str | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None

    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
