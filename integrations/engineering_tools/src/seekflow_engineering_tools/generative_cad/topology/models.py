"""Topology data models — EntityRecord, TopologyDelta, TopologyResolution.

Phase 1: data model definitions only. Not yet wired into handlers.
Phase 2+: TopologyDelta populated by history-aware operation wrappers.
Phase 6: NamedTopologySet for CAE bridge.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Entity Record ──


class TopologyEntityRecord(BaseModel):
    """Full lifecycle record of one persistent topology entity.

    Tracks the entity from creation (primitive/semantic naming) through
    modifications (OCCT history), splits, merges, and eventual deletion.
    """

    model_config = ConfigDict(extra="forbid")

    persistent_id: str

    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"]
    component_id: str
    owner_body_handle_id: str

    producer_node_id: str
    semantic_role: str

    generation: int = 0

    status: Literal[
        "active",
        "deleted",
        "ambiguous",
        "unresolved",
        "superseded",
    ] = "active"

    resolution_method: Literal[
        "primitive_semantic",
        "kernel_generated",
        "kernel_modified",
        "kernel_selected",
        "fingerprint_unique",
        "set_expansion",
        "unresolved",
    ] = "primitive_semantic"

    # Runtime-only locator (NOT persisted across rebuilds)
    current_locator: dict | None = None

    # Fingerprint for fallback matching (Phase 3+)
    fingerprint: dict | None = None

    # Lineage
    ancestor_ids: list[str] = Field(default_factory=list)
    descendant_ids: list[str] = Field(default_factory=list)

    # Evidence
    confidence: float = 1.0
    evidence: list[dict] = Field(default_factory=list)


# ── Topology Relation ──


class TopologyRelation(BaseModel):
    """One evolution relation between old and new topology entities.

    Mirrors OCCT naming concepts:
      - PRIMITIVE → first creation
      - GENERATED → new sub-shape from operation
      - MODIFIED → old sub-shape modified (1:1)
      - DELETED → old sub-shape consumed/destroyed
      - SELECTED → explicit user selection for downstream ref
      - SPLIT → one old → many new (records branches)
      - MERGED → many old → one new (records ancestors)
      - UNCHANGED → passed through operation unaffected
    """

    model_config = ConfigDict(extra="forbid")

    relation: Literal[
        "primitive",
        "generated",
        "modified",
        "deleted",
        "selected",
        "split",
        "merged",
        "unchanged",
    ]

    source_ids: list[str] = Field(default_factory=list)
    result_entity_keys: list[str] = Field(default_factory=list)

    semantic_role: str | None = None
    evidence: dict = Field(default_factory=dict)


# ── Topology Delta ──


class TopologyDelta(BaseModel):
    """Topology evolution result from one operation execution.

    Each operation that produces or modifies geometry SHOULD return
    a TopologyDelta describing what happened to every sub-shape.
    Operations without topology awareness return None for the delta
    (backward compatible, treated as 'legacy_none').
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str
    component_id: str

    result_body_handle_ids: list[str] = Field(default_factory=list)

    relations: list[TopologyRelation] = Field(default_factory=list)

    unresolved_entities: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)

    history_provider: Literal[
        "occt_make_shape",
        "occt_boolean_history",
        "operation_semantics",
        "fingerprint_matcher",
        "legacy_none",
    ] = "legacy_none"

    history_provider_version: str = "0.0.0"


# ── Topology Resolution ──


class TopologyResolution(BaseModel):
    """Result of resolving a persistent topology reference at runtime.

    Returns structured status — NEVER silently resolves to a wrong entity.
    If ambiguous, deleted, or unresolved, the status field tells consumers
    exactly what happened (fail-closed for high-risk consumers like CAE).
    """

    model_config = ConfigDict(extra="forbid")

    requested_id: str

    status: Literal[
        "exact",
        "set",
        "deleted",
        "ambiguous",
        "unresolved",
        "type_mismatch",
    ]

    resolved_entity_ids: list[str] = Field(default_factory=list)
    current_handles: list[str] = Field(default_factory=list)

    method: str = "unresolved"
    confidence: float = 0.0

    evidence: list[dict] = Field(default_factory=list)


# ── Named Topology Set (CAE bridge, Phase 6) ──


class NamedTopologySet(BaseModel):
    """Named collection of topology entities for CAE load/constraint/contact targets.

    Replaces raw "Face17" references in FEA input files with stable,
    semantically meaningful topology references. CAE pre-flight gate
    enforces: all IDs active, type correct, cardinality correct, no ambiguity.
    """

    model_config = ConfigDict(extra="forbid")

    name: str

    entity_type: Literal["face", "edge", "vertex", "body"]
    persistent_ids: list[str] = Field(default_factory=list)

    semantic_purpose: Literal[
        "load",
        "constraint",
        "contact",
        "mesh_control",
        "result_path",
        "inspection",
    ] = "inspection"

    required_resolution: Literal["exact", "exact_or_set"] = "exact"
