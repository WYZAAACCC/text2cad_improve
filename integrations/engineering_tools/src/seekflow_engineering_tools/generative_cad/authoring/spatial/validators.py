"""Phase A Spatial Validator — constraint consistency checks.

Validates the SpatialConstraintGraph for:
- V001: unplaced multi-component bodies
- V002: identity collapse (multiple identity placements)
- V003: left/right naming without symmetric constraint
- V008: assembly connectivity
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import (
    SpatialConstraintGraph,
    SpatialValidationReport,
    SpatialValidationIssue,
)


def validate_spatial_contract_phase_a(
    graph: SpatialConstraintGraph,
) -> SpatialValidationReport:
    """Phase A spatial validation.

    Checks constraint logic consistency without requiring actual dimensions.
    All checks use constraint structure and component naming only.
    """
    issues: list[SpatialValidationIssue] = []
    component_ids = {c.component_id for c in graph.components}

    # V001: unplaced multi-component body
    _check_unplaced(graph, component_ids, issues)

    # V002: identity collapse
    _check_identity_collapse(graph, issues)

    # V003: left/right naming without symmetry
    _check_left_right_symmetry(graph, issues)

    # V008: connectivity
    _check_connectivity(graph, component_ids, issues)

    return SpatialValidationReport(
        ok=not any(i.severity == "error" for i in issues),
        issues=issues,
    )


def _check_unplaced(
    graph: SpatialConstraintGraph,
    component_ids: set[str],
    issues: list[SpatialValidationIssue],
) -> None:
    """V001: Multi-component assemblies need placement for every component."""
    if len(component_ids) <= 1:
        return

    placed_ids: set[str] = set()
    for c in graph.constraints:
        placed_ids.update(c.entities)

    unplaced = component_ids - placed_ids
    for cid in sorted(unplaced):
        issues.append(SpatialValidationIssue(
            severity="warning",
            code="spatial_unplaced_component",
            message=f"Component '{cid}' has no placement constraint (will default to identity)",
            entities=[cid],
        ))


def _check_identity_collapse(
    graph: SpatialConstraintGraph,
    issues: list[SpatialValidationIssue],
) -> None:
    """V002: Multiple components with identity placement → likely error."""
    identity_entities: set[str] = set()
    for c in graph.constraints:
        if c.type == "identity":
            identity_entities.update(c.entities)

    if len(identity_entities) > 1:
        issues.append(SpatialValidationIssue(
            severity="error",
            code="spatial_identity_collapse",
            message=f"Multiple components have identity placement (will overlap): {identity_entities}",
            entities=sorted(identity_entities),
        ))


def _check_left_right_symmetry(
    graph: SpatialConstraintGraph,
    issues: list[SpatialValidationIssue],
) -> None:
    """V003: left/right named components should have symmetric_pair constraint."""
    pairs = _find_left_right_pairs(graph)
    for a, b in pairs:
        has_symmetric = any(
            c.type == "symmetric" and a in c.entities and b in c.entities
            for c in graph.constraints
        )
        if not has_symmetric:
            issues.append(SpatialValidationIssue(
                severity="warning",
                code="spatial_left_right_no_symmetry",
                message=f"Components '{a}' and '{b}' have left/right naming "
                        f"but no symmetric_pair constraint",
                entities=[a, b],
            ))


def _check_connectivity(
    graph: SpatialConstraintGraph,
    component_ids: set[str],
    issues: list[SpatialValidationIssue],
) -> None:
    """V008: Assembly constraint graph should be connected."""
    if len(component_ids) <= 1:
        return

    adj: dict[str, set[str]] = {cid: set() for cid in component_ids}
    for c in graph.constraints:
        for i in range(len(c.entities)):
            for j in range(i + 1, len(c.entities)):
                a, b = c.entities[i], c.entities[j]
                if a in adj and b in adj:
                    adj[a].add(b)
                    adj[b].add(a)

    if not adj:
        return

    visited: set[str] = set()

    def dfs(node: str) -> None:
        visited.add(node)
        for nb in adj.get(node, set()):
            if nb not in visited:
                dfs(nb)

    start = next(iter(adj))
    dfs(start)

    disconnected = component_ids - visited
    if disconnected:
        issues.append(SpatialValidationIssue(
            severity="error",
            code="spatial_disconnected_assembly",
            message=f"Disconnected components (no constraints linking them): {disconnected}",
            entities=sorted(disconnected),
        ))


def _find_left_right_pairs(graph: SpatialConstraintGraph) -> list[tuple[str, str]]:
    """Find component pairs with _left/_right naming pattern."""
    left = [c for c in graph.components if "_left" in c.component_id.lower()]
    right = [c for c in graph.components if "_right" in c.component_id.lower()]
    pairs: list[tuple[str, str]] = []
    for lc in left:
        base = lc.component_id.lower().replace("_left", "")
        for rc in right:
            if rc.component_id.lower().replace("_right", "") == base:
                pairs.append((lc.component_id, rc.component_id))
    return pairs
