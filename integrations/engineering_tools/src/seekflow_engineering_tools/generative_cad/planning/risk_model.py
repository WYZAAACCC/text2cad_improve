"""Risk model — thresholds and categories for planning analysis.

Phase 3: defines conservative thresholds for pattern sizes, operation counts,
and phase ordering checks. Thresholds are chosen to be safely below known
failure points observed in stress30 testing.
"""

from __future__ import annotations

from dataclasses import dataclass

# ═══════════════════════════════════════════════════════════════════════════════
# Pattern thresholds
# ═══════════════════════════════════════════════════════════════════════════════

# Hole count above which individual boolean cuts become slow/infeasible.
# Batch cut via compound is recommended.
HOLE_PATTERN_BATCH_THRESHOLD: int = 8

# Hole count above which compound batching is strongly recommended.
# Observed OCCT instability above ~120 individual cuts in stress30.
HOLE_PATTERN_LARGE_THRESHOLD: int = 120

# Maximum safe pattern instances (global cap, enforced by composition preflight).
MAX_PATTERN_INSTANCES: int = 360

# ═══════════════════════════════════════════════════════════════════════════════
# Operation count thresholds
# ═══════════════════════════════════════════════════════════════════════════════

# Number of destructive (cuts_material) ops in a single component
# above which batching or reordering should be considered.
MANY_DESTRUCTIVE_OPS_THRESHOLD: int = 32

# ═══════════════════════════════════════════════════════════════════════════════
# Phase ordering
# ═══════════════════════════════════════════════════════════════════════════════

# Edge treatment phases that should appear late in the operation sequence.
EDGE_TREATMENT_PHASES: set[str] = {"edge_treatment"}

# Destructive phases that edge treatment should ideally precede.
# (Edge treatment should come AFTER these phases.)
DESTRUCTIVE_PHASES: set[str] = {
    "primary_cut",
    "hole_pattern",
    "pattern_cut",
    "annular_detail",
    "rim_detail",
}


@dataclass(frozen=True)
class RiskCategory:
    """A named risk category with threshold and suggested action."""
    code: str
    severity: str  # "warning" or "info"
    threshold_description: str
    suggested_action: str


# ── Risk catalog ──

RISK_CATALOG: list[RiskCategory] = [
    RiskCategory(
        code="hole_pattern_should_batch",
        severity="info",
        threshold_description=f"cut_circular_hole_pattern count >= {HOLE_PATTERN_BATCH_THRESHOLD}",
        suggested_action=(
            "Use compound-based batch cut (boolean_batch.batch_cut) "
            "instead of sequential individual cuts to improve performance "
            "and reduce OCCT boolean failures."
        ),
    ),
    RiskCategory(
        code="large_pattern_risk",
        severity="warning",
        threshold_description=f"pattern count >= {HOLE_PATTERN_LARGE_THRESHOLD}",
        suggested_action=(
            "Reduce pattern count below 120 or split across multiple "
            "smaller patterns. Large patterns are slow and prone to "
            "OCCT instability."
        ),
    ),
    RiskCategory(
        code="many_destructive_ops",
        severity="warning",
        threshold_description=f">= {MANY_DESTRUCTIVE_OPS_THRESHOLD} cuts_material ops in a single component",
        suggested_action=(
            "Consider batching or reordering destructive operations. "
            "High counts of boolean cuts increase failure probability."
        ),
    ),
    RiskCategory(
        code="edge_treatment_too_early",
        severity="warning",
        threshold_description="edge_treatment phase op appears before subsequent destructive ops",
        suggested_action=(
            "Move edge treatment (chamfer/fillet) to a later phase. "
            "Edge treatments applied before destructive ops may be "
            "destroyed or cause downstream boolean failures."
        ),
    ),
]
