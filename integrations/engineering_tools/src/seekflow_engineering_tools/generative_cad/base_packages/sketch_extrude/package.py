"""SketchExtrude BasePackage — prismatic parts via extrude_rectangle grammar.

This is an LLM authoring package, NOT an executor. It does not import
CadQuery and does not run geometry. Runtime execution lives in
``generative_cad.dialects.sketch_extrude``.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.base_packages.models import (
    BasePackage,
    BasePackageExample,
    BasePackageManifest,
)
from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash

# ── Manifest ──────────────────────────────────────────────────────────────────

SKETCH_EXTRUDE_MANIFEST = BasePackageManifest(
    package_id="sketch_extrude",
    dialect_id="sketch_extrude",
    dialect_version="0.2.0",
    title="Sketch Extrude Grammar",
    summary=(
        "Prismatic machined parts generated from 2D rectangular sketches, "
        "with extrudes, pockets, holes, linear hole patterns, rectangular "
        "bosses, ribs, fillets, and chamfers."
    ),
    modeling_paradigm="sketch_extrude",
    typical_geometry=[
        "rectangular base plates",
        "flat mounting brackets",
        "machined blocks",
        "clevis-like concept parts",
        "adapter plates",
    ],
    typical_parts=[
        "base plate",
        "mounting bracket",
        "clamp block",
        "adapter plate",
        "L-bracket reference",
    ],
    main_ops=[
        "extrude_rectangle",
        "cut_rectangular_pocket",
        "cut_hole",
        "cut_hole_pattern_linear",
        "add_rectangular_boss",
        "add_rib",
        "apply_safe_fillet",
        "apply_safe_chamfer",
    ],
    unsupported_cases=[
        "organic freeform shapes",
        "complex swept profiles",
        "lofted geometries",
        "non-rectangular base profiles (use sketch_profile dialect)",
    ],
    safety_notes=[
        "Output is reference geometry only — not manufacturing-ready.",
        "Do not claim certification, airworthiness, or structural validation.",
    ],
    primitive_preferred_when=[
        "Certified / airworthy / manufacturing-ready part required.",
        "Exact gear geometry (use involute_spur_gear primitive).",
    ],
    composition_notes=[
        "Can be combined with other dialects via composition dialect.",
        "Composition op inputs must reference component outputs, not internal nodes.",
    ],
)

# ── Example ───────────────────────────────────────────────────────────────────

BASE_PLATE_EXAMPLE = BasePackageExample(
    example_id="sketch_extrude_base_plate_001",
    title="Simple rectangular base plate — 100x80x10mm with 4 mounting holes",
    user_request=(
        "Create a reference base plate 100mm wide, 80mm tall, 10mm thick "
        "with four 6mm mounting holes at the corners."
    ),
    raw_document={
        "schema_version": "g_cad_core_v0.2",
        "document_id": "base-plate-001",
        "part_name": "reference_base_plate",
        "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "sketch_extrude", "version": "0.2.0"}],
        "components": [
            {"id": "plate_body", "owner_dialect": "sketch_extrude", "root_node": "n_fillet"}
        ],
        "nodes": [
            {
                "id": "n_extrude",
                "component": "plate_body",
                "dialect": "sketch_extrude",
                "op": "extrude_rectangle",
                "op_version": "1.0.0",
                "phase": "base_solid",
                "inputs": [],
                "outputs": [{"name": "body", "type": "solid"}],
                "params": {
                    "width_mm": 100.0,
                    "height_mm": 80.0,
                    "depth_mm": 10.0,
                    "plane": "XY",
                    "centered": True,
                    "direction": "+",
                },
                "required": True,
                "degradation_policy": "fail",
            },
            {
                "id": "n_holes",
                "component": "plate_body",
                "dialect": "sketch_extrude",
                "op": "cut_hole_pattern_linear",
                "op_version": "1.0.0",
                "phase": "hole_pattern",
                "inputs": [{"node": "n_extrude", "output": "body"}],
                "outputs": [{"name": "body", "type": "solid"}],
                "params": {
                    "hole_dia_mm": 6.0,
                    "count_x": 2,
                    "count_y": 2,
                    "spacing_x_mm": 80.0,
                    "spacing_y_mm": 60.0,
                    "axis": "Z",
                    "through_all": True,
                },
                "required": True,
                "degradation_policy": "fail",
            },
            {
                "id": "n_fillet",
                "component": "plate_body",
                "dialect": "sketch_extrude",
                "op": "apply_safe_fillet",
                "op_version": "1.0.0",
                "phase": "edge_treatment",
                "inputs": [{"node": "n_holes", "output": "body"}],
                "outputs": [{"name": "body", "type": "solid"}],
                "params": {"radius_mm": 2.0, "target": "all_external_edges"},
                "required": True,
                "degradation_policy": "fail",
            },
        ],
        "constraints": {
            "require_step_file": True,
            "require_metadata_sidecar": True,
            "require_closed_solid": True,
            "expected_body_count": 1,
        },
        "safety": {
            "non_flight_reference_only": True,
            "not_airworthy": True,
            "not_certified": True,
            "not_for_manufacturing": True,
            "not_for_installation": True,
            "no_structural_validation": True,
            "no_life_prediction": True,
        },
    },
    expected_dialects=["sketch_extrude"],
    expected_validation_stages=[
        "structure", "registry", "params", "ownership", "graph",
        "typecheck", "phase", "composition", "safety",
        "canonicalize", "dialect_semantics", "geometry_preflight",
    ],
    notes=["Demonstrates the standard base plate pattern with corner mounting holes."],
)

# ── Anti-examples ─────────────────────────────────────────────────────────────

SKETCH_EXTRUDE_ANTI_EXAMPLES: list[dict] = [
    {
        "anti_id": "make_bracket_bad",
        "title": "DO NOT use part-named ops like make_bracket",
        "bad_op": "make_bracket",
        "explanation": (
            "SketchExtrude is a sketch grammar, not a bracket template. "
            "Use extrude_rectangle with appropriate cut operations."
        ),
    },
    {
        "anti_id": "direct_cadquery_bad",
        "title": "DO NOT output CadQuery code",
        "bad_snippet": "import cadquery as cq\nresult = cq.Workplane('XY').box(100,80,10)",
        "explanation": "The LLM must output RawGcadDocument JSON, never CadQuery code.",
    },
    {
        "anti_id": "safety_false_bad",
        "title": "DO NOT set any safety flag to false",
        "bad_field": "non_flight_reference_only: false",
        "explanation": "All safety flags must be explicitly true.",
    },
    {
        "anti_id": "cross_dialect_internal_bad",
        "title": "DO NOT reference internal nodes across dialects",
        "explanation": "Cross-dialect references must go through composition component outputs.",
    },
    {
        "anti_id": "invent_op_bad",
        "title": "DO NOT invent operations like make_mounting_plate",
        "bad_op": "make_mounting_plate",
        "explanation": "Only use operations from the sketch_extrude OperationSpec registry.",
    },
]


def _build_sketch_extrude_level2_usage() -> str:
    """Generate sketch_extrude Level-2 usage skill via the centralized generator."""
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )
    from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
        generate_level2_usage_skill,
    )

    reg = default_registry()
    dialect = reg.require("sketch_extrude")
    return generate_level2_usage_skill(
        dialect=dialect,
        package_manifest=SKETCH_EXTRUDE_MANIFEST,
        include_examples=True,
    )


def _compute_se_contract_hash() -> str:
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )
    return contract_hash(default_registry().require("sketch_extrude").contract())


SKETCH_EXTRUDE_BASE_PACKAGE = BasePackage(
    manifest=SKETCH_EXTRUDE_MANIFEST,
    level2_usage_markdown=_build_sketch_extrude_level2_usage(),
    examples=[BASE_PLATE_EXAMPLE],
    anti_examples=SKETCH_EXTRUDE_ANTI_EXAMPLES,
    contract_hash=_compute_se_contract_hash(),
)
