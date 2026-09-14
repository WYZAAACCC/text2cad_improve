"""Build a case from artifacts an earlier run already produced.

This exists for one reason: to prove the deterministic half of the chain -
materialise, solve, post-process - end to end before any agent is rebuilt on
top of it. It seeds the case from files an earlier run left behind, so the
numbers it produces can be compared against numbers that are already trusted.

It is a bootstrap, not a design. Each of its inputs is replaced, in turn, by
the stage that should really produce it:

  * `domain`      <- the domain agent          (increment 4)
  * `load_surface`<- the face-finding sub-agent (increment 2)
  * `physics`     <- the assembly agent        (increment 2)
  * `mesh`        <- the meshing agent         (increment 5)

Until then it is deliberately loud about where each group came from, so a
result produced this way cannot be mistaken for one the agents produced.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from seekflow_structural.case.model import (
    BundleRef,
    Case,
    ConstraintBinding,
    DomainDecision,
    Frame,
    LoadBinding,
    LoadSurface,
    MaterialBinding,
    MaterialPoint,
    MeshPlan,
    MeshRegion,
    ModelFacts,
    Physics,
    RotationBinding,
    TemperatureBinding,
    Vec3,
    Written,
)
from seekflow_structural.core.load_radius import measure as measure_load_radius
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.materialize import MESH_DIR, MESH_FILE


def _vec(values) -> Vec3:
    return Vec3(x=float(values[0]), y=float(values[1]), z=float(values[2]))


def _written(by_stage: str, source: str) -> Written:
    return Written(by_stage=by_stage, kind="measured", source=source)


def axial_extent_mm(mesh_inp: Path) -> tuple[float, float]:
    """The mesh's own z range, which is the one the deck will see."""
    lo = hi = None
    for line in mesh_inp.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        if not line.startswith("N,"):
            continue
        parts = line.strip().split(",")
        if len(parts) != 5:
            continue
        try:
            z = float(parts[4])
        except ValueError:
            continue
        lo = z if lo is None else min(lo, z)
        hi = z if hi is None else max(hi, z)
    if lo is None or hi is None:
        raise StructuralError(
            "empty_mesh", f"{mesh_inp} contains no nodes", "frame"
        )
    return lo, hi


def model_facts_from_profile(
    profile: dict, bundle: Path, mesh_inp: Path
) -> ModelFacts:
    """What the geometry is, measured rather than read from a config.

    `r_max_mm` comes from the profile's own sampling of the surface, and the
    axial extent from the mesh. Neither is a bounding-box corner: the corner
    of a symmetric box sits at radius*sqrt(2) and is nowhere near the material,
    and a config value is just a claim.
    """
    r_max = float(profile["r_max_mm"])
    r_min = float(profile.get("r_min_mm") or 0.0)
    z_lo, z_hi = axial_extent_mm(mesh_inp)
    return ModelFacts(
        bounds_min_mm=Vec3(x=-r_max, y=-r_max, z=z_lo),
        bounds_max_mm=Vec3(x=r_max, y=r_max, z=z_hi),
        r_max_mm=r_max,
        has_rotation_axis=True,
        frame=Frame(
            axis_origin_mm=Vec3(x=0.0, y=0.0, z=0.0),
            axis_direction=Vec3(x=0.0, y=0.0, z=1.0),
            measured_from=str(bundle),
        ),
        bore_radius_mm=r_min if r_min > 0 else None,
        face_count=int(profile.get("face_count") or 0),
        written=_written("frame", f"profile of {bundle.name}"),
    )


def domain_from_config(mesh_config: dict, source: str) -> DomainDecision:
    """The domain, taken from a config that an earlier run wrote.

    The config is only read here because nothing has decided the domain yet in
    this bootstrap path; once the domain agent lands, the config stops being
    an input and starts being an output.
    """
    geometry = mesh_config.get("geometry", {})
    sector = float(geometry.get("sector_deg", 360.0))
    return DomainDecision(
        sector_deg=None if sector >= 359.9 else sector,
        theta_low_deg=float(geometry.get("theta_low_deg", 0.0)),
        symmetry_planes_used=(
            ["z0"] if geometry.get("z_symmetry", True) else []
        ),
        evidence={"source": source},
        rationale=f"seeded from {source}",
        written=Written(
            by_stage="domain", kind="agent_decision", source=source
        ),
    )


