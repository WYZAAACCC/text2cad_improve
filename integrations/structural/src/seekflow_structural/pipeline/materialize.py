"""Turn the case into the deck inputs, and stop guessing where things are.

Two things used to be read from files that did not have to agree with anything:
the sector angle and the bore radius came from a mesh config, while the domain
agent had decided the sector somewhere else entirely, and the part's real
thickness came from neither. One of those disagreements truncated 4 mm of rim
off D27 without a word.

Everything downstream of the case now derives from the case. A mesh config is
built here rather than read, and the geometry block in it is written from
`case.domain` and `case.model` - so a config file cannot hold a stale sector
angle, because there is no config file to hold one.
"""
from __future__ import annotations

import json
from pathlib import Path

from seekflow_structural.case.model import Case, MeshPlan, SolveRecord, Written
from seekflow_structural.core.structural_apdl import (
    materialize_intent,
    render_apdl,
)
from seekflow_structural.core.structural_intent_models import StructuralIntent
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.orchestrator import RunContext
from seekflow_structural.tools.frames import normalise_mesh

MESH_DIR = "mesh"
SOLVE_DIR = "solve"
MESH_FILE = "mesh.inp"

# A selected load surface is the denominator of the pressure. If the mesh
# reaches none of a selected face, the solver receives a higher pressure and a
# load path the engineer did not choose. A sector or half-thickness model can
# legitimately map slightly less CAD area as the idealisation clips the faces;
# the floor catches a missing repeated sector while permitting that measured
# model-area effect.
LOAD_SURFACE_MIN_COVERAGE = 0.95


def mesh_path(ctx: RunContext) -> Path:
    return ctx.path / MESH_DIR / MESH_FILE


