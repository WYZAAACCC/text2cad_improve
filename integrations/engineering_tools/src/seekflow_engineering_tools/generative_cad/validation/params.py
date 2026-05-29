"""Params validation — validate node.params against OperationSpec.params_model."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_params(raw: RawGcadDocument) -> ValidationReport:
    issues = []

    for node in raw.nodes:
        try:
            dialect = require_dialect(node.dialect)
        except KeyError:
            continue  # caught in registry stage

        try:
            version = node.op_version or dialect.default_op_version(node.op)
            op_spec = dialect.get_op_spec(node.op, version)
        except (KeyError, ValueError):
            continue  # caught in registry stage

        try:
            op_spec.validate_params(node.params)
        except Exception as exc:
            issues.append(ValidationReport.fail(
                "params", "invalid_params",
                f"node {node.id!r} params invalid for op {node.op!r}: {exc}",
                node_id=node.id,
            ).issues[0])

    if issues:
        return ValidationReport(ok=False, stage="params", issues=issues)
    return ValidationReport.ok_report("params")
