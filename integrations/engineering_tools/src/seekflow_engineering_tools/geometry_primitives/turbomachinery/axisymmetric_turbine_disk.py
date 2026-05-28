from __future__ import annotations

import math
from typing import Any


KERNEL_NAME = "cadquery_axisymmetric_revolve_v0"
PRIMITIVE_NAME = "axisymmetric_turbine_disk"


def _hole_pattern_metadata(name: str, count: int, pcd_mm: float, dia_mm: float, axis: str) -> dict[str, Any]:
    return {
        "name": name,
        "count": int(count),
        "pcd_mm": float(pcd_mm),
        "hole_dia_mm": float(dia_mm),
        "axis": axis,
    }


def _cut_hole_ring(result, *, count: int, pcd_mm: float, hole_dia_mm: float, axis: str):
    if count == 0:
        return result

    if axis != "Z":
        raise ValueError(f"Only Z-axis through holes are supported in v0.1, got {axis!r}")

    radius = pcd_mm / 2.0

    return (
        result.faces(">Z")
        .workplane(centerOption="CenterOfBoundBox")
        .polarArray(radius, 0, 360, count)
        .hole(hole_dia_mm)
    )


def _reference_dimensions(params: dict) -> dict[str, Any]:
    return {
        "outer_dia_mm": float(params["outer_dia_mm"]),
        "bore_dia_mm": float(params["bore_dia_mm"]),
        "axial_width_mm": float(params["axial_width_mm"]),
        "hub_outer_dia_mm": float(params["hub_outer_dia_mm"]),
        "web_outer_dia_mm": float(params["web_outer_dia_mm"]),
        "rim_inner_dia_mm": float(params["rim_inner_dia_mm"]),
        "hub_width_mm": float(params["hub_width_mm"]),
        "web_width_mm": float(params["web_width_mm"]),
        "rim_width_mm": float(params["rim_width_mm"]),
        "bolt_hole_count": int(params["bolt_hole_count"]),
        "lightening_hole_count": int(params["lightening_hole_count"]),
        "cooling_hole_count": int(params["cooling_hole_count"]),
        "expected_through_hole_count": (
            1
            + int(params["bolt_hole_count"])
            + int(params["lightening_hole_count"])
            + int(params["cooling_hole_count"])
        ),
    }


def build_axisymmetric_turbine_disk_cadquery(params: dict):
    import cadquery as cq

    outer_d = float(params["outer_dia_mm"])
    bore_d = float(params["bore_dia_mm"])
    hub_d = float(params["hub_outer_dia_mm"])
    web_d = float(params["web_outer_dia_mm"])
    rim_inner_d = float(params["rim_inner_dia_mm"])

    hub_w = float(params["hub_width_mm"])
    web_w = float(params["web_width_mm"])
    rim_w = float(params["rim_width_mm"])

    r_bore = bore_d / 2.0
    r_hub = hub_d / 2.0
    r_web = web_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    r_outer = outer_d / 2.0

    t_hub = hub_w / 2.0
    t_web = web_w / 2.0
    t_rim = rim_w / 2.0

    profile_points = [
        (r_bore, -t_hub),
        (r_hub, -t_hub),
        (r_hub, -t_web),
        (r_web, -t_web),
        (r_rim_inner, -t_rim),
        (r_outer, -t_rim),
        (r_outer, t_rim),
        (r_rim_inner, t_rim),
        (r_web, t_web),
        (r_hub, t_web),
        (r_hub, t_hub),
        (r_bore, t_hub),
    ]

    result = (
        cq.Workplane("XZ")
        .polyline(profile_points)
        .close()
        .revolve()
    )

    result = _cut_hole_ring(
        result,
        count=int(params["bolt_hole_count"]),
        pcd_mm=float(params["bolt_pcd_mm"]),
        hole_dia_mm=float(params["bolt_hole_dia_mm"]),
        axis=str(params["bolt_hole_axis"]),
    )

    result = _cut_hole_ring(
        result,
        count=int(params["lightening_hole_count"]),
        pcd_mm=float(params["lightening_hole_pcd_mm"]),
        hole_dia_mm=float(params["lightening_hole_dia_mm"]),
        axis=str(params["lightening_hole_axis"]),
    )

    result = _cut_hole_ring(
        result,
        count=int(params["cooling_hole_count"]),
        pcd_mm=float(params["cooling_hole_pcd_mm"]),
        hole_dia_mm=float(params["cooling_hole_dia_mm"]),
        axis=str(params["cooling_hole_axis"]),
    )

    warnings: list[str] = [
        "axisymmetric_turbine_disk is non-flight reference geometry only.",
        "Not airworthy, not certified, not manufacturing-ready.",
        "No real fir-tree slots, blade attachment, material, stress, life, or cooling-flow validation is performed.",
    ]

    ref_dims = _reference_dimensions(params)

    metadata = {
        "primitive": PRIMITIVE_NAME,
        "metadata_version": "primitive_metadata_v1",
        "kernel": KERNEL_NAME,
        "parameters": dict(params),
        "reference_dimensions": ref_dims,
        "warnings": warnings,
        "radial_zones": {
            "bore_radius_mm": r_bore,
            "hub_outer_radius_mm": r_hub,
            "web_outer_radius_mm": r_web,
            "rim_inner_radius_mm": r_rim_inner,
            "outer_radius_mm": r_outer,
        },
        "profile_points": [[float(r), float(z)] for r, z in profile_points],
        "hole_patterns": [
            _hole_pattern_metadata(
                "bolt",
                int(params["bolt_hole_count"]),
                float(params["bolt_pcd_mm"]),
                float(params["bolt_hole_dia_mm"]),
                str(params["bolt_hole_axis"]),
            ),
            _hole_pattern_metadata(
                "lightening",
                int(params["lightening_hole_count"]),
                float(params["lightening_hole_pcd_mm"]),
                float(params["lightening_hole_dia_mm"]),
                str(params["lightening_hole_axis"]),
            ),
            _hole_pattern_metadata(
                "cooling",
                int(params["cooling_hole_count"]),
                float(params["cooling_hole_pcd_mm"]),
                float(params["cooling_hole_dia_mm"]),
                str(params["cooling_hole_axis"]),
            ),
        ],
        "safety": {
            "non_flight_reference_only": True,
            "not_for_manufacturing": True,
            "not_airworthy": True,
            "not_certified": True,
        },
    }

    return result, metadata
