from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LengthUnit = Literal["mm", "m", "inch"]
BackendName = Literal["solidworks2025", "nx12", "cadquery"]
PlaneName = Literal["XY", "YZ", "XZ", "front", "top", "right"]


class OutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    native: bool = True
    step: bool = True
    stl: bool = False
    preview_png: bool = False


class ValidationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_bbox_mm: list[float] | None = None
    expected_body_count: int | None = None
    expected_hole_count: int | None = None
    expected_through_hole_count: int | None = None
    expected_feature_count_min: int | None = None
    tolerance_mm: float = Field(default=0.1, gt=0)

    @model_validator(mode="after")
    def validate_bbox(self):
        if self.expected_bbox_mm is not None and len(self.expected_bbox_mm) != 3:
            raise ValueError("expected_bbox_mm must be length 3 [x, y, z]")
        return self


class CircleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["circle"] = "circle"
    diameter_mm: float = Field(gt=0)


class RectangleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["rectangle"] = "rectangle"
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    centered: bool = True


class PolygonProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["polygon"] = "polygon"
    points_mm: list[list[float]]


Profile = CircleProfile | RectangleProfile | PolygonProfile


class SketchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plane: PlaneName
    origin_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    profile: Profile


class ExtrudeFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["extrude"] = "extrude"
    sketch: SketchSpec
    depth_mm: float = Field(gt=0)
    operation: Literal["add", "cut"] = "add"
    direction: Literal["+", "-"] = "+"


class HoleFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["hole"] = "hole"
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


class CircularPatternHolesFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["circular_pattern_holes"] = "circular_pattern_holes"
    count: int = Field(ge=2)
    hole_diameter_mm: float = Field(gt=0)
    pitch_circle_diameter_mm: float = Field(gt=0)
    axis: Literal["X", "Y", "Z"] = "Z"
    center_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    through_all: bool = True


class FilletFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["fillet"] = "fillet"
    radius_mm: float = Field(gt=0)
    target: Literal["all_external_edges", "named_edges", "manual"] = "all_external_edges"
    edge_ids: list[str] = Field(default_factory=list)


class ChamferFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["chamfer"] = "chamfer"
    distance_mm: float = Field(gt=0)
    target: Literal["all_external_edges", "named_edges", "manual"] = "all_external_edges"
    edge_ids: list[str] = Field(default_factory=list)


class RecipeFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["recipe"] = "recipe"
    recipe_name: str
    parameters: dict[str, Any]

    @model_validator(mode="after")
    def validate_params(self):
        from seekflow_engineering_tools.recipes.registry import get_recipe_definition, validate_recipe_parameters
        rd = get_recipe_definition(self.recipe_name)
        if rd is None:
            # Unknown recipe — let capability/backend layer handle it
            return self
        errors = validate_recipe_parameters(self.recipe_name, self.parameters)
        if errors:
            raise ValueError(f"Recipe '{self.recipe_name}' parameter validation failed: {'; '.join(errors)}")
        return self


CADFeature = (
    ExtrudeFeature
    | HoleFeature
    | CircularPatternHolesFeature
    | FilletFeature
    | ChamferFeature
    | RecipeFeature
)


class CADPartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
