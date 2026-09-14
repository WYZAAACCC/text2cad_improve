"""Backend contract and deterministic test backend; no implicit real-solver fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import Field

from .evidence import DomainReport, FaceBinding, MeshReport, ResultReport, SolverReport
from .models import CFDError, Model, SimulationSpec
from .storage import atomic_json

OPERATIONS = {
    "domain.construct": "geometry_topology",
    "mesh.generate": "domain_mesh",
    "physics.configure": "physics_boundary",
    "solver.initialize": "solver_monitor",
    "solver.advance": "solver_monitor",
    "solver.stop": "solver_monitor",
    "results.extract": "verification_report",
}


class Capabilities(Model):
    name: str
    version: str
    is_mock: bool
    operations: list[str]
    domain_strategies: list[str]
    mesh_methods: list[str]
    turbulence_models: list[str]
    heat_models: list[str]
    time_modes: list[str]
    rotation_models: list[str]
    compressible: bool = False
    temperature_tables: bool = False
    restart: bool = False
    resource_limits_enforced: bool = False

    # Solver settings the backend actually transfers to the solver. A spec that
    # asks for anything outside these is refused at preflight, instead of being
    # executed with silently different physics. The defaults are the fail-closed
    # ones: a backend that has not declared support does not have it.
    # `materials` lists the material names the backend can configure; "*"
    # matches any name.
    spatial_orders: list[int] = Field(default_factory=list)
    pv_coupling_schemes: list[str] = Field(default_factory=list)
    under_relaxation: bool = False
    materials: list[str] = Field(default_factory=list)
    operating_pressure: bool = False
    gravity: bool = False
    inflation: bool = False

    def check(self, spec: SimulationSpec):
        choices = [
            (spec.domain_strategy.strategy, self.domain_strategies),
            (spec.mesh_strategy.method, self.mesh_methods),
            (spec.physics_spec.turbulence, self.turbulence_models),
            (spec.physics_spec.heat_transfer, self.heat_models),
            (spec.physics_spec.time_mode, self.time_modes),
            (spec.physics_spec.rotation_model, self.rotation_models),
        ]
        gaps = [v for v, supported in choices if v not in supported]
        gaps.extend(set(OPERATIONS) - set(self.operations))
        if spec.physics_spec.compressible and not self.compressible:
            gaps.append("compressibility")
        if spec.solver_control.spatial_order not in self.spatial_orders:
            gaps.append(f"spatial_order:{spec.solver_control.spatial_order}")
        if spec.solver_control.algorithm not in self.pv_coupling_schemes:
            gaps.append(f"pv_coupling:{spec.solver_control.algorithm}")
        if not self.under_relaxation:
            gaps.append("under_relaxation")
        if "*" not in self.materials:
            gaps.extend(
                f"material:{m.name}"
                for m in spec.material_spec
                if m.name not in self.materials
            )
        if not self.operating_pressure:
            gaps.append("operating_pressure")
        if (
            any(abs(value) > 0 for value in spec.physics_spec.gravity_m_s2)
            and not self.gravity
        ):
            gaps.append("gravity")
        if spec.mesh_strategy.inflation_layers and not self.inflation:
            gaps.append("inflation")
        if (
            any(
                prop and prop.temperature_table
                for m in spec.material_spec
                for prop in (
                    m.density_kg_m3,
                    m.viscosity_pa_s,
                    m.conductivity_w_mk,
                    m.heat_capacity_j_kgk,
                )
            )
            and not self.temperature_tables
        ):
            gaps.append("temperature_tables")
        if not self.is_mock and not self.resource_limits_enforced:
            gaps.append("enforced_cpu_memory_process_limits")
        if gaps:
            raise CFDError(
                "backend_capability",
                "Unsupported capabilities: " + ", ".join(sorted(gaps)),
                "preflight",
                "capability_gap",
            )


class Backend(Protocol):
    capabilities: Capabilities

    def execute(
        self, operation: str, payload: dict, job_dir: Path, timeout_s: float
    ) -> dict: ...


class MockBackend:
    capabilities = Capabilities(
        name="mock",
        version="1",
        is_mock=True,
        operations=list(OPERATIONS),
        domain_strategies=["full", "sector", "extract", "outer"],
        mesh_methods=["tetra", "poly", "hex"],
        turbulence_models=["laminar", "k_epsilon", "k_omega_sst"],
        heat_models=["isothermal", "energy", "cht"],
        time_modes=["steady", "transient"],
        rotation_models=["none", "mrf", "sliding_mesh"],
        compressible=True,
        temperature_tables=True,
        restart=True,
        spatial_orders=[1, 2],
        pv_coupling_schemes=["simple", "simplec", "piso", "coupled"],
        under_relaxation=True,
        materials=["*"],
        operating_pressure=True,
        gravity=True,
        inflation=True,
    )

    def __init__(self, fault: str | None = None):
        self.fault = fault
        self.calls = []

    def execute(self, operation, payload, job_dir, timeout_s):
        if operation not in OPERATIONS:
            raise CFDError("unknown_tool", operation, "tools")
        self.calls.append(operation)
        spec = SimulationSpec.model_validate(payload["spec"])
        h = spec.spec_hash
        if operation == "domain.construct":
            g = spec.geometry_ref
            mapping = {}
            for b in spec.boundary_specs:
                if b.surface.source == "selection":
                    binding = FaceBinding.model_validate(
                        payload["topology"][b.surface.key]
                    )
                else:
                    binding = FaceBinding(
                        source_key=b.surface.key,
                        status="unique",
                        proof="exact_construction",
                        entity_ids=["mock:generated:" + b.surface.key],
                        lineage_id=g.lineage_id,
                        revision_id=g.revision_id,
                        geometry_hash=g.geometry.sha256,
                        history_complete=True,
                        provenance="MOCK_DOMAIN_CONSTRUCTION_ONLY",
                    )
                mapping[b.name] = binding
            result = DomainReport(
                domain_id="mock-domain-" + h[:12],
                spec_hash=h,
                volume_m3=0.001,
                fluid_regions=[spec.domain_strategy.fluid_region],
                solid_regions=spec.domain_strategy.solid_regions,
                boundary_map=mapping,
                exterior_entity_ids=[i for b in mapping.values() for i in b.entity_ids],
            )
            return result.model_dump(mode="json")
        if operation == "mesh.generate":
            name = f"mock-mesh-{h[:12]}.json"
            atomic_json(
                job_dir / name,
                {
                    "mock": True,
                    "notice": "Synthetic mesh metadata, not a physical mesh",
                    "spec_hash": h,
                },
            )
            return MeshReport(
                mesh_id="mock-mesh-" + h[:12],
                spec_hash=h,
                cell_count=1000,
                min_volume_m3=-1 if self.fault == "bad_mesh" else 1e-12,
                negative_volume_cells=int(self.fault == "bad_mesh"),
                max_skewness=0.3,
                min_orthogonal_quality=0.8,
                periodic_node_mismatch=0,
                boundary_map=payload["domain"]["boundary_map"],
                zone_labels={b.name: b.name for b in spec.boundary_specs},
                artifact_paths=[name],
            ).model_dump(mode="json")
        if operation in {"physics.configure", "solver.initialize", "solver.stop"}:
            return {"ok": True, "spec_hash": h, "is_mock": True}
        if operation == "solver.advance":
            start = payload["start_iteration"]
            end = start + payload["iterations"]
            samples = []
            for i in range(start + 1, end + 1):
                value = (
                    1
                    if self.fault == "stagnation"
                    else 10.0 ** min(20, i)
                    if self.fault == "divergence"
                    else 10.0 ** (-min(i, 12))
                )
                flux = {b.name: 0.0 for b in spec.boundary_specs}
                inlets = [
                    b.name for b in spec.boundary_specs if b.kind.endswith("inlet")
                ]
                outlets = [
                    b.name for b in spec.boundary_specs if b.kind == "pressure_outlet"
                ]
                if inlets and outlets:
                    for n in inlets:
                        flux[n] = -1.0 / len(inlets)
                    for n in outlets:
                        flux[n] = (
                            2.0 if self.fault == "mass_imbalance" else 1.0
                        ) / len(outlets)
                samples.append(
                    {
                        "iteration": i,
                        "physical_time_s": i * (spec.solver_control.time_step_s or 0),
                        "residuals": {
                            k: value for k in spec.convergence_criteria.residuals
                        },
                        "mass_flux_kg_s": flux,
                        "energy_flux_w": {k: v * 10 for k, v in flux.items()},
                        "courant": 0.5,
                        "monitors": {
                            r.name: 300.0 if r.quantity == "temperature" else 1.0
                            for r in spec.result_requests
                        },
                    }
                )
            checkpoint = f"mock-checkpoint-{h[:12]}-{end}.json"
            atomic_json(
                job_dir / checkpoint, {"spec_hash": h, "iteration": end, "mock": True}
            )
            log = f"mock-solver-{h[:12]}-{end}.json"
            atomic_json(job_dir / log, {"samples": samples, "mock": True})
            return SolverReport(
                spec_hash=h, samples=samples, checkpoint=checkpoint, log_paths=[log]
            ).model_dump(mode="json")
        if operation == "results.extract":
            units = {
                "pressure": "Pa",
                "temperature": "K",
                "mass_flow": "kg/s",
                "heat_flux": "W/m2",
                "velocity": "m/s",
            }
            integrated = {
                "pressure": "N",
                "temperature": "K*m2",
                "mass_flow": "kg/s",
                "heat_flux": "W",
                "velocity": "m3/s",
            }
            return ResultReport(
                spec_hash=h,
                metrics={
                    r.name: {
                        "value": 300 if r.quantity == "temperature" else 1,
                        "unit": (integrated if r.operation == "integral" else units)[
                            r.quantity
                        ],
                        "boundary": r.boundary,
                    }
                    for r in spec.result_requests
                },
            ).model_dump(mode="json")
        raise CFDError("unknown_tool", operation, "tools")
