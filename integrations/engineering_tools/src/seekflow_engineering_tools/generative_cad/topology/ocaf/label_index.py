"""StableLabelIndex — persistent object_id -> TagPath mapping with OCAF storage.

v4.0 P0-02: Composite keys (object_kind + namespace + object_id), OCAF persistence
at Tag 100/7, and cross-process index recovery on open().

Tag 100/7 schema:
  100:7 StableIdIndex
  ├── 1 Counters
  │   ├── 1 component_next
  │   ├── 2 feature_next
  │   ├── 3 selection_next
  │   └── 4 revision_next
  └── 2 Entries
      └── <entry_tag> (dynamic, starting at 1001)
          ├── 1 key (TDataStd_AsciiString: JSON of StableObjectKey)
          ├── 2 tag_path
          ├── 3 created_revision
          ├── 4 retired_revision
          └── 5 schema_version
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import StableObjectKey
from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
    DYNAMIC_TAG_START,
    TAGPATH_STABLE_ID_INDEX,
    TagPath,
    make_component_tagpath,
    make_feature_tagpath,
    make_selection_tagpath,
)


@dataclass(frozen=True)
class IndexEntry:
    """A single record in the StableLabelIndex."""
    key: StableObjectKey
    tag_path: TagPath
    created_revision: int
    retired_revision: int | None = None
    schema_version: str = "gcad_topo_v3@ocaf_v1"


@dataclass
class StableLabelIndex:
    """Persistent object_id -> TagPath mapping with OCAF storage.

    Uses composite StableObjectKey (kind + namespace + id) to prevent
    collisions between components/features/selections with the same name.

    On save: writes index to Tag 100/7 in the OCAF document.
    On open: rebuilds index from OCAF.
    """

    _by_key: dict[str, IndexEntry] = field(default_factory=dict)
    _by_path: dict[TagPath, IndexEntry] = field(default_factory=dict)
    _next_tags: dict[str, int] = field(default_factory=lambda: {
        "component": DYNAMIC_TAG_START,
        "feature": DYNAMIC_TAG_START,
        "selection": DYNAMIC_TAG_START,
        "revision": 1,
    })

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def resolve_key(self, object_kind: str, namespace: str, object_id: str) -> TagPath | None:
        key_str = str(StableObjectKey(object_kind, namespace, object_id))
        entry = self._by_key.get(key_str)
        return entry.tag_path if entry else None

    def resolve_path(self, path: TagPath) -> IndexEntry | None:
        return self._by_path.get(path)

    def is_allocated(self, object_kind: str, namespace: str, object_id: str) -> bool:
        key_str = str(StableObjectKey(object_kind, namespace, object_id))
        return key_str in self._by_key

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

    def allocate(
        self, object_kind: str, namespace: str, object_id: str, revision: int
    ) -> IndexEntry:
        key = StableObjectKey(object_kind, namespace, object_id)
        key_str = str(key)

        existing = self._by_key.get(key_str)
        if existing is not None:
            if existing.key.object_kind != object_kind:
                from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
                    StableLabelConflictError,
                )
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
        else:
            raise ValueError(f"Unknown object_kind: {object_kind!r}")

        entry = IndexEntry(key=key, tag_path=tag_path, created_revision=revision)
        self._by_key[key_str] = entry
        self._by_path[tag_path] = entry
        return entry

    def allocate_feature(
        self, component_tag: int, feature_namespace: str, object_id: str, revision: int
    ) -> IndexEntry:
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

    def retire(self, object_kind: str, namespace: str, object_id: str, revision: int) -> None:
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
    # OCAF persistence
    # ------------------------------------------------------------------

    def save_to_ocaf(self, main_label) -> None:
        """Write index counters and entries to Tag 100/7."""
        from OCP.TDataStd import TDataStd_Integer, TDataStd_AsciiString
        from OCP.TCollection import TCollection_AsciiString as TCAscii

        idx_root = TAGPATH_STABLE_ID_INDEX.resolve_or_create(main_label)

        # Counters
        counters = idx_root.FindChild(1, True)
        for i, kind in enumerate(["component", "feature", "selection", "revision"], 1):
            val = self._next_tags.get(kind, DYNAMIC_TAG_START)
            TDataStd_Integer.Set_s(counters.FindChild(i, True), val)

        # Entries
        entries_label = idx_root.FindChild(2, True)
        entry_tag = 1001
        for key_str, entry in self._by_key.items():
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
        """Rebuild index from Tag 100/7 in the OCAF document."""
        from OCP.TDataStd import TDataStd_Integer, TDataStd_AsciiString
        from OCP.TCollection import TCollection_AsciiString as TCAscii
        from OCP.TDF import TDF_ChildIterator

        self._by_key.clear()
        self._by_path.clear()

        idx_root = TAGPATH_STABLE_ID_INDEX.resolve(main_label)
        if idx_root.IsNull():
            return  # No index yet

        # Load counters
        counters = idx_root.FindChild(1, False)
        if not counters.IsNull():
            for i, kind in enumerate(["component", "feature", "selection", "revision"], 1):
                c = counters.FindChild(i, False)
                if not c.IsNull():
                    try:
                        self._next_tags[kind] = TDataStd_Integer.Get_s(c)
                    except Exception:
                        pass

        # Load entries
        entries_label = idx_root.FindChild(2, False)
        if not entries_label.IsNull():
            it = TDF_ChildIterator(entries_label)
            while it.More():
                e_label = it.Value()
                it.Next()
                try:
                    s = TDataStd_AsciiString.Get_s(e_label)
                    data = json.loads(TCAscii(s).ToCString())
                    key = StableObjectKey(
                        object_kind=data["object_kind"],
                        namespace=data["namespace"],
                        object_id=data["object_id"],
                    )
                    tags = tuple(int(t) for t in data["tag_path"].split(":"))
                    tag_path = TagPath(tags)
                    entry = IndexEntry(
                        key=key,
                        tag_path=tag_path,
                        created_revision=data.get("created_revision", 1),
                        retired_revision=data.get("retired_revision"),
                        schema_version=data.get("schema_version", "gcad_topo_v3@ocaf_v1"),
                    )
                    self._by_key[str(key)] = entry
                    self._by_path[tag_path] = entry
                except Exception:
                    continue

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        self._by_key.clear()
        self._by_path.clear()
        self._next_tags = {
            "component": DYNAMIC_TAG_START,
            "feature": DYNAMIC_TAG_START,
            "selection": DYNAMIC_TAG_START,
            "revision": 1,
        }

    @property
    def entry_count(self) -> int:
        return len(self._by_key)

    @property
    def active_count(self) -> int:
        return sum(1 for e in self._by_key.values() if e.retired_revision is None)

    def entries(self) -> list[IndexEntry]:
        return list(self._by_key.values())
