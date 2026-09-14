"""Versioned CFD intermediate representation. All physical values use SI units."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Positive = Annotated[float, Field(gt=0)]
Nonnegative = Annotated[float, Field(ge=0)]
UnitInterval = Annotated[float, Field(gt=0, le=1)]
Name = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def canonical(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, validate_default=True
    )


class Artifact(Model):
    path: str = Field(min_length=1)
    sha256: Digest


class GeometryRef(Model):
    lineage_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    cad_record_id: str = Field(min_length=1)
    geometry: Artifact
    topology: Artifact
    history_evidence: Artifact
    length_unit: Literal["m", "mm"]


class SurfaceRef(Model):
    source: Literal["selection", "generated"]
    key: str = Field(min_length=1)
    cardinality: Literal["exact_one", "set_allowed"] = "exact_one"


class DomainSpec(Model):
    strategy: Literal["full", "sector", "extract", "outer"]
    fluid_region: Name
    solid_regions: list[Name] = Field(default_factory=list)
    construction: Literal[
        "existing_fluid", "extract_void", "subtract_solid", "sector_cut"
    ]
    generated_surfaces: list[Name] = Field(default_factory=list)
    sector_angle_deg: Annotated[float, Field(gt=0, lt=360)] | None = None
    axis: tuple[float, float, float] = (0, 0, 1)
    origin_m: tuple[float, float, float] = (0, 0, 0)
    outer_bounds_m: tuple[float, float, float, float, float, float] | None = None

    @model_validator(mode="after")
    def consistent(self):
        if sum(x * x for x in self.axis) < 1e-20:
            raise ValueError("domain axis must be nonzero")
        if self.strategy == "sector" and (
            self.sector_angle_deg is None or self.construction != "sector_cut"
        ):
            raise ValueError("sector requires explicit angle and sector_cut")
        if self.strategy == "outer":
            b = self.outer_bounds_m
            if b is None or any(b[i] >= b[i + 3] for i in range(3)):
                raise ValueError("outer domain requires ordered bounds in metres")
        if len(set(self.generated_surfaces)) != len(self.generated_surfaces):
            raise ValueError("duplicate generated surfaces")
        return self


class Refinement(Model):
    surface: SurfaceRef
    size_m: Positive


class MeshSpec(Model):
    method: Literal["tetra", "poly", "hex"]
    global_size_m: Positive
    refinements: list[Refinement] = Field(default_factory=list)
    inflation_layers: Annotated[int, Field(ge=0, le=100)] = 0
    first_layer_m: Positive | None = None
    growth_rate: Annotated[float, Field(gt=1, le=2)] = 1.2
    max_cells: Annotated[int, Field(gt=0)] = 1000000
    max_skewness: Annotated[float, Field(gt=0, lt=1)] = 0.95
    min_orthogonal_quality: UnitInterval = 0.1

    @model_validator(mode="after")
    def inflation(self):
        if self.inflation_layers and self.first_layer_m is None:
            raise ValueError("inflation requires first_layer_m")
        return self


class Property(Model):
    constant: Positive | None = None
    temperature_table: list[tuple[Positive, Positive]] = Field(default_factory=list)

    @model_validator(mode="after")
    def one_source(self):
        if (self.constant is None) == (not self.temperature_table):
            raise ValueError("supply exactly one constant or temperature table")
        ts = [p[0] for p in self.temperature_table]
        if ts and (len(ts) < 2 or ts != sorted(set(ts))):
            raise ValueError(
                "temperature table needs >=2 increasing unique temperatures"
            )
        return self


class Material(Model):
    name: Name
    region: Name
    phase: Literal["fluid", "solid"]
    density_kg_m3: Property
    equation_of_state: Literal["constant_density", "ideal_gas"] = "constant_density"
    gas_constant_j_kgk: Positive | None = None
    viscosity_pa_s: Property | None = None
    conductivity_w_mk: Property | None = None
    heat_capacity_j_kgk: Property | None = None


class PhysicsSpec(Model):
    time_mode: Literal["steady", "transient"]
    turbulence: Literal["laminar", "k_epsilon", "k_omega_sst"]
    heat_transfer: Literal["isothermal", "energy", "cht"]
    compressible: bool = False
    reference_pressure_pa: Positive
    reference_temperature_k: Positive
    rotation_rad_s: float = 0
    rotation_model: Literal["none", "mrf", "sliding_mesh"] = "none"
    gravity_m_s2: tuple[float, float, float] = (0, 0, 0)

    @model_validator(mode="after")
    def rotation(self):
        if self.rotation_rad_s and self.rotation_model == "none":
            raise ValueError("rotation requires an explicit frame model")
        if self.rotation_model == "sliding_mesh" and self.time_mode != "transient":
            raise ValueError("sliding mesh requires transient physics")
        return self


class BoundarySpec(Model):
    name: Name
    surface: SurfaceRef
    kind: Literal[
        "velocity_inlet",
        "mass_flow_inlet",
        "pressure_outlet",
        "wall",
        "symmetry",
        "periodic",
        "interface",
    ]
    velocity_m_s: tuple[float, float, float] | None = None
    mass_flow_kg_s: Positive | None = None
    gauge_pressure_pa: float | None = None
    temperature_k: Positive | None = None
    heat_flux_w_m2: float | None = None
    thermal: Literal["adiabatic", "temperature", "heat_flux", "coupled"] = "adiabatic"
    peer: Name | None = None
    periodic_transform: (
        tuple[
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
        ]
        | None
    ) = None
    turbulence_intensity: UnitInterval | None = None
    hydraulic_diameter_m: Positive | None = None

    @model_validator(mode="after")
    def fields(self):
        required = {
            "velocity_inlet": "velocity_m_s",
            "mass_flow_inlet": "mass_flow_kg_s",
            "pressure_outlet": "gauge_pressure_pa",
        }
        for kind, field in required.items():
            if (getattr(self, field) is not None) != (self.kind == kind):
                raise ValueError(f"{field} is required only for {kind}")
        if (self.peer is not None) != (self.kind in {"periodic", "interface"}):
            raise ValueError(
                "periodic/interface require a peer; other boundaries forbid peers"
            )
        if self.thermal == "temperature" and self.temperature_k is None:
            raise ValueError("temperature wall requires temperature_k")
        if (self.heat_flux_w_m2 is not None) != (self.thermal == "heat_flux"):
            raise ValueError("heat flux requires explicit thermal=heat_flux")
        if (self.periodic_transform is not None) != (self.kind == "periodic"):
            raise ValueError("periodic boundaries require explicit 4x4 transforms")
        if self.kind == "wall" and (self.temperature_k is not None) != (
            self.thermal == "temperature"
        ):
            raise ValueError("wall temperature and thermal mode conflict")
        if self.kind == "interface" and self.thermal != "coupled":
            raise ValueError("CHT interface must be explicitly coupled")
        if self.kind != "wall" and self.thermal not in {"adiabatic", "coupled"}:
            raise ValueError("wall thermal controls only apply to walls")
        return self


class SolverControl(Model):
    algorithm: Literal["simple", "simplec", "piso", "coupled"]
    spatial_order: Literal[1, 2] = 2
    relaxation: UnitInterval = 0.5
    max_iterations: Annotated[int, Field(gt=0)] = 1000
    chunk_iterations: Annotated[int, Field(gt=0)] = 25
    time_step_s: Positive | None = None
    end_time_s: Positive | None = None
    max_courant: Positive = 5


class ConvergenceCriteria(Model):
    residuals: dict[Name, Positive]
    mass_relative_tolerance: UnitInterval = 0.001
    energy_relative_tolerance: UnitInterval = 0.01
    window: Annotated[int, Field(ge=2)] = 3
    divergence_factor: Annotated[float, Field(gt=1)] = 100
    stagnation_window: Annotated[int, Field(ge=3)] = 8
    monitor_relative_tolerance: UnitInterval = 0.001

    @model_validator(mode="after")
    def required_residuals(self):
        if (
            not {"continuity", "x_velocity", "y_velocity", "z_velocity"}
            <= self.residuals.keys()
        ):
            raise ValueError(
                "continuity and all velocity residual criteria are mandatory"
            )
        return self


class ResultRequest(Model):
    name: Name
    quantity: Literal["pressure", "temperature", "mass_flow", "heat_flux", "velocity"]
    operation: Literal["mean", "min", "max", "integral"]
    boundary: Name
    expected_range: tuple[float, float] | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.expected_range and self.expected_range[0] > self.expected_range[1]:
            raise ValueError("expected range must be ordered")
        return self


class Budget(Model):
    wall_time_s: Positive = 600
    cpu_count: Annotated[int, Field(gt=0)] = 2
    memory_mb: Annotated[int, Field(gt=0)] = 2048
    max_tool_calls: Annotated[int, Field(gt=0)] = 200
    max_agent_calls: Annotated[int, Field(gt=0)] = 10
    max_repairs: Annotated[int, Field(ge=0)] = 2
    max_output_bytes: Annotated[int, Field(gt=0)] = 100000000


class SimulationSpec(Model):
    schema_version: Literal["cfd_spec_v1"] = "cfd_spec_v1"
    geometry_ref: GeometryRef
    domain_strategy: DomainSpec
    mesh_strategy: MeshSpec
    physics_spec: PhysicsSpec
    material_spec: list[Material] = Field(min_length=1)
    boundary_specs: list[BoundarySpec] = Field(min_length=1)
    solver_control: SolverControl
    convergence_criteria: ConvergenceCriteria
    result_requests: list[ResultRequest] = Field(min_length=1)
    budget: Budget = Field(default_factory=Budget)
    allowed_repairs: list[Literal["refine_mesh", "reduce_relaxation"]] = Field(
        default_factory=list
    )
    expert_confirmed: bool = False
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistency(self):
        boundaries = {b.name: b for b in self.boundary_specs}
        if len(boundaries) != len(self.boundary_specs):
            raise ValueError("duplicate boundary name")
        refs = [(b.surface.source, b.surface.key) for b in self.boundary_specs]
        if len(set(refs)) != len(refs):
            raise ValueError("a surface cannot have conflicting boundary conditions")
        for b in self.boundary_specs:
            if (
                b.surface.source == "generated"
                and b.surface.key not in self.domain_strategy.generated_surfaces
            ):
                raise ValueError(f"unknown generated surface: {b.surface.key}")
            if b.peer:
                peer = boundaries.get(b.peer)
                if (
                    peer is None
                    or peer is b
                    or peer.peer != b.name
                    or peer.kind != b.kind
                ):
                    raise ValueError("boundary pairs must be reciprocal and distinct")
                if b.kind == "periodic":
                    a, c = b.periodic_transform, peer.periodic_transform
                    if tuple(a[12:]) != (0, 0, 0, 1):
                        raise ValueError("periodic transform must be affine")
                    for i in range(4):
                        for j in range(4):
                            value = sum(a[4 * i + k] * c[4 * k + j] for k in range(4))
                            if abs(value - float(i == j)) > 1e-8:
                                raise ValueError(
                                    "periodic peer transforms must be inverse"
                                )
                    for i in range(3):
                        for j in range(3):
                            value = sum(a[4 * i + k] * a[4 * j + k] for k in range(3))
                            if abs(value - float(i == j)) > 1e-8:
                                raise ValueError(
                                    "periodic transforms must preserve lengths"
                                )

        kinds = {b.kind for b in self.boundary_specs}
        if bool(kinds & {"velocity_inlet", "mass_flow_inlet"}) != (
            "pressure_outlet" in kinds
        ):
            raise ValueError("open flow requires both an inlet and a pressure outlet")
        for refinement in self.mesh_strategy.refinements:
            if (
                refinement.surface.source == "generated"
                and refinement.surface.key
                not in self.domain_strategy.generated_surfaces
            ):
                raise ValueError("refinement references unknown generated surface")
        for r in self.result_requests:
            if r.boundary not in boundaries:
                raise ValueError("result references unknown boundary")
        if len({r.name for r in self.result_requests}) != len(self.result_requests):
            raise ValueError("duplicate result name")
        p = self.physics_spec
        c = self.solver_control
        if p.time_mode == "transient" and (
            c.time_step_s is None or c.end_time_s is None
        ):
            raise ValueError("transient needs timestep and physical end time")
        if p.time_mode == "steady" and (
            c.time_step_s is not None or c.end_time_s is not None
        ):
            raise ValueError("steady forbids transient time controls")
        residuals = self.convergence_criteria.residuals
        needed = (
            {"k", "omega"}
            if p.turbulence == "k_omega_sst"
            else {"k", "epsilon"}
            if p.turbulence == "k_epsilon"
            else set()
        )
        if p.heat_transfer != "isothermal":
            needed.add("energy")
        if not needed <= residuals.keys():
            raise ValueError(
                f"missing active-equation criteria: {needed - residuals.keys()}"
            )
        regions = [m.region for m in self.material_spec]
        if len(set(regions)) != len(regions):
            raise ValueError("one material per region required")
        fluids = [m for m in self.material_spec if m.phase == "fluid"]
        if (
            len(fluids) != 1
            or fluids[0].region != self.domain_strategy.fluid_region
            or fluids[0].viscosity_pa_s is None
        ):
            raise ValueError("one viscous fluid material must match the fluid region")
        if p.compressible and (
            fluids[0].equation_of_state != "ideal_gas"
            or fluids[0].gas_constant_j_kgk is None
        ):
            raise ValueError(
                "compressible model requires explicit ideal-gas EOS and gas constant"
            )
        if not p.compressible and fluids[0].equation_of_state != "constant_density":
            raise ValueError("incompressible model requires constant-density EOS")
        solids = {m.region for m in self.material_spec if m.phase == "solid"}
        if solids != set(self.domain_strategy.solid_regions):
            raise ValueError("solid materials must match solid regions")
        if p.heat_transfer == "cht" and (
            not solids or not any(b.kind == "interface" for b in self.boundary_specs)
        ):
            raise ValueError("CHT requires solids and coupled interfaces")
        if p.heat_transfer != "isothermal":
            if any(
                m.conductivity_w_mk is None or m.heat_capacity_j_kgk is None
                for m in self.material_spec
            ):
                raise ValueError("energy requires conductivity and heat capacity")
            if any(
                b.kind.endswith("inlet") and b.temperature_k is None
                for b in self.boundary_specs
            ):
                raise ValueError("energy inlets require temperature")
        if p.turbulence != "laminar" and any(
            b.kind.endswith("inlet")
            and (b.turbulence_intensity is None or b.hydraulic_diameter_m is None)
            for b in self.boundary_specs
        ):
            raise ValueError(
                "turbulent inlet requires intensity and hydraulic diameter"
            )
        return self

    @property
    def spec_hash(self) -> str:
        return digest(self)


class Diagnostic(Model):
    code: str
    message: str
    stage: str
    status: Literal["failed", "rejected", "timeout", "capability_gap"] = "rejected"
    recoverable: bool = False
    details: dict = Field(default_factory=dict)


class CFDError(Exception):
    def __init__(
        self, code, message, stage, status="rejected", recoverable=False, **details
    ):
        self.diagnostic = Diagnostic(
            code=code,
            message=message,
            stage=stage,
            status=status,
            recoverable=recoverable,
            details=details,
        )
        super().__init__(message)
