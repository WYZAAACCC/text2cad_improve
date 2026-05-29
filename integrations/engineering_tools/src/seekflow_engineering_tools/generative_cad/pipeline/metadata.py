"""Metadata v2.1 builder and validator — hard validation with require_validation_ok."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext

REQUIRED_VALIDATION_STAGES = [
    "core_validation",
    "dialect_semantics",
    "geometry_preflight",
    "runtime_postconditions",
    "inspection_validation",
]

REQUIRED_SAFETY_FLAGS = [
    "non_flight_reference_only", "not_airworthy", "not_certified",
    "not_for_manufacturing", "not_for_installation",
    "no_structural_validation", "no_life_prediction",
]


def build_generative_metadata(
    canonical: CanonicalGcadDocument,
    ctx: RuntimeContext,
    validation: dict | None = None,
    repair_summary: dict | None = None,
) -> dict:
    if validation is None:
        validation = {
            "core_validation": {
                "ok": False, "stage": "core_validation",
                "issues": [{"code": "missing_core_validation_report", "message": "No core validation report was provided.", "severity": "error"}],
            },
            "dialect_semantics": {
                "ok": False, "stage": "dialect_semantics",
                "issues": [{"code": "missing_dialect_semantics_report", "message": "No dialect semantics report was provided.", "severity": "error"}],
            },
            "geometry_preflight": {
                "ok": False, "stage": "geometry_preflight",
                "issues": [{"code": "missing_geometry_preflight_report", "message": "No geometry preflight report was provided.", "severity": "error"}],
            },
            "runtime_postconditions": {
                "ok": False, "stage": "runtime_postconditions",
                "issues": [{"code": "missing_runtime_postconditions_report", "message": "No runtime postconditions report was provided.", "severity": "error"}],
            },
            "inspection_validation": {
                "ok": False, "stage": "inspection_validation",
                "issues": [{"code": "missing_inspection_validation_report", "message": "No inspection validation report was provided.", "severity": "error"}],
            },
        }
    return {
        "generative_metadata": {
            "metadata_version": "generative_metadata_v2",
            "metadata_schema_minor": "2.1",
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
            "repair_attempts": repair_summary.get("attempts", 0) if repair_summary else 0,
            "warnings": ctx.warnings,
            "safety": canonical.safety.model_dump(),
        },
        "build_warnings": ctx.warnings,
        "validation": validation,
    }


def validate_generative_metadata_v2(
    metadata: dict,
    canonical: CanonicalGcadDocument | None = None,
    registry_check: bool = True,
    require_validation_ok: bool = False,
) -> dict:
    """Validate generative_metadata_v2.

    If require_validation_ok=True, every validation stage must have ok: True.
    Registry check now runs regardless of canonical presence.
    """
    issues: list[dict] = []
    gm = metadata.get("generative_metadata")
    if not isinstance(gm, dict):
        return {"ok": False, "issues": [{"code": "missing_generative_metadata", "message": "generative_metadata missing"}]}

    # Basic required fields
    if gm.get("metadata_version") != "generative_metadata_v2":
        issues.append({"code": "invalid_metadata_version", "message": f"Expected generative_metadata_v2, got {gm.get('metadata_version')!r}"})
    if not gm.get("metadata_schema_minor"):
        issues.append({"code": "missing_metadata_schema_minor", "message": "metadata_schema_minor missing"})
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
    rgh = gm.get("raw_graph_hash", "")
    if not isinstance(rgh, str) or not rgh.startswith("sha256:"):
        issues.append({"code": "missing_raw_hash", "message": "raw_graph_hash missing/invalid"})
    if not gm.get("runner_version"):
        issues.append({"code": "missing_runner_version", "message": "runner_version missing"})
    if not gm.get("geometry_runtime"):
        issues.append({"code": "missing_geometry_runtime", "message": "geometry_runtime missing"})

    # Safety flags
    safety = gm.get("safety", {})
    if isinstance(safety, dict):
        for flag in REQUIRED_SAFETY_FLAGS:
            if safety.get(flag) is not True:
                issues.append({"code": f"safety_{flag}", "message": f"safety flag {flag} must be true"})
    else:
        issues.append({"code": "missing_safety", "message": "safety flags missing"})

    if not isinstance(metadata.get("build_warnings"), list):
        issues.append({"code": "missing_build_warnings", "message": "build_warnings must be list"})

    # Validation section
    val = metadata.get("validation")
    if not isinstance(val, dict):
        issues.append({"code": "missing_validation", "message": "validation must be dict"})
    else:
        for key in REQUIRED_VALIDATION_STAGES:
            stage = val.get(key)
            if not isinstance(stage, dict):
                issues.append({"code": f"missing_{key}", "message": f"validation.{key} must be dict"})
            elif require_validation_ok and stage.get("ok") is not True:
                issues.append({"code": f"{key}_not_ok", "message": f"validation.{key}.ok must be true, got {stage.get('ok')!r}"})

    # Registry contract hash check — always run when registry_check=True
    if registry_check:
        for d in gm.get("selected_dialects", []):
            did = d.get("dialect")
            if not did:
                continue
            try:
                reg_hash = dialect_contract_hash(did)
            except KeyError:
                issues.append({"code": "unknown_metadata_dialect", "message": f"metadata references unknown dialect {did!r}"})
                continue
            if d.get("contract_hash") != reg_hash:
                issues.append({"code": "contract_hash_mismatch", "message": f"dialect {did!r} contract_hash mismatch: metadata={d.get('contract_hash')}, registry={reg_hash}"})

    # Native rebuild rejection
    if gm.get("native_rebuild_allowed") is True:
        issues.append({"code": "native_rebuild_forbidden", "message": "Generative artifacts may only be imported as canonical STEP; native rebuild is forbidden."})
    if metadata.get("native_rebuild_allowed") is True:
        issues.append({"code": "native_rebuild_forbidden", "message": "Generative artifacts may only be imported as canonical STEP; native rebuild is forbidden."})

    # If canonical provided, compare provenance
    if canonical is not None:
        if gm.get("schema_version") != canonical.schema_version:
            issues.append({"code": "schema_version_mismatch", "message": f"metadata schema_version={gm.get('schema_version')!r} != canonical {canonical.schema_version!r}"})
        if gm.get("canonical_version") != canonical.canonical_version:
            issues.append({"code": "canonical_version_mismatch", "message": "metadata canonical_version mismatch"})
        if gm.get("trust_level") != canonical.trust_level:
            issues.append({"code": "trust_level_mismatch", "message": f"metadata trust_level={gm.get('trust_level')!r} != canonical {canonical.trust_level!r}"})
        if gm.get("canonical_graph_hash") != canonical.canonical_graph_hash:
            issues.append({"code": "canonical_hash_mismatch", "message": "metadata canonical_graph_hash != canonical document hash"})
        if gm.get("raw_graph_hash") and canonical.raw_graph_hash and gm["raw_graph_hash"] != canonical.raw_graph_hash:
            issues.append({"code": "raw_hash_mismatch", "message": "metadata raw_graph_hash != canonical raw_graph_hash"})
        meta_safety = gm.get("safety", {})
        canon_safety = canonical.safety.model_dump()
        for flag in REQUIRED_SAFETY_FLAGS:
            if meta_safety.get(flag) is not True or canon_safety.get(flag) is not True:
                issues.append({"code": "safety_drift", "message": f"safety flag {flag} mismatch in metadata vs canonical"})
        if len(gm.get("op_versions", [])) != len(canonical.nodes):
            issues.append({"code": "op_versions_count_mismatch", "message": f"metadata has {len(gm.get('op_versions', []))} op_versions, canonical has {len(canonical.nodes)} nodes"})
        if len(gm.get("selected_dialects", [])) != len(canonical.selected_dialects):
            issues.append({"code": "dialect_count_mismatch", "message": f"metadata has {len(gm.get('selected_dialects', []))} dialects, canonical has {len(canonical.selected_dialects)}"})

    return {"ok": len(issues) == 0, "issues": issues}
