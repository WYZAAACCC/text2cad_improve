"""ArchetypeRegistry — matcher-based mechanical layout templates.

Archetypes match MechanicalObjectGraphDraft by component roles/names,
and inject default SpatialRelationDraft entries with SourceKind=ARCHETYPE_DEFAULT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft,
    SpatialRelationDraft,
)


@dataclass(frozen=True)
class ArchetypeSpec:
    """A single archetype definition.

    matcher: predicate receiving the object graph; returns True if this archetype applies.
    relations: generator that produces default SpatialRelationDraft list.
    applicable_modes: AUTO modes this archetype is valid for.
    """
    archetype_id: str
    description: str
    matcher: Callable[[MechanicalObjectGraphDraft], bool]
    relations: Callable[[MechanicalObjectGraphDraft], list[SpatialRelationDraft]]
    applicable_modes: tuple[str, ...] = ("auto_mechanical", "auto_complex_verified")


class ArchetypeRegistry:
    """In-memory registry of mechanical archetypes."""

    def __init__(self):
        self._archetypes: dict[str, ArchetypeSpec] = {}

    def register(self, spec: ArchetypeSpec) -> None:
        if spec.archetype_id in self._archetypes:
            raise ValueError(f"duplicate archetype: {spec.archetype_id}")
        self._archetypes[spec.archetype_id] = spec

    def match(self, graph: MechanicalObjectGraphDraft) -> list[ArchetypeSpec]:
        """Return all archetypes whose matcher accepts this graph."""
        return [a for a in self._archetypes.values() if a.matcher(graph)]

    def list_ids(self) -> list[str]:
        return sorted(self._archetypes.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# Default registry (4 initial archetypes)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_default_archetypes() -> ArchetypeRegistry:
    from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes import (
        pillar_support,
        axial_coupling,
        bearing_on_base,
        flanged_connection,
    )
    reg = ArchetypeRegistry()
    for spec in [
        pillar_support.SPEC,
        axial_coupling.SPEC,
        bearing_on_base.SPEC,
        flanged_connection.SPEC,
    ]:
        reg.register(spec)
    return reg


_default_archetypes: ArchetypeRegistry | None = None


def default_archetypes() -> ArchetypeRegistry:
    global _default_archetypes
    if _default_archetypes is None:
        _default_archetypes = _build_default_archetypes()
    return _default_archetypes
