"""SketchProfile BasePackage — 2D sketch profile grammar."""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.base_packages.models import (
    BasePackage,
    BasePackageExample,
    BasePackageManifest,
)
from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash

SKETCH_PROFILE_MANIFEST = BasePackageManifest(
    package_id="sketch_profile",
    dialect_id="sketch_profile",
    dialect_version="0.2.0",
    title="Sketch Profile Grammar",
    summary=(
        "2D sketch-based profile grammar for non-rectangular extruded/cut/revolved geometry. "
        "Supports lines, arcs, circles, polylines, fillets, and mirroring composed into closed "
        "profiles, which are then extruded, cut, or revolved to create solids. "
        "revolve_profile enables arbitrary R-Z polygon revolution for axisymmetric parts "
        "with varying radial thickness (turbine discs, wheels, pulleys)."
    ),
    modeling_paradigm="sketch_profile",
    typical_geometry=[
        "L-shaped brackets with ribs",
        "non-rectangular profiled plates",
        "custom mounting flanges",
        "profiled cutouts",
        "axisymmetric parts with arbitrary R-Z polygon profiles (turbine discs, wheels)",
    ],
    typical_parts=[
        "L-bracket",
        "custom flange profile",
        "profiled adapter plate",
        "gusset plate",
        "turbine disc body (via revolve_profile)",
        "fir-tree slot cutter (via sketch + extrude + mirror + fillet)",
    ],
    main_ops=[
        "create_2d_sketch",
        "add_line_segment",
        "add_arc_segment",
        "add_circle",
        "add_polyline",
        "add_slot",
        "close_profile",
        "fillet_sketch",
        "mirror_profile",
        "extrude_profile",
        "cut_profile",
        "revolve_profile",
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
        "For complex axisymmetric parts (turbine discs): sketch_profile for ordered "
        "R-Z polygon revolve (disk body), sketch_profile for slot cutter "
        "(sketch→extrude→mirror→fillet), then composition for "
        "circular_pattern(rotate_copies=True) + boolean_cut.",
    ],
)

# ── Examples ──────────────────────────────────────────────────────────────────

