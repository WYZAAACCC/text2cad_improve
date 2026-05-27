"""Test PrimitiveFeature Pydantic schema and CADPartSpec integration."""

import pytest


def test_primitive_feature_model():
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    pf = PrimitiveFeature(
        id="gear1",
        type="primitive",
        primitive_name="involute_spur_gear",
        parameters={"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0},
    )

    assert pf.id == "gear1"
    assert pf.type == "primitive"
    assert pf.primitive_name == "involute_spur_gear"
    assert pf.operation == "new_body"  # default
    assert pf.placement == {}  # default


def test_primitive_feature_empty_name_rejected():
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    with pytest.raises(ValueError):
        PrimitiveFeature(
            id="bad",
            type="primitive",
            primitive_name="",  # empty
            parameters={},
        )

    with pytest.raises(ValueError):
        PrimitiveFeature(
            id="bad",
            type="primitive",
            primitive_name="   ",  # whitespace only
            parameters={},
        )


def test_primitive_feature_in_cad_part_spec():
    from seekflow_engineering_tools.ir.cad import CADPartSpec, PrimitiveFeature

    spec = CADPartSpec(
        name="test_gear",
        units="mm",
        features=[
            PrimitiveFeature(
                id="gear1",
                primitive_name="involute_spur_gear",
                parameters={"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0},
            ),
        ],
    )

    assert len(spec.features) == 1
    feat = spec.features[0]
    assert feat.type == "primitive"
    assert feat.primitive_name == "involute_spur_gear"


def test_primitive_feature_from_dict():
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    spec = CADPartSpec.model_validate({
        "name": "test_gear",
        "units": "mm",
        "features": [{
            "id": "gear1",
            "type": "primitive",
            "primitive_name": "involute_spur_gear",
            "parameters": {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0},
        }],
    })

    feat = spec.features[0]
    assert feat.type == "primitive"
    assert feat.primitive_name == "involute_spur_gear"


def test_extra_fields_forbidden_on_primitive():
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    with pytest.raises(ValueError):
        PrimitiveFeature(
            id="gear1",
            type="primitive",
            primitive_name="involute_spur_gear",
            parameters={},
            extra_unknown_field=123,
        )
