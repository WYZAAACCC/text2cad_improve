"""ANSYS 18.1 APDL template schema registry and parameter validation."""

from __future__ import annotations

from typing import Any

ANSYS_TEMPLATE_SCHEMAS: dict[str, dict[str, Any]] = {
    "static_cantilever_beam_rect": {
        "analysis_type": "static_structural",
        "units": "mm,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "required": True, "min": 1},
            "width_mm": {"type": "float", "required": True, "min": 0.1},
            "height_mm": {"type": "float", "required": True, "min": 0.1},
            "force_n": {"type": "float", "required": True},
            "element_size_mm": {"type": "float", "required": False, "default": 10.0},
        },
        "metrics": ["max_displacement_mm", "max_von_mises_mpa"],
    },
    "plate_with_hole_tension": {
        "analysis_type": "static_structural",
        "units": "mm,N,MPa",
        "parameters": {
            "plate_width_mm": {"type": "float", "default": 200.0},
            "plate_height_mm": {"type": "float", "default": 100.0},
            "plate_thickness_mm": {"type": "float", "default": 10.0},
            "hole_diameter_mm": {"type": "float", "default": 20.0},
            "tensile_stress_mpa": {"type": "float", "default": 100.0},
            "element_size_mm": {"type": "float", "default": 5.0},
        },
        "metrics": ["max_von_mises_mpa", "stress_concentration_factor"],
    },
    "beam_thermal": {
        "analysis_type": "thermal_steady",
        "units": "mm,C,W",
        "parameters": {
            "length_mm": {"type": "float", "default": 200.0},
            "width_mm": {"type": "float", "default": 20.0},
            "height_mm": {"type": "float", "default": 20.0},
            "temp_left_c": {"type": "float", "default": 100.0},
            "temp_right_c": {"type": "float", "default": 0.0},
            "ambient_temp_c": {"type": "float", "default": 25.0},
            "element_size_mm": {"type": "float", "default": 5.0},
        },
        "metrics": ["tmin_c", "tmax_c", "tmid_c"],
    },
    "cantilever_modal": {
        "analysis_type": "modal",
        "units": "mm,tonne,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "default": 200.0},
            "width_mm": {"type": "float", "default": 20.0},
            "height_mm": {"type": "float", "default": 20.0},
            "young_mpa": {"type": "float", "default": 210000.0},
            "density_kgmm3": {"type": "float", "default": 7.85e-6},
            "poisson": {"type": "float", "default": 0.3},
            "n_modes": {"type": "int", "default": 5},
            "element_size_mm": {"type": "float", "default": 10.0},
        },
        "metrics": ["modal_frequencies_hz"],
    },
    "buckling_column": {
        "analysis_type": "buckling",
        "units": "mm,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "default": 500.0},
            "width_mm": {"type": "float", "default": 20.0},
            "height_mm": {"type": "float", "default": 20.0},
            "young_mpa": {"type": "float", "default": 210000.0},
            "poisson": {"type": "float", "default": 0.3},
            "element_size_mm": {"type": "float", "default": 10.0},
        },
        "metrics": ["buckling_load_factor", "pcr_n"],
    },
    "bilinear_plastic": {
        "analysis_type": "bilinear_plastic",
        "units": "mm,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "default": 100.0},
            "width_mm": {"type": "float", "default": 10.0},
            "height_mm": {"type": "float", "default": 10.0},
            "young_mpa": {"type": "float", "default": 210000.0},
            "yield_stress_mpa": {"type": "float", "default": 235.0},
            "tangent_modulus_mpa": {"type": "float", "default": 2100.0},
            "displacement_mm": {"type": "float", "default": 5.0},
            "element_size_mm": {"type": "float", "default": 5.0},
            "n_substeps": {"type": "int", "default": 20},
        },
        "metrics": ["max_plastic_strain", "tip_displacement_mm"],
    },
}


def validate_template_parameters(template_name: str, parameters: dict) -> dict:
    """Validate and fill defaults for a named template's parameters.

    Returns the complete parameter dict with defaults applied.
    Raises ValueError if the template is unknown or required params are missing.
    """
    if template_name not in ANSYS_TEMPLATE_SCHEMAS:
        available = sorted(ANSYS_TEMPLATE_SCHEMAS.keys())
        raise ValueError(
            f"Unknown template '{template_name}'. Available: {available}"
        )

    schema = ANSYS_TEMPLATE_SCHEMAS[template_name]
    validated: dict = {}

    for pname, pinfo in schema["parameters"].items():
        if pname in parameters:
            validated[pname] = parameters[pname]
        elif pinfo.get("required", False):
            raise ValueError(
                f"Template '{template_name}' requires parameter '{pname}'"
            )
        elif "default" in pinfo:
            validated[pname] = pinfo["default"]

    return validated
