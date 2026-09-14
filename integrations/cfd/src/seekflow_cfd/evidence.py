"""Typed backend evidence and independent acceptance gates."""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

from pydantic import Field

from .models import CFDError, Digest, Model, Name, Nonnegative, Positive, SimulationSpec


class FaceBinding(Model):
    source_key: str
    status: Literal["unique", "set"]
    proof: Literal[
        "exact_kernel_history",
        "exact_construction",
        "exact_brep_transfer",
    ]
    entity_kind: Literal["face"] = "face"
    # IDs are current-revision opaque handles, never reusable geometry indices.
    entity_ids: list[str] = Field(min_length=1)
    lineage_id: str
    revision_id: str
    geometry_hash: Digest
    history_complete: Literal[True]
    provenance: str = Field(min_length=1)
    parent_entity_ids: list[str] = Field(default_factory=list)
    native_face_artifacts: dict[str, str] = Field(default_factory=dict)


class DomainReport(Model):
    domain_id: str
    spec_hash: Digest
    volume_m3: Positive
    fluid_regions: list[str] = Field(min_length=1)
    solid_regions: list[str] = Field(default_factory=list)
    boundary_map: dict[str, FaceBinding]
    exterior_entity_ids: list[str] = Field(min_length=1)
    uncovered_entity_ids: list[str] = Field(default_factory=list)


class MeshReport(Model):
    mesh_id: str
    spec_hash: Digest
    cell_count: int = Field(gt=0)
    min_volume_m3: float
    negative_volume_cells: int = Field(ge=0)
    max_skewness: float = Field(ge=0, le=1)
    min_orthogonal_quality: float = Field(ge=0, le=1)
    periodic_node_mismatch: int = Field(ge=0)
    boundary_map: dict[str, FaceBinding]
    # Exact named-zone -> topology mapping must survive export/import.
    zone_labels: dict[str, str]
    artifact_paths: list[str] = Field(default_factory=list)


class Sample(Model):
    iteration: int = Field(gt=0)
    physical_time_s: Nonnegative = 0
    residuals: dict[str, Nonnegative]
    # Signed outward flux, including sources/storage (e.g. transient storage).
    mass_flux_kg_s: dict[str, float]
    mass_source_kg_s: float = 0
    mass_storage_kg_s: float = 0
    energy_flux_w: dict[str, float] = Field(default_factory=dict)
    energy_source_w: float = 0
    energy_storage_w: float = 0
    courant: Nonnegative
    monitors: dict[str, float]


class SolverReport(Model):
    spec_hash: Digest
    samples: list[Sample] = Field(min_length=1)
    checkpoint: str = Field(min_length=1)
    log_paths: list[str] = Field(min_length=1)
    solver_error: str | None = None


class Metric(Model):
    value: float
    unit: str = Field(min_length=1)
    boundary: Name


class ResultReport(Model):
    spec_hash: Digest
    metrics: dict[str, Metric]
    artifact_paths: list[str] = Field(default_factory=list)


def check_domain(spec: SimulationSpec, report: DomainReport):
    g = spec.geometry_ref
    if report.spec_hash != spec.spec_hash:
        raise CFDError("stale_domain", "Domain belongs to a different spec", "domain")
    if report.fluid_regions != [spec.domain_strategy.fluid_region] or set(
        report.solid_regions
    ) != set(spec.domain_strategy.solid_regions):
        raise CFDError(
            "region_mismatch", "Domain regions disagree with materials", "domain"
        )
    if report.uncovered_entity_ids or set(report.boundary_map) != {
        b.name for b in spec.boundary_specs
    }:
        raise CFDError(
            "boundary_coverage", "All boundaries must be explicitly bound", "domain"
        )
    seen = set()
    for b in spec.boundary_specs:
        binding = report.boundary_map[b.name]
        if (binding.lineage_id, binding.revision_id, binding.geometry_hash) != (
            g.lineage_id,
            g.revision_id,
            g.geometry.sha256,
        ):
            raise CFDError(
                "stale_binding", "Boundary is bound to another CAD revision", "domain"
            )
        if binding.source_key != b.surface.key:
            raise CFDError(
                "wrong_binding", "Boundary source does not match spec", "domain"
            )
        ids = binding.entity_ids
        if len(set(ids)) != len(ids) or seen.intersection(ids):
            raise CFDError(
                "overlapping_boundaries",
                "Duplicate/overlapping physical faces",
                "domain",
            )
        if b.surface.cardinality == "exact_one" and len(ids) != 1:
            raise CFDError(
                "boundary_cardinality",
                "Boundary split requires explicit SET policy",
                "domain",
            )
        if binding.status != ("unique" if len(ids) == 1 else "set"):
            raise CFDError("binding_status", "Binding status/count mismatch", "domain")
        seen.update(ids)
    if seen != set(report.exterior_entity_ids) or len(
        set(report.exterior_entity_ids)
    ) != len(report.exterior_entity_ids):
        raise CFDError(
            "boundary_coverage",
            "Exterior surface inventory does not match boundary assignments",
            "domain",
        )


