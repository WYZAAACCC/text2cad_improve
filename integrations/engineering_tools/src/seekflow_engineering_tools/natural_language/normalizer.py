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


# ── Natural language trigger words for primitives ──

PRIMITIVE_TRIGGER_WORDS: dict[str, list[str]] = {
    "involute_spur_gear": [
        "gear", "spur gear", "involute gear", "involute",
        "渐开线齿轮", "直齿轮", "模数", "压力角", "齿数",
        "gear tooth", "tooth profile", "pitch diameter",
    ],
}

# Words that explicitly signal legacy/demo gear (not engineering)
LEGACY_GEAR_WORDS = [
    "visual approximation", "demo gear", "star-like gear",
    "star polygon", "近似齿轮", "视觉齿轮",
]


def should_use_primitive(intent: dict) -> str | None:
    """Determine which primitive (if any) should be used based on NL intent.

    Returns primitive name or None.
    """
    text = intent.get("description", "") + " " + intent.get("user_text", "")
    text_lower = text.lower()

    # Check for explicit legacy/demo requests first
    for word in LEGACY_GEAR_WORDS:
        if word.lower() in text_lower:
            return None

    for primitive_name, triggers in PRIMITIVE_TRIGGER_WORDS.items():
        for trigger in triggers:
            if trigger.lower() in text_lower:
                return primitive_name

    return None


def rewrite_deprecated_recipes_to_primitives(spec: dict) -> dict:
    """Rewrite deprecated spur_gear recipe features to primitive involute_spur_gear.

    Returns a NEW spec dict with 'rewrite_warnings' added.
    Does not mutate the input spec.
    """
    import copy
    spec = copy.deepcopy(spec)
    warnings: list[str] = []
    features = spec.get("features", [])

    for feat in features:
        if feat.get("type") != "recipe":
            continue
        recipe_name = feat.get("recipe_name", "")

        if recipe_name == "spur_gear":
            params = feat.get("parameters", {})
            feat["type"] = "primitive"
            feat["primitive_name"] = "involute_spur_gear"
            feat.pop("recipe_name", None)

            # Map parameters
            if "placement" not in feat:
                feat["placement"] = {}
            if "operation" not in feat:
                feat["operation"] = "new_body"

            # Ensure default primitive params are set
            params.setdefault("pressure_angle_deg", 20.0)
            params.setdefault("addendum_coefficient", 1.0)
            params.setdefault("clearance_coefficient", 0.25)
            params.setdefault("profile_shift_coefficient", 0.0)
            params.setdefault("backlash_mm", 0.0)
            params.setdefault("root_fillet_radius_mm", 0.0)
            params.setdefault("quality_grade", "industrial_brep")

            warnings.append(
                "Recipe 'spur_gear' was rewritten to primitive 'involute_spur_gear'. "
                "Engineering-grade gears must use primitive involute_spur_gear."
            )

    spec["rewrite_warnings"] = warnings
    return spec
