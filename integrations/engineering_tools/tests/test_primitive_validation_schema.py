"""Test ValidationSpec.primitive_validation schema constraints."""

import pytest


def test_primitive_validation_accepts_dict():
    from seekflow_engineering_tools.ir.cad import ValidationSpec
    vs = ValidationSpec(
        primitive_validation={"f1": {"expected_kernel": "test"}}
    )
    assert vs.primitive_validation["f1"]["expected_kernel"] == "test"


def test_primitive_validation_defaults_to_empty_dict():
    from seekflow_engineering_tools.ir.cad import ValidationSpec
    vs = ValidationSpec()
    assert vs.primitive_validation == {}


def test_primitive_validation_rejects_empty_key():
    from seekflow_engineering_tools.ir.cad import ValidationSpec
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ValidationSpec(primitive_validation={"": {"x": 1}})


def test_primitive_validation_rejects_whitespace_key():
    from seekflow_engineering_tools.ir.cad import ValidationSpec
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ValidationSpec(primitive_validation={"   ": {"x": 1}})


def test_primitive_validation_rejects_non_dict_value():
    from seekflow_engineering_tools.ir.cad import ValidationSpec
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ValidationSpec(primitive_validation={"f1": "not_a_dict"})


def test_existing_expected_fields_still_work():
    from seekflow_engineering_tools.ir.cad import ValidationSpec
    vs = ValidationSpec(
        expected_bbox_mm=[100, 50, 25],
        expected_body_count=1,
        expected_kernel="cq_gears",
        expected_tooth_count=24,
        primitive_validation={"gear1": {"extra": True}},
    )
    assert vs.expected_bbox_mm == [100, 50, 25]
    assert vs.expected_kernel == "cq_gears"
    assert vs.expected_tooth_count == 24
    assert vs.primitive_validation["gear1"] == {"extra": True}
