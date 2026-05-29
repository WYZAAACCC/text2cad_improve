"""Test sketch_extrude base definition and operation models."""

import pytest

from seekflow_engineering_tools.generative_cad.bases.sketch_extrude.models import (
    AddRectangularBossParams,
    AddRibParams,
    ApplySafeChamferParams,
    ApplySafeFilletParams,
    CutHoleParams,
    CutHolePatternLinearParams,
    CutRectangularPocketParams,
    ExtrudeRectangleParams,
)


class TestExtrudeRectangleParams:
    def test_valid(self):
        p = ExtrudeRectangleParams(width_mm=100, height_mm=50, depth_mm=10)
        assert p.width_mm == 100
        assert p.height_mm == 50

    def test_negative_width_fails(self):
        with pytest.raises(ValueError):
            ExtrudeRectangleParams(width_mm=-1, height_mm=50, depth_mm=10)

    def test_zero_depth_fails(self):
        with pytest.raises(ValueError):
            ExtrudeRectangleParams(width_mm=100, height_mm=50, depth_mm=0)


class TestCutRectangularPocketParams:
    def test_valid(self):
        p = CutRectangularPocketParams(width_mm=50, height_mm=30, depth_mm=5)
        assert p.depth_mm == 5


class TestCutHoleParams:
    def test_valid(self):
        p = CutHoleParams(diameter_mm=10, position_mm=[25, 0, 0])
        assert p.diameter_mm == 10

    def test_position_bad_length_fails(self):
        with pytest.raises(ValueError, match="position_mm"):
            CutHoleParams(diameter_mm=10, position_mm=[25])

    def test_zero_diameter_fails(self):
        with pytest.raises(ValueError):
            CutHoleParams(diameter_mm=0, position_mm=[25, 0])


class TestCutHolePatternLinearParams:
    def test_valid(self):
        p = CutHolePatternLinearParams(
            hole_dia_mm=5, count_x=2, count_y=3,
            spacing_x_mm=20, spacing_y_mm=15,
        )
        assert p.count_x == 2
        assert p.count_y == 3

    def test_count_x_zero_fails(self):
        with pytest.raises(ValueError):
            CutHolePatternLinearParams(
                hole_dia_mm=5, count_x=0, count_y=1,
                spacing_x_mm=20, spacing_y_mm=15,
            )


class TestAddRectangularBossParams:
    def test_valid(self):
        p = AddRectangularBossParams(
            width_mm=30, height_mm=20, depth_mm=5, position_mm=[10, 10],
        )
        assert p.width_mm == 30

    def test_invalid_position_fails(self):
        with pytest.raises(ValueError, match="position_mm"):
            AddRectangularBossParams(
                width_mm=30, height_mm=20, depth_mm=5, position_mm=[10],
            )


class TestAddRibParams:
    def test_valid(self):
        p = AddRibParams(
            thickness_mm=3, height_mm=15, length_mm=50, direction="X",
        )
        assert p.thickness_mm == 3


class TestApplySafeFilletParams:
    def test_valid(self):
        p = ApplySafeFilletParams(radius_mm=2.0)
        assert p.radius_mm == 2.0


class TestApplySafeChamferParams:
    def test_valid(self):
        p = ApplySafeChamferParams(distance_mm=1.0)
        assert p.distance_mm == 1.0
