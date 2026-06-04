"""Axial coupling archetype — coaxial hub-spider-hub chain."""

from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes.registry import ArchetypeSpec
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft, SpatialRelationDraft, Confidence,
)

SPEC = ArchetypeSpec(
    archetype_id="axial_coupling",
    description="Axial coupling: hub-spider-hub coaxial chain",
    matcher=lambda g: (
        len(g.components) >= 3
        and any("hub" in c.role.lower() or "hub" in c.component_id.lower() for c in g.components)
        and any("spider" in c.role.lower() or "spider" in c.component_id.lower() for c in g.components)
    ),
    relations=lambda g: _axial_coupling_relations(g),
)


def _axial_coupling_relations(g: MechanicalObjectGraphDraft) -> list[SpatialRelationDraft]:
    hubs = [c for c in g.components if "hub" in c.role.lower() or "hub" in c.component_id.lower()]
    spiders = [c for c in g.components if "spider" in c.role.lower() or "spider" in c.component_id.lower()]

    relations: list[SpatialRelationDraft] = []
    rid = 0
    all_axial = hubs + spiders

    # Coaxial constraints
    if len(all_axial) >= 2:
        for i in range(len(all_axial) - 1):
            rid += 1
            relations.append(SpatialRelationDraft(
                relation_id=f"archetype_ac_{rid}",
                type="coaxial",
                entities=[all_axial[i].component_id, all_axial[i + 1].component_id],
                source="archetype_default",
                confidence=Confidence(value=0.80, reason="axial_coupling: coaxial alignment"),
                rationale="axial_coupling archetype: coaxial alignment",
            ))

    # Face contact chain: hub_a → spider → hub_b
    if len(hubs) == 2 and len(spiders) == 1:
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_ac_{rid}",
            type="face_contact",
            entities=[hubs[0].component_id, spiders[0].component_id],
            direction="+Z",
            source="archetype_default",
            confidence=Confidence(value=0.70, reason="axial_coupling: hub_a contacts spider"),
            rationale="axial_coupling archetype: hub_a contacts spider",
        ))
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_ac_{rid}",
            type="face_contact",
            entities=[spiders[0].component_id, hubs[1].component_id],
            direction="+Z",
            source="archetype_default",
            confidence=Confidence(value=0.70, reason="axial_coupling: spider contacts hub_b"),
            rationale="axial_coupling archetype: spider contacts hub_b",
        ))

    for rel in relations:
        if rel.rationale not in g.assumptions:
            g.assumptions.append(f"[archetype:axial_coupling] {rel.rationale}")

    return relations
