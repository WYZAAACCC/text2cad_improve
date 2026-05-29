"""Test axisymmetric base definition and operation models."""

import pytest

from seekflow_engineering_tools.generative_cad.bases.axisymmetric.models import (
    ApplySafeChamferParams,
    CutAnnularGrooveParams,
    CutCenterBoreParams,
    CutCircularHolePatternParams,
    CutRimSlotPatternParams,
    ProfileStation,
    RevolveProfileParams,
    RimSlotProfile,
    SlotProfileStation,
)


class TestProfileStation:
    def test_valid_station(self):
        s = ProfileStation(r_mm=50, z_front_mm=0, z_rear_mm=10)
        assert s.r_mm == 50

    def test_z_inverted_fails(self):
        with pytest.raises(ValueError, match="z_front_mm"):
            ProfileStation(r_mm=50, z_front_mm=20, z_rear_mm=10)

    def test_negative_radius_fails(self):
        with pytest.raises(ValueError):
            ProfileStation(r_mm=-1, z_front_mm=0, z_rear_mm=10)


class TestRevolveProfileParams:
    def test_min_length_2(self):
        with pytest.raises(ValueError, match="profile_stations"):
            RevolveProfileParams(
                axis="Z",
                profile_stations=[
                    ProfileStation(r_mm=50, z_front_mm=0, z_rear_mm=10),
                ],
            )

    def test_valid_params(self):
        p = RevolveProfileParams(
            axis="Z",
            profile_stations=[
                ProfileStation(r_mm=50, z_front_mm=0, z_rear_mm=10),
                ProfileStation(r_mm=30, z_front_mm=10, z_rear_mm=20),
            ],
        )
        assert len(p.profile_stations) == 2


class TestCutCenterBoreParams:
    def test_valid(self):
        p = CutCenterBoreParams(diameter_mm=20, axis="Z")
        assert p.diameter_mm == 20


class TestCutAnnularGrooveParams:
    def test_valid(self):
        p = CutAnnularGrooveParams(
            side="front", inner_dia_mm=40, outer_dia_mm=60, depth_mm=5,
        )
        assert p.side == "front"

    def test_inner_gte_outer_fails(self):
        with pytest.raises(ValueError, match="inner_dia_mm"):
            CutAnnularGrooveParams(
                side="front", inner_dia_mm=60, outer_dia_mm=40, depth_mm=5,
            )


class TestCutCircularHolePatternParams:
    def test_valid(self):
        p = CutCircularHolePatternParams(
            count=6, pcd_mm=80, hole_dia_mm=10, axis="Z",
        )
        assert p.count == 6

    def test_count_less_than_2_fails(self):
        with pytest.raises(ValueError):
            CutCircularHolePatternParams(
                count=1, pcd_mm=80, hole_dia_mm=10, axis="Z",
            )


class TestRimSlotProfile:
    def test_valid(self):
        p = RimSlotProfile(
            stations=[
                SlotProfileStation(depth_mm=0, half_width_mm=5),
                SlotProfileStation(depth_mm=10, half_width_mm=8),
            ],
        )
        assert len(p.stations) == 2

    def test_depths_non_monotonic_fails(self):
        with pytest.raises(ValueError, match="nondecreasing"):
            RimSlotProfile(
                stations=[
                    SlotProfileStation(depth_mm=10, half_width_mm=5),
                    SlotProfileStation(depth_mm=5, half_width_mm=8),
                ],
            )

    def test_min_length_2(self):
        with pytest.raises(ValueError):
            RimSlotProfile(
                stations=[SlotProfileStation(depth_mm=0, half_width_mm=5)],
            )


class TestCutRimSlotPatternParams:
    def test_valid(self):
        p = CutRimSlotPatternParams(
            count=12,
            slot_depth_mm=20,
            slot_profile=RimSlotProfile(
                stations=[
                    SlotProfileStation(depth_mm=0, half_width_mm=5),
                    SlotProfileStation(depth_mm=10, half_width_mm=8),
                ],
            ),
        )
        assert p.count == 12


class TestApplySafeChamferParams:
    def test_valid(self):
        p = ApplySafeChamferParams(distance_mm=1.0)
        assert p.distance_mm == 1.0
