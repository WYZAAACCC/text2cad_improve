"""GeometricParameterSolver — deterministic constraint satisfaction.

When preflight detects geometrically impossible parameter combinations,
this solver computes minimal adjustments to restore feasibility.

Architecture: Solver runs BEFORE LLM retry. If it finds a solution,
the LLM never sees the infeasible parameters. If it can't find one,
it returns clear diagnostics for the repair hints system.

v6.2: Initial implementation handles axisymmetric hole pattern constraints.
      Future: expand to sketch_extrude envelope, loft_sweep path self-intersection.
"""

from __future__ import annotations
from typing import Any


def solve_hole_pattern_constraints(
    params: dict[str, Any],
    outer_radius: float | None = None,
    bore_dia: float | None = None,
    min_pcd: float | None = None,
    max_pcd: float | None = None,
    margin: float = 1.0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Find minimal parameter adjustments to satisfy hole pattern constraints.

    Constraints:
      min_pcd = bore_dia + hole_dia + 2*margin  (holes must not intersect bore)
      max_pcd = 2*outer_r - hole_dia - 2*margin (holes must fit within profile)

    Returns (adjusted_params, audit_entries).
    If already feasible, returns (params, []).
    If no feasible solution exists, returns (params, [error_entry]).
    """
    pcd = float(params.get("pcd_mm", 0))
    hole_dia = float(params.get("hole_dia_mm", 0))
    count = int(params.get("count", 0))

    # If we don't have enough data, compute what we can
    if outer_radius is None or bore_dia is None:
        return params, [{"error": "insufficient data for constraint solving"}]

    # Compute current feasible ranges
    if min_pcd is None:
        min_pcd = bore_dia + hole_dia + 2 * margin
    if max_pcd is None:
        max_pcd = 2 * outer_radius - hole_dia - 2 * margin

    # Already feasible?
    if min_pcd <= max_pcd and min_pcd <= pcd <= max_pcd:
        return params, []

    gap = min_pcd - max_pcd
    if gap <= 0 and (pcd < min_pcd or pcd > max_pcd):
        # PCD out of range but range is valid — just adjust PCD
        new_pcd = max(min_pcd, min(max_pcd, pcd))
        if new_pcd == pcd:
            new_pcd = (min_pcd + max_pcd) / 2  # center of feasible range
        return (
            {**params, "pcd_mm": round(new_pcd, 1)},
            [{"action": "adjust_pcd", "old": pcd, "new": round(new_pcd, 1),
              "reason": f"PCD adjusted to feasible range [{min_pcd:.0f}, {max_pcd:.0f}]mm"}],
        )

    # Gap > 0: wall too thin for holes — need multi-parameter adjustment
    strategies = []

    # Strategy A: Reduce hole diameter
    hole_reduction = gap / 2.0  # each mm hole reduction closes gap by 2mm
    new_hole_dia = hole_dia - hole_reduction
    if new_hole_dia >= 2.0:  # minimum practical hole diameter
        strategies.append({
            "name": "reduce_hole",
            "params": {**params, "hole_dia_mm": round(new_hole_dia, 1)},
            "changes": [{"param": "hole_dia_mm", "old": hole_dia, "new": round(new_hole_dia, 1)}],
            "delta": hole_reduction,
            "reason": f"Reduce hole_dia by {hole_reduction:.0f}mm (from {hole_dia:.0f} to {new_hole_dia:.0f})",
        })

    # Strategy B: Reduce bore diameter
    new_bore_dia = bore_dia - gap
    if new_bore_dia >= 2.0:
        best_pcd = (min_pcd + max_pcd - gap) / 2  # PCD that works with new bore
        if best_pcd > 0:
            strategies.append({
                "name": "reduce_bore",
                "params": {**params, "pcd_mm": round(best_pcd, 1)},
                "bore_changes": [{"param": "bore_dia", "old": bore_dia, "new": round(new_bore_dia, 1)},
                                 {"param": "pcd_mm", "old": pcd, "new": round(best_pcd, 1)}],
                "delta": gap,
                "reason": f"Reduce bore_dia by {gap:.0f}mm (to {new_bore_dia:.0f}) + adjust PCD to {best_pcd:.0f}",
            })

    # Strategy C: Increase outer radius
    outer_increase = gap / 2.0
    new_outer_r = outer_radius + outer_increase
    strategies.append({
        "name": "increase_outer",
        "params": params,  # params don't change (outer_r is in revolve_profile)
        "profile_changes": [{"param": "profile_max_radius", "old": outer_radius, "new": round(new_outer_r, 1)}],
        "delta": outer_increase,
        "reason": f"Increase outer radius by {outer_increase:.0f}mm (to {new_outer_r:.0f})",
    })

    # Select best strategy: minimum delta (smallest change)
    strategies.sort(key=lambda s: s["delta"])
    best = strategies[0]

    # Build audit trail
    audit = []
    for change in best.get("changes", []):
        audit.append({
            "action": f"solver_{best['name']}",
            "param": change["param"],
            "old_value": change["old"],
            "new_value": change["new"],
            "reason": best["reason"],
            "confidence": 0.95,
            "category": "context_safe",
        })
    for change in best.get("bore_changes", []):
        audit.append({
            "action": f"solver_{best['name']}_bore",
            "param": change["param"],
            "old_value": change["old"],
            "new_value": change["new"],
            "reason": best["reason"],
            "confidence": 0.95,
            "category": "context_safe",
            "note": "The bore diameter is in cut_center_bore params, not hole_pattern params. Apply separately.",
        })
    for change in best.get("profile_changes", []):
        audit.append({
            "action": f"solver_{best['name']}_profile",
            "param": change["param"],
            "old_value": change["old"],
            "new_value": change["new"],
            "reason": best["reason"],
            "confidence": 0.90,
            "category": "context_safe",
            "note": "Outer radius is in revolve_profile params. Adjust profile_stations r_mm values.",
        })

    if best["name"] != "increase_outer":
        return best["params"], audit
    else:
        # Profile change needs special handling — return params unchanged
        # but with audit trail explaining what profile change is needed
        return params, audit


def apply_hole_pattern_solution(
    raw_doc: dict,
    node_id: str,
    solution_params: dict,
    audit_entries: list[dict],
) -> dict:
    """Apply the solver's solution to the raw document.

    Modifies the specific node's params with solved values.
    Also handles cross-node changes (bore adjustment on cut_center_bore node).
    """
    # Apply hole pattern params
    for node in raw_doc.get("nodes", []):
        if node.get("id") == node_id:
            for key in ("pcd_mm", "hole_dia_mm"):
                if key in solution_params:
                    node.setdefault("params", {})[key] = solution_params[key]

    # Apply bore changes if present
    for entry in audit_entries:
        if "bore" in entry.get("action", "") and entry["param"] == "bore_dia":
            new_bore = entry["new_value"]
            # Find the cut_center_bore node in the same component
            target_comp = None
            for node in raw_doc.get("nodes", []):
                if node.get("id") == node_id:
                    target_comp = node.get("component")
                    break
            if target_comp:
                for node in raw_doc.get("nodes", []):
                    if node.get("component") == target_comp and node.get("op") == "cut_center_bore":
                        node.setdefault("params", {})["diameter_mm"] = new_bore
                        break

    return raw_doc
