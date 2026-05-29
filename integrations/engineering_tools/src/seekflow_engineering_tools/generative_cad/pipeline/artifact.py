"""CanonicalStepArtifact builder — accepts optional paths, returns proper None for unavailable."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_canonical_step_artifact(
    canonical,
    step_path: Path,
    metadata_path: Path,
    ctx=None,
    *,
    graph_path: str | None = None,
    runner_script_path: str | None = None,
    inspection: dict | None = None,
    validation: dict | None = None,
) -> dict[str, Any]:
    return {
        "artifact_type": "canonical_step_artifact",
        "source_route": "llm_skill_base",
        "part_name": canonical.part_name,
        "step_path": str(step_path),
        "metadata_path": str(metadata_path),
        "graph_path": graph_path,
        "runner_script_path": runner_script_path,
        "units": canonical.units,
        "trust_level": canonical.trust_level,
        "native_rebuild_allowed": False,
        "step_import_allowed": True,
        "inspection": inspection or {},
        "validation": validation or {},
    }
