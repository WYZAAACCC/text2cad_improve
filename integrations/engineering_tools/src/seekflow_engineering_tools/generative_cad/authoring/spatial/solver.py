"""Phase A Spatial Solver — constraint consistency validation only.

In Phase A, component dimensions are unknown, so the solver does NOT compute
numeric placements. It only validates logical consistency of the constraint graph:
- No cyclic stack dependencies
- No contradictory constraints
- All constraint entities exist in the component list

Numeric resolution happens in Phase C (runtime/constraint_resolver.py).
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    SpatialConstraintGraph,
    SpatialSolverReport,
    SpatialSolverIssue,
    PlacementConstraint,
)


def validate_constraint_graph(
    graph: SpatialConstraintGraph,
) -> SpatialSolverReport:
    """Phase A: validate logical consistency of the constraint graph.

    No numeric coordinates are computed.
    """
    issues: list[SpatialSolverIssue] = []

    _check_stack_cycles(graph, issues)
    _check_contradictory_constraints(graph, issues)
    _check_entity_existence(graph, issues)

    total = len(graph.constraints)
    unsolved = sum(1 for i in issues if i.severity == "error")
    return SpatialSolverReport(
        ok=unsolved == 0,
        constraints_total=total,
        constraints_solved=total - unsolved,
        constraints_unsolved=unsolved,
        issues=issues,
    )


def _check_stack_cycles(
    graph: SpatialConstraintGraph, issues: list[SpatialSolverIssue]
) -> None:
    """Detect cycles in Z-axis stacking constraints using DFS."""
    stack_edges: dict[str, list[str]] = {}
    for c in graph.constraints:
        if c.type == "stack" and c.axis == "Z" and len(c.entities) == 2:
            lower, upper = c.entities[0], c.entities[1]
            stack_edges.setdefault(lower, []).append(upper)

    if not stack_edges:
        return

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    def dfs(u: str, path: list[str]) -> None:
        color[u] = GRAY
        for v in stack_edges.get(u, []):
            cv = color.get(v, WHITE)
            if cv == GRAY:
                cycle = path + [v]
                issues.append(SpatialSolverIssue(
                    severity="error",
                    code="stack_cycle",
                    message=f"Cyclic Z stacking: {' → '.join(cycle)}",
                    entities=cycle,
                ))
            elif cv == WHITE:
                dfs(v, path + [v])
        color[u] = BLACK

    for node in list(stack_edges.keys()):
        if color.get(node, WHITE) == WHITE:
            dfs(node, [node])


def _check_contradictory_constraints(
    graph: SpatialConstraintGraph, issues: list[SpatialSolverIssue]
) -> None:
    """Detect contradictory constraints on the same entity pair."""
    pairs: dict[tuple[str, str], list[PlacementConstraint]] = {}
    for c in graph.constraints:
        if len(c.entities) >= 2:
            key = (c.entities[0], c.entities[1])
            pairs.setdefault(key, []).append(c)

    for (a, b), constraints in pairs.items():
        types = {c.type for c in constraints}
        if "stack" in types:
            offsets = [c.offset_mm for c in constraints if c.type == "stack"]
            if any(o > 0 for o in offsets) and any(o < 0 for o in offsets):
                issues.append(SpatialSolverIssue(
                    severity="error",
                    code="contradictory_stack",
                    message=f"Contradictory stack constraints between '{a}' and '{b}'",
                    entities=[a, b],
                ))


def _check_entity_existence(
    graph: SpatialConstraintGraph, issues: list[SpatialSolverIssue]
) -> None:
    """Verify all constraint entities exist in the component list."""
    component_ids = {c.component_id for c in graph.components}
    for c in graph.constraints:
        for eid in c.entities:
            if eid not in component_ids:
                issues.append(SpatialSolverIssue(
                    severity="error",
                    code="unknown_entity",
                    message=f"Constraint '{c.constraint_id}' references unknown entity '{eid}'",
                    entities=[eid],
                ))
