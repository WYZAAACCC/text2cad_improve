"""Structure validation — component/node uniqueness, root_node, basic envelope checks."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_structure(raw: RawGcadDocument) -> ValidationReport:
    issues = []

    comp_ids = [c.id for c in raw.components]
    node_ids = [n.id for n in raw.nodes]
    node_map = {n.id: n for n in raw.nodes}

    # Component IDs unique
    if len(comp_ids) != len(set(comp_ids)):
        issues.append(ValidationReport.fail("structure", "duplicate_component_id", "component ids must be unique").issues[0])

    # Node IDs unique
    if len(node_ids) != len(set(node_ids)):
        issues.append(ValidationReport.fail("structure", "duplicate_node_id", "node ids must be unique").issues[0])

    # Every node references an existing component
    for node in raw.nodes:
        if node.component not in comp_ids:
            issues.append(ValidationReport.fail("structure", "node_unknown_component",
                f"node {node.id!r} references unknown component {node.component!r}", node_id=node.id, component_id=node.component).issues[0])

    # Component/node IDs non-empty
    for c in raw.components:
        if not c.id.strip():
            issues.append(ValidationReport.fail("structure", "empty_component_id", "component id must be non-empty").issues[0])
    for n in raw.nodes:
        if not n.id.strip():
            issues.append(ValidationReport.fail("structure", "empty_node_id", "node id must be non-empty").issues[0])

    # P0-1: root_node validation — must be explicit, exist, belong, have outputs, body:solid
    for c in raw.components:
        rn_id = (c.root_node or "").strip()
        if not rn_id:
            issues.append(ValidationReport.fail("structure", "missing_root_node",
                f"component {c.id!r} must have explicit root_node", component_id=c.id).issues[0])
            continue
        if rn_id not in node_map:
            issues.append(ValidationReport.fail("structure", "root_node_not_found",
                f"component {c.id!r} root_node {rn_id!r} does not exist", component_id=c.id, node_id=rn_id).issues[0])
            continue
        rn = node_map[rn_id]
        if rn.component != c.id:
            issues.append(ValidationReport.fail("structure", "root_node_wrong_component",
                f"component {c.id!r} root_node {rn_id!r} belongs to {rn.component!r}", component_id=c.id, node_id=rn_id).issues[0])
        if not rn.outputs:
            issues.append(ValidationReport.fail("structure", "root_node_no_outputs",
                f"component {c.id!r} root_node {rn_id!r} has no outputs", component_id=c.id, node_id=rn_id).issues[0])
        else:
            has_body = any(o.name == "body" and o.type == "solid" for o in rn.outputs)
            if not has_body:
                issues.append(ValidationReport.fail("structure", "root_node_no_body_solid",
                    f"component {c.id!r} root_node {rn_id!r} must output body:solid", component_id=c.id, node_id=rn_id).issues[0])

    if issues:
        return ValidationReport(ok=False, stage="structure", issues=issues)
    return ValidationReport.ok_report("structure")
