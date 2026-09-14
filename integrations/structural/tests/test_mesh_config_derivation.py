"""The mesh config is derived from the case, and says what it means.

Two things this pins. The geometry block is written from `case.model` and
`case.domain` rather than read back from a file, which is the fix for the seam
where a config still carried a sector angle the domain agent had already
changed. And `z_symmetry` means the mid-plane specifically: a plane containing
the axis bounds the azimuth, and reading it as the mid-plane tells the mesher
to halve a thickness that was never halved.
"""
from __future__ import annotations

import pytest

from seekflow_structural.case.model import (
    Case,
    DomainDecision,
    Frame,
    ModelFacts,
    Plane,
    Vec3,
    Written,
)
from seekflow_structural.pipeline.materialize import mesh_config_from_case

MEASURED = Written(by_stage="frame", kind="measured", source="test")
DECIDED = Written(by_stage="domain", kind="agent_decision", source="test")


def _plane(identifier: str, normal) -> Plane:
    return Plane(
        id=identifier, origin_mm=Vec3(x=0.0, y=0.0, z=0.0),
        normal=Vec3(x=float(normal[0]), y=float(normal[1]),
                    z=float(normal[2])),
        matched_area_fraction=1.0,
    )


def a_case(*, planes, used, sector_deg: float | None = 18.0,
           theta_low_deg=9.0) -> Case:
    model = ModelFacts(
        bounds_min_mm=Vec3(x=-300.0, y=-300.0, z=-42.2),
        bounds_max_mm=Vec3(x=300.0, y=300.0, z=38.0),
        r_max_mm=300.0,
        has_rotation_axis=True,
        frame=Frame(
            axis_origin_mm=Vec3(x=0.0, y=0.0, z=0.0),
            axis_direction=Vec3(x=0.0, y=0.0, z=1.0),
        ),
        symmetry_planes=planes,
        bore_radius_mm=60.0,
        written=MEASURED,
    )
    domain = DomainDecision(
        sector_deg=sector_deg, theta_low_deg=theta_low_deg,
        symmetry_planes_used=used, written=DECIDED,
    )
    return Case(
        case_id="c", bundle=_bundle(), model=model, domain=domain,
    )


def _bundle():
    from seekflow_structural.case.model import BundleRef

    return BundleRef(path="E:/bundle", lineage_id="D", revision_id="rev-1")


MID_PLANE = _plane("z0", (0.0, 0.0, 1.0))
SIDE_PLANE = _plane("x0", (1.0, 0.0, 0.0))


def geometry_of(case) -> dict:
    return mesh_config_from_case(case, None)["geometry"]


def test_the_mid_plane_is_reported_as_z_symmetry():
    case = a_case(planes=[MID_PLANE, SIDE_PLANE], used=["z0"])
    assert geometry_of(case)["z_symmetry"] is True


def test_a_plane_containing_the_axis_is_not_z_symmetry():
    """The bug this replaces: any plane at all was reported as the mid-plane,
    so a part cut into a wedge was also told to mesh half its thickness."""
    case = a_case(planes=[MID_PLANE, SIDE_PLANE], used=["x0"])
    assert geometry_of(case)["z_symmetry"] is False


def test_no_symmetry_plane_at_all_is_not_z_symmetry():
    case = a_case(planes=[MID_PLANE], used=[])
    assert geometry_of(case)["z_symmetry"] is False


def test_the_sector_angles_are_written_from_the_case():
    case = a_case(
        planes=[MID_PLANE], used=["z0"], sector_deg=18.0, theta_low_deg=9.0
    )
    geometry = geometry_of(case)
    assert geometry["sector_deg"] == 18.0
    assert geometry["theta_low_deg"] == 9.0
    assert geometry["r_outer_mm"] == 300.0
    assert geometry["r_bore_mm"] == 60.0
    assert geometry["z_half_mm"] == pytest.approx(42.2, abs=0.01)


def test_a_whole_revolution_is_reported_as_360_not_as_no_sector():
    case = a_case(planes=[], used=[], sector_deg=None)
    assert geometry_of(case)["sector_deg"] == 360.0
