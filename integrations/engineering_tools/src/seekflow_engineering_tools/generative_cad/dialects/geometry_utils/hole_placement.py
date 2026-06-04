"""Hole placement resolver — semantic face+UV → 3D point+direction.

Converts HolePlacementV2 (face name, UV coordinates, origin mode) into
ResolvedHolePlacement (3D center, direction, workplane) using actual
component bounding box measurements.

Reference: llm_skill_base21.md §3.4, AUDIT P1-1 (cylindrical face limitation noted)
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from seekflow_engineering_tools.generative_cad.ir.geometry_semantics import (
    CanonicalFace,
    Axis3,
    OriginMode,
    HolePlacementV2,
    CircularPatternPlacementV2,
)


@dataclass(frozen=True)
class ResolvedHolePlacement:
    """Fully resolved 3D hole placement.

    Attributes:
        center_xyz: 3D world coordinate of the hole center on the entry face.
        direction_xyz: Unit vector pointing INTO the part (drilling direction).
        plane: CadQuery workplane name for the entry face.
        u_axis: Unit vector in the face's U (horizontal) direction.
        v_axis: Unit vector in the face's V (vertical) direction.
    """
    center_xyz: tuple[float, float, float]
    direction_xyz: tuple[float, float, float]
    plane: str
    u_axis: tuple[float, float, float]
    v_axis: tuple[float, float, float]


def _unit(v: tuple[float, float, float]) -> tuple[float, float, float]:
    """Normalize a 3D vector to unit length."""
    x, y, z = v
    n = math.sqrt(x * x + y * y + z * z)
    if n <= 1e-12:
        raise ValueError(f"zero vector cannot be normalized: {v}")
    return (x / n, y / n, z / n)


def resolve_face_hole_placement(
    placement: HolePlacementV2,
    bbox,  # CadQuery BoundingBox or any object with xmin/xmax/ymin/ymax/zmin/zmax
) -> ResolvedHolePlacement:
    """Resolve a HolePlacementV2 to 3D coordinates using the component's bbox.

    Only origin_mode=FACE_CENTER is implemented in v1.
    DATUM, PART_CENTER, and LOWER_LEFT will raise NotImplementedError.

    The bbox parameter must have attributes: xmin, xmax, ymin, ymax, zmin, zmax.
    CadQuery BoundingBox satisfies this interface.
    """
    u, v = placement.center_uv_mm
    face = placement.target_face
    origin = placement.origin_mode

    if origin != OriginMode.FACE_CENTER:
        raise NotImplementedError(
            f"origin_mode={origin} is not implemented in v1. "
            f"Only FACE_CENTER is supported. DATUM requires a datum registry."
        )

    # Compute face center and normal for each canonical face
    if face == CanonicalFace.TOP:
        face_center = (
            (bbox.xmin + bbox.xmax) / 2.0,
            (bbox.ymin + bbox.ymax) / 2.0,
            bbox.zmax,
        )
        direction = (0.0, 0.0, -1.0)  # into part
        plane = "XY"
        u_axis = (1.0, 0.0, 0.0)
        v_axis = (0.0, 1.0, 0.0)

    elif face == CanonicalFace.BOTTOM:
        face_center = (
            (bbox.xmin + bbox.xmax) / 2.0,
            (bbox.ymin + bbox.ymax) / 2.0,
            bbox.zmin,
        )
        direction = (0.0, 0.0, 1.0)  # into part
        plane = "XY"
        u_axis = (1.0, 0.0, 0.0)
        v_axis = (0.0, 1.0, 0.0)

    elif face == CanonicalFace.FRONT:
        face_center = (
            (bbox.xmin + bbox.xmax) / 2.0,
            bbox.ymin,
            (bbox.zmin + bbox.zmax) / 2.0,
        )
        direction = (0.0, 1.0, 0.0)  # +Y into part
        plane = "XZ"
        u_axis = (1.0, 0.0, 0.0)
        v_axis = (0.0, 0.0, 1.0)

    elif face == CanonicalFace.BACK:
        face_center = (
            (bbox.xmin + bbox.xmax) / 2.0,
            bbox.ymax,
            (bbox.zmin + bbox.zmax) / 2.0,
        )
        direction = (0.0, -1.0, 0.0)  # -Y into part
        plane = "XZ"
        u_axis = (1.0, 0.0, 0.0)
        v_axis = (0.0, 0.0, 1.0)

    elif face == CanonicalFace.RIGHT:
        face_center = (
            bbox.xmax,
            (bbox.ymin + bbox.ymax) / 2.0,
            (bbox.zmin + bbox.zmax) / 2.0,
        )
        direction = (-1.0, 0.0, 0.0)  # -X into part
        plane = "YZ"
        u_axis = (0.0, 1.0, 0.0)
        v_axis = (0.0, 0.0, 1.0)

    elif face == CanonicalFace.LEFT:
        face_center = (
            bbox.xmin,
            (bbox.ymin + bbox.ymax) / 2.0,
            (bbox.zmin + bbox.zmax) / 2.0,
        )
        direction = (1.0, 0.0, 0.0)  # +X into part
        plane = "YZ"
        u_axis = (0.0, 1.0, 0.0)
        v_axis = (0.0, 0.0, 1.0)

    elif face == CanonicalFace.CYLINDRICAL:
        # Cylindrical face: u = angle_deg, v = z_offset_mm
        # Face center is at (cx + R, cy, cz_mid) — the point on the
        # cylindrical surface at angle=0, at the bbox mid-height.
        # The radial direction (into part) is computed from the angle.
        cx = (bbox.xmin + bbox.xmax) / 2.0
        cy = (bbox.ymin + bbox.ymax) / 2.0
        cz_mid = (bbox.zmin + bbox.zmax) / 2.0
        # Estimate cylinder radius from bbox XY extent
        R = max(bbox.xlen, bbox.ylen) / 2.0
        # u = angle_deg measured from +X axis on XY plane
        angle_rad = math.radians(u)
        # Point on cylindrical surface at angle_rad, mid-height + v offset
        face_center = (
            cx + R * math.cos(angle_rad),
            cy + R * math.sin(angle_rad),
            cz_mid + v,
        )
        # Direction is radially inward
        direction = (-math.cos(angle_rad), -math.sin(angle_rad), 0.0)
        plane = "XY"  # workplane for profile; drilling is radial
        # U: tangential (perpendicular to radius in XY plane)
        u_axis = (-math.sin(angle_rad), math.cos(angle_rad), 0.0)
        v_axis = (0.0, 0.0, 1.0)

        return ResolvedHolePlacement(
            center_xyz=face_center,
            direction_xyz=_unit(direction),
            plane=plane,
            u_axis=u_axis,
            v_axis=v_axis,
        )

    elif face == CanonicalFace.CUSTOM:
        raise ValueError(
            "CanonicalFace.CUSTOM requires explicit datum plane. "
            "Use drill_hole_3d with explicit origin_mm + direction for arbitrary faces."
        )
    else:
        raise ValueError(f"Unknown face: {face}")

    # Compute hole center from face center + UV offset
    cx = face_center[0] + u * u_axis[0] + v * v_axis[0]
    cy = face_center[1] + u * u_axis[1] + v * v_axis[1]
    cz = face_center[2] + u * u_axis[2] + v * v_axis[2]

    return ResolvedHolePlacement(
        center_xyz=(cx, cy, cz),
        direction_xyz=_unit(direction),
        plane=plane,
        u_axis=u_axis,
        v_axis=v_axis,
    )


def iter_linear_pattern_centers(
    base_center_uv: tuple[float, float],
    count_u: int,
    count_v: int,
    spacing_u: float,
    spacing_v: float,
):
    """Generate (u, v) offsets for a centered linear grid pattern.

    The grid is centered around base_center_uv, expanding in both positive
    and negative U/V directions. This matches how most CAD tools lay out
    linear patterns (center-reference, not corner-reference).
    """
    cu, cv = base_center_uv
    for iu in range(count_u):
        for iv in range(count_v):
            u = cu + (iu - (count_u - 1) / 2.0) * spacing_u
            v = cv + (iv - (count_v - 1) / 2.0) * spacing_v
            yield u, v
