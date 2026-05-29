"""Canonicalization — convert RawGcadDocument to CanonicalGcadDocument."""

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
from seekflow_engineering_tools.generative_cad.ir.values import ValueType
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def canonicalize(raw: RawGcadDocument) -> tuple[CanonicalGcadDocument | None, ValidationReport]:
    """Convert a validated RawGcadDocument to CanonicalGcadDocument."""
    issues = []

    # Resolve dialects with contract hashes
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
            dialect=sd.dialect,
            version=sd.version,
            contract_hash=ch,
        ))

    if issues:
        return None, ValidationReport(ok=False, stage="canonicalize", issues=issues)

    # Resolve components
    canonical_components = []
    for c in raw.components:
        root_node = c.root_node or ""
        if not root_node:
            # Find first node in this component as root
            for n in raw.nodes:
                if n.component == c.id:
                    root_node = n.id
                    break
        canonical_components.append(CanonicalComponent(
            id=c.id,
            owner_dialect=c.owner_dialect,
            kind_hint=c.kind_hint,
            root_node=root_node,
        ))

    # Resolve nodes
    canonical_nodes = []
    for node in raw.nodes:
        dialect = require_dialect(node.dialect)
        version = node.op_version or dialect.default_op_version(node.op)
        op_spec = dialect.get_op_spec(node.op, version)

        # Validate and get typed_params
        try:
            typed_params = op_spec.validate_params(node.params)
        except Exception as exc:
            issues.append(ValidationReport.fail(
                "canonicalize", "canonicalize_params_validation",
                f"node {node.id!r} params failed: {exc}",
                node_id=node.id,
            ).issues[0])
            continue

        # Resolve inputs with types
        resolved_inputs = []
        node_map = {n.id: n for n in raw.nodes}
        for inp in node.inputs:
            resolved_type: ValueType = "solid"  # default fallback
            if inp.node is not None:
                producer = node_map.get(inp.node)
                if producer is not None:
                    for o in producer.outputs:
                        if o.name == inp.output:
                            resolved_type = o.type  # type: ignore[assignment]
                            break
            resolved_inputs.append(CanonicalValueRef(
                producer_node=inp.node,
                producer_component=inp.component,
                output=inp.output,
                resolved_type=resolved_type,
            ))

        # Resolve outputs with value_ids
        resolved_outputs = []
        for i, decl in enumerate(node.outputs):
            vid = f"{decl.type}:{node.component}:{node.id}:{decl.name}"
            resolved_outputs.append(CanonicalValueDecl(
                name=decl.name,
                type=decl.type,  # type: ignore[arg-type]
                value_id=vid,
            ))

        canonical_nodes.append(CanonicalNode(
            id=node.id,
            component=node.component,
            dialect=node.dialect,
            op=node.op,
            op_version=version,
            phase=node.phase,
            inputs=resolved_inputs,
            outputs=resolved_outputs,
            params=node.params,
            typed_params=typed_params,
            required=node.required,
            degradation_policy=node.degradation_policy,
            operation_effects=op_spec.effects,
            postconditions=op_spec.postconditions,
        ))

    if issues:
        return None, ValidationReport(ok=False, stage="canonicalize", issues=issues)

    # Compute canonical graph hash
    raw_hash = stable_hash(raw.model_dump())
    nodes_for_hash = [
        {
            "id": n.id, "component": n.component, "dialect": n.dialect,
            "op": n.op, "op_version": n.op_version, "phase": n.phase,
            "inputs": [i.model_dump() for i in n.inputs],
            "outputs": [o.model_dump() for o in n.outputs],
            "params": n.params,
        }
        for n in canonical_nodes
    ]
    cgh = stable_hash(nodes_for_hash)

    canonical = CanonicalGcadDocument(
        document_id=raw.document_id,
        part_name=raw.part_name,
        units=raw.units,
        trust_level=raw.trust_level,
        selected_dialects=resolved_dialects,
        components=canonical_components,
        nodes=canonical_nodes,
        constraints=raw.constraints,
        safety=raw.safety,
        canonical_graph_hash=cgh,
        raw_graph_hash=raw_hash,
    )

    return canonical, ValidationReport.ok_report("canonicalize")
