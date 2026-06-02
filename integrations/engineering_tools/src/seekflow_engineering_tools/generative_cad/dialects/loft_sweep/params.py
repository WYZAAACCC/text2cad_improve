"""LoftSweep params models."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Point3D(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_mm: float = 0.0
    y_mm: float = 0.0
    z_mm: float = 0.0


class ProfileSection(BaseModel):
    """A 2D cross-section at a specific 3D position + orientation."""
    model_config = ConfigDict(extra="forbid")
    position: Point3D
    shape: Literal["circle", "rectangle", "ellipse"] = "circle"
    radius_mm: float = Field(default=10.0, gt=0)
    width_mm: float = Field(default=20.0, gt=0)
    height_mm: float = Field(default=20.0, gt=0)


class CreateSweepPathParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path_points: list[Point3D] = Field(min_length=2)


class SweepProfileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shape: Literal["circle", "rectangle"] = "circle"
    radius_mm: float = Field(default=5.0, gt=0)
    width_mm: float = Field(default=10.0, gt=0)
    height_mm: float = Field(default=10.0, gt=0)


class LoftSectionsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sections: list[ProfileSection] = Field(min_length=2)
    ruled: bool = False


class HelixSweepParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    radius_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    pitch_mm: float = Field(gt=0)
    profile_radius_mm: float = Field(default=2.0, gt=0)
    turns: float = Field(default=5.0, gt=0)
    variable_pitch: bool = False
    start_pitch_mm: float | None = None
    end_pitch_mm: float | None = None
