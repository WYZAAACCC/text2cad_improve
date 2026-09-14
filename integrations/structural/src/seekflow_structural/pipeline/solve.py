"""Run the deck, then read the results back into the case.

The solve is the one step that talks to something outside this process and
cannot be undone, so its handling is deliberately narrow: the exit status is
recorded either way, the artifacts the postprocessor needs are checked for
before it is called, and an interrupted run is never retried automatically -
a solve that was killed may have left state nobody has looked at.

The scientific status is stamped here, from the parameter file's confirmation
state, so it travels with the results rather than being remembered at the
point of reporting.
"""
from __future__ import annotations

import json
from pathlib import Path

from seekflow_structural.case.model import SolveRecord, Written
from seekflow_structural.core.postprocess_structural import postprocess as _post
from seekflow_structural.errors import STATUS_FAILED, StructuralError
from seekflow_structural.pipeline.materialize import (
    MESH_DIR,
    MESH_FILE,
    SOLVE_DIR,
    intent_from_case,
)
from seekflow_structural.pipeline.orchestrator import RunContext

ANSYS_CANDIDATES = (
    Path(r"D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ANSYS181.exe"),
    Path(r"D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"),
    Path(r"C:\Program Files\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"),
)

SOLVE_INP = "solve.inp"
RESULTS_CSV = "nodal_stress_3d.csv"
LOAD_AUDIT = "load_audit.json"
METRICS = "structural_metrics.json"


def ansys_executable(explicit: Path | None = None) -> Path:
    import os

    if explicit is not None:
        if not explicit.is_file():
            raise StructuralError(
                "ansys_missing", f"{explicit} is not a file", "solve"
            )
        return explicit.resolve()
    from_env = os.environ.get("ANSYS181_EXE")
    if from_env and Path(from_env).is_file():
        return Path(from_env).resolve()
    for candidate in ANSYS_CANDIDATES:
        if candidate.is_file():
            return candidate.resolve()
    raise StructuralError(
        "ansys_missing",
        "ANSYS181.exe was not found; pass --ansys-exe or set ANSYS181_EXE",
        "solve",
    )


def solve_dir(ctx: RunContext) -> Path:
    return ctx.path / SOLVE_DIR


def selection_path(ctx: RunContext) -> Path:
    return solve_dir(ctx) / "selected_face_nodes.json"


def _runner(job_dir: Path, timeout_s: int, explicit: Path | None):
    from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner

    return AnsysAPDLRunner(
        ansys_exe=ansys_executable(explicit),
        workspace_root=job_dir,
        default_timeout_s=timeout_s,
    )


def _memory_mb() -> int:
    import os

    return int(os.environ.get("STRUCTURAL_MEMORY_MB", "12000"))


def run_solve(ctx: RunContext, *, ansys_exe: Path | None = None,
              memory_mb: int | None = None) -> SolveRecord:
    directory = solve_dir(ctx)
    solve_inp = directory / SOLVE_INP
    if not solve_inp.is_file():
        raise StructuralError(
            "deck_missing",
            f"{solve_inp} does not exist; materialize must run first",
            "solve",
        )

    timeout_s = ctx.budget.max_ansys_wall_s
    runner = _runner(directory, timeout_s, ansys_exe)
    ctx.tool_call()
    run = runner.run_apdl_file(
        input_file=solve_inp,
        job_dir=directory,
        jobname="structural",
        timeout_s=timeout_s,
        memory_mb=memory_mb if memory_mb is not None else _memory_mb(),
    )
    ctx.job.write(
        f"{SOLVE_DIR}/ansys_run.json", run
    )
    ctx.job.event(
        {
            "kind": "solve_finished",
            "stage": "solve",
            "has_error": bool(run.get("has_error")),
            "exit_code": run.get("returncode"),
        }
    )
    if run.get("has_error"):
        # `failed`, not `rejected`: ANSYS has run and left files behind, so a
        # blind retry is not automatically safe.
        raise StructuralError(
            "ansys_failed",
            f"ANSYS reported an error; see {SOLVE_DIR}/ansys_run.json",
            "solve",
            status=STATUS_FAILED,
        )
    return SolveRecord(
        job_dir=str(directory),
        ansys_exit_ok=True,
        written=Written(by_stage="solve", kind="measured"),
    )


def read_results(ctx: RunContext) -> dict:
    """Post-process the stored results into the case's metrics.

    Written as a separate step from the solve so the post-processing agent can
    re-read the same artifacts later without running ANSYS again - which is
    the whole reason the results are kept as files rather than as objects.
    """
    case = ctx.case
    directory = solve_dir(ctx)
    if not (directory / RESULTS_CSV).is_file():
        raise StructuralError(
            "no_results",
            f"{directory / RESULTS_CSV} does not exist; there is nothing to "
            "post-process",
            "postprocess",
        )

    intent = intent_from_case(
        case, ctx.path / MESH_DIR / MESH_FILE, selection_path(ctx)
    )
    metrics = _post(
        intent, directory, selection_path(ctx), directory / LOAD_AUDIT
    )
    ctx.job.write(f"{SOLVE_DIR}/{METRICS}", metrics)
    return metrics


def summarise(metrics: dict) -> dict:
    """The handful of numbers a report quotes, pulled out by name."""
    stress = metrics.get("stress", {})
    return {
        "max_displacement_mm": metrics.get("displacement", {}).get("max_mm"),
        "max_von_mises_mpa": stress.get("max_von_mises_mpa"),
        "max_von_mises_radius_mm": stress.get("max_radius_mm"),
        "max_load_surface_von_mises_mpa": stress.get(
            "max_load_surface_von_mises_mpa"
        ),
        "min_safety_factor": stress.get("min_safety_factor"),
        "scientific_status": metrics.get("scientific_status"),
    }


def write_summary(path: Path, metrics: dict) -> None:
    path.write_text(
        json.dumps(summarise(metrics), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def stage_solve(ctx: RunContext) -> "object":
    """The orchestrator's solve stage: run the deck, record that it ran.

    The results are not read here. Solving and interpreting are separate
    stages because the post-processing agent has to be able to re-read the
    same artifacts later without paying for another solve.
    """
    record = run_solve(ctx)
    ctx.case.solve = record
    return ctx.case


def stage_postprocess(ctx: RunContext) -> "object":
    """Read the stored results into the case, and stamp the run's status."""
    case = ctx.case
    metrics = read_results(ctx)
    record = case.solve or SolveRecord(
        written=Written(by_stage="postprocess", kind="measured")
    )
    record.metrics = metrics
    record.scientific_status = str(metrics.get("scientific_status") or "")
    record.finished_at_utc = str(metrics.get("created_at_utc") or "")
    if record.written is None:
        record.written = Written(by_stage="postprocess", kind="measured")
    case.solve = record
    return case


PROPAGATION = (MESH_DIR, MESH_FILE, SOLVE_DIR)
