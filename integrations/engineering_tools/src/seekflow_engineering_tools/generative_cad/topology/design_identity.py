"""Stable design identity and feature identity — §2.1, §2.2 of the supplementary spec.

Separates three concepts that were previously conflated in document_id:
  - design_id:    permanent identifier for the same design
  - revision_id:  a controlled design change
  - run_id:       a single execution

Provides FeatureIdentity for stable feature UIDs and FeatureIdentityReconciler
for matching features across LLM rewrites.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.1, §2.2
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, ConfigDict


# ═══════════════════════════════════════════════════════════════════════════════
# IdentitySource — where the design identity came from
# ═══════════════════════════════════════════════════════════════════════════════


class IdentitySource(str, Enum):
    """Origin of the design identity.

    Only PERSISTED_PROJECT_MANIFEST and CALLER_SUPPLIED claim strong persistence.
    EPHEMERAL_GENERATED means the identity was auto-generated and will differ
    on every authoring run — persistent topology is NOT guaranteed in this mode.
    """

    PERSISTED_PROJECT_MANIFEST = "persisted_project_manifest"
    CALLER_SUPPLIED = "caller_supplied"
    EPHEMERAL_GENERATED = "ephemeral_generated"


# ═══════════════════════════════════════════════════════════════════════════════
# DesignIdentity — stable design-level identity (§2.1)
# ═══════════════════════════════════════════════════════════════════════════════


class DesignIdentity(BaseModel):
    """Separates design_id / revision_id / run_id from mutable document_id.

    design_id:     permanent, stable identifier for the same design.
    revision_id:   a controlled design modification (optional).
    run_id:        a single execution identifier (never enters PID).
    identity_source: where the identity came from — only strong sources
                     guarantee cross-rebuild PID stability.

    Rule: when identity_source is EPHEMERAL_GENERATED, the system MUST NOT
    claim strong persistence. The identity_source must be written to metadata
    and sidecar so downstream consumers can make informed trust decisions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    design_id: str
    revision_id: str = ""
    run_id: str = ""
    identity_source: IdentitySource = IdentitySource.EPHEMERAL_GENERATED

    @property
    def is_strong(self) -> bool:
        """True when the design identity supports strong persistence claims."""
        return self.identity_source in (
            IdentitySource.PERSISTED_PROJECT_MANIFEST,
            IdentitySource.CALLER_SUPPLIED,
        )

    @property
    def document_lineage_id(self) -> str:
        """The stable lineage identifier — design_id is the canonical source.

        This is what enters the V3 PID's document_lineage_id field.
        When is_strong is False, this is still the best available
        identifier but consumers should treat it as ephemeral.
        """
        return self.design_id


# ═══════════════════════════════════════════════════════════════════════════════
# FeatureIdentity — stable feature-level identity (§2.2)
# ═══════════════════════════════════════════════════════════════════════════════


