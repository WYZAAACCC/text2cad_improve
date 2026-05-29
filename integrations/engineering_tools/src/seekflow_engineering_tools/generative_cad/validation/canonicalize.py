"""Canonicalization — convert RawGcadDocument to CanonicalGcadDocument.

Changes v0.2.1:
- typed_params stored as dict (JSON-safe, was Pydantic object)
- root_node REQUIRED, must exist and belong to component
- No implicit "solid" fallback for unresolved input types
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import (
    dialect_contract_hash,
    require_dialect,
)
from seekflow_engineering_tools.generative_cad.ir.canonical import (
    CanonicalComponent,
    CanonicalGcadDocument,
    CanonicalNode,
    CanonicalSelectedDialect,
    CanonicalValueDecl,
    CanonicalValueRef,
)
from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def canonicalize(raw: RawGcadDocument) -> tuple[CanonicalGcadDocument | None, ValidationReport]:
    issues = []

    resolved_dialects = []
    for sd in raw.selected_dialects:
        try:
            ch = dialect_contract_hash(sd.dialect)
        except KeyError:
            issues.append(ValidationReport.fail(
                "canonicalize", "canonicalize_dialect_missing",
                f"dialect {sd.dialect!r} not found during canonicalization",
            ).issues[0])
            continue
        resolved_dialects.append(CanonicalSelectedDialect(
            dialect=sd.dialect, version=sd.version, contract_hash=ch,
        ))

    if issues:
        return None, ValidationReport(ok=False, stage="canonicalize", issues=issues)

    node_map = {n.id: n for n in raw.nodes}

    # Components — root_node REQUIRED
    canonical_components = []
    for c in raw.components:
        rn_id = (c.root_node or "").strip()
        if not rn_id:
            issues.append(ValidationReport.fail(
                "canonicalize", "missing_root_node",
                f"component {c.id!r} must have explicit root_node",
                component_id=c.id,
            ).issues[0])
            continue
        if rn_id not in node_map:
            issues.append(ValidationReport.fail(
                "canonicalize", "root_node_not_found",
                f"component {c.id!r} root_node {rn_id!r} does not exist",
                component_id=c.id, node_id=rn_id,
            ).issues[0])
            continue
        rn = node_map[rn_id]
        if rn.component != c.id:
            issues.append(ValidationReport.fail(
                "canonicalize", "root_node_wrong_component",
                f"component {c.id!r} root_node {rn_id!r} belongs to {rn.component!r}",
                component_id=c.id, node_id=rn_id,
            ).issues[0])
            continue
        if not rn.outputs:
            issues.append(ValidationReport.fail(
                "canonicalize", "root_node_no_outputs",
                f"component {c.id!r} root_node {rn_id!r} has no outputs",
                component_id=c.id, node_id=rn_id,
            ).issues[0])
            continue
        canonical_components.append(CanonicalComponent(
            id=c.id, owner_dialect=c.owner_dialect,
            kind_hint=c.kind_hint, root_node=rn_id,
        ))

    if issues:
        return None, ValidationReport(ok=False, stage="canonicalize", issues=issues)

    # Nodes
    canonical_nodes = []
    for node in raw.nodes:
        dialect = require_dialect(node.dialect)
        version = node.op_version or dialect.default_op_version(node.op)
        op_spec = dialect.get_op_spec(node.op, version)

        # typed_params as dict (JSON-safe)
        try:
            typed_params_obj = op_spec.validate_params(node.params)
            typed_params = typed_params_obj.model_dump()
        except Exception as exc:
            issues.append(ValidationReport.fail(
                "canonicalize", "canonicalize_params_validation",
                f"node {node.id!r} params failed: {exc}",
                node_id=node.id,
            ).issues[0])
            continue

        # Resolve input types — no implicit fallback
        resolved_inputs = []
        for inp in node.inputs:
            rt = _resolve_input_type(inp, node_map, issues, node.id)
            if rt is None:
                continue
            resolved_inputs.append(CanonicalValueRef(
                producer_node=inp.node, producer_component=inp.component,
                output=inp.output, resolved_type=rt,
            ))

        resolved_outputs = []
        for decl in node.outputs:
            resolved_outputs.append(CanonicalValueDecl(
                name=decl.name, type=decl.type,
                value_id=f"{decl.type}:{node.component}:{node.id}:{decl.name}",
            ))

        canonical_nodes.append(CanonicalNode(
            id=node.id, component=node.component, dialect=node.dialect,
            op=node.op, op_version=version, phase=node.phase,
            inputs=resolved_inputs, outputs=resolved_outputs,
            params=node.params, typed_params=typed_params,
            required=node.required, degradation_policy=node.degradation_policy,
            operation_effects=op_spec.effects, postconditions=op_spec.postconditions,
        ))

    if issues:
        return None, ValidationReport(ok=False, stage="canonicalize", issues=issues)

    raw_hash = stable_hash(raw.model_dump())
    nodes_for_hash = [
        {"id": n.id, "component": n.component, "dialect": n.dialect,
         "op": n.op, "op_version": n.op_version, "phase": n.phase,
         "inputs": [i.model_dump() for i in n.inputs],
         "outputs": [o.model_dump() for o in n.outputs],
         "params": n.params}
        for n in canonical_nodes
    ]
    cgh = stable_hash(nodes_for_hash)

    canonical = CanonicalGcadDocument(
        document_id=raw.document_id, part_name=raw.part_name,
        units=raw.units, trust_level=raw.trust_level,
        selected_dialects=resolved_dialects,
        components=canonical_components, nodes=canonical_nodes,
        constraints=raw.constraints, safety=raw.safety,
        canonical_graph_hash=cgh, raw_graph_hash=raw_hash,
    )
    return canonical, ValidationReport.ok_report("canonicalize")


def _resolve_input_type(inp, node_map, issues, consumer_id):
    if inp.node is not None:
        producer = node_map.get(inp.node)
        if producer is None:
            issues.append(ValidationReport.fail(
                "canonicalize", "input_producer_not_found",
                f"node {consumer_id!r} input refs unknown producer {inp.node!r}",
                node_id=consumer_id,
            ).issues[0])
            return None
        for o in producer.outputs:
            if o.name == inp.output:
                return o.type
        issues.append(ValidationReport.fail(
            "canonicalize", "input_output_not_found",
            f"node {consumer_id!r} refs output {inp.output!r} from {inp.node!r}, not declared",
            node_id=consumer_id,
        ).issues[0])
        return None
    elif inp.component is not None:
        return "component_ref"
    else:
        issues.append(ValidationReport.fail(
            "canonicalize", "input_no_source",
            f"node {consumer_id!r} input has neither node nor component",
            node_id=consumer_id,
        ).issues[0])
        return None
