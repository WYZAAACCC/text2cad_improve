"""Sketch-extrude base contract — detailed op definitions for LLM graph authoring."""

SKETCH_EXTRUDE_CONTRACT = {
    "base_id": "sketch_extrude_base",
    "base_version": "0.1.0",
    "phase_order": [
        "base_solid",
        "primary_cut",
        "hole_pattern",
        "boss_rib",
        "edge_treatment",
        "cleanup",
    ],
    "allowed_ops": {
        "extrude_rectangle": {
            "phase": "base_solid",
            "description": "Create a rectangular prism by extruding a 2D rectangle.",
            "required_params": ["width_mm", "height_mm", "depth_mm"],
            "hard_constraints": [
                "width_mm > 0",
                "height_mm > 0",
                "depth_mm > 0",
                "plane one of XY, YZ, XZ",
            ],
        },
        "cut_rectangular_pocket": {
            "phase": "primary_cut",
            "description": "Cut a rectangular pocket into the solid.",
            "required_params": ["width_mm", "height_mm", "depth_mm"],
            "hard_constraints": [
                "width_mm > 0",
                "height_mm > 0",
                "depth_mm > 0",
            ],
        },
        "cut_hole": {
            "phase": "primary_cut",
            "description": "Cut a circular hole at a specified position.",
            "required_params": ["diameter_mm", "position_mm"],
            "hard_constraints": [
                "diameter_mm > 0",
                "position_mm must be length 2 or 3",
            ],
        },
        "cut_hole_pattern_linear": {
            "phase": "hole_pattern",
            "description": "Cut a rectangular grid pattern of holes.",
            "required_params": [
                "hole_dia_mm", "count_x", "count_y", "spacing_x_mm", "spacing_y_mm",
            ],
            "hard_constraints": [
                "hole_dia_mm > 0",
                "count_x between 1 and 20",
                "count_y between 1 and 20",
                "spacing_x_mm > 0",
                "spacing_y_mm > 0",
            ],
        },
        "add_rectangular_boss": {
            "phase": "boss_rib",
            "description": "Add a rectangular boss protruding from a face.",
            "required_params": ["width_mm", "height_mm", "depth_mm"],
            "hard_constraints": [
                "width_mm > 0",
                "height_mm > 0",
                "depth_mm > 0",
            ],
        },
        "add_rib": {
            "phase": "boss_rib",
            "description": "Add a reinforcing rib.",
            "required_params": ["thickness_mm", "height_mm", "length_mm", "direction"],
            "hard_constraints": [
                "thickness_mm > 0",
                "height_mm > 0",
                "length_mm > 0",
            ],
        },
        "apply_safe_fillet": {
            "phase": "edge_treatment",
            "description": "Apply a fillet to all external edges.",
            "required_params": ["radius_mm", "target"],
            "hard_constraints": [
                "radius_mm > 0",
                "target must be 'all_external_edges' in v0",
            ],
        },
        "apply_safe_chamfer": {
            "phase": "edge_treatment",
            "description": "Apply a chamfer to all external edges.",
            "required_params": ["distance_mm", "target"],
            "hard_constraints": [
                "distance_mm > 0",
                "target must be 'all_external_edges' in v0",
            ],
        },
    },
}
