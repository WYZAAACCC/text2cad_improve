"""Test turbine disk v0.2 visual features — rim slots, hub sleeve, annular details."""

import pytest


def test_turbine_disk_v2_rim_slot_style_rejects_invalid():
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.validator import (
        validate_axisymmetric_turbine_disk_parameters,
    )
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    norm = normalize_primitive_parameters("axisymmetric_turbine_disk", {
        "outer_dia_mm": 520.0,
        "bore_dia_mm": 86.0,
        "axial_width_mm": 62.0,
        "hub_outer_dia_mm": 210.0,
        "web_outer_dia_mm": 360.0,
        "rim_inner_dia_mm": 420.0,
        "hub_width_mm": 62.0,
        "web_width_mm": 30.0,
        "rim_width_mm": 58.0,
        "quality_grade": "concept_geometry",
        "non_flight_reference_only": True,
        "rim_slot_style": "invalid_style_xyz",
    })
    errors = validate_axisymmetric_turbine_disk_parameters(norm)
    assert any("rim_slot_style" in e for e in errors)


def test_turbine_disk_v2_style_none_requires_count_zero():
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.validator import (
        validate_axisymmetric_turbine_disk_parameters,
    )
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    norm = normalize_primitive_parameters("axisymmetric_turbine_disk", {
        "outer_dia_mm": 520.0,
        "bore_dia_mm": 86.0,
        "axial_width_mm": 62.0,
        "hub_outer_dia_mm": 210.0,
        "web_outer_dia_mm": 360.0,
        "rim_inner_dia_mm": 420.0,
        "hub_width_mm": 62.0,
        "web_width_mm": 30.0,
        "rim_width_mm": 58.0,
        "quality_grade": "concept_geometry",
        "non_flight_reference_only": True,
        "rim_slot_style": "none",
        "rim_slot_count": 60,
    })
    errors = validate_axisymmetric_turbine_disk_parameters(norm)
    assert any("rim_slot_count" in e for e in errors)


def test_turbine_disk_v2_slot_depth_too_large_fails():
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.validator import (
        validate_axisymmetric_turbine_disk_parameters,
    )
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    norm = normalize_primitive_parameters("axisymmetric_turbine_disk", {
        "outer_dia_mm": 520.0,
        "bore_dia_mm": 86.0,
        "axial_width_mm": 62.0,
        "hub_outer_dia_mm": 210.0,
        "web_outer_dia_mm": 360.0,
        "rim_inner_dia_mm": 420.0,
        "hub_width_mm": 62.0,
        "web_width_mm": 30.0,
        "rim_width_mm": 58.0,
        "quality_grade": "concept_geometry",
        "non_flight_reference_only": True,
        "rim_slot_style": "fir_tree_like",
        "rim_slot_count": 60,
        "rim_slot_depth_mm": 200.0,  # way too deep
        "rim_slot_width_mm": 7.0,
        "rim_slot_neck_width_mm": 4.5,
        "rim_slot_lobe_width_mm": 8.5,
        "rim_slot_lobe_depth_mm": 7.0,
        "rim_slot_axial_margin_mm": 4.0,
    })
    errors = validate_axisymmetric_turbine_disk_parameters(norm)
    assert any("too large" in e or "too deeply" in e for e in errors)


def test_turbine_disk_v2_slots_too_wide_fails():
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.validator import (
        validate_axisymmetric_turbine_disk_parameters,
    )
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    norm = normalize_primitive_parameters("axisymmetric_turbine_disk", {
        "outer_dia_mm": 520.0,
        "bore_dia_mm": 86.0,
        "axial_width_mm": 62.0,
        "hub_outer_dia_mm": 210.0,
        "web_outer_dia_mm": 360.0,
        "rim_inner_dia_mm": 420.0,
        "hub_width_mm": 62.0,
        "web_width_mm": 30.0,
        "rim_width_mm": 58.0,
        "quality_grade": "concept_geometry",
        "non_flight_reference_only": True,
        "rim_slot_style": "rectangular",
        "rim_slot_count": 60,
        "rim_slot_depth_mm": 38.0,
        "rim_slot_width_mm": 50.0,  # too wide for 60 slots at r=260
        "rim_slot_axial_margin_mm": 4.0,
    })
    errors = validate_axisymmetric_turbine_disk_parameters(norm)
    assert any("overlap" in e or "too large" in e for e in errors)


def test_turbine_disk_v2_front_hub_sleeve_diameter_ordering():
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.validator import (
        validate_axisymmetric_turbine_disk_parameters,
    )
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    norm = normalize_primitive_parameters("axisymmetric_turbine_disk", {
        "outer_dia_mm": 520.0,
        "bore_dia_mm": 86.0,
        "axial_width_mm": 62.0,
        "hub_outer_dia_mm": 210.0,
        "web_outer_dia_mm": 360.0,
        "rim_inner_dia_mm": 420.0,
        "hub_width_mm": 62.0,
        "web_width_mm": 30.0,
        "rim_width_mm": 58.0,
        "quality_grade": "concept_geometry",
        "non_flight_reference_only": True,
        "front_hub_sleeve_outer_dia_mm": 80.0,
        "front_hub_sleeve_inner_dia_mm": 150.0,  # inner > outer
        "front_hub_sleeve_height_mm": 55.0,
    })
    errors = validate_axisymmetric_turbine_disk_parameters(norm)
    assert any("hub_sleeve" in e for e in errors)


def test_turbine_disk_v2_supported_kernels():
    from seekflow_engineering_tools.geometry_primitives.registry import get_primitive
    pd = get_primitive("axisymmetric_turbine_disk")
    assert pd is not None
    assert "cadquery_turbine_disk_reference_v2" in pd.supported_kernels
