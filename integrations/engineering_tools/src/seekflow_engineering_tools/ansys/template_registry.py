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
            "element_size_mm": {"type": "float", "required": False, "default": 10.0, "min": 0.01},
        },
        "metrics": ["max_displacement_mm", "max_von_mises_mpa"],
    },
    "plate_with_hole_tension": {
        "analysis_type": "static_structural",
        "units": "mm,N,MPa",
        "parameters": {
            "plate_width_mm": {"type": "float", "default": 200.0, "min": 1},
            "plate_height_mm": {"type": "float", "default": 100.0, "min": 1},
            "plate_thickness_mm": {"type": "float", "default": 10.0, "min": 0.1},
            "hole_diameter_mm": {"type": "float", "default": 20.0, "min": 0.1},
            "tensile_stress_mpa": {"type": "float", "default": 100.0},
            "element_size_mm": {"type": "float", "default": 5.0, "min": 0.01},
        },
        "metrics": ["max_von_mises_mpa", "stress_concentration_factor"],
        "geometry_constraints": [
            {"rule": "hole_diameter_mm < plate_width_mm",
             "message": "Hole diameter must be less than plate width."},
            {"rule": "hole_diameter_mm < plate_height_mm",
             "message": "Hole diameter must be less than plate height."},
        ],
    },
    "beam_thermal": {
        "analysis_type": "thermal_steady",
        "units": "mm,C,W",
        "parameters": {
            "length_mm": {"type": "float", "default": 200.0, "min": 1},
            "width_mm": {"type": "float", "default": 20.0, "min": 0.1},
            "height_mm": {"type": "float", "default": 20.0, "min": 0.1},
            "temp_left_c": {"type": "float", "default": 100.0},
            "temp_right_c": {"type": "float", "default": 0.0},
            "ambient_temp_c": {"type": "float", "default": 25.0},
            "element_size_mm": {"type": "float", "default": 5.0, "min": 0.01},
        },
        "metrics": ["tmin_c", "tmax_c", "tmid_c"],
    },
    "cantilever_modal": {
        "analysis_type": "modal",
        "units": "mm,tonne,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "default": 200.0, "min": 1},
            "width_mm": {"type": "float", "default": 20.0, "min": 0.1},
            "height_mm": {"type": "float", "default": 20.0, "min": 0.1},
            "young_mpa": {"type": "float", "default": 210000.0, "min": 1},
            "density_kgmm3": {"type": "float", "default": 7.85e-6, "min": 1e-12},
            "poisson": {"type": "float", "default": 0.3, "min": 0.0, "max": 0.49},
            "n_modes": {"type": "int", "default": 5, "min": 1, "max": 100},
            "element_size_mm": {"type": "float", "default": 10.0, "min": 0.01},
        },
        "metrics": ["modal_frequencies_hz", "mode_1_hz", "mode_2_hz", "mode_3_hz"],
    },
    "buckling_column": {
        "analysis_type": "buckling",
        "units": "mm,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "default": 500.0, "min": 1},
            "width_mm": {"type": "float", "default": 20.0, "min": 0.1},
            "height_mm": {"type": "float", "default": 20.0, "min": 0.1},
            "young_mpa": {"type": "float", "default": 210000.0, "min": 1},
            "poisson": {"type": "float", "default": 0.3, "min": 0.0, "max": 0.49},
            "element_size_mm": {"type": "float", "default": 10.0, "min": 0.01},
        },
        "metrics": ["buckling_load_factor", "pcr_n"],
    },
    "bilinear_plastic": {
        "analysis_type": "bilinear_plastic",
        "units": "mm,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "default": 100.0, "min": 1},
            "width_mm": {"type": "float", "default": 10.0, "min": 0.1},
            "height_mm": {"type": "float", "default": 10.0, "min": 0.1},
            "young_mpa": {"type": "float", "default": 210000.0, "min": 1},
            "yield_stress_mpa": {"type": "float", "default": 235.0, "min": 0.1},
            "tangent_modulus_mpa": {"type": "float", "default": 2100.0, "min": 0.1},
            "displacement_mm": {"type": "float", "default": 5.0, "min": 0.001},
            "element_size_mm": {"type": "float", "default": 5.0, "min": 0.01},
            "n_substeps": {"type": "int", "default": 20, "min": 1, "max": 1000},
        },
        "metrics": ["max_plastic_strain", "tip_displacement_mm"],
    },
    "turbine_disc_rotational_thermal": {
        "analysis_type": "thermo_structural_axisymmetric",
        "units": "mm,tonne,N,MPa,C",
        "parameters": {
            "step_file_path": {"type": "str", "default": ""},
            "rpm": {"type": "float", "default": 15000.0, "min": 100},
            "temp_rim_c": {"type": "float", "default": 650.0, "min": 20},
            "temp_bore_c": {"type": "float", "default": 500.0, "min": 20},
            "young_rim_mpa": {"type": "float", "default": 150000.0},
            "young_bore_mpa": {"type": "float", "default": 175000.0},
            "yield_mpa_650c": {"type": "float", "default": 900.0},
            "density_tonnemm3": {"type": "float", "default": 8.24e-9},
            "poisson": {"type": "float", "default": 0.3},
            "alpha": {"type": "float", "default": 1.45e-5},
            "element_size_mm": {"type": "float", "default": 5.0, "min": 0.5},
            "n_slots": {"type": "int", "default": 60, "min": 1},
            "slot_depth_mm": {"type": "float", "default": 20.0},
        },
        "metrics": [
            "max_von_mises_mpa", "max_radial_stress_mpa", "max_hoop_stress_mpa",
            "min_safety_factor",
        ],
    },
}


