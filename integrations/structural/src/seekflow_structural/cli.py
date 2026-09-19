"""One command for the whole chain.

Before this existed the chain was driven by hand-typed commands in a README
and three shell scripts with one part's paths baked in: nothing ran two stages,
nothing recorded what a run had done, and nothing could be resumed.

    seekflow-structural run     --bundle <dir> --params <case.json> --job <id>
    seekflow-structural run     --bundle <dir> --brief <brief.md>   --job <id>
    seekflow-structural resume  --bundle <dir> --params <case.json> --job <id>
    seekflow-structural summary --job <id>
    seekflow-structural schema  --bundle <dir>

What the simulation *is* has to be said one of two ways: a parameter file, or
a description in prose for the setup stage to read. A brief produces a
parameter file - it is written to the job as `params.resolved.json` - so a
case can start as a description and be repeated later as a file.

`resume` takes the same arguments on purpose. It re-reads them to confirm the
job is being continued against the model it started on, then proceeds from the
stored case.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from seekflow_structural.case.model import BundleRef, Case
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.orchestrator import Budget, Orchestrator
from seekflow_structural.runtime.store import JobStore, file_hash

DEFAULT_OUTPUT = "_structural_experiment/output/structural"
DEFAULT_JOB = "structural"


def _bundle_ref(bundle: Path) -> BundleRef:
    """Bind the model input by content, not by path.

    The chain opens `design.xbf` for topology and `model.step` for meshing.
    Both are hashed here so a resume can tell whether it is continuing the same
    job, and so a mismatched pair - a STEP from one revision and an XBF from
    another - is visible rather than silently meshed.
    """
    bundle = bundle.resolve()
    required = ("model.step", "design.xbf", "history.json")
    missing = [name for name in required if not (bundle / name).is_file()]
    if missing:
        raise StructuralError(
            "bundle_incomplete",
            f"{bundle} is missing {', '.join(missing)}; a model bundle needs "
            "model.step, design.xbf and history.json",
            "preflight",
        )

    history = json.loads((bundle / "history.json").read_text(encoding="utf-8"))
    return BundleRef(
        path=str(bundle),
        lineage_id=history.get("lineage_id", ""),
        revision_id=history.get("revision_id", ""),
        model_step_sha256=file_hash(bundle / "model.step"),
        design_xbf_sha256=file_hash(bundle / "design.xbf"),
        history_topology_hash=history.get("topology_hash", ""),
    )


def _confirmation_gate(params: dict, allow_unconfirmed: bool) -> str:
    status = params.get("confirmation_status") or "unconfirmed"
    if status == "confirmed":
        return "confirmed_case"
    if not allow_unconfirmed:
        raise StructuralError(
            "needs_confirmation",
            f"the parameter file is {status!r}; a run on unconfirmed inputs "
            "must be requested explicitly with --allow-unconfirmed, and it "
            "will be stamped as synthetic",
            "preflight",
        )
    return "synthetic_or_unconfirmed_pipeline_validation"


def _seed_case(bundle: Path, inputs_path: Path, params: dict) -> Case:
    """The case a fresh run starts from: the model, and a hash of its inputs.

    The hash is of whichever file stated the case - the parameter file, or the
    brief when the parameters are going to be read out of prose. Either way it
    is the thing a later run has to match to be continuing the same job.
    """
    return Case(
        case_id=str(params.get("case_id") or inputs_path.stem or bundle.name),
        bundle=_bundle_ref(bundle),
        params_hash=file_hash(inputs_path),
    )


def _seeded_case(args) -> Case:
    """Build a case from an earlier run's artifacts.

    The mesh and the radial profile are copied into the job so the run is
    self-contained: a job that reads its inputs from wherever they happened to
    be is a job that cannot be reproduced later.
    """
    from seekflow_structural.core.mesh_profile import build_profile
    from seekflow_structural.pipeline import seed as seed_module
    from seekflow_structural.runtime.store import JobStore

    if args.params is None:
        raise StructuralError(
            "seed_incomplete",
            "--seed-dir builds the case from an earlier run's artifacts, and "
            "those are read alongside a parameter file; pass --params",
            "preflight",
        )
    seed_dir = args.seed_dir.resolve()
    required = ("mesh.inp", "mesh_config.json", "intent.json")
    missing = [name for name in required if not (seed_dir / name).is_file()]
    if missing:
        raise StructuralError(
            "seed_incomplete",
            f"{seed_dir} is missing {', '.join(missing)}",
            "preflight",
        )

    mesh_inp = seed_dir / "mesh.inp"
    mesh_config = json.loads(
        (seed_dir / "mesh_config.json").read_text(encoding="utf-8")
    )
    intent_payload = json.loads(
        (seed_dir / "intent.json").read_text(encoding="utf-8")
    )
    profile_path = seed_dir / "radial_profile.json"
    if profile_path.is_file():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    else:
        # No cached profile: measure it from the model's own STEP, which is
        # the only surface description available here.
        profile = build_profile(args.bundle.resolve() / "model.step", 12)

    case = seed_module.build_case(
        bundle=args.bundle,
        params=json.loads(args.params.read_text(encoding="utf-8")),
        profile=profile,
        mesh_config=mesh_config,
        face_intent=args.face_intent.resolve(),
        intent_payload=intent_payload,
        mesh_inp=mesh_inp,
        mesh_config_source=str(seed_dir / "mesh_config.json"),
    )
    case.bundle = _bundle_ref(args.bundle)

    # Place the mesh where the chain expects it, in the job, now.
    job = JobStore(args.output, args.job)
    seed_module.install_mesh(_PathContext(job.path), mesh_inp)
    _copy_face_selection(args, job)

    return case


class _PathContext:
    """The minimum a stage helper needs to know about a job."""

    def __init__(self, path: Path):
        self.path = path


def _copy_face_selection(args, job) -> None:
    """Run the face-to-node mapping now that the mesh is in place.

    The mapping depends only on the geometry, the selected faces and the mesh,
    so it is deterministic - but it is kept as an explicit copy step rather
    than folded into materialise, because the face-finding sub-agent will
    produce the selection that feeds it.
    """
    import subprocess
    import sys

    from seekflow_structural.pipeline.materialize import SOLVE_DIR

    target = job.path / SOLVE_DIR
    target.mkdir(parents=True, exist_ok=True)
    selection = target / "selected_face_nodes.json"
    if selection.is_file():
        return

    repo_root = None
    for parent in Path(__file__).resolve().parents:
        if (parent / "_structural_experiment").is_dir():
            repo_root = parent
            break
    if repo_root is None:
        raise StructuralError(
            "repo_root_missing",
            "could not locate the repository root for the face mapping",
            "preflight",
        )
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "_structural_experiment/map_solid_faces.py"),
            str(args.bundle.resolve()),
            str(args.face_intent.resolve()),
            str(job.path / "mesh" / "mesh.inp"),
            str(selection),
        ],
        check=True,
        capture_output=True,
    )


def _orchestrator(
    output_root: Path, budget: Budget, *, seeded: bool
) -> Orchestrator:
    """Register whatever stages exist.

    Stages are registered by name so that an unfinished chain reports which
    stage is missing instead of failing at import. As each agent lands it is
    added here and the seeded pass-through for its stage is removed.

    `seeded` marks the bootstrap path: the case was built from artifacts an
    earlier run produced, so the stages that would have produced them are
    registered as pass-throughs. It goes away when the last agent lands.
    """
    from seekflow_structural.agents import assembly as assembly_stage
    from seekflow_structural.agents import domain as domain_stage
    from seekflow_structural.agents import feedback as feedback_stage
    from seekflow_structural.agents import mesh as mesh_stage
    from seekflow_structural.agents import setup as setup_stage
    from seekflow_structural.agents import verify as verify_stage
    from seekflow_structural.pipeline import frame as frame_stage
    from seekflow_structural.pipeline import materialize as materialize_stage
    from seekflow_structural.pipeline import solve as solve_stage
    from seekflow_structural.pipeline.stages import Stage

    orchestrator = Orchestrator(output_root, budget=budget)
    if seeded:
        # Stages whose real implementation is still to land. Each is replaced
        # by the agent named beside it, and until then the case carries the
        # values an earlier run left behind.
        for stage in (
            Stage.FRAME,     # frame measurement
            Stage.DOMAIN,    # domain agent
            Stage.SETUP,     # setup agent; the case carries its physics
            Stage.ASSEMBLY,  # assembly agent + face-finding sub-agent
            Stage.MESH,      # meshing agent
            Stage.VERIFY,    # verification agent
        ):
            orchestrator.register(stage, lambda ctx: None)
    else:
        # The stages that are built. The ones left out report themselves by
        # name when the run reaches them, which is what an unfinished chain
        # should do - better than a silent default that looks like a decision.
        orchestrator.register(Stage.FRAME, frame_stage.frame)
        orchestrator.register(Stage.DOMAIN, domain_stage.domain)
        orchestrator.register(Stage.SETUP, setup_stage.setup)
        orchestrator.register(Stage.ASSEMBLY, assembly_stage.assembly)
        orchestrator.register(Stage.MESH, mesh_stage.mesh)
        orchestrator.register(Stage.VERIFY, verify_stage.verify)
    orchestrator.register(Stage.MATERIALIZE, materialize_stage.materialize)
    orchestrator.register(Stage.SOLVE, solve_stage.stage_solve)
    orchestrator.register(Stage.POSTPROCESS, solve_stage.stage_postprocess)
    # Registered on both paths. A seeded run replays a case built from an
    # earlier run's artifacts, and deciding what to change about that case is
    # the whole point of reading it - so this stage is never a pass-through.
    orchestrator.register(Stage.FEEDBACK, feedback_stage.feedback)
    return orchestrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="seekflow-structural")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_run_args(p):
        p.add_argument("--bundle", type=Path, required=True,
                       help="model bundle directory")
        p.add_argument("--params", type=Path,
                       help=(
                           "parameter file (case JSON). One of --params or "
                           "--brief is required; if both are given the "
                           "written values win, because a person who typed a "
                           "number meant that number"
                       ))
        p.add_argument("--brief", type=Path,
                       help=(
                           "a description of the simulation in prose, for the "
                           "setup agent to turn into parameters. What it "
                           "produces is written to the job as "
                           "params.resolved.json, which can be passed as "
                           "--params on a later run"
                       ))
        p.add_argument("--job", default=DEFAULT_JOB, help="job id")
        p.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))
        p.add_argument("--allow-unconfirmed", action="store_true")
        p.add_argument("--max-tool-calls", type=int, default=200)
        p.add_argument("--max-ansys-wall-s", type=int, default=4000)
        p.add_argument("--wall-time-s", type=int, default=24 * 3600)
        p.add_argument("--api-key-file", type=Path, help=(
            "file holding the model provider key; otherwise read from "
            "DEEPSEEK_API_KEY"
        ))
        p.add_argument("--model", default=None)
        p.add_argument("--mesh-plan", type=Path, help=(
            "a meshing plan to use instead of letting the meshing agent "
            "choose one. Two runs given the same plan are resolved by the same "
            "rule, which is what makes a difference between their peaks "
            "attributable to their geometry rather than to their meshes."
        ))
        p.add_argument("--face-selection", type=Path, help=(
            "a load surface to use instead of letting the face-finding agent "
            "choose one, as the case.json's `load_surface` block from an "
            "earlier run. Two runs loaded through different faces are not the "
            "same experiment however equal their resultant force is."
        ))
        p.add_argument("--domain", type=Path, help=(
            "a domain decision to use instead of letting the domain agent "
            "choose one, as the case.json's `domain` block from an earlier "
            "run. Which piece of the part is cut out is part of the "
            "experiment, not of the design."
        ))
        p.add_argument("--ansys-exe", type=Path)
        p.add_argument("--memory-mb", type=int, default=12000)
        # Bootstrap only: build the case from artifacts an earlier run left
        # behind instead of from the agents. Removed when the last agent lands.
        p.add_argument("--seed-dir", type=Path, help=(
            "directory holding mesh.inp, mesh_config.json, intent.json and "
            "radial_profile.json from an earlier run (bootstrap path)"
        ))
        p.add_argument("--face-intent", type=Path, help=(
            "the accepted face selection JSON (bootstrap path)"
        ))

    add_run_args(sub.add_parser("run"))
    add_run_args(sub.add_parser("resume"))

    summary = sub.add_parser("summary")
    summary.add_argument("--job", default=DEFAULT_JOB)
    summary.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))

    schema = sub.add_parser("schema")
    schema.add_argument("--bundle", type=Path, required=True)

    args = parser.parse_args(argv)

    if args.command == "schema":
        print(json.dumps(
            _bundle_ref(args.bundle).model_dump(mode="json"),
            ensure_ascii=False, indent=2,
        ))
        return 0

    if args.command == "summary":
        job = JobStore(args.output, args.job)
        record = job.read("record.json") if job.exists("record.json") else None
        state = job.read("state.json") if job.exists("state.json") else {}
        print(json.dumps(
            {"job_id": args.job, "record": record,
             "stage": state.get("stage"),
             "stage_hashes": state.get("stage_hashes", {})},
            ensure_ascii=False, indent=2,
        ))
        return 0

    if args.params is None and args.brief is None:
        raise StructuralError(
            "no_parameters",
            "a run needs either --params, a written parameter file, or "
            "--brief, a description of the simulation for the setup agent to "
            "read. There is no third way to say what the simulation is.",
            "preflight",
        )
    params = (
        json.loads(args.params.read_text(encoding="utf-8"))
        if args.params is not None else {}
    )
    brief = args.brief.read_text(encoding="utf-8") if args.brief else ""
    scientific_status = _confirmation_gate(params, args.allow_unconfirmed)

    seeded = args.seed_dir is not None
    if seeded:
        if args.face_intent is None:
            raise StructuralError(
                "seed_incomplete",
                "--seed-dir also needs --face-intent",
                "preflight",
            )
        case = _seeded_case(args)
    else:
        case = _seed_case(args.bundle, args.params or args.brief, params)

    # The key is loaded here, once, and the stages read it from the
    # environment through the shared caller. Six standalone agents each used
    # to load their own.
    if args.command in ("run", "resume"):
        from seekflow_structural.runtime.caller import load_api_key

        load_api_key(args.api_key_file)

    budget = Budget(
        max_tool_calls=args.max_tool_calls,
        max_ansys_wall_s=args.max_ansys_wall_s,
        wall_time_s=args.wall_time_s,
    )
    orchestrator = _orchestrator(args.output, budget, seeded=seeded)
    import os

    if args.ansys_exe:
        os.environ["ANSYS181_EXE"] = str(args.ansys_exe.resolve())
    mesh_plan = (
        json.loads(args.mesh_plan.read_text(encoding="utf-8"))
        if getattr(args, "mesh_plan", None) else None
    )
    face_selection = (
        json.loads(args.face_selection.read_text(encoding="utf-8"))
        if getattr(args, "face_selection", None) else None
    )
    domain_decision = (
        json.loads(args.domain.read_text(encoding="utf-8"))
        if getattr(args, "domain", None) else None
    )
    os.environ["STRUCTURAL_MEMORY_MB"] = str(args.memory_mb)

    try:
        record = orchestrator.run(
            args.job,
            case=case,
            resume=args.command == "resume",
            allow_unconfirmed=args.allow_unconfirmed,
            params=params,
            params_path=(str(args.params.resolve()) if args.params else ""),
            brief=brief,
            brief_path=(str(args.brief.resolve()) if args.brief else ""),
            mesh_plan=mesh_plan,
            face_selection=face_selection,
            domain_decision=domain_decision,
        )
    except StructuralError as exc:
        print(json.dumps(
            exc.diagnostic.model_dump(mode="json"), ensure_ascii=False, indent=2
        ), file=sys.stderr)
        return 1

    record["scientific_status"] = record.get("scientific_status") or (
        scientific_status
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
