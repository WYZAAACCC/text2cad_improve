"""Pydantic params models for sketch_extrude_base operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtrudeRectangleParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    depth_mm: float = Field(gt=0)
    plane: Literal["XY", "YZ", "XZ"] = "XY"
    centered: bool = True
    direction: Literal["+", "-"] = "+"


class CutRectangularPocketParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    depth_mm: float = Field(gt=0)
    plane: Literal["XY", "YZ", "XZ"] = "XY"
    centered: bool = True
    direction: Literal["+", "-"] = "+"


class CutHoleParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diameter_mm: float = Field(gt=0)
    position_mm: list[float]
    axis: Literal["X", "Y", "Z"] = "Z"
    through_all: bool = True
    depth_mm: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_position(self):
        if len(self.position_mm) not in (2, 3):
            raise ValueError("position_mm must be length 2 or 3")
        return self


class CutHolePatternLinearParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hole_dia_mm: float = Field(gt=0)
    count_x: int = Field(ge=1, le=20)
    count_y: int = Field(ge=1, le=20)
    spacing_x_mm: float = Field(gt=0)
    spacing_y_mm: float = Field(gt=0)
    axis: Literal["X", "Y", "Z"] = "Z"
    through_all: bool = True


class AddRectangularBossParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    depth_mm: float = Field(gt=0)
    position_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    plane: Literal["XY", "YZ", "XZ"] = "XY"
    centered: bool = True

    @model_validator(mode="after")
    def validate_position(self):
        if len(self.position_mm) not in (2, 3):
            raise ValueError("position_mm must be length 2 or 3")
        return self


class AddRibParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thickness_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    length_mm: float = Field(gt=0)
    position_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    direction: Literal["X", "Y"] = "X"

    @model_validator(mode="after")
    def validate_position(self):
        if len(self.position_mm) not in (2, 3):
            raise ValueError("position_mm must be length 2 or 3")
        return self


class ApplySafeFilletParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    radius_mm: float = Field(gt=0)
    target: Literal["all_external_edges"] = "all_external_edges"


class ApplySafeChamferParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distance_mm: float = Field(gt=0)
    target: Literal["all_external_edges"] = "all_external_edges"
