"""OCP arbitrary-direction cylinder cutter.

Creates a cylinder solid along any 3D direction for use as a boolean
cut tool in drill_hole_3d and cut_hole_v2 operations.

Uses OCP BRepPrimAPI_MakeCylinder with gp_Ax2 for arbitrary axis placement.

Reference: llm_skill_base21.md §3.5
"""

from __future__ import annotations

import math


def make_cylinder_cutter(
    center_xyz: tuple[float, float, float],
    direction_xyz: tuple[float, float, float],
    radius_mm: float,
    length_mm: float,
    *,
    extend_both: bool = True,
):
    """Create a cylinder solid for boolean hole cutting.

    Args:
        center_xyz: Reference point on the entry face.
        direction_xyz: Axis direction INTO the part (will be normalized).
        radius_mm: Cylinder radius. Must be > 0.
        length_mm: Total cylinder length. Must be > 0.
        extend_both: If True (default), cylinder is centered at center_xyz
            (extends length/2 in both directions — for through-all holes).
            If False, cylinder starts at center_xyz and extends length_mm
            in the direction_xyz direction (for blind holes).

    Returns:
        cadquery.Workplane wrapping the cylinder solid.

    Raises:
        ValueError: If radius_mm or length_mm is non-positive,
                    or direction is a zero vector.
    """
    import cadquery as cq
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    if radius_mm <= 0:
        raise ValueError(f"radius_mm must be positive, got {radius_mm}")
    if length_mm <= 0:
        raise ValueError(f"length_mm must be positive, got {length_mm}")

    dx, dy, dz = direction_xyz
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    if n <= 1e-12:
        raise ValueError("direction vector cannot be zero")

    dx, dy, dz = dx / n, dy / n, dz / n

    if extend_both:
        # Through-all mode: centered at entry point, extends both ways
        half = length_mm / 2.0
        sx = center_xyz[0] - dx * half
        sy = center_xyz[1] - dy * half
        sz = center_xyz[2] - dz * half
    else:
        # Blind hole mode: starts at entry point, extends INTO the part
        sx, sy, sz = center_xyz

    ax = gp_Ax2(gp_Pnt(sx, sy, sz), gp_Dir(dx, dy, dz))
    shape = BRepPrimAPI_MakeCylinder(ax, radius_mm, length_mm).Shape()
    return cq.Workplane(obj=shape)
