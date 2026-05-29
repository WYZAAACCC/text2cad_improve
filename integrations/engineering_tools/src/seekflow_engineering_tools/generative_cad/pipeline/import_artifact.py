"""Generative STEP artifact import gate — validates before SolidWorks/NX import.

Ensures only validated, safe generative artifacts enter native CAD systems.
"""

from __future__ import annotations

import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2


def validate_generative_step_artifact_for_native_import(
    step_path: str | Path,
    metadata_path: str | Path,
    *,
    require_inspection_ok: bool = True,
    require_geometry_preflight_ok: bool = True,
    registry_check: bool = True,
) -> dict:
    """Validate a generative STEP artifact before importing into SolidWorks/NX.

    Returns {"ok": bool, "issues": [...], "metadata": ..., "gate": {...}}.
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
        "inspection_ok": False,
        "geometry_preflight_ok": False,
        "native_rebuild_allowed": False,
        "step_import_allowed": True,
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

    # Validate metadata v2
    meta_result = validate_generative_metadata_v2(metadata, registry_check=registry_check)
    if not meta_result["ok"]:
        issues.extend(meta_result["issues"])
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
    gate["metadata_valid"] = True

    gm = metadata.get("generative_metadata", {})

    # source_route must be llm_skill_base
    if gm.get("source_route") != "llm_skill_base":
        issues.append({"code": "invalid_source_route", "message": "source_route must be llm_skill_base for generative artifact import"})
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

    # Contract hash checks
    for d in gm.get("selected_dialects", []):
        ch = d.get("contract_hash", "")
        if not isinstance(ch, str) or not ch.startswith("sha256:"):
            issues.append({"code": "invalid_contract_hash", "message": f"dialect {d.get('dialect')!r} has invalid contract_hash"})
    if any(i["code"] == "invalid_contract_hash" for i in issues):
        return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
    gate["contract_hash_valid"] = True

    # Inspection validation
    val = metadata.get("validation", {})
    insp = val.get("inspection_validation", {})
    if require_inspection_ok:
        if not isinstance(insp, dict) or insp.get("ok") is not True:
            issues.append({"code": "inspection_not_ok", "message": "inspection_validation must be ok for native import"})
            return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
    gate["inspection_ok"] = True

    # Geometry preflight
    gp = val.get("geometry_preflight", {})
    if require_geometry_preflight_ok:
        if isinstance(gp, dict) and gp.get("ok") is False:
            issues.append({"code": "geometry_preflight_failed", "message": "geometry_preflight must be ok for native import"})
            return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
    gate["geometry_preflight_ok"] = True

    gate["native_rebuild_allowed"] = False
    gate["step_import_allowed"] = True

    return {"ok": True, "issues": [], "metadata": metadata, "gate": gate}