def list_template_names() -> list[str]:
    return sorted(ANSYS_TEMPLATE_SCHEMAS.keys())


def get_template_schema(template_name: str) -> dict | None:
    return ANSYS_TEMPLATE_SCHEMAS.get(template_name)


def validate_template_parameters(template_name: str, parameters: dict) -> dict:
    """Validate and fill defaults for a named template's parameters.

    Checks: unknown params (reject), required params, type coercion,
    min/max constraints, geometry constraints.
    Returns the complete parameter dict with defaults applied.
    Raises ValueError if the template is unknown or validation fails.
    """
    if template_name not in ANSYS_TEMPLATE_SCHEMAS:
        available = sorted(ANSYS_TEMPLATE_SCHEMAS.keys())
        raise ValueError(
            f"Unknown template '{template_name}'. Available: {available}"
        )

    schema = ANSYS_TEMPLATE_SCHEMAS[template_name]
    errors: list[str] = []

    # Check for unknown parameters
    known_params = set(schema["parameters"].keys())
    for key in parameters:
        if key not in known_params:
            errors.append(
                f"Unknown parameter '{key}' for template '{template_name}'. "
                f"Allowed: {sorted(known_params)}"
            )

    validated: dict = {}

    for pname, pinfo in schema["parameters"].items():
        expected_type = pinfo["type"]

        if pname in parameters:
            value = parameters[pname]

            # Type validation
            if expected_type == "float":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    errors.append(
                        f"Parameter '{pname}' must be float, got {type(value).__name__}: {value}"
                    )
                else:
                    validated[pname] = float(value)
            elif expected_type == "int":
                if isinstance(value, bool):
                    errors.append(
                        f"Parameter '{pname}' must be int, got bool: {value}"
                    )
                elif not isinstance(value, int):
                    errors.append(
                        f"Parameter '{pname}' must be int, got {type(value).__name__}: {value}"
                    )
                else:
                    validated[pname] = int(value)
            elif expected_type == "str":
                if not isinstance(value, str):
                    errors.append(
                        f"Parameter '{pname}' must be str, got {type(value).__name__}: {value}"
                    )
                else:
                    validated[pname] = value
            elif expected_type == "bool":
                validated[pname] = bool(value)

            # Min/max validation for numeric types
            if pname in validated and expected_type in ("float", "int"):
                v = float(validated[pname])
                if "min" in pinfo and v < pinfo["min"]:
                    errors.append(
                        f"Parameter '{pname}' value {v} < min {pinfo['min']}"
                    )
                if "max" in pinfo and v > pinfo["max"]:
                    errors.append(
                        f"Parameter '{pname}' value {v} > max {pinfo['max']}"
                    )

        elif pinfo.get("required", False):
            errors.append(
                f"Template '{template_name}' requires parameter '{pname}'"
            )
        elif "default" in pinfo:
            validated[pname] = pinfo["default"]

    if errors:
        raise ValueError("; ".join(errors))

    # Geometry constraint validation
    _validate_template_constraints(template_name, validated)

    return validated


def _validate_template_constraints(template_name: str, params: dict) -> None:
    """Check geometry-specific constraints for a template."""
    schema = ANSYS_TEMPLATE_SCHEMAS.get(template_name, {})
    constraints = schema.get("geometry_constraints", [])

    for constraint in constraints:
        rule = constraint.get("rule", "")
        message = constraint.get("message", "Geometry constraint violated")

        try:
            # Safe eval using only the params dict
            if not eval(rule, {"__builtins__": {}}, params):
                raise ValueError(message)
        except NameError:
            pass  # Rule references a parameter not in params — skip
        except Exception:
            raise ValueError(message) from None
