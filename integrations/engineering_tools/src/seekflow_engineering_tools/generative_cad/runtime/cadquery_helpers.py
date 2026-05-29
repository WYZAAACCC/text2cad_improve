"""CadQuery operation helpers — thin wrappers for translate/rotate/union/cut/export.

Does NOT replace primitive deterministic kernels. Used only by generative dialect handlers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def cq_translate(obj: Any, vector: tuple[float, float, float]) -> Any:
    return obj.translate(vector)


def cq_rotate(obj: Any, origin: tuple[float, float, float], axis: tuple[float, float, float], angle_deg: float) -> Any:
    return obj.rotate(origin, axis, angle_deg)


def cq_union(a: Any, b: Any) -> Any:
    return a.union(b)


def cq_cut(target: Any, tool: Any) -> Any:
    return target.cut(tool)


def cq_export_step(obj: Any, path: Path) -> None:
    import cadquery as cq
    cq.exporters.export(obj, str(path))
