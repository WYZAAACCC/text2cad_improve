"""Run the chain from assembly onward, with the face selection supplied.

The face-finding agent is the one stage that cannot be made to produce a
selection on demand, so a break anywhere downstream of it is invisible: the
chain never gets there. This substitutes a selection measured from the model
and runs every stage after it for real - the meshing agent, the materialiser,
ANSYS, the post-processor and the verifier.

What it is for is finding out where the chain actually stops, which is a
different question from whether the faces are the right ones.

    python chain_downstream.py <job-id> [--radius-min MM] [--radius-max MM]

The selection is the planar tool faces of the final cut whose centroid radius
falls in the band, restricted to the sector the domain stage chose. Both are
arguments because the point is to run the stages, not to decide the faces.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import traceback

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))
sys.path.insert(0, str(REPO / "integrations" / "engineering_tools" / "src"))

from seekflow_structural.case.model import (                       # noqa: E402
    Case,
    LoadSurface,
    Vec3,
    Written,
)
from seekflow_structural.pipeline import params as params_module   # noqa: E402
from seekflow_structural.pipeline.orchestrator import (            # noqa: E402
    Budget,
    Orchestrator,
    RunContext,
)
from seekflow_structural.pipeline.stages import Stage              # noqa: E402
from seekflow_structural.runtime.store import JobStore             # noqa: E402
from seekflow_structural.tools import geometry                     # noqa: E402

SOURCE_JOB = "d27-chain"
OUTPUT = REPO / "_structural_experiment" / "output" / "structural"
PARAMS = REPO / "_structural_experiment" / "input" / "d27_chain_case.json"
DEFAULT_PARAMS = PARAMS


def _band(case: Case, low: float, high: float):
    """The planar tool faces in the radius band, inside the sector."""
    bundle = pathlib.Path(case.bundle.path)
    session = geometry.open_bundle(bundle)
    try:
        rows = geometry.face_rows(session, "n_final_cut", 0)
    finally:
        close = getattr(session, "close", None)
        if close is not None:
            close()

    theta_low = float(case.domain.theta_low_deg)
    theta_high = theta_low + float(case.domain.sector_deg)
    hits = []
    for index, row in enumerate(rows):
        if row.get("surface_type") != "plane":
            continue
        # `face_rows` on its own carries no provenance - that is added by the
        # agent's own row builder, which reads the evolution index. The band
        # already isolates the outer fir-tree, so the filter is used when it
        # is there and not required when it is not.
        operand = row.get("origin_operand")
        if operand is not None and operand != "tool":
            continue
        radius = (row.get("centroid_cyl_mm_deg") or [None])[0]
        theta = (row.get("centroid_cyl_mm_deg") or [None, None])[1]
        if radius is None or theta is None:
            continue
        if not (low <= radius <= high):
            continue
        if not (theta_low - 1e-9 <= theta <= theta_high + 1e-9):
            continue
        hits.append((index, row))
    return hits


# What the face-finding agent converges on for D27: the fir-tree flanks at
# r 280.7..295.4. Four separate runs that submitted at all submitted exactly
# this set, and the user confirmed it against the blade root. Taken from those
# runs rather than re-derived, so a failure downstream is a failure of the
# stages below assembly and not of a selection this probe made up.
KNOWN_GOOD = [
    3954, 3962, 3970, 3978, 3990, 3998, 4006, 4014, 4020, 4028, 4036, 4044,
    4056, 4064, 4072, 4080, 4086, 4094, 4102, 4110, 4122, 4130, 4138, 4146,
]


def _replay(case: Case, submission: pathlib.Path) -> LoadSurface:
    """A submission the face-finding agent actually made, handed on as it is.

    The payload is the agent's own `final` - the criterion it declared, the
    residuals against it, the indices and the measured radii - and it is
    turned into the case's load surface by the same function the chain uses.
    Nothing here reformats or re-derives anything, so what the stages below
    see is what they would have seen had the agent submitted this during a
    real run, down to the fields the agent left unset.
    """
    from seekflow_structural.agents import facefind

    payload = json.loads(submission.read_text(encoding="utf-8"))
    final = payload.get("final") or payload
    if not final.get("accepted"):
        raise SystemExit(f"{submission} holds no accepted submission")

    state = facefind.FaceFinderState(session=None, bundle=None)
    state.submitted = final
    surface = facefind.to_case_selection(state, pathlib.Path(case.bundle.path))
    print(
        f"replayed submission: {len(surface.face_indices)} faces, "
        f"r {surface.radius_min_mm:.2f}..{surface.radius_max_mm:.2f}, "
        f"area-weighted radius {surface.load_radius_mm:.4f}, "
        f"method {final.get('selection_method')}"
    )
    return surface


def _measure(case: Case, indices: list[int]) -> LoadSurface:
    """A selection described by the faces' own measured facts."""
    bundle = pathlib.Path(case.bundle.path)
    session = geometry.open_bundle(bundle)
    try:
        rows = geometry.face_rows(session, "n_final_cut", 0)
    finally:
        close = getattr(session, "close", None)
        if close is not None:
            close()

    picked = [rows[index] for index in indices]
    areas = [float(row.get("area_mm2") or 0.0) for row in picked]
    radii = [float(row["centroid_cyl_mm_deg"][0]) for row in picked]
    total = sum(areas) or 1.0
    weighted = sum(a * r for a, r in zip(areas, radii)) / total
    centroid = [0.0, 0.0, 0.0]
    for row, area in zip(picked, areas):
        point = row.get("centroid_mm") or [0.0, 0.0, 0.0]
        for axis in range(3):
            centroid[axis] += area * point[axis] / total
    print(
        f"selection: {len(picked)} faces, r {min(radii):.2f}..{max(radii):.2f}, "
        f"area-weighted radius {weighted:.4f}"
    )
    return LoadSurface(
        feature="n_final_cut",
        solid_index=0,
        face_indices=list(indices),
        area_mm2_total=total,
        load_radius_mm=weighted,
        radius_min_mm=min(radii),
        radius_max_mm=max(radii),
        centroid_mm=Vec3(x=centroid[0], y=centroid[1], z=centroid[2]),
        written=Written(by_stage="assembly", kind="agent_decision",
                        source="probe: faces measured from the model"),
    )


