"""Metadata v2 builder and validator for generative CAD output."""

from __future__ import annotations

import hashlib
import json

from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext


def build_generative_metadata(
    canonical: CanonicalGcadDocument,
    ctx: RuntimeContext,
) -> dict:
    """Build generative_metadata_v2 sidecar structure."""
    dialects = []
    for sd in canonical.selected_dialects:
        dialects.append({
            "dialect": sd.dialect,
            "version": sd.version,
            "contract_hash": sd.contract_hash,
        })

    op_versions = []
    for node in canonical.nodes:
        op_versions.append({
            "node_id": node.id,
            "dialect": node.dialect,
            "op": node.op,
            "op_version": node.op_version,
        })

    return {
        "generative_metadata": {
            "metadata_version": "generative_metadata_v2",
            "source_route": "llm_skill_base",
            "schema_version": canonical.schema_version,
            "canonical_version": canonical.canonical_version,
            "trust_level": canonical.trust_level,
            "part_name": canonical.part_name,

            "selected_dialects": dialects,
            "op_versions": op_versions,

            "raw_graph_hash": canonical.raw_graph_hash,
            "canonical_graph_hash": canonical.canonical_graph_hash,
            "runner_version": ctx.runner_version,
            "geometry_runtime": ctx.geometry_runtime_name,

            "operation_metrics": ctx.operation_metrics,
            "degraded_features": ctx.degraded_features,
            "repair_attempts": 0,
            "warnings": ctx.warnings,

            "safety": canonical.safety.model_dump(),
        },
        "build_warnings": ctx.warnings,
        "validation": {
            "core_validation": {},
            "geometry_preflight": {},
            "inspection_validation": {},
        },
    }


def validate_generative_metadata_v2(metadata: dict) -> dict:
    """Validate generative_metadata_v2 sidecar. Returns {"ok": bool, "issues": [...]}."""
    issues = []

    gm = metadata.get("generative_metadata")
    if not isinstance(gm, dict):
        return {"ok": False, "issues": [
            {"code": "missing_generative_metadata", "message": "generative_metadata missing or not dict"}
        ]}

    if gm.get("metadata_version") != "generative_metadata_v2":
        issues.append({
            "code": "invalid_metadata_version",
            "message": f"Expected generative_metadata_v2, got {gm.get('metadata_version')!r}",
        })

    if gm.get("source_route") != "llm_skill_base":
        issues.append({"code": "invalid_source_route", "message": "source_route must be llm_skill_base"})

    if gm.get("trust_level") not in ("concept_geometry", "reference_geometry"):
        issues.append({"code": "invalid_trust_level", "message": f"trust_level invalid: {gm.get('trust_level')!r}"})

    if not isinstance(gm.get("selected_dialects"), list) or not gm["selected_dialects"]:
        issues.append({"code": "missing_selected_dialects", "message": "selected_dialects must be non-empty list"})

    for d in gm.get("selected_dialects", []):
        if not d.get("contract_hash", "").startswith("sha256:"):
            issues.append({"code": "missing_contract_hash", "message": f"dialect {d.get('dialect')!r} missing contract_hash"})

    if not isinstance(gm.get("canonical_graph_hash", ""), str) or not gm["canonical_graph_hash"].startswith("sha256:"):
        issues.append({"code": "missing_canonical_hash", "message": "canonical_graph_hash missing or invalid"})

    if not gm.get("runner_version"):
        issues.append({"code": "missing_runner_version", "message": "runner_version missing"})

    if not gm.get("geometry_runtime"):
        issues.append({"code": "missing_geometry_runtime", "message": "geometry_runtime missing"})

    safety = gm.get("safety", {})
    if isinstance(safety, dict):
        required = [
            "non_flight_reference_only", "not_airworthy", "not_certified",
            "not_for_manufacturing", "not_for_installation",
            "no_structural_validation", "no_life_prediction",
        ]
        for flag in required:
            if safety.get(flag) is not True:
                issues.append({"code": f"safety_{flag}", "message": f"safety flag {flag} must be true"})
    else:
        issues.append({"code": "missing_safety", "message": "safety flags missing"})

    if not isinstance(metadata.get("build_warnings"), list):
        issues.append({"code": "missing_build_warnings", "message": "build_warnings must be list"})

    if not isinstance(metadata.get("validation"), dict):
        issues.append({"code": "missing_validation", "message": "validation must be dict"})

    return {"ok": len(issues) == 0, "issues": issues}
