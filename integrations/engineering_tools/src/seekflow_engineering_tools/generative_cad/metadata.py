"""Generative metadata validation — guarantees mandatory sidecar structure."""

from __future__ import annotations


def validate_generative_metadata_v1(metadata: dict) -> dict:
    """Validate a generative metadata v1 sidecar.

    Returns {"ok": bool, "issues": [{"code": ..., "message": ...}]}.
    """
    issues: list[dict] = []

    if "generative_metadata" not in metadata:
        issues.append({
            "code": "missing_generative_metadata",
            "message": "Top-level 'generative_metadata' key is missing.",
        })
        return {"ok": False, "issues": issues}

    gm = metadata.get("generative_metadata", {})
    if not isinstance(gm, dict):
        issues.append({
            "code": "invalid_generative_metadata",
            "message": f"'generative_metadata' must be a dict, got {type(gm).__name__}.",
        })
        return {"ok": False, "issues": issues}

    # metadata_version
    if gm.get("metadata_version") != "generative_metadata_v1":
        issues.append({
            "code": "invalid_metadata_version",
            "message": (
                f"metadata_version must be 'generative_metadata_v1', "
                f"got {gm.get('metadata_version')!r}."
            ),
        })

    # source_route
    if gm.get("source_route") != "llm_skill_base":
        issues.append({
            "code": "invalid_source_route",
            "message": (
                f"source_route must be 'llm_skill_base', "
                f"got {gm.get('source_route')!r}."
            ),
        })

    # trust_level
    if gm.get("trust_level") not in ("concept_geometry", "reference_geometry"):
        issues.append({
            "code": "invalid_trust_level",
            "message": (
                f"trust_level must be 'concept_geometry' or 'reference_geometry', "
                f"got {gm.get('trust_level')!r}."
            ),
        })

    # base_stack
    base_stack = gm.get("base_stack", [])
    if not isinstance(base_stack, list) or not base_stack:
        issues.append({
            "code": "missing_base_stack",
            "message": "base_stack must be a non-empty list.",
        })

    # feature_graph_hash
    fgh = gm.get("feature_graph_hash", "")
    if not isinstance(fgh, str) or not fgh.startswith("sha256:"):
        issues.append({
            "code": "missing_feature_graph_hash",
            "message": "feature_graph_hash must be a string starting with 'sha256:'.",
        })

    # safety flags
    safety = gm.get("safety")
    if not isinstance(safety, dict) or not safety:
        issues.append({
            "code": "missing_safety",
            "message": "safety flags are missing, empty, or not a dict.",
        })
    else:
        required_safety = [
            "non_flight_reference_only",
            "not_airworthy",
            "not_certified",
            "not_for_manufacturing",
            "not_for_installation",
            "no_structural_validation",
            "no_life_prediction",
        ]
        for flag in required_safety:
            if safety.get(flag) is not True:
                issues.append({
                    "code": f"safety_flag_{flag}",
                    "message": f"Safety flag {flag!r} must be true, got {safety.get(flag)!r}.",
                })

    # build_warnings
    bw = metadata.get("build_warnings")
    if not isinstance(bw, list):
        issues.append({
            "code": "missing_build_warnings",
            "message": "build_warnings must be a list.",
        })

    # validation
    val = metadata.get("validation")
    if not isinstance(val, dict):
        issues.append({
            "code": "missing_validation",
            "message": "validation must be a dict.",
        })

    return {"ok": len(issues) == 0, "issues": issues}
