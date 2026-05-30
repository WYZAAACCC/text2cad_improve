"""CanonicalStepArtifact builder — vNext: typed Pydantic model, step_sha256, metadata_sha256."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from seekflow_engineering_tools.generative_cad.pipeline.artifact_models import CanonicalStepArtifact


def _sha256_file(path: Path) -> str:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return ""


def build_canonical_step_artifact(
    canonical,
    step_path: str | Path,
    metadata_path: str | Path,
    *,
    graph_path: str | None = None,
    validation_seed_path: str | None = None,
    runner_script_path: str | None = None,
    validation: dict[str, Any] | None = None,
    inspection: dict[str, Any] | None = None,
    ctx=None,
) -> dict[str, Any]:
    step_path = Path(step_path)
    metadata_path = Path(metadata_path)

    if validation is None and ctx is not None:
        validation = getattr(ctx, "validation", None)

    if validation is None:
        validation = {
            "core_validation": {"ok": False, "stage": "core_validation",
                "issues": [{"code": "missing_core_validation", "message": "No core validation provided.", "severity": "error"}]},
            "dialect_semantics": {"ok": False, "stage": "dialect_semantics",
                "issues": [{"code": "missing_dialect_semantics", "message": "No dialect semantics provided.", "severity": "error"}]},
            "geometry_preflight": {"ok": False, "stage": "geometry_preflight",
                "issues": [{"code": "missing_geometry_preflight", "message": "No geometry preflight provided.", "severity": "error"}]},
            "runtime_postconditions": {"ok": False, "stage": "runtime_postconditions",
                "issues": [{"code": "missing_runtime_postconditions", "message": "No runtime postconditions provided.", "severity": "error"}]},
            "inspection_validation": {"ok": False, "stage": "inspection_validation",
                "issues": [{"code": "missing_inspection_validation", "message": "No inspection validation provided.", "severity": "error"}]},
        }

    artifact = CanonicalStepArtifact(
        artifact_type="canonical_step_artifact",
        artifact_schema_version="canonical_step_artifact_v1",
        source_route="llm_skill_base",
        state="validated_reference_step",
        part_name=canonical.part_name,
        document_id=getattr(canonical, "document_id", ""),
        step_path=str(step_path),
        metadata_path=str(metadata_path),
        graph_path=str(graph_path) if graph_path else "",
        validation_seed_path=str(validation_seed_path) if validation_seed_path else None,
        runner_script_path=str(runner_script_path) if runner_script_path else None,
        units="mm",
        trust_level=canonical.trust_level,
        schema_version=canonical.schema_version,
        canonical_version=canonical.canonical_version,
        raw_graph_hash=getattr(canonical, "raw_graph_hash", "") or "",
        canonical_graph_hash=getattr(canonical, "canonical_graph_hash", ""),
        selected_dialects=[d.model_dump() for d in canonical.selected_dialects],
        native_rebuild_allowed=False,
        step_import_candidate=True,
        step_import_allowed=False,
        requires_import_gate=True,
        step_sha256=_sha256_file(step_path) if step_path.exists() else "",
        metadata_sha256=_sha256_file(metadata_path) if metadata_path.exists() else None,
        inspection=inspection or {},
        validation=validation,
    )
    return artifact.model_dump()
