"""Type checking — input/output type resolution and matching."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_typecheck(raw: RawGcadDocument) -> ValidationReport:
    issues = []
    node_map = {n.id: n for n in raw.nodes}

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

        # Check output count matches declared
        if len(node.outputs) != len(op_spec.output_types):
            issues.append(ValidationReport.fail(
                "typecheck", "output_count_mismatch",
                f"node {node.id!r} declares {len(node.outputs)} outputs, "
                f"op {node.op!r} expects {len(op_spec.output_types)}",
                node_id=node.id,
                expected=str(len(op_spec.output_types)),
                actual=str(len(node.outputs)),
            ).issues[0])
        else:
            # Check output types match
            for i, (decl, expected_type) in enumerate(zip(node.outputs, op_spec.output_types)):
                if decl.type != expected_type:
                    issues.append(ValidationReport.fail(
                        "typecheck", "output_type_mismatch",
                        f"node {node.id!r} output[{i}] {decl.name!r} type {decl.type!r} "
                        f"!= op expected {expected_type!r}",
                        node_id=node.id,
                        expected=expected_type,
                        actual=decl.type,
                    ).issues[0])

        # Check input count matches declared
        if len(node.inputs) != len(op_spec.input_types):
            issues.append(ValidationReport.fail(
                "typecheck", "input_count_mismatch",
                f"node {node.id!r} declares {len(node.inputs)} inputs, "
                f"op {node.op!r} expects {len(op_spec.input_types)}",
                node_id=node.id,
                expected=str(len(op_spec.input_types)),
                actual=str(len(node.inputs)),
            ).issues[0])

        # Resolve input types
        for inp in node.inputs:
            if inp.node is not None:
                producer = node_map.get(inp.node)
                if producer is None:
                    continue  # caught in graph stage
                # Find producer's output declaration
                prod_output = None
                for o in producer.outputs:
                    if o.name == inp.output:
                        prod_output = o
                        break
                if prod_output is None:
                    issues.append(ValidationReport.fail(
                        "typecheck", "missing_output_ref",
                        f"node {node.id!r} references output {inp.output!r} "
                        f"from node {inp.node!r}, which does not declare that output",
                        node_id=node.id,
                    ).issues[0])
            elif inp.component is not None:
                # Component output — handled by composition type rules
                pass

    if issues:
        return ValidationReport(ok=False, stage="typecheck", issues=issues)
    return ValidationReport.ok_report("typecheck")
