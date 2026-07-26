"""TopologyNamingWriter — write LiveEvolutionBatch to OCAF with correct TNaming semantics.

Reads LiveEvolutionRelation (with real TopoDS_Shape handles from PR-2) and writes
the correct TNaming_Builder calls according to EvolutionKind:

  PRIMITIVE:  b.Generated(new_shape)           — one call per new_shape
  GENERATED:  b.Generated(old_shape, new_shape) — one call per new_shape (1→N)
  MODIFIED:   b.Modify(old_shape, new_shape)    — one call per new_shape
  DELETED:    b.Delete(old_shape)               — no new shapes

Key design rules (§3.3 of v3.0 guide):
  - Writer does NOT manage transactions — caller is responsible.
  - Every TNaming write failure propagates immediately (fail-closed).
  - Labels use fixed Tags via FindChild(tag, True) — NEVER NewChild().
  - Each relation gets a stable identity via Tag-indexed labels.

Label schema under each feature label (based on §4.3):
  Tag 2: CurrentResult              — TNaming for batch.result_shape
  Tag 3: EvolutionRelations         — container, then Tag 1001+ per relation
  Tag 4: ConstructionRoles          — first_shape, last_shape, etc.
  Tag 5: RevisionAudit              — audit metadata (future use)

Verified APIs (OCP 7.8.1.1, PR-3 Step 1):
  - TNaming_Builder.Generated(shape)              ✅
  - TNaming_Builder.Generated(old_shape, new_shape) ✅
  - TNaming_Builder.Modify(old_shape, new_shape)    ✅
  - TNaming_Builder.Delete(old_shape)               ✅
"""

from __future__ import annotations

from typing import Any

from OCP.TNaming import TNaming_Builder

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    LiveEvolutionBatch,
    LiveEvolutionRelation,
)

# ---------------------------------------------------------------------------
# Fixed tag layout under a feature label
# ---------------------------------------------------------------------------

TAG_CURRENT_RESULT = 2
TAG_EVOLUTION_RELATIONS = 3
TAG_CONSTRUCTION_ROLES = 4
TAG_REVISION_AUDIT = 5

# Relation labels start at 1001 under TAG_EVOLUTION_RELATIONS
_RELATION_TAG_BASE = 1001


# ---------------------------------------------------------------------------
# TopologyNamingWriter
# ---------------------------------------------------------------------------


