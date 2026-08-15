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
    TopologyEntityKind,
)

# ---------------------------------------------------------------------------
# Fixed tag layout under a feature label
# ---------------------------------------------------------------------------

# Import from schema for consistency (v6.0 §3.2)
from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
    FEATURE_TAG_RESULT_ROOT,
    FEATURE_TAG_RELATION_METADATA,
    FEATURE_TAG_CONSTRUCTION_ROLES,
    FEATURE_TAG_REVISION_AUDIT,
    ROLE_TAG_BASE,
)

# Backward-compat aliases
TAG_CURRENT_RESULT = FEATURE_TAG_RESULT_ROOT
TAG_EVOLUTION_RELATIONS = FEATURE_TAG_RELATION_METADATA
TAG_CONSTRUCTION_ROLES = FEATURE_TAG_CONSTRUCTION_ROLES
TAG_REVISION_AUDIT = FEATURE_TAG_REVISION_AUDIT

# Stable order of named face roles under ResultRoot. Each key maps to
# ROLE_TAG_BASE + index, so a role keeps the same label tag across revisions.
# start_cap/end_cap retain their historical tags 1001/1002.
ROLE_KEY_ORDER = ("start_cap", "end_cap", "+X", "-X", "+Y", "-Y", "rim", "bore", "web", "fillet", "chamfer")


def role_tag_for_key(role_key: str) -> int:
    """Return the stable ResultRoot child tag for a named face role."""
    try:
        index = ROLE_KEY_ORDER.index(role_key)
    except ValueError as exc:
        raise ValueError(f"unknown face role key: {role_key!r}") from exc
    return ROLE_TAG_BASE + index


EDGE_ROLE_TAG_BASE = 2001

# Axis-aligned box edges derived from adjacent face roles. Each edge is the
# intersection of exactly two of the six box faces; the stable key is the
# sorted pair of face role keys.
_BOX_EDGE_FACE_PAIRS = (
    ("start_cap", "+X"), ("start_cap", "-X"), ("start_cap", "+Y"), ("start_cap", "-Y"),
    ("end_cap", "+X"), ("end_cap", "-X"), ("end_cap", "+Y"), ("end_cap", "-Y"),
    ("+X", "+Y"), ("+X", "-Y"), ("-X", "+Y"), ("-X", "-Y"),
)


def edge_role_key(face_a: str, face_b: str) -> str:
    """Return the stable key for an edge shared by two face roles."""
    return "/".join(sorted((face_a, face_b)))


EDGE_ROLE_KEYS = tuple(edge_role_key(a, b) for a, b in _BOX_EDGE_FACE_PAIRS)


def edge_tag_for_key(edge_key: str) -> int:
    """Return the stable ResultRoot child tag for a named box edge role."""
    try:
        index = EDGE_ROLE_KEYS.index(edge_key)
    except ValueError as exc:
        raise ValueError(f"unknown edge role key: {edge_key!r}") from exc
    return EDGE_ROLE_TAG_BASE + index


