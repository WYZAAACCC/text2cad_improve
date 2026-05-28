"""Test axisymmetric_turbine_disk parameter validation."""

import pytest


VALID_PARAMS = {
    "outer_dia_mm": 480.0,
    "bore_dia_mm": 80.0,
    "axial_width_mm": 60.0,
    "hub_outer_dia_mm": 200.0,
    "web_outer_dia_mm": 340.0,
    "rim_inner_dia_mm": 400.0,
    "hub_width_mm": 60.0,
    "web_width_mm": 32.0,
    "rim_width_mm": 56.0,
    "hub_fillet_radius_mm": 0.0,
    "web_fillet_radius_mm": 0.0,
    "rim_fillet_radius_mm": 0.0,
    "edge_chamfer_mm": 0.0,
    "bolt_hole_count": 12,
    "bolt_pcd_mm": 140.0,
    "bolt_hole_dia_mm": 10.0,
    "bolt_hole_axis": "Z",
    "lightening_hole_count": 8,
    "lightening_hole_pcd_mm": 280.0,
    "lightening_hole_dia_mm": 24.0,
    "lightening_hole_axis": "Z",
    "cooling_hole_count": 24,
    "cooling_hole_pcd_mm": 430.0,
    "cooling_hole_dia_mm": 5.0,
    "cooling_hole_axis": "Z",
    "quality_grade": "concept_geometry",
    "non_flight_reference_only": True,
}


def test_normalize_happy_path():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    result = normalize_primitive_parameters("axisymmetric_turbine_disk", dict(VALID_PARAMS))
    assert result["outer_dia_mm"] == 480.0
    assert result["non_flight_reference_only"] is True


def test_invalid_diameter_ordering_fails():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    p = dict(VALID_PARAMS, hub_outer_dia_mm=500.0)  # hub > outer
    with pytest.raises(ValueError, match="Diameter ordering"):
        normalize_primitive_parameters("axisymmetric_turbine_disk", p)


def test_non_flight_reference_only_false_fails():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    p = dict(VALID_PARAMS, non_flight_reference_only="False")
    with pytest.raises(ValueError, match="non_flight_reference_only"):
        normalize_primitive_parameters("axisymmetric_turbine_disk", p)


def test_quality_grade_flight_ready_fails():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    p = dict(VALID_PARAMS, quality_grade="flight_ready")
    with pytest.raises(ValueError, match="quality_grade"):
        normalize_primitive_parameters("axisymmetric_turbine_disk", p)


def test_count_zero_pcd_nonzero_fails():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    p = dict(VALID_PARAMS, bolt_hole_count=0, bolt_pcd_mm=100.0)
    with pytest.raises(ValueError, match="bolt_pcd_mm must be 0"):
        normalize_primitive_parameters("axisymmetric_turbine_disk", p)


def test_count_positive_pcd_zero_fails():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    p = dict(VALID_PARAMS, bolt_hole_count=6, bolt_pcd_mm=0.0)
    with pytest.raises(ValueError, match="bolt_pcd_mm must be > 0"):
        normalize_primitive_parameters("axisymmetric_turbine_disk", p)


def test_axis_not_z_fails():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    p = dict(VALID_PARAMS, bolt_hole_axis="X")
    with pytest.raises(ValueError, match="bolt_hole_axis"):
        normalize_primitive_parameters("axisymmetric_turbine_disk", p)


def test_bore_geq_hub_fails():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    p = dict(VALID_PARAMS, bore_dia_mm=250.0, hub_outer_dia_mm=200.0)
    with pytest.raises(ValueError, match="Diameter ordering"):
        normalize_primitive_parameters("axisymmetric_turbine_disk", p)


def test_count_positive_dia_zero_fails():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    p = dict(VALID_PARAMS, bolt_hole_count=6, bolt_hole_dia_mm=0.0)
    with pytest.raises(ValueError, match="bolt_hole_dia_mm must be > 0"):
        normalize_primitive_parameters("axisymmetric_turbine_disk", p)


def test_missing_required_param_fails():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        normalize_primitive_parameters,
    )
    p = dict(VALID_PARAMS)
    del p["outer_dia_mm"]
    with pytest.raises(ValueError, match="Missing required parameter"):
        normalize_primitive_parameters("axisymmetric_turbine_disk", p)
