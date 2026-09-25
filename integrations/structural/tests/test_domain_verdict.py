"""Whether a cut sector can be used, said by the tool rather than inferred.

`preview_domain` draws a candidate sector and reports what came out of the cut:
the volume it holds, the faces on each of its two boundary planes. The one
thing that decides whether to stop is whether those two planes carry the same
number of faces - a cyclic sector is solved by tying them to each other - and
that was left as two integers in a reply of eleven fields.

Measured on the second complete loop run. rev-2's domain agent settled the
period in four calls, then cut nine angles from 0 to 8 degrees one at a time
and ran out of budget with nothing submitted. Five of those nine were usable:

    theta_low   faces low/high   area low/high mm2   verdict
        0.0          1 / 2        7163.4 / 6283.1    boundary cuts a feature
        1.0       2 solids                           not a single piece
        2.0          1 / 1        7163.4 / 7163.4    usable
        3.0          1 / 1        7163.4 / 7163.4    usable
        4.0          1 / 1        7163.4 / 7163.4    usable
        5.0       2 solids                           not a single piece
        6.0          1 / 1        6500.6 / 6500.6    usable
        7.0       2 solids                           not a single piece
        8.0          1 / 1        7163.4 / 7163.4    usable

A cut costs three to four minutes, so a sweep of the period is eighteen cuts
and cannot finish inside a budget of fourteen. The verdict exists so that the
first angle that works is recognisable as the answer.
"""
from __future__ import annotations

import pytest

from seekflow_structural.core.domain_preview import _verdict

# (theta_low, faces_low, faces_high, area_low, area_high) - measured on the
# model rev-000002 was built from.
MEASURED = [
    (0.0, 1, 2, 7163.368, 6283.138),
    (2.0, 1, 1, 7163.368, 7163.368),
    (3.0, 1, 1, 7163.368, 7163.368),
    (4.0, 1, 1, 7163.368, 7163.368),
    (6.0, 1, 1, 6500.578, 6500.578),
    (8.0, 1, 1, 7163.368, 7163.368),
]


def _call(theta, low, high, area_low, area_high, full=False):
    counts = {"low": low, "high": high, "sym": 3}
    areas = {"low": area_low, "high": area_high, "sym": 0.0}
    return _verdict(counts, areas, full)


@pytest.mark.parametrize("theta", [2.0, 3.0, 4.0, 6.0, 8.0])
def test_an_angle_the_agent_passed_over_is_reported_usable(theta):
    """The five answers it had and did not take."""
    row = next(r for r in MEASURED if r[0] == theta)
    usable, why = _call(*row)
    assert usable is True
    assert "can be tied" in why
    assert "1 face" in why


def test_the_angle_that_cuts_a_feature_is_reported_unusable():
    """Unequal counts are the one thing the check exists to catch."""
    usable, why = _call(*MEASURED[0])
    assert usable is False
    assert "1 low" in why and "2 high" in why
    assert "Turn the sector" in why


def test_a_plane_with_no_face_is_unusable_even_when_the_counts_match():
    """Equal and zero is not a sector - there is no surface to tie."""
    usable, why = _call(0.0, 0, 0, 0.0, 0.0)
    assert usable is False
    assert "no face" in why


def test_the_count_matters_before_the_area_does():
    """Two planes of one face each are tie-able however their areas differ.

    The check is the face count, which is what the tie is built from. Areas are
    reported beside it because a reader wants to see them; they are not the
    test, and making them one would refuse sectors that solve.
    """
    usable, _ = _call(6.0, 1, 1, 6500.578, 6500.578)
    assert usable is True
    usable, _ = _call(0.0, 2, 2, 7163.368, 6283.138)
    assert usable is True


def test_the_whole_part_is_usable_with_nothing_to_tie():
    """360 degrees has no cut planes, so it cannot disagree with itself."""
    usable, why = _call(0.0, 0, 0, 0.0, 0.0, full=True)
    assert usable is True
    assert "no cut planes" in why


def test_the_domain_agent_has_a_terminal_decision_turn():
    from seekflow_structural.agents import domain

    spec = domain.spec(max_calls=4)
    assert spec.terminal_model is domain.CommitAction
    schema = domain.CommitAction.model_json_schema()
    assert set(schema["properties"]["action"]["enum"]) == {
        "submit_domain", "needs_input"
    }
