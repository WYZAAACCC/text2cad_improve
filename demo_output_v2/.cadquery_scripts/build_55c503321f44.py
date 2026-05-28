import cadquery as cq
from cadquery import exporters
import json

BUILD_WARNINGS = []
PRIMITIVE_METADATA = {}
result = None
# [Primitive: axisymmetric_turbine_disk]
from seekflow_engineering_tools.geometry_primitives.turbomachinery.axisymmetric_turbine_disk import (
    build_axisymmetric_turbine_disk_cadquery,
)

_params = {
    "outer_dia_mm": 520.0,
    "bore_dia_mm": 86.0,
    "axial_width_mm": 62.0,
    "hub_outer_dia_mm": 210.0,
    "web_outer_dia_mm": 360.0,
    "rim_inner_dia_mm": 420.0,
    "hub_width_mm": 62.0,
    "web_width_mm": 30.0,
    "rim_width_mm": 58.0,
    "hub_fillet_radius_mm": 1.5,
    "web_fillet_radius_mm": 1.0,
    "rim_fillet_radius_mm": 1.0,
    "edge_chamfer_mm": 0.5,
    "bolt_hole_count": 0,
    "bolt_pcd_mm": 0.0,
    "bolt_hole_dia_mm": 0.0,
    "bolt_hole_axis": 'Z',
    "lightening_hole_count": 10,
    "lightening_hole_pcd_mm": 310.0,
    "lightening_hole_dia_mm": 20.0,
    "lightening_hole_axis": 'Z',
    "cooling_hole_count": 36,
    "cooling_hole_pcd_mm": 455.0,
    "cooling_hole_dia_mm": 4.0,
    "cooling_hole_axis": 'Z',
    "quality_grade": 'engineering_reference',
    "non_flight_reference_only": True,
    "rim_slot_count": 60,
    "rim_slot_style": 'fir_tree_like',
    "rim_slot_orientation": 'axial_through',
    "rim_slot_depth_mm": 38.0,
    "rim_slot_width_mm": 7.0,
    "rim_slot_neck_width_mm": 4.5,
    "rim_slot_lobe_width_mm": 9.0,
    "rim_slot_lobe_depth_mm": 7.0,
    "rim_slot_mouth_width_mm": 5.2,
    "rim_slot_throat_width_mm": 4.5,
    "rim_slot_root_width_mm": 5.5,
    "rim_slot_socket_mode": 'internal_lobes',
    "rim_slot_expose_lobes_on_od": False,
    "rim_slot_axial_margin_mm": 0.0,
    "rim_slot_through_clearance_mm": 2.0,
    "rim_slot_outer_clearance_mm": 4.0,
    "rim_slot_root_fillet_mm": 0.0,
    "rim_slot_tip_chamfer_mm": 0.0,
    "front_hub_sleeve_outer_dia_mm": 155.0,
    "front_hub_sleeve_inner_dia_mm": 86.0,
    "front_hub_sleeve_height_mm": 58.0,
    "front_hub_sleeve_wall_mm": 8.0,
    "front_hub_sleeve_chamfer_mm": 1.5,
    "rear_hub_sleeve_outer_dia_mm": 0.0,
    "rear_hub_sleeve_inner_dia_mm": 0.0,
    "rear_hub_sleeve_height_mm": 0.0,
    "rear_hub_sleeve_chamfer_mm": 0.0,
    "enable_annular_details": True,
    "inner_hub_step_outer_dia_mm": 190.0,
    "inner_hub_step_height_mm": 8.0,
    "mid_web_recess_inner_dia_mm": 225.0,
    "mid_web_recess_outer_dia_mm": 365.0,
    "mid_web_recess_depth_mm": 3.0,
    "outer_rim_recess_inner_dia_mm": 395.0,
    "outer_rim_recess_outer_dia_mm": 485.0,
    "outer_rim_recess_depth_mm": 2.0,
    "seal_land_count": 2,
    "seal_land_height_mm": 2.0,
    "seal_land_width_mm": 3.0,
    "seal_land_start_dia_mm": 160.0,
    "seal_land_pitch_mm": 8.0,
    "coverplate_bolt_count": 18,
    "coverplate_bolt_pcd_mm": 175.0,
    "coverplate_bolt_dia_mm": 4.0,
    "coverplate_bolt_axis": 'Z',
    "balance_hole_count": 0,
    "balance_hole_pcd_mm": 0.0,
    "balance_hole_dia_mm": 0.0,
    "balance_hole_axis": 'Z',
}

result, PRIMITIVE_METADATA["axisymmetric_turbine_disk"] = (
    build_axisymmetric_turbine_disk_cadquery(_params)
)

BUILD_WARNINGS.extend(
    PRIMITIVE_METADATA["axisymmetric_turbine_disk"].get("warnings", [])
)

cq.exporters.export(result, r"E:\auto_detection_process\demo_output_v2\models\axisymmetric_turbine_disk.step")

# Write primitive metadata sidecar
_meta_payload = {
    "primitive_metadata": PRIMITIVE_METADATA,
    "build_warnings": BUILD_WARNINGS,
}
with open(r"E:\auto_detection_process\demo_output_v2\models\axisymmetric_turbine_disk.metadata.json", "w", encoding="utf-8") as _f:
    json.dump(_meta_payload, _f, indent=2, ensure_ascii=False, default=str)

if BUILD_WARNINGS:
    for w in BUILD_WARNINGS:
        print(f"CQ_WARNING: {w}")