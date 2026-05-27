"""Test validate_primitive_metadata_v1 for all primitive types."""

import pytest


VALID_METADATA = {
    "kernel": "test_kernel",
    "primitive": "test_primitive_x",
    "parameters": {"p1": 1},
    "reference_dimensions": {"dim1": 10.0},
}


def test_valid_metadata_passes():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= VALID_METADATA)
    assert result["ok"] is True
    assert len(result["issues"]) == 0
    assert result["normalized_metadata"] is not None


def test_missing_metadata_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= None)
    assert result["ok"] is False
    assert any("missing" in i["code"].lower() for i in result["issues"])
    assert result["normalized_metadata"] is None


def test_primitive_mismatch_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    m = dict(VALID_METADATA)  # primitive="test_primitive_x"
    result = validate_primitive_metadata_v1(primitive_name="different_name", metadata=m)
    assert result["ok"] is False
    assert any("mismatch" in i["code"].lower() for i in result["issues"])


def test_missing_kernel_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    m = dict(VALID_METADATA)
    del m["kernel"]
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= m)
    assert result["ok"] is False
    assert any("kernel" in i["code"].lower() for i in result["issues"])


def test_missing_parameters_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    m = dict(VALID_METADATA)
    del m["parameters"]
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= m)
    assert result["ok"] is False
    assert any("parameters" in i["code"].lower() for i in result["issues"])


def test_missing_reference_dimensions_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    m = dict(VALID_METADATA)
    del m["reference_dimensions"]
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= m)
    assert result["ok"] is False
    assert any("reference_dimensions" in i["code"].lower() for i in result["issues"])


def test_kernel_empty_string_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    m = dict(VALID_METADATA, kernel="   ")
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= m)
    assert result["ok"] is False
    assert any("kernel" in i["code"].lower() for i in result["issues"])


def test_parameters_not_dict_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    m = dict(VALID_METADATA, parameters="not_dict")
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= m)
    assert result["ok"] is False
    assert any("parameters" in i["code"].lower() for i in result["issues"])


def test_reference_dimensions_not_dict_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    m = dict(VALID_METADATA, reference_dimensions=[1, 2, 3])
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= m)
    assert result["ok"] is False


def test_warnings_not_list_warns():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    m = dict(VALID_METADATA, warnings="not_a_list")
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata=m)
    issues = result["issues"]
    assert any("warnings" in i["code"].lower() for i in issues)
    # warnings not-list is warning, not error → still ok
    assert result["ok"] is True
    # warnings normalized to []
    assert result["normalized_metadata"]["warnings"] == []


def test_unknown_metadata_version_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    m = dict(VALID_METADATA, metadata_version="v99_broken")
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= m)
    assert result["ok"] is False
    assert any("version" in i["code"].lower() for i in result["issues"])


def test_v1_metadata_version_passes():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    m = dict(VALID_METADATA, metadata_version="primitive_metadata_v1")
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= m)
    assert result["ok"] is True


def test_metadata_not_dict_type_fails():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= "not_a_dict")
    assert result["ok"] is False
    assert any("not_dict" in i["code"].lower() for i in result["issues"])


def test_issue_has_code_message_severity():
    from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
        validate_primitive_metadata_v1,
    )
    result = validate_primitive_metadata_v1(primitive_name="test_primitive_x", metadata= None)
    for issue in result["issues"]:
        assert "code" in issue
        assert "message" in issue
        assert "severity" in issue
        assert issue["severity"] in ("error", "warning")
