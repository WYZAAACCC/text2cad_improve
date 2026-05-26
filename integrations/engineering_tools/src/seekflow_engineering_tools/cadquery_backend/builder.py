"""CadQuery build backend — executes CadQuery scripts to produce real STEP files."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from seekflow_engineering_tools.cadquery_backend.compiler import compile_cad_ir_to_cadquery_script
from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_extension, ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.ir.cad import CADPartSpec


def assert_file_created(path: Path, label: str = "output", min_size: int = 1) -> None:
    """Raise if *path* does not exist or is empty."""
    if not path.exists():
        raise FileNotFoundError(f"{label} file was not created: {path}")
    if path.stat().st_size < min_size:
        raise ValueError(f"{label} file is empty or too small: {path} ({path.stat().st_size} bytes)")


def _run_inspection(step_path: Path, spec: CADPartSpec) -> dict:
    """Run CadQuery inspection on a STEP file and validate against spec."""
    info = inspect_step_with_cadquery(step_path)
    if info.get("error"):
        return {"inspection": info, "validation": {"ok": False, "error": info["error"]}}

    errors: list[str] = []
    warnings: list[str] = []
    vs = spec.validation

    if vs.expected_bbox_mm is not None:
        actual = info.get("bbox_mm")
        if actual is None:
            errors.append("Cannot inspect bbox (cadquery may not be installed)")
        elif actual is not None:
            for i, (exp, act) in enumerate(zip(vs.expected_bbox_mm, actual)):
                dim = ["x", "y", "z"][i]
                if abs(exp - act) > vs.tolerance_mm:
                    errors.append(
                        f"bbox {dim}: expected {exp} mm, got {act:.1f} mm "
                        f"(delta={abs(exp - act):.1f} > tolerance {vs.tolerance_mm})"
                    )

    if vs.expected_body_count is not None:
        actual = info.get("solid_count")
        if actual is not None and actual != vs.expected_body_count:
            errors.append(
                f"body_count: expected {vs.expected_body_count}, got {actual}"
            )

    if vs.expected_hole_count is not None:
        actual = info.get("hole_count_estimate")
        if actual is None:
            warnings.append("Cannot estimate hole count for validation")
        elif actual != vs.expected_hole_count:
            errors.append(
                f"hole_count: expected {vs.expected_hole_count}, got {actual}"
            )

    if vs.expected_through_hole_count is not None:
        actual = info.get("through_hole_count_estimate")
        if actual is None:
            warnings.append("Cannot estimate through hole count for validation")
        elif actual != vs.expected_through_hole_count:
            errors.append(
                f"through_hole_count: expected {vs.expected_through_hole_count}, got {actual}"
            )

    validation_ok = len(errors) == 0
    return {
        "inspection": info,
        "validation": {
            "ok": validation_ok,
            "errors": errors,
            "warnings": warnings,
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

    # Write script
    if script_out:
        script_path = ensure_inside_workspace(workspace, script_out)
        ensure_extension(script_path, {".py"})
    else:
        script_path = Path(tempfile.mktemp(suffix="_cq_build.py"))

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
    validation_report = None

    if inspect:
        insp_result = _run_inspection(step_path, spec)
        metrics["inspection"] = insp_result["inspection"]
        validation_report = insp_result["validation"]
        metrics["validation"] = validation_report
        warnings.extend(validation_report.get("warnings", []))

        if not validation_report.get("ok", True):
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
                error="; ".join(validation_report.get("errors", [])),
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
