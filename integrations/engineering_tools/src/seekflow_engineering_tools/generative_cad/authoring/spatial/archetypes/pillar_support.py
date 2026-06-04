"""Pillar support archetype — top/bottom plates + symmetric pillars."""

from seekflow_engineering_tools.generative_cad.authoring.spatial.archetypes.registry import ArchetypeSpec
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft, SpatialRelationDraft, Confidence,
)

SPEC = ArchetypeSpec(
    archetype_id="pillar_support",
    description="Top/bottom plates with symmetric pillar supports (workbench, stand, frame)",
    matcher=lambda g: (
        len(g.components) >= 3
        and any("plate" in c.role.lower() or "plate" in c.component_id.lower() for c in g.components)
        and any(
            "pillar" in c.role.lower() or "pillar" in c.component_id.lower()
            or "column" in c.role.lower() or "column" in c.component_id.lower()
            for c in g.components
        )
    ),
    relations=lambda g: _pillar_support_relations(g),
)


def _pillar_support_relations(g: MechanicalObjectGraphDraft) -> list[SpatialRelationDraft]:
    plates = [
        c for c in g.components
        if "plate" in c.role.lower() or "plate" in c.component_id.lower()
    ]
    pillars = [
        c for c in g.components
        if "pillar" in c.role.lower() or "pillar" in c.component_id.lower()
        or "column" in c.role.lower() or "column" in c.component_id.lower()
    ]

    relations: list[SpatialRelationDraft] = []
    rid = 0

    # Top plate above pillars, pillars above bottom plate
    if len(plates) >= 2 and len(pillars) >= 1:
        top = next(
            (p for p in plates if "top" in p.component_id.lower() or "top" in p.role.lower()),
            plates[0],
        )
        bottom = next(
            (p for p in plates if "bottom" in p.component_id.lower() or "bottom" in p.role.lower()),
            plates[-1],
        )
        pref = pillars[0]

        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_ps_{rid}",
            type="above",
            entities=[top.component_id, pref.component_id],
            direction="+Z",
            source="archetype_default",
            confidence=Confidence(value=0.75, reason="pillar_support: top plate above pillars"),
            rationale="pillar_support archetype: top plate above pillars",
        ))
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_ps_{rid}",
            type="above",
            entities=[pref.component_id, bottom.component_id],
            direction="+Z",
            source="archetype_default",
            confidence=Confidence(value=0.75, reason="pillar_support: pillars above bottom plate"),
            rationale="pillar_support archetype: pillars above bottom plate",
        ))

    # Symmetric pillars
    if len(pillars) == 2:
        rid += 1
        relations.append(SpatialRelationDraft(
            relation_id=f"archetype_ps_{rid}",
            type="symmetric_pair",
            entities=[pillars[0].component_id, pillars[1].component_id],
            source="archetype_default",
            confidence=Confidence(value=0.70, reason="pillar_support: two pillars symmetric"),
            rationale="pillar_support archetype: symmetric pillar pair",
        ))
    elif len(pillars) == 4:
        for pair in [(0, 1), (2, 3)]:
            if pair[1] < len(pillars):
                rid += 1
                relations.append(SpatialRelationDraft(
                    relation_id=f"archetype_ps_{rid}",
                    type="symmetric_pair",
                    entities=[pillars[pair[0]].component_id, pillars[pair[1]].component_id],
                    source="archetype_default",
                    confidence=Confidence(value=0.70, reason="pillar_support: corner pillar symmetry"),
                    rationale="pillar_support archetype: corner pillar pair",
                ))

    for rel in relations:
        if rel.rationale not in g.assumptions:
            g.assumptions.append(f"[archetype:pillar_support] {rel.rationale}")

    return relations
