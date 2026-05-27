"""Validate involute spur gear parameters for engineering correctness."""

from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.gears.standards import (
    spur_gear_reference_dimensions,
)


def validate_involute_spur_gear_parameters(params: dict) -> list[str]:
    errors: list[str] = []

    m = float(params.get("module_mm", 0))
    z = int(params.get("teeth", 0))
    fw = float(params.get("face_width_mm", 0))
    bore = float(params.get("bore_dia_mm", 0.0))

    if m <= 0:
        errors.append("module_mm must be > 0")
    if z < 6:
        errors.append("teeth must be >= 6")
    if fw <= 0:
        errors.append("face_width_mm must be > 0")

    if errors:
        return errors

    dims = spur_gear_reference_dimensions(params)
    root_d = dims["root_diameter_mm"]
    pitch_d = dims["pitch_diameter_mm"]
    outer_d = dims["outer_diameter_mm"]
    base_d = dims["base_diameter_mm"]
    circular_pitch = dims["circular_pitch_mm"]
    backlash = float(params.get("backlash_mm", 0.0))

    if root_d <= 0:
        errors.append(f"root_diameter_mm ({root_d:.3f}) must be > 0")
    if not (root_d < pitch_d < outer_d):
        errors.append(
            f"Diameter ordering violated: root ({root_d:.3f}) < pitch ({pitch_d:.3f}) "
            f"< outer ({outer_d:.3f}) must hold"
        )
    if base_d > outer_d:
        errors.append(
            f"base_diameter_mm ({base_d:.3f}) must be <= outer_diameter_mm ({outer_d:.3f})"
        )

    if bore > 0 and bore >= root_d * 0.85:
        errors.append(
            f"bore_dia_mm ({bore:.3f}) must be < 0.85 * root_diameter_mm "
            f"({root_d * 0.85:.3f}) to avoid weakening the root"
        )

    if backlash >= circular_pitch * 0.25:
        errors.append(
            f"backlash_mm ({backlash:.3f}) must be < 0.25 * circular_pitch_mm "
            f"({circular_pitch * 0.25:.3f}) to ensure proper meshing"
        )

    return errors
