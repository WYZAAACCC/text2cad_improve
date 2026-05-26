"""Test that inspection and validation are wired into the build pipeline."""

from __future__ import annotations

from pathlib import Path

from seekflow_engineering_tools.cadquery_backend.builder import (
    _run_inspection,
    assert_file_created,
)
from seekflow_engineering_tools.ir.cad import CADPartSpec, RecipeFeature, ValidationSpec


class TestAssertFileCreated:
    def test_raises_when_file_missing(self, tmp_path: Path):
        p = tmp_path / "nonexistent.step"
        try:
            assert_file_created(p, "STEP")
            assert False, "Should have raised"
        except FileNotFoundError:
            pass

    def test_raises_when_file_empty(self, tmp_path: Path):
        p = tmp_path / "empty.step"
        p.write_text("")
        try:
            assert_file_created(p, "STEP", min_size=1)
            assert False, "Should have raised"
        except ValueError:
            pass

    def test_passes_when_file_nonempty(self, tmp_path: Path):
        p = tmp_path / "good.step"
        p.write_text("ISO-10303-21;")
        assert_file_created(p, "STEP", min_size=1)


class TestInspectionValidation:
    def test_bbox_mismatch_detected(self):
        spec = CADPartSpec(
            name="test",
            features=[
                RecipeFeature(
                    id="f1",
                    type="recipe",
                    recipe_name="box",
                    parameters={
                        "length_mm": 100,
                        "width_mm": 50,
                        "height_mm": 25,
                    },
                )
            ],
            validation=ValidationSpec(
                expected_bbox_mm=[100, 50, 25],
                tolerance_mm=0.1,
            ),
        )
        # Simulate inspection with wrong bbox
        result = _run_inspection_with_mock(
            spec,
            mock_info={
                "bbox_mm": [100, 50, 20],  # wrong z
                "solid_count": 1,
            },
        )
        assert result["validation"]["ok"] is False
        assert any("bbox" in e.lower() for e in result["validation"]["errors"])

    def test_bbox_match_passes(self):
        spec = CADPartSpec(
            name="test",
            features=[
                RecipeFeature(
                    id="f1",
                    type="recipe",
                    recipe_name="box",
                    parameters={
                        "length_mm": 100,
                        "width_mm": 50,
                        "height_mm": 25,
                    },
                )
            ],
            validation=ValidationSpec(
                expected_bbox_mm=[100, 50, 25],
                tolerance_mm=0.2,
            ),
        )
        result = _run_inspection_with_mock(
            spec,
            mock_info={
                "bbox_mm": [100.05, 50.0, 25.0],
                "solid_count": 1,
            },
        )
        assert result["validation"]["ok"] is True

    def test_body_count_mismatch_detected(self):
        spec = CADPartSpec(
            name="test",
            features=[
                RecipeFeature(
                    id="f1",
                    type="recipe",
                    recipe_name="box",
                    parameters={
                        "length_mm": 100,
                        "width_mm": 50,
                        "height_mm": 25,
                    },
                )
            ],
            validation=ValidationSpec(expected_body_count=1),
        )
        result = _run_inspection_with_mock(
            spec,
            mock_info={
                "bbox_mm": [100, 50, 25],
                "solid_count": 3,  # wrong
            },
        )
        assert result["validation"]["ok"] is False
        assert any("body_count" in e for e in result["validation"]["errors"])

    def test_validation_with_no_expectations_passes(self):
        spec = CADPartSpec(
            name="test",
            features=[
                RecipeFeature(
                    id="f1",
                    type="recipe",
                    recipe_name="box",
                    parameters={
                        "length_mm": 100,
                        "width_mm": 50,
                        "height_mm": 25,
                    },
                )
            ],
            validation=ValidationSpec(),
        )
        result = _run_inspection_with_mock(
            spec,
            mock_info={
                "bbox_mm": [99, 51, 24],
                "solid_count": 1,
            },
        )
        assert result["validation"]["ok"] is True


def _run_inspection_with_mock(spec, mock_info):
    """Helper to test _run_inspection with a mock inspection result."""
    from unittest.mock import patch

    with patch(
        "seekflow_engineering_tools.cadquery_backend.builder.inspect_step_with_cadquery",
        return_value=mock_info,
    ):
        from seekflow_engineering_tools.cadquery_backend.builder import _run_inspection
        return _run_inspection(Path("/fake/test.step"), spec)
