"""The face filter, tested against rows rather than against a kernel.

The filter had no test at all, and it was wrong in a way that looked like a
fact about the part: the table said the "area" filter reads `area_mm2` while
the predicate looked up the key "area", which no face has. Every face failed
that filter on every query, so every search returned nothing. The agent saw
`matched: 0` eleven times, was told to widen its bounds, and spent its whole
budget widening bounds that were already correct.

These are the two things that were missing: an unfiltered query returns
everything, and each filter reads the fact it names.
"""
from __future__ import annotations

import pytest

from seekflow_structural.agents.facefind import _bounds, _filters
from seekflow_structural.tools import geometry

NO_BOUNDS = {name: None for name in geometry.CYLINDRICAL_FILTERS}


def _row(*, area, r, theta, z, kind="plane", normal=(0.0, 0.0, 1.0)):
    radial, tangential, axial = normal
    return {
        "surface_type": kind,
        "area_mm2": area,
        "centroid_cyl_mm_deg": [r, theta, z],
        "normal_cylindrical": {
            "radial": radial, "tangential": tangential, "axial": axial
        },
    }


@pytest.fixture
def rows():
    return [
        _row(area=100.0, r=60.0, theta=0.0, z=0.0, kind="plane",
             normal=(1.0, 0.0, 0.0)),
        _row(area=200.0, r=212.67, theta=9.0, z=5.0, kind="plane",
             normal=(0.6, 0.8, 0.0)),
        _row(area=300.0, r=212.67, theta=-9.0, z=-5.0, kind="cylinder",
             normal=(0.0, 0.0, 1.0)),
        _row(area=400.0, r=288.0, theta=45.0, z=20.0, kind="cone",
             normal=(-0.8, 0.0, 0.6)),
    ]


def test_no_filters_matches_every_face(rows):
    """The regression. An unset filter is not a filter.

    This is the one that failed on the real part: 4216 faces, a query with no
    bound set, and nothing matched.
    """
    assert geometry.query(rows, NO_BOUNDS) == [0, 1, 2, 3]


def test_empty_filter_dict_matches_every_face(rows):
    assert geometry.query(rows, {}) == [0, 1, 2, 3]


def test_surface_type_filter(rows):
    assert geometry.query(rows, NO_BOUNDS, surface_type="plane") == [0, 1]
    assert geometry.query(rows, NO_BOUNDS, surface_type="cone") == [3]


def test_area_filter_reads_area_mm2(rows):
    """`area` is the name of the filter; `area_mm2` is the fact it reads."""
    assert geometry.query(rows, {**NO_BOUNDS, "area": (150.0, 350.0)}) == [1, 2]


def test_radial_filter_reads_centroid_cyl(rows):
    """The measured load radius, which is the number the mesh refines on."""
    match = geometry.query(rows, {**NO_BOUNDS, "radial": (200.0, 220.0)})
    assert match == [1, 2]


def test_theta_and_z_filters(rows):
    assert geometry.query(rows, {**NO_BOUNDS, "theta": (0.0, 10.0)}) == [0, 1]
    assert geometry.query(rows, {**NO_BOUNDS, "z": (0.0, 10.0)}) == [0, 1]


def test_normal_components_read_normal_cylindrical(rows):
    assert geometry.query(
        rows, {**NO_BOUNDS, "normal_radial": (0.5, 1.0)}
    ) == [0, 1]
    assert geometry.query(
        rows, {**NO_BOUNDS, "normal_axial": (0.5, 1.0)}
    ) == [2, 3]
    assert geometry.query(
        rows, {**NO_BOUNDS, "normal_tangential": (0.5, 1.0)}
    ) == [1]


def test_filters_combine(rows):
    match = geometry.query(rows, {
        **NO_BOUNDS,
        "radial": (200.0, 220.0),
        "theta": (0.0, 10.0),
    })
    assert match == [1]


def test_an_unmeasured_fact_is_not_excluded_by_an_unset_filter():
    """A normal on the axis has no radial component, and that is not a miss.

    `face_facts` reports radial/tangential as None when a face's centroid sits
    on the axis. An agent that set no normal filter has not asked about the
    normal, so the face must still come back; an agent that did set one is
    asking a question this face cannot answer, and it is left out.
    """
    unmeasured = {
        "surface_type": "plane",
        "area_mm2": 10.0,
        "centroid_cyl_mm_deg": [0.0, 0.0, 3.0],
        "normal_cylindrical": {
            "radial": None, "tangential": None, "axial": 1.0
        },
    }
    assert geometry.query([unmeasured], NO_BOUNDS) == [0]
    assert geometry.query(
        [unmeasured], {**NO_BOUNDS, "normal_radial": (-1.0, 1.0)}
    ) == []


def test_describe_does_not_invent_a_normal_for_an_unmeasured_face():
    """`normal.get("radial", 0.0)` does not guard an explicit None.

    The key is present with the value None, so the default never applies and
    `float(None)` raises. Reading a page that happened to include one such
    face killed the whole query - which is how a part with a single on-axis
    face returned a TypeError instead of a page of faces.
    """
    unmeasured = {
        "surface_type": "plane",
        "area_mm2": 10.0,
        "centroid_cyl_mm_deg": [0.0, 0.0, 3.0],
        "normal_cylindrical": {
            "radial": None, "tangential": None, "axial": 1.0
        },
        "edge_count": 4,
    }
    described = geometry.describe([unmeasured], [0])[0]
    assert described["normal_radial"] is None
    assert described["normal_tangential"] is None
    assert described["normal_axial"] == 1.0
    assert described["radius_mm"] == 0.0


def test_summarise_reports_the_shape_of_the_matched_set(rows):
    """What the agent reads instead of paging through sixty at a time."""
    summary = geometry.summarise(rows, [0, 1, 2, 3])
    assert summary["count"] == 4
    assert summary["surface_types"] == {"plane": 2, "cylinder": 1, "cone": 1}
    assert summary["radius_mm"] == {"min": 60.0, "median": 212.67, "max": 288.0}
    assert geometry.summarise(rows, []) == {"empty": True}


def test_summarise_of_a_narrowed_set(rows):
    summary = geometry.summarise(rows, [1, 2])
    assert summary["count"] == 2
    assert summary["surface_types"] == {"plane": 1, "cylinder": 1}


def test_unset_bounds_become_none_not_a_wide_number():
    """The agent's action carries ±1e30 for a bound it did not set.

    Passed through as numbers those are still filters, and they exclude any
    face whose fact was never measured - so the schema's sentinel has to be
    translated back into "not asked".
    """
    from seekflow_structural.agents.facefind import Action

    action = Action(action="query_faces", feature="f")
    assert all(value is None for value in _filters(action).values())

    narrowed = Action(
        action="query_faces", feature="f",
        radial_min=200.0, radial_max=220.0,
    )
    filters = _filters(narrowed)
    assert filters["radial"] == (200.0, 220.0)
    assert filters["area"] is None


def test_bounds_treats_a_half_open_range_as_set():
    assert _bounds(-1e30, 10.0) == (-1e30, 10.0)
    assert _bounds(0.0, 1e30) == (0.0, 1e30)
    assert _bounds(-1e30, 1e30) is None