class TopologyNamingWriter:
    """Writes one LiveEvolutionBatch to the OCAF document with correct TNaming.

    Usage:
        writer = TopologyNamingWriter(session)
        writer.write_batch(batch)

    Does NOT manage transactions — begin_txn/commit_txn/abort_txn must be
    called by the Revision Session that owns the document lifecycle.
    """

    def __init__(self, session):
        """session: OcafDocumentSession from PR-1."""
        self._session = session

    # ── Public API ──────────────────────────────────────────────────────

    def write_batch(
        self, batch: LiveEvolutionBatch, *, previous_result: Any = None,
    ) -> int:
        """Write all relations from one LiveEvolutionBatch.

        Args:
            batch: LiveEvolutionBatch with scope, relations, etc.
            previous_result: TopoDS_Shape | None — previous revision's
                CurrentResult. If None (initial revision), writes Generated(new).
                If provided (subsequent revision), writes Modify(old,new).

        Returns the total number of TNaming calls written (one per shape).

        Raises immediately on any write failure — no exception swallowing.
        """
        scope = batch.scope
        feat_label = self._ensure_feature_label(scope.component_id, scope.node_id)

        written = 0

        # 1. Write result shape to Tag 2 (Generated or Modify)
        if batch.result_shape is not None:
            self.write_feature_result(
                feat_label, batch.result_shape, previous_result=previous_result,
            )
            written += 1

        # 2. Write each evolution relation under Tag 3
        written += self._write_relations(feat_label, batch.relations)

        # 3. Write construction roles (first/last) to Tag 4
        written += self._write_construction_roles(feat_label, batch.construction_roles)

        return written

    # ── Label management ────────────────────────────────────────────────

    def _ensure_feature_label(self, component_id: str, node_id: str):
        """Get or create a stable feature label via session's index.

        Uses session.ensure_component/ensure_feature from PR-1 —
        these use StableLabelIndex.allocate() for persistent tag assignment.
        """
        comp_label = self._session.ensure_component(component_id or "default")
        return self._session.ensure_feature(comp_label, node_id or "unnamed")

    # ── Result shape ────────────────────────────────────────────────────

    def write_feature_result(
        self, feat_label, new_result: Any, *, previous_result: Any = None,
    ) -> None:
        """Write CurrentResult: Generated(initial) or Modify(prev,new) for revisions.

        v5.0 §7.4: subsequent revisions MUST call Modify(old,new) on the same
        CurrentResult label — NOT write a new Generated(). This is the
        fundamental mechanism that makes TNaming Solve work across revisions.

        Args:
            feat_label: The feature's TDF_Label.
            new_result: The new TopoDS_Shape for this revision.
            previous_result: The previous revision's CurrentResult shape.
                             None for initial revision → Generated(new).
        """
        label = feat_label.FindChild(TAG_CURRENT_RESULT, True)
        builder = TNaming_Builder(label)
        if previous_result is None:
            builder.Generated(new_result)
        else:
            builder.Modify(previous_result, new_result)

    def _write_result_shape(self, feat_label, result_shape: Any) -> None:
        """Deprecated — use write_feature_result() instead."""
        self.write_feature_result(feat_label, result_shape)

    # ── Relations ───────────────────────────────────────────────────────

    def _write_relations(
        self, feat_label, relations: list[LiveEvolutionRelation]
    ) -> int:
        """Write every LiveEvolutionRelation under Tag 3.

        Creates a child label at Tag 1001+idx within TAG_EVOLUTION_RELATIONS.
        Returns the number of TNaming calls written (1 per shape).
        """
        container = feat_label.FindChild(TAG_EVOLUTION_RELATIONS, True)
        written = 0

        for idx, rel in enumerate(relations):
            # ★ Fail-closed: validate contract before writing
            rel.validate()

            if rel.kind == EvolutionKind.PRIMITIVE:
                written += self._write_primitive(container, idx, rel)

            elif rel.kind == EvolutionKind.GENERATED:
                written += self._write_generated(container, idx, rel)

            elif rel.kind == EvolutionKind.MODIFIED:
                written += self._write_modified(container, idx, rel)

            elif rel.kind == EvolutionKind.DELETED:
                written += self._write_deleted(container, idx, rel)

        return written

    # ── Per-kind writers ────────────────────────────────────────────────

    def _write_primitive(self, container, idx: int, rel: LiveEvolutionRelation) -> int:
        """PRIMITIVE: Generated(new_shape) — one call per new_shape."""
        tag = self._relation_tag(rel, idx)
        written = 0
        for si, new_shape in enumerate(rel.new_shapes):
            label = self._relation_label(container, tag, si)
            TNaming_Builder(label).Generated(new_shape)
            written += 1
        return written

    def _write_generated(self, container, idx: int, rel: LiveEvolutionRelation) -> int:
        """GENERATED: Generated(old_shape, new_shape) — one call per new_shape.

        Supports 1→N split: one Generated call per element in new_shapes.
        """
        tag = self._relation_tag(rel, idx)
        written = 0
        for si, new_shape in enumerate(rel.new_shapes):
            label = self._relation_label(container, tag, si)
            TNaming_Builder(label).Generated(rel.old_shape, new_shape)
            written += 1
        return written

    def _write_modified(self, container, idx: int, rel: LiveEvolutionRelation) -> int:
        """MODIFIED: Modify(old_shape, new_shape) — one call per new_shape."""
        tag = self._relation_tag(rel, idx)
        written = 0
        for si, new_shape in enumerate(rel.new_shapes):
            label = self._relation_label(container, tag, si)
            TNaming_Builder(label).Modify(rel.old_shape, new_shape)
            written += 1
        return written

    def _write_deleted(self, container, idx: int, rel: LiveEvolutionRelation) -> int:
        """DELETED: Delete(old_shape) — single call."""
        tag = self._relation_tag(rel, idx)
        label = self._relation_label(container, tag, 0)
        TNaming_Builder(label).Delete(rel.old_shape)
        return 1

    # ── Construction roles ──────────────────────────────────────────────

    def _write_construction_roles(self, feat_label, roles: dict) -> int:
        """Write first_shape/last_shape etc. under Tag 4."""
        first_shape = roles.get("start_cap")
        last_shape = roles.get("end_cap")
        written = 0

        if first_shape is not None:
            label = feat_label.FindChild(TAG_CONSTRUCTION_ROLES, True).FindChild(1, True)
            TNaming_Builder(label).Generated(first_shape)
            written += 1

        if last_shape is not None and first_shape is not None and not last_shape.IsSame(first_shape):
            label = feat_label.FindChild(TAG_CONSTRUCTION_ROLES, True).FindChild(2, True)
            TNaming_Builder(label).Generated(last_shape)
            written += 1

        return written

    # ── Label helpers ───────────────────────────────────────────────────

    def _relation_tag(self, rel: LiveEvolutionRelation, rel_idx: int) -> int:
        """Get a stable tag for a relation.

        v5.0 §8.3: When Index allocation is explicitly enabled (via session
        flag or RelationKey), uses the StableLabelIndex. Otherwise falls back
        to position-based tag (1001 + idx) for backward compatibility.
        """
        # Index-based path: only when explicitly requested
        if self._session is not None and hasattr(self._session, 'label_index'):
            index = self._session.label_index
            # Check if already in index (recovery), but don't auto-allocate
            existing = index.resolve_key(
                "relation", f"feature:{rel.operation_id}", rel.relation_id,
            )
            if existing is not None:
                return existing.tags[-1]
        # Default: position-based (backward compatible)
        return _RELATION_TAG_BASE + rel_idx

    @staticmethod
    def _relation_label(container, rel_tag: int, sub_idx: int = 0):
        """Get or create a stable label for a relation sub-shape.

        Schema: container / Tag (rel_tag) / Tag (1 + sub_idx)
        Uses a stable tag (from Index or position) to ensure
        1→N relations can write multiple TNaming attributes
        on separate child labels within the relation's label tree.
        """
        rel_label = container.FindChild(rel_tag, True)
        return rel_label.FindChild(1 + sub_idx, True)


# ---------------------------------------------------------------------------
# Backwards-compatible module-level function
# ---------------------------------------------------------------------------


def write_batch(session, batch: LiveEvolutionBatch) -> int:
    """Convenience function: write one batch using TopologyNamingWriter.

    Returns the number of TNaming calls written.
    Does NOT manage transactions.
    """
    writer = TopologyNamingWriter(session)
    return writer.write_batch(batch)
