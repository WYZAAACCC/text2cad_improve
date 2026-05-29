"""GcadRunResult — runner output with step_path, metadata_path, artifact."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GcadRunResult:
    ok: bool
    step_path: Path | None = None
    metadata_path: Path | None = None
    artifact: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    degraded_features: list[dict[str, Any]] = field(default_factory=list)
    operation_metrics: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
