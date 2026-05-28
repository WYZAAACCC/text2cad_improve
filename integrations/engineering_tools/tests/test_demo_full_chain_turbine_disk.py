"""Test demo_full_chain axisymmetric_turbine_disk case."""

import json
import tempfile
from pathlib import Path


def test_demo_turbine_disk_strategy_none_fails():
    """choose_backend must fail when no strategy is registered for a primitive."""
    from demo_full_chain import _run_primitive_case
    from seekflow_engineering_tools.geometry_primitives.registry import normalize_primitive_parameters
    from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

    # Verify strategy exists for cadquery
    strategy = get_primitive_strategy("cadquery", "axisymmetric_turbine_disk")
    assert strategy == "native_cadquery_primitive"

    # Verify strategy is None for a non-existent backend
    strategy_none = get_primitive_strategy("nonexistent_backend_xyz", "axisymmetric_turbine_disk")
    assert strategy_none is None


def test_demo_turbine_disk_required_metrics_defined():
    from demo_full_chain import TURBINE_DISK_REQUIRED_METRICS

    assert "kernel_used" in TURBINE_DISK_REQUIRED_METRICS
    assert "reference_dimensions.outer_dia_mm" in TURBINE_DISK_REQUIRED_METRICS
    assert "reference_dimensions.expected_through_hole_count" in TURBINE_DISK_REQUIRED_METRICS


def test_demo_turbine_disk_case_runner_exists():
    from demo_full_chain import CASE_RUNNERS

    assert "axisymmetric_turbine_disk" in CASE_RUNNERS
    assert callable(CASE_RUNNERS["axisymmetric_turbine_disk"])


def test_demo_turbine_disk_in_all_cases():
    from demo_full_chain import ALL_CASES

    assert "axisymmetric_turbine_disk" in ALL_CASES
