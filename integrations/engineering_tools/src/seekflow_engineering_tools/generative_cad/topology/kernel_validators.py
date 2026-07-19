"""Kernel-compatible topology validators — plug into validation_kernel RuleRegistry.

Each validator has signature: evaluate_fn(subject) -> ValidationReport
where subject is RawGcadDocument (RAW stage) or CanonicalGcadDocument (CANONICAL).

Phase 7: WARNING level — missing topology contracts produce warnings, not errors.
Phase 8+: ERROR level for high-risk consumers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from seekflow_engineering_tools.generative_cad.validation.reports import (
    ValidationIssue,
    ValidationReport,
)

if TYPE_CHECKING:
    from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument


def validate_topology_contracts(subject: "CanonicalGcadDocument") -> ValidationReport:
    """Check all geometry-producing operations have topology contracts.

    Iterates over canonical nodes, looks up each operation's OperationSpec
    via the dialect registry, and emits a WARNING if no topology_contract
    is declared. Never fails the build in Phase 7.

    Args:
        subject: CanonicalGcadDocument (post-canonicalize).

    Returns:
        ValidationReport with ok=True (advisory only), issues as warnings.
    """
    issues: list[ValidationIssue] = []

    # Geometry-producing effects
    _geometry_effects = frozenset({
        "creates_solid", "modifies_solid", "cuts_material",
        "adds_material", "boolean_union", "boolean_cut", "boolean_intersect",
    })

    for node in subject.nodes:
        # Look up OperationSpec via dialect registry
        try:
            from seekflow_engineering_tools.generative_cad.dialects.registry import (
                require_dialect,
            )
            dialect = require_dialect(node.dialect)
            op_key = (node.op, node.op_version or "1.0.0")
            op_spec = dialect.op_specs().get(op_key)
        except Exception:
            op_spec = None

        if op_spec is None:
            continue

        effects = getattr(op_spec, "effects", [])
        is_geometry_op = any(e in _geometry_effects for e in effects)

        if is_geometry_op:
            contract = getattr(op_spec, "topology_contract", None)
            if contract is None:
                issues.append(ValidationIssue(
                    stage="topology_contract",
                    code="TOPOLOGY_CONTRACT_MISSING",
                    severity="warning",
                    node_id=node.id,
                    message=(
                        f"Geometry-producing operation '{node.op}' "
                        f"(dialect={node.dialect}, node={node.id}) "
                        f"has no topology_contract. Persistent topology naming "
                        f"will be unavailable for faces/edges from this operation."
                    ),
                    path=f"/nodes/{node.id}",
                ))

    return ValidationReport(
        ok=True,  # Phase 7: advisory only, never fails build
        stage="topology_contract",
        issues=issues,
        stages_run=["topology_contract"],
    )


def validate_topology_references(subject: "CanonicalGcadDocument") -> ValidationReport:
    """Check PersistentTopoRef validity in canonical IR.

    Phase 7: placeholder — current IR has no PersistentTopoRef fields.
    Returns ok=True with no issues until IR schema is upgraded.

    Args:
        subject: CanonicalGcadDocument.

    Returns:
        ValidationReport (always ok in Phase 7).
    """
    return ValidationReport(
        ok=True,
        stage="topology_reference",
        issues=[],
        stages_run=["topology_reference"],
    )
