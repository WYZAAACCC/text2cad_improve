"""SketchProfile params models — Pydantic validation for sketch operations."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Create2dSketchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plane: Literal["XY", "YZ", "XZ"] = "XY"
    origin_x_mm: float = Field(default=0.0, description="Sketch origin X offset in mm")
    origin_y_mm: float = Field(default=0.0, description="Sketch origin Y offset in mm")


class Point2D(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_mm: float = Field(description="X coordinate in mm")
    y_mm: float = Field(description="Y coordinate in mm")


class AddLineSegmentParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: Point2D
    end: Point2D


class AddArcSegmentParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: Point2D
    end: Point2D
    center: Point2D
    direction: Literal["cw", "ccw"] = "ccw"


class AddCircleParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    center: Point2D
    radius_mm: float = Field(gt=0)


class AddPolylineParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    points: list[Point2D] = Field(min_length=2, description="Ordered list of polyline vertices")


class CloseProfileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """No additional params — profile is closed from last point back to first."""


class ExtrudeProfileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    depth_mm: float = Field(gt=0, description="Extrusion depth in mm")
    direction: Literal["+", "-", "both"] = "+"
    taper_deg: float = Field(default=0.0, ge=-45, le=45, description="Taper angle in degrees")


class CutProfileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    depth_mm: float = Field(gt=0, description="Cut depth in mm")
    direction: Literal["+", "-", "both"] = "-"


class AddSlotParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    center: Point2D
    length_mm: float = Field(gt=0)
    width_mm: float = Field(gt=0)
    angle_deg: float = Field(default=0.0, description="Rotation angle in degrees")


class LinearPatternParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(ge=1, le=20)
    spacing_x_mm: float = Field(gt=0)
    spacing_y_mm: float = Field(default=0.0, ge=0)


class MirrorFeatureParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    axis: Literal["X", "Y"] = "X"
    offset_mm: float = Field(default=0.0)


class RevolveProfileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    axis: Literal["Z"] = "Z"
    angle_deg: float = Field(default=360.0, gt=0, le=360, description="Revolve angle in degrees")


class FilletSketchParams(BaseModel):
    """fillet_sketch@1.0.0 — DEPRECATED. Use FilletSketchV2Params instead.

    Vertex-index-based filleting is unreliable because OCC wire topology
    reordering can change which vertex sits at each index.
    """
    model_config = ConfigDict(extra="forbid")
    radius_mm: float = Field(gt=0, description="Fillet radius in mm")
    at_vertex_index: list[int] | None = Field(
        default=None,
        description="DEPRECATED: use FilletSketchV2Params with between_segments instead. "
        "Vertex indices are NOT stable across OCC topology changes.",
    )


class SketchFilletTarget(BaseModel):
    """Semantic fillet target — identified by adjacent edge IDs, not vertex index."""
    model_config = ConfigDict(extra="forbid")
    corner_id: str = Field(description="Stable corner identifier, e.g. 'right_upper_tooth_tip'")
    between_segments: tuple[str, str] = Field(
        description="Pair of adjacent edge IDs that meet at this corner"
    )
    radius_mm: float = Field(gt=0)
    expected_convexity: Literal["convex", "concave", "either"] = "either"
    engineering_role: str | None = None
    required: bool = True


class FilletSketchV2Params(BaseModel):
    """fillet_sketch@2.0.0 — semantic corner filleting via edge adjacency.

    Uses stable segment IDs (from ProfileGraph) instead of fragile vertex indices.
    Each target specifies its own radius, convexity expectation, and required flag.
    """
    model_config = ConfigDict(extra="forbid")
    wire_id: str = Field(
        default="profile",
        description="Target wire ID from the profile graph"
    )
    targets: list[SketchFilletTarget] = Field(
        min_length=1,
        description="Ordered list of corners to fillet, each with independent radius",
    )
    strict: bool = Field(
        default=True,
        description="If True, all targets must be feasible (fail-closed)"
    )
    tolerance_mm: float = Field(default=1e-5, gt=0)
