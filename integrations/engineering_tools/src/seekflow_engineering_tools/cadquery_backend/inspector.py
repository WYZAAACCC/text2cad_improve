"""Inspect CadQuery shapes and STEP files for validation."""

from __future__ import annotations

from pathlib import Path


def inspect_cadquery_shape(shape) -> dict:
    """Extract bbox, volume, and solid count from a CadQuery shape."""
    try:
        bb = shape.val().BoundingBox()
        return {
            "bbox_mm": [bb.xlen, bb.ylen, bb.zlen],
            "volume_mm3": shape.val().Volume(),
            "solid_count": len(shape.solids().vals()),
        }
    except Exception:
        return {
            "bbox_mm": None,
            "volume_mm3": None,
            "solid_count": None,
        }


def inspect_step_with_cadquery(step_path: Path) -> dict:
    """Import a STEP file with CadQuery and return inspection metrics."""
    try:
        import cadquery as cq

        obj = cq.importers.importStep(str(step_path))
        return inspect_cadquery_shape(obj)
    except ImportError:
        return {
            "bbox_mm": None,
            "volume_mm3": None,
            "solid_count": None,
            "error": "cadquery not installed",
        }
    except Exception as exc:
        return {
            "bbox_mm": None,
            "volume_mm3": None,
            "solid_count": None,
            "error": str(exc),
        }
