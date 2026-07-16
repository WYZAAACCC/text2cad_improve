"""Unified authoring build pipeline — explicit wrapper with audit trail.

Provides generate_validate_build_step() which orchestrates the full
Text → staged authoring → autofix → validate → canonical → runtime → STEP
pipeline and produces a complete output directory with report_v2.json.

This is the recommended entry point for production use. It does NOT modify
validate_and_canonicalize_with_bundle, which remains fail-closed.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import (
    auto_fix_with_report,
)
from seekflow_engineering_tools.generative_cad.authoring.pipeline import (
    generate_gcad_from_user_request,
)
from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash
from seekflow_engineering_tools.generative_cad.llm.models import AuthoringLlmConfig
from seekflow_engineering_tools.generative_cad.validation.pipeline import (
    validate_and_canonicalize_with_bundle,
)


# ── Result types ─────────────────────────────────────────────────────────────


class AuthoringBuildResult(BaseModel):
    """Full result of generate_validate_build_step."""
    model_config = ConfigDict(extra="forbid")

    case_id: str = ""
    ok: bool = False
    step_ok: bool = False

    # Staged outputs
    route_plan: dict[str, Any] | None = None
    feature_sequence: dict[str, Any] | None = None
    node_params: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Validation stages
    raw_original_valid: bool = False
    autofix_applied: bool = False
    raw_fixed_valid: bool = False
    canonical_valid: bool = False
    runtime_valid: bool = False
    artifact_valid: bool = False
    semantic_valid: bool | None = None

    final_error: str | None = None
    report_v2: dict[str, Any] = Field(default_factory=dict)

    # v6: Spatial frontend
    spatial_frontend: dict[str, Any] | None = None
    spatial_contract_hash: str | None = None
    failures: list[dict[str, Any]] = Field(default_factory=list)


# ── Main entry point ─────────────────────────────────────────────────────────


def generate_validate_build_step(
    *,
    user_request: str,
    llm_config: AuthoringLlmConfig,
    dialect_registry,  # DialectRegistry
    base_package_registry,  # BasePackageRegistry
    out_dir: Path,
    route_caller=None,  # LlmToolCaller
    feature_sequence_caller=None,  # LlmToolCaller
    node_params_caller=None,  # LlmToolCaller
    repair_caller=None,  # LlmToolCaller
    allow_autofix: bool = True,
    max_repair_attempts: int = 2,
    # ── v6: Spatial frontend ──
    enable_spatial_frontend: bool = False,
    spatial_mode: str = "guided",
    object_graph_caller=None,
    spatial_plan_caller=None,
    question_caller=None,
    answer_normalizer_caller=None,
    spatial_user_answers=None,
    spatial_session_state=None,
    # v6.3: Auto spatial mode — when True, auto-enables spatial frontend
    # for multi-component cases detected at routing stage
    auto_spatial: bool = False,
) -> AuthoringBuildResult:
    """Execute the full Text → STEP pipeline with staged authoring and audit.

    v6: enable_spatial_frontend=True adds Stage 0 spatial intent resolution
    before routing. For single-component cases the frontend auto-skips.
    Spatial contract is saved as a sidecar file for Phase C constraint resolution.

    Args:
        user_request: Natural language part description.
        llm_config: LLM configuration for router/author/repair roles.
        dialect_registry: Frozen DialectRegistry.
        base_package_registry: BasePackageRegistry.
        out_dir: Output directory (created if missing).
        route_caller: Route-plan LLM caller (mock or real).
        feature_sequence_caller: Feature sequence LLM caller.
        node_params_caller: Per-node params LLM caller.
        repair_caller: Repair LLM caller.
        allow_autofix: Enable deterministic autofix after validation failure.
        max_repair_attempts: Max LLM repair retry rounds.
        enable_spatial_frontend: v6 spatial intent resolution (Stage 0).
        spatial_mode: "guided" | "auto_conservative" | "auto_mechanical" | "precision".
        object_graph_caller: LLM caller for MechanicalObjectGraphDraft extraction.

    Returns:
        AuthoringBuildResult with full stage-by-stage status and report_v2.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    node_params_dir = out_dir / "node_params"
    node_params_dir.mkdir(parents=True, exist_ok=True)

    result = AuthoringBuildResult()
    report_v2: dict[str, Any] = {
        "case_id": "",
        "ok": False,
        "step_ok": False,
        "raw_original_valid": False,
        "autofix_applied": False,
        "raw_fixed_valid": False,
        "canonical_valid": False,
        "runtime_valid": False,
        "artifact_valid": False,
        "semantic_valid": None,
        "final_error": None,
        "hashes": {},
        "autofix": {},
        "validation_stages_run": [],
    }

    # ── Save prompt ──
    (out_dir / "prompt.txt").write_text(user_request, encoding="utf-8")

    # ════════════════════════════════════════════════════════════
    # v6: Stage 0 — Spatial Frontend (intent resolution)
    # v6.3: auto_spatial mode — auto-enable when object_graph_caller provided
    # ════════════════════════════════════════════════════════════
    should_run_spatial = (
        enable_spatial_frontend or (auto_spatial and object_graph_caller is not None)
    )
    if should_run_spatial and object_graph_caller is not None:
        try:
            from seekflow_engineering_tools.generative_cad.authoring.spatial.pipeline import (
                run_spatial_authoring_frontend,
            )
            spatial_result = run_spatial_authoring_frontend(
                user_request=user_request,
                llm_config=llm_config,
                dialect_registry=dialect_registry,
                base_package_registry=base_package_registry,
                object_graph_caller=object_graph_caller,
                spatial_plan_caller=spatial_plan_caller,
                question_caller=question_caller,
                answer_normalizer_caller=answer_normalizer_caller,
                user_answers=spatial_user_answers,
                session_state=spatial_session_state,
                mode=spatial_mode,
            )
            result.spatial_frontend = (
                spatial_result.model_dump() if spatial_result else None
            )

            if spatial_result.needs_clarification:
                result.final_error = "spatial_clarification_needed"
                return result

            # Save spatial contract sidecar for Phase C constraint resolution
            if spatial_result.constraint_graph is not None:
                sc_path = out_dir / "spatial_contract.json"
                sc_path.write_text(
                    json.dumps(
                        spatial_result.constraint_graph.model_dump(),
                        indent=2, default=str, ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
        except Exception as exc:
            result.failures.append({
                "code": "CONTEXT_BUILD_ERROR",
                "stage": "spatial_frontend",
                "message": f"spatial frontend failed: {exc}",
            })
    # ════════════════════════════════════════════════════════════

    try:
        # ── Stage 1–4: Staged authoring (RoutePlan → FeatureSequence → NodeParams → Assemble) ──
        pipeline_result = generate_gcad_from_user_request(
            user_request=user_request,
            llm_config=llm_config,
            dialect_registry=dialect_registry,
            base_package_registry=base_package_registry,
            route_caller=route_caller,
            feature_sequence_caller=feature_sequence_caller,
            node_params_caller=node_params_caller,
            repair_caller=repair_caller,
            max_repair_attempts=max_repair_attempts,
            allow_autofix=allow_autofix,
        )

        # Save staged outputs
        if pipeline_result.route_plan:
            rp_dict = pipeline_result.route_plan.model_dump()
            (out_dir / "route_plan.json").write_text(
                json.dumps(rp_dict, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            result.route_plan = rp_dict

        if pipeline_result.feature_sequence:
            fs_dict = pipeline_result.feature_sequence.model_dump()
            (out_dir / "feature_sequence.json").write_text(
                json.dumps(fs_dict, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            result.feature_sequence = fs_dict

        for nid, np in pipeline_result.node_params.items():
            np_dict = np.model_dump()
            (node_params_dir / f"{nid}.json").write_text(
                json.dumps(np_dict, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            result.node_params[nid] = np_dict

        # ── Stage 5: Raw assembly exists? ──
        if pipeline_result.raw_assembly is None:
            result.final_error = "Raw assembly failed — no raw_document produced"
            report_v2["final_error"] = result.final_error
            result.report_v2 = report_v2
            (out_dir / "report_v2.json").write_text(
                json.dumps(report_v2, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            return result

        raw_original = pipeline_result.raw_assembly.raw_document
        (out_dir / "raw_original.json").write_text(
            json.dumps(raw_original, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        report_v2["hashes"]["raw_original"] = pipeline_result.raw_assembly.source_feature_sequence_hash

        # ── Stage 6: Validate raw_original ──
        canonical, v_report, bundle = validate_and_canonicalize_with_bundle(raw_original)
        result.raw_original_valid = v_report.ok if v_report else False
        report_v2["raw_original_valid"] = result.raw_original_valid
        report_v2["validation_stages_run"] = v_report.stages_run if v_report else []

        (out_dir / "raw_original_validation.json").write_text(
            json.dumps(_report_to_dict(v_report), indent=2, ensure_ascii=False), encoding="utf-8",
        )

        raw_to_use = raw_original

        # ── Stage 7: Deterministic autofix ──
        if not result.raw_original_valid and allow_autofix:
            try:
                fixed_doc, autofix_report = auto_fix_with_report(
                    raw_original, dialect_registry,
                )
                result.autofix_applied = autofix_report.applied
                report_v2["autofix_applied"] = autofix_report.applied
                report_v2["autofix"] = autofix_report.model_dump()

                (out_dir / "autofix_report.json").write_text(
                    json.dumps(autofix_report.model_dump(), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                (out_dir / "raw_fixed.json").write_text(
                    json.dumps(fixed_doc, indent=2, ensure_ascii=False), encoding="utf-8",
                )

                if autofix_report.applied:
                    # Re-validate fixed doc
                    canonical, v_report, bundle = validate_and_canonicalize_with_bundle(fixed_doc)
                    result.raw_fixed_valid = v_report.ok if v_report else False
                    report_v2["raw_fixed_valid"] = result.raw_fixed_valid
                    report_v2["hashes"]["raw_fixed"] = autofix_report.after_hash

                    (out_dir / "raw_fixed_validation.json").write_text(
                        json.dumps(_report_to_dict(v_report), indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )

                    if result.raw_fixed_valid:
                        raw_to_use = fixed_doc
            except Exception:
                pass  # autofix failed, keep raw_original

        # ── Stage 8: Canonicalize ──
        # (may already be done if validation passed or autofix succeeded)
        if canonical is None or not (v_report and v_report.ok):
            # Use raw_to_use (may be fixed or original)
            v_result = validate_and_canonicalize_with_bundle(raw_to_use)
            if isinstance(v_result, tuple):
                canonical, v_report, bundle = v_result
            else:
                canonical = v_result

        result.canonical_valid = canonical is not None
        report_v2["canonical_valid"] = result.canonical_valid

        if canonical:
            can_dict = canonical.model_dump()
            (out_dir / "canonical.json").write_text(
                json.dumps(can_dict, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
            report_v2["hashes"]["canonical"] = stable_hash(can_dict)

        if bundle:
            (out_dir / "validation_bundle.json").write_text(
                json.dumps(bundle.to_metadata_dict(), indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )

        if not result.canonical_valid:
            result.final_error = "Canonicalization failed"
            report_v2["final_error"] = result.final_error
            result.report_v2 = report_v2
            (out_dir / "report_v2.json").write_text(
                json.dumps(report_v2, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            return result

        # ── Stage 9: Runtime → STEP ──
        if canonical is None:
            result.final_error = "No canonical document to build STEP from"
            report_v2["final_error"] = result.final_error
            result.report_v2 = report_v2
            (out_dir / "report_v2.json").write_text(
                json.dumps(report_v2, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            return result

        step_path = out_dir / "output.step"
        metadata_path = out_dir / "metadata.json"

        try:
            from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad

            run_result = run_canonical_gcad(
                canonical=canonical,
                out_step=step_path,
                metadata_path=metadata_path,
                validation_seed=bundle.to_metadata_dict() if bundle else {},
                require_full_validation_seed=False,
            )

            result.runtime_valid = run_result.ok
            result.artifact_valid = run_result.ok and step_path.exists() and step_path.stat().st_size > 0
            report_v2["runtime_valid"] = result.runtime_valid
            report_v2["artifact_valid"] = result.artifact_valid

            if step_path.exists():
                import hashlib
                sha = hashlib.sha256(step_path.read_bytes()).hexdigest()
                report_v2["hashes"]["step_sha256"] = sha

            if run_result.warnings:
                (out_dir / "runtime_report.json").write_text(
                    json.dumps({
                        "ok": run_result.ok,
                        "warnings": run_result.warnings,
                        "degraded_features": run_result.degraded_features,
                        "operation_metrics": run_result.operation_metrics,
                    }, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )

            if not run_result.ok:
                result.final_error = f"Runtime: {run_result.error}"
        except Exception as exc:
            result.final_error = f"Runtime exception: {exc}"
            report_v2["final_error"] = result.final_error

        # ── Final: report_v2 ──
        result.ok = result.artifact_valid
        result.step_ok = result.artifact_valid
        report_v2["ok"] = result.ok
        report_v2["step_ok"] = result.step_ok
        if result.final_error:
            report_v2["final_error"] = result.final_error

        result.report_v2 = report_v2
        (out_dir / "report_v2.json").write_text(
            json.dumps(report_v2, indent=2, ensure_ascii=False), encoding="utf-8",
        )

    except Exception as exc:
        tb = traceback.format_exc()
        result.final_error = f"{exc}\n{tb[-1000:]}"
        report_v2["final_error"] = result.final_error
        result.report_v2 = report_v2
        (out_dir / "report_v2.json").write_text(
            json.dumps(report_v2, indent=2, ensure_ascii=False), encoding="utf-8",
        )

    return result


# ── Helpers ──────────────────────────────────────────────────────────────────


def _report_to_dict(report) -> dict[str, Any]:
    """Convert a ValidationReport to a JSON-safe dict."""
    if report is None:
        return {"ok": False, "issues": []}
    if hasattr(report, "model_dump"):
        return report.model_dump()
    if isinstance(report, dict):
        return report
    return {
        "ok": getattr(report, "ok", False),
        "stage": getattr(report, "stage", "unknown"),
        "issues": [
            i.model_dump() if hasattr(i, "model_dump") else i
            for i in getattr(report, "issues", [])
        ],
        "stages_run": getattr(report, "stages_run", []),
    }
