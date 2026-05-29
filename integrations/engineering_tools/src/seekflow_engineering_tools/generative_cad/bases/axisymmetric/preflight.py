"""Geometry preflight checks for axisymmetric_base operations.

Runs lightweight geometric reasoning before CadQuery to catch hallucinated dimensions.
"""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.legacy.preflight_v01 import DEFAULT_GEOMETRY_POLICY


def _derive_outer_radius(nodes: list[dict]) -> float | None:
    """Derive outer radius from revolve_profile node if present."""
    for node in nodes:
        if node.get("op") != "revolve_profile":
            continue
        params = node.get("params", {})
        stations = params.get("profile_stations", [])
        if stations:
            return max(s.get("r_mm", 0) for s in stations)
    return None


def _derive_bore_radius(nodes: list[dict]) -> float | None:
    """Derive bore radius from cut_center_bore node if present."""
    for node in nodes:
        if node.get("op") != "cut_center_bore":
            continue
        dia = node.get("params", {}).get("diameter_mm", 0)
        if dia > 0:
            return dia / 2.0
    return None


def preflight_revolve_profile(node: dict, _all_nodes: list[dict]) -> list[dict]:
    """Preflight checks for revolve_profile operation."""
    issues: list[dict] = []
    params = node.get("params", {})
    stations = params.get("profile_stations", [])

    if len(stations) < 2:
        issues.append({
            "code": "revolve_too_few_stations",
            "message": "revolve_profile requires at least 2 profile stations.",
            "node_id": node.get("id"),
            "severity": "error",
        })
        return issues

    if len(stations) > DEFAULT_GEOMETRY_POLICY["max_profile_points"]:
        issues.append({
            "code": "revolve_too_many_stations",
            "message": (
                f"Profile station count {len(stations)} exceeds "
                f"max {DEFAULT_GEOMETRY_POLICY['max_profile_points']}."
            ),
            "node_id": node.get("id"),
            "severity": "error",
        })

    for i, s in enumerate(stations):
        r = s.get("r_mm", 0)
        if r <= 0:
            issues.append({
                "code": "revolve_non_positive_radius",
                "message": f"Station {i} radius must be positive, got {r}.",
                "node_id": node.get("id"),
                "severity": "error",
            })
        zf = s.get("z_front_mm", 0)
        zr = s.get("z_rear_mm", 0)
        if zf > zr:
            issues.append({
                "code": "revolve_z_inverted",
                "message": f"Station {i}: z_front_mm ({zf}) > z_rear_mm ({zr}).",
                "node_id": node.get("id"),
                "severity": "error",
            })

    return issues


def preflight_cut_center_bore(node: dict, all_nodes: list[dict]) -> list[dict]:
    """Preflight checks for cut_center_bore."""
    issues: list[dict] = []
    params = node.get("params", {})
    dia = params.get("diameter_mm", 0)

    outer_r = _derive_outer_radius(all_nodes)
    if outer_r is not None and dia / 2.0 >= outer_r:
        issues.append({
            "code": "bore_larger_than_outer",
            "message": (
                f"Bore radius {dia / 2.0} >= outer radius {outer_r}. "
                "Bore would consume the entire solid."
            ),
            "node_id": node.get("id"),
            "expected": f"< {outer_r}",
            "actual": dia / 2.0,
            "severity": "error",
        })

    if dia / 2.0 < DEFAULT_GEOMETRY_POLICY["min_wall_thickness_mm"]:
        issues.append({
            "code": "bore_too_small",
            "message": (
                f"Bore radius {dia / 2.0} below minimum wall thickness "
                f"{DEFAULT_GEOMETRY_POLICY['min_wall_thickness_mm']}."
            ),
            "node_id": node.get("id"),
            "severity": "warning",
        })

    return issues


