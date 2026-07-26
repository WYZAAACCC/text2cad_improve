"""StableLabelIndex — persistent object_id → TagPath mapping.

Implements §4.4 of the v3.0 implementation guide:

  - Object IDs are resolved to fixed TagPaths within the OCAF label tree.
  - First-allocation uses a monotonic counter per container.
  - Deleted tags are never reused.
  - The OCAF document (TagPath: 100/7 StableIdIndex) is the authoritative store.
  - In-process cache is a mirror, rebuilt from OCAF on open.

Key rules:
  - Python hash() is NEVER used for tag generation.
  - Same object_id MUST resolve to the same TagPath.
  - object_id conflict (same ID, different kind) → fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
    DYNAMIC_TAG_START,
    TAGPATH_STABLE_ID_INDEX,
    TagPath,
)


@dataclass(frozen=True)
class IndexEntry:
    """A single record in the StableLabelIndex."""

    object_kind: str        # "component" | "feature" | "selection"
    object_id: str          # stable business identifier
    tag_path: TagPath       # resolved path in the OCAF label tree
    created_revision: int   # revision number when first allocated
    retired_revision: int | None = None  # revision when deleted, or None
    schema_version: str = "gcad_topo_v3@ocaf_v1"


@dataclass
class StableLabelIndex:
    """In-process mirror of the persistent object_id → TagPath index.

    The authoritative source is the OCAF document at TAGPATH_STABLE_ID_INDEX.
    This cache is rebuilt from OCAF when a document is opened.

    Allocates new tags from a monotonic counter per object_kind, starting at
    DYNAMIC_TAG_START.  Tags are NEVER reused, even after retirement.
    """

    _by_id: dict[str, IndexEntry] = field(default_factory=dict)
    _by_path: dict[TagPath, IndexEntry] = field(default_factory=dict)
    _next_tags: dict[str, int] = field(default_factory=lambda: {
        "component": DYNAMIC_TAG_START,
        "feature": DYNAMIC_TAG_START,
        "selection": DYNAMIC_TAG_START,
    })

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def resolve_id(self, object_id: str) -> TagPath | None:
        """Return the TagPath for a given object_id, or None."""
        entry = self._by_id.get(object_id)
        if entry is None:
            return None
        return entry.tag_path

    def resolve_path(self, path: TagPath) -> IndexEntry | None:
        """Return the IndexEntry for a TagPath, or None."""
        return self._by_path.get(path)

    def is_allocated(self, object_id: str) -> bool:
        """Check whether an object_id has already been allocated."""
        return object_id in self._by_id

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

    def allocate(self, object_kind: str, object_id: str, revision: int) -> IndexEntry:
        """Allocate a new TagPath for a given object_id.

        Returns the new IndexEntry.

        Raises StableLabelConflictError if the object_id is already allocated
        with a different object_kind.
        """
        from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
            StableLabelConflictError,
        )

        # Collision check
        existing = self._by_id.get(object_id)
        if existing is not None:
            if existing.object_kind != object_kind:
                raise StableLabelConflictError(
                    f"object_id {object_id!r} already allocated as "
                    f"{existing.object_kind!r}, cannot re-allocate as {object_kind!r}",
                    object_id=object_id,
                    existing_kind=existing.object_kind,
                    requested_kind=object_kind,
                )
            # Same kind, same ID → idempotent: return existing
            return existing

        # Allocate next tag
        tag = self._next_tags[object_kind]
        self._next_tags[object_kind] = tag + 1

        # Build TagPath based on kind
        from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
            make_component_tagpath,
            make_feature_tagpath,
            make_selection_tagpath,
        )

        if object_kind == "component":
            tag_path = make_component_tagpath(tag)
        elif object_kind == "feature":
            # Feature allocation requires a parent component_tag.
            # This is set by allocate_feature() below.
            raise ValueError(
                "Use allocate_feature(component_tag, object_id, revision) "
                "for feature allocation"
            )
        elif object_kind == "selection":
            tag_path = make_selection_tagpath(tag)
        else:
            raise ValueError(f"Unknown object_kind: {object_kind!r}")

        entry = IndexEntry(
            object_kind=object_kind,
            object_id=object_id,
            tag_path=tag_path,
            created_revision=revision,
        )
        self._by_id[object_id] = entry
        self._by_path[tag_path] = entry
        return entry

    def allocate_feature(
        self, component_tag: int, object_id: str, revision: int
    ) -> IndexEntry:
        """Allocate a TagPath for a feature within a specific component."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
            StableLabelConflictError,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
            make_feature_tagpath,
        )

        existing = self._by_id.get(object_id)
        if existing is not None:
            if existing.object_kind != "feature":
                raise StableLabelConflictError(
                    f"object_id {object_id!r} already allocated as "
                    f"{existing.object_kind!r}, cannot re-allocate as feature",
                    object_id=object_id,
                    existing_kind=existing.object_kind,
                    requested_kind="feature",
                )
            return existing

        tag = self._next_tags["feature"]
        self._next_tags["feature"] = tag + 1
        tag_path = make_feature_tagpath(component_tag, tag)

        entry = IndexEntry(
            object_kind="feature",
            object_id=object_id,
            tag_path=tag_path,
            created_revision=revision,
        )
        self._by_id[object_id] = entry
        self._by_path[tag_path] = entry
        return entry

    # ------------------------------------------------------------------
    # Retirement
    # ------------------------------------------------------------------

    def retire(self, object_id: str, revision: int) -> None:
        """Mark an object_id as retired (deleted). Tag is never reused."""
        entry = self._by_id.get(object_id)
        if entry is None:
            return
        # Replace with retired version
        retired = IndexEntry(
            object_kind=entry.object_kind,
            object_id=entry.object_id,
            tag_path=entry.tag_path,
            created_revision=entry.created_revision,
            retired_revision=revision,
            schema_version=entry.schema_version,
        )
        self._by_id[object_id] = retired
        self._by_path[entry.tag_path] = retired

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Drop all in-process cache entries."""
        self._by_id.clear()
        self._by_path.clear()
        self._next_tags = {
            "component": DYNAMIC_TAG_START,
            "feature": DYNAMIC_TAG_START,
            "selection": DYNAMIC_TAG_START,
        }

    @property
    def entry_count(self) -> int:
        return len(self._by_id)

    @property
    def active_count(self) -> int:
        return sum(1 for e in self._by_id.values() if e.retired_revision is None)

    def entries(self) -> list[IndexEntry]:
        return list(self._by_id.values())
