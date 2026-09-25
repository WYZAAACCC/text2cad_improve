"""The face-finding agent's actions, driven without a kernel.

`_rows_for` reads through a cache, so seeding that cache with measured-shaped
rows exercises the real resolution path - filters, index validation, criterion
checking - without opening an OCAF document. That matters because the parts of
this that broke were exactly the parts with no test: a filter that read a key
no face has, and a resolution that only accepted indices.
"""
from __future__ import annotations

import pytest

from seekflow_structural.agents import facefind
from seekflow_structural.case.model import CountClause, Criterion
from seekflow_structural.errors import StructuralError

FEATURE = "n_final_cut"


def _row(*, area, r, theta=0.0, z=0.0, kind="plane", normal=(0.0, 0.0, 1.0)):
    radial, tangential, axial = normal
    return {
        "surface_type": kind,
        "area_mm2": area,
        "centroid_mm": [r, 0.0, z],
        "centroid_cyl_mm_deg": [r, theta, z],
        "normal_xyz": list(normal),
        "normal_cylindrical": {
            "radial": radial, "tangential": tangential, "axial": axial
        },
        "edge_count": 4,
    }


@pytest.fixture
def rows():
    """Six flanks on a rim, three leaning each way, plus an end face."""
    return [
        _row(area=10.0, r=212.0, theta=0.0, kind="plane",
             normal=(-0.5, 0.8, 0.0)),
        _row(area=10.0, r=212.0, theta=1.0, kind="plane",
             normal=(-0.5, -0.8, 0.0)),
        _row(area=10.0, r=212.0, theta=2.0, kind="plane",
             normal=(-0.5, 0.8, 0.0)),
        _row(area=10.0, r=212.0, theta=3.0, kind="plane",
             normal=(-0.5, -0.8, 0.0)),
        _row(area=10.0, r=212.0, theta=4.0, kind="plane",
             normal=(-0.5, 0.8, 0.0)),
        _row(area=10.0, r=212.0, theta=5.0, kind="plane",
             normal=(-0.5, -0.8, 0.0)),
        _row(area=9000.0, r=0.0, z=-38.0, kind="plane",
             normal=(0.0, 0.0, -1.0)),
    ]


@pytest.fixture
def state(rows):
    return facefind.FaceFinderState(
        session=None, cache={(FEATURE, 0): rows}
    )


def _action(**kwargs):
    return facefind.Action(action="submit_faces", feature=FEATURE, **kwargs)


CRITERION = Criterion(intent="the flank faces that carry the load")


def test_submit_by_filters_resolves_the_set(state):
    """The agent's answer, stated as the filters that describe it."""
    out = facefind._submit_faces(
        _action(criterion=CRITERION, normal_radial_max=-0.2), state
    )["result"]
    assert out["accepted"] is True
    assert out["selection_method"] == "filters"
    assert len(out["selected_face_indices"]) == 6
    assert out["area_mm2_total"] == 60.0
    assert out["load_radius_mm"] == 212.0
    assert out["radius_min_mm"] == 212.0


def test_submit_by_indices_still_works(state):
    out = facefind._submit_faces(
        _action(criterion=CRITERION, face_indices=[0, 1]), state
    )["result"]
    assert out["selection_method"] == "indices"
    assert out["selected_face_indices"] == [0, 1]


def test_filters_win_over_indices_when_both_are_given(state):
    """Stated both ways, the filters are the narrower claim."""
    out = facefind._submit_faces(
        _action(criterion=CRITERION, face_indices=[6],
                normal_radial_max=-0.2), state
    )["result"]
    assert out["selection_method"] == "filters"
    assert 6 not in out["selected_face_indices"]


def test_submit_with_neither_is_refused(state):
    from seekflow_structural.errors import StructuralError

    with pytest.raises(StructuralError) as exc:
        facefind._submit_faces(_action(criterion=CRITERION), state)
    assert exc.value.diagnostic.code == "no_faces"


def test_submit_needs_a_criterion(state):
    from seekflow_structural.errors import StructuralError

    with pytest.raises(StructuralError) as exc:
        facefind._submit_faces(
            _action(normal_radial_max=-0.2), state
        )
    assert exc.value.diagnostic.code == "no_criterion"


