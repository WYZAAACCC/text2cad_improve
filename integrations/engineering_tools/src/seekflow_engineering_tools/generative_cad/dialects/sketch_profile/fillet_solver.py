"""Fillet feasibility pre-check — validate that requested radii fit within edge lengths.

Prevents OCC BRep_API failures by catching infeasible fillets before any
geometry kernel call. Uses the semantic ProfileGraph for stable edge/corner
identification.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from seekflow_engineering_tools.generative_cad.dialects.sketch_profile.profile_graph import (
    ProfileGraph,
)


@dataclass
class FilletFeasibilityReport:
    """Per-corner feasibility assessment."""

    corner_id: str
    feasible: bool
    radius_mm: float
    trim_length_mm: float | None = None

    # Edge budget check
    edge_id: str | None = None
    edge_length_mm: float | None = None
    required_length_mm: float | None = None

    suggested_max_radius_mm: float | None = None
    error_code: str | None = None


@dataclass
class FilletBudgetReport:
    """Full feasibility report for a set of fillet targets on a wire."""

    wire_id: str
    targets: list[FilletFeasibilityReport] = field(default_factory=list)
    all_feasible: bool = True

    @property
    def infeasible(self) -> list[FilletFeasibilityReport]:
        return [t for t in self.targets if not t.feasible]

    @property
    def constrained_edge_ids(self) -> set[str]:
        """Edge IDs that appear in any infeasible report."""
        return {t.edge_id for t in self.infeasible if t.edge_id}


def check_fillet_feasibility(
    graph: ProfileGraph,
    wire_id: str | None,
    corners: list[dict],
) -> FilletBudgetReport:
    """Check whether all fillet radii are geometrically feasible.

    Each *corner* dict must contain:
    - corner_id: str
    - between_segments: (edge_a_id, edge_b_id)
    - radius_mm: float > 0
    - expected_convexity: "convex" | "concave" | "either" (optional)

    Returns a report listing every target and whether it can be constructed
    without violating adjacent edge lengths.
    """
    reports: list[FilletFeasibilityReport] = []
    wire = graph.resolve_wire(wire_id)
    all_feasible = True

    # Accumulate trim-length demands per edge (edges may be shared by two corners)
    edge_demand: dict[str, float] = {}

    for c in corners:
        corner_id = c["corner_id"]
        e1, e2 = c["between_segments"]
        radius = float(c["radius_mm"])
        feasible = True

        try:
            angle = graph.interior_angle_rad(e1, e2, wire_id)
        except (ValueError, KeyError) as exc:
            reports.append(FilletFeasibilityReport(
                corner_id=corner_id, feasible=False, radius_mm=radius,
                error_code="CORNER_NOT_FOUND",
            ))
            all_feasible = False
            continue

        if angle < 0.01 or angle > math.pi - 0.01:
            reports.append(FilletFeasibilityReport(
                corner_id=corner_id, feasible=False, radius_mm=radius,
                error_code="CORNER_NEARLY_COLLINEAR",
            ))
            all_feasible = False
            continue

        trim = radius / math.tan(angle / 2.0)

        # Check each adjacent edge
        for eid in (e1, e2):
            try:
                length = graph.edge_length(eid)
            except KeyError:
                reports.append(FilletFeasibilityReport(
                    corner_id=corner_id, feasible=False, radius_mm=radius,
                    edge_id=eid, error_code="EDGE_NOT_FOUND",
                ))
                all_feasible = False
                continue

            demand = edge_demand.get(eid, 0.0) + trim
            if demand >= length - 1e-6:
                feasible = False
                # Compute the max radius this edge can support
                max_r = (length - edge_demand.get(eid, 0.0)) * math.tan(angle / 2.0)
                reports.append(FilletFeasibilityReport(
                    corner_id=corner_id, feasible=False, radius_mm=radius,
                    trim_length_mm=trim, edge_id=eid,
                    edge_length_mm=length,
                    required_length_mm=demand,
                    suggested_max_radius_mm=round(max_r, 4),
                    error_code="FILLET_SHARED_EDGE_TOO_SHORT",
                ))
                all_feasible = False
            else:
                edge_demand[eid] = demand

        if feasible:
            reports.append(FilletFeasibilityReport(
                corner_id=corner_id, feasible=True, radius_mm=radius,
                trim_length_mm=trim,
            ))

    return FilletBudgetReport(
        wire_id=wire.wire_id,
        targets=reports,
        all_feasible=all_feasible,
    )
