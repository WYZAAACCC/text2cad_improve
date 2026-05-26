from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

LengthUnit = Literal["mm", "m", "inch"]
BackendName = Literal["solidworks2025", "nx12", "cadquery"]
PlaneName = Literal["XY", "YZ", "XZ", "front", "top", "right"]


class OutputSpec(BaseModel):
    native: bool = True
    step: bool = True
    stl: bool = False
    preview_png: bool = False


class ValidationSpec(BaseModel):
    expected_bbox_mm: list[float] | None = None
    expected_body_count: int | None = None
    expected_hole_count: int | None = None
    expected_through_hole_count: int | None = None
    expected_feature_count_min: int | None = None
    tolerance_mm: float = 0.1


class CircleProfile(BaseModel):
    type: Literal["circle"] = "circle"
    diameter_mm: float


class RectangleProfile(BaseModel):
    type: Literal["rectangle"] = "rectangle"
    width_mm: float
    height_mm: float
    centered: bool = True


class PolygonProfile(BaseModel):
    type: Literal["polygon"] = "polygon"
    points_mm: list[list[float]]


Profile = CircleProfile | RectangleProfile | PolygonProfile


class SketchSpec(BaseModel):
    plane: PlaneName
    origin_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    profile: Profile


class ExtrudeFeature(BaseModel):
    id: str
    type: Literal["extrude"] = "extrude"
    sketch: SketchSpec
    depth_mm: float
    operation: Literal["add", "cut"] = "add"
    direction: Literal["+", "-"] = "+"


class HoleFeature(BaseModel):
    id: str
    type: Literal["hole"] = "hole"
    diameter_mm: float
    position_mm: list[float]
    axis: Literal["X", "Y", "Z"] = "Z"
    through_all: bool = True
    depth_mm: float | None = None


class CircularPatternHolesFeature(BaseModel):
    id: str
    type: Literal["circular_pattern_holes"] = "circular_pattern_holes"
    count: int
    hole_diameter_mm: float
    pitch_circle_diameter_mm: float
    axis: Literal["X", "Y", "Z"] = "Z"
    center_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    through_all: bool = True


class FilletFeature(BaseModel):
    id: str
    type: Literal["fillet"] = "fillet"
    radius_mm: float
    target: Literal["all_external_edges", "named_edges", "manual"] = "all_external_edges"
    edge_ids: list[str] = Field(default_factory=list)


class ChamferFeature(BaseModel):
    id: str
    type: Literal["chamfer"] = "chamfer"
    distance_mm: float
    target: Literal["all_external_edges", "named_edges", "manual"] = "all_external_edges"
    edge_ids: list[str] = Field(default_factory=list)


class RecipeFeature(BaseModel):
    id: str
    type: Literal["recipe"] = "recipe"
    recipe_name: str
    parameters: dict[str, Any]


CADFeature = (
    ExtrudeFeature
    | HoleFeature
    | CircularPatternHolesFeature
    | FilletFeature
    | ChamferFeature
    | RecipeFeature
)


class CADPartSpec(BaseModel):
    nlcad_version: str = "0.1"
    name: str
    units: LengthUnit = "mm"
    target_backend: list[BackendName] = Field(default_factory=lambda: ["cadquery"])
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    features: list[CADFeature]
    validation: ValidationSpec = Field(default_factory=ValidationSpec)
    outputs: OutputSpec = Field(default_factory=OutputSpec)

    @model_validator(mode="after")
    def validate_basic(self):
        if self.units != "mm":
            raise ValueError("v1 CAD-IR only accepts mm at the IR boundary")
        ids_ = [f.id for f in self.features]
        if len(ids_) != len(set(ids_)):
            raise ValueError("feature ids must be unique")
        return self
