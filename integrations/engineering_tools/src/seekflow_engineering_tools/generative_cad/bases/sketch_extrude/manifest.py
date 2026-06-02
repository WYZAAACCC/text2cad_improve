"""Sketch-extrude base manifest — DEPRECATED v0.1.

This module is part of the legacy bases/ package. It is superseded by:
- ``generative_cad.base_packages.sketch_extrude`` (LLM-facing authoring package)
- ``generative_cad.dialects.sketch_extrude`` (compiler/runtime ABI)

Do NOT use in new code. This file is retained for backward compatibility only.
"""

SKETCH_EXTRUDE_MANIFEST = {
    "base_id": "sketch_extrude_base",
    "base_version": "0.1.0",
    "summary": (
        "For prismatic machined parts generated from 2D sketches, "
        "with extrudes, pockets, holes, patterns, bosses, ribs, fillets, and chamfers."
    ),
    "typical_parts": [
        "brackets",
        "mounting plates",
        "blocks",
        "clevis-like concept parts",
        "adapter plates",
    ],
    "main_ops": [
        "extrude_rectangle",
        "cut_rectangular_pocket",
        "cut_hole",
        "cut_hole_pattern_linear",
        "add_rectangular_boss",
        "add_rib",
        "apply_safe_fillet",
        "apply_safe_chamfer",
    ],
    "unsupported": [
        "organic freeform shapes",
        "arbitrary Python",
        "complex swept profiles",
        "lofted geometries",
    ],
}