def check_mesh(spec: SimulationSpec, domain: DomainReport, mesh: MeshReport):
    m = spec.mesh_strategy
    if mesh.spec_hash != spec.spec_hash or mesh.boundary_map != domain.boundary_map:
        raise CFDError("mesh_binding_mismatch", "Mesh lost topology provenance", "mesh")
    if (
        set(mesh.zone_labels) != set(domain.boundary_map)
        or len(set(mesh.zone_labels.values())) != len(mesh.zone_labels)
        or any(not v for v in mesh.zone_labels.values())
    ):
        raise CFDError(
            "mesh_zone_mismatch", "Every boundary needs a distinct solver zone", "mesh"
        )
    if mesh.cell_count > m.max_cells:
        raise CFDError("cell_budget", "Mesh exceeds hard cell budget", "mesh")
    if (
        mesh.min_volume_m3 <= 0
        or mesh.negative_volume_cells
        or mesh.max_skewness > m.max_skewness
        or mesh.min_orthogonal_quality < m.min_orthogonal_quality
        or mesh.periodic_node_mismatch
    ):
        raise CFDError(
            "mesh_quality",
            "Mesh quality gate failed",
            "mesh",
            "failed",
            True,
            report=mesh.model_dump(mode="json"),
        )


def imbalance(flux: dict[str, float], source: float, storage: float) -> float:
    scale = max(sum(abs(v) for v in flux.values()), abs(source), abs(storage), 1e-30)
    return abs(sum(flux.values()) + storage - source) / scale


def convergence(spec: SimulationSpec, samples: list[Sample]) -> dict:
    criteria = spec.convergence_criteria
    if any(
        b.iteration <= a.iteration or b.physical_time_s < a.physical_time_s
        for a, b in pairwise(samples)
    ):
        raise CFDError(
            "nonmonotonic_history",
            "Solver history must strictly advance",
            "solver",
            "failed",
        )
    names = {b.name for b in spec.boundary_specs}
    active = set(criteria.residuals)
    for s in samples:
        if not active <= s.residuals.keys() or set(s.mass_flux_kg_s) != names:
            raise CFDError(
                "missing_evidence",
                "Residual or boundary mass flux evidence missing",
                "solver",
                "failed",
            )
        if set(s.monitors) != {r.name for r in spec.result_requests}:
            raise CFDError(
                "missing_monitors",
                "Requested result monitors are mandatory",
                "solver",
                "failed",
            )
        if (
            spec.physics_spec.heat_transfer != "isothermal"
            and set(s.energy_flux_w) != names
        ):
            raise CFDError(
                "missing_energy_evidence",
                "Every boundary needs an energy flux",
                "solver",
                "failed",
            )
    window = samples[-criteria.window :]
    if len(window) < criteria.window:
        return {"state": "continue", "reason": "insufficient_window"}
    masses = [
        imbalance(s.mass_flux_kg_s, s.mass_source_kg_s, s.mass_storage_kg_s)
        for s in window
    ]
    energies = [
        imbalance(s.energy_flux_w, s.energy_source_w, s.energy_storage_w)
        for s in window
    ]
    residual_ok = all(
        s.residuals[k] <= v for s in window for k, v in criteria.residuals.items()
    )
    mass_ok = max(masses) <= criteria.mass_relative_tolerance
    energy_ok = (
        spec.physics_spec.heat_transfer == "isothermal"
        or max(energies) <= criteria.energy_relative_tolerance
    )
    courant_ok = all(s.courant <= spec.solver_control.max_courant for s in window)
    stable = all(
        (
            max(s.monitors[r.name] for s in window)
            - min(s.monitors[r.name] for s in window)
        )
        / max(max(abs(s.monitors[r.name]) for s in window), 1e-30)
        <= criteria.monitor_relative_tolerance
        for r in spec.result_requests
    )
    time_ok = (
        spec.physics_spec.time_mode == "steady"
        or samples[-1].physical_time_s >= spec.solver_control.end_time_s
    )
    # Transient stability refers to stationary/statistically stable endpoints only;
    # nonstationary periodic statistics require a backend extension, not a false pass.
    state = (
        "converged"
        if residual_ok and mass_ok and energy_ok and courant_ok and stable and time_ok
        else "continue"
    )
    if any(
        window[-1].residuals[k]
        > max(window[0].residuals[k], criteria.residuals[k])
        * criteria.divergence_factor
        for k in active
    ):
        state = "diverged"
    if (
        state == "continue"
        and len(samples) >= criteria.stagnation_window
        and not residual_ok
    ):
        tail = samples[-criteria.stagnation_window :]
        if all(
            max(s.residuals[k] for s in tail) - min(s.residuals[k] for s in tail)
            <= max(tail[0].residuals[k], 1e-30) * 1e-3
            for k in active
        ):
            state = "stagnated"
    return {
        "state": state,
        "residuals_pass": residual_ok,
        "mass_pass": mass_ok,
        "energy_pass": energy_ok,
        "courant_pass": courant_ok,
        "monitors_stable": stable,
        "physical_time_pass": time_ok,
        "mass_relative_error": max(masses),
        "energy_relative_error": max(energies),
        "window_iterations": [s.iteration for s in window],
    }


