"""Neutral structural-intent models for the isolated FEA experiment."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _unit_vector(value: list[float], *, label: str) -> list[float]:
    if len(value) != 3:
        raise ValueError(f"{label} must contain exactly three components")
    norm = math.sqrt(sum(float(v) ** 2 for v in value))
    if norm <= 1e-15:
        raise ValueError(f"{label} must be non-zero")
    return [float(v) / norm for v in value]


class RotationIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axis_origin_mm: list[float]
    axis_direction: list[float]
    rpm: float = Field(gt=0)
    source: str
    rationale: str = ""

    @model_validator(mode="after")
    def _validate_axis(self):
        self.axis_origin_mm = [float(v) for v in self.axis_origin_mm]
        if len(self.axis_origin_mm) != 3:
            raise ValueError("axis_origin_mm must contain exactly three components")
        self.axis_direction = _unit_vector(
            self.axis_direction, label="axis_direction"
        )
        return self

    @property
    def omega_rad_s(self) -> float:
        return self.rpm * 2.0 * math.pi / 60.0


class TemperatureIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Literal[
        "isothermal",
        "radial_power_law",
        "node_profile_file",
        "coordinate_samples",
        "analytic_expression",
    ]
    reference_temperature_c: float
    source: str
    uniform_c: float | None = None
    bore_c: float | None = None
    rim_c: float | None = None
    bore_radius_mm: float | None = Field(default=None, gt=0)
    outer_radius_mm: float | None = Field(default=None, gt=0)
    exponent: float | None = None
    node_profile_file: str | None = None
    # A scattered `x,y,z,value` cloud. This is the shape a CFD export arrives
    # in, and it is also the only source that can be asked for a value where it
    # has no data - hence the policy, which is required rather than defaulted
    # silently.
    sample_points_file: str | None = None
    outside_support_policy: Literal[
        "nearest_sample", "reference_temperature", "fail"
    ] | None = None
    # A formula the field is evaluated from, at each mesh node.
    expression: str | None = None
    parameters: dict[str, float] = Field(default_factory=dict)
    rationale: str = ""

    @model_validator(mode="after")
    def _validate_model(self):
        if self.model == "isothermal":
            if self.uniform_c is None:
                raise ValueError("isothermal temperature requires uniform_c")
        elif self.model == "radial_power_law":
            required = {
                "bore_c": self.bore_c,
                "rim_c": self.rim_c,
                "bore_radius_mm": self.bore_radius_mm,
                "outer_radius_mm": self.outer_radius_mm,
                "exponent": self.exponent,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(
                    "radial_power_law missing fields: " + ", ".join(missing)
                )
            if self.outer_radius_mm <= self.bore_radius_mm:
                raise ValueError("outer_radius_mm must exceed bore_radius_mm")
        elif self.model == "node_profile_file":
            if not self.node_profile_file:
                raise ValueError(
                    "node_profile_file temperature requires a file path"
                )
        elif self.model == "coordinate_samples":
            if not self.sample_points_file:
                raise ValueError(
                    "coordinate_samples temperature requires sample_points_file"
                )
            if self.outside_support_policy is None:
                raise ValueError(
                    "coordinate_samples requires outside_support_policy: a "
                    "sample cloud covers a volume, and where the mesh falls "
                    "outside it the field must say what it does rather than "
                    "extrapolate"
                )
        elif self.model == "analytic_expression":
            if not self.expression:
                raise ValueError(
                    "analytic_expression temperature requires expression"
                )
        return self


class MaterialPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature_c: float
    young_mpa: float = Field(gt=0)
    alpha_per_c: float = Field(gt=0)
    yield_mpa: float = Field(gt=0)


class MaterialIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    poisson_ratio: float = Field(gt=-1, lt=0.5)
    density_t_mm3: float = Field(gt=0)
    points: list[MaterialPoint] = Field(min_length=2)
    rationale: str = ""

    @model_validator(mode="after")
    def _validate_points(self):
        temperatures = [point.temperature_c for point in self.points]
        if any(
            temperatures[index] >= temperatures[index + 1]
            for index in range(len(temperatures) - 1)
        ):
            raise ValueError("material temperatures must be strictly increasing")
        return self


class BladeLoadIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Literal[
        "equivalent_total_force",
        "mass_centroid_rpm",
    ]
    total_force_n_per_slot: float | None = Field(default=None, gt=0)
    effective_mass_kg: float | None = Field(default=None, gt=0)
    center_of_mass_radius_mm: float | None = Field(default=None, gt=0)
    blades_per_slot: int = Field(default=1, ge=1)
    direction_rule: Literal[
        "radial_outward_from_rotation_axis",
        "flank_surface_normal",
    ]
    # How the load reaches the material. `area_weighted_equal_nodes` splits a
    # face's share equally among the nodes of that face and applies it as
    # nodal forces - the historical path, kept because it is the control the
    # surface-pressure path is measured against. `area_weighted_uniform_pressure`
    # applies a uniform pressure to the element faces, which is what a bearing
    # load physically is: ANSYS then builds the consistent load vector, putting
    # nothing on the corner nodes and a third of each face's force on each
    # mid-side node.
    distribution: Literal[
        "area_weighted_equal_nodes", "area_weighted_uniform_pressure"
    ]
    source: str
    rationale: str = ""

    @model_validator(mode="after")
    def _validate_model(self):
        if self.model == "equivalent_total_force":
            if self.total_force_n_per_slot is None:
                raise ValueError(
                    "equivalent_total_force requires total_force_n_per_slot"
                )
        else:
            missing = [
                name
                for name, value in (
                    ("effective_mass_kg", self.effective_mass_kg),
                    ("center_of_mass_radius_mm", self.center_of_mass_radius_mm),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "mass_centroid_rpm missing fields: " + ", ".join(missing)
                )
        return self


class ConstraintIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cyclic_symmetry: bool
    axial_symmetry_z0: bool
    tangential_anchor: bool
    source: str
    rationale: str = ""


class StructuralIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["structural_intent_v1"] = "structural_intent_v1"
    status: Literal["ready", "ready_for_confirmation", "needs_input"]
    case_id: str
    bundle: str
    mesh_inp: str
    selected_face_nodes: str
    rotation: RotationIntent | None = None
    temperature: TemperatureIntent | None = None
    material: MaterialIntent | None = None
    blade_load: BladeLoadIntent | None = None
    constraints: ConstraintIntent | None = None
    source_manifest: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    rationale: str = ""

    @model_validator(mode="after")
    def _validate_ready(self):
        if self.status == "ready" or self.status == "ready_for_confirmation":
            missing = [
                name
                for name in (
                    "rotation",
                    "temperature",
                    "material",
                    "blade_load",
                    "constraints",
                )
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(
                    "ready intent missing sections: " + ", ".join(missing)
                )
        return self


class StructuralIntentAction(BaseModel):
    """Single tool schema used by the structural intent agent."""

    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "get_case_input",
        "inspect_mesh",
        "inspect_load_faces",
        "calculate_centrifugal_force",
        "submit_intent",
        "needs_input",
    ]
    mass_kg: float | None = Field(default=None, gt=0)
    center_of_mass_radius_mm: float | None = Field(default=None, gt=0)
    rpm: float | None = Field(default=None, gt=0)
    intent: StructuralIntent | None = None
    questions: list[str] = Field(default_factory=list)