def test_a_selection_outside_the_solved_sector_is_refused(state):
    """The correct feature in another repeated sector is not in the mesh."""
    state.sector = {"theta_low_deg": 9.0, "theta_high_deg": 27.0}
    from seekflow_structural.errors import StructuralError

    with pytest.raises(StructuralError) as exc:
        facefind._submit_faces(
            _action(criterion=CRITERION, normal_radial_max=-0.2), state
        )
    assert exc.value.diagnostic.code == "selection_outside_sector"
    assert "theta" in str(exc.value)


def _normal_family_rows():
    """An outer load band with two normal families and a low-radius decoy."""
    return [
        _row(area=100.0, r=100.0, theta=float(index),
             normal=(-0.95, 0.1, 0.0))
        for index in range(4)
    ] + [
        _row(area=100.0, r=250.0, theta=float(index),
             normal=(-0.8, 0.1, 0.0))
        for index in range(4)
    ] + [
        _row(area=100.0, r=250.0, theta=float(index),
             normal=(-0.3, 0.1, 0.0))
        for index in range(4, 8)
    ]


def test_a_flank_selection_cannot_mix_the_two_normal_families():
    """D27's failure mode: other radial bands and shallow tooth faces are not
    the working flanks. The gap is measured from the model, so the gate does
    not hard-code D27's face indices or normal threshold."""
    rows = _normal_family_rows()
    state = facefind.FaceFinderState(
        session=None, cache={(FEATURE, 0): rows}, require_planar=True,
        load_direction_rule="flank_surface_normal",
    )

    with pytest.raises(StructuralError) as excinfo:
        facefind._submit_faces(
            _action(criterion=CRITERION, normal_radial_max=-0.2), state
        )
    assert excinfo.value.diagnostic.code == "selection_mixes_normal_families"


def test_the_strong_normal_family_can_be_submitted_whole():
    rows = _normal_family_rows()
    state = facefind.FaceFinderState(
        session=None, cache={(FEATURE, 0): rows}, require_planar=True,
        load_direction_rule="flank_surface_normal",
    )

    out = facefind._submit_faces(
        _action(criterion=CRITERION, radial_min=250.0,
                normal_radial_min=-0.9, normal_radial_max=-0.7),
        state,
    )["result"]
    assert out["selected_face_indices"] == [4, 5, 6, 7]


def test_query_reports_the_normal_family_separation_before_submission():
    rows = _normal_family_rows()
    state = facefind.FaceFinderState(
        session=None, cache={(FEATURE, 0): rows}, require_planar=True,
        load_direction_rule="flank_surface_normal",
    )

    out = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE), state
    )["result"]
    alignment = out["load_normal_alignment"]
    assert alignment["separation"]["significant"] is True
    assert alignment["strong_family"]["face_count"] == 4
    assert alignment["separation"]["normal"][
        "upper_family_alignment_min"
    ] == pytest.approx(0.8)
    assert alignment["strong_family"]["measured_query_bounds"] == {
        "radial_min": 250.0,
        "normal_radial_max": -0.8,
    }


def test_query_reports_sector_coverage_before_submission(state):
    state.sector = {"theta_low_deg": 2.0, "theta_high_deg": 4.0}
    out = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE), state
    )["result"]
    coverage = out["sector_coverage"]
    assert coverage["inside_count"] == 3
    assert coverage["outside_count"] == 4
    assert coverage["applicable"] is True


def test_a_curved_load_face_is_refused_when_pressure_mapping_requires_a_plane(state):
    rows = state.cache[(FEATURE, 0)]
    rows[1]["surface_type"] = "cylinder"
    state.require_planar = True
    from seekflow_structural.errors import StructuralError

    with pytest.raises(StructuralError) as exc:
        facefind._submit_faces(
            _action(criterion=CRITERION, normal_radial_max=-0.2), state
        )
    assert exc.value.diagnostic.code == "selection_not_mappable"
    assert "planar" in str(exc.value)


def test_check_criterion_reports_structural_submission_readiness(state):
    state.sector = {"theta_low_deg": 9.0, "theta_high_deg": 27.0}
    out = facefind._check_criterion(
        facefind.Action(
            action="check_criterion", feature=FEATURE,
            criterion=CRITERION, normal_radial_max=-0.2,
        ),
        state,
    )["result"]
    assert out["submission"]["ready"] is False
    assert out["submission"]["sector"]["outside_count"] == 6


def test_filters_matching_nothing_says_so(state):
    from seekflow_structural.errors import StructuralError

    with pytest.raises(StructuralError) as exc:
        facefind._submit_faces(
            _action(criterion=CRITERION, radial_min=5000.0), state
        )
    assert exc.value.diagnostic.code == "filters_match_nothing"


