"""SketchProfile BasePackage — 2D sketch profile grammar."""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.base_packages.models import (
    BasePackage,
    BasePackageManifest,
)
from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash

SKETCH_PROFILE_MANIFEST = BasePackageManifest(
    package_id="sketch_profile",
    dialect_id="sketch_profile",
    dialect_version="0.2.0",
    title="Sketch Profile Grammar",
    summary=(
        "2D sketch-based profile grammar for non-rectangular extruded/cut geometry. "
        "Supports lines, arcs, circles, polylines, and slots composed into closed "
        "profiles, which are then extruded or used to cut existing solids."
    ),
    modeling_paradigm="sketch_profile",
    typical_geometry=[
        "L-shaped brackets with ribs",
        "non-rectangular profiled plates",
        "custom mounting flanges",
        "profiled cutouts",
    ],
    typical_parts=[
        "L-bracket",
        "custom flange profile",
        "profiled adapter plate",
        "gusset plate",
    ],
    main_ops=[
        "create_2d_sketch",
        "add_line_segment",
        "add_arc_segment",
        "add_circle",
        "add_polyline",
        "add_slot",
        "close_profile",
        "extrude_profile",
        "cut_profile",
    ],
    unsupported_cases=[
        "freeform surfaces",
        "3D swept paths (use loft_sweep dialect when available)",
        "organic shapes",
        "shelled thin-walled parts",
    ],
    safety_notes=[
        "Output is reference geometry only — not manufacturing-ready.",
    ],
    primitive_preferred_when=[
        "Certified / airworthy / manufacturing-ready part required.",
    ],
    composition_notes=[
        "Can be combined with other dialects via composition.",
    ],
)

SKETCH_PROFILE_ANTI_EXAMPLES: list[dict] = [
    {
        "anti_id": "make_bracket_bad",
        "title": "DO NOT use part-named ops",
        "bad_op": "make_bracket",
        "explanation": "SketchProfile is a grammar. Use create_2d_sketch + add_polyline + extrude_profile.",
    },
    {
        "anti_id": "direct_cadquery_bad",
        "title": "DO NOT output CadQuery code",
        "explanation": "The LLM must output RawGcadDocument JSON, never CadQuery code.",
    },
    {
        "anti_id": "safety_false_bad",
        "title": "DO NOT set any safety flag to false",
        "explanation": "All safety flags must be explicitly true.",
    },
    {
        "anti_id": "invent_op_bad",
        "title": "DO NOT invent operations",
        "bad_op": "make_custom_profile",
        "explanation": "Only use ops from the sketch_profile OperationSpec registry.",
    },
]


def _build_sketch_profile_level2_usage() -> str:
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
    from seekflow_engineering_tools.generative_cad.skills.level2_usage import generate_level2_usage_skill

    reg = default_registry()
    dialect = reg.require("sketch_profile")
    return generate_level2_usage_skill(
        dialect=dialect,
        package_manifest=SKETCH_PROFILE_MANIFEST,
        include_examples=True,
    )


def _compute_sp_contract_hash() -> str:
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
    return contract_hash(default_registry().require("sketch_profile").contract())


SKETCH_PROFILE_BASE_PACKAGE = BasePackage(
    manifest=SKETCH_PROFILE_MANIFEST,
    level2_usage_markdown=_build_sketch_profile_level2_usage(),
    examples=[],
    anti_examples=SKETCH_PROFILE_ANTI_EXAMPLES,
    contract_hash=_compute_sp_contract_hash(),
)
