"""Turbomachinery primitive definitions.

Axisymmetric turbine disk — non-flight reference geometry only.
v0.2 adds cyclic rim slots, hub sleeve, annular details, coverplate/balance holes.
"""

from seekflow_engineering_tools.geometry_primitives.base import (
    PrimitiveDefinition,
    PrimitiveParameter,
)

AXISYMMETRIC_TURBINE_DISK = PrimitiveDefinition(
    name="axisymmetric_turbine_disk",
    category="turbomachinery",
    description=(
        "Axisymmetric turbine disk non-flight reference geometry: "
        "hub-web-rim body, center bore, optional bolt/lightening/cooling "
        "hole rings, cyclic rim blade-root slots (fir_tree_like/dovetail/rectangular), "
        "front/rear hub sleeves, annular details, coverplate bolt ring, balance holes. "
        "This primitive is not airworthy, not certified, and not for manufacturing."
    ),
    parameters=[
        # ── v0.1 legacy parameters ──
        PrimitiveParameter(name="outer_dia_mm", type="float", unit="mm", required=True, min_value=1.0),
        PrimitiveParameter(name="bore_dia_mm", type="float", unit="mm", required=True, min_value=0.0),
        PrimitiveParameter(name="axial_width_mm", type="float", unit="mm", required=True, min_value=0.1),

        PrimitiveParameter(name="hub_outer_dia_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="web_outer_dia_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="rim_inner_dia_mm", type="float", unit="mm", required=True, min_value=0.1),

        PrimitiveParameter(name="hub_width_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="web_width_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="rim_width_mm", type="float", unit="mm", required=True, min_value=0.1),

        PrimitiveParameter(name="hub_fillet_radius_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="web_fillet_radius_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="rim_fillet_radius_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="edge_chamfer_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),

        PrimitiveParameter(name="bolt_hole_count", type="int", required=False, default=0, min_value=0),
        PrimitiveParameter(name="bolt_pcd_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="bolt_hole_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="bolt_hole_axis", type="str", required=False, default="Z"),

        PrimitiveParameter(name="lightening_hole_count", type="int", required=False, default=0, min_value=0),
        PrimitiveParameter(name="lightening_hole_pcd_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="lightening_hole_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="lightening_hole_axis", type="str", required=False, default="Z"),

        PrimitiveParameter(name="cooling_hole_count", type="int", required=False, default=0, min_value=0),
        PrimitiveParameter(name="cooling_hole_pcd_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="cooling_hole_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="cooling_hole_axis", type="str", required=False, default="Z"),

        PrimitiveParameter(name="quality_grade", type="str", required=False, default="concept_geometry"),
        PrimitiveParameter(name="non_flight_reference_only", type="bool", required=False, default=True),

        # ── v0.2 rim slot parameters ──
        PrimitiveParameter(name="rim_slot_count", type="int", required=False, default=60, min_value=0),
        PrimitiveParameter(name="rim_slot_style", type="str", required=False, default="fir_tree_like"),
        PrimitiveParameter(name="rim_slot_depth_mm", type="float", unit="mm", required=False, default=35.0, min_value=0.0),
        PrimitiveParameter(name="rim_slot_width_mm", type="float", unit="mm", required=False, default=7.0, min_value=0.0),
        PrimitiveParameter(name="rim_slot_neck_width_mm", type="float", unit="mm", required=False, default=4.5, min_value=0.0),
        PrimitiveParameter(name="rim_slot_lobe_width_mm", type="float", unit="mm", required=False, default=8.5, min_value=0.0),
        PrimitiveParameter(name="rim_slot_lobe_depth_mm", type="float", unit="mm", required=False, default=7.0, min_value=0.0),
        PrimitiveParameter(name="rim_slot_axial_margin_mm", type="float", unit="mm", required=False, default=4.0, min_value=0.0),
        PrimitiveParameter(name="rim_slot_root_fillet_mm", type="float", unit="mm", required=False, default=0.5, min_value=0.0),
        PrimitiveParameter(name="rim_slot_tip_chamfer_mm", type="float", unit="mm", required=False, default=0.3, min_value=0.0),

        # ── v0.2 hub sleeve parameters ──
        PrimitiveParameter(name="front_hub_sleeve_outer_dia_mm", type="float", unit="mm", required=False, default=150.0, min_value=0.0),
        PrimitiveParameter(name="front_hub_sleeve_inner_dia_mm", type="float", unit="mm", required=False, default=80.0, min_value=0.0),
        PrimitiveParameter(name="front_hub_sleeve_height_mm", type="float", unit="mm", required=False, default=55.0, min_value=0.0),
        PrimitiveParameter(name="front_hub_sleeve_wall_mm", type="float", unit="mm", required=False, default=8.0, min_value=0.0),
        PrimitiveParameter(name="front_hub_sleeve_chamfer_mm", type="float", unit="mm", required=False, default=2.0, min_value=0.0),

        PrimitiveParameter(name="rear_hub_sleeve_outer_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="rear_hub_sleeve_inner_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="rear_hub_sleeve_height_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),

        # ── v0.2 annular details parameters ──
        PrimitiveParameter(name="enable_annular_details", type="bool", required=False, default=True),
        PrimitiveParameter(name="inner_hub_step_outer_dia_mm", type="float", unit="mm", required=False, default=180.0, min_value=0.0),
        PrimitiveParameter(name="inner_hub_step_height_mm", type="float", unit="mm", required=False, default=8.0, min_value=0.0),
        PrimitiveParameter(name="mid_web_recess_inner_dia_mm", type="float", unit="mm", required=False, default=220.0, min_value=0.0),
        PrimitiveParameter(name="mid_web_recess_outer_dia_mm", type="float", unit="mm", required=False, default=360.0, min_value=0.0),
        PrimitiveParameter(name="mid_web_recess_depth_mm", type="float", unit="mm", required=False, default=3.0, min_value=0.0),
        PrimitiveParameter(name="outer_rim_recess_inner_dia_mm", type="float", unit="mm", required=False, default=390.0, min_value=0.0),
        PrimitiveParameter(name="outer_rim_recess_outer_dia_mm", type="float", unit="mm", required=False, default=450.0, min_value=0.0),
        PrimitiveParameter(name="outer_rim_recess_depth_mm", type="float", unit="mm", required=False, default=2.0, min_value=0.0),
        PrimitiveParameter(name="seal_land_count", type="int", required=False, default=2, min_value=0),
        PrimitiveParameter(name="seal_land_height_mm", type="float", unit="mm", required=False, default=2.0, min_value=0.0),
        PrimitiveParameter(name="seal_land_width_mm", type="float", unit="mm", required=False, default=3.0, min_value=0.0),
        PrimitiveParameter(name="seal_land_start_dia_mm", type="float", unit="mm", required=False, default=155.0, min_value=0.0),
        PrimitiveParameter(name="seal_land_pitch_mm", type="float", unit="mm", required=False, default=8.0, min_value=0.0),

        # ── v0.2 coverplate / balance hole parameters ──
        PrimitiveParameter(name="coverplate_bolt_count", type="int", required=False, default=18, min_value=0),
        PrimitiveParameter(name="coverplate_bolt_pcd_mm", type="float", unit="mm", required=False, default=170.0, min_value=0.0),
        PrimitiveParameter(name="coverplate_bolt_dia_mm", type="float", unit="mm", required=False, default=4.0, min_value=0.0),

        PrimitiveParameter(name="balance_hole_count", type="int", required=False, default=10, min_value=0),
        PrimitiveParameter(name="balance_hole_pcd_mm", type="float", unit="mm", required=False, default=310.0, min_value=0.0),
        PrimitiveParameter(name="balance_hole_dia_mm", type="float", unit="mm", required=False, default=18.0, min_value=0.0),
    ],
    supported_kernels=[
        "cadquery_axisymmetric_revolve_v0",
        "cadquery_turbine_disk_reference_v2",
    ],
    supported_backends=["cadquery", "solidworks2025", "nx12"],
    standards=[],
    validation_defaults={
        "expected_body_count": 1,
        "tolerance_mm": 0.5,
        "non_flight_reference_only": True,
    },
)

TURBOMACHINERY_PRIMITIVES: list[PrimitiveDefinition] = [
    AXISYMMETRIC_TURBINE_DISK,
]
