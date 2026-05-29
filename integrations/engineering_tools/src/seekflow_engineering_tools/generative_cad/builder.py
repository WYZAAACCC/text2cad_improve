"""Generative CAD builder — validates spec, runs fixed harness, produces STEP + metadata.

Upgraded to G-CAD Core v0.2: accepts RawGcadDocument dict, runs validate_and_canonicalize,
writes canonical JSON, executes fixed harness via subprocess.
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
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize


def build_generative_cad_model(
    spec: RawGcadDocument | dict,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    inspect: bool = True,
    graph_out: str | Path | None = None,
    script_out: str | Path | None = None,
) -> dict:
    """Build a STEP file from RawGcadDocument using G-CAD Core v0.2 pipeline.

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

    # ── 1. Validate spec if dict ──
    if isinstance(spec, dict):
        try:
            spec = RawGcadDocument.model_validate(spec)
        except Exception as exc:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="build_generative_cad",
                error=f"RawGcadDocument validation failed: {exc}",
            ).model_dump()

    # ── 2. Validate and canonicalize ──
    canonical, report = validate_and_canonicalize(spec)
    if canonical is None or not report.ok:
        error_msgs = [f"[{i.code}] {i.message}" for i in report.issues if i.severity == "error"]
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error="Validation failed: " + "; ".join(error_msgs),
            metrics={"validation": report.model_dump()},
        ).model_dump()

    # ── 3. Write canonical JSON ──
    meta_path = step_path.with_suffix(".metadata.json")

    if graph_out:
        graph_path = ensure_inside_workspace(workspace, graph_out)
    else:
        import uuid
        graph_dir = ensure_inside_workspace(workspace, ".generative_cad_graphs")
        graph_dir.mkdir(parents=True, exist_ok=True)
        graph_path = graph_dir / f"gcad_{uuid.uuid4().hex[:12]}.json"

    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(
        json.dumps(canonical.model_dump(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # ── 4. Generate fixed harness ──
    if script_out:
        script_path = ensure_inside_workspace(workspace, script_out)
        ensure_extension(script_path, {".py"})
    else:
        import uuid
        script_dir = ensure_inside_workspace(workspace, ".generative_cad_scripts")
        script_dir.mkdir(parents=True, exist_ok=True)
        script_path = script_dir / f"run_gcad_{uuid.uuid4().hex[:12]}.py"

    harness_script = _generate_harness_script(graph_path, step_path, meta_path)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(harness_script, encoding="utf-8")

    # ── 5. Execute runner via subprocess ──
    timeout = canonical.constraints.max_runtime_seconds
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
            metrics={"graph_path": str(graph_path), "script_path": str(script_path)},
        ).model_dump()

    # ── 6. Assert STEP exists ──
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
            metrics={"graph_path": str(graph_path), "script_path": str(script_path)},
        ).model_dump()

    files_created = [str(step_path), str(graph_path), str(script_path)]

    # ── 7. Assert metadata exists ──
    try:
        assert_file_created(meta_path, "metadata")
    except (FileNotFoundError, ValueError) as exc:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error=f"Metadata sidecar validation failed: {exc}",
            files_created=files_created,
        ).model_dump()

    files_created.append(str(meta_path))

    # ── 8. Validate generative metadata v2 ──
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

    meta_validation = validate_generative_metadata_v2(metadata)
    if not meta_validation["ok"]:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_generative_cad",
            error="Metadata v2 validation failed: "
            + "; ".join(i["message"] for i in meta_validation["issues"]),
            files_created=files_created,
        ).model_dump()

    metrics: dict = {
        "graph_path": str(graph_path),
        "script_path": str(script_path),
        "step_path": str(step_path),
        "step_size_bytes": step_path.stat().st_size,
        "feature_count": len(canonical.nodes),
        "component_count": len(canonical.components),
        "validation": report.model_dump(),
        "canonical_graph_hash": canonical.canonical_graph_hash,
        "metadata_validation": meta_validation,
    }
    warnings: list[str] = list(build_warnings)

    # ── 9. Inspection ──
    if inspect:
        insp_result = inspect_step_with_cadquery(step_path)
        metrics["inspection"] = insp_result

        if insp_result.get("error"):
            warnings.append(f"Inspection unavailable: {insp_result['error']}")
        else:
            # Validate against constraints
            contract_issues = []
            sc = canonical.constraints
            solid_count = insp_result.get("solid_count")
            if solid_count is not None and solid_count != sc.expected_body_count:
                contract_issues.append({
                    "code": "body_count_mismatch",
                    "message": f"Expected {sc.expected_body_count} body(s), got {solid_count}.",
                    "severity": "error",
                })
            if sc.expected_bbox_mm is not None:
                bbox = insp_result.get("bbox_mm")
                if bbox is not None:
                    for i, (exp, act) in enumerate(zip(sc.expected_bbox_mm, bbox)):
                        if abs(exp - act) > sc.bbox_tolerance_mm:
                            contract_issues.append({
                                "code": "bbox_mismatch",
                                "message": f"Bbox axis {i}: expected {exp}, got {act}.",
                                "severity": "error",
                            })

            inspection_validation = {
                "ok": len(contract_issues) == 0,
                "issues": contract_issues,
            }
            metrics["validation"] = inspection_validation

            # Write validation back to metadata
            if meta_path.exists():
                metadata["validation"] = {
                    "core_validation": report.model_dump(),
                    "geometry_preflight": {},
                    "inspection_validation": inspection_validation,
                }
                meta_path.write_text(
                    json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )

            if not inspection_validation["ok"]:
                return EngineeringActionResult(
                    ok=False,
                    software="cadquery",
                    action="build_generative_cad",
                    message="STEP file created but validation failed.",
                    files_created=files_created,
                    metrics=metrics,
                    warnings=warnings,
                    error="; ".join(i["message"] for i in contract_issues),
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
    """Fixed harness — loads canonical JSON, calls run_gcad_core_from_files."""
    return f'''
"""Fixed G-CAD runner harness — auto-generated, contains no LLM CAD code."""
import sys
from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core_from_files

result = run_gcad_core_from_files(
    input_json=r"{graph_path.as_posix()}",
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
