"""Metadata v2 builder and validator — v0.2.1: canonical + registry comparison."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext


def build_generative_metadata(canonical: CanonicalGcadDocument, ctx: RuntimeContext) -> dict:
    return {
        "generative_metadata": {
            "metadata_version": "generative_metadata_v2",
            "source_route": "llm_skill_base",
            "schema_version": canonical.schema_version,
            "canonical_version": canonical.canonical_version,
            "trust_level": canonical.trust_level,
            "part_name": canonical.part_name,
            "selected_dialects": [{"dialect": d.dialect, "version": d.version, "contract_hash": d.contract_hash} for d in canonical.selected_dialects],
            "op_versions": [{"node_id": n.id, "dialect": n.dialect, "op": n.op, "op_version": n.op_version} for n in canonical.nodes],
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
        "validation": {"core_validation": {}, "geometry_preflight": {}, "inspection_validation": {}},
    }


def validate_generative_metadata_v2(metadata: dict, canonical=None, registry_check: bool = True) -> dict:
    """Validate generative_metadata_v2. If canonical provided, compare hashes and contracts."""
    issues = []
    gm = metadata.get("generative_metadata")
    if not isinstance(gm, dict):
        return {"ok": False, "issues": [{"code": "missing_generative_metadata", "message": "generative_metadata missing"}]}

    if gm.get("metadata_version") != "generative_metadata_v2":
        issues.append({"code": "invalid_metadata_version", "message": f"Expected generative_metadata_v2, got {gm.get('metadata_version')!r}"})
    if gm.get("source_route") != "llm_skill_base":
        issues.append({"code": "invalid_source_route", "message": "source_route must be llm_skill_base"})
    if gm.get("trust_level") not in ("concept_geometry", "reference_geometry"):
        issues.append({"code": "invalid_trust_level", "message": f"trust_level invalid: {gm.get('trust_level')!r}"})
    if not isinstance(gm.get("selected_dialects"), list) or not gm["selected_dialects"]:
        issues.append({"code": "missing_selected_dialects", "message": "selected_dialects must be non-empty"})
    for d in gm.get("selected_dialects", []):
        ch = d.get("contract_hash", "")
        if not isinstance(ch, str) or not ch.startswith("sha256:"):
            issues.append({"code": "missing_contract_hash", "message": f"dialect {d.get('dialect')!r} missing contract_hash"})
    cgh = gm.get("canonical_graph_hash", "")
    if not isinstance(cgh, str) or not cgh.startswith("sha256:"):
        issues.append({"code": "missing_canonical_hash", "message": "canonical_graph_hash missing/invalid"})
    if not gm.get("runner_version"):
        issues.append({"code": "missing_runner_version", "message": "runner_version missing"})
    if not gm.get("geometry_runtime"):
        issues.append({"code": "missing_geometry_runtime", "message": "geometry_runtime missing"})
    safety = gm.get("safety", {})
    if isinstance(safety, dict):
        for flag in ["non_flight_reference_only", "not_airworthy", "not_certified", "not_for_manufacturing", "not_for_installation", "no_structural_validation", "no_life_prediction"]:
            if safety.get(flag) is not True:
                issues.append({"code": f"safety_{flag}", "message": f"safety flag {flag} must be true"})
    else:
        issues.append({"code": "missing_safety", "message": "safety flags missing"})
    if not isinstance(metadata.get("build_warnings"), list):
        issues.append({"code": "missing_build_warnings", "message": "build_warnings must be list"})
    if not isinstance(metadata.get("validation"), dict):
        issues.append({"code": "missing_validation", "message": "validation must be dict"})

    # If canonical provided, compare all provenance fields
    if canonical is not None and not issues:
        if gm.get("schema_version") != canonical.schema_version:
            issues.append({"code": "schema_version_mismatch", "message": f"metadata schema_version={gm.get('schema_version')!r} != canonical {canonical.schema_version!r}"})
        if gm.get("canonical_version") != canonical.canonical_version:
            issues.append({"code": "canonical_version_mismatch", "message": f"metadata canonical_version mismatch"})
        if gm.get("trust_level") != canonical.trust_level:
            issues.append({"code": "trust_level_mismatch", "message": f"metadata trust_level={gm.get('trust_level')!r} != canonical {canonical.trust_level!r}"})
        if gm.get("canonical_graph_hash") != canonical.canonical_graph_hash:
            issues.append({"code": "canonical_hash_mismatch", "message": "metadata canonical_graph_hash != canonical document hash"})
        if gm.get("raw_graph_hash") and canonical.raw_graph_hash and gm["raw_graph_hash"] != canonical.raw_graph_hash:
            issues.append({"code": "raw_hash_mismatch", "message": "metadata raw_graph_hash != canonical raw_graph_hash"})
        # Compare safety
        meta_safety = gm.get("safety", {})
        canon_safety = canonical.safety.model_dump()
        for flag in ["non_flight_reference_only", "not_airworthy", "not_certified", "not_for_manufacturing", "not_for_installation", "no_structural_validation", "no_life_prediction"]:
            if meta_safety.get(flag) is not True or canon_safety.get(flag) is not True:
                issues.append({"code": "safety_drift", "message": f"safety flag {flag} mismatch in metadata vs canonical"})
        # Compare op_versions count
        meta_ops = gm.get("op_versions", [])
        if len(meta_ops) != len(canonical.nodes):
            issues.append({"code": "op_versions_count_mismatch", "message": f"metadata has {len(meta_ops)} op_versions, canonical has {len(canonical.nodes)} nodes"})
        # Compare selected_dialects count
        meta_dialects = gm.get("selected_dialects", [])
        if len(meta_dialects) != len(canonical.selected_dialects):
            issues.append({"code": "dialect_count_mismatch", "message": f"metadata has {len(meta_dialects)} dialects, canonical has {len(canonical.selected_dialects)}"})
        if registry_check:
            for d in meta_dialects:
                try:
                    reg_ch = dialect_contract_hash(d["dialect"])
                    if d.get("contract_hash") != reg_ch:
                        issues.append({"code": "contract_hash_mismatch", "message": f"dialect {d['dialect']!r} contract_hash mismatch: metadata={d.get('contract_hash')}, registry={reg_ch}"})
                except KeyError:
                    pass

    return {"ok": len(issues) == 0, "issues": issues}
