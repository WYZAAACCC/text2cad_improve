"""Geometry semantic models — canonical face, axis, hole placement V2.

Pure Pydantic data models for semantic geometry representation.
Execution/resolution logic lives in dialects/geometry_utils/hole_placement.py.

Design principle: LLM emits semantic descriptions (face, axis, datum);
the system resolves them deterministically using actual bbox measurements.

Reference: llm_skill_base21.md §3.1, AUDIT P0-1 (fixed OperationSpec params)
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ═══════════════════════════════════════════════════════════════════════════════
# Axis and face enums
# ═══════════════════════════════════════════════════════════════════════════════


class Axis3(str, Enum):
    """Signed 3D axis with direction."""
    POS_X = "+X"
    NEG_X = "-X"
    POS_Y = "+Y"
    NEG_Y = "-Y"
    POS_Z = "+Z"
    NEG_Z = "-Z"


class CanonicalFace(str, Enum):
    """Named faces of a component's bounding box.

    For cuboid parts these map to the 6 box faces.
    For axisymmetric parts:
    - TOP/BOTTOM are the circular end faces
    - CYLINDRICAL represents the lateral surface, parameterized by angle
      (center_uv_mm is interpreted as (angle_deg, z_offset_mm) from the
      bbox center at the lateral surface)
    """
    TOP = "top"
    BOTTOM = "bottom"
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    CYLINDRICAL = "cylindrical"
    CUSTOM = "custom"


class OriginMode(str, Enum):
    """How to interpret center_uv_mm relative to the target face."""
    FACE_CENTER = "face_center"
    PART_CENTER = "part_center"
    LOWER_LEFT = "lower_left"
    DATUM = "datum"


class ThroughMode(str, Enum):
    """How a hole terminates."""
    THROUGH_ALL = "through_all"
    BLIND = "blind"
    TO_NEXT = "to_next"
    UP_TO_FACE = "up_to_face"


# ═══════════════════════════════════════════════════════════════════════════════
# Feature scope — controls which operations a feature applies to
# ═══════════════════════════════════════════════════════════════════════════════


class FeatureScope(BaseModel):
    """Scope control for a feature operation.

    Allows the LLM to express constraints like:
    - "this hole should not cut through ribs added later"
    - "this fillet only applies to external edges from stage X"

    In v1 (current), FeatureScope is recorded but not enforced by the runtime.
    Future versions will use it for operation ordering and exclusion.
    """
    model_config = ConfigDict(extra="forbid")

    target_component: str | None = Field(
        default=None,
        description="Component this feature targets. None = current component."
    )
    target_stage: str | None = Field(
        default=None,
        description="Feature stage this operation belongs to."
    )
    include_features: list[str] = Field(
        default_factory=list,
        description="Feature IDs to include in scope."
    )
    exclude_features: list[str] = Field(
        default_factory=list,
        description="Feature IDs to exclude from scope."
    )
    required: bool = Field(
        default=True,
        description="Whether this feature is required for functional correctness."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Hole placement V2
# ═══════════════════════════════════════════════════════════════════════════════


class HolePlacementV2(BaseModel):
    """Semantic hole placement — face-relative, deterministic.

    Replaces legacy axis + position_mm which had these problems:
    - 2D position on side faces was ambiguous (no Z coordinate)
    - axis=X/Y didn't specify which face (front vs back, left vs right)
    - origin was always implicit (bbox center or (0,0) depending on axis)

    Example (top face hole at center):
        HolePlacementV2(
            target_face="top",
            center_uv_mm=(0, 0),
            normal_axis="+Z",
            origin_mode="face_center",
            through_mode="through_all",
        )

    Example (front face blind hole, 50mm right, 20mm up from face center):
        HolePlacementV2(
            target_face="front",
            center_uv_mm=(50, 20),
            normal_axis="+Y",
            origin_mode="face_center",
            through_mode="blind",
            depth_mm=30,
        )
    """
    model_config = ConfigDict(extra="forbid")

    target_face: CanonicalFace = Field(
        description="Which face of the component to drill into."
    )
    center_uv_mm: tuple[float, float] = Field(
        description="(U, V) coordinates on the target face, relative to origin_mode."
    )
    normal_axis: Axis3 = Field(
        description="Direction from entry face INTO the part (e.g., +Y for front face)."
    )
    origin_mode: OriginMode = Field(
        default=OriginMode.FACE_CENTER,
        description="How center_uv_mm is interpreted. Currently only FACE_CENTER is implemented."
    )

    through_mode: ThroughMode = Field(
        default=ThroughMode.THROUGH_ALL,
        description="How the hole terminates."
    )
    depth_mm: float | None = Field(
        default=None, gt=0,
        description="Required for blind holes. Depth from entry face into part."
    )

    start_offset_mm: float = Field(
        default=0.0, ge=0,
        description="Offset above the face before drilling starts (for counterbore lead-in)."
    )
    scope: FeatureScope = Field(
        default_factory=FeatureScope,
        description="Feature scope for ordering and exclusion."
    )

    @model_validator(mode="after")
    def check_depth_for_blind(self):
        if self.through_mode == ThroughMode.BLIND and self.depth_mm is None:
            raise ValueError(
                f"through_mode='blind' requires depth_mm to be set. "
                f"Use through_mode='through_all' if you want a through hole."
            )
        return self


# ═══════════════════════════════════════════════════════════════════════════════
# Circular pattern placement V2
# ═══════════════════════════════════════════════════════════════════════════════


class CircularPatternPlacementV2(BaseModel):
    """Semantic circular hole pattern placement.

    Example (6-hole bolt circle on top face, 100mm PCD, starting at 0°):
        CircularPatternPlacementV2(
            target_face="top",
            center_uv_mm=(0, 0),
            normal_axis="+Z",
            pcd_mm=100.0,
            count=6,
            start_angle_deg=0,
        )
    """
    model_config = ConfigDict(extra="forbid")

    target_face: CanonicalFace = Field(
        description="Face the bolt circle is on."
    )
    center_uv_mm: tuple[float, float] = Field(
        default=(0.0, 0.0),
        description="Center of the bolt circle on the target face."
    )
    normal_axis: Axis3 = Field(
        description="Direction INTO the part from the target face."
    )
    pcd_mm: float = Field(gt=0, description="Pitch circle diameter.")
    count: int = Field(ge=1, le=512, description="Number of holes.")
    start_angle_deg: float = Field(
        default=0.0,
        description="Angle of first hole from datum_axis (0 = U-axis direction)."
    )
    angular_span_deg: float = Field(
        default=360.0, ge=0, le=360,
        description="Angular span of the pattern. 360 = full circle."
    )
    datum_axis: Literal["U", "V"] = Field(
        default="U",
        description="Reference axis for start_angle_deg on the face UV plane."
    )
    origin_mode: OriginMode = Field(default=OriginMode.FACE_CENTER)


# ═══════════════════════════════════════════════════════════════════════════════
# V2 Params models for sketch_extrude ops
# ═══════════════════════════════════════════════════════════════════════════════


class CutHoleV2Params(BaseModel):
    """V2 hole params — face-relative, semantic placement.

    LEGACY NOTE: Old CutHoleParams with axis + position_mm is deprecated.
    New code and LLM prompts should use cut_hole_v2 exclusively.
    """
    model_config = ConfigDict(extra="forbid")

    diameter_mm: float = Field(gt=0, description="Hole diameter.")
    placement: HolePlacementV2


class DrillHole3DParams(BaseModel):
    """3D drill hole — arbitrary direction, not face-relative.

    Use for holes that cannot be expressed as face-normal:
    - Angled holes on curved surfaces
    - Oil passages in engine blocks
    - Intersecting cooling channels
    """
    model_config = ConfigDict(extra="forbid")

    diameter_mm: float = Field(gt=0, description="Hole diameter.")
    origin_mm: tuple[float, float, float] = Field(
        description="3D origin point of the hole."
    )
    direction: tuple[float, float, float] = Field(
        description="Normalized direction vector of the hole axis."
    )
    through_mode: ThroughMode = Field(default=ThroughMode.THROUGH_ALL)
    depth_mm: float | None = Field(default=None, gt=0)
    counterbore_dia_mm: float | None = Field(default=None, gt=0)
    counterbore_depth_mm: float | None = Field(default=None, gt=0)
    countersink_angle_deg: float | None = Field(default=None, gt=0, le=179)
    scope: FeatureScope = Field(default_factory=FeatureScope)

    @model_validator(mode="after")
    def validate_direction_and_depth(self):
        x, y, z = self.direction
        if abs(x) + abs(y) + abs(z) < 1e-9:
            raise ValueError("direction vector cannot be zero")
        if self.through_mode == ThroughMode.BLIND and self.depth_mm is None:
            raise ValueError("blind drill_hole_3d requires depth_mm")
        return self


class CutHolePatternLinearV2Params(BaseModel):
    """V2 linear hole pattern — face-relative grid.

    Replaces legacy CutHolePatternLinearParams which was Z-axis only.
    The grid is laid out on the target face's UV plane.
    """
    model_config = ConfigDict(extra="forbid")

    hole_dia_mm: float = Field(gt=0)
    count_u: int = Field(ge=1, le=512)
    count_v: int = Field(ge=1, le=512)
    spacing_u_mm: float = Field(gt=0)
    spacing_v_mm: float = Field(gt=0)
    placement: HolePlacementV2


class CutCircularHolePatternV2Params(BaseModel):
    """V2 circular hole pattern — face-relative bolt circle.

    Replaces legacy cut_circular_hole_pattern in axisymmetric dialect.
    The bolt circle is laid out on the target face.
    """
    model_config = ConfigDict(extra="forbid")

    hole_dia_mm: float = Field(gt=0)
    placement: CircularPatternPlacementV2
    through_mode: ThroughMode = Field(default=ThroughMode.THROUGH_ALL)
    depth_mm: float | None = Field(default=None, gt=0)
    scope: FeatureScope = Field(default_factory=FeatureScope)
