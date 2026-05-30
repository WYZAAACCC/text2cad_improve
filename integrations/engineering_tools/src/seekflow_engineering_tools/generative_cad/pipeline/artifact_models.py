"""CanonicalStepArtifact — typed Pydantic model for artifact state machine."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

ArtifactState = Literal[
    "created_unverified",
    "validated_reference_step",
    "native_import_eligible",
]


class CanonicalStepArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["canonical_step_artifact"]
    artifact_schema_version: Literal["canonical_step_artifact_v1"]

    source_route: Literal["llm_skill_base"]
    state: Literal["validated_reference_step"]

    part_name: str
    document_id: str

    step_path: str
    metadata_path: str
    graph_path: str
    validation_seed_path: str | None = None
    runner_script_path: str | None = None

    units: Literal["mm"]
    trust_level: Literal["concept_geometry", "reference_geometry"]

    schema_version: str
    canonical_version: str

    raw_graph_hash: str
    canonical_graph_hash: str
    selected_dialects: list[dict]

    native_rebuild_allowed: Literal[False]
    step_import_candidate: Literal[True]
    step_import_allowed: Literal[False]
    requires_import_gate: Literal[True]

    step_sha256: str
    metadata_sha256: str | None = None

    inspection: dict
    validation: dict
