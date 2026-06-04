"""Placement constraint injection into FeatureSequence generation.

Converts SpatialConstraintGraph into:
1. SPATIAL CONTRACT text for FeatureSequence user prompt
2. place_component NodePlanDraft entries (PLACEHOLDER coords, solver fills later)
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.authoring.schemas import (
    FeatureSequenceDraft,
    NodePlanDraft,
    ComponentDraft,
)
from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    SpatialConstraintGraph,
)


def inject_placements_into_feature_sequence(
    feature_sequence: FeatureSequenceDraft,
    spatial_graph: SpatialConstraintGraph,
) -> FeatureSequenceDraft:
    """Inject placement nodes for multi-component assemblies.

    Rules:
    1. Multi-component assemblies need __assembly__ component
    2. Each leaf component root body gets a place_component before boolean_union
    3. place_component uses PLACEHOLDER coords (solver fills at runtime)
    4. boolean_union consumes placed solids (via raw_assembler scope)
    """
    components = list(feature_sequence.components)
    nodes = list(feature_sequence.node_sequence)

    non_assembly = [c for c in components if c.component_id != "__assembly__"]
    if len(non_assembly) <= 1:
        return feature_sequence

    # Ensure __assembly__ exists
    assembly = next((c for c in components if c.component_id == "__assembly__"), None)
    if assembly is None:
        assembly = ComponentDraft(
            component_id="__assembly__",
            owner_dialect="composition",
            kind_hint="assembly",
        )
        components.append(assembly)

    existing_ids = {n.node_id for n in nodes}
    placement_nodes: list[NodePlanDraft] = []

    for comp in non_assembly:
        place_id = f"place_{comp.component_id}"
        if place_id not in existing_ids:
            placement_nodes.append(NodePlanDraft(
                node_id=place_id,
                component_id="__assembly__",
                dialect="composition",
                op="place_component",
                op_version="1.0.0",
                phase="transform",
                purpose=f"Place {comp.component_id} root body at solver-derived coordinates",
                expected_input_source=comp.component_id,
                expected_output_name="body",
            ))

    # Insert before boolean_union
    assembly_nodes = [n for n in nodes if n.component_id == "__assembly__"]
    union_indices = [
        i for i, n in enumerate(assembly_nodes)
        if n.op == "boolean_union"
    ]
    insert_index = union_indices[0] if union_indices else len(nodes)
    for pn in reversed(placement_nodes):
        nodes.insert(insert_index, pn)

    return FeatureSequenceDraft(
        components=components,
        node_sequence=nodes,
        assumptions=feature_sequence.assumptions,
        unsupported_details=feature_sequence.unsupported_details,
    )


def build_spatial_context_for_prompt(
    spatial_graph: SpatialConstraintGraph,
) -> str:
    """Build SPATIAL CONTRACT text for FeatureSequence user prompt.

    Returns compact markdown describing symbolic constraints.
    """
    if not spatial_graph.constraints:
        return ""

    lines = [
        "SPATIAL CONTRACT (symbolic constraints — numeric values solved at runtime):",
        "",
    ]
    for c in spatial_graph.constraints:
        entities_str = ", ".join(c.entities)
        lines.append(f"- [{c.constraint_id}] {c.type}({entities_str})")
        if c.bindings:
            for k, v in c.bindings.items():
                lines.append(f"    {k} = ${v.component_id}.{v.axis}_{v.edge}")
        if c.offset_mm != 0.0:
            lines.append(f"    offset={c.offset_mm}mm")
        lines.append(f"    source={c.source}")

    if spatial_graph.assumptions:
        lines.append("")
        lines.append("ASSUMPTIONS:")
        for a in spatial_graph.assumptions[:20]:
            lines.append(f"- {a}")

    return "\n".join(lines)
