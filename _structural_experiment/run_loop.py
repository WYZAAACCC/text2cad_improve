"""The loop, run for real: generate, solve, diagnose, revise, and do it again.

Every seam is now the real thing. `parametric` supplies generate and solve,
`loop_wiring` supplies the two agents, and the loop between them is the code
that was tested with fakes. Nothing is typed in by hand - what revision two is
comes from what the feedback agent said about revision one.

Two revisions is the minimum that tests anything: the first observation of a
rule cannot tell a mechanism from a coincidence, and a prediction with no
second run to check it against is not a prediction.

    python run_loop.py --revisions 2
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The runs were moved off the working disk; see _store.py.
from _store import loop_test  # noqa: E402
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))
sys.path.insert(0, str(REPO / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(REPO / "_param_experiment"))

from seekflow_structural.core.mesh_profile import build_profile  # noqa: E402
from seekflow_structural.pipeline import iterate  # noqa: E402
from seekflow_structural.pipeline.design_effect import surface_cells  # noqa: E402
from seekflow_structural.tools import (  # noqa: E402
    knowledge, loop_wiring, parametric, workspace,
)

# The frozen snapshot the D27 dataset was built from. The live
# `_param_experiment/param_templates.py` has drifted from it, and the stored
# D27 document matches neither - so which one is the master is a decision, and
# it is made here rather than left to whichever directory is on the path.
MASTER = (REPO / "_param_experiment" / "turbine_disc_dataset_D01-D32"
          / "scripts")

# D27, as `design_families` and `agentic_golden.family_params` define it.
D27_PARAMS = {
    "category": "coupled", "form": "large_hub",
    "od_mm": 600, "bore_mm": 120, "thick_mm": 76, "hub_mm": 38, "rim_mm": 30,
    "slots": 60, "teeth": 3, "R_mm": 215, "depth_mm": 22.4,
    "throat_half_width_mm": 6.0, "fr_mm": 0.97,
    "holes": 20, "pcd_mm": 208, "hdia_mm": 12,
    "grooves": 1, "gw_mm": 10, "gd_mm": 9,
}


def _frame_kwargs(case_path: Path | None) -> dict:
    """The axis the generated STEP should be measured about, when known."""
    if case_path is None:
        return {}
    path = Path(case_path)
    if path.is_dir():
        path = path / "case.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    frame = ((payload.get("model") or {}).get("frame") or {})
    origin = frame.get("axis_origin_mm")
    direction = frame.get("axis_direction")
    if origin is None or direction is None:
        return {}

    def components(value):
        if isinstance(value, dict):
            return [value["x"], value["y"], value["z"]]
        return list(value)

    origin = components(origin)
    direction = components(direction)
    return {
        "axis_origin_mm": [float(v) for v in origin],
        "axis_direction_mm": [float(v) for v in direction],
    }


def _experiment_from(case_path: Path) -> dict:
    """The three decisions a case records, in the shape the CLI takes back.

    Read from the case the run wrote rather than from an agent's return value,
    because the case is what the solve was actually built from - a value taken
    from a return path could disagree with the file and the file would be the
    one that was right.
    """
    case_path = Path(case_path)
    if case_path.is_dir():
        case_path = case_path / "case.json"
    if not case_path.is_file():
        return {}
    case = json.loads(case_path.read_text(encoding="utf-8"))
    out: dict = {}
    if case.get("domain"):
        out["domain"] = case["domain"]
    if case.get("mesh"):
        out["mesh_plan"] = case["mesh"]
    if case.get("load_surface"):
        out["face_selection"] = case["load_surface"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revisions", type=int, default=2)
    parser.add_argument("--root", type=Path,
                        default=loop_test() / "live")
    parser.add_argument("--lineage", default="D27")
    parser.add_argument("--brief", type=Path,
                        default=REPO / "_structural_experiment" / "input"
                        / "d27_brief.md")
    parser.add_argument("--case-params", type=Path, default=None,
                        help=(
                            "the physical case JSON for this design family. "
                            "It is passed to the structural run so a family "
                            "other than D27 does not inherit D27's physics."
                        ))
    parser.add_argument("--document", type=Path, default=None,
                        help=(
                            "the generated design the run starts from - the "
                            "llm_raw the generation system produced. With it, "
                            "revision one *is* that design and every revision "
                            "after it is that document with a feedback change "
                            "applied. Without it, revision one is built by "
                            "`param_templates.build`, which is the same "
                            "mechanism but a different starting point."
                        ))
    parser.add_argument("--experiment", type=Path, default=None,
                        help=(
                            "a case.json (or the job directory holding one) "
                            "from an earlier run whose domain, face selection "
                            "and mesh plan every revision of this run is held "
                            "to, the first included. Without it the first "
                            "revision decides for itself and later revisions "
                            "are held to that - which fixes the experiment "
                            "within a run but not between runs, and two runs "
                            "can then land their peaks on different features."
                        ))
    parser.add_argument("--api-key-file", type=Path,
                        default=REPO / "_archive" / "apikey.txt")
    parser.add_argument("--ansys-exe", type=Path, default=None)
    parser.add_argument("--feedback-calls", type=int, default=32)
    parser.add_argument("--revise-calls", type=int, default=16)
    parser.add_argument("--timeout-s", type=int, default=5400)
    args = parser.parse_args()

    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    key = args.api_key_file if args.api_key_file.is_file() else None

    def generate(space: workspace.Workspace) -> Path:
        started = time.time()
        bundle = parametric.generate_bundle(
            space, repo_root=REPO, timeout_s=args.timeout_s,
            python=sys.executable,
        )
        print(f"[{space.revision}] generated in {time.time() - started:.0f}s "
              f"-> {bundle}", flush=True)
        return bundle

    # The three decisions that are the experiment rather than the design.
    #
    # The first revision makes them - the domain agent, the face-finding agent
    # and the meshing agent each choose once - and every revision after it is
    # held to the same ones. Without this a later revision arrives at its own
    # load case and its own mesh, and the difference between two peaks is no
    # longer attributable to the design. Measured on the first two-revision run
    # that completed end to end: rev-1 loaded the fir-tree tooth flanks over
    # 4,373 mm2, rev-2 loaded the slot walls over 12,009 mm2, and the applied
    # resultant came out reversed - so the 26% fall in peak stress between them
    # was a change of load case as much as a change of geometry, and the loop
    # wrote it into the knowledge base as a rule about the hole.
    experiment: dict = {}
    if args.experiment is not None:
        experiment.update(_experiment_from(args.experiment))
        print(
            "held from the start to an earlier run's experiment: "
            + (", ".join(sorted(experiment)) or "(nothing found in it)"),
            flush=True,
        )

    # Whether this run had to decide the experiment itself. Seeded from
    # `--experiment`, it never does, and every revision - including the first -
    # is held to a load case and a mesh that some earlier run established.
    established_here = [not experiment]
    established_frame: dict = _frame_kwargs(args.experiment)

    def solve(bundle: Path, space: workspace.Workspace) -> dict:
        started = time.time()
        run = parametric.solve_bundle(
            bundle, space, job_id=f"{args.lineage}-{space.revision}",
            output_root=root / "jobs", brief_path=args.brief,
            params_path=args.case_params,
            api_key_file=key, ansys_exe=args.ansys_exe, **experiment,
        )
        if established_here[0]:
            experiment.update(_experiment_from(Path(run["job"])))
            case_path = Path(run["job"]) / "case.json"
            if case_path.is_file():
                frame = ((json.loads(case_path.read_text(encoding="utf-8"))
                          .get("model") or {}).get("frame") or {})
                origin = frame.get("axis_origin_mm")
                direction = frame.get("axis_direction")
                if origin is not None and direction is not None:
                    established_frame.update({
                        "axis_origin_mm": [float(v) for v in origin],
                        "axis_direction_mm": [float(v) for v in direction],
                    })
            established_here[0] = False
            print(f"[{space.revision}] established the experiment: "
                  f"{', '.join(sorted(experiment)) or '(nothing to hold)'}",
                  flush=True)
        else:
            print(f"[{space.revision}] held to the experiment: "
                  f"{', '.join(sorted(experiment)) or '(nothing)'}",
                  flush=True)
        print(f"[{space.revision}] solved in {time.time() - started:.0f}s",
              flush=True)
        return run

    def inspect_design(
        bundle: Path, space: workspace.Workspace, target: dict | None = None
    ) -> dict:
        profile = build_profile(
            Path(bundle) / "model.step", 12,
            **established_frame,
        )
        return {
            "r_min_mm": profile.get("r_min_mm"),
            "r_max_mm": profile.get("r_max_mm"),
            "z_min_mm": profile.get("z_min_mm"),
            "z_max_mm": profile.get("z_max_mm"),
            "face_count": profile.get("face_count"),
            "total_volume_mm3": profile.get("total_volume_mm3"),
            "total_surface_area_mm2": profile.get("total_surface_area_mm2"),
            "bands": profile.get("bands"),
            "surface_cells": surface_cells(profile),
            "target_context": target or {},
        }

    base = knowledge.KnowledgeBase.load(root / "knowledge.json")
    seed = (
        json.loads(args.document.read_text(encoding="utf-8"))
        if args.document and args.document.is_file() else None
    )
    origin = args.document if seed else "(none - built from the template layer)"
    print(f"seed document: {origin}", flush=True)
    family_params = dict(D27_PARAMS)
    if args.case_params is not None:
        family_params.update(
            json.loads(args.case_params.read_text(encoding="utf-8"))
        )
    loop = iterate.Loop(
        master_dir=MASTER, root=root / "revisions", lineage=args.lineage,
        params=family_params, document=seed,
        generate=generate, solve=solve,
        diagnose=loop_wiring.make_diagnose(
            api_key_file=key, max_calls=args.feedback_calls, base=base),
        revise=loop_wiring.make_revise(
            base=base, api_key_file=key, max_calls=args.revise_calls),
        knowledge_path=root / "knowledge.json",
        design_probe=inspect_design,
    )

    result = loop.run(args.revisions)
    (root / "loop_result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n".join(iterate.report_lines(result)), flush=True)
    print(f"\nwritten: {root / 'loop_result.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
