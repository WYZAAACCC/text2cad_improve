"""Axisymmetric base contract — detailed op definitions for LLM graph authoring.

Does NOT include CadQuery code. LLM sees this to emit valid feature graphs.
"""

AXISYMMETRIC_CONTRACT = {
    "base_id": "axisymmetric_base",
    "base_version": "0.1.0",
    "phase_order": [
        "base_solid",
        "primary_cut",
        "annular_detail",
        "pattern_cut",
        "rim_detail",
        "edge_treatment",
        "cleanup",
    ],
    "allowed_ops": {
        "revolve_profile": {
            "phase": "base_solid",
            "description": "Create a rotational solid from radial-axial profile stations.",
            "required_params": ["axis", "profile_stations"],
            "hard_constraints": [
                "axis must be 'Z' in v0",
                "all radii must be positive",
                "z_front_mm <= z_rear_mm for each station",
                "profile_stations must contain at least 2 stations",
            ],
        },
        "cut_center_bore": {
            "phase": "primary_cut",
            "description": "Cut a coaxial cylindrical bore through the center.",
            "required_params": ["diameter_mm", "axis"],
            "hard_constraints": [
                "diameter_mm > 0",
                "axis must be 'Z' in v0",
            ],
        },
        "cut_annular_groove": {
            "phase": "annular_detail",
            "description": "Cut an annular groove on front or rear face.",
            "required_params": ["side", "inner_dia_mm", "outer_dia_mm", "depth_mm"],
            "hard_constraints": [
                "inner_dia_mm < outer_dia_mm",
                "inner_dia_mm > 0",
                "outer_dia_mm > 0",
                "depth_mm > 0",
            ],
        },
        "cut_circular_hole_pattern": {
            "phase": "pattern_cut",
            "description": "Cut a circular pattern of through holes along the Z axis.",
            "required_params": ["count", "pcd_mm", "hole_dia_mm", "axis", "through_all"],
            "hard_constraints": [
                "count between 2 and 240",
                "hole_dia_mm > 0",
                "pcd_mm > 0",
                "axis must be 'Z' in v0",
            ],
        },
        "cut_rim_slot_pattern": {
            "phase": "rim_detail",
            "description": "Cut a circular pattern of slots at the outer rim.",
            "required_params": ["count", "slot_depth_mm", "slot_profile"],
            "hard_constraints": [
                "count between 2 and 360",
                "slot_depth_mm > 0",
                "slot_profile stations must have nondecreasing depths",
                "at least 2 stations per slot profile",
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