def load_surface_coverage(selection_path: Path, case: Case) -> dict:
    """How much of the declared load surface actually reached the mesh.

    `selected_face_nodes.json` carries every selected face, including the
    zero-node rows the mapper could not place. Counting the row areas rather
    than the rows with nodes is what hid a 30% load coverage on D27. This
    measurement therefore counts area only on faces that mapped at least one
    node, and compares it with the area the selection declared.
    """
    payload = json.loads(Path(selection_path).read_text(encoding="utf-8"))
    per_face = payload.get("per_face") or {}
    selected = [
        int(value) for value in (case.load_surface.face_indices
                                 if case.load_surface else [])
    ]
    mapped: list[int] = []
    mapped_area = 0.0
    for key, row in per_face.items():
        try:
            face_index = int(key)
            node_count = int(row.get("node_count") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if node_count <= 0:
            continue
        mapped.append(face_index)
        mapped_area += float(row.get("area_mm2") or 0.0)
    missing = sorted(set(selected) - set(mapped))
    declared_area = float(
        case.load_surface.area_mm2_total if case.load_surface else 0.0
    )
    coverage = mapped_area / declared_area if declared_area > 0 else None
    complete = bool(
        selected and not missing and coverage is not None
        and coverage >= LOAD_SURFACE_MIN_COVERAGE
    )
    return {
        "selected_face_count": len(selected),
        "mapped_face_count": len(mapped),
        "missing_face_count": len(missing),
        "missing_face_indices": missing[:12],
        "declared_area_mm2": round(declared_area, 6),
        "mapped_area_mm2": round(mapped_area, 6),
        "area_coverage_fraction": (
            round(coverage, 6) if coverage is not None else None
        ),
        "minimum_coverage_fraction": LOAD_SURFACE_MIN_COVERAGE,
        "complete": complete,
    }


def deck_axis_for(case: Case):
    """The axis a deck written in the normalised frame must name.

    `None` means no override is needed because the source frame is already the
    deck frame. `(0, 0, 1)` is not a guess: it is the post-normalisation axis
    the mesher, face mapper, APDL writer and postprocessor all receive.
    """
    normalisation = normalisation_for(case)
    return None if normalisation.is_identity else (0.0, 0.0, 1.0)


def normalisation_for(case: Case):
    """The transform taking the part's axis onto the deck's +Z.

    A no-op for a part whose axis is already +Z through the origin, which is
    every part the chain has run so far - and that is deliberate, because a
    no-op means the change cannot alter a result that was already trusted.
    """
    from seekflow_structural.tools.frames import Normalisation

    model = case.model
    if model is None or model.frame is None:
        return Normalisation((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    frame = model.frame
    return Normalisation(
        frame.axis_origin_mm.as_tuple(), frame.axis_direction.as_tuple()
    )


def intent_from_case(
    case: Case, mesh_inp: Path, selection: Path, axis=None
) -> StructuralIntent:
    """Assemble the materialiser's input from the case.

    The physical values are the user's and are copied through unchanged; what
    is chosen here is only how they are expressed. `status` is carried over
    from the parameter file so the confirmation gate downstream still sees it.
    """
    physics = case.physics
    if physics is None:
        raise StructuralError(
            "case_incomplete", "materialize needs the physics group",
            "materialize",
        )

    temperature = dict(physics.temperature.payload)
    if not temperature:
        raise StructuralError(
            "case_incomplete",
            "the parameter file declares no temperature model",
            "materialize",
        )
    temperature.setdefault(
        "reference_temperature_c", physics.temperature.reference_temperature_c
    )
    temperature.setdefault("source", physics.temperature.source)

    # The rotation geometry is a list in the materialiser's schema and a
    # structured point in the case. The conversion happens here, once, at the
    # boundary - the alternative is two representations of the same axis
    # drifting apart, which is the failure this whole case object exists to
    # prevent.
    rotation = physics.rotation.model_dump(mode="json")
    for key in ("axis_origin_mm", "axis_direction"):
        value = rotation.get(key)
        if isinstance(value, dict):
            rotation[key] = [value["x"], value["y"], value["z"]]
    # A parameter file may state only a speed. `physics_from_params` says so in
    # as many words - "the axis may be given with the rotation or measured
    # later; absent means the parameter file did not say, which the frame
    # stage resolves" - and until now nothing resolved it: the rotation
    # reached the materialiser as `axis_origin_mm: None`, and the intent model
    # refused it. The frame stage has measured the axis from the model by this
    # point, and a rotation about the wrong axis is a different load case, so
    # the measured one is filled in rather than the pair being left empty.
    measured_frame = case.model.frame if case.model else None
    if axis is None and measured_frame is not None:
        if rotation.get("axis_origin_mm") is None:
            rotation["axis_origin_mm"] = list(
                measured_frame.axis_origin_mm.as_tuple()
            )
        if rotation.get("axis_direction") is None:
            rotation["axis_direction"] = list(
                measured_frame.axis_direction.as_tuple()
            )
    if rotation.get("axis_origin_mm") is None or rotation.get(
        "axis_direction"
    ) is None:
        raise StructuralError(
            "rotation_axis_unknown",
            "the parameter file states a rotation but no axis, and the model "
            "has no measured rotation axis to fall back on. A rotation about "
            "an unstated axis is not a case that can be solved.",
            "materialize",
        )
    if axis is not None:
        # The deck is written in the normalised frame, where the axis is +Z
        # through the origin by construction. The physical rotation - the
        # speed, the direction the material spins - is unchanged; only the
        # frame the deck describes it in is.
        rotation["axis_origin_mm"] = [0.0, 0.0, 0.0]
        rotation["axis_direction"] = list(axis)

    payload = {
        "status": getattr(case, "_status", None) or "ready_for_confirmation",
        "case_id": case.case_id,
        "bundle": case.bundle.path,
        "mesh_inp": str(mesh_inp),
        "selected_face_nodes": str(selection),
        "rotation": rotation,
        "temperature": temperature,
        "material": physics.material.model_dump(mode="json"),
        "blade_load": physics.blade_load.model_dump(mode="json"),
        "constraints": physics.constraints.model_dump(mode="json"),
    }
    # The core models carry `rationale`/`source` strings describing where a
    # value came from; the case already records that in `Written`, so the
    # per-section source strings are filled from the bindings rather than
    # invented here.
    for section in ("rotation", "material", "blade_load", "constraints"):
        payload[section].setdefault("rationale", "")
    return StructuralIntent.model_validate(payload)


def _has_axial_symmetry(model, domain) -> bool:
    """Whether the plane the domain chose is the one normal to the axis.

    The mid-plane is the plane whose normal runs along the rotation axis; a
    plane containing the axis has a normal perpendicular to it. The
    distinction is the difference between "mesh half the thickness because the
    other half is its mirror" and "mesh a wedge", and they are not
    interchangeable.
    """
    used = set(domain.symmetry_planes_used or [])
    if not used or model.frame is None:
        return False
    axis = model.frame.axis_direction.as_tuple()
    for plane in model.symmetry_planes:
        if plane.id not in used:
            continue
        normal = plane.normal.as_tuple()
        magnitude = sum(value * value for value in normal) ** 0.5
        if magnitude <= 0:
            continue
        alignment = abs(
            sum(normal[i] * axis[i] for i in range(3)) / magnitude
        )
        if alignment > 0.999:
            return True
    return False


def mesh_config_from_case(case: Case, mesh: MeshPlan | None) -> dict:
    """The mesher's config, with every geometric value derived from the case.

    The refinement block is the exception: until the meshing agent lands, the
    regions it describes are expressed in the same radial vocabulary the
    mesher already understands. When that agent lands this is where its
    described regions are compiled, and nothing else changes.
    """
    model = case.model
    domain = case.domain
    if model is None or domain is None:
        raise StructuralError(
            "case_incomplete",
            "a mesh config needs the model and domain groups",
            "materialize",
        )

    bounds_min = model.bounds_min_mm.as_tuple()
    bounds_max = model.bounds_max_mm.as_tuple()
    z_half = max(abs(bounds_min[2]), abs(bounds_max[2]))

    config = {
        # The mesher opens the STEP for geometry; the chain opens the XBF for
        # topology. Both are named, so a config cannot be pointed at the
        # geometry of one revision and the topology of another.
        "step_file": str(Path(case.bundle.path) / "model.step"),
        "geometry": {
            # Written from the case, never read from a file.
            "frame": {
                "axis_origin_mm": list(
                    model.frame.axis_origin_mm.as_tuple()
                    if model.frame else (0.0, 0.0, 0.0)
                ),
                "axis_direction_mm": list(
                    model.frame.axis_direction.as_tuple()
                    if model.frame else (0.0, 0.0, 1.0)
                ),
            },
            "sector_deg": 360.0 if domain.sector_deg is None
            else float(domain.sector_deg),
            "theta_low_deg": float(domain.theta_low_deg),
            # Whether the mid-plane is one of the planes the domain chose, not
            # merely whether it chose any. A plane containing the axis bounds
            # the sector's azimuth; only the mid-plane lets the mesher halve
            # the thickness, and reading the first as the second meshes half a
            # part that was never halved. Decided by the plane's normal rather
            # than by its id, so it follows the geometry the frame stage
            # measured rather than a naming convention.
            "z_symmetry": _has_axial_symmetry(model, domain),
            "r_bore_mm": float(model.bore_radius_mm or 0.0),
            "r_outer_mm": float(model.r_max_mm),
            "z_half_mm": float(z_half),
        },
        "mesh": {"size_max_mm": 12.0, "size_min_mm": 0.4, "curvature_pts": 12},
    }
    if mesh is not None:
        config["mesh"]["size_max_mm"] = float(mesh.web_size_mm or 12.0)
        sizes = [region.size_mm for region in mesh.regions]
        if sizes:
            config["mesh"]["size_min_mm"] = min([0.4] + sizes)
        config["mesh"]["refinement"] = {
            "web_size_mm": float(mesh.web_size_mm or 12.0),
            "zones": [
                {
                    "name": region.name,
                    "r_center_mm": (
                        (region.center_mm.as_tuple()[0] ** 2
                         + region.center_mm.as_tuple()[1] ** 2) ** 0.5
                        if region.center_mm is not None
                        else (region.radius_mm or 0.0)
                    ),
                    "size_mm": region.size_mm,
                    "ramp_mm": region.ramp_mm,
                }
                for region in mesh.regions
            ],
        }
    return config


def materialize(ctx: RunContext) -> Case:
    """Write the deck inputs for this case into the job's solve directory."""
    case = ctx.case
    if case is None:
        raise StructuralError("no_case", "no case to materialise", "materialize")

    mesh_inp = mesh_path(ctx)
    if not mesh_inp.is_file():
        raise StructuralError(
            "mesh_missing",
            f"{mesh_inp} does not exist; the meshing stage must run first",
            "materialize",
        )

    selection = ctx.path / SOLVE_DIR / "selected_face_nodes.json"
    if not selection.is_file():
        raise StructuralError(
            "selection_missing",
            f"{selection} does not exist; the faces must be mapped to mesh "
            "nodes before the deck can carry a load",
            "materialize",
        )
    coverage = load_surface_coverage(selection, case)
    if not coverage["complete"]:
        missing = coverage["missing_face_indices"]
        fraction = coverage["area_coverage_fraction"]
        shown = "unmeasurable" if fraction is None else f"{fraction:.2%}"
        raise StructuralError(
            "load_surface_not_materialised",
            "the mesh did not materialise the complete selected load surface: "
            f"{coverage['mapped_face_count']}/{coverage['selected_face_count']} "
            f"faces mapped, area coverage {shown}"
            + (f", missing face indices {missing}" if missing else "")
            + ". A partial surface would raise the pressure and change the "
              "load path, so the solve is refused rather than learnt from.",
            "materialize",
        )

    solve_dir = ctx.path / SOLVE_DIR
    solve_dir.mkdir(parents=True, exist_ok=True)
    config = mesh_config_from_case(case, case.mesh)

    # The deck's frame is the normalised one. For a part whose axis is already
    # +Z this is the identity and the mesh is passed through untouched - which
    # is what makes the change safe to add under work that already ran.
    normalisation = normalisation_for(case)
    frame_already_applied = bool(
        case.mesh and (case.mesh.measured or {}).get("frame_applied")
    )
    if normalisation.is_identity or frame_already_applied:
        deck_mesh = mesh_inp
    else:
        # Normalise the canonical mesh in place.  reads the
        # whole file before writing, so the source coordinates are not lost
        # while the rewrite is in progress. Keeping one canonical mesh path is
        # what lets the APDL deck and postprocessor read the same coordinates
        # without either of them guessing which normalised copy was used.
        deck_mesh = mesh_inp
        moved = normalise_mesh(mesh_inp, deck_mesh, normalisation)
        if not moved:
            raise StructuralError(
                "mesh_normalisation_failed",
                f"the frame is not the identity but no node in {mesh_inp} "
                "was moved; the mesh and the frame do not describe the same "
                "model",
                "materialize",
            )
        ctx.job.event({
            "kind": "mesh_normalised",
            "stage": "materialize",
            "nodes_moved": moved,
            "from_axis": list(
                case.model.frame.axis_direction.as_tuple()
                if case.model.frame else (0.0, 0.0, 1.0)
            ),
        })
    intent = intent_from_case(
        case, deck_mesh, selection, axis=deck_axis_for(case),
    )

    # Everything below this line must use the mesh the deck actually binds.
    # When the mesher has already applied the case frame, `deck_mesh` is the
    # original path; when this stage had to normalise it, `deck_mesh` is the
    # rewritten file. Passing `mesh_inp` here would silently bind the APDL
    # deck to the unnormalised coordinates while the intent described +Z.
    materialized = materialize_intent(
        intent, deck_mesh, selection, solve_dir, config
    )
    solve_inp = render_apdl(
        intent, deck_mesh, solve_dir, Path(materialized["load_table"]), config
    )

    ctx.record_call(
        "materialize",
        {
            "solve_inp": solve_inp.name,
            "load_table": Path(materialized["load_table"]).name,
            "mesh_config": config,
        },
    )
    ctx.job.event(
        {
            "kind": "deck_written",
            "stage": "materialize",
            "solve_inp": solve_inp.name,
            "sector_deg": config["geometry"]["sector_deg"],
            "theta_low_deg": config["geometry"]["theta_low_deg"],
        }
    )
    case.mesh = case.mesh or MeshPlan(
        written=Written(by_stage="materialize", kind="derived")
    )
    return case


def solve_record(case: Case, job_dir: Path, **fields) -> SolveRecord:
    return SolveRecord(
        job_dir=str(job_dir),
        written=Written(by_stage="solve", kind="measured"),
        **fields,
    )
