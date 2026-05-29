"""Type checking — input/output type resolution with producer-consumer matching.

v0.2.1: truly compares producer output type with consumer expected input type.
No implicit solid fallback.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_typecheck(raw: RawGcadDocument) -> ValidationReport:
    issues = []
    node_map = {n.id: n for n in raw.nodes}
    comp_map = {c.id: c for c in raw.components}

    for node in raw.nodes:
        try:
            dialect = require_dialect(node.dialect)
        except KeyError:
            continue
        try:
            version = node.op_version or dialect.default_op_version(node.op)
            op_spec = dialect.get_op_spec(node.op, version)
        except (KeyError, ValueError):
            continue

        # Output count + type match
        if len(node.outputs) != len(op_spec.output_types):
            issues.append(ValidationReport.fail(
                "typecheck", "output_count_mismatch",
                f"node {node.id!r}: {len(node.outputs)} outputs, op expects {len(op_spec.output_types)}",
                node_id=node.id, expected=str(len(op_spec.output_types)), actual=str(len(node.outputs)),
            ).issues[0])
        else:
            for i, (decl, exp) in enumerate(zip(node.outputs, op_spec.output_types)):
                if decl.type != exp:
                    issues.append(ValidationReport.fail(
                        "typecheck", "output_type_mismatch",
                        f"node {node.id!r} output[{i}] {decl.name!r}: {decl.type!r} != op {exp!r}",
                        node_id=node.id, expected=exp, actual=decl.type,
                    ).issues[0])

        # Input count match
        if len(node.inputs) != len(op_spec.input_types):
            issues.append(ValidationReport.fail(
                "typecheck", "input_count_mismatch",
                f"node {node.id!r}: {len(node.inputs)} inputs, op expects {len(op_spec.input_types)}",
                node_id=node.id, expected=str(len(op_spec.input_types)), actual=str(len(node.inputs)),
            ).issues[0])

        # Input type matching — compare producer output type with consumer expected input type
        for idx, (inp, expected) in enumerate(zip(node.inputs, op_spec.input_types)):
            actual = _resolve_producer_type(inp, node_map, comp_map)
            if actual is None:
                issues.append(ValidationReport.fail(
                    "typecheck", "input_type_unresolved",
                    f"node {node.id!r} input[{idx}]: cannot resolve producer type",
                    node_id=node.id,
                ).issues[0])
            elif actual == "component_ref":
                if node.dialect != "composition":
                    issues.append(ValidationReport.fail(
                        "typecheck", "cross_component_not_composition",
                        f"node {node.id!r} (dialect={node.dialect}) cannot consume component output",
                        node_id=node.id,
                    ).issues[0])
            elif actual != expected:
                issues.append(ValidationReport.fail(
                    "typecheck", "input_type_mismatch",
                    f"node {node.id!r} input[{idx}]: producer type {actual!r} != expected {expected!r}",
                    node_id=node.id, expected=expected, actual=actual,
                ).issues[0])

    if issues:
        return ValidationReport(ok=False, stage="typecheck", issues=issues)
    return ValidationReport.ok_report("typecheck")


def _resolve_producer_type(inp, node_map, comp_map) -> str | None:
    if inp.node is not None:
        p = node_map.get(inp.node)
        if p is None:
            return None
        for o in p.outputs:
            if o.name == inp.output:
                return o.type
        return None
    elif inp.component is not None:
        c = comp_map.get(inp.component)
        if c is None or not c.root_node:
            return None
        rn = node_map.get(c.root_node)
        if rn is None:
            return None
        for o in rn.outputs:
            if o.name == inp.output:
                return o.type
        return None
    return None