def preflight_cut_circular_hole_pattern(node: dict, all_nodes: list[dict]) -> list[dict]:
    """Preflight checks for cut_circular_hole_pattern."""
    issues: list[dict] = []
    params = node.get("params", {})
    count = params.get("count", 0)
    pcd = params.get("pcd_mm", 0)
    hole_dia = params.get("hole_dia_mm", 0)

    hole_r = hole_dia / 2.0
    pcd_r = pcd / 2.0

    outer_r = _derive_outer_radius(all_nodes)

    if outer_r is not None:
        outer_margin = pcd_r + hole_r
        if outer_margin > outer_r - DEFAULT_GEOMETRY_POLICY["min_boolean_clearance_mm"]:
            issues.append({
                "code": "hole_pattern_outside_material",
                "message": (
                    f"PCD radius {pcd_r} + hole radius {hole_r} = {outer_margin} "
                    f"exceeds inferred outer radius margin "
                    f"(outer={outer_r}, margin={DEFAULT_GEOMETRY_POLICY['min_boolean_clearance_mm']})."
                ),
                "node_id": node.get("id"),
                "expected": f"<= {outer_r - DEFAULT_GEOMETRY_POLICY['min_boolean_clearance_mm']}",
                "actual": outer_margin,
                "severity": "error",
            })

    bore_r = _derive_bore_radius(all_nodes)
    if bore_r is not None and pcd_r - hole_r < bore_r + DEFAULT_GEOMETRY_POLICY["min_hole_to_boundary_margin_mm"]:
        issues.append({
            "code": "hole_pattern_intersects_bore",
            "message": (
                f"PCD radius {pcd_r} - hole radius {hole_r} = {pcd_r - hole_r} "
                f"is too close to bore radius {bore_r}."
            ),
            "node_id": node.get("id"),
            "severity": "error",
        })

    # Ligament check
    import math
    if count >= 2 and pcd_r > 0:
        ligament = 2 * math.pi * pcd_r / count - hole_dia
        if ligament < DEFAULT_GEOMETRY_POLICY["min_wall_thickness_mm"]:
            issues.append({
                "code": "hole_ligament_too_small",
                "message": (
                    f"Angular ligament between holes = {ligament:.2f} mm, "
                    f"below min {DEFAULT_GEOMETRY_POLICY['min_wall_thickness_mm']} mm."
                ),
                "node_id": node.get("id"),
                "severity": "error",
            })

    return issues


def preflight_cut_rim_slot_pattern(node: dict, all_nodes: list[dict]) -> list[dict]:
    """Preflight checks for cut_rim_slot_pattern."""
    issues: list[dict] = []
    params = node.get("params", {})
    slot_depth = params.get("slot_depth_mm", 0)
    slot_profile = params.get("slot_profile", {})
    stations = slot_profile.get("stations", [])

    outer_r = _derive_outer_radius(all_nodes)
    bore_r = _derive_bore_radius(all_nodes)

    if outer_r is not None and bore_r is not None:
        available_rim = outer_r - bore_r
        if slot_depth > available_rim - DEFAULT_GEOMETRY_POLICY["min_boolean_clearance_mm"]:
            issues.append({
                "code": "rim_slot_too_deep",
                "message": (
                    f"Slot depth {slot_depth} exceeds available rim thickness "
                    f"({available_rim}) minus margin."
                ),
                "node_id": node.get("id"),
                "severity": "error",
            })

    if len(stations) < 2:
        issues.append({
            "code": "rim_slot_too_few_stations",
            "message": "Slot profile requires at least 2 stations.",
            "node_id": node.get("id"),
            "severity": "error",
        })
    else:
        depths = [s.get("depth_mm", 0) for s in stations]
        if depths != sorted(depths):
            issues.append({
                "code": "rim_slot_depths_non_monotonic",
                "message": "Slot profile station depths must be nondecreasing.",
                "node_id": node.get("id"),
                "severity": "error",
            })

    return issues


def preflight_apply_safe_chamfer(node: dict, _all_nodes: list[dict]) -> list[dict]:
    """Preflight checks for apply_safe_chamfer."""
    issues: list[dict] = []
    params = node.get("params", {})
    distance = params.get("distance_mm", 0)
    if distance < DEFAULT_GEOMETRY_POLICY["min_edge_length_mm"]:
        issues.append({
            "code": "chamfer_below_min_edge",
            "message": (
                f"Chamfer distance {distance} below min edge length "
                f"{DEFAULT_GEOMETRY_POLICY['min_edge_length_mm']}."
            ),
            "node_id": node.get("id"),
            "severity": "warning",
        })
    return issues


AXISYMMETRIC_PREFLIGHT_HANDLERS = {
    "revolve_profile": preflight_revolve_profile,
    "cut_center_bore": preflight_cut_center_bore,
    "cut_annular_groove": lambda n, a: [],  # No geometry-level preflight beyond schema
    "cut_circular_hole_pattern": preflight_cut_circular_hole_pattern,
    "cut_rim_slot_pattern": preflight_cut_rim_slot_pattern,
    "apply_safe_chamfer": preflight_apply_safe_chamfer,
}