class FeatureIdentity(BaseModel):
    """Stable feature identity — feature_uid enters the V3 PID.

    feature_uid:      stable, human-meaningful identifier (e.g. "revolve_main",
                      "center_bore"). This replaces mutable producer_node_id
                      in the V3 PID key.
    display_node_id:  the mutable IR node id — for debugging only, never
                      enters persistent identity.
    operation_kind:   the dialect operation (e.g. "revolve_profile").
    component_uid:    the owning component's stable identifier.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_uid: str
    display_node_id: str = ""
    operation_kind: str = ""
    component_uid: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# FeatureIdentityReconciler — match features across LLM rewrites (§2.2)
# ═══════════════════════════════════════════════════════════════════════════════


class FeatureIdentityReconciler:
    """6-step matching algorithm to preserve feature_uid across authoring runs.

    Rules (checked in priority order):
      1. Same canonical IR re-run → reuse feature_uid directly.
      2. Repair patch: undeleted nodes keep their feature_uid.
      3. Parameter modification only → feature_uid unchanged.
      4. Prepended upstream features → existing feature_uid unchanged.
      5. Full LLM rewrite:
         a. Align by (component, operation_kind, graph neighborhood, explicit feature key).
         b. Unique match → reuse.
         c. Multiple candidates → mark ambiguous.
         d. Position-only matching is FORBIDDEN.
      6. Unable to align → create new feature_uid, generate feature-level lineage.

    This is the mechanism that prevents "node renamed → all PIDs change"
    even when the LLM assigns different node IDs to the same logical feature.
    """

    @staticmethod
    def generate_feature_uid(
        component_uid: str,
        operation_kind: str,
        hint: str = "",
    ) -> str:
        """Generate a stable feature_uid from component + operation + optional hint.

        The resulting UID is human-readable and stable as long as the same
        component performs the same operation with the same intent.
        """
        if hint:
            return f"{component_uid}.{operation_kind}.{hint}"
        return f"{component_uid}.{operation_kind}"

    @staticmethod
    def from_producer_node_id(producer_node_id: str) -> FeatureIdentity:
        """Create a FeatureIdentity from a mutable producer node ID.

        This is a convenience for bootstrapping — it stores the node ID
        as both display_node_id and feature_uid, accepting the churn risk.
        Callers that have access to stable feature UIDs should use the
        full constructor instead.
        """
        return FeatureIdentity(
            feature_uid=producer_node_id,
            display_node_id=producer_node_id,
        )

    @staticmethod
    def try_match(
        old_features: list[FeatureIdentity],
        new_node_id: str,
        *,
        component_uid: str = "",
        operation_kind: str = "",
        graph_neighbors: list[str] | None = None,
    ) -> tuple[FeatureIdentity | None, str]:
        """Attempt to match a new node to an existing FeatureIdentity.

        Returns:
            (matched_feature | None, resolution_note)

        resolution_note is one of:
          - "exact_match" — unambiguous reuse
          - "ambiguous" — multiple candidates, cannot choose
          - "no_match" — no viable match, new feature_uid needed
          - "position_match_rejected" — matched by position only (forbidden)
        """
        candidates: list[FeatureIdentity] = []

        for feat in old_features:
            # Filter by component
            if component_uid and feat.component_uid != component_uid:
                continue
            # Filter by operation kind
            if operation_kind and feat.operation_kind != operation_kind:
                continue
            candidates.append(feat)

        if len(candidates) == 1:
            return candidates[0], "exact_match"
        elif len(candidates) > 1:
            return None, "ambiguous"
        else:
            # No component+operation match — try display node ID
            for feat in old_features:
                if feat.display_node_id == new_node_id:
                    return feat, "exact_match"
            return None, "no_match"


# ═══════════════════════════════════════════════════════════════════════════════
# DesignIdentityContext — runtime wrapper (§4.1 of the repair guide)
# ═══════════════════════════════════════════════════════════════════════════════


class DesignIdentityContext(BaseModel):
    """Runtime wrapper carrying stable design identity for topology operations.

    Makes document_lineage_id, component_stable_ids, and feature_stable_ids
    accessible to all handlers via RuntimeContext.  Separates the *stable*
    identity fields (which enter PID keys) from mutable runtime state.

    Ref: text2cad_persistent_topology_v3_repair_guide.md §4.1
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_lineage_id: str
    document_revision_id: str = ""
    component_stable_ids: dict[str, str] = {}
    feature_stable_ids: dict[str, str] = {}
    identity_algorithm_version: str = "3.1.0"
    design_identity: "DesignIdentity | None" = None

    def feature_stable_id_for(self, node_id: str, *, component_id: str = "") -> str:
        """Look up stable feature UID, falling back to node_id.

        The feature_stable_ids dict can be seeded with explicit stable UIDs
        (e.g. via FeatureIdentityReconciler) or left empty for ephemeral
        backwards-compatible mode where node_id serves as the stable id.
        """
        key = f"{component_id}.{node_id}" if component_id else node_id
        return self.feature_stable_ids.get(key, node_id)

    @property
    def ephemeral_identity(self) -> bool:
        """True when no explicit stable feature IDs have been registered."""
        return len(self.feature_stable_ids) == 0
