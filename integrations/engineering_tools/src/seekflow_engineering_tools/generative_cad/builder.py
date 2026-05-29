"""Generative CAD builder — v0.4: hard-gate, strict validation, metadata proof."""

from __future__ import annotations

import json, subprocess, sys, uuid
from pathlib import Path

from seekflow_engineering_tools.cadquery_backend.builder import assert_file_created
from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_extension, ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle


def build_generative_cad_model(
    spec: RawGcadDocument | dict,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    inspect: bool = True,
    strict_inspection: bool = True,
    graph_out: str | Path | None = None,
    script_out: str | Path | None = None,
) -> dict:
    workspace = config.workspace_root
    step_path = ensure_inside_workspace(workspace, out_step)
    ensure_extension(step_path, {".step", ".stp"})
    step_path.parent.mkdir(parents=True, exist_ok=True)

    if step_path.exists() and not config.allow_overwrite:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error=f"Output file {step_path} already exists.").model_dump()

    if isinstance(spec, dict):
        try: spec = RawGcadDocument.model_validate(spec)
        except Exception as exc:
            return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
                error=f"RawGcadDocument validation failed: {exc}").model_dump()

    # v0.4: Legacy GenerativeCADSpec v0.1 is NOT accepted by production builder
    if hasattr(spec, "feature_graph") and not hasattr(spec, "components"):
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error=(
                "Legacy GenerativeCADSpec v0.1 is not accepted by the v0.4 production builder. "
                "Convert explicitly using generative_cad.compatibility.legacy_spec_adapter in a legacy-only workflow."
            ),
        ).model_dump()

    # v0.4: use bundle to capture all stage reports
    canonical, report, validation_bundle = validate_and_canonicalize_with_bundle(spec)
    if canonical is None or not report.ok:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error="Validation failed: " + "; ".join(f"[{i.code}] {i.message}" for i in report.issues if i.severity == "error"),
            metrics={"core_validation": report.model_dump()}).model_dump()

    meta_path = step_path.with_suffix(".metadata.json")

    # Graph path with workspace guard
    graph_dir = ensure_inside_workspace(workspace, ".generative_cad_graphs")
    graph_dir.mkdir(parents=True, exist_ok=True)
    if graph_out is not None:
        graph_path = ensure_inside_workspace(workspace, graph_out)
    else:
        graph_path = graph_dir / f"gcad_{uuid.uuid4().hex[:12]}.json"
    graph_path = Path(graph_path)
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(json.dumps(canonical.model_dump(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    # Script path with workspace guard
    script_dir = ensure_inside_workspace(workspace, ".generative_cad_scripts")
    script_dir.mkdir(parents=True, exist_ok=True)
    if script_out is not None:
        script_path = ensure_inside_workspace(workspace, script_out)
    else:
        script_path = script_dir / f"run_gcad_{uuid.uuid4().hex[:12]}.py"
    script_path = Path(script_path)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_generate_harness_script(Path(graph_path), step_path, meta_path), encoding="utf-8")

    timeout = canonical.constraints.max_runtime_seconds
    try:
        result = subprocess.run([sys.executable, str(script_path)], capture_output=True, text=True, timeout=timeout, cwd=str(step_path.parent))
    except subprocess.TimeoutExpired:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error=f"Generative CAD build timed out after {timeout}s.").model_dump()

    stdout_tail = (result.stdout or "")[-2000:]; stderr_tail = (result.stderr or "")[-2000:]
    build_warnings = [line[len("CQ_WARNING:"):].strip() for line in (result.stdout or "").split("\n") if line.startswith("CQ_WARNING:")]

    if result.returncode != 0:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error=f"Runner failed (rc={result.returncode}). {(result.stderr or '')[:200]}",
            stdout_tail=stdout_tail, stderr_tail=stderr_tail, warnings=build_warnings,
            metrics={"graph_path": str(graph_path), "script_path": str(script_path)}).model_dump()

    try: assert_file_created(step_path, "STEP")
    except (FileNotFoundError, ValueError) as exc:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error=str(exc), stdout_tail=stdout_tail, stderr_tail=stderr_tail,
            metrics={"graph_path": str(graph_path), "script_path": str(script_path)}).model_dump()

    files_created = [str(step_path), str(graph_path), str(script_path)]

    try: assert_file_created(meta_path, "metadata")
    except (FileNotFoundError, ValueError) as exc:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error=f"Metadata missing: {exc}", files_created=files_created).model_dump()
    files_created.append(str(meta_path))

    try: metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error=f"Metadata JSON invalid: {exc}", files_created=files_created).model_dump()

    # Initial metadata validation (NO require_validation_ok — runtime/inspection not yet attached)
    meta_validation = validate_generative_metadata_v2(metadata, canonical=canonical, registry_check=True, require_validation_ok=False)
    if not meta_validation["ok"]:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error="Metadata v2 invalid: " + "; ".join(i["message"] for i in meta_validation["issues"]),
            files_created=files_created).model_dump()

    # ── Inspection ──
    insp_val: dict = {"ok": True, "issues": []}
    if inspect:
        insp_result = inspect_step_with_cadquery(step_path)
        if insp_result.get("error"):
            if strict_inspection:
                return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
                    error=f"Strict inspection failed: {insp_result['error']}",
                    files_created=files_created).model_dump()
            else:
                build_warnings.append(f"Inspection unavailable: {insp_result['error']}")
                insp_val = {"ok": True, "skipped": True, "warning": insp_result["error"]}
        else:
            contract_issues = []
            sc = canonical.constraints
            sc_count = insp_result.get("solid_count")
            if sc_count is not None and sc_count != sc.expected_body_count:
                contract_issues.append({"code": "inspection_body_count_mismatch", "message": f"Expected {sc.expected_body_count} body(s), got {sc_count}.", "severity": "error"})
            if sc.expected_bbox_mm is not None:
                bbox = insp_result.get("bbox_mm")
                if bbox is not None:
                    for i, (exp, act) in enumerate(zip(sc.expected_bbox_mm, bbox)):
                        if abs(exp - act) > sc.bbox_tolerance_mm:
                            contract_issues.append({"code": "inspection_bbox_mismatch", "message": f"Bbox[{i}]: expected {exp}, got {act}.", "severity": "error"})
            insp_val = {"ok": len(contract_issues) == 0, "issues": contract_issues}
            if not insp_val["ok"]:
                return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
                    message="STEP created but inspection validation failed.", files_created=files_created,
                    error="; ".join(i["message"] for i in contract_issues)).model_dump()
    else:
        insp_val = {"ok": None, "skipped": True, "message": "Inspection was disabled."}

    # ── Write full validation proof into metadata ──
    validation_meta = validation_bundle.to_metadata_dict()
    # Preserve runtime postconditions from runner-generated metadata
    runner_validation = metadata.get("validation", {})
    validation_meta["runtime_postconditions"] = runner_validation.get(
        "runtime_postconditions",
        {"ok": False, "stage": "runtime_postconditions", "issues": [{"code": "missing_runtime_postconditions_report", "message": "Runtime did not produce postconditions report.", "severity": "error"}]},
    )
    validation_meta["inspection_validation"] = insp_val
    metadata["validation"] = validation_meta
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    # ── Final revalidation with require_validation_ok=True ──
    meta_validation_final = validate_generative_metadata_v2(
        metadata, canonical=canonical, registry_check=True, require_validation_ok=True,
    )
    if not meta_validation_final["ok"]:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error="Metadata v2.1 final validation failed: " + "; ".join(i["message"] for i in meta_validation_final["issues"]),
            files_created=files_created).model_dump()

    metrics = {
        "graph_path": str(graph_path), "script_path": str(script_path),
        "step_path": str(step_path), "step_size_bytes": step_path.stat().st_size,
        "feature_count": len(canonical.nodes), "component_count": len(canonical.components),
        "core_validation": report.model_dump(),
        "canonical_graph_hash": canonical.canonical_graph_hash,
        "metadata_validation": meta_validation_final,
        "inspection": insp_result if inspect else {},
        "inspection_validation": insp_val,
    }
    warnings_list = list(build_warnings)

    from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
    metrics["artifact"] = build_canonical_step_artifact(
        canonical=canonical, step_path=step_path, metadata_path=meta_path,
        graph_path=str(graph_path), runner_script_path=str(script_path),
        validation=validation_meta,
    )

    return EngineeringActionResult(ok=True, software="cadquery", action="build_generative_cad",
        message=f"Generative CAD STEP created: {step_path}", files_created=files_created,
        stdout_tail=stdout_tail, stderr_tail=stderr_tail, metrics=metrics, warnings=warnings_list).model_dump()


def _generate_harness_script(graph_path: Path, out_step: Path, metadata_path: Path) -> str:
    """Fixed harness — calls run_canonical_gcad_from_files (canonical JSON, NOT raw)."""
    return f'''
"""Fixed G-CAD runner harness — auto-generated, no LLM CAD code."""
import sys
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files

result = run_canonical_gcad_from_files(
    canonical_json=r"{graph_path.as_posix()}",
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
