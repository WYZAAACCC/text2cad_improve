"""Structure validation stage — component/node uniqueness, basic envelope checks."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_structure(raw: RawGcadDocument) -> ValidationReport:
    issues = []

    # Component IDs unique
    comp_ids = [c.id for c in raw.components]
    if len(comp_ids) != len(set(comp_ids)):
        issues.append(ValidationReport.fail(
            "structure", "duplicate_component_id",
            "component ids must be unique",
        ).issues[0])

    # Node IDs unique
    node_ids = [n.id for n in raw.nodes]
    if len(node_ids) != len(set(node_ids)):
        issues.append(ValidationReport.fail(
            "structure", "duplicate_node_id",
            "node ids must be unique",
        ).issues[0])

    # Every node references an existing component
    for node in raw.nodes:
        if node.component not in comp_ids:
            issues.append(ValidationReport.fail(
                "structure", "node_unknown_component",
                f"node {node.id!r} references unknown component {node.component!r}",
                node_id=node.id,
                component_id=node.component,
            ).issues[0])

    # Component IDs must be non-empty
    for c in raw.components:
        if not c.id.strip():
            issues.append(ValidationReport.fail(
                "structure", "empty_component_id",
                "component id must be non-empty",
            ).issues[0])

    # Node IDs must be non-empty
    for n in raw.nodes:
        if not n.id.strip():
            issues.append(ValidationReport.fail(
                "structure", "empty_node_id",
                "node id must be non-empty",
            ).issues[0])

    if issues:
        return ValidationReport(ok=False, stage="structure", issues=issues)
    return ValidationReport.ok_report("structure")
