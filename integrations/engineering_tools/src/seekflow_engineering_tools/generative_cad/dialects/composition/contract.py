"""Composition dialect contract."""

COMPOSITION_CONTRACT = {
    "dialect_id": "composition",
    "version": "0.2.0",
    "phase_order": ["transform", "pattern", "boolean", "export"],
    "allowed_ops": {
        "translate_solid": {
            "phase": "transform",
            "description": "Translate a solid by a vector.",
            "required_params": ["vector_mm"],
            "hard_constraints": ["vector_mm must be (x, y, z) in mm"],
        },
        "rotate_solid": {
            "phase": "transform",
            "description": "Rotate a solid around an axis.",
            "required_params": ["axis_dir", "angle_deg"],
        },
        "place_component": {
            "phase": "transform",
            "description": "Place a component at a position.",
            "required_params": ["position_mm"],
        },
        "circular_pattern_component": {
            "phase": "pattern",
            "description": "Create a circular pattern of a component.",
            "required_params": ["count", "radius_mm"],
        },
        "linear_pattern_component": {
            "phase": "pattern",
            "description": "Create a linear pattern of a component.",
            "required_params": ["count", "spacing_mm", "direction"],
        },
        "boolean_union": {
            "phase": "boolean",
            "description": "Union multiple solid bodies.",
            "required_params": [],
        },
        "boolean_cut": {
            "phase": "boolean",
            "description": "Cut tool solids from target solid.",
            "required_params": [],
        },
    },
    "unsupported": [
        "sketch", "profile", "loft", "sweep",
        "hole semantics", "LLM calls", "raw Python eval",
    ],
}
