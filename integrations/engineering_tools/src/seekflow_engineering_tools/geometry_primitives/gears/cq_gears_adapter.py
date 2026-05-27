"""CQ_Gears adapter — deterministic involute spur gear kernel.

This is the PRIMARY gear kernel. LLM must NEVER generate involute curves directly.
"""

from __future__ import annotations


def cq_gears_available() -> bool:
    try:
        import cq_gears  # noqa: F401
        return True
    except ImportError:
        return False


def build_involute_spur_gear_cq_gears(params: dict):
    """Build an involute spur gear using the CQ_Gears deterministic kernel.

    Returns (cadquery.Workplane, metadata_dict).

    The metadata dict MUST contain:
      - kernel: "cq_gears"
      - is_standard_involute: True
      - parameters: the normalized parameters
      - reference_dimensions: computed dimensions
    """
    from seekflow_engineering_tools.geometry_primitives.gears.validator import (
        validate_involute_spur_gear_parameters,
    )
    from seekflow_engineering_tools.geometry_primitives.gears.standards import (
        spur_gear_reference_dimensions,
    )

    errors = validate_involute_spur_gear_parameters(params)
    if errors:
        raise ValueError("Gear parameter validation failed: " + "; ".join(errors))

    import cadquery as cq
    import cq_gears

    m = float(params["module_mm"])
    z = int(params["teeth"])
    fw = float(params["face_width_mm"])
    bore = float(params.get("bore_dia_mm", 0.0))
    alpha = float(params.get("pressure_angle_deg", 20.0))

    spur_gear = cq_gears.SpurGear(
        module=m,
        teeth_number=z,
        width=fw,
        bore_d=bore if bore > 0 else None,
        pressure_angle=alpha,
    )

    result = cq.Workplane("XY").gear(spur_gear)

    dims = spur_gear_reference_dimensions(params)
    metadata = {
        "kernel": "cq_gears",
        "is_standard_involute": True,
        "primitive": "involute_spur_gear",
        "parameters": {k: v for k, v in params.items()},
        "reference_dimensions": dims,
    }

    return result, metadata