SKETCH_REVOLVE_DISK_EXAMPLE = BasePackageExample(
    example_id="sketch_revolve_disk_001",
    title="Axisymmetric disk body via sketch_profile.revolve_profile",
    user_request=(
        "Create a rotationally symmetric disk with varying thickness: "
        "hub thick, web thin, rim thick."
    ),
    raw_document={
        "schema_version": "g_cad_core_v0.2",
        "document_id": "gcad_revolve_disk_example",
        "part_name": "RevolveDiskExample",
        "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [
            {"dialect": "sketch_profile", "version": "0.2.0"},
            {"dialect": "composition", "version": "0.2.0"},
        ],
        "components": [
            {
                "id": "disk_body",
                "owner_dialect": "sketch_profile",
                "kind_hint": "axisymmetric_disk",
                "root_node": "n_revolve",
            },
            {
                "id": "__assembly__",
                "owner_dialect": "composition",
                "kind_hint": None,
                "root_node": "n_final",
            },
        ],
        "nodes": [
            {
                "id": "n_sketch", "component": "disk_body",
                "dialect": "sketch_profile", "op": "create_2d_sketch",
                "op_version": "1.0.0", "phase": "sketch",
                "inputs": [], "outputs": [{"name": "sketch", "type": "sketch"}],
                "params": {"plane": "XZ"},
                "required": True, "degradation_policy": "fail",
            },
            {
                "id": "n_polyline", "component": "disk_body",
                "dialect": "sketch_profile", "op": "add_polyline",
                "op_version": "1.0.0", "phase": "profile",
                "inputs": [{"node": "n_sketch", "output": "sketch"}],
                "outputs": [{"name": "profile", "type": "profile"}],
                "params": {
                    "points": [
                        {"x_mm": 60, "y_mm": -38}, {"x_mm": 120, "y_mm": -38},
                        {"x_mm": 170, "y_mm": -22}, {"x_mm": 215, "y_mm": -16},
                        {"x_mm": 250, "y_mm": -32}, {"x_mm": 250, "y_mm": 32},
                        {"x_mm": 215, "y_mm": 16},  {"x_mm": 170, "y_mm": 22},
                        {"x_mm": 120, "y_mm": 38},  {"x_mm": 60, "y_mm": 38},
                    ],
                },
                "required": True, "degradation_policy": "fail",
            },
            {
                "id": "n_close", "component": "disk_body",
                "dialect": "sketch_profile", "op": "close_profile",
                "op_version": "1.0.0", "phase": "profile",
                "inputs": [{"node": "n_polyline", "output": "profile"}],
                "outputs": [{"name": "profile", "type": "profile"}],
                "params": {},
                "required": True, "degradation_policy": "fail",
            },
            {
                "id": "n_revolve", "component": "disk_body",
                "dialect": "sketch_profile", "op": "revolve_profile",
                "op_version": "1.0.0", "phase": "feature",
                "inputs": [{"node": "n_close", "output": "profile"}],
                "outputs": [{"name": "body", "type": "solid"}],
                "params": {"angle_deg": 360.0},
                "required": True, "degradation_policy": "fail",
            },
        ],
        "constraints": {
            "require_step_file": True,
            "require_metadata_sidecar": True,
            "require_closed_solid": True,
            "expected_body_count": 1,
        },
        "safety": {
            "non_flight_reference_only": True, "not_airworthy": True,
            "not_certified": True, "not_for_manufacturing": True,
            "not_for_installation": True, "no_structural_validation": True,
            "no_life_prediction": True,
        },
    },
    expected_dialects=["sketch_profile", "composition"],
    notes=[
        "Key workflow: create_2d_sketch(plane=XZ) → add_polyline(R-Z polygon) → close_profile → revolve_profile.",
        "The polyline on XZ plane: X=R(radius), Y=Z(axial). Points define the exact R-Z cross-section.",
        "NOT Z-sorted: unlike axisymmetric.revolve_profile, the order of polyline points is preserved.",
        "For complete turbine disc: add a second sketch_profile component for slot cutter, then use "
        "composition dialect for circular_pattern(rotate_copies=True) + boolean_cut.",
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
    {
        "anti_id": "slot_half_profile_bad",
        "title": "DO NOT stop at root center (Y=0) — this creates a wedge, NOT a fir-tree",
        "explanation": (
            "This is the #1 slot-cutter mistake.  The LLM traces mouth→right→root "
            "and STOPS at (X=-D, Y=0), expecting close_profile to finish the shape. "
            "WRONG: close_profile draws a STRAIGHT LINE from (-D,0) back to (0,±W), "
            "producing a triangular WEDGE, not a fir-tree.  "
            "CORRECT: trace the FULL contour — mouth top (0, +W) → right side "
            "down (−X,+Y) through all lobes → root bottom (−D, 0 or −D, −w) → "
            "left side back up (−X,−Y) through all lobes → mouth bottom (0, −W). "
            "The profile MUST be symmetric about Y=0.  Typical point count: 22-24 "
            "(NOT 11-13).  If you have 11 points all with Y>=0, YOU DID IT WRONG."
        ),
    },
    {
        "anti_id": "slot_too_shallow_bad",
        "title": "DO NOT confuse radial slot depth with axial rim thickness",
        "explanation": (
            "The slot profile's radial depth (18-24mm, X negative from rim surface) defines "
            "the fir-tree geometry only.  Axial cutting through the 60mm Z-thickness of the "
            "rim is handled by extrude_profile(depth_mm=80, direction=\"both\").  "
            "Do NOT make the slot deeper than the user requested."
        ),
    },
    {
        "anti_id": "slot_mouth_too_wide_bad",
        "title": "DO NOT make slot mouth wider than the user requested",
        "explanation": (
            "The mouth half-width (Y at X=0) must match the user's specification. "
            "If the user says 3-4mm half-width, DO NOT use Y=7 or Y=8 at X=0. "
            "A mouth wider than specified weakens the posts between slots."
        ),
    },
    {
        "anti_id": "slot_staircase_not_firtree_bad",
        "title": "DO NOT use staircase OR inverted fir-tree — MUST be 外宽内窄 with neck flats + bottom tooth",
        "explanation": (
            "Real fir-tree: 7.5>6.5>3.5 (外宽内窄). Neck flats 3mm long for fillet room. "
            "Bottom has a small 3rd tooth (NOT flat rectangle). "
            "All flanks INCLINED (dx!=0 AND dy!=0). "
            "24-point parameterized template: W_lobe1=7.5, W_lobe2=6.5, W_bottom=3.5, "
            "W_wedge1=2.5, W_wedge2=2.0, L_neck1=3.0, L_neck2=2.0, R_fillet=1.5."
        ),
        "correct_approach": (
            "PARAMETERIZED 24-pt template: RIGHT-(0,W_mouth)→(-3,W_wedge1)→(-4,W_lobe1)→"
            "(-7,W_lobe1)→(-9,W_wedge1)→(-12,W_wedge1)[neck]→(-12.5,W_lobe2)→(-14.5,W_lobe2)→"
            "(-16,W_wedge2)→(-18,W_wedge2)[neck]→(-18.5,W_bottom)→(-20,W_bottom-0.5)[root]. "
            "LEFT mirrors. VERIFY: W_lobe1>W_lobe2>W_bottom, neck flats ≥2×R_fillet."
        ),
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
    examples=[SKETCH_REVOLVE_DISK_EXAMPLE],
    anti_examples=SKETCH_PROFILE_ANTI_EXAMPLES,
    contract_hash=_compute_sp_contract_hash(),
)
