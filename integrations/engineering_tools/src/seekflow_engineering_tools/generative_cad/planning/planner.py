"""PlannerPass — read-only optimization analysis for the CAD compiler.

Analyzes the canonical operation graph (with ShapeFacts if available) and
produces a PlanningReport containing optimization opportunities and risk
warnings. Does NOT modify the graph or alter execution behavior.

Phase 3 rules:
  1. cut_circular_hole_pattern count >= 8  → opportunity hole_pattern_should_batch
  2. pattern count >= 120                    → warning large_pattern_risk
  3. >= 32 destructive ops in component      → warning many_destructive_ops
  4. edge_treatment before later destructive  → warning edge_treatment_too_early
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.planning.planning_report import (
    PlanningIssue,
    PlanningReport,
)
from seekflow_engineering_tools.generative_cad.planning.risk_model import (
    HOLE_PATTERN_BATCH_THRESHOLD,
    HOLE_PATTERN_LARGE_THRESHOLD,
    MANY_DESTRUCTIVE_OPS_THRESHOLD,
    EDGE_TREATMENT_PHASES,
    DESTRUCTIVE_PHASES,
)


class PlannerPass:
    """Compiler pass: analyze canonical graph for optimization opportunities.

    Runs after FactPropagationPass (Phase 1). Uses ShapeFacts for
    additional detail when available, but can run without them.
    Reads canonical nodes directly — does NOT modify anything.
    """

    name = "planning"

    def run(self, module: "CompilerModule") -> "CompilerModule":
        """Analyze the canonical graph and produce a PlanningReport."""
        canonical = module.canonical
        if canonical is None:
            module.add_issue(
                stage="planning",
                code="no_canonical",
                message="No canonical document to analyze.",
                severity="error",
            )
            return module

        issues: list[PlanningIssue] = []

        for component in canonical.components:
            if component.id == "__assembly__":
                continue

            nodes = [
                n for n in canonical.nodes
                if n.component == component.id
            ]
            if not nodes:
                continue

            # ── Rule 1+2: Pattern count analysis ──
            self._check_pattern_counts(nodes, component.id, issues)

            # ── Rule 3: Destructive op count ──
            self._check_destructive_op_count(nodes, component.id, issues)

            # ── Rule 4: Edge treatment ordering ──
            self._check_edge_treatment_ordering(nodes, component.id, issues)

        # Build report
        opt_ops = [
            i.model_dump() for i in issues if i.severity == "info"
        ]
        report = PlanningReport(
            ok=not any(i.severity == "error" for i in issues),
            issues=issues,
            optimization_opportunities=opt_ops,
        )

        module.planning_report = report.model_dump()

        # Emit issues as compiler diagnostics
        for issue in issues:
            module.add_issue(
                stage="planning",
                code=issue.code,
                message=issue.message,
                severity=issue.severity,
                node_id=issue.node_id,
                component_id=issue.component_id,
                details=issue.details,
            )

        return module

    # ── Rule helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _check_pattern_counts(nodes, component_id, issues):
        """Check hole pattern counts against batching and large-pattern thresholds."""
        for node in nodes:
            if node.op == "cut_circular_hole_pattern":
                count = node.typed_params.get("count") if node.typed_params else node.params.get("count", 0)
                if isinstance(count, (int, float)):
                    count = int(count)

                if count >= HOLE_PATTERN_LARGE_THRESHOLD:
                    issues.append(PlanningIssue(
                        code="large_pattern_risk",
                        severity="warning",
                        message=(
                            f"Large hole pattern on node '{node.id}': "
                            f"count={count} >= {HOLE_PATTERN_LARGE_THRESHOLD}. "
                            f"Large patterns are slow and prone to OCCT instability."
                        ),
                        node_id=node.id,
                        component_id=component_id,
                        suggestion=(
                            f"Reduce count below {HOLE_PATTERN_LARGE_THRESHOLD} "
                            f"or split across multiple smaller patterns."
                        ),
                        details={"count": count, "threshold": HOLE_PATTERN_LARGE_THRESHOLD},
                    ))
                elif count >= HOLE_PATTERN_BATCH_THRESHOLD:
                    issues.append(PlanningIssue(
                        code="hole_pattern_should_batch",
                        severity="info",
                        message=(
                            f"Hole pattern on node '{node.id}': "
                            f"count={count} >= {HOLE_PATTERN_BATCH_THRESHOLD}. "
                            f"Consider using compound-based batch cut."
                        ),
                        node_id=node.id,
                        component_id=component_id,
                        suggestion=(
                            "Use batch_cut with a compound of all hole cylinders "
                            "instead of sequential individual cuts."
                        ),
                        details={"count": count, "threshold": HOLE_PATTERN_BATCH_THRESHOLD},
                    ))

            elif node.op == "cut_hole_pattern_linear":
                count_x = node.typed_params.get("count_x") if node.typed_params else node.params.get("count_x", 0)
                count_y = node.typed_params.get("count_y") if node.typed_params else node.params.get("count_y", 0)
                total = int(count_x) * int(count_y) if count_x and count_y else 0

                if total >= HOLE_PATTERN_LARGE_THRESHOLD:
                    issues.append(PlanningIssue(
                        code="large_pattern_risk",
                        severity="warning",
                        message=(
                            f"Large linear hole pattern on node '{node.id}': "
                            f"total={total} (x={count_x}, y={count_y}) >= {HOLE_PATTERN_LARGE_THRESHOLD}."
                        ),
                        node_id=node.id,
                        component_id=component_id,
                        suggestion="Reduce pattern dimensions or split across multiple patterns.",
                        details={"count_x": count_x, "count_y": count_y, "total": total},
                    ))
                elif total >= HOLE_PATTERN_BATCH_THRESHOLD:
                    issues.append(PlanningIssue(
                        code="hole_pattern_should_batch",
                        severity="info",
                        message=(
                            f"Linear hole pattern on node '{node.id}': "
                            f"total={total} (x={count_x}, y={count_y}) >= {HOLE_PATTERN_BATCH_THRESHOLD}. "
                            f"Consider batch cutting."
                        ),
                        node_id=node.id,
                        component_id=component_id,
                        suggestion="Use batch_cut with a compound of all hole cylinders.",
                        details={"count_x": count_x, "count_y": count_y, "total": total},
                    ))

            elif node.op == "cut_rim_slot_pattern":
                count = node.typed_params.get("count") if node.typed_params else node.params.get("count", 0)
                if isinstance(count, (int, float)):
                    count = int(count)

                if count >= HOLE_PATTERN_BATCH_THRESHOLD:
                    issues.append(PlanningIssue(
                        code="hole_pattern_should_batch",
                        severity="info",
                        message=(
                            f"Rim slot pattern on node '{node.id}': "
                            f"count={count} >= {HOLE_PATTERN_BATCH_THRESHOLD}. "
                            f"Consider batch cutting."
                        ),
                        node_id=node.id,
                        component_id=component_id,
                        suggestion="Use batch_cut with a compound of all slot cutters.",
                        details={"count": count, "threshold": HOLE_PATTERN_BATCH_THRESHOLD},
                    ))

    @staticmethod
    def _check_destructive_op_count(nodes, component_id, issues):
        """Check if a component has an unusually high number of destructive ops."""
        destructive_ops = [
            n for n in nodes
            if any(e in ("cuts_material", "boolean_cut") for e in (n.operation_effects or []))
        ]
        count = len(destructive_ops)
        if count >= MANY_DESTRUCTIVE_OPS_THRESHOLD:
            issues.append(PlanningIssue(
                code="many_destructive_ops",
                severity="warning",
                message=(
                    f"Component '{component_id}' has {count} destructive operations "
                    f"(>= {MANY_DESTRUCTIVE_OPS_THRESHOLD}). "
                    f"High boolean cut counts increase failure probability."
                ),
                component_id=component_id,
                suggestion=(
                    "Consider batching or reordering destructive operations "
                    "to reduce OCCT boolean instability risk."
                ),
                details={
                    "count": count,
                    "threshold": MANY_DESTRUCTIVE_OPS_THRESHOLD,
                    "node_ids": [n.id for n in destructive_ops],
                },
            ))

    @staticmethod
    def _check_edge_treatment_ordering(nodes, component_id, issues):
        """Check if edge treatment ops appear before later destructive ops.

        For each edge_treatment node, check if there are destructive ops
        that come later in the phase order. If so, the edge treatment
        may be destroyed or cause downstream boolean failures.
        """
        # Build phase order from canonical nodes
        phase_order: dict[str, int] = {}
        for node in nodes:
            if node.phase not in phase_order:
                phase_order[node.phase] = len(phase_order)

        for et_node in nodes:
            if et_node.phase not in EDGE_TREATMENT_PHASES:
                continue

            # Check if any destructive op comes AFTER this edge treatment
            et_index = phase_order.get(et_node.phase, 0)
            later_destructive = [
                n for n in nodes
                if n.phase in DESTRUCTIVE_PHASES
                and phase_order.get(n.phase, 0) > et_index
            ]

            if later_destructive:
                later_ids = [n.id for n in later_destructive]
                issues.append(PlanningIssue(
                    code="edge_treatment_too_early",
                    severity="warning",
                    message=(
                        f"Edge treatment on node '{et_node.id}' (phase='{et_node.phase}') "
                        f"appears before {len(later_destructive)} subsequent destructive "
                        f"operation(s): {later_ids}. Edge treatments should usually be "
                        f"among the last operations."
                    ),
                    node_id=et_node.id,
                    component_id=component_id,
                    suggestion=(
                        "Move edge treatment (chamfer/fillet) to a later phase "
                        "to avoid being destroyed by downstream boolean operations."
                    ),
                    details={
                        "edge_treatment_node": et_node.id,
                        "later_destructive_nodes": later_ids,
                    },
                ))
