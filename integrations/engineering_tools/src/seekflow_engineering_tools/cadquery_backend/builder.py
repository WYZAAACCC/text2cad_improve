"""CadQuery build backend — executes CadQuery scripts to produce real STEP files."""

from __future__ import annotations

import json
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
from seekflow_engineering_tools.repair.loop import make_repair_diagnostics


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


def _run_mechanical_validation(spec: CADPartSpec, step_path: Path, inspection: dict) -> dict:
    """Run mechanical validation for primitive features.

    FAIL-CLOSED: if the mechanical validation module cannot be imported,
    that is a hard error — we cannot validate the model.
    """
    try:
        from seekflow_engineering_tools.mechanical_validation.common import (
            validate_mechanical_primitives,
        )
        return validate_mechanical_primitives(spec, step_path, inspection)
    except ImportError as exc:
        return {
            "ok": False,
            "results": [],
            "issues": [
                {
                    "code": "mechanical_validation_unavailable",
                    "message": f"Mechanical validation module could not be imported: {exc}",
                    "severity": "error",
                }
            ],
        }


def _assert_metadata_sidecar(step_path: Path, spec: CADPartSpec) -> dict:
    """Load and validate the metadata sidecar for a primitive build.

    Uses the generic validate_primitive_metadata_v1 for all primitives,
    then applies per-primitive checks (e.g. is_standard_involute for gears).

    Raises ValueError or FileNotFoundError if:
    - metadata file is missing or empty
    - primitive_metadata / build_warnings top-level keys are missing
    - any PrimitiveFeature has no entry in primitive_metadata
    - any primitive fails generic metadata validation
    - gear primitive is missing is_standard_involute
    """
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )

    meta_path = step_path.with_suffix(".metadata.json")
    assert_file_created(meta_path, "metadata")

    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Metadata JSON is invalid: {exc}")

    if "primitive_metadata" not in metadata:
        raise ValueError("Metadata missing 'primitive_metadata' key")
    if "build_warnings" not in metadata:
        raise ValueError("Metadata missing 'build_warnings' key")

    pm = metadata.get("primitive_metadata", {})

    for feat in spec.features:
        if feat.type != "primitive":
            continue

        pname = feat.primitive_name
        primitive_entry = pm.get(pname)
        if primitive_entry is None:
            raise ValueError(
                f"Metadata missing primitive entry for '{pname}'"
            )

        # ── Generic metadata validation (v1) ──
        v_result = validate_primitive_metadata_v1(pname, primitive_entry)
        if not v_result.get("ok"):
            issue_msgs = [i["message"] for i in v_result.get("issues", [])]
            raise ValueError(
                f"Primitive metadata validation failed for '{pname}': "
                + "; ".join(issue_msgs)
            )

        # ── Per-primitive checks ──
        if pname == "involute_spur_gear":
            if "is_standard_involute" not in primitive_entry:
                raise ValueError(
                    "Gear metadata missing 'is_standard_involute'"
                )

    return metadata


def _check_fallback_policy(spec: CADPartSpec, metadata: dict) -> tuple[bool, list[str]]:
    """Check if visual fallback is allowed for the given spec.

    Returns (is_hard_fail, warnings).

    Rules:
    - quality_grade="industrial_brep" or "validated" with cadquery_visual_fallback → HARD FAIL
    - expected_kernel="cq_gears" with cadquery_visual_fallback → HARD FAIL (regardless of quality_grade)
    - quality_grade="visual_fallback" or allow_visual_fallback=True → warning only
    """
    pm = metadata.get("primitive_metadata", {})
    gear_meta = pm.get("involute_spur_gear", {})
    kernel = gear_meta.get("kernel", "")
    is_standard = gear_meta.get("is_standard_involute", True)

    if kernel != "cadquery_visual_fallback" and is_standard:
        return False, []  # Not a fallback, no issue

    # Check expected_kernel from validation spec (if set, must match)
    expected_kernel = spec.validation.expected_kernel if spec.validation else None
    if expected_kernel == "cq_gears" and kernel == "cadquery_visual_fallback":
        return True, [
            f"Expected kernel 'cq_gears' but got 'cadquery_visual_fallback'. "
            "Visual fallback is not acceptable when cq_gears is explicitly required. "
            "Install cq_gears for industrial-grade involute profiles.",
            "This fallback is NOT certified involute geometry.",
        ]

    # Check each primitive feature for quality_grade
    for feat in spec.features:
        if feat.type != "primitive" or feat.primitive_name != "involute_spur_gear":
            continue

        quality = feat.parameters.get("quality_grade", "industrial_brep")
        allow_fallback = feat.parameters.get("allow_visual_fallback", False)

        if quality in ("industrial_brep", "validated") and not allow_fallback:
            return True, [
                "Visual fallback gear (cadquery_visual_fallback) is not acceptable "
                f"for quality_grade='{quality}'. Install cq_gears for industrial-grade "
                "involute profiles.",
                "This fallback is NOT certified involute geometry.",
            ]

    return False, [
        "Visual fallback gear used; this is NOT certified involute geometry. "
        "Ensure this is acceptable for your use case.",
    ]


def _load_and_update_metadata(step_path: Path, validation: dict | None = None) -> dict | None:
    """Load metadata sidecar and write back validation results."""
    meta_path = step_path.with_suffix(".metadata.json")
    if not meta_path.exists():
        return None

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))

    if validation is not None:
        metadata["validation"] = validation
        meta_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    return metadata


