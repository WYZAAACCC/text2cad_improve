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
    direction: Literal["+", "-"] = "+"
    taper_deg: float = Field(default=0.0, ge=-45, le=45, description="Taper angle in degrees")


class CutProfileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    depth_mm: float = Field(gt=0, description="Cut depth in mm")
    direction: Literal["+", "-"] = "-"


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
