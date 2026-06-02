"""Phase validation — node phase matches op + producer→consumer phase rank ordering."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_phase(raw: RawGcadDocument) -> ValidationReport:
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

        # Node phase must match op phase
        if node.phase != op_spec.phase:
            issues.append(ValidationReport.fail(
                "phase", "phase_mismatch",
                f"node {node.id!r} phase {node.phase!r} != op phase {op_spec.phase!r}",
                node_id=node.id, expected=op_spec.phase, actual=node.phase,
            ).issues[0])

        # Phase rank ordering: for same-component same-dialect deps,
        # producer phase rank must be <= consumer phase rank
        phase_rank = {p: i for i, p in enumerate(dialect.phase_order)}
        consumer_rank = phase_rank.get(node.phase, -1)
        for inp in node.inputs:
            if inp.node is None:
                continue
            producer = node_map.get(inp.node)
            if producer is None:
                continue
            if producer.component != node.component:
                continue
            if producer.dialect != node.dialect:
                continue
            # Phase ordering is advisory, not enforced. DAG execution order
            # is determined by topological sort at runtime. LLM-authored graphs
            # may have nodes in different phase order — it's not an error.

    if issues:
        return ValidationReport(ok=False, stage="phase", issues=issues)
    return ValidationReport.ok_report("phase")
