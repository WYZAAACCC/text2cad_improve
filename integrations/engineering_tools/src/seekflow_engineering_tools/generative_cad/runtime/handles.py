"""Runtime typed handles — cross-dialect data exchange via typed handles only."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RuntimeHandle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    component_id: str | None = None
    producer_node: str | None = None


class SolidHandle(RuntimeHandle):
    type: Literal["solid"] = "solid"
    bbox_mm: tuple[float, float, float] | None = None
    volume_mm3: float | None = None


class SolidArrayHandle(RuntimeHandle):
    type: Literal["solid_array"] = "solid_array"
    solid_ids: list[str] = Field(default_factory=list)


class FrameHandle(RuntimeHandle):
    type: Literal["frame"] = "frame"
    origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    x_axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    y_axis: tuple[float, float, float] = (0.0, 1.0, 0.0)
    z_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)


class PlaneHandle(RuntimeHandle):
    type: Literal["plane"] = "plane"
    origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    normal: tuple[float, float, float] = (0.0, 0.0, 1.0)


class PointHandle(RuntimeHandle):
    type: Literal["point"] = "point"
    xyz_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)


class CurveHandle(RuntimeHandle):
    type: Literal["curve"] = "curve"


class ProfileHandle(RuntimeHandle):
    type: Literal["profile"] = "profile"


class EdgeHandle(RuntimeHandle):
    """Handle for a specific edge on a solid body."""
    type: Literal["edge"] = "edge"
    parent_solid_id: str | None = None
    edge_index: int = 0


class FaceHandle(RuntimeHandle):
    """Handle for a specific face on a solid body."""
    type: Literal["face"] = "face"
    parent_solid_id: str | None = None
    face_index: int = 0


RuntimeValue = (
    SolidHandle
    | SolidArrayHandle
    | FrameHandle
    | PlaneHandle
    | PointHandle
    | CurveHandle
    | ProfileHandle
    | EdgeHandle
    | FaceHandle
)
