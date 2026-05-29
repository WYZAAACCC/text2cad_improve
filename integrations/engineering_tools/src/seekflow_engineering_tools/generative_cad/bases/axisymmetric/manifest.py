"""Axisymmetric base manifest — small, always safe to include in LLM prompt."""

AXISYMMETRIC_MANIFEST = {
    "base_id": "axisymmetric_base",
    "base_version": "0.1.0",
    "summary": (
        "For rotationally symmetric solids generated from radial-axial profiles, "
        "with optional coaxial bores, grooves, circular hole patterns, and rim slot patterns."
    ),
    "typical_parts": [
        "disk",
        "hub",
        "flange",
        "ring",
        "pulley",
        "shaft-like bodies",
    ],
    "main_ops": [
        "revolve_profile",
        "cut_center_bore",
        "cut_annular_groove",
        "cut_circular_hole_pattern",
        "cut_rim_slot_pattern",
        "apply_safe_chamfer",
    ],
    "unsupported": [
        "freeform surfaces",
        "arbitrary Python",
        "internal cooling networks",
        "non-axisymmetric housings",
    ],
}
