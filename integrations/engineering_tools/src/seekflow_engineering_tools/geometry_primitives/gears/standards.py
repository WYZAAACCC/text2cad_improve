"""Standard involute spur gear dimension calculations per ISO 53 / DIN 867."""

from __future__ import annotations

import math


def spur_gear_reference_dimensions(params: dict) -> dict:
    m = float(params["module_mm"])
    z = int(params["teeth"])
    alpha = float(params.get("pressure_angle_deg", 20.0))
    ha = float(params.get("addendum_coefficient", 1.0))
    c = float(params.get("clearance_coefficient", 0.25))
    x = float(params.get("profile_shift_coefficient", 0.0))
    backlash = float(params.get("backlash_mm", 0.0))

    alpha_rad = math.radians(alpha)
    pitch_diameter_mm = m * z
    base_diameter_mm = pitch_diameter_mm * math.cos(alpha_rad)
    outer_diameter_mm = m * (z + 2.0 * (ha + x))
    root_diameter_mm = pitch_diameter_mm - 2.0 * m * (ha + c - x)
    circular_pitch_mm = math.pi * m
    tooth_thickness_pitch_mm = circular_pitch_mm / 2.0 - backlash

    face_width = float(params.get("face_width_mm", 0))
    bore_dia = float(params.get("bore_dia_mm", 0))

    return {
        "module_mm": m,
        "teeth": z,
        "pressure_angle_deg": alpha,
        "face_width_mm": face_width,
        "bore_dia_mm": bore_dia,
        "pitch_diameter_mm": pitch_diameter_mm,
        "base_diameter_mm": base_diameter_mm,
        "outer_diameter_mm": outer_diameter_mm,
        "root_diameter_mm": root_diameter_mm,
        "circular_pitch_mm": circular_pitch_mm,
        "tooth_thickness_pitch_mm": tooth_thickness_pitch_mm,
    }
