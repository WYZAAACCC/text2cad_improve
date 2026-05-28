"""Test axisymmetric_turbine_disk metadata validation."""

import pytest


VALID_TURBINE_METADATA = {
    "primitive": "axisymmetric_turbine_disk",
    "metadata_version": "primitive_metadata_v1",
    "kernel": "cadquery_axisymmetric_revolve_v0",
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
    "profile_points": [[40.0, -30.0], [100.0, -30.0], [240.0, -28.0], [240.0, 28.0]],
    "hole_patterns": [
        {"name": "bolt", "count": 12},
        {"name": "lightening", "count": 8},
        {"name": "cooling", "count": 24},
    ],
    "safety": {
        "non_flight_reference_only": True,
        "not_for_manufacturing": True,
        "not_airworthy": True,
        "not_certified": True,
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
