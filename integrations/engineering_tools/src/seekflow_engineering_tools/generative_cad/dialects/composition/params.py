"""Composition dialect params models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TranslateSolidParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vector_mm: tuple[float, float, float]


class RotateSolidParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    axis_origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    axis_dir: tuple[float, float, float]
    angle_deg: float


class CircularPatternComponentParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(ge=1, le=360)
    radius_mm: float = Field(ge=0)
    axis: Literal["Z"] = "Z"
    start_angle_deg: float = 0.0
    rotate_copies: bool = Field(default=True, description="Whether each copy rotates to face radially outward")


class LinearPatternComponentParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(ge=1, le=100)
    spacing_mm: float = Field(gt=0)
    direction: Literal["X", "Y", "Z"] = "X"


class BooleanUnionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clean_after: bool = True


class BooleanCutParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clean_after: bool = True


class PlaceComponentParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    component_id: str | None = Field(
        default=None,
        description="Target component ID for spatial placement lookup. "
                    "When set and ctx.spatial_placements exists, the solver-computed "
                    "placement overrides position_mm."
    )
