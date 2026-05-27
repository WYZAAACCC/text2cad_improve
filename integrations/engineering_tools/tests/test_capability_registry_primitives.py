"""Test capability registry primitive support."""

import pytest


def test_cadquery_has_stable_primitives():
    from seekflow_engineering_tools.capabilities.registry import CAPABILITIES

    cq = CAPABILITIES["cadquery"]
    assert "stable_primitives" in cq
    assert "involute_spur_gear" in cq["stable_primitives"]
    assert cq["primitive_strategy"]["involute_spur_gear"] == "native_cadquery_primitive"


def test_solidworks_primitive_strategy():
    from seekflow_engineering_tools.capabilities.registry import CAPABILITIES

    sw = CAPABILITIES["solidworks2025"]
    assert "involute_spur_gear" in sw["stable_primitives"]
    assert sw["primitive_strategy"]["involute_spur_gear"] == "cadquery_step_import"


def test_nx_primitive_strategy():
    from seekflow_engineering_tools.capabilities.registry import CAPABILITIES

    nx = CAPABILITIES["nx12"]
    assert "involute_spur_gear" in nx["stable_primitives"]
    assert nx["primitive_strategy"]["involute_spur_gear"] == "cadquery_step_import"


def test_backend_supports_primitive_feature():
    from seekflow_engineering_tools.capabilities.registry import backend_supports_feature
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    gear_feat = PrimitiveFeature(
        id="g1", primitive_name="involute_spur_gear",
        parameters={"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0},
    )

    assert backend_supports_feature("cadquery", gear_feat) is True
    assert backend_supports_feature("solidworks2025", gear_feat) is True
    assert backend_supports_feature("nx12", gear_feat) is True


def test_get_primitive_strategy():
    from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

    assert get_primitive_strategy("cadquery", "involute_spur_gear") == "native_cadquery_primitive"
    assert get_primitive_strategy("solidworks2025", "involute_spur_gear") == "cadquery_step_import"
    assert get_primitive_strategy("nx12", "involute_spur_gear") == "cadquery_step_import"


def test_choose_backend_with_primitive():
    from seekflow_engineering_tools.capabilities.registry import choose_backend
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    spec = CADPartSpec(
        name="test_gear",
        features=[
            PrimitiveFeature(
                id="g1", primitive_name="involute_spur_gear",
                parameters={"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0},
            ),
        ],
    )

    choice = choose_backend(spec, preferred=["cadquery"])
    assert choice.backend == "cadquery"

    # SW supports this primitive (via step_import strategy), so SW should be selected
    choice_sw = choose_backend(spec, preferred=["solidworks2025"])
    assert choice_sw.backend == "solidworks2025"
