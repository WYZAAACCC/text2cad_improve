"""Normalize raw natural-language modelling intent into CAD-IR."""

from __future__ import annotations


def detect_ambiguities(intent: dict) -> dict:
    """Check a partial intent for missing required dimensions.

    Returns a dict with *ambiguities* and *suggested_template*.
    """
    ambiguities: list[str] = []
    recipe = intent.get("suggested_template") or intent.get("recipe_name", "")

    required_params = {
        "flanged_hub": [
            "flange_dia_mm", "flange_thickness_mm", "hub_dia_mm",
            "hub_height_mm", "bore_dia_mm", "bolt_pcd_mm",
            "bolt_dia_mm", "bolt_count",
        ],
        "l_bracket": [
            "base_length_mm", "base_width_mm", "thickness_mm", "leg_height_mm",
        ],
        "block_with_hole": [
            "length_mm", "width_mm", "height_mm", "hole_dia_mm",
        ],
        "stepped_block": [
            "base_length_mm", "base_width_mm", "base_height_mm",
            "top_length_mm", "top_width_mm", "top_height_mm",
        ],
        "spur_gear": [
            "module_mm", "teeth", "face_width_mm", "bore_dia_mm",
        ],
        "box": [
            "length_mm", "width_mm", "height_mm",
        ],
    }

    params = intent.get("parameters", {})
    if recipe in required_params:
        for p in required_params[recipe]:
            if p not in params:
                ambiguities.append(f"缺少{recipe}参数: {p}")

    return {
        "ambiguities": ambiguities,
        "suggested_template": recipe or None,
    }
