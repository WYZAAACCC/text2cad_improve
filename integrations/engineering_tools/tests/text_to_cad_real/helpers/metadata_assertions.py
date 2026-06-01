"""Metadata assertions for text-to-CAD tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REQUIRED_VALIDATION_STAGES = [
    "core_validation",
    "dialect_semantics",
    "geometry_preflight",
    "runtime_postconditions",
    "inspection_validation",
]

REQUIRED_SAFETY_FLAGS = [
    "non_flight_reference_only",
    "not_airworthy",
    "not_certified",
    "not_for_manufacturing",
    "not_for_installation",
    "no_structural_validation",
    "no_life_prediction",
]


def assert_metadata_proof(metadata: dict) -> None:
    """Verify metadata contains all required proof fields."""
    gm = metadata.get("generative_metadata", {})

    # Source route
    assert gm.get("source_route") in {
        "llm_skill_base",
        "deterministic_primitive",
    }, f"Unexpected source_route: {gm.get('source_route')}"

    # Trust level - must be reference/concept, never manufacturing/certified
    assert gm.get("trust_level") in {
        "concept_geometry",
        "reference_geometry",
    }, f"Unexpected trust_level: {gm.get('trust_level')}"
    assert gm.get("trust_level") != "manufacturing_ready"
    assert gm.get("trust_level") != "certified"

    # Safety flags must all be True
    safety = gm.get("safety", {})
    for flag in REQUIRED_SAFETY_FLAGS:
        assert safety.get(flag) is True, \
            f"Safety flag {flag} must be True, got {safety.get(flag)}"

    # Validation must be present
    assert "validation" in metadata, "metadata must contain 'validation' key"


def assert_all_validation_stages_ok(metadata: dict) -> None:
    """Verify all required validation stages passed."""
    validation = metadata.get("validation", {})
    for stage in REQUIRED_VALIDATION_STAGES:
        assert stage in validation, \
            f"Missing validation stage: {stage}"
        stage_result = validation[stage]
        if isinstance(stage_result, dict):
            assert stage_result.get("ok") is True, \
                f"Validation stage {stage} failed: {stage_result}"


def assert_step_hash_matches(metadata: dict, step_path: Path) -> None:
    """Verify metadata step_sha256 matches actual STEP file."""
    actual_hash = sha256_file(step_path)
    gm = metadata.get("generative_metadata", {})
    artifact = gm.get("artifact", {})
    recorded_hash = artifact.get("step_sha256", "")
    assert recorded_hash == actual_hash, \
        f"STEP hash mismatch: recorded={recorded_hash}, actual={actual_hash}"


def assert_safety_flags_all_true(metadata: dict) -> None:
    """Verify all safety flags are explicitly True."""
    gm = metadata.get("generative_metadata", {})
    safety = gm.get("safety", {})
    for flag in REQUIRED_SAFETY_FLAGS:
        assert safety.get(flag) is True, \
            f"Safety flag '{flag}' must be True, got {safety.get(flag)}"


def sha256_file(path: Path) -> str:
    """Compute sha256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"
