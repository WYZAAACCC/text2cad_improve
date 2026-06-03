"""Composition validation — multi-component assembly rules (v0.3 C001-C008)."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue, ValidationReport


def validate_composition_requirements(raw: RawGcadDocument) -> ValidationReport:
    """Validate multi-component composition rules.

    C001: multiple non-assembly components require __assembly__
    C002: __assembly__ must owner_dialect = composition
    C003: __assembly__ must have at least one node
    C004: __assembly__ root_node must exist
    C005: __assembly__ root_node must output body:solid
    C006: non-assembly component root_node must output body:solid
    C007: single non-assembly component without __assembly__ is allowed
    C008: assembly nodes must use composition dialect
    """
    issues: list[ValidationIssue] = []
    stage = "composition"

    non_assembly = [c for c in raw.components if c.id != "__assembly__"]
    assembly = next((c for c in raw.components if c.id == "__assembly__"), None)

    # C001: multiple non-assembly components require __assembly__
    if len(non_assembly) > 1 and assembly is None:
        issues.append(ValidationIssue(
            stage=stage, code="multiple_components_require_assembly",
            message="multiple non-assembly components require __assembly__ composition component",
            severity="error",
        ))
        return ValidationReport(ok=False, stage=stage, issues=issues)

    if assembly is not None:
        # C002: __assembly__ must owner_dialect = composition
        if assembly.owner_dialect != "composition":
            issues.append(ValidationIssue(
                stage=stage, code="assembly_owner_must_be_composition",
                message="__assembly__ component must have owner_dialect='composition'",
                severity="error",
                component_id=assembly.id,
                actual=assembly.owner_dialect,
                expected="composition",
            ))

        # C003: __assembly__ must have at least one node
        assembly_nodes = [n for n in raw.nodes if n.component == "__assembly__"]
        if not assembly_nodes:
            issues.append(ValidationIssue(
                stage=stage, code="empty_assembly_component",
                message="__assembly__ component must have at least one node",
                severity="error",
                component_id="__assembly__",
            ))

        # C004: __assembly__ root_node must exist
        if assembly.root_node:
            root_found = any(n.id == assembly.root_node for n in raw.nodes)
            if not root_found:
                issues.append(ValidationIssue(
                    stage=stage, code="assembly_missing_root_node",
                    message=f"__assembly__ root_node {assembly.root_node!r} not found",
                    severity="error",
                    component_id="__assembly__",
                ))
        else:
            issues.append(ValidationIssue(
                stage=stage, code="assembly_missing_root_node",
                message="__assembly__ component must have an explicit root_node",
                severity="error",
                component_id="__assembly__",
            ))

        # C005: __assembly__ root_node must output body:solid
        if assembly.root_node:
            for n in raw.nodes:
                if n.id == assembly.root_node and n.component == "__assembly__":
                    body_outputs = [o for o in n.outputs if o.name == "body" and o.type == "solid"]
                    if not body_outputs:
                        issues.append(ValidationIssue(
                            stage=stage, code="assembly_root_must_output_body_solid",
                            message=f"__assembly__ root_node {assembly.root_node!r} must output body:solid",
                            severity="error",
                            component_id="__assembly__",
                            node_id=assembly.root_node,
                        ))
                    break

        # C008: assembly nodes must use composition dialect
        for n in assembly_nodes:
            if n.dialect != "composition":
                issues.append(ValidationIssue(
                    stage=stage, code="assembly_node_must_use_composition",
                    message=f"Node {n.id!r} in __assembly__ must use composition dialect, got {n.dialect!r}",
                    severity="error",
                    node_id=n.id,
                    component_id="__assembly__",
                    actual=n.dialect,
                    expected="composition",
                ))

    # C006: non-assembly component root_node must output body:solid
    for comp in non_assembly:
        if not comp.root_node:
            continue
        for n in raw.nodes:
            if n.id == comp.root_node and n.component == comp.id:
                body_outputs = [o for o in n.outputs if o.name == "body" and o.type == "solid"]
                if not body_outputs:
                    issues.append(ValidationIssue(
                        stage=stage, code="component_root_must_output_body_solid",
                        message=f"Component {comp.id!r} root_node {comp.root_node!r} must output body:solid",
                        severity="error",
                        component_id=comp.id,
                        node_id=comp.root_node,
                    ))
                break

    # C007: single non-assembly component without __assembly__ is allowed — no error

    # C009: composition operations MUST only appear in __assembly__ component
    for n in raw.nodes:
        if n.dialect == "composition" and n.component != "__assembly__":
            issues.append(ValidationIssue(
                stage=stage, code="composition_op_in_leaf_component",
                message=(
                    f"Node {n.id!r} uses composition dialect in leaf component "
                    f"{n.component!r}. Composition operations may only appear "
                    f"in the __assembly__ component."
                ),
                severity="error",
                node_id=n.id,
                component_id=n.component,
            ))

    # C010: boolean_union must have exactly 2 inputs
    for n in raw.nodes:
        if n.op == "boolean_union":
            if len(n.inputs) != 2:
                issues.append(ValidationIssue(
                    stage=stage, code="boolean_union_input_count",
                    message=(
                        f"Node {n.id!r} boolean_union has {len(n.inputs)} input(s), "
                        f"requires exactly 2. Use pairwise chain for 3+ solids."
                    ),
                    severity="error",
                    node_id=n.id,
                    actual=len(n.inputs),
                    expected=2,
                ))

    return ValidationReport(
        ok=not any(i.severity == "error" for i in issues),
        stage=stage,
        issues=issues,
    )
