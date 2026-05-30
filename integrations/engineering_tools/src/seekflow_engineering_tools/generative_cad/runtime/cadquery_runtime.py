"""CadQueryRuntime — CadQuery-based GeometryRuntime implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import warnings


class CadQueryRuntime:
    """CadQuery backend for STEP export and solid inspection."""

    runtime_id = "cadquery"
    runtime_version = "cadquery_runtime_v1"

    def export_step(self, solid_obj: Any, out_step: Path) -> None:
        import cadquery as cq
        cq.exporters.export(solid_obj, str(out_step))

    def inspect_solid(self, solid_obj: Any) -> dict:
        """Best-effort object-level inspection."""
        try:
            return {
                "solid_count": _count_solids(solid_obj),
                "bbox_mm": self.compute_bbox_mm(solid_obj),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def validate_closed_solid(self, solid_obj: Any) -> dict:
        try:
            if hasattr(solid_obj, "isClosed") and not solid_obj.isClosed():
                return {"ok": False, "issue": "solid is not closed"}
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def compute_bbox_mm(self, solid_obj: Any) -> list[float] | None:
        """Compute bounding box. Returns None on geometry inspection failure."""
        try:
            import cadquery as cq
            if isinstance(solid_obj, cq.Assembly):
                solid_obj = solid_obj.toCompound()
            bb = solid_obj.BoundingBox()
            return [bb.xlen, bb.ylen, bb.zlen]
        except (ValueError, AttributeError, RuntimeError):
            warnings.warn("compute_bbox_mm: geometry inspection failed")
            return None
        # Fatal errors (MemoryError, ImportError, etc.) propagate naturally

    def count_bodies(self, solid_obj: Any) -> int | None:
        """Count bodies. Returns None on geometry inspection failure."""
        try:
            return _count_solids(solid_obj)
        except (ValueError, AttributeError, RuntimeError):
            warnings.warn("count_bodies: geometry inspection failed")
            return None
        # Fatal errors propagate naturally


def _count_solids(solid_obj: Any) -> int:
    """Count solids in a CadQuery object (Workplane, Solid, Compound, Assembly).

    Returns the detected solid count. Raises on fatal errors.
    """
    import cadquery as cq
    if isinstance(solid_obj, cq.Assembly):
        return len(list(solid_obj))
    if hasattr(solid_obj, "Solids"):
        return len(solid_obj.Solids())
    if hasattr(solid_obj, "val"):
        wrapped = solid_obj.val()
        if hasattr(wrapped, "Solids"):
            return len(wrapped.Solids())
    return 1
