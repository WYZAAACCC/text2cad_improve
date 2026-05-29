"""Adapter: convert v0.1 GenerativeCADSpec → v0.2 RawGcadDocument."""

from __future__ import annotations


def adapt_legacy_spec(legacy) -> "RawGcadDocument":
    from seekflow_engineering_tools.generative_cad.ir.raw import (
        RawGcadDocument, RawComponent, RawNode, RawValueDecl, RawValueRef,
        RawSelectedDialect, RawConstraints, RawSafety,
    )

    base_to_dialect = {"axisymmetric_base": "axisymmetric", "sketch_extrude_base": "sketch_extrude"}

    components = []
    nodes = []
    selected_dialects: dict[str, str] = {}

    for sb in legacy.selected_bases:
        did = base_to_dialect.get(sb.base_id, sb.base_id)
        # Legacy v0.1 spec uses dialect version from registry, not base_version
        selected_dialects[did] = "0.2.0"

    base_nodes: dict[str, list] = {}
    for node in legacy.feature_graph.nodes:
        base_nodes.setdefault(node.base_id, []).append(node)

    comp_idx = 0
    for base_id, group in base_nodes.items():
        did = base_to_dialect.get(base_id, base_id)
        comp_id = f"comp_{comp_idx}"; comp_idx += 1
        root_id = group[0].id if group else f"root_{comp_id}"
        components.append(RawComponent(id=comp_id, owner_dialect=did, root_node=root_id))

        for node in group:
            inputs = [RawValueRef(node=dep_id, output="body") for dep_id in node.depends_on]
            outputs = [RawValueDecl(name="body", type="solid")]
            if node.op == "revolve_profile":
                outputs.append(RawValueDecl(name="outer_frame", type="frame"))
            nodes.append(RawNode(
                id=node.id, component=comp_id, dialect=did,
                op=node.op, op_version="1.0.0", phase=node.phase,
                inputs=inputs, outputs=outputs,
                params=node.params,
                required=node.required,
                degradation_policy=node.degradation_policy,
            ))

    sc = legacy.system_validation_contract
    return RawGcadDocument(
        schema_version="g_cad_core_v0.2",
        document_id=f"legacy_{legacy.part_name}",
        part_name=legacy.part_name,
        selected_dialects=[RawSelectedDialect(dialect=k, version=v) for k, v in selected_dialects.items()],
        components=components,
        nodes=nodes,
        constraints=RawConstraints(
            require_step_file=sc.require_step_file,
            require_metadata_sidecar=sc.require_metadata_sidecar,
            require_closed_solid=sc.require_closed_solid,
            expected_body_count=sc.expected_body_count,
            max_runtime_seconds=sc.max_runtime_seconds,
        ),
        safety=RawSafety(**legacy.safety.model_dump()),
    )