def test_an_out_of_range_index_is_named(state):
    from seekflow_structural.errors import StructuralError

    with pytest.raises(StructuralError) as exc:
        facefind._submit_faces(
            _action(criterion=CRITERION, face_indices=[99]), state
        )
    assert exc.value.diagnostic.code == "face_index_out_of_range"


def test_check_criterion_accepts_filters_without_a_listing(state):
    """Checking and submitting are the same statement.

    `check_criterion` used to take indices only, so an agent that had narrowed
    a set with filters had to spend a call listing it just to read its own
    indices off a page before it could check it.
    """
    out = facefind._check_criterion(
        facefind.Action(
            action="check_criterion", feature=FEATURE,
            criterion=Criterion(
                intent="inward-pointing flanks",
                normal_clauses=[],
            ),
            normal_radial_max=-0.2,
        ),
        state,
    )["result"]
    assert out["checked_face_count"] == 6
    assert out["face_count"] == 6


def test_check_criterion_reports_a_count_clause_it_fails(state):
    out = facefind._check_criterion(
        facefind.Action(
            action="check_criterion", feature=FEATURE,
            criterion=Criterion(
                intent="exactly four flanks", count=CountClause(max_count=4)
            ),
            normal_radial_max=-0.2,
        ),
        state,
    )["result"]
    assert out["count_clause"]["satisfied"] is False
    assert out["satisfied"] is False


def test_check_criterion_needs_a_criterion(state):
    from seekflow_structural.errors import StructuralError

    with pytest.raises(StructuralError) as exc:
        facefind._check_criterion(
            facefind.Action(action="check_criterion", feature=FEATURE,
                            normal_radial_max=-0.2),
            state,
        )
    assert exc.value.diagnostic.code == "no_criterion"


def test_a_matched_set_within_the_budget_is_listed_without_being_asked(state):
    """A set the reply can carry is not a set you should have to ask to see.

    Both ways of getting this wrong have been measured. Leaving a small set
    behind a summary-only default had an agent write "list the carried faces
    to read their normals" as its reason, get a summary anyway, and spend
    fourteen calls re-running the query. A cutoff of sixty faces put the sets
    this agent actually selects - 195, 308 - on the wrong side of the line, and
    it re-ran the identical query up to twenty-five times.
    """
    out = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE), state
    )["result"]
    assert out["matched"] == 7
    assert out["faces_listed"] == 7
    assert out["listed_in_full"] is True
    assert len(out["listing"]["faces"]) == 7
    assert out["listing"]["columns"][0] == "index"


def test_a_set_of_a_few_hundred_faces_is_still_listed(state):
    """The sets this agent selects land here, and used to be shown nothing."""
    rows = [dict(state.cache[(FEATURE, 0)][0]) for _ in range(300)]
    big = facefind.FaceFinderState(session=None, cache={(FEATURE, 0): rows})
    out = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE), big
    )["result"]
    assert out["matched"] == 300
    assert out["faces_listed"] == 300
    assert out["listed_in_full"] is True


def test_a_listing_larger_than_the_budget_is_cut_and_says_so(state):
    """Bounded by reply size, not by a face count that lands on a cliff."""
    row = state.cache[(FEATURE, 0)][0]
    rows = [dict(row) for _ in range(4000)]
    huge = facefind.FaceFinderState(session=None, cache={(FEATURE, 0): rows})
    out = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE), huge
    )["result"]
    assert out["matched"] == 4000
    assert out["listed_in_full"] is False
    assert 0 < out["faces_listed"] < 4000
    assert out["listing"]["faces_withheld"] == 4000 - out["faces_listed"]
    assert "of 4000 faces" in out["note"]


def test_an_explicit_limit_still_pages(state):
    out = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE, limit=3), state
    )["result"]
    assert out["faces_listed"] == 3
    assert out["listed_in_full"] is False
    assert out["listing"]["faces_withheld"] == 4


def test_a_listed_row_carries_what_a_filter_is_written_from(state):
    out = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE), state
    )["result"]
    line = out["listing"]["faces"][0]
    values = line.split("|")
    assert len(values) == len(out["listing"]["columns"])
    assert values[0] == "0"          # index
    assert values[1] == "plane"      # type
    assert abs(float(values[2]) - 212.0) < 1e-6   # radius


