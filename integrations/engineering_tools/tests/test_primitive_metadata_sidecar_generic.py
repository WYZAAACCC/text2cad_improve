"""Test builder _assert_metadata_sidecar with generic validator."""

import json
import tempfile
from pathlib import Path
import pytest


_META = {
    "primitive_metadata": {
        "involute_spur_gear": {
            "kernel": "cq_gears",
            "primitive": "involute_spur_gear",
            "is_standard_involute": True,
            "parameters": {"module_mm": 2.0, "teeth": 24},
            "reference_dimensions": {"pitch_diameter_mm": 48.0},
        },
    },
    "build_warnings": [],
}


def _write_sidecar(step_path, data):
    meta_path = step_path.with_suffix(".metadata.json")
    meta_path.write_text(json.dumps(data))
    return meta_path


def test_sidecar_valid_passes():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("dummy")
        _write_sidecar(step, _META)
        spec = CADPartSpec(name="test", features=[
            PrimitiveFeature(id="g1", primitive_name="involute_spur_gear",
                             parameters={"module_mm": 2.0, "teeth": 24})
        ])
        loaded = _assert_metadata_sidecar(step, spec)
        assert loaded["primitive_metadata"]["involute_spur_gear"]["kernel"] == "cq_gears"


def test_sidecar_requires_primitive_metadata_top_key():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("x")
        _write_sidecar(step, {"build_warnings": [], "other": {}})
        spec = CADPartSpec(name="test", features=[])
        with pytest.raises(ValueError, match="primitive_metadata"):
            _assert_metadata_sidecar(step, spec)


def test_sidecar_requires_build_warnings_top_key():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("x")
        _write_sidecar(step, {"primitive_metadata": {}})
        spec = CADPartSpec(name="test", features=[])
        with pytest.raises(ValueError, match="build_warnings"):
            _assert_metadata_sidecar(step, spec)


def test_sidecar_requires_entry_for_primitive_feature():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("x")
        data = {
            "primitive_metadata": {},  # empty — no entry for involute_spur_gear
            "build_warnings": [],
        }
        _write_sidecar(step, data)
        spec = CADPartSpec(name="test", features=[
            PrimitiveFeature(id="g1", primitive_name="involute_spur_gear",
                             parameters={"module_mm": 2.0, "teeth": 24})
        ])
        with pytest.raises(ValueError, match="missing primitive entry"):
            _assert_metadata_sidecar(step, spec)


def test_sidecar_gear_requires_is_standard_involute():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("x")
        data = {
            "primitive_metadata": {
                "involute_spur_gear": {
                    "kernel": "cq_gears",
                    "primitive": "involute_spur_gear",
                    "parameters": {"module_mm": 2.0, "teeth": 24},
                    "reference_dimensions": {"pitch_diameter_mm": 48.0},
                    # missing is_standard_involute!
                },
            },
            "build_warnings": [],
        }
        _write_sidecar(step, data)
        spec = CADPartSpec(name="test", features=[
            PrimitiveFeature(id="g1", primitive_name="involute_spur_gear",
                             parameters={"module_mm": 2.0, "teeth": 24})
        ])
        with pytest.raises(ValueError, match="is_standard_involute"):
            _assert_metadata_sidecar(step, spec)


def test_sidecar_fails_on_missing_kernel():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("x")
        data = {
            "primitive_metadata": {
                "involute_spur_gear": {
                    "primitive": "involute_spur_gear",
                    "is_standard_involute": True,
                    "parameters": {"module_mm": 2.0},
                    "reference_dimensions": {"pitch_diameter_mm": 48.0},
                    # missing kernel!
                },
            },
            "build_warnings": [],
        }
        _write_sidecar(step, data)
        spec = CADPartSpec(name="test", features=[
            PrimitiveFeature(id="g1", primitive_name="involute_spur_gear",
                             parameters={"module_mm": 2.0, "teeth": 24})
        ])
        with pytest.raises(ValueError, match="kernel"):
            _assert_metadata_sidecar(step, spec)


def test_build_warnings_non_list_fails():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("x")
        data = {
            "primitive_metadata": {},
            "build_warnings": "not_a_list",  # must be list
        }
        _write_sidecar(step, data)
        spec = CADPartSpec(name="test", features=[])
        with pytest.raises(ValueError, match="build_warnings.*list"):
            _assert_metadata_sidecar(step, spec)


def test_primitive_metadata_not_dict_fails():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("x")
        data = {
            "primitive_metadata": "not_a_dict",  # must be dict
            "build_warnings": [],
        }
        _write_sidecar(step, data)
        spec = CADPartSpec(name="test", features=[])
        with pytest.raises(ValueError, match="primitive_metadata.*dict"):
            _assert_metadata_sidecar(step, spec)


def test_future_fake_primitive_passes_generic_sidecar():
    """A hypothetical future primitive with valid generic metadata passes."""
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("x")
        data = {
            "primitive_metadata": {
                "future_primitive_xyz": {
                    "metadata_version": "primitive_metadata_v1",
                    "kernel": "test_kernel_v2",
                    "primitive": "future_primitive_xyz",
                    "parameters": {"radius_mm": 100.0},
                    "reference_dimensions": {"outer_diameter_mm": 200.0},
                    "warnings": [],
                },
            },
            "build_warnings": [],
        }
        _write_sidecar(step, data)
        spec = CADPartSpec(name="test", features=[
            PrimitiveFeature(id="f1", primitive_name="future_primitive_xyz",
                             parameters={"radius_mm": 100.0})
        ])
        loaded = _assert_metadata_sidecar(step, spec)
        assert loaded["primitive_metadata"]["future_primitive_xyz"]["kernel"] == "test_kernel_v2"
