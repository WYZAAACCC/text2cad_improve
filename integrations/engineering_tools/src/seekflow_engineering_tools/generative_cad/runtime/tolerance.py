"""Global geometry tolerance model — single source of truth for all precision decisions.

Replaces scattered hardcoded magic numbers (0.01mm in boolean fallback, etc.)
with a unified, auditable tolerance configuration.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class GeometryTolerance:
    """Global tolerance model for all geometry operations.

    All values in millimeters and degrees. Every handler and validator
    that needs a numeric tolerance MUST read from this object, never
    from a hardcoded literal.
    """

    # ── Core precision ──
    linear_mm: float = 0.01        # Linear tolerance for boolean ops, distance checks
    angular_deg: float = 0.1       # Angular tolerance for tangency/parallel checks
    fuzzy_zero_mm: float = 1e-6    # Threshold below which a dimension is considered zero

    # ── Geometry quality thresholds ──
    min_edge_length_mm: float = 0.25     # Edges shorter than this are degenerate
    min_wall_thickness_mm: float = 1.0   # Walls thinner than this may fail
    min_boolean_clearance_mm: float = 0.2  # Min gap for reliable boolean operations

    # ── Feature-specific ──
    max_fillet_ratio: float = 0.25       # Fillet radius / local thickness must be < this
    min_hole_to_boundary_margin_mm: float = 1.0

    # ── Safe defaults for common operations ──
    @property
    def boolean_fallback_tolerance(self) -> float:
        """Tolerance to use when first boolean attempt fails."""
        return self.linear_mm

    @property
    def chamfer_fallback_ratio(self) -> float:
        """Ratio to reduce chamfer distance on first failure."""
        return 0.5


# ── Singleton default ─────────────────────────────────────────────────────────

DEFAULT_TOLERANCE = GeometryTolerance()
