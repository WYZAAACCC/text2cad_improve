"""Test primitive compiler handler registry."""

import pytest


def test_gear_compiler_registered():
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        list_primitive_compiler_names, PRIMITIVE_COMPILERS,
    )
    names = list_primitive_compiler_names()
    assert "involute_spur_gear" in names
    assert callable(PRIMITIVE_COMPILERS["involute_spur_gear"])


def test_unknown_compiler_raises():
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        compile_primitive_to_cadquery_script, PrimitiveCompileError,
    )

    class FakeFeature:
        primitive_name = "nonexistent_xyz"

    with pytest.raises(PrimitiveCompileError, match="Unknown primitive"):
        compile_primitive_to_cadquery_script(FakeFeature())


def test_duplicate_registration_fails():
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        register_primitive_compiler, PrimitiveCompileError,
    )

    def dummy(feature):
        return ["# dummy"]

    with pytest.raises(PrimitiveCompileError, match="Duplicate"):
        register_primitive_compiler("involute_spur_gear", dummy)


def test_compiler_produces_valid_lines():
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        compile_primitive_to_cadquery_script,
    )

    class FakeFeature:
        primitive_name = "involute_spur_gear"
        parameters = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
                       "bore_dia_mm": 10.0}

    lines = compile_primitive_to_cadquery_script(FakeFeature())
    assert isinstance(lines, list)
    assert len(lines) > 0
    full = "\n".join(lines)
    assert "involute_spur_gear" in full
    assert "cq_gears_available" in full


def test_temporary_fake_compiler_can_be_registered_and_called():
    """A new compiler can be temporarily registered and used."""
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        register_primitive_compiler, compile_primitive_to_cadquery_script,
        PRIMITIVE_COMPILERS, list_primitive_compiler_names,
    )

    def fake_compiler(feature) -> list[str]:
        return [f"# Fake compile for {feature.primitive_name}"]

    # Register and verify
    register_primitive_compiler("_test_fake_primitive", fake_compiler)
    try:
        assert "_test_fake_primitive" in list_primitive_compiler_names()

        class FakeFeature:
            primitive_name = "_test_fake_primitive"
            parameters = {}

        lines = compile_primitive_to_cadquery_script(FakeFeature())
        assert any("Fake compile" in l for l in lines)
    finally:
        # Clean up
        PRIMITIVE_COMPILERS.pop("_test_fake_primitive", None)