def check_results(spec: SimulationSpec, report: ResultReport) -> list[str]:
    if report.spec_hash != spec.spec_hash or set(report.metrics) != {
        r.name for r in spec.result_requests
    }:
        raise CFDError(
            "result_mismatch",
            "Missing results or wrong spec hash",
            "postprocess",
            "failed",
        )
    units = {
        "pressure": "Pa",
        "temperature": "K",
        "mass_flow": "kg/s",
        "heat_flux": "W/m2",
        "velocity": "m/s",
    }
    warnings = []
    for r in spec.result_requests:
        m = report.metrics[r.name]
        unit = units[r.quantity]
        if r.operation == "integral" and r.quantity == "heat_flux":
            unit = "W"
        elif r.operation == "integral" and r.quantity in {
            "pressure",
            "temperature",
            "velocity",
        }:
            unit = {"pressure": "N", "temperature": "K*m2", "velocity": "m3/s"}[
                r.quantity
            ]
        if m.boundary != r.boundary or m.unit != unit:
            raise CFDError(
                "result_units",
                "Result unit or boundary mismatch",
                "postprocess",
                "failed",
            )
        if r.quantity == "temperature" and m.value <= 0:
            warnings.append(f"{r.name}: nonphysical absolute temperature")
        if (
            r.expected_range
            and not r.expected_range[0] <= m.value <= r.expected_range[1]
        ):
            warnings.append(f"{r.name}: outside expert expected range")
    return warnings


def mesh_independence(
    records: list[dict], metric: str, tolerance: float = 0.02
) -> dict:
    """Conservative three-grid comparison; no unsupported GCI claim."""
    if len(records) < 3 or not 0 < tolerance < 1:
        return {
            "verified": False,
            "reason": "three successful distinct meshes required",
        }
    if any(r.get("status") != "success" or r.get("is_mock") for r in records):
        return {"verified": False, "reason": "real successful solves required"}
    specs = [SimulationSpec.model_validate(r["simulation_spec"]) for r in records]
    comparable = []
    for s in specs:
        d = s.model_dump(mode="json")
        d.pop("mesh_strategy")
        comparable.append(d)
    if any(d != comparable[0] for d in comparable[1:]):
        return {"verified": False, "reason": "geometry/physics/controls differ"}
    pairs = sorted(
        (r["mesh_report"]["cell_count"], r["metrics"][metric]["value"]) for r in records
    )
    if len({n for n, _ in pairs}) != len(pairs):
        return {"verified": False, "reason": "mesh sizes must differ"}
    differences = [abs(b[1] - a[1]) / max(abs(b[1]), 1e-30) for a, b in pairwise(pairs)]
    return {
        "verified": all(d <= tolerance for d in differences[-2:]),
        "relative_differences": differences,
        "method": "three_mesh_relative_comparison",
        "gci": None,
    }
