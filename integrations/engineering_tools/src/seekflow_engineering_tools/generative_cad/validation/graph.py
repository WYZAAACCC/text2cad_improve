"""Graph validation — DAG check, topological sort, input reference resolution."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_graph(raw: RawGcadDocument) -> ValidationReport:
    issues = []
    node_ids = {n.id for n in raw.nodes}
    component_ids = {c.id for c in raw.components}

    # Build adjacency from node inputs (node-to-node edges)
    adj: dict[str, list[str]] = {n.id: [] for n in raw.nodes}
    for node in raw.nodes:
        for inp in node.inputs:
            if inp.node is not None:
                if inp.node not in node_ids:
                    issues.append(ValidationReport.fail(
                        "graph", "missing_input_node_ref",
                        f"node {node.id!r} references unknown node {inp.node!r}",
                        node_id=node.id,
                    ).issues[0])
                else:
                    adj[node.id].append(inp.node)
            if inp.component is not None:
                if inp.component not in component_ids:
                    issues.append(ValidationReport.fail(
                        "graph", "missing_input_component_ref",
                        f"node {node.id!r} references unknown component {inp.component!r}",
                        node_id=node.id,
                    ).issues[0])

    if issues:
        return ValidationReport(ok=False, stage="graph", issues=issues)

    # Cycle detection
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
                issues.append(ValidationReport.fail(
                    "graph", "dag_cycle",
                    f"cycle detected: {' -> '.join(cycle)}",
                    node_id=cycle[0] if cycle else None,
                ).issues[0])
                break

    if issues:
        return ValidationReport(ok=False, stage="graph", issues=issues)
    return ValidationReport.ok_report("graph")
