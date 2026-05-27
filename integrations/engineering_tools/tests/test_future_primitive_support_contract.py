"""Test contract: future primitives are supported by infrastructure without main-chain changes."""


def test_turbomachinery_family_in_module_list():
    """TURBOMACHINERY_PRIMITIVES module must be in PRIMITIVE_FAMILY_MODULES."""
    from seekflow_engineering_tools.geometry_primitives.registry import (
        PRIMITIVE_FAMILY_MODULES,
    )
    turbomachinery_paths = [p for p in PRIMITIVE_FAMILY_MODULES if "turbomachinery" in p]
    assert len(turbomachinery_paths) == 1, (
        f"Expected exactly one turbomachinery entry in PRIMITIVE_FAMILY_MODULES, "
        f"got {turbomachinery_paths}"
    )


def test_turbomachinery_module_loadable():
    """TURBOMACHINERY_PRIMITIVES must be importable and be an empty list."""
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.models import (
        TURBOMACHINERY_PRIMITIVES,
    )
    assert isinstance(TURBOMACHINERY_PRIMITIVES, list)
    assert len(TURBOMACHINERY_PRIMITIVES) == 0, (
        "TURBOMACHINERY_PRIMITIVES must be empty — no primitives implemented yet"
    )


def test_compiler_registry_supports_register():
    """register_primitive_compiler must be callable."""
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        register_primitive_compiler, list_primitive_compiler_names,
    )
    assert callable(register_primitive_compiler)


def test_mechanical_validator_registry_supports_register():
    """register_primitive_mechanical_validator must be callable."""
    from seekflow_engineering_tools.mechanical_validation.common import (
        register_primitive_mechanical_validator,
        list_primitive_mechanical_validator_names,
    )
    assert callable(register_primitive_mechanical_validator)


def test_metadata_validator_works_for_any_primitive():
    """validate_primitive_metadata_v1 must accept any primitive name."""
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )

    # Test with a hypothetical future primitive name
    result = validate_primitive_metadata_v1(primitive_name="axisymmetric_turbine_disk", metadata={
        "kernel": "test",
        "primitive": "axisymmetric_turbine_disk",
        "parameters": {"outer_radius_mm": 100},
        "reference_dimensions": {"bore_radius_mm": 20},
    })
    assert result["ok"] is True


def test_validation_spec_accepts_primitive_validation():
    """ValidationSpec.primitive_validation field is present and accepts dict."""
    from seekflow_engineering_tools.ir.cad import ValidationSpec
    assert hasattr(ValidationSpec, "model_fields")
    assert "primitive_validation" in ValidationSpec.model_fields


def test_future_primitive_requires_full_implementation():
    """A future primitive needs: definition + compiler + metadata + validator + tests + capability."""
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        list_primitive_compiler_names,
    )
    from seekflow_engineering_tools.mechanical_validation.common import (
        list_primitive_mechanical_validator_names,
    )
    from seekflow_engineering_tools.geometry_primitives.registry import (
        list_primitive_names,
    )
    from seekflow_engineering_tools.capabilities.registry import CAPABILITIES

    # All three registries must have involute_spur_gear (the reference implementation)
    assert "involute_spur_gear" in list_primitive_names()
    assert "involute_spur_gear" in list_primitive_compiler_names()
    assert "involute_spur_gear" in list_primitive_mechanical_validator_names()
    assert "involute_spur_gear" in CAPABILITIES["cadquery"]["stable_primitives"]

    # axisymmetric_turbine_disk must be in NONE of these (not implemented)
    assert "axisymmetric_turbine_disk" not in list_primitive_names()
    assert "axisymmetric_turbine_disk" not in list_primitive_compiler_names()
    assert "axisymmetric_turbine_disk" not in list_primitive_mechanical_validator_names()
