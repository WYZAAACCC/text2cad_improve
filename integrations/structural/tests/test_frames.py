"""Moving the model onto the deck's axis, and the promises that has to keep.

Three properties matter, and each is a way the change could go quietly wrong.

Algebraic equivalence: the transform is rigid, so a solve through it returns
the same physics. What is checked here is the invariant that makes the rest of
the package valid afterwards - distance from the axis is preserved, so every
radius (bore, band edges, load radius) still means what it meant.

The no-op: when the axis is already +Z, nothing may move. That is what lets
the change be added to a chain that already runs, and the regression test
compares an emitted deck byte for byte.

The general case: an axis that is tilted, or displaced off the origin, has to
land on +Z with its radius intact - which is the case no existing part
exercises.
"""
from __future__ import annotations

import pytest

from seekflow_structural.tools.frames import (
    IDENTITY,
    Normalisation,
    distance_from_axis,
    normalise_mesh,
)


def test_an_axis_already_on_z_is_left_exactly_alone():
    """Exact, not approximate: the no-op regression compares decks bytewise."""
    n = Normalisation((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert n.rotation == IDENTITY
    assert n.translation == [0.0, 0.0, 0.0]
    assert n.is_identity is True
    assert n.point(12.5, -3.25, 7.125) == (12.5, -3.25, 7.125)


def test_an_axis_pointing_down_z_is_turned_back():
    n = Normalisation((0.0, 0.0, 0.0), (0.0, 0.0, -1.0))
    assert n.is_identity is False
    # a point on the axis stays on it, with its axial position negated
    x, y, z = n.point(0.0, 0.0, 5.0)
    assert (x, y) == pytest.approx((0.0, 0.0), abs=1e-12)
    assert z == pytest.approx(-5.0)


def test_inverse_point_returns_to_the_source_frame():
    n = Normalisation((10.0, -4.0, 2.5), (0.2, 0.3, 0.93))
    point = (17.0, 3.0, -5.0)
    case_point = n.point(*point)
    assert n.inverse_point(*case_point) == pytest.approx(point, abs=1e-12)


def test_distance_from_the_axis_survives_the_transform():
    """Every radius in the package depends on this."""
    axis = ((3.0, -2.0, 1.5), (0.3, 0.5, 0.81))
    n = Normalisation(*axis)
    for point in ((10.0, 4.0, 6.0), (-7.0, 12.0, -3.0), (0.0, 0.0, 0.0),
                  (100.0, -50.0, 20.0)):
        before = distance_from_axis(point, axis[0], axis[1])
        after = distance_from_axis(n.point(*point), (0.0, 0.0, 0.0),
                                   (0.0, 0.0, 1.0))
        assert after == pytest.approx(before, rel=1e-9)


def test_the_axis_lands_on_the_z_axis():
    axis = ((25.0, -40.0, 7.0), (0.2, 0.3, 0.93))
    n = Normalisation(*axis)
    for along in (-50.0, 0.0, 33.0):
        point = [axis[0][i] + along * axis[1][i] for i in range(3)]
        x, y, z = n.point(*point)
        assert x == pytest.approx(0.0, abs=1e-9)
        assert y == pytest.approx(0.0, abs=1e-9)


def test_the_rotation_is_orthonormal():
    """A rotation that is not orthonormal is not rigid, and quietly changes
    lengths."""
    n = Normalisation((1.0, 2.0, 3.0), (0.4, -0.6, 0.69))
    m = n.as_matrix()
    for i in range(3):
        for j in range(3):
            dot = sum(m[k][i] * m[k][j] for k in range(3))
            assert dot == pytest.approx(1.0 if i == j else 0.0, abs=1e-12)


def test_vectors_rotate_and_do_not_translate():
    """The distinction matters the moment a reflection is added, so the two
    are separate operations even though a pure rotation makes them equal."""
    n = Normalisation((10.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert n.is_identity is False, "the origin moves, so this is not a no-op"
    moved_point = n.point(13.0, 0.0, 0.0)
    moved_vector = n.direction(1.0, 0.0, 0.0)
    assert moved_point == pytest.approx((3.0, 0.0, 0.0))
    assert moved_vector == pytest.approx((1.0, 0.0, 0.0))


def test_a_mesh_is_rewritten_without_touching_its_elements(tmp_path):
    mesh = tmp_path / "mesh.inp"
    mesh.write_text(
        "/NOPR\n"
        "N,1,10.0,0.0,0.0\n"
        "N,2,0.0,10.0,0.0\n"
        "TYPE,1\nMAT,1\n"
        "EN,1,1,2,3,4,5,6,7,8\n"
        "EMORE,9,10\n"
        "/GOPR\n",
        encoding="ascii",
    )
    out = tmp_path / "moved.inp"
    n = Normalisation((10.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    moved = normalise_mesh(mesh, out, n)

    assert moved == 2
    text = out.read_text(encoding="ascii")
    # node 1 sat at the axis origin, so it moves onto the Z axis
    assert "N,1,0,0,0" in text
    assert "N,2,-10,10,0" in text
    # connectivity is untouched
    assert "EN,1,1,2,3,4,5,6,7,8" in text
    assert "EMORE,9,10" in text
    assert "/GOPR" in text


def test_moving_a_mesh_through_the_identity_changes_nothing_but_rounding(
    tmp_path,
):
    """The same node values come back, so an existing run's mesh still does."""
    mesh = tmp_path / "mesh.inp"
    mesh.write_text(
        "/NOPR\nN,1,59.91777,3.14016,38.00000\n/GOPR\n", encoding="ascii"
    )
    out = tmp_path / "same.inp"
    normalise_mesh(mesh, out, Normalisation((0, 0, 0), (0, 0, 1)))
    assert "N,1,59.91777,3.14016,38" in out.read_text(encoding="ascii")


def test_an_axis_through_the_origin_is_not_a_no_op_for_a_displaced_part():
    """A part modelled away from the origin still needs moving onto the axis,
    even when its own axis is parallel to +Z - which is the case the three
    refusals used to reject."""
    n = Normalisation((100.0, 50.0, 0.0), (0.0, 0.0, 1.0))
    assert n.is_identity is False
    x, y, _ = n.point(100.0, 50.0, 12.0)
    assert (x, y) == pytest.approx((0.0, 0.0), abs=1e-12)
    # and the radius is unchanged elsewhere
    assert distance_from_axis(
        n.point(160.0, 50.0, 0.0), (0, 0, 0), (0, 0, 1)
    ) == pytest.approx(60.0)

def test_a_non_global_axis_is_converted_to_the_deck_axis_contract():
    from seekflow_structural.case.model import (
        BundleRef,
        Case,
        Frame,
        ModelFacts,
        Vec3,
        Written,
    )
    from seekflow_structural.pipeline.materialize import deck_axis_for

    frame = Frame(
        axis_origin_mm=Vec3(x=10.0, y=-5.0, z=2.0),
        axis_direction=Vec3(x=0.2, y=0.3, z=0.93),
    )
    case = Case(
        case_id="tilted",
        bundle=BundleRef(path="."),
        model=ModelFacts(
            bounds_min_mm=Vec3(x=-1.0, y=-1.0, z=-1.0),
            bounds_max_mm=Vec3(x=1.0, y=1.0, z=1.0),
            r_max_mm=1.0,
            frame=frame,
            written=Written(by_stage="frame", kind="measured"),
        ),
    )
    assert deck_axis_for(case) == (0.0, 0.0, 1.0)


def test_an_identity_frame_needs_no_deck_axis_override():
    from seekflow_structural.case.model import (
        BundleRef,
        Case,
        Frame,
        ModelFacts,
        Vec3,
        Written,
    )
    from seekflow_structural.pipeline.materialize import deck_axis_for

    case = Case(
        case_id="z",
        bundle=BundleRef(path="."),
        model=ModelFacts(
            bounds_min_mm=Vec3(x=-1.0, y=-1.0, z=-1.0),
            bounds_max_mm=Vec3(x=1.0, y=1.0, z=1.0),
            r_max_mm=1.0,
            frame=Frame(
                axis_origin_mm=Vec3(x=0.0, y=0.0, z=0.0),
                axis_direction=Vec3(x=0.0, y=0.0, z=1.0),
            ),
            written=Written(by_stage="frame", kind="measured"),
        ),
    )
    assert deck_axis_for(case) is None

def test_the_gmsh_and_structural_frame_transforms_agree():
    """One frame contract, two runtimes: drift here changes every radius."""
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    path = repo / "app" / "text-to-cad" / "server" / "fea3d" / "mesh_sector.py"
    spec = importlib.util.spec_from_file_location("mesh_sector_frame_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    for origin, direction in (
        ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        ((100.0, 50.0, 7.0), (0.0, 0.0, 1.0)),
        ((10.0, -5.0, 2.0), (0.2, 0.3, 0.93)),
        ((0.0, 0.0, 0.0), (0.0, 0.0, -1.0)),
    ):
        expected = Normalisation(origin, direction)
        actual = module.case_frame_transform(origin, direction)
        for row_actual, row_expected in zip(
            actual["rotation"], expected.rotation, strict=True
        ):
            assert row_actual == pytest.approx(row_expected, abs=1e-12)
        assert actual["translation"] == pytest.approx(
            expected.translation, abs=1e-12
        )



def test_frame_reads_a_declared_axis_before_setup_has_run():
    from seekflow_structural.case.model import Vec3
    from seekflow_structural.pipeline.frame import _declared_axis_from_params

    assert _declared_axis_from_params({
        "rotation": {
            "axis_origin_mm": [1, 2, 3],
            "axis_direction": [0.0, -0.5, 0.8660254037844387],
        }
    }) == (
        Vec3(x=1.0, y=2.0, z=3.0),
        Vec3(x=0.0, y=-0.5, z=0.8660254037844387),
    )
    assert _declared_axis_from_params({"rotation": {"rpm": 15000}}) is None
