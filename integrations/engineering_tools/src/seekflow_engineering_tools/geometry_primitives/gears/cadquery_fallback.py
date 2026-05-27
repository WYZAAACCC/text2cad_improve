"""CadQuery visual fallback gear — NOT certified involute geometry.

This is a VISUAL APPROXIMATION only. Must ALWAYS emit warnings and set
is_standard_involute=False in metadata.
"""

from __future__ import annotations

import math


def build_visual_spur_gear_fallback(params: dict):
    """Build an approximate visual spur gear using CadQuery polyline extrusion.

    WARNING: This is NOT a certified involute profile. Use only when CQ_Gears
    is unavailable, and ALWAYS propagate the warning to the user.

    Returns (cadquery.Workplane, metadata_dict).
    """
    from seekflow_engineering_tools.geometry_primitives.gears.standards import (
        spur_gear_reference_dimensions,
    )

    import cadquery as cq

    m = float(params["module_mm"])
    z = int(params["teeth"])
    fw = float(params["face_width_mm"])
    bore = float(params.get("bore_dia_mm", 0.0))

    pitch_r = m * z / 2.0
    outer_r = pitch_r + m
    root_r = pitch_r - 1.25 * m

    pts = []
    for i in range(z):
        c = 2.0 * math.pi * i / z
        pts.append((outer_r * math.cos(c), outer_r * math.sin(c)))
        pts.append((root_r * math.cos(c + math.pi / z), root_r * math.sin(c + math.pi / z)))
    pts.append(pts[0])

    gear = cq.Workplane("XY").polyline(pts).close().extrude(fw)

    if bore > 0:
        result = gear.faces(">Z").workplane().hole(bore)
    else:
        result = gear

    dims = spur_gear_reference_dimensions(params)
    warnings_list = [
        "cq_gears is not available; generated approximate visual fallback gear.",
        "This fallback is NOT certified involute geometry.",
    ]

    metadata = {
        "kernel": "cadquery_visual_fallback",
        "is_standard_involute": False,
        "primitive": "involute_spur_gear",
        "parameters": {k: v for k, v in params.items()},
        "reference_dimensions": dims,
        "warnings": warnings_list,
    }

    return result, metadata