def _stable_relation_id(rel: LiveEvolutionRelation) -> str:
    """Prefer a semantic RelationKey when present, else keep the legacy id."""
    if rel.relation_key is None:
        return rel.relation_id
    ref = rel.relation_key.source_entity_ref
    return (
        f"rk:{rel.relation_key.feature_id}"
        f":{ref.component_id}:{ref.feature_id}:{ref.selection_id or ''}"
        f":{ref.construction_role or ''}:{ref.entity_kind.value}"
        f":{rel.relation_key.evolution_kind.value}"
        f":{rel.relation_key.relation_role}"
    )


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

        # 2. Write construction roles (first/last) to Tag 4
        written += self._write_construction_roles(feat_label, batch.construction_roles)

        # 3. Write derived edge roles under ResultRoot (v8 Stage 1)
        written += self._write_edge_roles(feat_label, getattr(batch, "edge_roles", {}))

        # 4. Write every persisted face role under ResultRoot.
        face_roles = getattr(batch, "face_roles", {}) or {}
        feature_namespace = f"feature:{scope.node_id or scope.operation or 'unnamed'}"
        written += self._write_face_roles(feat_label, face_roles, feature_namespace)

        # 5. Write evolution relations under Tag 3. Face relations that are now
        # represented by face_roles are skipped so Solve only follows the stable
        # ResultRoot chain instead of a duplicate/possibly-broken relation chain.
        written += self._write_relations(
            feat_label, batch.relations, face_roles=face_roles,
        )

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

    def write_role_result(
        self, feat_label, role_tag: int, face: Any,
        *, previous_face: Any = None,
    ) -> None:
        """Write a semantic role face under ResultRoot as TNaming_NamedShape.

        v6.0 §3.2: Sub-shape history must be children of ResultRoot so that
        OCCT Selector can find them during Solve. Each role gets its own
        child label with a single TNaming_Builder entry.

        Args:
            feat_label: The feature's TDF_Label.
            role_tag: Tag under ResultRoot (e.g. 1001 for top_role).
            face: The TopoDS_Face for this role.
            previous_face: Previous revision's face for Modify. None → Generated.
        """
        result_root = feat_label.FindChild(FEATURE_TAG_RESULT_ROOT, True)
        role_label = result_root.FindChild(role_tag, True)
        builder = TNaming_Builder(role_label)
        if previous_face is None:
            builder.Generated(face)
        else:
            builder.Modify(previous_face, face)

    def _write_result_shape(self, feat_label, result_shape: Any) -> None:
        """Deprecated — use write_feature_result() instead."""
        self.write_feature_result(feat_label, result_shape)

    # ── Relations ───────────────────────────────────────────────────────

    def _write_relations(
        self, feat_label, relations: list[LiveEvolutionRelation], *,
        face_roles: dict | None = None,
    ) -> int:
        """Write every LiveEvolutionRelation under Tag 3.

        Each relation gets a stable Index-allocated tag (v6.0 §11.2 — no
        position fallback), so the same relation_id maps to the same tag
        regardless of list order.
        Returns the number of TNaming calls written (1 per shape).
        """
        container = feat_label.FindChild(TAG_EVOLUTION_RELATIONS, True)
        component_tag, feature_tag = self._component_feature_tags(feat_label)
        written = 0

        for rel in relations:
            # ★ Fail-closed: validate contract before writing
            rel.validate()

            if (
                face_roles
                and rel.entity_kind == TopologyEntityKind.FACE
                and rel.kind in (EvolutionKind.GENERATED, EvolutionKind.MODIFIED)
            ):
                continue

            if rel.kind == EvolutionKind.PRIMITIVE:
                written += self._write_primitive(container, rel, component_tag, feature_tag)

            elif rel.kind == EvolutionKind.GENERATED:
                written += self._write_generated(container, rel, component_tag, feature_tag)

            elif rel.kind == EvolutionKind.MODIFIED:
                written += self._write_modified(container, rel, component_tag, feature_tag)

            elif rel.kind == EvolutionKind.DELETED:
                written += self._write_deleted(container, rel, component_tag, feature_tag)

        return written

    # ── Per-kind writers ────────────────────────────────────────────────

    def _write_primitive(self, container, rel, component_tag, feature_tag) -> int:
        """PRIMITIVE: Generated(new_shape) — one call per new_shape."""
        tag = self._relation_tag(rel, component_tag, feature_tag)
        written = 0
        for si, new_shape in enumerate(rel.new_shapes):
            label = self._relation_label(container, tag, si)
            TNaming_Builder(label).Generated(new_shape)
            written += 1
        return written

    def _write_generated(self, container, rel, component_tag, feature_tag) -> int:
        """GENERATED: one Builder writes all old→new pairs (v6.0 §11.3).

        Uses a single TNaming_Builder on one label for 1→N relations.
        Multiple Generated calls on the same builder → one NamedShape with SET.
        """
        tag = self._relation_tag(rel, component_tag, feature_tag)
        label = self._relation_label(container, tag)  # same label for all
        builder = TNaming_Builder(label)
        for new_shape in rel.new_shapes:
            builder.Generated(rel.old_shape, new_shape)
        return len(rel.new_shapes)

    def _write_modified(self, container, rel, component_tag, feature_tag) -> int:
        """MODIFIED: one Builder writes all old→new pairs (v6.0 §11.3)."""
        tag = self._relation_tag(rel, component_tag, feature_tag)
        label = self._relation_label(container, tag)
        builder = TNaming_Builder(label)
        for new_shape in rel.new_shapes:
            builder.Modify(rel.old_shape, new_shape)
        return len(rel.new_shapes)

    def _write_deleted(self, container, rel, component_tag, feature_tag) -> int:
        """DELETED: Delete(old_shape) — single call."""
        tag = self._relation_tag(rel, component_tag, feature_tag)
        label = self._relation_label(container, tag, 0)
        TNaming_Builder(label).Delete(rel.old_shape)
        return 1

    # ── Construction roles ──────────────────────────────────────────────

    def _write_construction_roles(self, feat_label, roles: dict) -> int:
        """Write named role faces under ResultRoot (v7 T12-c / role registry).

        Role faces are written as children of ResultRoot (Tag 2) so
        TNaming_Selector can find them during Solve. Cross-revision roles are
        written as Modify(prev_face, new_face). The tag for each role is
        derived from its position in ROLE_KEY_ORDER so it is stable across
        revisions.
        """
        written = 0
        written_faces: list[Any] = []
        for index, role_key in enumerate(ROLE_KEY_ORDER):
            face = roles.get(role_key)
            if face is None:
                continue
            # Guard against the same TShape being written under two roles.
            if any(face.IsSame(prev_face) for prev_face in written_faces):
                continue
            role_tag = ROLE_TAG_BASE + index
            previous_face = self._get_previous_role_result(feat_label, role_tag)
            self.write_role_result(
                feat_label, role_tag, face, previous_face=previous_face,
            )
            written_faces.append(face)
            written += 1

        return written

    def _write_edge_roles(self, feat_label, edge_roles: dict) -> int:
        """Write derived box edge roles under ResultRoot (v8 Stage 1).

        Edge tags use EDGE_ROLE_TAG_BASE + index in EDGE_ROLE_KEYS so the same
        edge keeps the same label across revisions. Subsequent revisions write
        Modify(prev_edge, new_edge) via the shared write_role_result helper.
        """
        written = 0
        written_edges: list[Any] = []
        for index, edge_key in enumerate(EDGE_ROLE_KEYS):
            edge = edge_roles.get(edge_key)
            if edge is None:
                continue
            if any(edge.IsSame(prev_edge) for prev_edge in written_edges):
                continue
            edge_tag = EDGE_ROLE_TAG_BASE + index
            previous_edge = self._get_previous_role_result(feat_label, edge_tag)
            self.write_role_result(
                feat_label, edge_tag, edge, previous_face=previous_edge,
            )
            written_edges.append(edge)
            written += 1

        return written

    def _write_face_roles(
        self, feat_label, face_roles: dict, feature_namespace: str,
    ) -> int:
        """Write per-face naming entries under ResultRoot.

        Each face gets a stable Index-allocated child tag under
        ``Feature/ResultRoot``. On subsequent revisions the previous face is
        retrieved and linked with ``Modify(previous_face, face)``. On first
        occurrence, a cross-feature source is written when available so
        TNaming_Selector can follow e.g. box face -> fillet face.
        """
        written = 0
        written_shapes: list[Any] = []
        component_tag, feature_tag = self._component_feature_tags(feat_label)

        for role_key, spec in face_roles.items():
            if spec is None or getattr(spec, "shape", None) is None:
                continue
            shape = spec.shape
            if any(shape.IsSame(prev_shape) for prev_shape in written_shapes):
                continue

            entry = self._session.label_index.allocate_face_role(
                component_tag, feature_tag, feature_namespace, role_key,
                self._session.revision_number,
            )
            label = entry.tag_path.resolve_or_create(self._session.main_label)
            previous_face = self._get_previous_role_result(
                feat_label, entry.tag_path.tags[-1],
            )

            builder = TNaming_Builder(label)
            if previous_face is not None:
                builder.Modify(previous_face, shape)
            elif getattr(spec, "source_shape", None) is not None:
                source = spec.source_shape
                first_evolution = getattr(spec, "first_evolution", None)
                if first_evolution is EvolutionKind.MODIFIED:
                    builder.Modify(source, shape)
                else:
                    builder.Generated(source, shape)
            else:
                builder.Generated(shape)

            written_shapes.append(shape)
            written += 1

        return written

    def _get_previous_role_result(self, feat_label, role_tag: int):
        """Return the previous revision's role face, or None (first revision)."""
        getter = getattr(self._session, "get_current_role_result", None)
        if getter is None:
            return None
        return getter(feat_label, role_tag)

    # ── Label helpers ───────────────────────────────────────────────────

    def _relation_tag(self, rel: LiveEvolutionRelation, component_tag: int, feature_tag: int) -> int:
        """Allocate (or recover) a stable Index-based tag for a relation.

        v6.0 §11.2: the tag is keyed by the relation's content identity
        (feature namespace + relation_id), never by list position.
        """
        index = self._session.label_index
        entry = index.allocate_relation(
            component_tag, feature_tag,
            f"feature:{rel.operation_id}", _stable_relation_id(rel),
            self._session.revision_number,
        )
        return entry.tag_path.tags[-1]

    def _component_feature_tags(self, feat_label):
        """Return (component_tag, feature_tag) by walking the label parents."""
        feature_tag = feat_label.Tag()
        component_label = feat_label.Father().Father()
        return component_label.Tag(), feature_tag

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
