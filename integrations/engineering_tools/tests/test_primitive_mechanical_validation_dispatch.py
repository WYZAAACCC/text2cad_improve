"""Test PRIMITIVE_MECHANICAL_VALIDATORS dispatch."""

import json
import tempfile
from pathlib import Path
import pytest


def test_gear_validator_registered():
    from seekflow_engineering_tools.mechanical_validation.common import (
        list_primitive_mechanical_validator_names,
        PRIMITIVE_MECHANICAL_VALIDATORS,
    )
    names = list_primitive_mechanical_validator_names()
    assert "involute_spur_gear" in names
    assert callable(PRIMITIVE_MECHANICAL_VALIDATORS["involute_spur_gear"])


def test_unregistered_primitive_fails_closed():
    """validate_mechanical_primitives must return ok=False for unregistered primitives."""
    from seekflow_engineering_tools.mechanical_validation.common import (
        validate_mechanical_primitives,
    )

    class FakeFeature:
        type = "primitive"
        primitive_name = "nonexistent_xyz"
        parameters = {}
        id = "f1"

    class FakeSpec:
        features = [FakeFeature()]
        validation = type("v", (), {"tolerance_mm": 0.1, "primitive_validation": {}})()

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("dummy")
        result = validate_mechanical_primitives(FakeSpec(), step, {})
        assert result["ok"] is False
        assert any(
            "missing" in i["code"].lower()
            for r in result["results"] for i in r.get("issues", [])
        )


def test_gear_validation_works_through_registry():
    from seekflow_engineering_tools.mechanical_validation.common import (
        validate_mechanical_primitives,
    )

    class FakeFeature:
        type = "primitive"
        primitive_name = "involute_spur_gear"
        parameters = {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}
        id = "gear1"

    class FakeSpec:
        features = [FakeFeature()]
        validation = type("v", (), {
            "tolerance_mm": 0.5,
            "expected_kernel": "cq_gears",
            "primitive_validation": {},
        })()

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("dummy")
        # Write valid metadata
        meta = {
            "primitive_metadata": {
                "involute_spur_gear": {
                    "kernel": "cq_gears",
                    "primitive": "involute_spur_gear",
                    "is_standard_involute": True,
                    "parameters": {
                        "module_mm": 2.0, "teeth": 24,
                        "face_width_mm": 15.0, "pressure_angle_deg": 20.0,
                    },
                    "reference_dimensions": {
                        "pitch_diameter_mm": 48.0,
                        "base_diameter_mm": 45.105,
                        "outer_diameter_mm": 52.0,
                        "root_diameter_mm": 43.0,
                    },
                },
            },
            "build_warnings": [],
        }
        meta_path = step.with_suffix(".metadata.json")
        meta_path.write_text(json.dumps(meta))

        inspection = {"bbox_mm": [52.0, 52.0, 15.0]}
        result = validate_mechanical_primitives(FakeSpec(), step, inspection)
        assert result["ok"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["kernel"] == "cq_gears"


def test_primitive_validation_merged_to_expected():
    """Per-feature primitive_validation dict should be merged into expected."""
    from seekflow_engineering_tools.mechanical_validation.common import (
        validate_mechanical_primitives,
    )

    class FakeFeature:
        type = "primitive"
        primitive_name = "involute_spur_gear"
        parameters = {
            "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
        }
        id = "custom_gear_1"

    from seekflow_engineering_tools.ir.cad import ValidationSpec

    class FakeSpec:
        features = [FakeFeature()]
        validation = ValidationSpec(
            tolerance_mm=0.5,
            expected_kernel="cq_gears",
            primitive_validation={
                "custom_gear_1": {"extra_custom_field": "present"},
            },
        )

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("dummy")
        meta = {
            "primitive_metadata": {
                "involute_spur_gear": {
                    "kernel": "cq_gears",
                    "primitive": "involute_spur_gear",
                    "is_standard_involute": True,
                    "parameters": {
                        "module_mm": 2.0, "teeth": 24,
                        "face_width_mm": 15.0, "pressure_angle_deg": 20.0,
                    },
                    "reference_dimensions": {
                        "pitch_diameter_mm": 48.0,
                        "base_diameter_mm": 45.105,
                        "outer_diameter_mm": 52.0,
                        "root_diameter_mm": 43.0,
                    },
                },
            },
            "build_warnings": [],
        }
        meta_path = step.with_suffix(".metadata.json")
        meta_path.write_text(json.dumps(meta))

        inspection = {"bbox_mm": [52.0, 52.0, 15.0]}
        result = validate_mechanical_primitives(FakeSpec(), step, inspection)
        # Should pass — primitive_validation is handled
        assert result["ok"] is True


def test_duplicate_validator_registration_fails():
    from seekflow_engineering_tools.mechanical_validation.common import (
        register_primitive_mechanical_validator,
    )

    def dummy(*a, **kw):
        return {"ok": True, "issues": [], "reference_dimensions": {}, "kernel": "x"}

    with pytest.raises(RuntimeError, match="Duplicate"):
        register_primitive_mechanical_validator("involute_spur_gear", dummy)
