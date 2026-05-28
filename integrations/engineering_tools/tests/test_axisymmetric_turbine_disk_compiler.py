"""Test axisymmetric_turbine_disk compiler registration."""

import pytest


def test_axisymmetric_turbine_disk_compiler_registered():
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        list_primitive_compiler_names,
    )
    assert "axisymmetric_turbine_disk" in list_primitive_compiler_names()


def test_axisymmetric_turbine_disk_compiler_uses_kernel():
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        compile_primitive_to_cadquery_script,
    )
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    feature = PrimitiveFeature(
        id="disk1",
        type="primitive",
        primitive_name="axisymmetric_turbine_disk",
        parameters={
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
            "bolt_hole_count": 0,
            "bolt_pcd_mm": 0.0,
            "bolt_hole_dia_mm": 0.0,
            "bolt_hole_axis": "Z",
            "lightening_hole_count": 0,
            "lightening_hole_pcd_mm": 0.0,
            "lightening_hole_dia_mm": 0.0,
            "lightening_hole_axis": "Z",
            "cooling_hole_count": 0,
            "cooling_hole_pcd_mm": 0.0,
            "cooling_hole_dia_mm": 0.0,
            "cooling_hole_axis": "Z",
            "quality_grade": "concept_geometry",
            "non_flight_reference_only": True,
        },
    )

    lines = compile_primitive_to_cadquery_script(feature)
    script = "\n".join(lines)

    assert "build_axisymmetric_turbine_disk_cadquery" in script
    assert 'PRIMITIVE_METADATA["axisymmetric_turbine_disk"]' in script


def test_unknown_primitive_compiler_fails():
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        compile_primitive_to_cadquery_script,
        PrimitiveCompileError,
    )
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    feature = PrimitiveFeature(
        id="ghost1",
        type="primitive",
        primitive_name="nonexistent_primitive_xyz",
        parameters={},
    )
    with pytest.raises(PrimitiveCompileError, match="Unknown primitive"):
        compile_primitive_to_cadquery_script(feature)
