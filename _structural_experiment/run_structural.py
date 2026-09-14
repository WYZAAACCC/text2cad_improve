"""Run the isolated Agent-defined structural solve end to end."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/engineering_tools/src"))

from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner  # noqa: E402

from seekflow_structural.core.postprocess_structural import postprocess  # noqa: E402
from seekflow_structural.core.structural_apdl import materialize_intent, render_apdl  # noqa: E402
from seekflow_structural.core.structural_intent_models import StructuralIntent  # noqa: E402


def _ansys_executable(explicit: Path | None) -> Path:
    candidates = []
    if explicit is not None:
        candidates.append(explicit)
    env_path = os.environ.get("ANSYS181_EXE")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            Path(r"D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ANSYS181.exe"),
            Path(r"D:\ANSYS181\ANSYS Inc\v181\ANSYS\bin\winx64\ansys181.exe"),
            Path(r"C:\Program Files\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"),
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("ANSYS181.exe was not found")


def _clean_ansys_outputs(job_dir: Path, jobname: str) -> None:
    for suffix in (
        ".out",
        ".err",
        ".log",
        ".db",
        ".rst",
        ".full",
        ".esav",
        ".mntr",
        ".stat",
        ".dsp",
    ):
        path = job_dir / f"{jobname}{suffix}"
        if path.is_file():
            path.unlink()
    for name in ("nodal_stress_3d.csv", "result_summary.txt"):
        path = job_dir / name
        if path.is_file():
            path.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("intent", type=Path)
    parser.add_argument("mesh_inp", type=Path)
    parser.add_argument("selected_face_nodes", type=Path)
    parser.add_argument("mesh_config", type=Path)
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--ansys-exe", type=Path)
    parser.add_argument("--allow-unconfirmed-reference", action="store_true")
    parser.add_argument("--memory-mb", type=int, default=3000)
    parser.add_argument("--timeout-s", type=int, default=1800)
    args = parser.parse_args()

    intent_payload = json.loads(args.intent.read_text(encoding="utf-8"))
    intent = StructuralIntent.model_validate(
        intent_payload["final"]["intent"]
    )
    if intent.status == "needs_input":
        raise SystemExit("intent is not executable: needs_input")
    if intent.status == "ready_for_confirmation" and not (
        args.allow_unconfirmed_reference
    ):
        raise SystemExit(
            "intent is ready_for_confirmation; obtain confirmation or use "
            "--allow-unconfirmed-reference for a non-design smoke test"
        )

    job_dir = args.job_dir.resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    mesh_inp = args.mesh_inp.resolve()
    selected_face_nodes = args.selected_face_nodes.resolve()
    mesh_config = json.loads(args.mesh_config.read_text(encoding="utf-8"))

    materialized = materialize_intent(
        intent,
        mesh_inp,
        selected_face_nodes,
        job_dir,
        mesh_config,
    )
    solve_inp = render_apdl(
        intent,
        mesh_inp,
        job_dir,
        Path(materialized["load_table"]),
        mesh_config,
    )

    ansys_exe = _ansys_executable(args.ansys_exe)
    runner = AnsysAPDLRunner(
        ansys_exe=ansys_exe,
        workspace_root=job_dir,
        default_timeout_s=args.timeout_s,
    )
    _clean_ansys_outputs(job_dir, "structural")
    run = runner.run_apdl_file(
        input_file=solve_inp,
        job_dir=job_dir,
        jobname="structural",
        timeout_s=args.timeout_s,
        memory_mb=args.memory_mb,
    )
    (job_dir / "ansys_run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    metrics = None
    if (job_dir / "nodal_stress_3d.csv").is_file():
        metrics = postprocess(
            intent,
            job_dir,
            selected_face_nodes,
            Path(materialized["load_audit"]),
        )
    manifest = {
        "schema_version": "structural_run_manifest_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": intent.case_id,
        "intent_status": intent.status,
        "intent_file": str(args.intent.resolve()),
        "mesh_inp": str(mesh_inp),
        "selected_face_nodes": str(selected_face_nodes),
        "solve_inp": str(solve_inp.resolve()),
        "load_table": materialized["load_table"],
        "load_audit": materialized["load_audit"],
        "ansys_exe": str(ansys_exe),
        "ansys_run": run,
        "metrics": metrics,
        "scientific_status": (
            "synthetic_or_unconfirmed_pipeline_validation"
            if intent.status != "ready"
            else "confirmed_case"
        ),
    }
    (job_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if run["has_error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
