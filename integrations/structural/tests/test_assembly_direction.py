"""What the assembly stage reports about the faces it just chose.

The stage's job is to turn a submission into the case's load surface. It also
measures which way the pressure on that surface pushes, and reports it - the
cheapest place to notice that a selection cannot be the one that was asked
for, rather than three stages later once a mesh and a solve have been paid
for.

It reports and does not refuse. What a load face is, is the agent's judgement;
the verification stage is where a contradiction becomes a verdict.
"""
from __future__ import annotations

from seekflow_structural.agents import assembly, facefind

FEATURE = "n_final_cut"


def a_face(index, radial, *, area=100.0, tangential=0.0):
    return {
        "surface_type": "plane",
        "area_mm2": area,
        "centroid_mm": [288.0, 0.0, 0.0],
        "centroid_cyl_mm_deg": [288.0, 10.0, 0.0],
        "normal_xyz": [radial, tangential, 0.0],
        "normal_cylindrical": {
            "radial": radial, "tangential": tangential, "axial": 0.0,
        },
        "edge_count": 4,
    }


def a_state(rows, indices):
    """The state the agent leaves behind: its rows, and what it submitted."""
    state = facefind.FaceFinderState(session=None)
    state.cache[(FEATURE, 0)] = rows
    state.submitted = {
        "accepted": True,
        "feature": FEATURE,
        "solid_index": 0,
        "selected_face_indices": indices,
        "criterion": {"intent": "the faces the load enters through"},
    }
    return state


def test_the_reported_direction_describes_the_faces_that_were_submitted():
    """An outward normal pointing away from the axis means the pressure -
    which acts along the inward normal - pushes the material outward."""
    rows = [a_face(0, -0.9), a_face(1, -0.8)]
    state = a_state(rows, [0, 1])
    surface = facefind.to_case_selection(state, None)
    comparison = assembly._load_direction(state, surface)
    assert comparison.name == "load_pushes_outward"
    assert comparison.residual is not None and comparison.residual > 0.5


def test_a_selection_pressing_the_wrong_way_is_reported_as_such():
    rows = [a_face(0, 1.0), a_face(1, 1.0)]
    state = a_state(rows, [0, 1])
    surface = facefind.to_case_selection(state, None)
    comparison = assembly._load_direction(state, surface)
    assert comparison.residual == -1.0
    # And it is a comparison the verdict can act on, not one printed beside a
    # number it is unable to contradict.
    assert comparison.relative == 1.0


def test_only_the_submitted_faces_are_measured():
    """The rows hold every face of the body; the direction is about the set.

    Measuring the whole body would report the part's own average, which is
    not a statement about the selection at all.
    """
    rows = [a_face(0, -1.0), a_face(1, 1.0), a_face(2, 1.0), a_face(3, 1.0)]
    state = a_state(rows, [0])
    surface = facefind.to_case_selection(state, None)
    comparison = assembly._load_direction(state, surface)
    assert comparison.residual == 1.0


def test_an_index_outside_the_rows_is_skipped_rather_than_crashing():
    """A selection that names a face the body does not have is caught by the
    submission's own validation; this must not turn it into an IndexError."""
    rows = [a_face(0, -1.0)]
    state = a_state(rows, [0, 99])
    surface = facefind.to_case_selection(state, None)
    comparison = assembly._load_direction(state, surface)
    assert comparison.residual == 1.0
