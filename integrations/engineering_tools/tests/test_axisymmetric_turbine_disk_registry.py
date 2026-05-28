"""Test axisymmetric_turbine_disk primitive registration."""

import pytest


def test_axisymmetric_turbine_disk_registered():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        get_primitive,
        list_primitive_names,
    )
    assert "axisymmetric_turbine_disk" in list_primitive_names()

    pd = get_primitive("axisymmetric_turbine_disk")
    assert pd is not None
    assert pd.category == "turbomachinery"
    assert "cadquery_axisymmetric_revolve_v0" in pd.supported_kernels


def test_axisymmetric_turbine_disk_backend_support():
    from seekflow_engineering_tools.geometry_primitives.registry import (
        backend_supports_primitive,
    )
    assert backend_supports_primitive("cadquery", "axisymmetric_turbine_disk")
    assert backend_supports_primitive("solidworks2025", "axisymmetric_turbine_disk")
    assert backend_supports_primitive("nx12", "axisymmetric_turbine_disk")


def test_axisymmetric_turbine_disk_capability_strategies():
    from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

    assert get_primitive_strategy("cadquery", "axisymmetric_turbine_disk") == "native_cadquery_primitive"
    assert get_primitive_strategy("solidworks2025", "axisymmetric_turbine_disk") == "cadquery_step_import"
    assert get_primitive_strategy("nx12", "axisymmetric_turbine_disk") == "cadquery_step_import"


def test_axisymmetric_turbine_disk_in_stable_primitives():
    from seekflow_engineering_tools.capabilities.registry import CAPABILITIES

    for backend in ["cadquery", "solidworks2025", "nx12"]:
        stable = CAPABILITIES.get(backend, {}).get("stable_primitives", [])
        assert "axisymmetric_turbine_disk" in stable, (
            f"axisymmetric_turbine_disk missing from {backend}.stable_primitives"
        )