def build_cadquery_from_cad_ir(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    inspect: bool = True,
    script_out: str | Path | None = None,
) -> dict:
    """Execute a full CadQuery build: compile → run → verify → inspect → validate.

    For primitive features: also runs mechanical validation and metadata sidecar.

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

    # Determine metadata path for primitive features
    meta_path = step_path.with_suffix(".metadata.json")

    has_primitive = any(f.type == "primitive" for f in spec.features)

    # Compile script
    script = compile_cad_ir_to_cadquery_script(
        spec,
        out_step=str(step_path),
        metadata_path=str(meta_path) if has_primitive else None,
    )

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

    # Collect warnings from stdout
    build_warnings: list[str] = []
    for line in (result.stdout or "").split("\n"):
        if line.startswith("CQ_WARNING:"):
            build_warnings.append(line[len("CQ_WARNING:"):].strip())

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
            warnings=build_warnings,
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
            warnings=build_warnings,
            metrics={"script_path": str(script_path)},
        ).model_dump()

    files_created = [str(step_path), str(script_path)]

    # ── Primitive metadata sidecar requirement ──
    if has_primitive:
        try:
            metadata = _assert_metadata_sidecar(step_path, spec)
        except (FileNotFoundError, ValueError) as exc:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="build_from_cad_ir",
                error=f"Metadata sidecar validation failed: {exc}",
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                warnings=build_warnings,
                metrics={"script_path": str(script_path)},
            ).model_dump()

        files_created.append(str(meta_path))

        # ── Fallback gear hard-fail for industrial_brep ──
        is_hard_fail, fallback_warnings = _check_fallback_policy(spec, metadata)
        if is_hard_fail:
            for w in fallback_warnings:
                if w not in build_warnings:
                    build_warnings.append(w)
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="build_from_cad_ir",
                message="STEP created but fallback gear is not engineering-grade.",
                files_created=files_created,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                metrics={
                    "script_path": str(script_path),
                    "script_length": len(script),
                    "step_path": str(step_path),
                    "step_size_bytes": step_path.stat().st_size,
                    "feature_count": len(spec.features),
                },
                warnings=build_warnings,
                error="Visual fallback is not certified involute geometry.",
            ).model_dump()
        for w in fallback_warnings:
            if w not in build_warnings:
                build_warnings.append(w)

    metrics: dict = {
        "script_path": str(script_path),
        "script_length": len(script),
        "step_path": str(step_path),
        "step_size_bytes": step_path.stat().st_size,
        "feature_count": len(spec.features),
    }
    warnings: list[str] = list(build_warnings)

    if inspect:
        insp_result = _run_inspection(step_path, spec)
        metrics["inspection"] = insp_result["inspection"]
        validation = insp_result["validation"]
        metrics["validation"] = validation

        # Mechanical validation for primitives
        if has_primitive:
            mv_result = _run_mechanical_validation(spec, step_path, insp_result["inspection"])
            metrics["mechanical_validation"] = mv_result

            # Write validation back to metadata
            metadata = _load_and_update_metadata(step_path, validation={
                "inspection_validation": validation,
                "mechanical_validation": mv_result,
            })

            if metadata:
                for md_warn in metadata.get("build_warnings", []):
                    if md_warn not in warnings:
                        warnings.append(md_warn)

            # Mechanical validation failure → fail the build
            if not mv_result.get("ok"):  # fail-closed: missing ok → fail
                mech_errors = []
                for r in mv_result.get("results", []):
                    for issue in r.get("issues", []):
                        if issue.get("severity") == "error":
                            mech_errors.append(issue["message"])
                return EngineeringActionResult(
                    ok=False,
                    software="cadquery",
                    action="build_from_cad_ir",
                    message="STEP file created but mechanical validation failed.",
                    files_created=files_created,
                    stdout_tail=stdout_tail,
                    stderr_tail=stderr_tail,
                    metrics=metrics,
                    warnings=warnings,
                    error="; ".join(mech_errors) if mech_errors else "Mechanical validation failed.",
                ).model_dump()

        if not validation.get("ok"):  # fail-closed: missing ok → fail
            errors = [i["message"] for i in validation.get("issues", []) if i.get("severity") == "error"]
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
                files_created=files_created,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                metrics=metrics,
                warnings=warnings,
                error="; ".join(errors),
            ).model_dump()

    # Fallback gear must NOT silently succeed — check explicit allow
    has_fallback = any("visual_fallback" in w.lower() or "not certified" in w.lower() for w in warnings)
    if has_fallback:
        # Determine if visual fallback is explicitly allowed
        fallback_allowed = False
        for feat in spec.features:
            if feat.type == "primitive" and feat.primitive_name == "involute_spur_gear":
                quality = feat.parameters.get("quality_grade", "industrial_brep")
                allow = feat.parameters.get("allow_visual_fallback", False)
                if quality == "visual_fallback" or allow:
                    fallback_allowed = True
                    break
        if not fallback_allowed:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="build_from_cad_ir",
                message="STEP file created but fallback gear is not engineering-grade.",
                files_created=files_created,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                metrics=metrics,
                warnings=warnings,
                error="Visual fallback is not certified involute geometry.",
            ).model_dump()
        # Explicitly allowed fallback — ok but with strong warnings
        return EngineeringActionResult(
            ok=True,
            software="cadquery",
            action="build_from_cad_ir",
            message=f"STEP file created (with explicitly allowed fallback): {step_path}",
            files_created=files_created,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            metrics=metrics,
            warnings=warnings,
        ).model_dump()

    return EngineeringActionResult(
        ok=True,
        software="cadquery",
        action="build_from_cad_ir",
        message=f"STEP file created and validated: {step_path}",
        files_created=files_created,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        metrics=metrics,
        warnings=warnings,
    ).model_dump()
