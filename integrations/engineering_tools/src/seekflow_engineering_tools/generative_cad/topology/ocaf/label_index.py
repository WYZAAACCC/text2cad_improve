"""StableLabelIndex v2 — persistent object_id -> TagPath mapping with OCAF storage.

v5.0 §5.3-5.6: fail-closed load, safe attribute readers, expanded kind set,
separate counters per object kind, schema version validation, retirement strategy.

Tag 100/7 schema (v5.0 §5.4):
  100:7 StableIdIndex
  ├── 1 Metadata
  │   ├── 1 schema_version   (TDataStd_AsciiString)
  │   └── 2 index_revision   (TDataStd_Integer)
  ├── 2 Counters
  │   ├── 1 component_next   (TDataStd_Integer)
  │   ├── 2 feature_next     (TDataStd_Integer)
  │   ├── 3 selection_next   (TDataStd_Integer)
  │   ├── 4 relation_next    (TDataStd_Integer)
  │   ├── 5 revision_next    (TDataStd_Integer)
  │   └── 6 cae_binding_next (TDataStd_Integer)
  └── 3 Entries
      └── <entry_tag>        (TDataStd_AsciiString: JSON)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    read_ascii_string,
    read_integer,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
    CorruptStableIndexError,
    StableLabelConflictError,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import StableObjectKey
from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
    DESIGN_ROOT_TAG,
    DYNAMIC_TAG_START,
    INDEX_TAG_METADATA,
    INDEX_TAG_COUNTERS,
    INDEX_TAG_ENTRIES,
    INDEX_META_SCHEMA_VERSION,
    INDEX_META_INDEX_REVISION,
    INDEX_COUNTER_KINDS,
    TAG_COMPONENTS,
    TAG_SELECTIONS,
    TAG_REVISIONS,
    TAG_CAE_BINDINGS,
    COMPONENT_TAG_FEATURES,
    FEATURE_TAG_RESULT_ROOT,
    FEATURE_TAG_RELATION_METADATA,
    TAGPATH_STABLE_ID_INDEX,
    TagPath,
    make_component_tagpath,
    make_feature_tagpath,
    make_selection_tagpath,
)

# ---------------------------------------------------------------------------
# Schema version — bump on incompatible index changes
# ---------------------------------------------------------------------------

INDEX_SCHEMA_VERSION = "gcad_topo_v4@ocaf_v2"

# ---------------------------------------------------------------------------
# IndexEntry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexEntry:
    """A single record in the StableLabelIndex."""
    key: StableObjectKey
    tag_path: TagPath
    created_revision: int
    retired_revision: int | None = None
    schema_version: str = INDEX_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# StableLabelIndex v2
# ---------------------------------------------------------------------------


@dataclass
class StableLabelIndex:
    """Persistent object_id -> TagPath mapping with fail-closed OCAF load.

    v2 changes (v5.0 §5.3-5.6):
      - Safe attribute readers (compat.read_*) instead of non-existent Get_s()
      - Schema version validation on load
      - Separate counter per object kind (component/feature/selection/relation/revision/cae_binding)
      - Full entry validation (key uniqueness, path uniqueness, label existence, counter consistency)
      - Retirement strategy: tags never reused, retired_revision recorded
      - get_existing() for read-only query without allocation
    """

    _by_key: dict[str, IndexEntry] = field(default_factory=dict)
    _by_path: dict[TagPath, IndexEntry] = field(default_factory=dict)
    _next_tags: dict[str, int] = field(default_factory=lambda: {
        kind: DYNAMIC_TAG_START for kind in INDEX_COUNTER_KINDS
    })

    def __post_init__(self):
        # revision numbers start at 1, not DYNAMIC_TAG_START
        if self._next_tags.get("revision", DYNAMIC_TAG_START) == DYNAMIC_TAG_START:
            self._next_tags["revision"] = 1

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def resolve_key(self, object_kind: str, namespace: str, object_id: str) -> TagPath | None:
        """Look up a TagPath by composite key. Returns None if not found."""
        key_str = str(StableObjectKey(object_kind, namespace, object_id))
        entry = self._by_key.get(key_str)
        return entry.tag_path if entry else None

    def resolve_path(self, path: TagPath) -> IndexEntry | None:
        """Look up an IndexEntry by TagPath."""
        return self._by_path.get(path)

    def get_existing(self, object_kind: str, namespace: str, object_id: str) -> IndexEntry | None:
        """Read-only query — NEVER allocates. Returns None if not in index.

        This is the primary API for proving index recovery (Index-1 test):
        open an OCAF document, call get_existing() without any ensure_*(),
        and assert the returned TagPath is correct.
        """
        key_str = str(StableObjectKey(object_kind, namespace, object_id))
        return self._by_key.get(key_str)

    def is_allocated(self, object_kind: str, namespace: str, object_id: str) -> bool:
        key_str = str(StableObjectKey(object_kind, namespace, object_id))
        return key_str in self._by_key

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

    def allocate(
        self, object_kind: str, namespace: str, object_id: str, revision: int
    ) -> IndexEntry:
        """Allocate a new TagPath for the given composite key.

        If already allocated with the same kind, returns the existing entry (idempotent).
        If allocated with a different kind, raises StableLabelConflictError.
        """
        key = StableObjectKey(object_kind, namespace, object_id)
        key_str = str(key)

        existing = self._by_key.get(key_str)
        if existing is not None:
            if existing.key.object_kind != object_kind:
                raise StableLabelConflictError(
                    f"Key {key_str} already allocated as {existing.key.object_kind!r}",
                    object_id=object_id,
                )
            return existing  # idempotent

        tag = self._next_tags.get(object_kind, DYNAMIC_TAG_START)
        self._next_tags[object_kind] = tag + 1

        if object_kind == "component":
            tag_path = make_component_tagpath(tag)
        elif object_kind == "feature":
            raise ValueError("Use allocate_feature() for features")
        elif object_kind == "selection":
            tag_path = make_selection_tagpath(tag)
        elif object_kind == "relation":
            raise ValueError("Use allocate_relation() for relations")
        elif object_kind == "revision":
            tag_path = TagPath((DESIGN_ROOT_TAG, TAG_REVISIONS, tag))
        elif object_kind == "cae_binding":
            tag_path = TagPath((DESIGN_ROOT_TAG, TAG_CAE_BINDINGS, tag))
        else:
            raise ValueError(f"Unknown object_kind: {object_kind!r}")

        entry = IndexEntry(key=key, tag_path=tag_path, created_revision=revision)
        self._by_key[key_str] = entry
        self._by_path[tag_path] = entry
        return entry

    def allocate_feature(
        self, component_tag: int, feature_namespace: str, object_id: str, revision: int
    ) -> IndexEntry:
        """Allocate a new feature label within a component."""
        key = StableObjectKey("feature", feature_namespace, object_id)
        key_str = str(key)

        existing = self._by_key.get(key_str)
        if existing is not None:
            return existing

        tag = self._next_tags["feature"]
        self._next_tags["feature"] = tag + 1
        tag_path = make_feature_tagpath(component_tag, tag)

        entry = IndexEntry(key=key, tag_path=tag_path, created_revision=revision)
        self._by_key[key_str] = entry
        self._by_path[tag_path] = entry
        return entry

    # ------------------------------------------------------------------
    # Retirement
    # ------------------------------------------------------------------

    def allocate_relation(
        self, component_tag: int, feature_tag: int,
        feature_namespace: str, relation_id: str, revision: int,
    ) -> IndexEntry:
        """Allocate a stable tag for an evolution relation within a feature.

        v5.0 §8.3 / v6.0 §11.2: Relation labels must not depend on list
        position. The tag is allocated via the Index from a stable content key
        (feature namespace + relation_id), and the tag_path points to the real
        relation label under the owning feature.
        """
        key = StableObjectKey("relation", feature_namespace, relation_id)
        key_str = str(key)

        existing = self._by_key.get(key_str)
        if existing is not None:
            return existing

        tag = self._next_tags.get("relation", DYNAMIC_TAG_START)
        self._next_tags["relation"] = tag + 1
        tag_path = TagPath((
            DESIGN_ROOT_TAG, TAG_COMPONENTS, component_tag,
            COMPONENT_TAG_FEATURES, feature_tag,
            FEATURE_TAG_RELATION_METADATA, tag,
        ))

        entry = IndexEntry(key=key, tag_path=tag_path, created_revision=revision)
        self._by_key[key_str] = entry
        self._by_path[tag_path] = entry
        return entry

    def allocate_face_role(
        self,
        component_tag: int,
        feature_tag: int,
        feature_namespace: str,
        role_key: str,
        revision: int,
    ) -> IndexEntry:
        """Allocate a stable tag for a per-face naming role under ResultRoot.

        The face role label is a child of ``Feature/ResultRoot``, so
        ``TNaming_Selector.Solve`` can follow it together with the feature
        result and semantic construction roles. The same (feature namespace,
        role_key) maps to the same tag across revisions.
        """
        key = StableObjectKey("face_role", feature_namespace, role_key)
        key_str = str(key)

        existing = self._by_key.get(key_str)
        if existing is not None:
            return existing

        tag = self._next_tags.get("face_role", DYNAMIC_TAG_START)
        self._next_tags["face_role"] = tag + 1
        tag_path = TagPath((
            DESIGN_ROOT_TAG, TAG_COMPONENTS, component_tag,
            COMPONENT_TAG_FEATURES, feature_tag,
            FEATURE_TAG_RESULT_ROOT, tag,
        ))

        entry = IndexEntry(key=key, tag_path=tag_path, created_revision=revision)
        self._by_key[key_str] = entry
        self._by_path[tag_path] = entry
        return entry

    def retire(self, object_kind: str, namespace: str, object_id: str, revision: int) -> None:
        """Mark an entry as retired. Tag is never reused (v5.0 §5.6)."""
        key_str = str(StableObjectKey(object_kind, namespace, object_id))
        entry = self._by_key.get(key_str)
        if entry is None:
            return
        retired = IndexEntry(
            key=entry.key, tag_path=entry.tag_path,
            created_revision=entry.created_revision, retired_revision=revision,
            schema_version=entry.schema_version,
        )
        self._by_key[key_str] = retired
        self._by_path[entry.tag_path] = retired

    # ------------------------------------------------------------------
    # OCAF persistence — v2 schema (v5.0 §5.4)
    # ------------------------------------------------------------------

    def save_to_ocaf(self, main_label) -> None:
        """Write index metadata, counters, and entries to Tag 100/7.

        Uses only Set_s() for writing — safe in OCP 7.8.1.1.
        """
        from OCP.TDataStd import TDataStd_Integer, TDataStd_AsciiString
        from OCP.TCollection import TCollection_AsciiString as TCAscii

        idx_root = TAGPATH_STABLE_ID_INDEX.resolve_or_create(main_label)

        # ── 1 Metadata ──
        meta = idx_root.FindChild(INDEX_TAG_METADATA, True)
        TDataStd_AsciiString.Set_s(
            meta.FindChild(INDEX_META_SCHEMA_VERSION, True),
            TCAscii(INDEX_SCHEMA_VERSION),
        )
        TDataStd_Integer.Set_s(
            meta.FindChild(INDEX_META_INDEX_REVISION, True),
            1,  # index revision counter
        )

        # ── 2 Counters ──
        counters = idx_root.FindChild(INDEX_TAG_COUNTERS, True)
        for i, kind in enumerate(INDEX_COUNTER_KINDS, 1):
            val = self._next_tags.get(kind, DYNAMIC_TAG_START)
            TDataStd_Integer.Set_s(counters.FindChild(i, True), val)

        # ── 3 Entries ──
        entries_label = idx_root.FindChild(INDEX_TAG_ENTRIES, True)
        entry_tag = DYNAMIC_TAG_START + 1  # 1001
        for entry in self._by_key.values():
            e_label = entries_label.FindChild(entry_tag, True)
            entry_tag += 1
            data = json.dumps({
                "object_kind": entry.key.object_kind,
                "namespace": entry.key.namespace,
                "object_id": entry.key.object_id,
                "tag_path": ":".join(str(t) for t in entry.tag_path.tags),
                "created_revision": entry.created_revision,
                "retired_revision": entry.retired_revision,
                "schema_version": entry.schema_version,
            })
            TDataStd_AsciiString.Set_s(e_label, TCAscii(data))

    def load_from_ocaf(self, main_label) -> None:
        """Rebuild index from Tag 100/7 using safe attribute readers.

        v5.0 §5.5: implements all 10 load validations.
        Raises CorruptStableIndexError on any integrity violation.
        """
        self._by_key.clear()
        self._by_path.clear()

        idx_root = TAGPATH_STABLE_ID_INDEX.resolve(main_label)
        if idx_root.IsNull():
            return  # No index yet — first revision

        # ── 1 Metadata (validate schema version) ──
        meta = idx_root.FindChild(INDEX_TAG_METADATA, False)
        if not meta.IsNull():
            schema_ver = read_ascii_string(
                meta.FindChild(INDEX_META_SCHEMA_VERSION, False)
            )
            if schema_ver is not None and schema_ver != INDEX_SCHEMA_VERSION:
                raise CorruptStableIndexError(
                    f"Index schema version mismatch: stored={schema_ver!r}, "
                    f"expected={INDEX_SCHEMA_VERSION!r}",
                    schema_version=schema_ver,
                )

        # ── 2 Counters ──
        counters_label = idx_root.FindChild(INDEX_TAG_COUNTERS, False)
        counters_loaded: dict[str, int] = {}
        if not counters_label.IsNull():
            for i, kind in enumerate(INDEX_COUNTER_KINDS, 1):
                c = counters_label.FindChild(i, False)
                if not c.IsNull():
                    val = read_integer(c)
                    if val is not None:
                        counters_loaded[kind] = val
                        self._next_tags[kind] = val

        # ── 3 Entries ──
        entries_label = idx_root.FindChild(INDEX_TAG_ENTRIES, False)
        if entries_label.IsNull():
            return  # No entries yet

        from OCP.TDF import TDF_ChildIterator

        seen_keys: set[str] = set()
        seen_paths: set[TagPath] = set()
        max_tags: dict[str, int] = {}

        it = TDF_ChildIterator(entries_label)
        while it.More():
            e_label = it.Value()
            it.Next()

            # Read entry JSON
            raw = read_ascii_string(e_label)
            if raw is None:
                raise CorruptStableIndexError(
                    f"Index entry at tag {e_label.Tag()} has no readable data",
                    entry_tag=e_label.Tag(),
                )

            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise CorruptStableIndexError(
                    f"Index entry at tag {e_label.Tag()} is not valid JSON: {exc}",
                    entry_tag=e_label.Tag(),
                ) from exc

            # Validate required fields
            for field in ("object_kind", "namespace", "object_id", "tag_path", "created_revision"):
                if field not in data:
                    raise CorruptStableIndexError(
                        f"Index entry at tag {e_label.Tag()} missing required field {field!r}",
                        entry_tag=e_label.Tag(),
                    )

            # Build key
            try:
                key = StableObjectKey(
                    object_kind=data["object_kind"],
                    namespace=data["namespace"],
                    object_id=data["object_id"],
                )
            except ValueError as exc:
                raise CorruptStableIndexError(
                    f"Index entry at tag {e_label.Tag()} has invalid key: {exc}",
                    entry_tag=e_label.Tag(),
                ) from exc

            # Build TagPath
            try:
                tags = tuple(int(t) for t in data["tag_path"].split(":"))
                tag_path = TagPath(tags)
            except (ValueError, KeyError) as exc:
                raise CorruptStableIndexError(
                    f"Index entry at tag {e_label.Tag()} has invalid tag_path: {exc}",
                    entry_tag=e_label.Tag(),
                ) from exc

            # Validate key uniqueness (v5.0 §5.5 rule 3)
            key_str = str(key)
            if key_str in seen_keys:
                raise CorruptStableIndexError(
                    f"Duplicate key in index: {key_str}",
                    duplicate_key=key_str,
                )
            seen_keys.add(key_str)

            # Validate path uniqueness (v5.0 §5.5 rule 4)
            if tag_path in seen_paths:
                raise CorruptStableIndexError(
                    f"Duplicate tag_path in index: {tag_path}",
                    duplicate_path=str(tag_path),
                )
            seen_paths.add(tag_path)

            # Validate label existence (v5.0 §5.5 rule 5)
            resolved = tag_path.resolve(main_label)
            if resolved.IsNull():
                raise CorruptStableIndexError(
                    f"Index entry tag_path does not resolve to existing label: {tag_path}",
                    dangling_path=str(tag_path),
                )

            # Track max tag per kind for counter validation
            kind = key.object_kind
            # Extract the object-level tag (last tag in path)
            obj_tag = tags[-1]
            prev = max_tags.get(kind, 0)
            if obj_tag > prev:
                max_tags[kind] = obj_tag

            entry = IndexEntry(
                key=key,
                tag_path=tag_path,
                created_revision=data["created_revision"],
                retired_revision=data.get("retired_revision"),
                schema_version=data.get("schema_version", "gcad_topo_v3@ocaf_v1"),
            )
            self._by_key[key_str] = entry
            self._by_path[tag_path] = entry

        # ── Validate counters (v5.0 §5.5 rules 6-7) ──
        for kind in INDEX_COUNTER_KINDS:
            max_tag = max_tags.get(kind)
            if max_tag is not None:
                loaded_counter = counters_loaded.get(kind)
                if loaded_counter is not None:
                    # Counter must be > max tag (rule 6)
                    if loaded_counter <= max_tag:
                        raise CorruptStableIndexError(
                            f"Counter {kind}_next={loaded_counter} <= max occupied "
                            f"tag {max_tag}",
                            kind=kind,
                            counter=loaded_counter,
                            max_tag=max_tag,
                        )
                else:
                    # Counter missing → rebuild from entries (rule 7)
                    self._next_tags[kind] = max_tag + 1

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        self._by_key.clear()
        self._by_path.clear()
        self._next_tags = {
            kind: DYNAMIC_TAG_START for kind in INDEX_COUNTER_KINDS
        }
        self._next_tags["revision"] = 1

    @property
    def entry_count(self) -> int:
        return len(self._by_key)

    @property
    def active_count(self) -> int:
        return sum(1 for e in self._by_key.values() if e.retired_revision is None)

    def entries(self) -> list[IndexEntry]:
        return list(self._by_key.values())
