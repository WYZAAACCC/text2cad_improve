"""Component ownership validation — cross-component and cross-dialect rules."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_ownership(raw: RawGcadDocument) -> ValidationReport:
    issues = []
    comp_map = {c.id: c for c in raw.components}
    selected = {sd.dialect for sd in raw.selected_dialects}

    for node in raw.nodes:
        comp = comp_map.get(node.component)
        if comp is None:
            continue  # caught in structure stage

        # Check component's owner_dialect is in selected_dialects
        if comp.owner_dialect not in selected:
            issues.append(ValidationReport.fail(
                "ownership", "owner_dialect_not_selected",
                f"component {comp.id!r} owner_dialect {comp.owner_dialect!r} "
                f"not in selected_dialects",
                component_id=comp.id,
            ).issues[0])

        # Check node's dialect is in selected_dialects
        if node.dialect not in selected:
            issues.append(ValidationReport.fail(
                "ownership", "node_dialect_not_selected",
                f"node {node.id!r} dialect {node.dialect!r} "
                f"not in selected_dialects",
                node_id=node.id,
            ).issues[0])

        # Rule: __assembly__ must have owner_dialect = "composition"
        if comp.id == "__assembly__" and comp.owner_dialect != "composition":
            issues.append(ValidationReport.fail(
                "ownership", "assembly_not_composition",
                f"__assembly__ component must use composition dialect, "
                f"got {comp.owner_dialect!r}",
                component_id=comp.id,
            ).issues[0])

        # Rule: non-assembly component nodes must use owner_dialect
        if comp.id != "__assembly__" and node.dialect != comp.owner_dialect:
            issues.append(ValidationReport.fail(
                "ownership", "node_dialect_mismatch_owner",
                f"node {node.id!r} dialect {node.dialect!r} != "
                f"component {comp.id!r} owner_dialect {comp.owner_dialect!r}",
                node_id=node.id,
                component_id=comp.id,
            ).issues[0])

        # Rule: cross-component node-to-node input forbidden unless composition
        for inp in node.inputs:
            if inp.node is not None:
                producer = _find_node(raw, inp.node)
                if producer is not None:
                    if producer.component != node.component and node.dialect != "composition":
                        issues.append(ValidationReport.fail(
                            "ownership", "cross_component_node_ref_forbidden",
                            f"node {node.id!r} (component={node.component}) references "
                            f"node {inp.node!r} (component={producer.component}) "
                            f"without composition dialect",
                            node_id=node.id,
                            component_id=node.component,
                        ).issues[0])

            if inp.component is not None and node.dialect != "composition":
                if inp.component != node.component:
                    issues.append(ValidationReport.fail(
                        "ownership", "cross_component_input_forbidden",
                        f"node {node.id!r} (dialect={node.dialect}) cannot consume "
                        f"component output from {inp.component!r} "
                        f"(only composition can)",
                        node_id=node.id,
                        component_id=node.component,
                    ).issues[0])

    if issues:
        return ValidationReport(ok=False, stage="ownership", issues=issues)
    return ValidationReport.ok_report("ownership")


def _find_node(raw: RawGcadDocument, node_id: str):
    for n in raw.nodes:
        if n.id == node_id:
            return n
    return None
