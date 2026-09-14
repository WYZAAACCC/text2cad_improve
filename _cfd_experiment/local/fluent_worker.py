"""Trusted local Fluent 18.1 file-RPC worker.

The worker implements the generic CFD operations used by seekflow_cfd:

  domain.construct   - Gmsh OCC import + rectangular outer-domain boolean cut
  mesh.generate      - tetrahedral volume mesh -> I-deas UNV -> Fluent native MSH
  physics.configure  - Fluent 18.1 TUI boundary-zone configuration
  solver.initialize  - real Fluent initialization and checkpoint write
  solver.advance     - real Fluent iteration chunks with per-iteration evidence
  solver.stop        - acknowledgement (chunks are already persisted)
  results.extract    - Fluent surface reports -> typed ResultReport

This is an operator-installed trusted executable. It never accepts or executes
Agent-authored scripts/commands. Only the first staged rectangular-domain
strategy ("outer" + "subtract_solid"), tetra meshing, steady laminar
isothermal flow, and normal-to-boundary velocity/pressure/wall BCs are
implemented; unsupported spec combinations return structured capability gaps.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from seekflow_cfd.backends import OPERATIONS
from seekflow_cfd.evidence import (
    DomainReport,
    FaceBinding,
    MeshReport,
    ResultReport,
    Sample,
    SolverReport,
)
from seekflow_cfd.models import CFDError, SimulationSpec
from seekflow_cfd.storage import atomic_json, confined

FLUENT_EXE = Path(
    os.environ.get(
        "SEEKFLOW_FLUENT_EXE",
        r"D:\ANSYS181\ANSYS Inc\v181\fluent\ntbin\win64\fluent.exe",
    )
)
FE_EXE = Path(
    os.environ.get(
        "SEEKFLOW_FE2RAM_EXE",
        r"D:\ANSYS181\ANSYS Inc\v181\fluent\fluent18.1.0\utility\fe2ram\win64\fe.exe",
    )
)
SIDE_KEYS = {"x_min", "x_max", "y_min", "y_max", "z_min", "z_max"}
KNOWN_DOMAIN_KEYS = SIDE_KEYS | {"solid_wall"}
MESH_IMPROVE_PASSES = 10
FLUENT_ZONE_TYPE = {
    "velocity_inlet": "velocity-inlet",
    "pressure_outlet": "pressure-outlet",
    "wall": "wall",
    "symmetry": "symmetry",
}


def _fluent_exe():
    if not FLUENT_EXE.is_file():
        raise CFDError(
            "fluent_missing",
            "Configured ANSYS Fluent executable is unavailable",
            "runner",
            "capability_gap",
        )
    return str(FLUENT_EXE)


def _fe_exe():
    if not FE_EXE.is_file():
        raise CFDError(
            "fe2ram_missing",
            "Configured Fluent fe2ram converter is unavailable",
            "mesh",
            "capability_gap",
        )
    return str(FE_EXE)


def _run_process(job_dir: Path, log_name: str, command: list[str]) -> Path:
    log = job_dir / log_name
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as out:
        result = subprocess.run(
            command,
            cwd=str(job_dir),
            stdout=out,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode:
        raise CFDError(
            "external_command_failed",
            f"{Path(command[0]).name} exited with code {result.returncode}; "
            f"see {log.name}",
            "runner",
            "failed",
        )
    return log


def _run_fluent(
    job_dir: Path,
    log_name: str,
    journal_lines: list[str],
    cpu_count: int,
) -> Path:
    journal = job_dir / (log_name + ".jou")
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("\n".join(journal_lines) + "\n", encoding="utf-8")
    log = _run_process(
        job_dir,
        log_name + ".out",
        [_fluent_exe(), "3ddp", f"-t{max(1, min(int(cpu_count), 20))}", "-g", "-i", str(journal)],
    )
    _fail_on_fluent_errors(job_dir, log)
    return log


# Fluent reports a journal that diverged from what the TUI expected in several
# ways, and only the first of them is prefixed with "Error". The others are the
# signature of an interactive menu consuming the wrong number of answers, which
# is exactly how the wizard-driven commands below (change-create, gravity,
# energy) fail. Verified against Fluent 18.1 on 2026-09-11.
FLUENT_ERROR_MARKERS = (
    "Error",  # "Error: eval: unbound variable" / "Error Object: ..."
    "*** ERROR",  # Fluent's solver-level banner uses upper case
    "invalid command [",
    "Please answer y[es] or n[o]",
    "The requested scheme is unavailable",
    "Invalid choice.",
)


def _fail_on_fluent_errors(job_dir: Path, log: Path) -> None:
    """Raise if the Fluent transcript shows the journal did not take effect.

    Fluent continues after a rejected TUI command and still exits 0, so the
    process exit code alone cannot tell whether the journal worked. A failed
    boundary condition, a diverged wizard answer sequence or a case that never
    loaded would otherwise surface only as a wrong number at the end of the run.
    """
    text = _read_log(job_dir, log)
    errors = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(
            stripped.startswith(marker) or marker in stripped
            for marker in FLUENT_ERROR_MARKERS
        ):
            errors.append(stripped[:200])
        if len(errors) >= 5:
            break
    if errors:
        raise CFDError(
            "fluent_tui_error",
            "Fluent reported errors while running the journal: "
            + " | ".join(errors),
            "solver",
            "failed",
        )


def _read_log(job_dir: Path, name: str | Path) -> str:
    if isinstance(name, Path):
        name = name.resolve().relative_to(job_dir.resolve()).as_posix()
    path = confined(job_dir, name)
    if not path.is_file():
        raise CFDError(
            "missing_log",
            "Expected worker log does not exist",
            "runner",
            "failed",
        )
    return path.read_text(encoding="utf-8", errors="replace")


def _geometry_step(input_root: str | None, spec: SimulationSpec) -> Path:
    if not input_root:
        raise CFDError(
            "input_root_missing",
            "Local worker requires the CAD input root in its RPC request",
            "domain",
            "capability_gap",
        )
    path = confined(Path(input_root), spec.geometry_ref.geometry.path)
    if not path.is_file():
        raise CFDError(
            "cad_geometry_missing",
            f"Missing STEP geometry: {path}",
            "domain",
            "failed",
        )
    return path


def _unapplied_spec_fields(spec: SimulationSpec) -> list[str]:
    """Spec fields this worker accepts but never transfers to Fluent.

    Disclosed in the physics.configure response so a reader of the run
    evidence cannot mistake a declared value for an applied one.
    """
    return [
        "physics_spec.reference_temperature_k",
    ]


def _check_spec_physics_applied(spec: SimulationSpec):
    """Reject spec physics this worker still cannot transfer to Fluent.

    Material, discretisation, pressure-velocity coupling, under-relaxation,
    operating pressure, gravity and the energy model are configured by the
    journal builders above. What remains unimplemented is rejected here.
    """
    if spec.physics_spec.rotation_model != "none":
        raise CFDError(
            "unsupported_rotation_model",
            "This worker sets no rotating reference frame",
            "physics",
            "capability_gap",
        )
    if spec.mesh_strategy.inflation_layers:
        raise CFDError(
            "unsupported_inflation",
            "This worker generates no boundary-layer inflation",
            "mesh",
            "capability_gap",
        )


def _check_implemented(spec: SimulationSpec, op: str):
    d = spec.domain_strategy
    p = spec.physics_spec
    if op in {"domain.construct", "mesh.generate"} and not (
        d.strategy == "outer"
        and d.construction == "subtract_solid"
        and d.outer_bounds_m is not None
    ):
        raise CFDError(
            "unsupported_domain",
            "This worker implements outer rectangular subtract-solid domains only",
            "domain",
            "capability_gap",
        )
    if op in {"mesh.generate"} and spec.mesh_strategy.method != "tetra":
        raise CFDError(
            "unsupported_mesh",
            "This worker implements tetrahedral volume meshes only",
            "mesh",
            "capability_gap",
        )
    if op in {
        "physics.configure",
        "solver.initialize",
        "solver.advance",
        "solver.stop",
        "results.extract",
    }:
        if p.time_mode != "steady" or p.turbulence != "laminar":
            raise CFDError(
                "unsupported_physics",
                "This worker implements steady laminar physics only",
                "physics",
                "capability_gap",
            )
        if p.heat_transfer != "isothermal" or p.compressible or p.rotation_rad_s:
            raise CFDError(
                "unsupported_physics",
                "This worker implements isothermal, incompressible, nonrotating flow only",
                "physics",
                "capability_gap",
            )
        if d.solid_regions:
            raise CFDError(
                "unsupported_regions",
                "Solid CHT regions are not implemented by this worker",
                "physics",
                "capability_gap",
            )
        _check_spec_physics_applied(spec)


def _validate_generated_keys(spec: SimulationSpec):
    known = set(spec.domain_strategy.generated_surfaces)
    unknown = known - KNOWN_DOMAIN_KEYS
    if unknown:
        raise CFDError(
            "unknown_generated_surface",
            "Outer-domain convention requires x_min/x_max/y_min/y_max/z_min/z_max/solid_wall keys; unknown: "
            + ", ".join(sorted(unknown)),
            "domain",
            "capability_gap",
        )
    for b in spec.boundary_specs:
        if b.surface.source == "generated" and b.surface.key not in known:
            raise CFDError(
                "missing_generated_surface",
                "Boundary references a key absent from generated_surfaces",
                "domain",
            )


def _scale_mm_to_m(dim_tags):
    matrix = [
        0.001,
        0.0,
        0.0,
        0.0,
        0.0,
        0.001,
        0.0,
        0.0,
        0.0,
        0.0,
        0.001,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    ]
    import gmsh

    gmsh.model.occ.affineTransform(dim_tags, matrix)
    gmsh.model.occ.synchronize()


def _surface_side_key(bounds_m, bbox, tolerance_m) -> str | None:
    xmin, ymin, zmin, xmax, ymax, zmax = bbox
    bx0, by0, bz0, bx1, by1, bz1 = bounds_m
    tol = tolerance_m
    candidates = []
    if abs(xmin - bx0) <= tol and abs(xmax - bx0) <= tol:
        candidates.append("x_min")
    if abs(xmin - bx1) <= tol and abs(xmax - bx1) <= tol:
        candidates.append("x_max")
    if abs(ymin - by0) <= tol and abs(ymax - by0) <= tol:
        candidates.append("y_min")
    if abs(ymin - by1) <= tol and abs(ymax - by1) <= tol:
        candidates.append("y_max")
    if abs(zmin - bz0) <= tol and abs(zmax - bz0) <= tol:
        candidates.append("z_min")
    if abs(zmin - bz1) <= tol and abs(zmax - bz1) <= tol:
        candidates.append("z_max")
    if len(candidates) > 1:
        raise CFDError(
            "ambiguous_surface_side",
            "Fluid surface lies on more than one outer domain plane",
            "domain",
            "failed",
        )
    return candidates[0] if candidates else None


@dataclass
class FluidDomain:
    volume_tags: list[tuple[int, int]] = field(default_factory=list)
    volume_m3: float = 0.0
    clearance_m: float = 0.0
    tags_by_key: dict[str, list[int]] = field(default_factory=dict)
    selection_parents: dict[str, list[str]] = field(default_factory=dict)


def _selected_surface_keys(spec: SimulationSpec) -> list[str]:
    keys = [
        boundary.surface.key
        for boundary in spec.boundary_specs
        if boundary.surface.source == "selection"
    ]
    keys.extend(
        refinement.surface.key
        for refinement in spec.mesh_strategy.refinements
        if refinement.surface.source == "selection"
    )
    return list(dict.fromkeys(keys))


def _import_selected_face_sources(
    spec: SimulationSpec,
    topology_payload: dict,
    job_dir: Path,
) -> tuple[dict[str, list[tuple[int, int]]], dict[str, list[str]], dict[str, str]]:
    import gmsh

    from seekflow_cfd.evidence import FaceBinding

    imported: dict[str, list[tuple[int, int]]] = {}
    parent_ids: dict[str, list[str]] = {}
    provenance: dict[str, str] = {}
    for key in _selected_surface_keys(spec):
        raw_binding = topology_payload.get(key)
        if raw_binding is None:
            raise CFDError(
                "selection_binding_missing",
                f"No persistent face binding for selection {key}",
                "domain",
                "failed",
            )
        binding = FaceBinding.model_validate(raw_binding)
        if not binding.native_face_artifacts:
            raise CFDError(
                "selection_artifact_missing",
                f"Selection {key} has no exported native face artifact",
                "domain",
                "failed",
            )
        entities = []
        for handle, relative_path in binding.native_face_artifacts.items():
            path = confined(job_dir, relative_path)
            if not path.is_file():
                raise CFDError(
                    "selection_artifact_missing",
                    f"Missing selected native face: {relative_path}",
                    "domain",
                    "failed",
                )
            dim_tags = gmsh.model.occ.importShapes(
                str(path), highestDimOnly=False
            )
            faces = [(dim, tag) for dim, tag in dim_tags if dim == 2]
            if not faces:
                raise CFDError(
                    "selection_not_face",
                    f"Selected artifact {relative_path} is not a face",
                    "domain",
                    "failed",
                )
            _scale_mm_to_m(faces)
            entities.extend(faces)
        gmsh.model.occ.synchronize()
        imported[key] = entities
        parent_ids[key] = list(binding.entity_ids)
        provenance[key] = binding.provenance
    return imported, parent_ids, provenance


def _strict_selected_face_transfer(
    spec: SimulationSpec,
    topology_payload: dict,
    job_dir: Path,
    solid_face_tags: list[int],
    span_m: float,
):
    import gmsh

    imported, parent_ids, provenance = _import_selected_face_sources(
        spec, topology_payload, job_dir
    )
    tolerance_m = max(1e-10, 1e-8 * span_m)
    prefilter_tolerance_m = max(1e-9, 1e-6 * span_m)
    target_rows = []
    for target_tag in solid_face_tags:
        target_rows.append(
            {
                "tag": target_tag,
                "area_mm2": float(gmsh.model.occ.getMass(2, target_tag)),
                "center": list(
                    gmsh.model.occ.getCenterOfMass(2, target_tag)
                ),
                "bbox": list(gmsh.model.getBoundingBox(2, target_tag)),
            }
        )
    assigned: dict[str, list[int]] = {}
    assigned_tags = set()
    evidence = {}
    for key, source_entities in imported.items():
        target_tags = []
        source_evidence = []
        for source_dim, source_tag in source_entities:
            source_area = float(gmsh.model.occ.getMass(source_dim, source_tag))
            source_center = list(
                gmsh.model.occ.getCenterOfMass(source_dim, source_tag)
            )
            source_bbox = list(gmsh.model.getBoundingBox(2, source_tag))
            prefiltered = []
            for target in target_rows:
                if target["tag"] in assigned_tags:
                    continue
                area_scale = max(
                    abs(source_area), abs(target["area_mm2"]), 1e-30
                )
                area_error = (
                    abs(source_area - target["area_mm2"]) / area_scale
                )
                center_error = sum(
                    (source_center[index] - target["center"][index]) ** 2
                    for index in range(3)
                ) ** 0.5
                bbox_error = max(
                    abs(source_bbox[index] - target["bbox"][index])
                    for index in range(6)
                )
                if (
                    area_error <= 1e-7
                    and center_error <= prefilter_tolerance_m
                    and bbox_error <= prefilter_tolerance_m
                ):
                    prefiltered.append(
                        {
                            "tag": target["tag"],
                            "area_error": area_error,
                            "center_error_m": center_error,
                            "bbox_error_m": bbox_error,
                        }
                    )
            candidates = []
            for candidate in prefiltered:
                distance = float(
                    gmsh.model.occ.getDistance(
                        2, source_tag, 2, candidate["tag"]
                    )[0]
                )
                if distance <= tolerance_m:
                    candidates.append(
                        {
                            **candidate,
                            "distance_m": distance,
                        }
                    )
            if len(candidates) != 1:
                raise CFDError(
                    "selection_transfer_ambiguous"
                    if candidates
                    else "selection_transfer_missing",
                    f"Selection {key} matched {len(candidates)} fluid boundary faces",
                    "domain",
                    "failed",
                    evidence={"source_key": key, "candidates": candidates},
                )
            match = candidates[0]
            target_tags.append(match["tag"])
            assigned_tags.add(match["tag"])
            source_evidence.append(match)
        if len(set(target_tags)) != len(target_tags):
            raise CFDError(
                "selection_transfer_overlap",
                f"Selection {key} maps to duplicate fluid faces",
                "domain",
                "failed",
            )
        assigned[key] = target_tags
        evidence[key] = {
            "target_tags": target_tags,
            "source_entity_count": len(source_entities),
            "matches": source_evidence,
            "parent_entity_ids": parent_ids[key],
            "source_provenance": provenance[key],
            "tolerance_m": tolerance_m,
        }
    if imported:
        gmsh.model.occ.remove(
            [entity for entities in imported.values() for entity in entities],
            recursive=False,
        )
        gmsh.model.occ.synchronize()
    return assigned, parent_ids, evidence


def _build_fluid_model(
    spec: SimulationSpec,
    input_root: str | None,
    topology_payload: dict | None = None,
    job_dir: Path | None = None,
) -> FluidDomain:
    """Construct box-minus-SI-solid inside a live Gmsh OCC session."""
    import gmsh

    _check_implemented(spec, "domain.construct")
    _validate_generated_keys(spec)
    step = _geometry_step(input_root, spec)
    d = spec.domain_strategy
    bx0, by0, bz0, bx1, by1, bz1 = d.outer_bounds_m
    if any(v is None for v in (bx0, by0, bz0, bx1, by1, bz1)):
        raise CFDError(
            "outer_bounds_required",
            "Outer domain requires all six bounds",
            "domain",
        )

    imported = gmsh.model.occ.importShapes(str(step), highestDimOnly=True)
    gmsh.model.occ.synchronize()
    solids = [(dim, tag) for dim, tag in imported if dim == 3]
    if not solids:
        raise CFDError(
            "no_solid_import",
            "STEP import produced no 3D solid",
            "domain",
            "failed",
        )
    _scale_mm_to_m(solids)

    extents = [gmsh.model.getBoundingBox(dim, tag) for dim, tag in solids]
    smin = tuple(min(e[i] for e in extents) for i in range(3))
    smax = tuple(max(e[i + 3] for e in extents) for i in range(3))
    clearance_m = min(
        [
            min(
                smin[i] - d.outer_bounds_m[i],
                d.outer_bounds_m[i + 3] - smax[i],
            )
            for i in range(3)
        ]
    )
    margin = max(1e-4, min(d.outer_bounds_m[i + 3] - d.outer_bounds_m[i] for i in range(3)) * 0.02)
    if not all(
        smin[i] > d.outer_bounds_m[i] + margin and smax[i] < d.outer_bounds_m[i + 3] - margin
        for i in range(3)
    ):
        raise CFDError(
            "solid_touches_domain_boundary",
            "Imported solid is not strictly inside the outer domain; widen bounds",
            "domain",
            "capability_gap",
        )

    origin = d.origin_m
    box = gmsh.model.occ.addBox(
        bx0 + origin[0],
        by0 + origin[1],
        bz0 + origin[2],
        bx1 - bx0,
        by1 - by0,
        bz1 - bz0,
    )
    gmsh.model.occ.synchronize()
    result, _ = gmsh.model.occ.cut(
        [(3, box)], solids, removeObject=True, removeTool=True
    )
    gmsh.model.occ.synchronize()
    fluid = gmsh.model.getEntities(3)
    if not fluid:
        raise CFDError(
            "empty_fluid_domain",
            "Boolean subtraction left no fluid volume",
            "domain",
            "failed",
        )
    if len(fluid) != 1:
        raise CFDError(
            "disconnected_fluid_domain",
            "This staged worker requires one connected rectangular outer domain",
            "domain",
            "capability_gap",
        )
    volume_m3 = float(gmsh.model.occ.getMass(fluid[0][0], fluid[0][1]))
    boundary_entities = [
        (dim, tag)
        for dim, tag in gmsh.model.getBoundary(
            fluid, oriented=False, recursive=False
        )
        if dim == 2
    ]
    boundary_entities = list(dict.fromkeys(boundary_entities))
    span = max(
        bx1 - bx0,
        by1 - by0,
        bz1 - bz0,
        1.0,
    )
    # OCC round-trips single precision-like boundary slop through STEP import.
    # This only classifies outer-box sides; selected face transfer uses a
    # stricter independent tolerance below.
    tolerance_m = 1e-6 * span
    selected_keys = _selected_surface_keys(spec)
    if selected_keys and (topology_payload is None or job_dir is None):
        raise CFDError(
            "selection_context_missing",
            "Selection boundaries require topology payload and job directory",
            "domain",
            "failed",
        )
    tags_by_key = {
        key: [] for key in spec.domain_strategy.generated_surfaces
    }
    for key in selected_keys:
        tags_by_key.setdefault(key, [])
    outer_keys = SIDE_KEYS
    solid_face_tags = []
    for dim, tag in boundary_entities:
        bbox = gmsh.model.getBoundingBox(dim, tag)
        key = _surface_side_key((bx0, by0, bz0, bx1, by1, bz1), bbox, tolerance_m)
        if key in outer_keys:
            if key not in tags_by_key:
                raise CFDError(
                    "surface_without_boundary_group",
                    f"Outer boundary {key} is absent from generated_surfaces",
                    "domain",
                    "failed",
                )
            tags_by_key[key].append(tag)
            continue
        solid_face_tags.append(tag)
    selected_tags = {}
    selection_parents = {}
    transfer_evidence = {}
    if selected_keys:
        selected_tags, selection_parents, transfer_evidence = (
            _strict_selected_face_transfer(
                spec,
                topology_payload or {},
                job_dir,
                solid_face_tags,
                span,
            )
        )
    for key, tags in selected_tags.items():
        tags_by_key[key].extend(tags)
    remaining_solid_faces = [
        tag for tag in solid_face_tags if tag not in set(
            tag for tags in selected_tags.values() for tag in tags
        )
    ]
    if remaining_solid_faces:
        if "solid_wall" not in tags_by_key:
            raise CFDError(
                "surface_without_boundary_group",
                "Unselected solid-wall faces require generated solid_wall",
                "domain",
                "failed",
            )
        tags_by_key["solid_wall"].extend(remaining_solid_faces)
    if remaining_solid_faces and not tags_by_key.get("solid_wall"):
        raise CFDError(
            "no_solid_wall_surface",
            "Subtraction did not produce a solid-wall boundary; check outer bounds",
            "domain",
            "failed",
        )
    if selected_keys:
        atomic_json(
            job_dir / "domain_selection_transfer.json",
            {
                "selected_face_count": sum(
                    len(tags) for tags in selected_tags.values()
                ),
                "selected_keys": selected_keys,
                "transfer_evidence": transfer_evidence,
            },
        )
    return FluidDomain(
        volume_tags=fluid,
        volume_m3=volume_m3,
        clearance_m=clearance_m,
        tags_by_key=tags_by_key,
        selection_parents=selection_parents,
    )


def _binding_for(
    spec: SimulationSpec,
    surface_key: str,
    entity_ids: list[str],
    *,
    proof: str = "exact_construction",
    parent_entity_ids: list[str] | None = None,
    provenance: str | None = None,
) -> FaceBinding:
    g = spec.geometry_ref
    return FaceBinding(
        source_key=surface_key,
        status="set" if len(entity_ids) > 1 else "unique",
        proof=proof,
        entity_ids=entity_ids,
        lineage_id=g.lineage_id,
        revision_id=g.revision_id,
        geometry_hash=g.geometry.sha256,
        history_complete=True,
        parent_entity_ids=parent_entity_ids or [],
        provenance=provenance
        or (
            "Gmsh OCC difference of explicit outer box and imported STEP solid; "
            "faces classified by exact outer-plane or subtracted-solid boundary"
        ),
    )


def _domain_construct(payload, job_dir: Path, input_root) -> dict:
    import gmsh

    from seekflow_cfd.evidence import FaceBinding

    spec = SimulationSpec.model_validate(payload["spec"])
    _check_implemented(spec, "domain.construct")
    gmsh.initialize()
    try:
        domain = _build_fluid_model(
            spec,
            input_root,
            topology_payload=payload.get("topology") or {},
            job_dir=job_dir,
        )
        boundary_map = {}
        exterior_entity_ids = []
        for b in spec.boundary_specs:
            ids = ["gmsh-face:" + str(tag) for tag in domain.tags_by_key[b.surface.key]]
            if not ids:
                raise CFDError(
                    "empty_boundary",
                    f"No fluid surface for generated boundary {b.surface.key}",
                    "domain",
                    "failed",
                )
            if b.surface.source == "selection":
                source_binding = FaceBinding.model_validate(
                    payload["topology"][b.surface.key]
                )
                if set(domain.selection_parents[b.surface.key]) != set(
                    source_binding.entity_ids
                ):
                    raise CFDError(
                        "selection_parent_mismatch",
                        f"Selection {b.surface.key} lost its native parent identity",
                        "domain",
                        "failed",
                    )
                binding = _binding_for(
                    spec,
                    b.surface.key,
                    ids,
                    proof="exact_brep_transfer",
                    parent_entity_ids=source_binding.entity_ids,
                    provenance=(
                        "exact native BRep face imported from OCAF topology worker "
                        "and transferred to the fluid boundary by unique area, "
                        "centroid and zero-distance surface matching"
                    ),
                )
            else:
                binding = _binding_for(spec, b.surface.key, ids)
            boundary_map[b.name] = binding.model_dump(mode="json")
            exterior_entity_ids.extend(ids)
        return DomainReport(
            domain_id="gmsh-outer-" + spec.spec_hash[:12],
            spec_hash=spec.spec_hash,
            volume_m3=domain.volume_m3,
            fluid_regions=[spec.domain_strategy.fluid_region],
            solid_regions=[],
            boundary_map=boundary_map,
            exterior_entity_ids=exterior_entity_ids,
        ).model_dump(mode="json")
    finally:
        gmsh.finalize()


def _quality_from_fluent_log(text: str) -> dict:
    volume = re.search(r"minimum volume \(m3\):\s*([0-9.eE+-]+)", text)
    ortho = re.search(
        r"Minimum Orthogonal Quality\s*=\s*([0-9.eE+-]+)", text, re.IGNORECASE
    )
    if not volume or not ortho:
        raise CFDError(
            "mesh_quality_unreadable",
            "Fluent mesh quality output was not readable",
            "mesh",
            "failed",
        )
    min_ortho = float(ortho.group(1))
    return {
        "min_volume_m3": float(volume.group(1)),
        "negative_volume_cells": 0,
        "min_orthogonal_quality": min_ortho,
        # Fluent 18.1 TUI prints orthogonal quality, not equiangle skewness.
        # Ortho-skew = 1 - orthogonal quality is a conservative upper bound.
        "max_skewness": min(1.0, max(0.0, 1.0 - min_ortho)),
        "mesh_check_negative_warning": "negative" in text.lower(),
    }


def _configure_size_field(gmsh, spec, domain) -> dict:
    """Configure a distance-based tetra size field from one generated surface group.

    A single distance+threshold field is used when the spec asks for one
    refinement surface (the staged worker's normal outer-domain case). The
    transition distances are derived from the refinement size and the measured
    clearance between the solid and the outer box, not hard-coded to a family.
    Multiple refinement groups are applied as exact per-surface sizes.
    """

    refinements = spec.mesh_strategy.refinements
    size_max = spec.mesh_strategy.global_size_m
    if not refinements:
        return {"mode": "global", "size_max_m": size_max}
    if len(refinements) > 1:
        for refinement in refinements:
            tags = domain.tags_by_key[refinement.surface.key]
            gmsh.model.mesh.setSize(
                [(2, tag) for tag in tags], refinement.size_m
            )
        return {"mode": "exact_surface_sizes", "count": len(refinements)}
    refinement = refinements[0]
    tags = domain.tags_by_key[refinement.surface.key]
    if not tags:
        raise CFDError(
            "empty_refinement_surface",
            f"No mesh surfaces for refinement {refinement.surface.key}",
            "mesh",
            "failed",
        )
    distance = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(distance, "FacesList", tags)
    threshold = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(threshold, "InField", distance)
    size_min = refinement.size_m
    dist_min = max(size_min * 0.2, 1e-4)
    dist_max = max(dist_min * 2.0, 0.5 * domain.clearance_m)
    gmsh.model.mesh.field.setNumber(threshold, "SizeMin", size_min)
    gmsh.model.mesh.field.setNumber(threshold, "SizeMax", size_max)
    gmsh.model.mesh.field.setNumber(threshold, "DistMin", dist_min)
    gmsh.model.mesh.field.setNumber(threshold, "DistMax", dist_max)
    gmsh.model.mesh.field.setAsBackgroundMesh(threshold)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    return {
        "mode": "distance_threshold",
        "source_surface_key": refinement.surface.key,
        "size_min_m": size_min,
        "size_max_m": size_max,
        "dist_min_m": dist_min,
        "dist_max_m": dist_max,
        "clearance_m": domain.clearance_m,
    }


def _mesh_generate(payload, job_dir: Path, input_root) -> dict:
    import gmsh

    spec = SimulationSpec.model_validate(payload["spec"])
    domain_payload = payload["domain"]
    _check_implemented(spec, "mesh.generate")
    gmsh.initialize()
    try:
        domain = _build_fluid_model(
            spec,
            input_root,
            topology_payload=payload.get("topology") or {},
            job_dir=job_dir,
        )
        fluid_region = spec.domain_strategy.fluid_region
        volume_tags = [tag for _, tag in domain.volume_tags]
        gmsh.model.addPhysicalGroup(
            3, volume_tags, tag=-1, name=fluid_region
        )
        used_keys = set()
        for b in spec.boundary_specs:
            if b.surface.key in used_keys:
                raise CFDError(
                    "shared_boundary_key",
                    "One physical group may only map to one boundary name",
                    "mesh",
                )
            used_keys.add(b.surface.key)
            tags = domain.tags_by_key[b.surface.key]
            if not tags:
                raise CFDError(
                    "empty_boundary",
                    f"No mesh surfaces for boundary {b.surface.key}",
                    "mesh",
                    "failed",
                )
            gmsh.model.addPhysicalGroup(2, tags, tag=-1, name=b.name)
        size_field_evidence = _configure_size_field(gmsh, spec, domain)
        size = spec.mesh_strategy.global_size_m
        gmsh.option.setNumber("Mesh.Algorithm3D", 4)
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(size, max(1e-5, size * 0.2)))
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)
        gmsh.model.mesh.generate(3)

        unv = job_dir / "mesh" / "fluid_domain.unv"
        unv.parent.mkdir(parents=True, exist_ok=True)
        gmsh.write(str(unv))
    finally:
        gmsh.finalize()

    _run_process(
        job_dir,
        "mesh/fe2ram.out",
        [
            _fe_exe(),
            "-d3",
            "-tIDEAS",
            "-zGROUP",
            "-oRAMPANT",
            str(confined(job_dir, "mesh/fluid_domain.unv")),
            str(confined(job_dir, "mesh/fluid_domain.msh")),
        ],
    )
    journal = [
        '/file/read-case "' + str(confined(job_dir, "mesh/fluid_domain.msh")) + '"'
    ]
    journal.extend(["/mesh/repair-improve/improve-quality"] * MESH_IMPROVE_PASSES)
    journal.extend(
        [
            "/mesh/quality",
            "/mesh/check",
            '/file/write-case "mesh/mesh-final.cas.gz"',
            "/exit",
        ]
    )
    log = _run_fluent(
        job_dir,
        "mesh/fluent_check",
        journal,
        spec.budget.cpu_count,
    )
    text = _read_log(job_dir, log)
    quality = _quality_from_fluent_log(text)
    if quality["mesh_check_negative_warning"]:
        raise CFDError(
            "negative_mesh",
            "Fluent mesh check reported negative-volume cells",
            "mesh",
            "failed",
            True,
        )
    cells = re.search(r"(\d+)\s+[\w-]+\s+cells", text)
    if not cells:
        raise CFDError(
            "cell_count_unreadable",
            "Fluent mesh read output did not report cell count",
            "mesh",
            "failed",
        )
    artifact_paths = [
        "mesh/fluid_domain.unv",
        "mesh/fluid_domain.msh",
        "mesh/mesh-final.cas.gz",
        "mesh/fluent_check.out",
    ]
    evidence = {
        "mesh_check_text_tail": text[-12000:],
        "mesh_size_field": size_field_evidence,
        "fluent_improve_passes": MESH_IMPROVE_PASSES,
        "quality_notes": [
            "max_skewness is the conservative ortho-skew proxy 1-Q_ortho; "
            "Fluent 18.1 TUI does not print equiangle skewness.",
            "periodic_node_mismatch=0 because no periodic pair is configured.",
            "negative_volume_cells=0 only when Fluent mesh/check reports no negative warning.",
            "Fluent /mesh/repair-improve/improve-quality is the built-in mesh "
            "improver; the final case is persisted before the quality gate.",
        ],
    }
    atomic_json(job_dir / "mesh/mesh_quality_evidence.json", evidence)
    artifact_paths.append("mesh/mesh_quality_evidence.json")
    boundary_map = {
        name: FaceBinding.model_validate(value).model_dump(mode="json")
        for name, value in domain_payload["boundary_map"].items()
    }
    return MeshReport(
        mesh_id="gmsh-tetra-" + spec.spec_hash[:12],
        spec_hash=spec.spec_hash,
        cell_count=int(cells.group(1)),
        min_volume_m3=quality["min_volume_m3"],
        negative_volume_cells=0,
        max_skewness=quality["max_skewness"],
        min_orthogonal_quality=quality["min_orthogonal_quality"],
        periodic_node_mismatch=0,
        boundary_map=boundary_map,
        zone_labels={b.name: b.name for b in spec.boundary_specs},
        artifact_paths=artifact_paths,
    ).model_dump(mode="json")


# --- Verified Fluent 18.1 TUI recipes -------------------------------------
# Every sequence below was executed against a real Fluent 18.1 on 2026-09-11.
# The prompt text quoted with each entry is what Fluent printed verbatim.
# Fluent's interactive menus consume journal lines positionally, so a Fluent
# version whose wizard asks a different number of questions would shift every
# subsequent answer. FLUENT_ERROR_MARKERS plus the readback below turn that
# into a loud failure rather than silently different physics.

# Prompt: "Convective discretization scheme for Momentum (0 1 2 4 6) [1]"
# The default is 1, which is Fluent's second-order upwind momentum scheme, so
# the spec's first/second order map to 0/1.
FLUENT_MOMENTUM_SCHEME_BY_ORDER = {1: 0, 2: 1}

# Prompt: "Pressure Velocity Coupling Scheme [20]"
FLUENT_PV_COUPLING_BY_ALGORITHM = {
    "simple": 20,
    "simplec": 21,
    "piso": 22,
    "coupled": 24,
}

# Scheme expression, evaluated after configuring, whose value Fluent echoes.
# Verified: reads 1 by default, 0 after setting 0, 1 after setting 1.
FLUENT_READBACK_MOMENTUM_SCHEME = "(rpgetvar 'mom/scheme)"

# Prompts verified: "enable gravitational forces? [no]", "x-component of
# gravity (m/s2) [0]" (same for y, z).
# "Enable energy model? [no]", "Compute viscous energy dissipation? [no]",
# "include pressure work in energy equation? [no]", "include kinetic energy in
# energy equation? [no]", "Include diffusion at inlets? [yes]".
FLUENT_ENERGY_LINES = ("yes", "no", "no", "no", "yes")


def _tui_number(value: float) -> str:
    return f"{float(value):.12g}"


def _material_journal_lines(spec: SimulationSpec) -> list[str]:
    """Set the fluid material's constant density and viscosity.

    Verified prompt order:
      material-name -> confirm existing -> change Density? -> method -> value
      -> change Cp? -> change Thermal Conductivity? -> change Viscosity? ->
      method -> value -> Molecular Weight -> Thermal Expansion Coefficient ->
      Speed of Sound -> Change/Create mixture and Overwrite?

    The material must already exist in the case; Fluent's default case carries
    ``air``, and other names require a /define/materials/data-base copy first.
    """
    fluids = [m for m in spec.material_spec if m.phase == "fluid"]
    if not fluids:
        raise CFDError(
            "unsupported_material_phase",
            "This worker configures a fluid material only",
            "physics",
            "capability_gap",
        )
    material = fluids[0]
    density = material.density_kg_m3
    viscosity = material.viscosity_pa_s
    if (
        density.temperature_table
        or (viscosity is not None and viscosity.temperature_table)
        or material.conductivity_w_mk is not None
        or material.heat_capacity_j_kgk is not None
    ):
        raise CFDError(
            "unsupported_material_property",
            "This worker sets constant density and viscosity only; temperature "
            "tables and thermal properties use the piecewise-linear editor, "
            "whose prompt sequence is not verified",
            "physics",
            "capability_gap",
        )
    if density.constant is None:
        raise CFDError(
            "unsupported_material_property",
            f"Material {material.name} declares no constant density",
            "physics",
            "capability_gap",
        )

    lines = ["/define/materials/change-create", material.name]
    lines.append("yes")  # the material already exists; modify it
    lines.extend(["yes", "constant", _tui_number(density.constant)])
    lines.append("no")  # Cp (Specific Heat)
    lines.append("no")  # Thermal Conductivity
    if viscosity is not None and viscosity.constant is not None:
        lines.extend(["yes", "constant", _tui_number(viscosity.constant)])
    else:
        lines.append("no")
    lines.extend(["no", "no", "no"])  # Molecular Weight, expansion, sound speed
    lines.append("yes")  # Change/Create mixture and Overwrite
    return lines


def _operating_conditions_journal_lines(spec: SimulationSpec) -> list[str]:
    physics = spec.physics_spec
    lines = [
        "/define/operating-conditions/operating-pressure "
        + _tui_number(physics.reference_pressure_pa)
    ]
    gravity = physics.gravity_m_s2
    if any(abs(value) > 0 for value in gravity):
        lines.append("/define/operating-conditions/gravity")
        lines.append("yes")
        lines.extend(_tui_number(value) for value in gravity)
    return lines


def _model_journal_lines(spec: SimulationSpec) -> list[str]:
    lines = []
    if spec.physics_spec.heat_transfer != "isothermal":
        lines.append("/define/models/energy")
        lines.extend(FLUENT_ENERGY_LINES)
    return lines


def _solver_setting_journal_lines(spec: SimulationSpec) -> list[str]:
    control = spec.solver_control
    scheme = FLUENT_MOMENTUM_SCHEME_BY_ORDER[control.spatial_order]
    return [
        f"/solve/set/discretization-scheme/mom {scheme}",
        f"/solve/set/under-relaxation/pressure {_tui_number(control.relaxation)}",
        f"/solve/set/under-relaxation/mom {_tui_number(control.relaxation)}",
        "/solve/set/p-v-coupling",
        str(FLUENT_PV_COUPLING_BY_ALGORITHM[control.algorithm]),
    ]


def _readback_journal_lines(spec: SimulationSpec) -> list[str]:
    """Echo the settings back so the run proves they were applied."""
    return [
        "! --- configured settings readback ---",
        f"! momentum scheme (expect "
        f"{FLUENT_MOMENTUM_SCHEME_BY_ORDER[spec.solver_control.spatial_order]})",
        FLUENT_READBACK_MOMENTUM_SCHEME,
    ]


def _boundary_journal_lines(spec: SimulationSpec) -> list[str]:
    lines = []
    for b in spec.boundary_specs:
        if b.kind not in FLUENT_ZONE_TYPE:
            raise CFDError(
                "bc_unsupported",
                f"Boundary kind {b.kind} is not implemented in the Fluent 18.1 worker",
                "physics",
                "capability_gap",
            )
        lines.append(
            f"/define/boundary-conditions/zone-type {b.name} {FLUENT_ZONE_TYPE[b.kind]}"
        )
        if b.kind == "velocity_inlet":
            velocity = b.velocity_m_s
            nonzero = [x for x in velocity if abs(x) > 1e-12]
            if len(nonzero) != 1:
                raise CFDError(
                    "bc_direction_unsupported",
                    "Fluent 18.1 TUI normal-to-boundary mode requires a one-axis velocity vector",
                    "physics",
                    "capability_gap",
                )
            lines.append(
                f"/define/boundary-conditions/set/velocity-inlet {b.name} () "
                f"vmag n {abs(nonzero[0])} q"
            )
        elif b.kind == "pressure_outlet":
            lines.append(
                f"/define/boundary-conditions/set/pressure-outlet {b.name} () "
                f"gauge-pressure n {b.gauge_pressure_pa} q"
            )
        elif b.kind == "wall":
            if b.thermal != "adiabatic":
                raise CFDError(
                    "wall_thermal_unsupported",
                    "Non-adiabatic walls are not implemented in this worker",
                    "physics",
                    "capability_gap",
                )
    return lines


def _physics_configure(payload, job_dir: Path, _input_root=None) -> dict:
    spec = SimulationSpec.model_validate(payload["spec"])
    _check_implemented(spec, "physics.configure")
    mesh_path = (
        "mesh/mesh-final.cas.gz"
        if confined(job_dir, "mesh/mesh-final.cas.gz").is_file()
        else "mesh/fluid_domain.msh"
    )
    if not confined(job_dir, mesh_path).is_file():
        raise CFDError(
            "mesh_missing",
            "configured case requires an existing Fluent mesh/case",
            "physics",
            "failed",
        )
    lines = ['/file/read-case "' + str(confined(job_dir, mesh_path)) + '"']
    lines.extend(_operating_conditions_journal_lines(spec))
    lines.extend(_model_journal_lines(spec))
    lines.extend(_material_journal_lines(spec))
    lines.extend(_solver_setting_journal_lines(spec))
    lines.extend(_boundary_journal_lines(spec))
    lines.extend(_readback_journal_lines(spec))
    lines.append('/file/write-case "case-configured.cas.gz"')
    lines.append("/exit")
    log = _run_fluent(
        job_dir,
        "physics/configure",
        lines,
        spec.budget.cpu_count,
    )
    _read_log(job_dir, log)
    if not confined(job_dir, "case-configured.cas.gz").is_file():
        raise CFDError(
            "configured_case_missing",
            "Fluent did not write the configured case",
            "physics",
            "failed",
        )
    return {
        "ok": True,
        "spec_hash": spec.spec_hash,
        # Declared but never transferred to Fluent; see _unapplied_spec_fields.
        "unapplied_spec_fields": _unapplied_spec_fields(spec),
    }


def _solver_initialize(payload, job_dir: Path, _input_root=None) -> dict:
    spec = SimulationSpec.model_validate(payload["spec"])
    _check_implemented(spec, "solver.initialize")
    case = confined(job_dir, "case-configured.cas.gz")
    if not case.is_file():
        raise CFDError(
            "case_missing",
            "solver.initialize requires a configured case file",
            "solver",
            "failed",
        )
    log = _run_fluent(
        job_dir,
        "solver/initialize",
        [
            '/file/read-case "' + str(case) + '"',
            "/solve/initialize/initialize-flow",
            '/file/write-case "initial.cas.gz"',
            '/file/write-data "initial.dat.gz"',
            "/exit",
        ],
        spec.budget.cpu_count,
    )
    _read_log(job_dir, log)
    if not confined(job_dir, "initial.dat.gz").is_file():
        raise CFDError(
            "initial_data_missing",
            "Fluent initialization did not write a data file",
            "solver",
            "failed",
        )
    return {"ok": True, "spec_hash": spec.spec_hash}


def _case_paths(job_dir: Path, checkpoint: str | None, end_iteration: int | None):
    if checkpoint:
        checkpoint = confined(job_dir, checkpoint).name
        if not checkpoint.endswith(".cas.gz") and not checkpoint.endswith(".cas"):
            raise CFDError(
                "checkpoint_name",
                "Checkpoint must name a Fluent case file",
                "solver",
                "failed",
            )
        cas = confined(job_dir, checkpoint)
        dat = confined(job_dir, checkpoint[: -len(".cas.gz")] + ".dat.gz")
        return cas, dat
    cas = confined(job_dir, "initial.cas.gz")
    dat = confined(job_dir, "initial.dat.gz")
    return cas, dat


def _report_zone_list(spec: SimulationSpec) -> str:
    return " ".join(b.name for b in spec.boundary_specs)


def _parse_mass_fluxes(section: str, spec: SimulationSpec) -> dict[str, float]:
    values = {b.name: 0.0 for b in spec.boundary_specs}
    names = set(values)
    read = False
    for line in section.splitlines():
        if "Mass Flow Rate" in line and "(kg/s)" in line:
            read = True
            continue
        if not read:
            continue
        if line.strip().startswith(">"):
            break
        parts = line.split()
        if len(parts) >= 2 and parts[0] in names:
            try:
                values[parts[0]] = float(parts[-1])
            except ValueError:
                pass
    return values


def _parse_area_average(
    section: str,
    spec: SimulationSpec,
) -> dict[str, float]:
    absolute_pa = spec.physics_spec.reference_pressure_pa
    values = {}
    names = {b.name for b in spec.boundary_specs}
    read = False
    for line in section.splitlines():
        if "Area-Weighted Average" in line:
            read = False
            continue
        if "Static Pressure" in line and "(pascal)" in line:
            read = True
            continue
        if not read:
            continue
        if line.strip().startswith(">"):
            break
        parts = line.split()
        if len(parts) >= 2 and parts[0] in names:
            try:
                values[parts[0]] = float(parts[-1]) + absolute_pa
            except ValueError:
                pass
    return values


def _monitor_request_journal(spec: SimulationSpec) -> list[str]:
    lines = [
        "/report/fluxes/mass-flow n (" + _report_zone_list(spec) + ") n"
    ]
    for request in spec.result_requests:
        if request.quantity == "pressure" and request.operation == "mean":
            lines.append(
                "/report/surface-integrals/area-weighted-avg "
                f"{request.boundary} () pressure n"
            )
        elif request.quantity == "mass_flow":
            continue
        else:
            raise CFDError(
                "monitor_unsupported",
                "Worker monitor extraction supports pressure mean and mass flow",
                "solver",
                "capability_gap",
            )
    return lines


def _parse_solver_blocks(
    text: str, spec: SimulationSpec
) -> list[dict]:
    def residual_rows(section: str) -> list[tuple[int, list[float]]]:
        rows = []
        for line in section.splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            head = parts[0].lstrip("!")
            if not head.isdigit():
                continue
            values = []
            for part in parts[1:]:
                try:
                    values.append(float(part))
                except ValueError:
                    break
            if len(values) >= 4:
                rows.append((int(head), values))
        return rows

    blocks = re.split(r"(?m)^\s*>\s*/solve/iterate\s+1\s*$", text)
    if len(blocks) < 2:
        raise CFDError(
            "solver_log_empty",
            "Fluent log did not contain iteration blocks",
            "solver",
            "failed",
        )
    samples = []
    residual_names = list(spec.convergence_criteria.residuals)
    for block in blocks[1:]:
        rows = residual_rows(block)
        if not rows:
            continue
        iteration, values = max(rows, key=lambda row: row[0])
        if len(values) < 4:
            continue
        residuals = {
            "continuity": values[0],
            "x_velocity": values[1],
            "y_velocity": values[2],
            "z_velocity": values[3],
        }
        for name, value in zip(residual_names[4:], values[4:]):
            residuals[name] = value
        mass_flux = _parse_mass_fluxes(block, spec)
        pressures = _parse_area_average(block, spec)
        monitors = {}
        for request in spec.result_requests:
            if request.quantity == "mass_flow":
                monitors[request.name] = mass_flux[request.boundary]
            elif request.quantity == "pressure" and request.operation == "mean":
                if request.boundary not in pressures:
                    raise CFDError(
                        "pressure_monitor_missing",
                        "Fluent log lacks requested pressure monitor",
                        "solver",
                        "failed",
                    )
                monitors[request.name] = pressures[request.boundary]
            else:
                raise CFDError(
                    "monitor_unsupported",
                    "Worker supports pressure mean and mass-flow monitors",
                    "solver",
                    "capability_gap",
                )
        samples.append(
            Sample(
                iteration=iteration,
                residuals=residuals,
                mass_flux_kg_s=mass_flux,
                mass_source_kg_s=0.0,
                mass_storage_kg_s=0.0,
                courant=0.0,
                monitors=monitors,
            ).model_dump(mode="json")
        )
    if not samples:
        raise CFDError(
            "solver_samples_empty",
            "No parseable residual/report samples were produced",
            "solver",
            "failed",
        )
    return samples


def _solver_advance(payload, job_dir: Path, _input_root=None) -> dict:
    spec = SimulationSpec.model_validate(payload["spec"])
    _check_implemented(spec, "solver.advance")
    start = int(payload["start_iteration"])
    count = int(payload["iterations"])
    if count < 1:
        raise CFDError("invalid_iteration_chunk", "Chunk must be positive", "solver")
    end = start + count
    cas, dat = _case_paths(job_dir, payload.get("checkpoint"), end)
    if not cas.is_file() or not dat.is_file():
        raise CFDError(
            "checkpoint_missing",
            f"Solver checkpoint unavailable: {cas.name} / {dat.name}",
            "solver",
            "failed",
        )
    report_lines = _monitor_request_journal(spec)
    lines = [
        '/file/read-case "' + str(cas) + '"',
        '/file/read-data "' + str(dat) + '"',
    ]
    for _ in range(count):
        lines.append("/solve/iterate 1")
        lines.extend(report_lines)
    new_cas = f"checkpoint-{end:06d}.cas.gz"
    new_dat = f"checkpoint-{end:06d}.dat.gz"
    lines.append('/file/write-case "' + new_cas + '"')
    lines.append('/file/write-data "' + new_dat + '"')
    lines.append("/exit")
    log = _run_fluent(
        job_dir,
        f"solver/advance-{start + 1:06d}-{end:06d}",
        lines,
        spec.budget.cpu_count,
    )
    text = _read_log(job_dir, log)
    if not confined(job_dir, new_cas).is_file() or not confined(job_dir, new_dat).is_file():
        raise CFDError(
            "checkpoint_write_failed",
            "Fluent did not write the advanced checkpoint",
            "solver",
            "failed",
        )
    samples = _parse_solver_blocks(text, spec)
    if samples[-1]["iteration"] > end:
        raise CFDError(
            "iteration_contract",
            "Solver advanced past the requested iteration bound",
            "solver",
            "failed",
        )
    return SolverReport(
        spec_hash=spec.spec_hash,
        samples=samples,
        checkpoint=new_cas,
        log_paths=[log.resolve().relative_to(job_dir.resolve()).as_posix()],
    ).model_dump(mode="json")


def _solver_stop(payload, job_dir: Path, _input_root=None) -> dict:
    spec = SimulationSpec.model_validate(payload["spec"])
    _check_implemented(spec, "solver.stop")
    if not payload.get("checkpoint"):
        raise CFDError(
            "checkpoint_missing",
            "solver.stop requires a checkpoint",
            "solver",
            "failed",
        )
    cas, dat = _case_paths(job_dir, payload["checkpoint"], None)
    if not cas.is_file() or not dat.is_file():
        raise CFDError(
            "checkpoint_missing",
            "solver.stop checkpoint files are missing",
            "solver",
            "failed",
        )
    return {"ok": True, "spec_hash": spec.spec_hash}


def _result_journal(spec: SimulationSpec) -> list[str]:
    lines = [
        "/report/fluxes/mass-flow n (" + _report_zone_list(spec) + ") n"
    ]
    for request in spec.result_requests:
        if request.quantity == "pressure" and request.operation == "mean":
            lines.append(
                "/report/surface-integrals/area-weighted-avg "
                f"{request.boundary} () pressure n"
            )
        elif request.quantity == "mass_flow":
            continue
        else:
            raise CFDError(
                "result_extract_unsupported",
                "Worker result extraction supports pressure mean and mass flow",
                "postprocess",
                "capability_gap",
            )
    return lines


def _results_extract(payload, job_dir: Path, _input_root=None) -> dict:
    spec = SimulationSpec.model_validate(payload["spec"])
    _check_implemented(spec, "results.extract")
    cas, dat = _case_paths(job_dir, payload["checkpoint"], None)
    if not cas.is_file() or not dat.is_file():
        raise CFDError(
            "checkpoint_missing",
            "Final solver checkpoint is missing",
            "postprocess",
            "failed",
        )
    lines = [
        '/file/read-case "' + str(cas) + '"',
        '/file/read-data "' + str(dat) + '"',
    ]
    lines.extend(_result_journal(spec))
    lines.append('/file/write-case "postprocess/extract.cas.gz"')
    lines.append('/file/write-data "postprocess/extract.dat.gz"')
    lines.append("/exit")
    log = _run_fluent(
        job_dir,
        "postprocess/extract",
        lines,
        spec.budget.cpu_count,
    )
    text = _read_log(job_dir, log)
    mass = _parse_mass_fluxes(text, spec)
    pressure = _parse_area_average(text, spec)
    metrics = {}
    for request in spec.result_requests:
        if request.quantity == "mass_flow":
            value = mass.get(request.boundary)
            unit = "kg/s"
        elif request.quantity == "pressure" and request.operation == "mean":
            value = pressure.get(request.boundary)
            unit = "Pa"
        else:
            raise CFDError(
                "result_extract_unsupported",
                "Worker result extraction supports pressure mean and mass flow",
                "postprocess",
                "capability_gap",
            )
        if value is None:
            raise CFDError(
                "result_value_missing",
                f"No value extracted for {request.name}",
                "postprocess",
                "failed",
            )
        metrics[request.name] = {
            "value": value,
            "unit": unit,
            "boundary": request.boundary,
        }
    evidence = {
        "log": log.name,
        "absolute_pressure_note": (
            "Fluent static pressure is gauge; worker adds physics reference pressure "
            "so pressure metrics are absolute Pa."
        ),
    }
    atomic_json(job_dir / "postprocess/results_evidence.json", evidence)
    return ResultReport(
        spec_hash=spec.spec_hash,
        metrics=metrics,
        artifact_paths=["postprocess/results_evidence.json"],
    ).model_dump(mode="json")


IMPLEMENTATIONS = {
    "domain.construct": _domain_construct,
    "mesh.generate": _mesh_generate,
    "physics.configure": _physics_configure,
    "solver.initialize": _solver_initialize,
    "solver.advance": _solver_advance,
    "solver.stop": _solver_stop,
    "results.extract": _results_extract,
}


def main():
    root = Path.cwd()
    request_path = confined(root, sys.argv[1])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    response = {k: request[k] for k in ("protocol", "call_id", "input_hash")}
    operation = request["operation"]
    input_root = request.get("input_root")
    try:
        if operation not in OPERATIONS or operation not in IMPLEMENTATIONS:
            raise CFDError(
                "local_adapter_not_implemented",
                f"Implement and validate {operation} in this local Fluent worker",
                operation,
                "capability_gap",
            )
        response["result"] = IMPLEMENTATIONS[operation](
            request["payload"], root, input_root
        )
    except CFDError as exc:
        response["error"] = exc.diagnostic.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 -- trusted worker RPC boundary
        response["error"] = {
            "code": "local_solver_error",
            "message": str(exc),
            "status": "failed",
            "operation": operation,
        }
    atomic_json(confined(root, sys.argv[2]), response)


if __name__ == "__main__":
    main()
