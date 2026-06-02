"""ShellHousing params models."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ShellBodyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thickness_mm: float = Field(gt=0, description="Wall thickness after shelling")
    open_faces: list[str] = Field(default_factory=list, description="Face names to leave open")


class ThickenSurfaceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thickness_mm: float = Field(gt=0)
    direction: Literal["inward", "outward", "both"] = "outward"


class HollowBodyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wall_thickness_mm: float = Field(gt=0)
    bottom_thickness_mm: float | None = None
