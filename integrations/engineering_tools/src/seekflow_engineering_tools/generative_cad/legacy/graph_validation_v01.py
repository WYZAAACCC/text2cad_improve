"""Graph validation pipeline for GenerativeCADSpec.

Validates: base existence, op existence, op params schema, DAG, phase order,
base semantics.  Fail-closed for unknown base/op.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GenerativeValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    severity: str = "error"  # "error" | "warning"
    node_id: str | None = None
    stage: str
    expected: Any | None = None
    actual: Any | None = None


class GenerativeValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    stage: str
    issues: list[GenerativeValidationIssue] = Field(default_factory=list)


def _make_issue(
    code: str, message: str, *, node_id: str | None = None, severity: str = "error",
    stage: str = "graph_validation", expected: Any = None, actual: Any = None,
) -> GenerativeValidationIssue:
    return GenerativeValidationIssue(
        code=code, message=message, severity=severity,
        node_id=node_id, stage=stage, expected=expected, actual=actual,
    )


def validate_selected_bases_exist(spec) -> GenerativeValidationReport:
    """Check all selected bases are registered."""
    from seekflow_engineering_tools.generative_cad.legacy.registry_v01 import BASE_REGISTRY

    issues: list[GenerativeValidationIssue] = []
    for sb in spec.selected_bases:
        if sb.base_id not in BASE_REGISTRY:
            issues.append(_make_issue(
                "unknown_base",
                f"Base {sb.base_id!r} is not registered. Available: {sorted(BASE_REGISTRY.keys())}",
                stage="base_existence",
            ))
    return GenerativeValidationReport(
        ok=len(issues) == 0, stage="base_existence", issues=issues,
    )


def validate_node_ops_exist(spec) -> GenerativeValidationReport:
    """Check every node's op exists in its base."""
    from seekflow_engineering_tools.generative_cad.legacy.registry_v01 import BASE_REGISTRY

    issues: list[GenerativeValidationIssue] = []
    for node in spec.feature_graph.nodes:
        base = BASE_REGISTRY.get(node.base_id)
        if base is None:
            continue  # Already reported
        if node.op not in base.operation_definitions:
            allowed = sorted(base.operation_definitions.keys())
            issues.append(_make_issue(
                "unknown_op",
                f"Op {node.op!r} not in base {node.base_id!r}. Allowed: {allowed}",
                node_id=node.id,
                stage="op_existence",
            ))
    return GenerativeValidationReport(
        ok=len(issues) == 0, stage="op_existence", issues=issues,
    )


def validate_op_params_schema(spec) -> GenerativeValidationReport:
    """Validate each node's params against the op's Pydantic model."""
    from seekflow_engineering_tools.generative_cad.legacy.registry_v01 import BASE_REGISTRY

    issues: list[GenerativeValidationIssue] = []
    for node in spec.feature_graph.nodes:
        base = BASE_REGISTRY.get(node.base_id)
        if base is None:
            continue
        op_def = base.operation_definitions.get(node.op)
        if op_def is None:
            continue  # Already reported
        try:
            op_def.params_model.model_validate(node.params)
        except Exception as exc:
            issues.append(_make_issue(
                "invalid_params",
                f"Node {node.id!r} params invalid for op {node.op!r}: {exc}",
                node_id=node.id,
                stage="params_schema",
            ))
    return GenerativeValidationReport(
        ok=len(issues) == 0, stage="params_schema", issues=issues,
    )


