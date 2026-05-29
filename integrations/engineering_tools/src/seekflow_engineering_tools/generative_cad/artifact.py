"""Canonical STEP artifact descriptor for generative CAD output.

This artifact is what downstream tooling consumes — it never becomes a primitive.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CanonicalStepArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["canonical_step_artifact"] = "canonical_step_artifact"
    source_route: Literal["llm_skill_base"] = "llm_skill_base"
    part_name: str
    step_path: str
    metadata_path: str
    graph_path: str
    runner_script_path: str | None = None
    units: Literal["mm"] = "mm"
    trust_level: Literal["concept_geometry", "reference_geometry"] = "reference_geometry"
    native_rebuild_allowed: bool = False
    step_import_allowed: bool = True
    inspection: dict = Field(default_factory=dict)
    validation: dict = Field(default_factory=dict)
