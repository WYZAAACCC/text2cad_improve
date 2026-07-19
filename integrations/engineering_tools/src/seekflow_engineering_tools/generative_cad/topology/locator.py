"""RuntimeTopoLocator — structured OCCT subshape locator.

Stored in TopologyEntityRecord.current_locator, provides everything needed
to retrieve the actual TopoDS subshape from the owner body at resolution time.

Design:
  - Uses OCCT TopTools_IndexedMapOfShape position as the authoritative
    locator key (NOT Python list enumeration order).
  - Carries OCCT shape hash, orientation, and location hash for verification.
  - owner_shape_content_hash enables cache-busting — when the owner body
    changes, all locators become stale.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RuntimeTopoLocator(BaseModel):
    """Structured OCCT subshape locator — stored in TopologyEntityRecord.current_locator.

    Contains everything needed to retrieve the actual subshape from the owner
    body at resolution time, plus hash-based cache-busting fields.

    The indexed_map_position is the AUTHORITATIVE locator key — it points to
    the position in a TopTools_IndexedMapOfShape built from the owner body.
    This is stable for the same body shape regardless of how faces are
    enumerated by CadQuery's Python-level .faces() iterator.
    """

    model_config = ConfigDict(extra="forbid")

    # Owner identity
    owner_body_handle_id: str = Field(
        description="Handle ID of the owner body in ObjectStore",
    )
    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"] = Field(
        description="Type of this topology entity",
    )

    # ── OCCT IndexedMap position (authoritative locator key) ──
    indexed_map_position: int = Field(
        description="1-based position in TopTools_IndexedMapOfShape for the owner body",
        ge=1,
    )

    # ── Shape identity hashes ──
    occt_shape_hash: int = Field(
        description="HashCode of the subshape itself (TopoDS_Shape.HashCode(INT_MAX))",
    )

    # ── Orientation ──
    orientation: Literal["forward", "reversed", "internal", "external"] = Field(
        default="forward",
        description="Orientation of this subshape relative to owner body",
    )

    # ── Location hash ──
    location_hash: int | None = Field(
        default=None,
        description="HashCode of the subshape's TopLoc_Location (for round-trip verification)",
    )

    # ── Cache-busting ──
    owner_shape_content_hash: str | None = Field(
        default=None,
        description="Content hash of the full owner body shape tree. "
        "When this changes, the locator is stale and must be rebuilt.",
    )

    # ── V3: Revision-based staleness ──
    owner_body_revision_id: str | None = Field(
        default=None,
        description="V3: ObjectStore revision token. When the owner body is "
        "replaced (via ObjectStore.replace()), the revision increments, making "
        "all old locators stale. This is the primary staleness mechanism — "
        "content hash is a secondary check.",
    )
    map_algorithm: Literal["occt_indexed_map_v1"] = Field(
        default="occt_indexed_map_v1",
        description="Algorithm used to build the IndexedMap. Reserved for "
        "future algorithm changes.",
    )

    # ── Convenience ──

    def to_display_key(self) -> str:
        """Human-readable display key for debugging."""
        return (
            f"{self.entity_type}:{self.owner_body_handle_id}:"
            f"#{self.indexed_map_position}"
        )

    def is_stale(self, current_content_hash: str) -> bool:
        """[DEPRECATED] Check if this locator is stale via content hash.

        Use is_stale_v3() for revision-based staleness detection.
        """
        if self.owner_shape_content_hash is None:
            return False
        return self.owner_shape_content_hash != current_content_hash

    def is_stale_v3(self, current_revision: str | None) -> bool:
        """V3 strict staleness: revision mismatch → stale.

        If owner_body_revision_id is set, compare to current_revision.
        If not set (legacy locator), fall back to content hash.
        """
        if self.owner_body_revision_id is not None and current_revision is not None:
            return self.owner_body_revision_id != current_revision
        return False  # legacy: no revision to compare
