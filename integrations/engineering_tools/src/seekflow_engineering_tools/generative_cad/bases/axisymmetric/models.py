"""Pydantic params models for axisymmetric_base operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfileStation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    r_mm: float = Field(gt=0)
    z_front_mm: float
    z_rear_mm: float
    label: str | None = None

    @model_validator(mode="after")
    def validate_z(self):
        if self.z_front_mm > self.z_rear_mm:
            raise ValueError("z_front_mm must be <= z_rear_mm")
        return self


class RevolveProfileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axis: Literal["Z"] = "Z"
    profile_stations: list[ProfileStation] = Field(min_length=2)


class CutCenterBoreParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diameter_mm: float = Field(gt=0)
    axis: Literal["Z"] = "Z"
    through_all: bool = True


class CutAnnularGrooveParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: Literal["front", "rear"]
    inner_dia_mm: float = Field(gt=0)
    outer_dia_mm: float = Field(gt=0)
    depth_mm: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_dia(self):
        if self.inner_dia_mm >= self.outer_dia_mm:
            raise ValueError("inner_dia_mm must be < outer_dia_mm")
        return self


class CutCircularHolePatternParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=2, le=240)
    pcd_mm: float = Field(gt=0)
    hole_dia_mm: float = Field(gt=0)
    axis: Literal["Z"] = "Z"
    through_all: bool = True


class SlotProfileStation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depth_mm: float = Field(ge=0)
    half_width_mm: float = Field(gt=0)


class RimSlotProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["symmetric_station_profile"] = "symmetric_station_profile"
    stations: list[SlotProfileStation] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_depth_order(self):
        depths = [s.depth_mm for s in self.stations]
        if depths != sorted(depths):
            raise ValueError("slot profile station depths must be nondecreasing")
        return self


class CutRimSlotPatternParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=2, le=360)
    slot_depth_mm: float = Field(gt=0)
    slot_profile: RimSlotProfile


class ApplySafeChamferParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distance_mm: float = Field(gt=0)
    target: Literal["all_external_edges"] = "all_external_edges"