def load_surface_from_selection(
    bundle: Path, face_intent: Path
) -> LoadSurface:
    """The selected faces, with the load radius measured - not supplied.

    The radius is measured here, by the same call the meshing stage will read
    from. That is the fix for the seam where a mesh was refined at 288 while
    the faces sat at 212.67: there is one measurement, and it lives in the
    case.
    """
    payload = json.loads(face_intent.read_text(encoding="utf-8"))
    final = payload.get("final") or {}
    if not final.get("accepted"):
        raise StructuralError(
            "selection_not_accepted",
            f"{face_intent} does not contain an accepted selection",
            "seed",
        )

    measured = measure_load_radius(bundle, face_intent)
    return LoadSurface(
        feature=str(final.get("feature", "")),
        solid_index=int(final.get("solid_index", 0)),
        face_indices=[int(v) for v in final.get("selected_face_indices", [])],
        area_mm2_total=float(measured.get("area_mm2_total") or 0.0),
        load_radius_mm=float(measured["load_radius_mm"]),
        radius_min_mm=float(measured["radius_min_mm"]),
        radius_max_mm=float(measured["radius_max_mm"]),
        written=_written("assembly", str(face_intent)),
    )


def physics_from_intent(intent_payload: dict, source: str) -> Physics:
    """Copy the user's physical values out of an earlier run's intent."""
    intent = intent_payload["final"]["intent"]
    temperature = dict(intent["temperature"])
    material = intent["material"]
    load = intent["blade_load"]
    rotation = intent["rotation"]
    constraints = intent["constraints"]

    return Physics(
        rotation=RotationBinding(
            rpm=float(rotation["rpm"]),
            axis_origin_mm=_vec(rotation["axis_origin_mm"]),
            axis_direction=_vec(rotation["axis_direction"]),
            source=str(rotation.get("source", "")),
        ),
        temperature=TemperatureBinding(
            model=str(temperature.get("model", "")),
            reference_temperature_c=float(
                temperature.get("reference_temperature_c", 20.0)
            ),
            payload=temperature,
            source=str(temperature.get("source", "")),
        ),
        material=MaterialBinding(
            name=str(material.get("name", "")),
            poisson_ratio=float(material["poisson_ratio"]),
            density_t_mm3=float(material["density_t_mm3"]),
            points=[MaterialPoint(**point) for point in material["points"]],
            source=str(material.get("source", "")),
        ),
        blade_load=LoadBinding(
            model=str(load.get("model", "")),
            total_force_n_per_slot=float(
                load.get("total_force_n_per_slot") or 0.0
            ),
            blades_per_slot=int(load.get("blades_per_slot", 1)),
            direction_rule=str(load.get("direction_rule", "")),
            distribution=str(load.get("distribution", "")),
            source=str(load.get("source", "")),
        ),
        constraints=ConstraintBinding(
            cyclic_symmetry=bool(constraints.get("cyclic_symmetry")),
            axial_symmetry_z0=bool(constraints.get("axial_symmetry_z0")),
            tangential_anchor=bool(constraints.get("tangential_anchor")),
            source=str(constraints.get("source", "")),
        ),
        written=Written(by_stage="assembly", kind="user_input", source=source),
    )


def mesh_plan_from_config(mesh_config: dict, source: str) -> MeshPlan:
    mesh = mesh_config.get("mesh", {})
    refinement = mesh.get("refinement") or {}
    regions = [
        MeshRegion(
            name=str(zone.get("name", "")),
            kind="cylinder",
            size_mm=float(zone["size_mm"]),
            ramp_mm=float(zone["ramp_mm"]),
            center_mm=Vec3(
                x=float(zone["r_center_mm"]), y=0.0, z=0.0
            ),
            rationale=f"seeded from {source}",
        )
        for zone in refinement.get("zones", [])
    ]
    return MeshPlan(
        regions=regions,
        web_size_mm=float(refinement.get("web_size_mm", mesh.get("size_max_mm", 12.0))),
        element_budget=150_000,
        written=Written(by_stage="mesh", kind="agent_decision", source=source),
    )


def install_mesh(ctx, mesh_inp: Path) -> Path:
    """Place an existing mesh where the chain expects to find it."""
    target_dir = ctx.path / MESH_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / MESH_FILE
    if mesh_inp.resolve() != target.resolve():
        shutil.copyfile(mesh_inp, target)
    return target


def build_case(
    *,
    bundle: Path,
    params: dict,
    profile: dict,
    mesh_config: dict,
    face_intent: Path,
    intent_payload: dict,
    mesh_inp: Path,
    mesh_config_source: str = "seed",
) -> Case:
    return Case(
        case_id=str(params.get("case_id") or bundle.name),
        bundle=BundleRef(
            path=str(bundle.resolve()),
            lineage_id=bundle.name,
            history_topology_hash="",
        ),
        model=model_facts_from_profile(profile, bundle, mesh_inp),
        domain=domain_from_config(mesh_config, mesh_config_source),
        load_surface=load_surface_from_selection(bundle, face_intent),
        physics=physics_from_intent(intent_payload, "seeded intent"),
        mesh=mesh_plan_from_config(mesh_config, mesh_config_source),
    )
