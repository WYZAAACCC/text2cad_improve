"""The clauses a criterion can carry, and whether they do anything.

Every clause below was, until now, inert in a different way. `planar_tol_mm`
was declared and never read. `normal_sign` and `area_rel_tol` were declared and
never read, so a symmetry clause tested neither the orientation nor the size of
the pairs it claimed to check. `kind` was echoed back in the result but never
consulted, so a mirror was silently evaluated as a rotation. And the azimuth
the whole check is built on was computed from the face's own radial direction,
which makes it zero for every face - so no pair ever matched and every declared
clause reported `unmatched_fraction: 1.0`.

That last one is the worst of them, because the residual is read as evidence:
an agent that declared a symmetry it had genuinely satisfied would be told it
had not, and would go looking for a fault in its own selection.
"""
from __future__ import annotations

import math

import pytest

from seekflow_structural.case.model import (
    Criterion,
    SymmetryClause,
    Vec3,
)
from seekflow_structural.tools import criteria

ORIGIN = Vec3(x=0.0, y=0.0, z=0.0)
AXIS = Vec3(x=0.0, y=0.0, z=1.0)


def face_at(index, *, radius=200.0, theta_deg=0.0, area=50.0,
            normal=(0.5, 0.5, math.sqrt(0.5))):
    """A face whose centroid really is at (radius, theta_deg).

    The existing helper places every centroid on the +X axis, which is fine
    for clause tests on a single face and useless for a symmetry test - the
    whole question is where the faces are relative to each other.
    """
    t = math.radians(theta_deg)
    return {
        "face_index": index,
        "surface_type": "plane",
        "area_mm2": area,
        "centroid_mm": [radius * math.cos(t), radius * math.sin(t), 0.0],
        "centroid_cyl_mm_deg": [radius, theta_deg, 0.0],
        "normal_xyz": list(normal),
        "normal_cylindrical": {
            "radial": normal[0], "tangential": normal[1], "axial": normal[2]
        },
        "edge_count": 4,
    }


def check(criterion, rows, azimuth=None):
    return criteria.check_selection(criterion, rows, ORIGIN, AXIS, azimuth)


# --------------------------------------------------------------------------
# The azimuth itself
# --------------------------------------------------------------------------

def test_azimuth_is_measured_from_a_direction_fixed_in_the_model():
    """The regression. It used to be zero for every point.

    `atan2(dot(radial_vec, tangential_dir), radius)` is identically zero
    because `tangential_dir` is the cross product of the axis with the unit
    vector along `radial_vec` - the two are perpendicular by construction, and
    the frame rotated with the face.
    """
    for theta in (0.0, 10.0, 45.0, 200.0, 359.0):
        t = math.radians(theta)
        point = Vec3(
            x=200.0 * math.cos(t), y=200.0 * math.sin(t), z=0.0
        )
        measured = criteria.cylindrical(
            point, Vec3(x=0.0, y=0.0, z=1.0), ORIGIN, AXIS
        )
        assert measured["theta_deg"] == pytest.approx(theta, abs=1e-6)


def test_azimuth_is_usable_about_an_axis_that_is_not_z():
    for theta in (0.0, 90.0, 180.0, 270.0):
        t = math.radians(theta)
        point = Vec3(
            x=0.0, y=200.0 * math.cos(t), z=200.0 * math.sin(t)
        )
        measured = criteria.cylindrical(
            point, Vec3(x=1.0, y=0.0, z=0.0), ORIGIN,
            Vec3(x=1.0, y=0.0, z=0.0),
        )
        assert measured["theta_deg"] == pytest.approx(theta, abs=1e-6)


# --------------------------------------------------------------------------
# kind: a rotation and a mirror are not the same claim
# --------------------------------------------------------------------------

def test_rotational_order_matches_a_partner_at_the_step():
    """A half turn: each face's target is the other, so the set maps to itself.

    The check is not mutual by construction - it asks whether each face has a
    partner at the rotated position - so a two-face fixture has to be the
    whole orbit. Two faces 18 degrees apart under an order-20 rotation is a
    set that genuinely is not closed, and reporting one face unmatched is the
    right answer rather than a limitation.
    """
    criterion = Criterion(
        intent="half turn",
        symmetry=SymmetryClause(kind="rotational_order", ref="2"),
    )
    result = check(criterion, [face_at(0, theta_deg=0.0),
                               face_at(1, theta_deg=180.0)])
    symmetry = result["symmetry"]
    assert symmetry["unmatched_indices"] == []
    assert symmetry["paired_count"] == 2
    assert result["satisfied"] is True


def test_rotational_order_reports_a_face_with_no_partner():
    criterion = Criterion(
        intent="half turn",
        symmetry=SymmetryClause(kind="rotational_order", ref="2"),
    )
    result = check(criterion, [face_at(0, theta_deg=0.0),
                               face_at(1, theta_deg=7.0)])
    assert result["symmetry"]["unmatched_indices"] == [0, 1]
    assert result["symmetry"]["unmatched_fraction"] == 1.0
    assert result["satisfied"] is False


