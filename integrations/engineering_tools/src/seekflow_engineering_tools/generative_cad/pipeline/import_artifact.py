"""Generative STEP artifact import gate — v0.8: fail-closed gate defaults, complete flags."""

from __future__ import annotations

import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2

REQUIRED_GATE_FLAGS = [
    "step_exists", "metadata_exists", "metadata_valid", "safety_valid",
    "contract_hash_valid", "core_validation_ok", "dialect_semantics_ok",
    "geometry_preflight_ok", "runtime_postconditions_ok", "inspection_ok",
    "native_rebuild_allowed", "step_import_allowed",
]


def validate_generative_step_artifact_for_native_import(
    step_path: str | Path,
    metadata_path: str | Path,
    *,
    require_inspection_ok: bool = True,
    require_geometry_preflight_ok: bool = True,
    registry_check: bool = True,
) -> dict:
    """Validate a generative STEP artifact before importing into SolidWorks/NX.

    Uses require_validation_ok=True — all validation stages must prove ok.
    Gate flags reflect actual state even when optional checks are skipped.
    """
    step_path = Path(step_path)
    metadata_path = Path(metadata_path)
    issues: list[dict] = []

    gate = {
        "step_exists": False,
        "metadata_exists": False,
        "metadata_valid": False,
        "safety_valid": False,
        "contract_hash_valid": False,
        "core_validation_ok": False,
        "dialect_semantics_ok": False,
        "geometry_preflight_ok": False,
        "runtime_postconditions_ok": False,
        "inspection_ok": False,
        "native_rebuild_allowed": False,
        "step_import_allowed": False,
    }

    # STEP exists and non-empty
    if not step_path.exists() or step_path.stat().st_size == 0:
        issues.append({"code": "step_missing_or_empty", "message": f"STEP file missing or empty: {step_path}"})
        return {"ok": False, "issues": issues, "metadata": None, "gate": gate}
    gate["step_exists"] = True

    # Metadata exists and valid JSON
    if not metadata_path.exists():
        issues.append({"code": "metadata_missing", "message": f"Metadata file missing: {metadata_path}"})
        return {"ok": False, "issues": issues, "metadata": None, "gate": gate}
    gate["metadata_exists"] = True

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        issues.append({"code": "metadata_invalid_json", "message": f"Metadata JSON invalid: {exc}"})
        return {"ok": False, "issues": issues, "metadata": None, "gate": gate}

    # Validate metadata v2.1 with hard gate — all stages must prove ok
    meta_result = validate_generative_metadata_v2(
        metadata, canonical=None, registry_check=registry_check, require_validation_ok=True,
    )
    if not meta_result["ok"]:
        issues.extend(meta_result["issues"])
        # Detect contract hash mismatch specifically
        if any(i.get("code") in {"contract_hash_mismatch", "unknown_metadata_dialect"}
               for i in meta_result["issues"]):
            gate["contract_hash_valid"] = False
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
    gate["metadata_valid"] = True
    gate["contract_hash_valid"] = True

    gm = metadata.get("generative_metadata", {})

    # source_route must be llm_skill_base
    if gm.get("source_route") != "llm_skill_base":
        issues.append({"code": "invalid_source_route", "message": "source_route must be llm_skill_base"})
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}

    # trust_level <= reference_geometry
    if gm.get("trust_level") not in ("concept_geometry", "reference_geometry"):
        issues.append({"code": "trust_level_too_high", "message": f"trust_level {gm.get('trust_level')!r} exceeds reference_geometry"})
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}

    # All safety flags true
    safety = gm.get("safety", {})
    required_safety = ["non_flight_reference_only", "not_airworthy", "not_certified",
                       "not_for_manufacturing", "not_for_installation",
                       "no_structural_validation", "no_life_prediction"]
    for flag in required_safety:
        if safety.get(flag) is not True:
            issues.append({"code": f"safety_{flag}_false", "message": f"Safety flag {flag} must be true"})
    if not all(safety.get(f) is True for f in required_safety):
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
    gate["safety_valid"] = True

    # Native rebuild explicitly rejected
    if gm.get("native_rebuild_allowed") is True or metadata.get("native_rebuild_allowed") is True:
        issues.append({"code": "native_rebuild_forbidden", "message": "Generative artifacts may only be imported as canonical STEP; native rebuild is forbidden."})
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}

    # Validation stage checks
    val = metadata.get("validation", {})

    # Core validation
    core = val.get("core_validation", {})
    if not isinstance(core, dict) or core.get("ok") is not True:
        issues.append({"code": "core_validation_not_ok", "message": "core_validation.ok must be true"})
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
    gate["core_validation_ok"] = True

    # Dialect semantics
    ds = val.get("dialect_semantics", {})
    if not isinstance(ds, dict) or ds.get("ok") is not True:
        issues.append({"code": "dialect_semantics_not_ok", "message": "dialect_semantics.ok must be true"})
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
    gate["dialect_semantics_ok"] = True

    # Geometry preflight — gate flag reflects actual state; require_* only controls failure
    gp = val.get("geometry_preflight", {})
    gate["geometry_preflight_ok"] = isinstance(gp, dict) and gp.get("ok") is True
    if require_geometry_preflight_ok and not gate["geometry_preflight_ok"]:
        issues.append({"code": "geometry_preflight_not_ok", "message": "geometry_preflight.ok must be true for native import"})
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}

    # Runtime postconditions
    rp = val.get("runtime_postconditions", {})
    if not isinstance(rp, dict) or rp.get("ok") is not True:
        issues.append({"code": "runtime_postconditions_not_ok", "message": "runtime_postconditions.ok must be true"})
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
    gate["runtime_postconditions_ok"] = True

    # Inspection — gate flag reflects actual state; require_* only controls failure
    insp = val.get("inspection_validation", {})
    gate["inspection_ok"] = isinstance(insp, dict) and insp.get("ok") is True
    if require_inspection_ok and not gate["inspection_ok"]:
        issues.append({"code": "inspection_not_ok", "message": "inspection_validation.ok must be true for native import"})
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}

    gate["native_rebuild_allowed"] = False
    gate["step_import_allowed"] = True

    # v0.9: postcondition invariant — all required flags must be True at success path
    REQUIRED_TRUE_FLAGS = [
        "step_exists", "metadata_exists", "metadata_valid", "safety_valid",
        "contract_hash_valid", "core_validation_ok", "dialect_semantics_ok",
        "geometry_preflight_ok", "runtime_postconditions_ok", "inspection_ok",
        "step_import_allowed",
    ]
    if not all(gate[k] is True for k in REQUIRED_TRUE_FLAGS):
        issues.append({
            "code": "gate_internal_invariant_failed",
            "message": "Import gate reached success path with incomplete true flags.",
        })
        gate["step_import_allowed"] = False
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}

    return {"ok": True, "issues": [], "metadata": metadata, "gate": gate}