def _selection(case: Case, low: float, high: float) -> LoadSurface:
    hits = _band(case, low, high)
    if not hits:
        raise SystemExit(
            f"no planar tool faces between r={low} and r={high} in the sector"
        )
    areas = [float(row.get("area_mm2") or 0.0) for _, row in hits]
    radii = [float(row["centroid_cyl_mm_deg"][0]) for _, row in hits]
    total = sum(areas) or 1.0
    weighted = sum(
        a * r for a, r in zip(areas, radii)
    ) / total
    centroid = [0.0, 0.0, 0.0]
    for (_, row), area in zip(hits, areas):
        point = row.get("centroid_mm") or [0.0, 0.0, 0.0]
        for axis in range(3):
            centroid[axis] += area * point[axis] / total
    print(
        f"selection: {len(hits)} faces, r {min(radii):.2f}..{max(radii):.2f}, "
        f"area-weighted radius {weighted:.4f}"
    )
    print(f"           indices {[i for i, _ in hits]}")
    return LoadSurface(
        feature="n_final_cut",
        solid_index=0,
        face_indices=[i for i, _ in hits],
        area_mm2_total=total,
        load_radius_mm=weighted,
        radius_min_mm=min(radii),
        radius_max_mm=max(radii),
        centroid_mm=Vec3(x=centroid[0], y=centroid[1], z=centroid[2]),
        written=Written(by_stage="assembly", kind="agent_decision",
                        source="probe: faces measured from the model"),
    )