def validate_graph_dag(spec) -> GenerativeValidationReport:
    """Check the feature graph is a DAG — no cycles."""
    issues: list[GenerativeValidationIssue] = []
    node_ids = {n.id for n in spec.feature_graph.nodes}

    # Check depends_on references exist
    for node in spec.feature_graph.nodes:
        for dep_id in node.depends_on:
            if dep_id not in node_ids:
                issues.append(_make_issue(
                    "missing_dependency",
                    f"Node {node.id!r} depends on {dep_id!r}, which does not exist.",
                    node_id=node.id,
                    stage="dag",
                ))

    # Cycle detection via DFS
    adj: dict[str, list[str]] = {n.id: list(n.depends_on) for n in spec.feature_graph.nodes}
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {nid: WHITE for nid in node_ids}

    def _dfs(nid: str) -> list[str] | None:
        color[nid] = GRAY
        for dep in adj.get(nid, []):
            if dep not in color:
                continue
            if color[dep] == GRAY:
                return [nid, dep]
            if color[dep] == WHITE:
                cycle = _dfs(dep)
                if cycle is not None:
                    return [nid] + cycle
        color[nid] = BLACK
        return None

    for nid in node_ids:
        if color[nid] == WHITE:
            cycle = _dfs(nid)
            if cycle is not None:
                issues.append(_make_issue(
                    "dag_cycle",
                    f"Cycle detected in feature graph: {' → '.join(cycle)}",
                    node_id=cycle[0] if cycle else None,
                    stage="dag",
                ))
                break

    return GenerativeValidationReport(
        ok=len(issues) == 0, stage="dag", issues=issues,
    )


def validate_phase_order(spec) -> GenerativeValidationReport:
    """Check each node's phase matches the op's registered phase."""
    from seekflow_engineering_tools.generative_cad.legacy.registry_v01 import BASE_REGISTRY

    issues: list[GenerativeValidationIssue] = []
    for node in spec.feature_graph.nodes:
        base = BASE_REGISTRY.get(node.base_id)
        if base is None:
            continue
        op_def = base.operation_definitions.get(node.op)
        if op_def is None:
            continue
        if node.phase != op_def.phase:
            issues.append(_make_issue(
                "phase_mismatch",
                f"Node {node.id!r} phase {node.phase!r} != op phase {op_def.phase!r}",
                node_id=node.id,
                stage="phase_order",
                expected=op_def.phase,
                actual=node.phase,
            ))
    return GenerativeValidationReport(
        ok=len(issues) == 0, stage="phase_order", issues=issues,
    )


def validate_base_semantics(spec) -> GenerativeValidationReport:
    """Run each base's semantic validator over the graph nodes it owns."""
    from seekflow_engineering_tools.generative_cad.legacy.registry_v01 import BASE_REGISTRY

    issues: list[GenerativeValidationIssue] = []
    # Group nodes by base
    base_nodes: dict[str, list] = {}
    for node in spec.feature_graph.nodes:
        base_nodes.setdefault(node.base_id, []).append(node)

    for base_id, nodes in base_nodes.items():
        base = BASE_REGISTRY.get(base_id)
        if base is None:
            continue
        try:
            graph_dict = {"nodes": [n.model_dump() for n in nodes]}
            semantic_issues = base.validate_semantics(graph_dict)
            for si in semantic_issues:
                issues.append(GenerativeValidationIssue(
                    code=si.get("code", "semantic_error"),
                    message=si.get("message", str(si)),
                    severity=si.get("severity", "error"),
                    node_id=si.get("node_id"),
                    stage="base_semantics",
                    expected=si.get("expected"),
                    actual=si.get("actual"),
                ))
        except Exception as exc:
            issues.append(_make_issue(
                "semantic_validation_error",
                f"Semantic validation for base {base_id!r} failed: {exc}",
                stage="base_semantics",
            ))

    return GenerativeValidationReport(
        ok=len([i for i in issues if i.severity == "error"]) == 0,
        stage="base_semantics",
        issues=issues,
    )


def run_graph_validation(spec) -> GenerativeValidationReport:
    """Run the full graph validation pipeline.

    Returns the first failing report, or the last (passing) one.
    """
    stages = [
        ("base_existence", validate_selected_bases_exist),
        ("op_existence", validate_node_ops_exist),
        ("params_schema", validate_op_params_schema),
        ("dag", validate_graph_dag),
        ("phase_order", validate_phase_order),
        ("base_semantics", validate_base_semantics),
    ]

    all_issues: list[GenerativeValidationIssue] = []
    for stage_name, validator in stages:
        report = validator(spec)
        all_issues.extend(report.issues)
        if not report.ok:
            return GenerativeValidationReport(
                ok=False,
                stage=stage_name,
                issues=all_issues,
            )

    return GenerativeValidationReport(
        ok=True,
        stage="graph_validation",
        issues=all_issues,
    )
