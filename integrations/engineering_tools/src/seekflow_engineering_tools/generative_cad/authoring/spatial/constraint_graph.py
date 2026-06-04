"""ConstraintGraphBuilder — relation drafts → SpatialConstraintGraph (symbolic constraints).

Converts LLM-produced SpatialRelationDraft entries into PlacementConstraint
objects with SymbolicDimensionRef bindings. No numeric coordinates computed.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    MechanicalObjectGraphDraft,
    SpatialConstraintGraph,
    SpatialRelationDraft,
    PlacementConstraint,
    SymbolicDimensionRef,
    ComponentRole,
)


def build_constraint_graph(
    object_graph: MechanicalObjectGraphDraft,
) -> SpatialConstraintGraph:
    """Convert candidate_relations into symbolic constraint graph.

    Mapping rules:
    - "above" + direction="+Z" → stack: lower.zmax + 0 = upper.zmin
    - "below" → stack (reversed)
    - "coaxial" → align_axis (default Z)
    - "symmetric_pair" → symmetric
    - "face_contact" → stack with offset=0
    - "supports" → stack with offset=0
    - "attached_to" → contact
    """
    constraints: list[PlacementConstraint] = []
    component_map = {c.component_id: c for c in object_graph.components}

    for rel in object_graph.candidate_relations:
        pc = _convert_relation(rel, component_map)
        if pc is not None:
            constraints.append(pc)

    return SpatialConstraintGraph(
        components=object_graph.components,
        local_frames=object_graph.local_frames,
        constraints=constraints,
        assumptions=list(object_graph.assumptions),
    )


def _convert_relation(
    rel: SpatialRelationDraft,
    component_map: dict[str, ComponentRole],
) -> PlacementConstraint | None:
    """Convert a single relation draft to a symbolic PlacementConstraint."""

    if len(rel.entities) < 2:
        return None

    a, b = rel.entities[0], rel.entities[1]

    if rel.type == "above":
        return PlacementConstraint(
            constraint_id=f"c_{rel.relation_id}",
            type="stack",
            entities=[b, a],  # lower, upper
            bindings={
                "lower_zmax": SymbolicDimensionRef(component_id=b, axis="Z", edge="max"),
                "upper_zmin": SymbolicDimensionRef(component_id=a, axis="Z", edge="min"),
            },
            offset_mm=rel.value_mm or 0.0,
            axis="Z",
            source=rel.source,
        )

    if rel.type == "below":
        return PlacementConstraint(
            constraint_id=f"c_{rel.relation_id}",
            type="stack",
            entities=[a, b],
            bindings={
                "lower_zmax": SymbolicDimensionRef(component_id=a, axis="Z", edge="max"),
                "upper_zmin": SymbolicDimensionRef(component_id=b, axis="Z", edge="min"),
            },
            offset_mm=rel.value_mm or 0.0,
            axis="Z",
            source=rel.source,
        )

    if rel.type == "coaxial":
        axis = "Z"
        if rel.direction is not None:
            axis = rel.direction.lstrip("+-")
        return PlacementConstraint(
            constraint_id=f"c_{rel.relation_id}",
            type="align_axis",
            entities=[a, b],
            axis=axis,
            source=rel.source,
        )

    if rel.type == "symmetric_pair":
        return PlacementConstraint(
            constraint_id=f"c_{rel.relation_id}",
            type="symmetric",
            entities=[a, b],
            spacing_mm=rel.value_mm,
            source=rel.source,
        )

    if rel.type == "face_contact":
        return PlacementConstraint(
            constraint_id=f"c_{rel.relation_id}",
            type="stack",
            entities=[a, b],
            bindings={
                "a_face": SymbolicDimensionRef(component_id=a, axis="Z", edge="max"),
                "b_face": SymbolicDimensionRef(component_id=b, axis="Z", edge="min"),
            },
            offset_mm=0.0,
            axis="Z",
            source=rel.source,
        )

    if rel.type == "supports":
        return PlacementConstraint(
            constraint_id=f"c_{rel.relation_id}",
            type="stack",
            entities=[a, b],
            bindings={
                "support_zmax": SymbolicDimensionRef(component_id=a, axis="Z", edge="max"),
                "supported_zmin": SymbolicDimensionRef(component_id=b, axis="Z", edge="min"),
            },
            offset_mm=0.0,
            axis="Z",
            source=rel.source,
        )

    if rel.type == "attached_to":
        return PlacementConstraint(
            constraint_id=f"c_{rel.relation_id}",
            type="contact",
            entities=[a, b],
            tolerance_mm=1.0,
            source=rel.source,
        )

    return None
