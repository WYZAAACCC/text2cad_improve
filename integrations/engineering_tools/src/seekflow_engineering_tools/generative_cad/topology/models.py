"""Topology data models — EntityRecord, TopologyDelta, TopologyResolution.

V3 upgrade: EntityLifecycle, BindingState, ProofClass enums added.
TopologyEntityRecord extended with V3 fields (all optional, backward-compatible).
Existing status/resolution_method fields DEPRECATED in favor of V3 fields.

Phase 1: data model definitions only. Not yet wired into handlers.
Phase 2+: TopologyDelta populated by history-aware operation wrappers.
Phase 6: NamedTopologySet for CAE bridge.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ═══════════════════════════════════════════════════════════════════════════════
# V3 — Lifecycle, Binding, Proof enums
# ═══════════════════════════════════════════════════════════════════════════════


class EntityLifecycle(str, Enum):
    """V3 entity lifecycle state — replaces deprecated 'status' field.

    I-02: Lifecycle is independent of binding and proof.
    """

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class BindingState(str, Enum):
    """V3 binding state — whether the entity is currently bound to a B-Rep subshape.

    I-02: Binding is independent of lifecycle and proof.
    """

    UNBOUND = "unbound"
    BOUND = "bound"
    STALE = "stale"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class ProofClass(str, Enum):
    """V3 proof strength — the evidence backing this entity's identity.

    I-07: Only EXACT_GENERATED_HISTORY and EXACT_MODIFIED_HISTORY are true
    exact proofs. All others are lower confidence.
    """

    EXACT_GENERATED_HISTORY = "exact_generated_history"
    EXACT_MODIFIED_HISTORY = "exact_modified_history"
    DETERMINISTIC_CONSTRUCTION = "deterministic_construction"
    VERIFIED_REBIND_UNIQUE = "verified_rebind_unique"
    FINGERPRINT_CANDIDATE = "fingerprint_candidate"
    AMBIGUOUS_SET = "ambiguous_set"
    NONE = "none"


# ── Entity Record ──


class TopologyEntityRecord(BaseModel):
    """Full lifecycle record of one persistent topology entity.

    Tracks the entity from creation (primitive/semantic naming) through
    modifications (OCCT history), splits, merges, and eventual deletion.

    V3 FIELDS (Phase 1+):
      lifecycle, binding_state, proof_class — replace deprecated status + resolution_method.
      identity_descriptor — stores TopologyIdentityDescriptorV3.model_dump() for full recoverability.
      owner_body_revision_id — body revision token for locator staleness detection.
    """

    model_config = ConfigDict(extra="forbid")

    persistent_id: str

    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"]
    component_id: str
    owner_body_handle_id: str

    producer_node_id: str
    semantic_role: str

    generation: int = 0

    # ── Deprecated fields (replaced by V3 enums) ──
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

    # ── V3 fields (Phase 1+: optional, default None for backward compat) ──

    lifecycle: EntityLifecycle | None = Field(
        default=None,
        description="V3 lifecycle state. Replaces deprecated 'status'.",
    )

    binding_state: BindingState | None = Field(
        default=None,
        description="V3 binding state. Replaces implicit active+locator logic.",
    )

    proof_class: ProofClass | None = Field(
        default=None,
        description="V3 proof strength. Replaces deprecated 'resolution_method'.",
    )

    identity_descriptor: dict | None = Field(
        default=None,
        description="TopologyIdentityDescriptorV3.model_dump() — full recoverable descriptor.",
    )

    owner_body_revision_id: str | None = Field(
        default=None,
        description="Body revision token for locator staleness detection.",
    )

    # Runtime-only locator (NOT persisted across rebuilds)
    current_locator: dict | None = None

    # Fingerprint for fallback matching (Phase 6+)
    fingerprint: dict | None = None

    # Lineage
    ancestor_ids: list[str] = Field(default_factory=list)
    descendant_ids: list[str] = Field(default_factory=list)

    # V3 §2.11: multi-dimensional trust certificate (set by assess())
    trust_certificate: dict | None = None

    # Evidence
    confidence: float = 1.0
    evidence: list[dict] = Field(default_factory=list)

    # ── V3 model validators ──

    @model_validator(mode="after")
    def _validate_v3_invariants(self) -> "TopologyEntityRecord":
        """Enforce V3 invariants when V3 fields are populated.

        I-03: active + unbound is an illegal state.
        I-04: superseded/deleted entities must not have a current locator.
        """
        # Only validate when V3 fields are explicitly set (backward compat:
        # existing code creates records without V3 fields)
        if self.lifecycle is None and self.binding_state is None:
            return self

        # Active lifecycle must have a binding state
        if self.lifecycle == EntityLifecycle.ACTIVE:
            if self.binding_state == BindingState.UNBOUND:
                raise ValueError(
                    f"Entity {self.persistent_id}: lifecycle=ACTIVE with "
                    f"binding_state=UNBOUND is illegal. Active entities "
                    f"must be BOUND (or STALE/AMBIGUOUS during resolution)."
                )

        # Superseded/deleted must not claim BOUND
        if self.lifecycle is not None and self.lifecycle in (
            EntityLifecycle.SUPERSEDED, EntityLifecycle.DELETED,
        ):
            if self.binding_state == BindingState.BOUND:
                raise ValueError(
                    f"Entity {self.persistent_id}: lifecycle={self.lifecycle.value} "
                    f"with binding_state=BOUND is illegal. "
                    f"Superseded/deleted entities cannot be bound to a shape."
                )

        return self


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

    # V3 §2.9: kernel history edges for identity transfer decisions
    kernel_edges: list[dict] | None = None

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


# ── Topology Timeline Event (Phase 6) ──


class TopologyTimelineEvent(BaseModel):
    """Structured topology timeline event — recorded at transaction commit time.

    Replaces ad-hoc dict events with structured fields including
    before/after entity counts for timeline verification.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str = ""
    op: str = ""
    event: str = ""
    entities_before: int = 0
    entities_after: int = 0
    method: str = ""
    face_count: int = 0
    deleted_count: int = 0
    generated_count: int = 0
    modified_count: int = 0
    relocated: int = 0
    unmatched: int = 0
    occurrence_count: int = 0


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
