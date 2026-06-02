"""Geometry measurement API — queryable mass properties and distances."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class MassProperties:
    volume_mm3: float
    center_of_mass_mm: tuple[float, float, float]
    bounding_box_mm: tuple[float, float, float, float, float, float]  # xmin,ymin,zmin,xmax,ymax,zmax


def measure_volume(solid: Any) -> float:
    """Return volume in mm^3, or 0 on failure."""
    try:
        s = solid.val() if hasattr(solid, 'val') else solid
        return s.Volume()
    except Exception:
        return 0.0


def measure_bbox(solid: Any) -> tuple[float, float, float, float, float, float] | None:
    """Return (xmin, ymin, zmin, xmax, ymax, zmax) in mm, or None."""
    try:
        s = solid.val() if hasattr(solid, 'val') else solid
        bb = s.BoundingBox()
        return (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)
    except Exception:
        return None


def measure_distance(solid: Any, face_a_selector: str, face_b_selector: str) -> float | None:
    """Minimum distance between two face groups, or None."""
    try:
        s = solid.val() if hasattr(solid, 'val') else solid
        fa = s.faces(face_a_selector)
        fb = s.faces(face_b_selector)
        min_dist = float('inf')
        for i in range(fa.size() if hasattr(fa, 'size') else 0):
            for j in range(fb.size() if hasattr(fb, 'size') else 0):
                try:
                    d = fa.item(i).distToShape(fb.item(j))
                    if d < min_dist:
                        min_dist = d
                except Exception:
                    continue
        return min_dist if min_dist != float('inf') else None
    except Exception:
        return None


def measure_wall_thickness(solid: Any, sample_count: int = 8) -> dict[str, float]:
    """Estimate minimum wall thickness by ray-casting from center. Returns {min, max, avg}."""
    try:
        s = solid.val() if hasattr(solid, 'val') else solid
        bb = s.BoundingBox()
        cx, cy, cz = (bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2
        thicknesses = []
        import math
        for i in range(sample_count):
            angle = 2 * math.pi * i / sample_count
            dx = math.cos(angle) * max(bb.xlen, bb.ylen)
            dy = math.sin(angle) * max(bb.xlen, bb.ylen)
            # Ray cast from center outward — crude but effective
            try:
                # Find intersection distance
                ray = s.intersect(
                    type(s).makeLine((cx, cy, cz), (cx + dx, cy + dy, cz))
                )
                thicknesses.append(ray.Length() if hasattr(ray, 'Length') else 0)
            except Exception:
                continue
        if not thicknesses:
            return {"min": 0, "max": 0, "avg": 0}
        return {
            "min": min(thicknesses),
            "max": max(thicknesses),
            "avg": sum(thicknesses) / len(thicknesses),
        }
    except Exception:
        return {"min": 0, "max": 0, "avg": 0}


def check_interference(a: Any, b: Any) -> dict:
    """Check if two solids interfere/intersect. Returns {interfering: bool, volume_mm3: float}."""
    try:
        sa = a.val() if hasattr(a, 'val') else a
        sb = b.val() if hasattr(b, 'val') else b
        common = sa.common(sb)
        vol = common.Volume() if hasattr(common, 'Volume') else 0
        return {"interfering": vol > 0.001, "intersection_volume_mm3": vol}
    except Exception:
        return {"interfering": False, "intersection_volume_mm3": 0, "error": "check failed"}