def main() -> int:
    # A stage that stalls leaves no trace of where it stalled - an earlier run
    # of this probe sat for half an hour in the meshing stage with an empty
    # directory and no way to tell whether it was working or blocked. This
    # dumps every thread's stack when nothing has happened for a long time.
    #
    # Long by default, and it must stay longer than a solve: the first version
    # of this was fifteen minutes, and it killed a run whose ANSYS solve was
    # still going - the analysis completed on its own a minute later, and the
    # chain never recorded it. The solve has its own budget of
    # `--max-ansys-wall-s`, and this watchdog must not be the shorter one.
    import faulthandler

    parser = argparse.ArgumentParser()
    parser.add_argument("job")
    parser.add_argument("--radius-min", type=float, default=270.0)
    parser.add_argument("--radius-max", type=float, default=300.0)
    parser.add_argument(
        "--faces", default=",".join(str(v) for v in KNOWN_GOOD),
        help=(
            "comma-separated face indices, or 'band' for every planar face in "
            "the radius band. The default is the set the face-finding agent "
            "converges on and the user confirmed; 'band' is the crude set that "
            "selects both flanks and so cancels."
        ),
    )
    parser.add_argument("--source-job", default=SOURCE_JOB)
    parser.add_argument(
        "--params", type=pathlib.Path, default=None,
        help="the parameter file to run on; defaults to the smoke-test case",
    )
    parser.add_argument(
        "--submission", type=pathlib.Path, default=None,
        help=(
            "a JSON file holding a face-finding agent's `final` payload, "
            "replayed through the chain's own output path instead of a "
            "selection this probe derives"
        ),
    )
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument(
        "--resume", action="store_true",
        help=(
            "continue the named job from the stage after the last one it "
            "recorded, instead of starting it over"
        ),
    )
    parser.add_argument(
        "--stall-timeout-s", type=int, default=7200,
        help="dump every thread's stack after this long without a stage ending",
    )
    args = parser.parse_args()

    faulthandler.dump_traceback_later(args.stall_timeout_s, exit=True)

    stored = json.loads(
        (OUTPUT / "jobs" / args.source_job / "case.json").read_text(
            encoding="utf-8"
        )
    )
    case = Case.model_validate(stored)
    print(f"case from {args.source_job}: model + domain carried over")

    params_path = (args.params.resolve() if args.params else PARAMS)
    params = json.loads(params_path.read_text(encoding="utf-8"))

    def assembly(ctx: RunContext) -> Case:
        ctx.case.physics = params_module.physics_from_params(
            ctx.params, str(params_path)
        )
        ctx.case.physics.consistency = params_module.check_consistency(
            ctx.case.physics, ctx.case.model
        )
        if args.submission is not None:
            ctx.case.load_surface = _replay(ctx.case, args.submission)
        elif args.faces == "band":
            ctx.case.load_surface = _selection(
                ctx.case, args.radius_min, args.radius_max
            )
        else:
            ctx.case.load_surface = _measure(
                ctx.case, [int(v) for v in args.faces.split(",")]
            )
        return ctx.case

    from seekflow_structural.agents import mesh as mesh_stage
    from seekflow_structural.agents import verify as verify_stage
    from seekflow_structural.pipeline import materialize as materialize_stage
    from seekflow_structural.pipeline import solve as solve_stage

    budget = Budget(max_tool_calls=200)
    orchestrator = Orchestrator(OUTPUT, budget=budget)
    # Frame and domain were decided by a real run and are carried over; every
    # stage from assembly onward runs for real.
    orchestrator.register(Stage.FRAME, lambda ctx: None)
    orchestrator.register(Stage.DOMAIN, lambda ctx: None)
    orchestrator.register(Stage.ASSEMBLY, assembly)
    orchestrator.register(Stage.MESH, mesh_stage.mesh)
    orchestrator.register(Stage.MATERIALIZE, materialize_stage.materialize)
    orchestrator.register(Stage.SOLVE, solve_stage.stage_solve)
    orchestrator.register(Stage.POSTPROCESS, solve_stage.stage_postprocess)
    orchestrator.register(Stage.VERIFY, verify_stage.verify)

    from seekflow_structural.runtime.caller import load_api_key

    load_api_key(REPO / "_structural_experiment" / "input" / ".deepseek_key")

    try:
        record = orchestrator.run(
            args.job, case=case, params=params, params_path=str(params_path),
            allow_unconfirmed=True, resume=args.resume,
        )
    except Exception:
        traceback.print_exc()
        return 1
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
