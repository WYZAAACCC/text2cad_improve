"""Test strict bool parsing — "False" must NOT become True."""

import pytest


def test_parse_bool_false_string_is_false():
    from seekflow_engineering_tools.geometry_primitives.registry import _parse_bool
    assert _parse_bool("False", "non_flight_reference_only") is False
    assert _parse_bool("false", "non_flight_reference_only") is False
    assert _parse_bool("0", "non_flight_reference_only") is False
    assert _parse_bool("no", "non_flight_reference_only") is False
    assert _parse_bool("n", "non_flight_reference_only") is False


def test_parse_bool_true_string_is_true():
    from seekflow_engineering_tools.geometry_primitives.registry import _parse_bool
    assert _parse_bool("True", "non_flight_reference_only") is True
    assert _parse_bool("true", "non_flight_reference_only") is True
    assert _parse_bool("1", "non_flight_reference_only") is True
    assert _parse_bool("yes", "non_flight_reference_only") is True
    assert _parse_bool("y", "non_flight_reference_only") is True


def test_parse_bool_passthrough_bool():
    from seekflow_engineering_tools.geometry_primitives.registry import _parse_bool
    assert _parse_bool(True, "flag") is True
    assert _parse_bool(False, "flag") is False


def test_parse_bool_rejects_ambiguous_string():
    from seekflow_engineering_tools.geometry_primitives.registry import _parse_bool
    with pytest.raises(ValueError):
        _parse_bool("maybe", "non_flight_reference_only")


def test_parse_bool_rejects_number():
    from seekflow_engineering_tools.geometry_primitives.registry import _parse_bool
    with pytest.raises(ValueError):
        _parse_bool(42, "non_flight_reference_only")
