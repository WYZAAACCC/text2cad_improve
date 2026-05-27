"""CadQuery build backend — executes CadQuery scripts to produce real STEP files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from seekflow_engineering_tools.cadquery_backend.compiler import compile_cad_ir_to_cadquery_script
from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_extension, ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.inspection.common import ModelInspection
from seekflow_engineering_tools.inspection.validation import validate_inspection_against_spec
from seekflow_engineering_tools.ir.cad import CADPartSpec
from seekflow_engineering_tools.repair.diagnostics import build_repair_prompt
from seekflow_engineering_tools.repair.loop import classify_failure, make_repair_diagnostics


def assert_file_created(path: Path, label: str = "output", min_size: int = 1) -> None:
    """Raise if *path* does not exist or is empty."""
    if not path.exists():
        raise FileNotFoundError(f"{label} file was not created: {path}")
    if path.stat().st_size < min_size:
        raise ValueError(f"{label} file is empty or too small: {path} ({path.stat().st_size} bytes)")


def _inspection_info_to_model(info: dict) -> ModelInspection:
    """Convert raw inspector dict to ModelInspection."""
    return ModelInspection(
        bbox_mm=info.get("bbox_mm"),
        volume_mm3=info.get("volume_mm3"),
        body_count=info.get("solid_count"),
        hole_count_estimate=info.get("hole_count_estimate"),
        through_hole_count_estimate=info.get("through_hole_count_estimate"),
        warnings=[],
    )


def _run_inspection(step_path: Path, spec: CADPartSpec) -> dict:
    """Run CadQuery inspection on a STEP file and validate against spec.

    Uses unified ModelInspection and validate_inspection_against_spec.
    """
    info = inspect_step_with_cadquery(step_path)
    if info.get("error"):
        return {
            "inspection": info,
            "validation": {
                "ok": False,
                "issues": [{"code": "inspect_error", "message": info["error"], "severity": "error"}],
            },
        }

    model = _inspection_info_to_model(info)
    report = validate_inspection_against_spec(model, spec)

    return {
        "inspection": info,
        "validation": {
            "ok": report.ok,
            "issues": [i.model_dump() for i in report.issues],
        },
    }


def build_cadquery_from_cad_ir(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    inspect: bool = True,
    script_out: str | Path | None = None,
) -> dict:
    """Execute a full CadQuery build: compile → run → verify → inspect → validate.

    Returns an EngineeringActionResult dict.
    """
    workspace = config.workspace_root
    step_path = ensure_inside_workspace(workspace, out_step)
    ensure_extension(step_path, {".step", ".stp"})

    step_path.parent.mkdir(parents=True, exist_ok=True)

    if step_path.exists() and not config.allow_overwrite:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_from_cad_ir",
            error=f"Output file {step_path} already exists.",
        ).model_dump()

    # Compile script
    script = compile_cad_ir_to_cadquery_script(spec, out_step=str(step_path))

    # Script path — always inside workspace
    if script_out:
        script_path = ensure_inside_workspace(workspace, script_out)
        ensure_extension(script_path, {".py"})
    else:
        script_dir = ensure_inside_workspace(workspace, ".cadquery_scripts")
        script_dir.mkdir(parents=True, exist_ok=True)
        import uuid
        script_path = script_dir / f"build_{uuid.uuid4().hex[:12]}.py"

    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8")

    # Execute script
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(step_path.parent),
        )
    except subprocess.TimeoutExpired:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_from_cad_ir",
            error="CadQuery build timed out after 120 seconds.",
        ).model_dump()

    stdout_tail = (result.stdout or "")[-2000:]
    stderr_tail = (result.stderr or "")[-2000:]

    if result.returncode != 0:
        repair = make_repair_diagnostics(
            stage="execute",
            error_type="script_execution_failed",
            message=f"CadQuery script failed (rc={result.returncode}). Stderr: {(result.stderr or '')[:200]}",
            spec=spec,
            suggested_fix="Check CadQuery API usage and geometry constraints in the generated script.",
        )
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_from_cad_ir",
            error=f"CadQuery script failed (rc={result.returncode}).",
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            metrics={
                "script_path": str(script_path),
                "script_length": len(script),
                "repair_diagnostics": repair,
            },
        ).model_dump()

    # Verify STEP file created
    try:
        assert_file_created(step_path, "STEP")
    except (FileNotFoundError, ValueError) as exc:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_from_cad_ir",
            error=str(exc),
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            metrics={"script_path": str(script_path)},
        ).model_dump()

    metrics: dict = {
        "script_path": str(script_path),
        "script_length": len(script),
        "step_path": str(step_path),
        "step_size_bytes": step_path.stat().st_size,
        "feature_count": len(spec.features),
    }
    warnings: list[str] = []

    if inspect:
        insp_result = _run_inspection(step_path, spec)
        metrics["inspection"] = insp_result["inspection"]
        validation = insp_result["validation"]
        metrics["validation"] = validation

        if not validation.get("ok", True):
            errors = [i["message"] for i in validation.get("issues", []) if i.get("severity") == "error"]
            # Wire repair diagnostics into metrics
            repair = make_repair_diagnostics(
                stage="validate",
                error_type="validation_failed",
                message="; ".join(errors),
                spec=spec,
                validation_report=validation,
                suggested_fix="Check CAD-IR dimensions and body count expectations.",
            )
            metrics["repair_diagnostics"] = repair
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="build_from_cad_ir",
                message="STEP file created but validation failed.",
                files_created=[str(step_path), str(script_path)],
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                metrics=metrics,
                warnings=warnings,
                error="; ".join(errors),
            ).model_dump()

    return EngineeringActionResult(
        ok=True,
        software="cadquery",
        action="build_from_cad_ir",
        message=f"STEP file created and validated: {step_path}",
        files_created=[str(step_path), str(script_path)],
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        metrics=metrics,
        warnings=warnings,
    ).model_dump()
