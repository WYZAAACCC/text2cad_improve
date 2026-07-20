"""Kernel relation → Identity decision layering — §2.5, §2.9 of the supplementary spec.

Separates two concepts that are currently conflated:
  - KernelHistoryEdge: pure OCCT observation (Generated/Modified/IsDeleted/IsSame)
  - IdentityDecision: domain-level decision (unchanged/generated_from_tool/split/…)

Includes IdentityTransferPolicy, an 8-dimension decision engine that maps
kernel observations to identity decisions.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.5, §2.9
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


# ═══════════════════════════════════════════════════════════════════════════════
# KernelRelation — pure OCCT observation (§2.9)
# ═══════════════════════════════════════════════════════════════════════════════


class KernelRelation(str, Enum):
    """OCCT kernel observation — pure, uninterpreted.

    These correspond directly to BRepTools_History queries:
      - SAME:     IsSame() → same TShape, same Location (orientation may differ)
      - MODIFIED: Modified() → kernel reports modification
      - GENERATED: Generated() → kernel reports new shape
      - REMOVED:  IsDeleted() → kernel reports removal
    """

    SAME = "same"
    MODIFIED = "modified"
    GENERATED = "generated"
    REMOVED = "removed"


class KernelHistoryEdge(BaseModel):
    """One directed edge in the OCCT kernel history graph.

    Maps a source persistent identity to a result occurrence key
    with the kernel's raw observation of what happened.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_pid: str
    result_occurrence_key: str
    kernel_relation: KernelRelation


# ═══════════════════════════════════════════════════════════════════════════════
# IdentityRelation — domain identity decision (§2.9)
# ═══════════════════════════════════════════════════════════════════════════════


class OccurrenceChange(str, Enum):
    """Change in occurrence properties (§2.5)."""
    NONE = "none"
    REORIENTED = "reoriented"
    RELOCATED = "relocated"
    REORIENTED_AND_RELOCATED = "reoriented_and_relocated"


class IdentityRelation(str, Enum):
    """Domain identity decision — interpreted from kernel observations.

    These are what the topology system SHOULD do, not what OCCT reported.
    The mapping from KernelRelation to IdentityRelation is governed by
    IdentityTransferPolicy.
    """

    UNCHANGED = "unchanged"                       # IsEqual → same identity, same PID
    REORIENTED = "reoriented"                     # IsSame but !IsEqual — §2.5
    RELOCATED = "relocated"                       # IsPartner only — §2.5
    MODIFIED_SAME_IDENTITY = "modified_same_identity"  # Modified, keep PID
    GENERATED_NEW_IDENTITY = "generated_new_identity"  # Generated, new PID (target face)
    GENERATED_FROM_TOOL = "generated_from_tool"         # Tool face → result face — §2.9 key rule
    SPLIT = "split"                               # 1 source → N results
    MERGE = "merge"                               # N sources → 1 result
    REPARTITION = "repartition"                   # N sources → M results
    CONSUMED = "consumed"                         # Tool body/face deleted
    DELETED = "deleted"                           # Entity explicitly removed


