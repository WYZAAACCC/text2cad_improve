"""Bearing-on-base archetype — bearing pair mounted on a common base."""

from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes.registry import ArchetypeSpec
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft, SpatialRelationDraft, Confidence,
)

SPEC = ArchetypeSpec(
    archetype_id="bearing_on_base",
    description="Bearing pair mounted on a shared base plate",
    matcher=lambda g: (
        len(g.components) >= 3
        and any("bearing" in c.role.lower() or "bearing" in c.component_id.lower() for c in g.components)
        and any("base" in c.role.lower() or "base" in c.component_id.lower() for c in g.components)
    ),
    relations=lambda g: _bearing_on_base_relations(g),
)


def _bearing_on_base_relations(g: MechanicalObjectGraphDraft) -> list[SpatialRelationDraft]:
    bearings = [
        c for c in g.components
        if "bearing" in c.role.lower() or "bearing" in c.component_id.lower()
    ]
    bases = [
        c for c in g.components
        if "base" in c.role.lower() or "base" in c.component_id.lower()
    ]

    relations: list[SpatialRelationDraft] = []
    rid = 0

    # Bearings contact base top
    for bearing in bearings:
        for base in bases:
            rid += 1
            relations.append(SpatialRelationDraft(
                relation_id=f"archetype_bob_{rid}",
                type="above",
                entities=[bearing.component_id, base.component_id],
                direction="+Z",
                source="archetype_default",
                confidence=Confidence(value=0.75, reason="bearing_on_base: bearing above base"),
                rationale="bearing_on_base archetype: bearing on base top",
            ))

    # Multiple bearings share same shaft axis height (Y alignment)
    if len(bearings) >= 2:
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_bob_{rid}",
            type="coaxial",
            entities=[bearings[0].component_id, bearings[1].component_id],
            source="archetype_default",
            confidence=Confidence(value=0.70, reason="bearing_on_base: bearing pair coaxial"),
            rationale="bearing_on_base archetype: bearing pair coaxial",
        ))

    for rel in relations:
        if rel.rationale not in g.assumptions:
            g.assumptions.append(f"[archetype:bearing_on_base] {rel.rationale}")

    return relations
