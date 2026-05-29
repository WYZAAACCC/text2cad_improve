"""Composition dialect manifest."""

COMPOSITION_MANIFEST = {
    "dialect_id": "composition",
    "version": "0.2.0",
    "summary": "Transform, pattern, and boolean operations across components. Does NOT create geometry.",
    "typical_use": "assembly composition, part placement, pattern generation",
    "main_ops": [
        "translate_solid", "rotate_solid", "place_component",
        "circular_pattern_component", "linear_pattern_component",
        "boolean_union", "boolean_cut",
    ],
    "unsupported": [
        "sketch", "profile", "loft", "sweep", "hole creation",
        "LLM calls", "raw Python eval",
    ],
}
