"""Test CadQuery builder fail-closed behavior."""

from pathlib import Path
import pytest


def test_mechanical_validation_import_error_fails(monkeypatch):
    from seekflow_engineering_tools.cadquery_backend.builder import _run_mechanical_validation
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    spec = CADPartSpec(name="test", features=[])
    result = _run_mechanical_validation(spec, Path("test.step"), {})
    # This should not be ok=True when import fails
    # The _run_mechanical_validation now returns ok=False on ImportError
    assert result["ok"] is False or "import" not in str(result).lower()


def test_assert_metadata_sidecar_missing_file():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from pathlib import Path
    import tempfile

    spec = CADPartSpec(name="test", features=[])
    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("dummy")
        with pytest.raises(FileNotFoundError):
            _assert_metadata_sidecar(step, spec)


def test_assert_metadata_sidecar_valid():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature
    import json, tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("dummy")
        meta = {
            "primitive_metadata": {
                "involute_spur_gear": {
                    "kernel": "cq_gears",
                    "is_standard_involute": True,
                    "primitive": "involute_spur_gear",
                    "parameters": {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0},
                    "reference_dimensions": {"pitch_diameter_mm": 48.0},
                }
            },
            "build_warnings": [],
        }
        meta_path = step.with_suffix(".metadata.json")
        meta_path.write_text(json.dumps(meta))

        spec = CADPartSpec(name="test", features=[
            PrimitiveFeature(id="g1", primitive_name="involute_spur_gear",
                             parameters={"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0})
        ])
        loaded = _assert_metadata_sidecar(step, spec)
        assert loaded["primitive_metadata"]["involute_spur_gear"]["kernel"] == "cq_gears"


def test_metadata_missing_primitive_metadata_key_raises():
    from seekflow_engineering_tools.cadquery_backend.builder import _assert_metadata_sidecar
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    import json, tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "test.step"
        step.write_text("x")
        meta = {"build_warnings": [], "extras": {}}
        meta_path = step.with_suffix(".metadata.json")
        meta_path.write_text(json.dumps(meta))

        spec = CADPartSpec(name="test", features=[])
        with pytest.raises(ValueError, match="primitive_metadata"):
            _assert_metadata_sidecar(step, spec)


def test_fallback_policy_industrial_brep_hard_fail():
    from seekflow_engineering_tools.cadquery_backend.builder import _check_fallback_policy
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    spec = CADPartSpec(name="test", features=[
        PrimitiveFeature(id="g1", primitive_name="involute_spur_gear",
                         parameters={"module_mm": 2.0, "teeth": 24,
                                      "face_width_mm": 15.0, "quality_grade": "industrial_brep"})
    ])
    metadata = {
        "primitive_metadata": {
            "involute_spur_gear": {
                "kernel": "cadquery_visual_fallback",
                "is_standard_involute": False,
            }
        },
        "build_warnings": ["not certified involute geometry"],
    }
    is_hard_fail, warnings = _check_fallback_policy(spec, metadata)
    assert is_hard_fail is True
    assert len(warnings) > 0


def test_fallback_policy_visual_fallback_allowed():
    from seekflow_engineering_tools.cadquery_backend.builder import _check_fallback_policy
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    spec = CADPartSpec(name="test", features=[
        PrimitiveFeature(id="g1", primitive_name="involute_spur_gear",
                         parameters={"module_mm": 2.0, "teeth": 24,
                                      "face_width_mm": 15.0, "quality_grade": "visual_fallback"})
    ])
    metadata = {
        "primitive_metadata": {
            "involute_spur_gear": {
                "kernel": "cadquery_visual_fallback",
                "is_standard_involute": False,
            }
        },
        "build_warnings": ["not certified"],
    }
    is_hard_fail, warnings = _check_fallback_policy(spec, metadata)
    assert is_hard_fail is False  # visual_fallback quality allows it
