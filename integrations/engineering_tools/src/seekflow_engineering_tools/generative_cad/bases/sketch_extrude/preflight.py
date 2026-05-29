"""Geometry preflight checks for sketch_extrude_base operations."""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.legacy.preflight_v01 import DEFAULT_GEOMETRY_POLICY


def preflight_extrude_rectangle(node: dict, _all_nodes: list[dict]) -> list[dict]:
    """Preflight checks for extrude_rectangle."""
    issues: list[dict] = []
    params = node.get("params", {})
    w = params.get("width_mm", 0)
    h = params.get("height_mm", 0)
    d = params.get("depth_mm", 0)

    min_edge = DEFAULT_GEOMETRY_POLICY["min_edge_length_mm"]
    for name, val in [("width_mm", w), ("height_mm", h), ("depth_mm", d)]:
        if val < min_edge:
            issues.append({
                "code": "extrude_dimension_too_small",
                "message": f"{name}={val} below min edge length {min_edge}",
                "node_id": node.get("id"),
                "severity": "warning",
            })
    return issues


def preflight_cut_hole(node: dict, _all_nodes: list[dict]) -> list[dict]:
    """Preflight checks for cut_hole."""
    issues: list[dict] = []
    params = node.get("params", {})
    dia = params.get("diameter_mm", 0)
    if dia < DEFAULT_GEOMETRY_POLICY["min_edge_length_mm"]:
        issues.append({
            "code": "hole_diameter_too_small",
            "message": (
                f"Hole diameter {dia} below min edge length "
                f"{DEFAULT_GEOMETRY_POLICY['min_edge_length_mm']}."
            ),
            "node_id": node.get("id"),
            "severity": "warning",
        })
    return issues


def preflight_cut_hole_pattern_linear(node: dict, _all_nodes: list[dict]) -> list[dict]:
    """Preflight checks for cut_hole_pattern_linear."""
    issues: list[dict] = []
    params = node.get("params", {})
    dia = params.get("hole_dia_mm", 0)
    sx = params.get("spacing_x_mm", 0)
    sy = params.get("spacing_y_mm", 0)

    if dia >= sx or dia >= sy:
        issues.append({
            "code": "hole_spacing_too_small",
            "message": (
                f"Hole diameter {dia} >= spacing (sx={sx}, sy={sy}). Holes would overlap."
            ),
            "node_id": node.get("id"),
            "severity": "error",
        })

    return issues


SKETCH_EXTRUDE_PREFLIGHT_HANDLERS = {
    "extrude_rectangle": preflight_extrude_rectangle,
    "cut_rectangular_pocket": preflight_extrude_rectangle,
    "cut_hole": preflight_cut_hole,
    "cut_hole_pattern_linear": preflight_cut_hole_pattern_linear,
    "add_rectangular_boss": preflight_extrude_rectangle,
    "add_rib": lambda n, a: [],
    "apply_safe_fillet": lambda n, a: [],
    "apply_safe_chamfer": lambda n, a: [],
}