class IdentityDecision(BaseModel):
    """One domain identity decision with full provenance.

    Every decision records:
      - Which kernel edges informed it (provenance_edges)
      - What identity relation was decided
      - Whether orientation/location changed (§2.5)

    Multiple provenance_edges are allowed because a single result face
    can be influenced by both target and tool kernel history.
    """

    model_config = ConfigDict(extra="forbid")

    source_pids: list[str] = []
    result_keys: list[str] = []
    identity_relation: IdentityRelation
    policy_id: str = ""
    provenance_edges: list[KernelHistoryEdge] = []
    primary_identity_source: str | None = None

    # §2.5: orientation/location tracking
    orientation_before: str | None = None     # TopAbs_Orientation value
    orientation_after: str | None = None
    location_before: str | None = None        # TopLoc_Location hash (int)
    location_after: str | None = None
    occurrence_change: str = "none"

    @property
    def preserves_identity(self) -> bool:
        """True when the decision keeps the same persistent identity."""
        return self.identity_relation in (
            IdentityRelation.UNCHANGED,
            IdentityRelation.REORIENTED,
            IdentityRelation.RELOCATED,
            IdentityRelation.MODIFIED_SAME_IDENTITY,
        )

    @property
    def creates_new_identity(self) -> bool:
        """True when the decision creates a new persistent identity."""
        return self.identity_relation in (
            IdentityRelation.GENERATED_NEW_IDENTITY,
            IdentityRelation.GENERATED_FROM_TOOL,
            IdentityRelation.SPLIT,
            IdentityRelation.MERGE,
            IdentityRelation.REPARTITION,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# IdentityTransferPolicy — 8-dimension decision engine (§2.9)
# ═══════════════════════════════════════════════════════════════════════════════


class IdentityTransferPolicy:
    """Maps kernel observations to identity decisions.

    Dimensions (checked in priority order):
      1. source_role:        target | tool | profile | construction
      2. entity_dimension:   face | edge | vertex | solid
      3. operation_kind:     revolve | extrude | boolean_cut | fillet | …
      4. semantic_role_continuity: does semantic_role survive?
      5. source/result cardinality: 1:1 | 1:N | N:1 | N:M
      6. orientation_change: IsEqual | IsSame | IsPartner
      7. location_change:    same | relocated
      8. consumer_safety_class: cae_contact | cae_load | assembly | debug

    DEFAULT: kernel_modified + target face → modified_same_identity
    KEY EXCEPTION: kernel_modified + tool face → generated_from_tool
    """

    # Tool roles — kernel Modified on these means "consumed" not "unchanged"
    TOOL_ROLES = frozenset({"tool", "cutter", "pattern_tool", "construction"})
    # Profile roles — kernel Generated on these means "generated_new_identity"
    PROFILE_ROLES = frozenset({"profile", "sketch", "wire", "section"})

    @staticmethod
    def default_policy_id() -> str:
        return "v3_default_transfer_policy_v1"

    @staticmethod
    def decide(
        kernel_edges: list[KernelHistoryEdge],
        *,
        source_role: str = "target",
        operation_kind: str = "unknown",
        entity_dimension: str = "face",
        semantic_role_continuity: bool = True,
        cardinality: tuple[int, int] = (1, 1),
        orientation_change: str | None = None,
        location_change: str | None = None,
    ) -> IdentityDecision:
        """Decide identity transfer from kernel observations.

        Args:
            kernel_edges: Raw OCCT observations for this operation.
            source_role: Role of the source entity (target/tool/profile/construction).
            operation_kind: Dialect operation (revolve_profile, boolean_cut, …).
            entity_dimension: face | edge | vertex | solid.
            semantic_role_continuity: True if the semantic role survives.
            cardinality: (source_count, result_count).
            orientation_change: IsEqual | IsSame | IsPartner or None.
            location_change: same | relocated or None.

        Returns:
            IdentityDecision with full provenance.
        """
        source_count, result_count = cardinality
        source_pids = list(dict.fromkeys(e.source_pid for e in kernel_edges))
        result_keys = list(dict.fromkeys(e.result_occurrence_key for e in kernel_edges))

        # ── Dimension 5: cardinality-based decisions (take priority) ──
        if source_count > 1 and result_count > 1:
            return IdentityDecision(
                source_pids=source_pids, result_keys=result_keys,
                identity_relation=IdentityRelation.REPARTITION,
                policy_id=IdentityTransferPolicy.default_policy_id(),
                provenance_edges=kernel_edges,
            )
        if source_count > 1 and result_count == 1:
            return IdentityDecision(
                source_pids=source_pids, result_keys=result_keys,
                identity_relation=IdentityRelation.MERGE,
                policy_id=IdentityTransferPolicy.default_policy_id(),
                provenance_edges=kernel_edges,
            )
        if source_count == 1 and result_count > 1:
            return IdentityDecision(
                source_pids=source_pids, result_keys=result_keys,
                identity_relation=IdentityRelation.SPLIT,
                policy_id=IdentityTransferPolicy.default_policy_id(),
                provenance_edges=kernel_edges,
            )

        # ── Dimension 1: source_role dominates ──
        is_tool = source_role in IdentityTransferPolicy.TOOL_ROLES
        is_profile = source_role in IdentityTransferPolicy.PROFILE_ROLES

        # ── Check kernel relations ──
        has_removed = any(e.kernel_relation == KernelRelation.REMOVED for e in kernel_edges)
        has_generated = any(e.kernel_relation == KernelRelation.GENERATED for e in kernel_edges)
        has_modified = any(e.kernel_relation == KernelRelation.MODIFIED for e in kernel_edges)
        has_same = any(e.kernel_relation == KernelRelation.SAME for e in kernel_edges)

        if has_removed:
            if is_tool:
                return IdentityDecision(
                    source_pids=source_pids, result_keys=result_keys,
                    identity_relation=IdentityRelation.CONSUMED,
                    policy_id=IdentityTransferPolicy.default_policy_id(),
                    provenance_edges=kernel_edges,
                )
            return IdentityDecision(
                source_pids=source_pids, result_keys=result_keys,
                identity_relation=IdentityRelation.DELETED,
                policy_id=IdentityTransferPolicy.default_policy_id(),
                provenance_edges=kernel_edges,
            )

        # ── §2.5: orientation/location-aware unchanged detection ──
        if has_same and not has_modified and not has_generated:
            occurrence_change = "none"
            if orientation_change == "IsSame" and location_change == "relocated":
                occurrence_change = "relocated"
                rel = IdentityRelation.RELOCATED
            elif orientation_change == "IsPartner":
                occurrence_change = "reoriented_and_relocated"
                rel = IdentityRelation.RELOCATED
            elif orientation_change == "IsSame":
                occurrence_change = "reoriented"
                rel = IdentityRelation.REORIENTED
            else:
                rel = IdentityRelation.UNCHANGED

            return IdentityDecision(
                source_pids=source_pids, result_keys=result_keys,
                identity_relation=rel,
                policy_id=IdentityTransferPolicy.default_policy_id(),
                provenance_edges=kernel_edges,
                occurrence_change=occurrence_change,
            )

        # ── KEY RULE (§2.9): tool face + kernel modified → generated_from_tool ──
        if is_tool and has_modified:
            return IdentityDecision(
                source_pids=source_pids, result_keys=result_keys,
                identity_relation=IdentityRelation.GENERATED_FROM_TOOL,
                policy_id=IdentityTransferPolicy.default_policy_id(),
                provenance_edges=kernel_edges,
            )

        # ── Profile + generated → generated_new_identity ──
        if is_profile and has_generated:
            return IdentityDecision(
                source_pids=source_pids, result_keys=result_keys,
                identity_relation=IdentityRelation.GENERATED_NEW_IDENTITY,
                policy_id=IdentityTransferPolicy.default_policy_id(),
                provenance_edges=kernel_edges,
            )

        # ── Default: target face + modified → modified_same_identity ──
        if has_modified and not is_tool:
            return IdentityDecision(
                source_pids=source_pids, result_keys=result_keys,
                identity_relation=IdentityRelation.MODIFIED_SAME_IDENTITY,
                policy_id=IdentityTransferPolicy.default_policy_id(),
                provenance_edges=kernel_edges,
            )

        # ── Default: generated + not tool → generated_new_identity ──
        if has_generated:
            return IdentityDecision(
                source_pids=source_pids, result_keys=result_keys,
                identity_relation=IdentityRelation.GENERATED_NEW_IDENTITY,
                policy_id=IdentityTransferPolicy.default_policy_id(),
                provenance_edges=kernel_edges,
            )

        # ── Fallback: no kernel evidence → best effort ──
        if semantic_role_continuity and not is_tool:
            return IdentityDecision(
                source_pids=source_pids, result_keys=result_keys,
                identity_relation=IdentityRelation.MODIFIED_SAME_IDENTITY,
                policy_id="v3_fallback_semantic_continuity",
                provenance_edges=kernel_edges,
            )
        return IdentityDecision(
            source_pids=source_pids, result_keys=result_keys,
            identity_relation=IdentityRelation.GENERATED_NEW_IDENTITY,
            policy_id="v3_fallback_no_evidence",
            provenance_edges=kernel_edges,
        )
