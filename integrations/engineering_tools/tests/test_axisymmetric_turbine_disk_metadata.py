"""Test axisymmetric_turbine_disk metadata validation."""

import pytest


VALID_TURBINE_METADATA = {
    "primitive": "axisymmetric_turbine_disk",
    "metadata_version": "primitive_metadata_v1",
    "kernel": "cadquery_turbine_disk_reference_v6",
    "parameters": {"outer_dia_mm": 480.0},
    "reference_dimensions": {"outer_dia_mm": 480.0},
    "warnings": ["test warning"],
    "radial_zones": {
        "bore_radius_mm": 40.0,
        "hub_outer_radius_mm": 100.0,
        "web_outer_radius_mm": 170.0,
        "rim_inner_radius_mm": 200.0,
        "outer_radius_mm": 240.0,
    },
    "axial_zones": {
        "rim_z_min_mm": -30.0, "rim_z_max_mm": 30.0,
        "hub_z_min_mm": -30.0, "hub_z_max_mm": 30.0,
        "web_z_min_mm": -16.0, "web_z_max_mm": 16.0,
        "base_z_min_mm": -30.0, "base_z_max_mm": 30.0,
    },
    "profile_points": [[40.0, -30.0], [100.0, -30.0], [240.0, -28.0], [240.0, 28.0]],
    "hole_patterns": [
        {"name": "bolt", "count": 12},
        {"name": "lightening", "count": 8},
        {"name": "cooling", "count": 24},
        {"name": "coverplate_bolt", "count": 0},
        {"name": "balance", "count": 0},
    ],
    "safety": {
        "non_flight_reference_only": True,
        "not_for_manufacturing": True,
        "not_airworthy": True,
        "not_certified": True,
        "not_for_installation": True,
        "no_structural_validation": True,
        "no_life_prediction": True,
    },
    "geometry_family": "axisymmetric_base_with_clean_symmetric_fir_tree_slots",
    "visual_fidelity": {
        "target": "reference_turbine_rotor_disk",
        "contains_cyclic_rim_slots": True,
        "contains_axial_through_rim_slots": True,
        "contains_clean_symmetric_fir_tree_slots": True,
        "contains_box_union_fir_tree_slots": False,
        "contains_hub_sleeve": True,
        "contains_annular_details": True,
        "contains_coverplate_interface": True,
        "contains_real_blade_attachment": False,
    },
    "slot_generation": {
        "version": "rim_slot_v6_clean_symmetric_polygon",
        "orientation": "axial_through",
        "profile_symmetry": "mirror_y",
        "is_mirror_symmetric": True,
        "stage_count": 3,
        "stage_stations": [[264.0, 0.0, "entry"], [260.0, 5.2, "mouth"]],
        "socket_mode": "internal_lobes",
        "exposes_lobes_on_od": False,
        "opens_front_face": True,
        "opens_back_face": True,
        "opens_outer_diameter": True,
        "z_min_mm": -32.0,
        "z_max_mm": 32.0,
        "rim_z_min_mm": -30.0,
        "rim_z_max_mm": 30.0,
        "profile_max_x_mm": 264.0,
        "profile_min_x_mm": 225.0,
        "outer_radius_mm": 240.0,
        "through_clearance_mm": 2.0,
        "outer_clearance_mm": 4.0,
    },
    "rim_features": {
        "slot_count": 60,
        "slot_style": "fir_tree_like",
        "slot_orientation": "axial_through",
        "slot_depth_mm": 35.0,
        "slot_width_mm": 7.0,
        "slot_profile_points_xy": [[240.0, 0.0], [233.0, 3.5], [233.0, -3.5], [240.0, 0.0]],
        "reference_only": True,
    },
    "hub_sleeve": {
        "front_enabled": True,
        "rear_enabled": False,
        "front_outer_dia_mm": 150.0,
        "front_inner_dia_mm": 80.0,
        "front_height_mm": 55.0,
    },
    "annular_details": {
        "enabled": True,
        "mid_web_recess": True,
        "outer_rim_recess": True,
        "seal_lands": 2,
    },
}


def test_generic_metadata_v1_happy_path():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    result = validate_primitive_metadata_v1(
        primitive_name="axisymmetric_turbine_disk",
        metadata=VALID_TURBINE_METADATA,
    )
    assert result["ok"] is True


def test_generic_metadata_v1_warnings_not_list_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    md = dict(VALID_TURBINE_METADATA, warnings="not-a-list")
    result = validate_primitive_metadata_v1(
        primitive_name="axisymmetric_turbine_disk", metadata=md,
    )
    assert result["ok"] is False
    assert any("warnings_not_list" in i["code"] for i in result["issues"])


def test_turbine_metadata_missing_radial_zones_fails():
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.metadata import (
        validate_axisymmetric_turbine_disk_metadata,
    )
    md = dict(VALID_TURBINE_METADATA)
    del md["radial_zones"]
    errors = validate_axisymmetric_turbine_disk_metadata(md)
    assert any("radial_zones" in e for e in errors)


def test_turbine_metadata_missing_safety_fails():
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.metadata import (
        validate_axisymmetric_turbine_disk_metadata,
    )
    md = dict(VALID_TURBINE_METADATA)
    del md["safety"]
    errors = validate_axisymmetric_turbine_disk_metadata(md)
    assert any("safety" in e for e in errors)


def test_turbine_metadata_safety_not_airworthy_fails():
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.metadata import (
        validate_axisymmetric_turbine_disk_metadata,
    )
    md = dict(VALID_TURBINE_METADATA)
    md["safety"] = dict(VALID_TURBINE_METADATA["safety"], not_airworthy=False)
    errors = validate_axisymmetric_turbine_disk_metadata(md)
    assert any("not_airworthy" in e for e in errors)


def test_turbine_metadata_happy_path():
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.metadata import (
        validate_axisymmetric_turbine_disk_metadata,
    )
    errors = validate_axisymmetric_turbine_disk_metadata(VALID_TURBINE_METADATA)
    assert len(errors) == 0


def test_turbine_metadata_missing_hole_pattern_fails():
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.metadata import (
        validate_axisymmetric_turbine_disk_metadata,
    )
    md = dict(VALID_TURBINE_METADATA)
    md["hole_patterns"] = [{"name": "bolt"}, {"name": "lightening"}]  # missing cooling
    errors = validate_axisymmetric_turbine_disk_metadata(md)
    assert any("cooling" in e for e in errors)
