"""CanonicalStepArtifact builder — merge point for downstream pipeline."""

from __future__ import annotations

from pathlib import Path


def build_canonical_step_artifact(
    canonical,
    step_path: Path,
    metadata_path: Path,
    ctx,
) -> dict:
    """Build CanonicalStepArtifact dict for downstream consumption."""
    return {
        "artifact_type": "canonical_step_artifact",
        "source_route": "llm_skill_base",
        "part_name": canonical.part_name,
        "step_path": str(step_path),
        "metadata_path": str(metadata_path),
        "graph_path": "",
        "runner_script_path": None,
        "units": "mm",
        "trust_level": canonical.trust_level,
        "native_rebuild_allowed": False,
        "step_import_allowed": True,
        "inspection": {},
        "validation": {
            "core_validation": {},
            "geometry_preflight": {},
            "inspection_validation": {},
        },
    }