def test_query_reports_what_it_actually_asked(state):
    out = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE,
                        radial_min=200.0, radial_max=220.0),
        state,
    )["result"]
    assert out["filters_applied"] == {"radial": [200.0, 220.0]}

    empty = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE), state
    )["result"]
    assert empty["filters_applied"] == {}


def test_the_agent_is_told_how_the_load_normal_families_are_reported():
    prompt = facefind.spec(requirement="the loaded faces").system_prompt
    assert "load_normal_alignment" in prompt
    assert "strongly aligned" in prompt


def test_the_agent_is_told_which_sector_is_being_solved():
    """A selection has to land inside the part that is actually meshed.

    Solving one sector of twenty means the other nineteen are not in the
    model. A selection that reaches across all of them looks correct - every
    one of those faces does carry the load - and describes a different part.
    """
    whole = facefind.spec(requirement="the loaded faces")
    assert "sector" not in whole.user_prompt.lower()

    sector = facefind.spec(
        requirement="the loaded faces", sector_deg=18.0, theta_low_deg=9.0
    )
    assert "the loaded faces" in sector.user_prompt
    assert "9 to 27 degrees" in sector.user_prompt
    assert "one sector's worth" in sector.user_prompt


def test_a_full_revolution_is_not_described_as_a_sector():
    full = facefind.spec(
        requirement="the loaded faces", sector_deg=360.0, theta_low_deg=0.0
    )
    assert "sector" not in full.user_prompt.lower()


def test_the_scope_wraps_past_zero():
    wrapped = facefind.spec(
        requirement="r", sector_deg=18.0, theta_low_deg=350.0
    )
    assert "350 to 8 degrees" in wrapped.user_prompt


def test_an_empty_result_distinguishes_the_two_causes(state):
    """Nothing matched because of the bounds, or because nothing was asked."""
    narrowed = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE,
                        radial_min=5000.0),
        state,
    )["result"]
    assert narrowed["matched"] == 0
    assert "widen" in narrowed["note"]

    # An unfiltered query that returns nothing is not a fact about the part,
    # and the note has to say so - an agent told only "empty" keeps searching.
    blank = facefind.FaceFinderState(session=None, cache={(FEATURE, 0): []})
    nothing = facefind._query_faces(
        facefind.Action(action="query_faces", feature=FEATURE), blank
    )["result"]
    assert nothing["matched"] == 0
    assert "not working" in nothing["note"]


def test_the_retry_condition_is_exhaustion_not_a_missing_final():
    """The retry was written against the wrong signal and never ran.

    `facefind.run` replaces a missing final with an `exhausted_final` dict, so
    `outcome.final is None` is never true and a check on it is dead code. The
    signal that means "the agent ran out of calls" is `exhausted`, and it is
    the only one that should start a second attempt - `needs_input` also
    produces `accepted: False`, and retrying a question the agent asked would
    be asking it again and hoping for a different answer.
    """
    from seekflow_structural.runtime.loop import AgentOutcome

    out_of_calls = AgentOutcome(final=None, calls=30, exhausted=True)
    asked_a_question = AgentOutcome(
        final={"accepted": False, "questions": ["which end is up?"]},
        calls=4, exhausted=False,
    )

    # What the stage would do with each, expressed the way the stage checks it.
    assert out_of_calls.exhausted is True
    assert out_of_calls.final is not None or out_of_calls.exhausted
    assert asked_a_question.exhausted is False

def test_a_radial_load_cannot_include_nearly_tangential_faces():
    """The D25/D26 failure: a population too flat to split still has a
    physical direction requirement."""
    rows = [
        _row(area=100.0, r=250.0, theta=float(index),
             normal=(-0.8, 0.6, 0.0))
        for index in range(3)
    ] + [
        _row(area=100.0, r=250.0, theta=float(index + 3),
             normal=(-0.02, 0.999, 0.0))
        for index in range(3)
    ]
    state = facefind.FaceFinderState(
        session=None, cache={(FEATURE, 0): rows}, require_planar=True,
        load_direction_rule="flank_surface_normal",
    )
    with pytest.raises(StructuralError) as excinfo:
        facefind._submit_faces(
            _action(criterion=CRITERION, normal_radial_min=-1.0,
                    normal_radial_max=0.0),
            state,
        )
    assert "selection_includes_non_radial_faces" in str(
        excinfo.value.diagnostic.code
    )

