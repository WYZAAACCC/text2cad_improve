"""Repair patch v0.3 — RepairPatchV2 based on RawGcadDocument paths."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RepairChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    old_value: Any | None = None
    new_value: Any
    reason: str


class RepairPatchV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_node: str | None = None
    target_component: str | None = None
    changes: list[RepairChange]
    reason: str
    give_up: bool = False


# Allowed paths for repair
ALLOWED_REPAIR_PATHS_V2 = frozenset({
    "/nodes/<node_id>/params/<field>",
    "/nodes/<node_id>/inputs",
    "/nodes/<node_id>/outputs",
    "/nodes/<node_id>/required",
    "/nodes/<node_id>/degradation_policy",
    "/components/<component_id>/root_node",
    "/llm_validation_hints",
})

FORBIDDEN_REPAIR_PATHS_V2 = frozenset({
    "/schema_version",
    "/selected_dialects",
    "/constraints/require_step_file",
    "/constraints/require_metadata_sidecar",
    "/constraints/require_closed_solid",
    "/safety",
    "/nodes/<node_id>/dialect",
    "/nodes/<node_id>/op",
    "/nodes/<node_id>/op_version",
    "/components/<component_id>/owner_dialect",
})