def test_mirror_plane_reflects_rather_than_rotates():
    """A mirror about the plane at 9 degrees sends 0 to 18, not to 18 by step.

    With `kind` ignored the two were indistinguishable at this angle, so the
    test uses a plane whose reflection is not a multiple of any step the same
    clause could have named as a rotation.
    """
    rows = [face_at(0, theta_deg=4.0), face_at(1, theta_deg=26.0)]
    mirrored = check(
        Criterion(intent="mirrored about 15",
                  symmetry=SymmetryClause(kind="mirror_plane", ref="p15")),
        rows, azimuth=15.0,
    )
    assert mirrored["symmetry"]["unmatched_indices"] == []
    assert mirrored["symmetry"]["kind"] == "mirror_plane"

    # 4 -> 26 is also a 22 degree rotation, but 26 -> 48 is not in the set, so
    # read as a rotation the same pair does not close.
    rotated = check(
        Criterion(intent="every 22",
                  symmetry=SymmetryClause(kind="rotational_order", ref="16.36")),
        rows,
    )
    assert rotated["symmetry"]["unmatched_indices"] == [1]


def test_a_mirror_without_its_azimuth_is_unmeasurable_not_assumed():
    """Silently treating it as a rotation is what this replaces."""
    result = check(
        Criterion(intent="mirrored",
                  symmetry=SymmetryClause(kind="mirror_plane", ref="p")),
        [face_at(0, theta_deg=4.0), face_at(1, theta_deg=26.0)],
    )
    symmetry = result["symmetry"]
    assert symmetry["status"] == "unmeasurable"
    assert "azimuth" in symmetry["note"]
    assert "unmatched_indices" not in symmetry


# --------------------------------------------------------------------------
# area_rel_tol and normal_sign
# --------------------------------------------------------------------------

def test_area_rel_tol_rejects_a_partner_of_the_wrong_size():
    criterion = Criterion(
        intent="equal flanks",
        symmetry=SymmetryClause(
            kind="rotational_order", ref="2", area_rel_tol=0.05
        ),
    )
    # Half the larger area, well outside the 5% asked for. The difference is
    # normalised by the larger of the two, so it is bounded by 1 rather than
    # growing without limit as one of the pair shrinks.
    result = check(criterion, [face_at(0, area=50.0),
                               face_at(1, theta_deg=180.0, area=100.0)])
    symmetry = result["symmetry"]
    assert symmetry["unmatched_indices"] == [0, 1]
    detail = symmetry["unmatched_detail"][0]["rejected"][0]
    assert detail["clause"] == "area_rel_tol"
    assert detail["relative_difference"] == pytest.approx(0.5, abs=1e-6)


def test_area_rel_tol_accepts_a_partner_within_it():
    criterion = Criterion(
        intent="equal flanks",
        symmetry=SymmetryClause(
            kind="rotational_order", ref="2", area_rel_tol=0.05
        ),
    )
    result = check(criterion, [face_at(0, area=50.0),
                               face_at(1, theta_deg=180.0, area=52.0)])
    assert result["symmetry"]["unmatched_indices"] == []


def test_normal_sign_same_rejects_a_partner_facing_the_other_way():
    criterion = Criterion(
        intent="both facing out",
        symmetry=SymmetryClause(
            kind="rotational_order", ref="2", normal_sign="same"
        ),
    )
    # Opposite normals: the dot product is -1, so they do not face the same way.
    result = check(criterion, [
        face_at(0, normal=(0.5, 0.5, math.sqrt(0.5))),
        face_at(1, theta_deg=180.0,
                normal=(-0.5, -0.5, -math.sqrt(0.5))),
    ])
    detail = result["symmetry"]["unmatched_detail"][0]["rejected"][0]
    assert detail["clause"] == "normal_sign"
    assert detail["normal_dot"] == pytest.approx(-1.0, abs=1e-6)


def test_normal_sign_opposite_rejects_a_partner_facing_the_same_way():
    criterion = Criterion(
        intent="mirrored flanks",
        symmetry=SymmetryClause(
            kind="rotational_order", ref="2", normal_sign="opposite"
        ),
    )
    result = check(criterion, [
        face_at(0, normal=(0.5, 0.5, math.sqrt(0.5))),
        face_at(1, theta_deg=180.0,
                normal=(0.5, 0.5, math.sqrt(0.5))),
    ])
    assert result["symmetry"]["unmatched_indices"] == [0, 1]


def test_normal_sign_unconstrained_accepts_either():
    criterion = Criterion(
        intent="either way",
        symmetry=SymmetryClause(
            kind="rotational_order", ref="2", normal_sign="unconstrained"
        ),
    )
    result = check(criterion, [
        face_at(0, normal=(0.5, 0.5, math.sqrt(0.5))),
        face_at(1, theta_deg=180.0,
                normal=(-0.5, -0.5, -math.sqrt(0.5))),
    ])
    assert result["symmetry"]["unmatched_indices"] == []


# --------------------------------------------------------------------------
# A clause that cannot be evaluated must not look like one that passed
# --------------------------------------------------------------------------

def test_symmetry_is_still_reported_and_never_refuses():
    """A set that is not closed may be exactly what the agent meant."""
    result = check(
        Criterion(intent="one flank",
                  symmetry=SymmetryClause(kind="rotational_order", ref="2")),
        [face_at(0, theta_deg=10.0)],
    )
    assert result["symmetry"]["declared"] is True
    assert result["symmetry"]["unmatched_fraction"] == 1.0


def test_a_criterion_does_not_offer_a_control_it_cannot_evaluate():
    """`planar_tol_mm` promised a flatness check no measurement supports.

    Surface type is exact in a B-rep, so the tolerance could only ever have
    been ignored - and an ignored field reads as a satisfied one.
    """
    schema = Criterion.model_json_schema()
    assert "planar_tol_mm" not in schema["properties"]
    for field in ("normal_sign", "area_rel_tol"):
        assert field in SymmetryClause.model_json_schema()["properties"]
