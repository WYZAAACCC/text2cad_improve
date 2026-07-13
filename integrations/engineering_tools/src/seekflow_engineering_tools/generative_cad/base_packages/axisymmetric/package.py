"""Axisymmetric BasePackage — rotationally symmetric solids via revolve_profile grammar.

This is an LLM authoring package, NOT an executor. It does not import
CadQuery and does not run geometry. Runtime execution lives in
``generative_cad.dialects.axisymmetric``.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.base_packages.models import (
    BasePackage,
    BasePackageExample,
    BasePackageManifest,
)
from seekflow_engineering_tools.generative_cad.ir.hashing import contract_hash

# ── Manifest ──────────────────────────────────────────────────────────────────

AXISYMMETRIC_MANIFEST = BasePackageManifest(
    package_id="axisymmetric",
    dialect_id="axisymmetric",
    dialect_version="0.2.0",
    title="Axisymmetric Revolve Grammar",
    summary=(
        "Rotationally symmetric solids generated from radial-axial profiles "
        "(revolve_profile), with optional coaxial bores, annular grooves, "
        "circular hole patterns, rim slot patterns, and safe edge chamfers."
    ),
    modeling_paradigm="revolve_profile",
    typical_geometry=[
        "disk-like bodies",
        "annular rings",
        "stepped hubs",
        "flanged cylinders",
        "thin washers / spacers",
        "pulley-like reference shapes",
    ],
    typical_parts=[
        "washer",
        "ring",
        "hub",
        "flange-like reference",
        "stepped spacer",
        "pulley-like reference",
        "disk with bolt circle",
    ],
    main_ops=[
        "revolve_profile",
        "cut_center_bore",
        "cut_annular_groove",
        "cut_circular_hole_pattern",
        "cut_rim_slot_pattern",
        "apply_safe_chamfer",
    ],
    unsupported_cases=[
        "freeform surfaces",
        "non-axisymmetric housings",
        "internal cooling networks",
        "organic shapes",
    ],
    safety_notes=[
        "Output is reference geometry only — not manufacturing-ready.",
        "Do not claim certification, airworthiness, or structural validation.",
    ],
    primitive_preferred_when=[
        "Exact involute gear geometry (use involute_spur_gear primitive).",
        "Certified / airworthy / manufacturing-ready part required.",
    ],
    composition_notes=[
        "Can be combined with other dialects via composition dialect.",
        "Composition op inputs must reference component outputs, not internal nodes.",
    ],
)

# ── Examples ──────────────────────────────────────────────────────────────────

WASHER_EXAMPLE = BasePackageExample(
    example_id="axisymmetric_washer_001",
    title="Simple reference washer — OD 80mm, ID 30mm, thickness 12mm",
    user_request="Create a reference washer with outer diameter 80mm, inner bore 30mm, thickness 12mm.",
    raw_document={
        "schema_version": "g_cad_core_v0.2",
        "document_id": "washer-001",
        "part_name": "reference_washer_80x30x12",
        "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0"}],
        "components": [
            {"id": "washer_body", "owner_dialect": "axisymmetric", "root_node": "n_chamfer"}
        ],
        "nodes": [
            {
                "id": "n_revolve",
                "component": "washer_body",
                "dialect": "axisymmetric",
                "op": "revolve_profile",
                "op_version": "1.0.0",
                "phase": "base_solid",
                "inputs": [],
                "outputs": [
                    {"name": "body", "type": "solid"},
                    {"name": "outer_frame", "type": "frame"},
                ],
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 40.0, "z_front_mm": 0.0, "z_rear_mm": 2.0},
                        {"r_mm": 40.0, "z_front_mm": 2.0, "z_rear_mm": 12.0},
                        {"r_mm": 14.0, "z_front_mm": 12.0, "z_rear_mm": 13.0},
                    ],
                },
                "required": True,
                "degradation_policy": "fail",
            },
            {
                "id": "n_bore",
                "component": "washer_body",
                "dialect": "axisymmetric",
                "op": "cut_center_bore",
                "op_version": "1.0.0",
                "phase": "primary_cut",
                "inputs": [{"node": "n_revolve", "output": "body"}],
                "outputs": [{"name": "body", "type": "solid"}],
                "params": {"diameter_mm": 30.0, "axis": "Z", "through_all": True},
                "required": True,
                "degradation_policy": "fail",
            },
            {
                "id": "n_chamfer",
                "component": "washer_body",
                "dialect": "axisymmetric",
                "op": "apply_safe_chamfer",
                "op_version": "1.0.0",
                "phase": "edge_treatment",
                "inputs": [{"node": "n_bore", "output": "body"}],
                "outputs": [{"name": "body", "type": "solid"}],
                "params": {"distance_mm": 0.5, "target": "all_external_edges"},
                "required": True,
                "degradation_policy": "fail",
            },
        ],
        "constraints": {
            "require_step_file": True,
            "require_metadata_sidecar": True,
            "require_closed_solid": True,
            "expected_body_count": 1,
            "expected_bbox_mm": [80.0, 80.0, 13.0],
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
    expected_dialects=["axisymmetric"],
    expected_validation_stages=[
        "structure", "registry", "params", "ownership", "graph",
        "typecheck", "phase", "composition", "safety",
        "canonicalize", "dialect_semantics", "geometry_preflight",
    ],
    notes=["Classic washer pattern. Shows correct profile_stations usage with r_mm=radius."],
)


# ── Turbine disc reference example ────────────────────────────────────────────
# Demonstrates continuous Hub+Rim outer contour. The web is the transition zone
# between hub (r=30) and rim (r=100) — NOT a cut_annular_groove side recess.

TURBINE_DISC_REFERENCE_EXAMPLE = BasePackageExample(
    example_id="axisymmetric_turbine_disc_001",
    title="Reference turbine disc — OD 200mm, bore 60mm, thickness 40mm, 60 fir-tree slots",
    user_request=(
        "Create a reference turbine disc with outer diameter 200mm, central bore 60mm, "
        "thickness 40mm. Hub radius 30mm extends Z=5→35. Rim radius 100mm extends Z=0→40. "
        "60 fir-tree slots on the outer circumference."
    ),
    raw_document={
        "schema_version": "g_cad_core_v0.2",
        "document_id": "turbine-disc-001",
        "part_name": "reference_turbine_disc_200x60x40",
        "units": "mm",
        "trust_level": "reference_geometry",
        "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0"}],
        "components": [
            {"id": "disc_body", "owner_dialect": "axisymmetric", "root_node": "n_slots"}
        ],
        "nodes": [
            {
                "id": "n_revolve",
                "component": "disc_body",
                "dialect": "axisymmetric",
                "op": "revolve_profile",
                "op_version": "1.0.0",
                "phase": "base_solid",
                "inputs": [],
                "outputs": [
                    {"name": "body", "type": "solid"},
                    {"name": "outer_frame", "type": "frame"},
                ],
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 32.0, "z_front_mm": 0.0,  "z_rear_mm": 5.0,  "label": "hub_front"},
                        {"r_mm": 100.0,"z_front_mm": 5.0,  "z_rear_mm": 35.0, "label": "rim_outer"},
                        {"r_mm": 32.0, "z_front_mm": 35.0, "z_rear_mm": 40.0, "label": "hub_rear"},
                    ],
                },
                "required": True,
                "degradation_policy": "fail",
            },
            {
                "id": "n_bore",
                "component": "disc_body",
                "dialect": "axisymmetric",
                "op": "cut_center_bore",
                "op_version": "1.0.0",
                "phase": "primary_cut",
                "inputs": [{"node": "n_revolve", "output": "body"}],
                "outputs": [{"name": "body", "type": "solid"}],
                "params": {"diameter_mm": 60.0, "axis": "Z", "through_all": True},
                "required": True,
                "degradation_policy": "fail",
            },
            {
                "id": "n_slots",
                "component": "disc_body",
                "dialect": "axisymmetric",
                "op": "cut_rim_slot_pattern",
                "op_version": "1.0.0",
                "phase": "rim_detail",
                "inputs": [{"node": "n_bore", "output": "body"}],
                "outputs": [{"name": "body", "type": "solid"}],
                "params": {
                    "count": 60,
                    "slot_depth_mm": 12.0,
                    "slot_profile": {
                        "kind": "symmetric_station_profile",
                        "stations": [
                            {"depth_mm": 3.0, "half_width_mm": 6.0},
                            {"depth_mm": 5.0, "half_width_mm": 4.0},
                            {"depth_mm": 8.0, "half_width_mm": 5.5},
                            {"depth_mm": 10.0, "half_width_mm": 2.5},
                        ],
                    },
                },
                "required": True,
                "degradation_policy": "fail",
            },
        ],
        "constraints": {
            "require_step_file": True,
            "require_metadata_sidecar": True,
            "require_closed_solid": True,
            "expected_body_count": 1,
            "expected_bbox_mm": [200.0, 200.0, 40.0],
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
    expected_dialects=["axisymmetric"],
    expected_validation_stages=[
        "structure", "registry", "params", "ownership", "graph",
        "typecheck", "phase", "composition", "safety",
        "canonicalize", "dialect_semantics", "geometry_preflight",
    ],
    notes=[
        "Hub(r=32) + Rim(r=100) continuous outer contour. Web is the transition between them — NOT a separate groove.",
        "DO NOT use cut_annular_groove to create a web recess — that makes an unrealistic empty cavity.",
        "DO NOT use profile_stations with zero-width or Z-overlapping stations.",
        "DO NOT use r_mm < 0.5mm filler stations (e.g. r=1.0 hub_lower_fill) — they produce degenerate needle solids (A009).",
        "hub_front/hub_rear r=32mm is slightly larger than bore_radius=30mm to avoid A005 coplanar detection.",
        "fir-tree slot stations MUST alternate wide (lobe) / narrow (neck) half_width to create undercuts: [6,4,5.5,2.5].",
        "half_width must NOT monotonically decrease — alternating wide/narrow creates the fir-tree locking geometry.",
        "slot depths are nondecreasing: [3, 5, 8, 10].",
    ],
)

# ── Anti-examples ─────────────────────────────────────────────────────────────

AXISYMMETRIC_ANTI_EXAMPLES: list[dict] = [
    {
        "anti_id": "make_turbine_disk_bad",
        "title": "DO NOT use part-named ops like make_turbine_disk",
        "bad_op": "make_turbine_disk",
        "explanation": (
            "Axisymmetric is a revolve grammar, not a turbine disk template. "
            "Use revolve_profile with appropriate profile_stations instead."
        ),
    },
    {
        "anti_id": "direct_cadquery_bad",
        "title": "DO NOT output CadQuery code",
        "bad_snippet": "import cadquery as cq\nresult = cq.Workplane('XY').circle(40).extrude(12)",
        "explanation": "The LLM must output RawGcadDocument JSON, never CadQuery code.",
    },
    {
        "anti_id": "safety_false_bad",
        "title": "DO NOT set any safety flag to false",
        "bad_field": "non_flight_reference_only: false",
        "explanation": "All safety flags must be explicitly true. Generative output is reference geometry only.",
    },
    {
        "anti_id": "cross_dialect_internal_bad",
        "title": "DO NOT reference internal nodes across dialects",
        "bad_input": {"node": "n_sketch_extrude_body", "output": "body"},
        "explanation": "Cross-dialect references must go through composition component outputs.",
    },
    {
        "anti_id": "unknown_op_bad",
        "title": "DO NOT invent operations",
        "bad_op": "make_rotor_disk",
        "explanation": "Only use operations listed in the axisymmetric OperationSpec registry.",
    },
    {
        "anti_id": "regional_profile_stations_bad",
        "title": "DO NOT output profile_stations as regional descriptions",
        "bad_snippet": [
            {"r_mm": 100, "z_front_mm": 0, "z_rear_mm": 40, "label": "rim"},
            {"r_mm": 80, "z_front_mm": 0, "z_rear_mm": 40, "label": "hub"},
            {"r_mm": 30, "z_front_mm": 0, "z_rear_mm": 40, "label": "bore_wall"}
        ],
        "explanation": (
            "profile_stations 必须是外轮廓的连续段（Z 的单值函数），"
            "不能按 bore/hub/web/rim 分区域描述。"
            "同一 Z 只能有一个半径。复杂截面请转换为外轮廓连续台阶。"
            "内壁（bore）应由 cut_center_bore 创建，而非在 profile_stations 中放内壁站点。"
        ),
    },
    {
        "anti_id": "hourglass_profile_bad",
        "title": "DO NOT use profile_stations radius variation to express web/bore recess",
        "bad_profile_stations": [
            {"r_mm": 100.0, "z_front_mm": 0.0, "z_rear_mm": 5.0},
            {"r_mm": 80.0, "z_front_mm": 5.0, "z_rear_mm": 35.0, "label": "web"},
            {"r_mm": 100.0, "z_front_mm": 35.0, "z_rear_mm": 40.0}
        ],
        "explanation": (
            "This creates an hourglass shape (wide ends, narrow middle), NOT a turbine disc. "
            "A turbine disc has a NARROW hub and WIDE rim — the opposite of hourglass. "
            "The rim outer radius must cover the FULL Z range. "
            "DO NOT use cut_annular_groove to create a web recess either — that makes an "
            "unrealistic empty cavity inside the disk body. "
            "The web is simply the transition zone between narrow hub and wide rim."
        ),
        "correct_approach": (
            "Use revolve_profile with narrow hub stations at both ends and a wide rim station "
            "in the middle: e.g. r=32 Z=0→5 (hub_front) | r=100 Z=5→35 (rim) | "
            "r=32 Z=35→40 (hub_rear). The vertical steps at Z=5 and Z=35 ARE the web faces "
            "— they naturally connect the narrow hub to the wide rim without any groove operation."
        ),
    },
]

# ── Build package ─────────────────────────────────────────────────────────────


def _build_axisymmetric_level2_usage() -> str:
    """Generate the axisymmetric Level-2 usage skill via the centralized generator."""
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )
    from seekflow_engineering_tools.generative_cad.skills.level2_usage import (
        generate_level2_usage_skill,
    )

    reg = default_registry()
    dialect = reg.require("axisymmetric")
    return generate_level2_usage_skill(
        dialect=dialect,
        package_manifest=AXISYMMETRIC_MANIFEST,
        include_examples=True,
    )


# ── Singleton ─────────────────────────────────────────────────────────────────


def _compute_axisymmetric_contract_hash() -> str:
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )
    return contract_hash(default_registry().require("axisymmetric").contract())


AXISYMMETRIC_BASE_PACKAGE = BasePackage(
    manifest=AXISYMMETRIC_MANIFEST,
    level2_usage_markdown=_build_axisymmetric_level2_usage(),
    examples=[WASHER_EXAMPLE, TURBINE_DISC_REFERENCE_EXAMPLE],
    anti_examples=AXISYMMETRIC_ANTI_EXAMPLES,
    contract_hash=_compute_axisymmetric_contract_hash(),
)
