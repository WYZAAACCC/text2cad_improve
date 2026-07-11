"""Composition BasePackage — multi-component assembly via boolean / pattern ops.

This is an LLM authoring package, NOT an executor. It does not import
CadQuery and does not run geometry. Runtime execution lives in
``generative_cad.dialects.composition``.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.base_packages.models import (
    BasePackage,
    BasePackageManifest,
)
from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash

# ── Manifest ──────────────────────────────────────────────────────────────────

COMPOSITION_MANIFEST = BasePackageManifest(
    package_id="composition",
    dialect_id="composition",
    dialect_version="0.2.0",
    title="Composition Grammar",
    summary=(
        "Multi-component assembly via placement, patterning, and boolean "
        "operations. The ONLY cross-dialect path — all multi-dialect "
        "combinations must go through composition."
    ),
    modeling_paradigm="composition",
    typical_geometry=[
        "multi-body assemblies",
        "boolean unions / cuts / intersections",
        "linear and circular component patterns",
    ],
    typical_parts=[
        "assembly of plate + boss",
        "two-component bracket with ribs",
        "patterned bolt-hole flange assembly",
    ],
    main_ops=[
        "translate_solid",
        "rotate_solid",
        "place_component",
        "circular_pattern_component",
        "linear_pattern_component",
        "boolean_union",
        "boolean_cut",
    ],
    unsupported_cases=[
        "creating new geometry from scratch",
        "sketch operations (use sketch_extrude or sketch_profile)",
        "freeform CAD ops",
        "make_assembly_part (forbidden)",
    ],
    safety_notes=[
        "Output is reference geometry only — not manufacturing-ready.",
        "Do not claim certification, airworthiness, or structural validation.",
    ],
    primitive_preferred_when=[
        "Single-part requests (use axisymmetric or sketch_extrude directly).",
        "Certified / manufacturing-ready parts.",
    ],
    composition_notes=[
        "This is the ONLY dialect allowed for cross-dialect combination.",
        "Component ID must be '__assembly__'.",
        "Boolean ops require exactly 2 inputs from component outputs.",
        "Composition ops cannot create new primitive geometry.",
    ],
)

# ── Anti-examples ─────────────────────────────────────────────────────────────

COMPOSITION_ANTI_EXAMPLES: list[dict] = [
    {
        "anti_id": "composition_create_sketch_bad",
        "title": "DO NOT use composition to create sketches",
        "bad_op": "create_sketch",
        "explanation": (
            "Composition only places, patterns, and boolean-combines existing solids. "
            "Creating geometry is the job of geometry dialects (axisymmetric, sketch_extrude, etc.)."
        ),
    },
    {
        "anti_id": "composition_cut_hole_bad",
        "title": "DO NOT use composition for feature cuts like cut_hole",
        "bad_op": "cut_hole",
        "explanation": (
            "Feature operations belong to geometry dialects. Composition only "
            "combines whole components."
        ),
    },
    {
        "anti_id": "composition_make_assembly_part_bad",
        "title": "DO NOT use make_assembly_part",
        "bad_op": "make_assembly_part",
        "explanation": "Composition is a grammar, not a part template.",
    },
    {
        "anti_id": "cross_dialect_internal_bad",
        "title": "DO NOT reference internal nodes directly across dialects",
        "explanation": (
            "Non-composition dialects must not directly reference internal nodes "
            "from other dialects. Only component outputs may be referenced by composition ops."
        ),
    },
    {
        "anti_id": "place_before_circular_pattern_bad",
        "title": "DO NOT use place_component before circular_pattern_component",
        "bad_op": "place_component",
        "explanation": (
            "circular_pattern_component automatically places each copy at (radius_mm, 0, 0) "
            "and rotates them around Z. Adding place_component before it causes double-translation: "
            "the body moves to position_mm, then the pattern handler moves it AGAIN to (radius_mm, 0, 0). "
            "Example: place_component(250,0,0) + circular_pattern(radius=250) → copies at R≈500mm, "
            "completely outside the disc. "
            "Correct: circular_pattern directly references the cutter component's extrude_profile output, "
            "with NO place_component node between them."
        ),
        "correct_approach": (
            "circular_pattern_component input: {node: \"n_cutter_extrude\", output: \"body\"}. "
            "No place_component needed — the pattern handler positions via radius_mm internally."
        ),
    },
]


def _build_composition_level2_usage() -> str:
    """Generate composition Level-2 usage skill via the centralized generator."""
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )
    from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
        generate_level2_usage_skill,
    )

    reg = default_registry()
    dialect = reg.require("composition")
    return generate_level2_usage_skill(
        dialect=dialect,
        package_manifest=COMPOSITION_MANIFEST,
        include_examples=True,
    )


def _compute_comp_contract_hash() -> str:
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )
    return contract_hash(default_registry().require("composition").contract())


COMPOSITION_BASE_PACKAGE = BasePackage(
    manifest=COMPOSITION_MANIFEST,
    level2_usage_markdown=_build_composition_level2_usage(),
    examples=[],
    anti_examples=COMPOSITION_ANTI_EXAMPLES,
    contract_hash=_compute_comp_contract_hash(),
)
