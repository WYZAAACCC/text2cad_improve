"""Generative CAD builder — validates spec, runs fixed harness, produces STEP + metadata.

Separate from build_cadquery_from_cad_ir which handles CADPartSpec.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from seekflow_engineering_tools.cadquery_backend.builder import assert_file_created
from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_extension, ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.generative_cad.graph_validation import run_graph_validation
from seekflow_engineering_tools.generative_cad.ir import GenerativeCADSpec
from seekflow_engineering_tools.generative_cad.metadata import validate_generative_metadata_v1
from seekflow_engineering_tools.generative_cad.preflight import run_geometry_preflight
from seekflow_engineering_tools.generative_cad.validation import (
    validate_artifact_against_generative_contract,
)


def build_generative_cad_model(
    spec: GenerativeCADSpec,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    inspect: bool = True,
    graph_out: str | Path | None = None,
    script_out: str | Path | None = None,
) -> dict:
    """Build a STEP file from GenerativeCADSpec using fixed runner harness.

    Returns EngineeringActionResult.model_dump().
    """
    workspace = config.workspace_root
    step_path = ensure_inside_workspace(workspace, out_step)
    ensure_extension(step_path, {".step", ".stp"})

    step_path.parent.mkdir(parents=True, exist_ok=True)

    if step_path.exists() and not config.allow_overwrite:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error=f"Output file {step_path} already exists.",
        ).model_dump()

    # ── 1. Validate spec if input is dict ──
    if isinstance(spec, dict):
        try:
            spec = GenerativeCADSpec.model_validate(spec)
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="build_generative_cad",
                error=f"GenerativeCADSpec validation failed: {exc}",
            ).model_dump()

    # ── 2. Graph validation ──
    gv_report = run_graph_validation(spec)
    if not gv_report.ok:
        error_msgs = [
            f"[{i.code}] {i.message}"
            for i in gv_report.issues if i.severity == "error"
        ]
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error="Graph validation failed: " + "; ".join(error_msgs),
            metrics={"graph_validation": gv_report.model_dump()},
        ).model_dump()

    # ── 3. Geometry preflight ──
    preflight_report = run_geometry_preflight(spec)
    if not preflight_report["ok"]:
        error_msgs = [
            f"[{i['code']}] {i['message']}"
            for i in preflight_report["issues"] if i.get("severity") == "error"
        ]
        if error_msgs:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="build_generative_cad",
                error="Geometry preflight failed: " + "; ".join(error_msgs),
                metrics={"preflight": preflight_report},
            ).model_dump()

    # ── 4. Write graph JSON ──
    meta_path = step_path.with_suffix(".metadata.json")

    if graph_out:
        graph_path = ensure_inside_workspace(workspace, graph_out)
    else:
        import uuid
        graph_dir = ensure_inside_workspace(workspace, ".generative_cad_graphs")
        graph_dir.mkdir(parents=True, exist_ok=True)
        graph_path = graph_dir / f"graph_{uuid.uuid4().hex[:12]}.json"

    # Serialize spec to JSON for runner consumption
    graph_dict = spec.model_dump()
    # Add skill_stack for metadata
    graph_dict["skill_stack"] = [
        {"skill_id": s.skill_id, "skill_version": s.skill_version}
        for s in spec.selected_skills
    ]
    graph_dict["part_name"] = spec.part_name

    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(
        json.dumps(graph_dict, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # ── 5. Write fixed runner script ──
    if script_out:
        script_path = ensure_inside_workspace(workspace, script_out)
        ensure_extension(script_path, {".py"})
    else:
        import uuid
        script_dir = ensure_inside_workspace(workspace, ".generative_cad_scripts")
        script_dir.mkdir(parents=True, exist_ok=True)
        script_path = script_dir / f"run_gen_{uuid.uuid4().hex[:12]}.py"

    harness_script = _generate_harness_script(graph_path, step_path, meta_path)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(harness_script, encoding="utf-8")

    # ── 6. Execute runner via subprocess ──
    timeout = spec.system_validation_contract.max_runtime_seconds
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(step_path.parent),
        )
    except subprocess.TimeoutExpired:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error=f"Generative CAD build timed out after {timeout} seconds.",
        ).model_dump()

    stdout_tail = (result.stdout or "")[-2000:]
    stderr_tail = (result.stderr or "")[-2000:]

    # Collect warnings
    build_warnings: list[str] = []
    for line in (result.stdout or "").split("\n"):
        if line.startswith("CQ_WARNING:"):
            build_warnings.append(line[len("CQ_WARNING:"):].strip())

    if result.returncode != 0:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error=f"Runner script failed (rc={result.returncode}). Stderr: {(result.stderr or '')[:200]}",
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            warnings=build_warnings,
            metrics={
                "graph_path": str(graph_path),
                "script_path": str(script_path),
            },
        ).model_dump()

    # ── 7. Assert STEP exists ──
    try:
        assert_file_created(step_path, "STEP")
    except (FileNotFoundError, ValueError) as exc:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error=str(exc),
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            metrics={
                "graph_path": str(graph_path),
                "script_path": str(script_path),
            },
        ).model_dump()

    files_created = [str(step_path), str(graph_path), str(script_path)]

    # ── 8. Assert metadata exists ──
    try:
        assert_file_created(meta_path, "metadata")
    except (FileNotFoundError, ValueError) as exc:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error=f"Metadata sidecar validation failed: {exc}",
            files_created=files_created,
            metrics={
                "graph_path": str(graph_path),
                "script_path": str(script_path),
                "step_path": str(step_path),
            },
        ).model_dump()

    files_created.append(str(meta_path))

    # ── 9. Validate generative metadata ──
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error=f"Metadata JSON invalid: {exc}",
            files_created=files_created,
        ).model_dump()

    meta_validation = validate_generative_metadata_v1(metadata)
    if not meta_validation["ok"]:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error="Metadata validation failed: "
            + "; ".join(i["message"] for i in meta_validation["issues"]),
            files_created=files_created,
        ).model_dump()

    metrics: dict = {
        "graph_path": str(graph_path),
        "script_path": str(script_path),
        "step_path": str(step_path),
        "step_size_bytes": step_path.stat().st_size,
        "feature_count": len(spec.feature_graph.nodes),
        "graph_validation": gv_report.model_dump(),
        "preflight": preflight_report,
        "metadata_validation": meta_validation,
    }
    warnings: list[str] = list(build_warnings)

    # ── 10. Inspection ──
    if inspect:
        insp_result = inspect_step_with_cadquery(step_path)
        metrics["inspection"] = insp_result

        if insp_result.get("error"):
            warnings.append(f"Inspection unavailable: {insp_result['error']}")
        else:
            validation_result = validate_artifact_against_generative_contract(
                insp_result, spec,
            )
            metrics["validation"] = validation_result

            # Write validation back to metadata
            if meta_path.exists():
                metadata["validation"] = {
                    "graph_validation": gv_report.model_dump(),
                    "geometry_preflight": preflight_report,
                    "inspection_validation": validation_result,
                }
                meta_path.write_text(
                    json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )

            if not validation_result["ok"]:
                return EngineeringActionResult(
                    ok=False,
                    software="cadquery",
                    action="build_generative_cad",
                    message="STEP file created but validation failed.",
                    files_created=files_created,
                    stdout_tail=stdout_tail,
                    stderr_tail=stderr_tail,
                    metrics=metrics,
                    warnings=warnings,
                    error="; ".join(
                        i["message"] for i in validation_result["issues"]
                    ),
                ).model_dump()

    return EngineeringActionResult(
        ok=True,
        software="cadquery",
        action="build_generative_cad",
        message=f"Generative CAD STEP file created and validated: {step_path}",
        files_created=files_created,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        metrics=metrics,
        warnings=warnings,
    ).model_dump()


def _generate_harness_script(
    graph_path: Path, out_step: Path, metadata_path: Path,
) -> str:
    """Generate the fixed runner harness — a small script that calls
    run_generative_cad_from_files. NEVER contains LLM-authored CadQuery code.
    """
    return f'''
"""Fixed generative CAD runner harness — auto-generated, contains no LLM code."""
import sys
sys.path.insert(0, r"{Path(__file__).resolve().parents[3]}")

from seekflow_engineering_tools.generative_cad.runner import run_generative_cad_from_files

result = run_generative_cad_from_files(
    graph_path=r"{graph_path.as_posix()}",
    out_step=r"{out_step.as_posix()}",
    metadata_path=r"{metadata_path.as_posix()}",
)

if not result.ok:
    print(f"BUILD FAILED: {{result.error}}", file=sys.stderr)
    sys.exit(1)

print(f"STEP exported: {{result.step_path}}")
print(f"Metadata written: {{result.metadata_path}}")
for w in result.warnings:
    print(f"CQ_WARNING: {{w}}")
'''
