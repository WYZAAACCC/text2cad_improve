"""GeometryRuntime protocol — abstract backend for STEP export and solid inspection.

Implementations: CadQueryRuntime, mock runtimes for testing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GeometryRuntime(Protocol):
    """Protocol that all geometry backends must satisfy.

    CadQuery is one implementation, not the architecture itself.
    """

    runtime_id: str
    runtime_version: str

    def export_step(self, solid_obj: Any, out_step: Path) -> None:
        ...

    def inspect_solid(self, solid_obj: Any) -> dict:
        ...

    def validate_closed_solid(self, solid_obj: Any) -> dict:
        ...

    def compute_bbox_mm(self, solid_obj: Any) -> list[float] | None:
        ...

    def count_bodies(self, solid_obj: Any) -> int | None:
        ...
