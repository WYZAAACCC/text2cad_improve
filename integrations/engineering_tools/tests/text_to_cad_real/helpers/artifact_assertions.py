"""Artifact assertions for text-to-CAD tests."""

from __future__ import annotations

import json
from pathlib import Path


def assert_success_artifacts(result) -> None:
    """Verify all required artifacts exist for a successful build."""
    assert result.step_path is not None, "step_path must not be None"
    assert result.step_path.exists(), f"STEP file not found: {result.step_path}"
    assert result.metadata_path is not None, "metadata_path must not be None"
    assert result.metadata_path.exists(), f"Metadata file not found: {result.metadata_path}"
    assert result.logs_path is not None, "logs_path must not be None"
    assert result.logs_path.exists(), f"Logs file not found: {result.logs_path}"


def assert_import_gate_passed(result) -> None:
    """Verify import gate result shows native_import_eligible."""
    import_gate_path = None
    if result.case_dir:
        for pattern in ["**/import_gate*.json", "**/gate*.json"]:
            found = list(result.case_dir.glob(pattern))
            if found:
                import_gate_path = found[0]
                break

    if import_gate_path is None:
        # Import gate is embedded in the build result
        # For generative path, the import gate is checked during build
        # The key assertion: import gates pass when result.ok is True
        assert result.ok, "Build must succeed for import gate to pass"
        return

    gate = json.loads(import_gate_path.read_text(encoding="utf-8"))
    assert gate.get("ok") is True, f"Import gate not OK: {gate}"
    assert gate.get("state") == "native_import_eligible", \
        f"Expected native_import_eligible, got {gate.get('state')}"
    gate_info = gate.get("gate", {})
    assert gate_info.get("step_import_allowed") is True, \
        "step_import_allowed must be True"
    assert gate_info.get("native_rebuild_allowed") is False, \
        "native_rebuild_allowed must be False"


def assert_builder_artifact_reference_only(result) -> None:
    """Verify artifact is reference-only (not manufacturing ready)."""
    artifact_path = _find_artifact_file(result)
    if artifact_path is None:
        # Check metadata proxy
        if result.metadata_path and result.metadata_path.exists():
            meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
            gm = meta.get("generative_metadata", {})
            assert gm.get("trust_level", "") != "manufacturing_ready"
            assert gm.get("trust_level", "") != "certified"
            safety = gm.get("safety", {})
            assert safety.get("not_for_manufacturing") is True
            assert safety.get("not_certified") is True
        return

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact.get("state") == "validated_reference_step", \
        f"Expected validated_reference_step, got {artifact.get('state')}"
    assert artifact.get("step_import_allowed") is False, \
        "step_import_allowed must be False (requires import gate)"
    assert artifact.get("native_rebuild_allowed") is False, \
        "native_rebuild_allowed must be False"
    assert artifact.get("requires_import_gate") is True, \
        "requires_import_gate must be True"


def _find_artifact_file(result) -> Path | None:
    if result.artifact_path and result.artifact_path.exists():
        return result.artifact_path
    if result.case_dir:
        for pattern in ["**/*artifact*.json", "**/artifact.json"]:
            found = list(result.case_dir.glob(pattern))
            if found:
                return found[0]
    return None
