"""OperationSemanticSpec — semantic metadata for each operation (sidecar to OperationSpec).

Phase 1: define the data model and populate specs for axisymmetric ops.
Phase 2+: wire into semantic_typecheck pass for trait-based validation.

Design: does NOT modify dialects/operation.py OperationSpec.
Semantic specs are stored in a separate registry keyed by (dialect, op, op_version).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class OperationSemanticSpec:
    """Semantic metadata for a single operation — sidecar to OperationSpec.

    Stored separately from OperationSpec to avoid modifying the stable ABI.
    """

    dialect: str
    op: str
    op_version: str = "1.0.0"

    # Traits that solid inputs should/must have
    required_input_traits: tuple[str, ...] = ()
    # Traits that this operation is known to produce
    produced_traits: tuple[str, ...] = ()

    # Reference to fact rule function (from fact_rules.py)
    fact_rule: Callable[..., Any] | None = None
    # Reference to feasibility check function
    feasibility_rule: Callable[..., Any] | None = None

    # Risk tags for planning
    risk_tags: tuple[str, ...] = ()


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 registry — axisymmetric + composition ops
# ═══════════════════════════════════════════════════════════════════════════════

SEMANTIC_SPECS: dict[tuple[str, str, str], OperationSemanticSpec] = {}

# Import fact rules lazily to avoid circular imports
def _populate_semantic_specs() -> None:
    """Populate the SEMANTIC_SPECS registry. Called once at first use."""
    if SEMANTIC_SPECS:
        return

    from seekflow_engineering_tools.generative_cad.analysis.fact_rules import (
        rule_revolve_profile,
        rule_cut_center_bore,
        rule_cut_circular_hole_pattern,
        rule_cut_annular_groove,
        rule_extrude_rectangle,
        rule_translate_solid,
        rule_boolean_union,
        rule_boolean_cut,
    )

    _specs: list[OperationSemanticSpec] = [
        # ── axisymmetric ──
        OperationSemanticSpec(
            dialect="axisymmetric",
            op="revolve_profile",
            produced_traits=("closed_candidate", "axisymmetric", "z_axis"),
            fact_rule=rule_revolve_profile,
        ),
        OperationSemanticSpec(
            dialect="axisymmetric",
            op="cut_center_bore",
            required_input_traits=("closed_candidate",),
            fact_rule=rule_cut_center_bore,
            risk_tags=("destructive", "may_remove_all_material"),
        ),
        OperationSemanticSpec(
            dialect="axisymmetric",
            op="cut_circular_hole_pattern",
            required_input_traits=("closed_candidate",),
            fact_rule=rule_cut_circular_hole_pattern,
            risk_tags=("destructive", "many_boolean_ops"),
        ),
        OperationSemanticSpec(
            dialect="axisymmetric",
            op="cut_annular_groove",
            required_input_traits=("closed_candidate",),
            fact_rule=rule_cut_annular_groove,
            risk_tags=("destructive",),
        ),
        # ── sketch_extrude ──
        OperationSemanticSpec(
            dialect="sketch_extrude",
            op="extrude_rectangle",
            produced_traits=("prismatic", "rectangular"),
            fact_rule=rule_extrude_rectangle,
        ),
        # ── composition ──
        OperationSemanticSpec(
            dialect="composition",
            op="translate_solid",
            fact_rule=rule_translate_solid,
        ),
        OperationSemanticSpec(
            dialect="composition",
            op="boolean_union",
            fact_rule=rule_boolean_union,
            risk_tags=("may_fail_on_near_tangent",),
        ),
        OperationSemanticSpec(
            dialect="composition",
            op="boolean_cut",
            required_input_traits=("closed_candidate",),
            fact_rule=rule_boolean_cut,
            risk_tags=("destructive", "may_be_noop", "may_remove_entire_body"),
        ),
    ]

    for spec in _specs:
        key = (spec.dialect, spec.op, spec.op_version)
        SEMANTIC_SPECS[key] = spec


def get_semantic_spec(
    dialect: str, op: str, op_version: str = "1.0.0"
) -> OperationSemanticSpec | None:
    """Look up an OperationSemanticSpec by (dialect, op, version)."""
    _populate_semantic_specs()
    return SEMANTIC_SPECS.get((dialect, op, op_version))
