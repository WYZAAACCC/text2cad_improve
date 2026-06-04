"""Flanged connection archetype — face-contact + coaxial flange pairs."""

from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes.registry import ArchetypeSpec
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft, SpatialRelationDraft, Confidence,
)

SPEC = ArchetypeSpec(
    archetype_id="flanged_connection",
    description="Flanged pipe/ring connection: face-contact, coaxial alignment",
    matcher=lambda g: (
        len(g.components) >= 2
        and sum(1 for c in g.components
                if "flange" in c.role.lower() or "flange" in c.component_id.lower()) >= 2
    ),
    relations=lambda g: _flanged_connection_relations(g),
)


def _flanged_connection_relations(g: MechanicalObjectGraphDraft) -> list[SpatialRelationDraft]:
    flanges = [
        c for c in g.components
        if "flange" in c.role.lower() or "flange" in c.component_id.lower()
    ]

    relations: list[SpatialRelationDraft] = []
    rid = 0

    if len(flanges) >= 2:
        # Coaxial alignment
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_fc_{rid}",
            type="coaxial",
            entities=[flanges[0].component_id, flanges[1].component_id],
            source="archetype_default",
            confidence=Confidence(value=0.80, reason="flanged_connection: coaxial flanges"),
            rationale="flanged_connection archetype: coaxial alignment",
        ))
        # Face contact
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_fc_{rid}",
            type="face_contact",
            entities=[flanges[0].component_id, flanges[1].component_id],
            direction="+Z",
            source="archetype_default",
            confidence=Confidence(value=0.75, reason="flanged_connection: face-to-face contact"),
            rationale="flanged_connection archetype: flange face contact",
        ))

    # Pipe/flange attachment: any pipe-like component contacts its flange
    pipes = [
        c for c in g.components
        if "pipe" in c.role.lower() or "pipe" in c.component_id.lower()
        or "tube" in c.role.lower() or "tube" in c.component_id.lower()
    ]
    for pipe in pipes:
        for flange in flanges:
            rid += 1
            relations.append(SpatialRelationDraft(
                relation_id=f"archetype_fc_{rid}",
                type="attached_to",
                entities=[pipe.component_id, flange.component_id],
                source="archetype_default",
                confidence=Confidence(value=0.65, reason="flanged_connection: pipe attaches to flange"),
                rationale="flanged_connection archetype: pipe-flange attachment",
            ))

    for rel in relations:
        if rel.rationale not in g.assumptions:
            g.assumptions.append(f"[archetype:flanged_connection] {rel.rationale}")

    return relations
