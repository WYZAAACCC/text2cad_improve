"""Generative CAD builder — v1.0: direct pipeline call (no subprocess).

v1.0: Replaces subprocess-based harness execution with direct call to
run_canonical_gcad(). This eliminates the 2000-char truncation of
warnings/degraded_features and preserves full operation metrics.
"""

from __future__ import annotations

import json, uuid
from pathlib import Path

from seekflow_engineering_tools.cadquery_backend.builder import assert_file_created
from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_extension, ensure_inside_workspace
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.pipeline.metadata_v3 import validate_generative_metadata_v3
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad


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

    # v0.4: Legacy GenerativeCADSpec v0.1 is NOT accepted by production builder
    # Check BEFORE model_validate so legacy dicts get a clear error, not confusing Pydantic errors
    if isinstance(spec, dict) and "feature_graph" in spec and "components" not in spec:
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error=(
                "Legacy GenerativeCADSpec v0.1 is not accepted by the v0.4 production builder. "
                "Convert explicitly using generative_cad.compatibility.legacy_spec_adapter in a legacy-only workflow."
            ),
        ).model_dump()

    if isinstance(spec, dict):
        from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
        parse_result = parse_raw_gcad_document(spec)
        if not parse_result.ok:
            return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
                error="RawGcadDocument parse failed: " + "; ".join(
                    f"[{i.code}] {i.message}" for i in parse_result.issues
                )).model_dump()
        spec = parse_result.document

    # Double-check legacy objects (non-dict) are also rejected
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

    # Write validation seed JSON
    validation_seed_path = graph_path.with_suffix(".validation.json")
    validation_seed_path.write_text(
        json.dumps(validation_bundle.to_metadata_dict(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # ── v1.0: Direct pipeline call (replaces subprocess harness) ──
    try:
        run_result = run_canonical_gcad(
            canonical=canonical,
            out_step=step_path,
            metadata_path=meta_path,
            validation_seed=validation_bundle.to_metadata_dict(),
            canonical_ir_path=graph_path,
            validation_seed_path=validation_seed_path,
            require_full_validation_seed=True,
        )
    except Exception as exc:
        import traceback
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error=f"Runtime execution failed: {exc}\n{traceback.format_exc()[-1000:]}",
            metrics={
                "graph_path": str(graph_path),
                "canonical_graph_hash": canonical.canonical_graph_hash,
            },
        ).model_dump()

    # ── Preserve FULL warnings and diagnostics (no 2000-char truncation) ──
    build_warnings = list(run_result.warnings) if run_result.warnings else []
    degraded_features = list(run_result.degraded_features) if run_result.degraded_features else []
    operation_metrics = list(run_result.operation_metrics) if run_result.operation_metrics else []

    if not run_result.ok:
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error=f"Runtime failed: {run_result.error}",
            warnings=build_warnings,
            metrics={
                "graph_path": str(graph_path),
                "canonical_graph_hash": canonical.canonical_graph_hash,
                "degraded_features": degraded_features,
                "operation_metrics": operation_metrics,
            },
        ).model_dump()

    try:
        assert_file_created(step_path, "STEP")
    except (FileNotFoundError, ValueError) as exc:
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error=str(exc),
            warnings=build_warnings,
            metrics={"graph_path": str(graph_path)},
        ).model_dump()

    files_created = [str(step_path), str(graph_path)]

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
    meta_validation = validate_generative_metadata_v3(
        metadata, canonical=canonical, registry=default_registry(),
        require_validation_ok=False, require_final_artifact_hash=False,
    )
    if not meta_validation["ok"]:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error="Metadata v3 invalid: " + "; ".join(i["message"] for i in meta_validation["issues"]),
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
        insp_result = {}  # type: ignore[assignment]

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
    meta_validation_final = validate_generative_metadata_v3(
        metadata, canonical=canonical, registry=default_registry(),
        require_validation_ok=True, require_final_artifact_hash=True,
    )
    if not meta_validation_final["ok"]:
        return EngineeringActionResult(ok=False, software="cadquery", action="build_generative_cad",
            error="Metadata v3 final validation failed: " + "; ".join(i["message"] for i in meta_validation_final["issues"]),
            files_created=files_created).model_dump()

    insp_data = insp_result if inspect else {}
    metrics = {
        "graph_path": str(graph_path),
        "step_path": str(step_path), "step_size_bytes": step_path.stat().st_size,
        "feature_count": len(canonical.nodes), "component_count": len(canonical.components),
        "core_validation": report.model_dump(),
        "canonical_graph_hash": canonical.canonical_graph_hash,
        "metadata_validation": meta_validation_final,
        "inspection": insp_data,
        "inspection_validation": insp_val,
        # v1.0: Full runtime diagnostics (no truncation)
        "warnings": build_warnings,
        "degraded_features": degraded_features,
        "operation_metrics": operation_metrics,
    }
    warnings_list = list(build_warnings)

    from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
    artifact = build_canonical_step_artifact(
        canonical=canonical, step_path=step_path, metadata_path=meta_path,
        graph_path=str(graph_path), validation_seed_path=str(validation_seed_path),
        runner_script_path=str(graph_path),  # graph serves as the "script" path for compat
        validation=validation_meta,
        inspection=insp_val,
    )

    # v0.9: extended artifact/metadata consistency checks
    # v1.1 (P4): artifact state machine — builder returns validated_reference_step
    metadata_gm = metadata.get("generative_metadata", {})
    if artifact.get("canonical_graph_hash") != metadata_gm.get("canonical_graph_hash"):
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error="Artifact/metadata canonical_graph_hash mismatch.",
            files_created=files_created,
        ).model_dump()
    if artifact.get("validation") != metadata.get("validation"):
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error="Artifact/metadata validation proof mismatch.",
            files_created=files_created,
        ).model_dump()
    if artifact.get("native_rebuild_allowed") is not False:
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error="Artifact native_rebuild_allowed must be False.",
            files_created=files_created,
        ).model_dump()
    if artifact.get("state") != "validated_reference_step":
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error=f"Artifact state must be validated_reference_step, got {artifact.get('state')!r}.",
            files_created=files_created,
        ).model_dump()
    if artifact.get("step_import_candidate") is not True:
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error="Artifact step_import_candidate must be True.",
            files_created=files_created,
        ).model_dump()
    if artifact.get("step_import_allowed") is not False:
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error="Artifact step_import_allowed must be False (only import gate may set true).",
            files_created=files_created,
        ).model_dump()
    if artifact.get("requires_import_gate") is not True:
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error="Artifact requires_import_gate must be True.",
            files_created=files_created,
        ).model_dump()
    if artifact.get("step_path") != str(step_path):
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error="Artifact step_path mismatch.",
            files_created=files_created,
        ).model_dump()
    if artifact.get("metadata_path") != str(meta_path):
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error="Artifact metadata_path mismatch.",
            files_created=files_created,
        ).model_dump()
    artifact_dialects = artifact.get("selected_dialects")
    metadata_dialects = metadata_gm.get("selected_dialects")
    if artifact_dialects != metadata_dialects:
        return EngineeringActionResult(
            ok=False, software="cadquery", action="build_generative_cad",
            error="Artifact/metadata selected_dialects mismatch.",
            files_created=files_created,
        ).model_dump()

    metrics["artifact"] = artifact
    metrics["metadata_path"] = str(meta_path)

    return EngineeringActionResult(ok=True, software="cadquery", action="build_generative_cad",
        message=f"Generative CAD STEP created: {step_path}", files_created=files_created,
        metrics=metrics, warnings=warnings_list).model_dump()
