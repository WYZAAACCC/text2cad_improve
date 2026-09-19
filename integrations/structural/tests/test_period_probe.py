"""Reading a periodicity probe: which of the orders scoring alike is the unit.

The numbers in here are measurements, not inventions. They were taken from the
D27 model the loop generated (`model.step`, 4,216 faces) by running
`probe_periodicity` at each order, and they are the reply that left the domain
agent unable to decide: five orders - 20, 10, 5, 4 and 2 - all came back at
`matched_area_fraction` 0.98888, and nothing in the reply said which of them
was the repeat unit. It spent the remaining twelve calls of its budget sweeping
the whole divisor space of 360 and submitted nothing, so the run produced no
result at all.

The part is 20-fold: it repeats every 18 degrees, and therefore also every 36,
72, 90 and 180. Validity at a coarse period is *implied* by validity at a finer
one, so the repeat unit is the finest confirmed period - the largest order -
and the coarser ones are consequences rather than candidates.
"""
from __future__ import annotations

import pytest

from seekflow_structural.core.mesh_profile import (
    finest_confirmed_order,
    probe_periodicity,
)

# (order, matched_area_fraction, residual_bins, bins_holding_90pct,
#  busiest_bin_fraction) - measured on the generated D27 model.
MEASURED = [
    (20, 0.98888, 72, 5, 0.4989),   # 18 deg - the repeat unit
    (10, 0.98888, 72, 4, 0.5071),   # 36 deg - a multiple
    (5, 0.98888, 72, 5, 0.4989),    # 72 deg - a multiple
    (4, 0.98888, 72, 4, 0.3649),    # 90 deg - a multiple
    (2, 0.98888, 72, 4, 0.3649),    # 180 deg - a multiple
    (12, 0.96359, 72, 25, 0.0976),  # 30 deg - not a period
    (6, 0.96359, 72, 25, 0.1018),
    (3, 0.96359, 72, 25, 0.0976),
    (18, 0.67836, 72, 63, 0.0196),  # 20 deg - not a period
    (9, 0.67674, 72, 63, 0.0198),
    (60, 0.96479, 72, 24, 0.1303),  # 6 deg - not a period
    (30, 0.96359, 72, 25, 0.147),
    (36, 0.67674, 72, 63, 0.0198),
]


def _row(order, matched, bins, holding, busiest):
    """A probe reply row, in the shape `probe_periodicity` returns."""
    row = {
        "order": order,
        "period_deg": 360.0 / order,
        "matched_area_fraction": matched,
        "unmatched_face_count": 1,
        "unmatched_area_mm2": 1.0,
        "residual_bins": bins,
        "residual_bins_holding_90pct": holding,
        "residual_busiest_bin_fraction": busiest,
        "face_count": 4216,
    }
    from seekflow_structural.core.mesh_profile import _is_confirmed_period
    row["confirmed_period"] = _is_confirmed_period(row)
    return row


def _annotated(orders):
    from seekflow_structural.core.mesh_profile import _annotate_multiples
    by_order = {row[0]: row for row in MEASURED}
    return _annotate_multiples([_row(*by_order[o]) for o in orders])


# --- what a confirmed period looks like ---------------------------------


@pytest.mark.parametrize("order", [20, 10, 5, 4, 2])
def test_a_true_period_is_confirmed_however_coarse(order):
    """18 degrees and its multiples are all real periods of this part."""
    rows = _annotated([order])
    assert rows[0]["confirmed_period"] is True


@pytest.mark.parametrize("order", [12, 6, 3, 18, 9, 60, 30, 36])
def test_a_period_the_part_does_not_have_is_not_confirmed(order):
    """The fraction can look close and the residual gives it away.

    30 degrees scores 0.96359 - within 3% of the true period's 0.98888 - and
    spreads its residual over 25 of 72 bins instead of 5.
    """
    rows = _annotated([order])
    assert rows[0]["confirmed_period"] is False


def test_the_fraction_alone_would_have_accepted_a_period_that_is_not_there():
    """The residual test is load-bearing, not a refinement."""
    rows = _annotated([12])
    assert rows[0]["matched_area_fraction"] > 0.96
    assert rows[0]["confirmed_period"] is False


# --- which one is the unit ----------------------------------------------


def test_the_first_probe_the_agent_made_now_names_the_repeat_unit():
    """The reply that stalled the run, read back.

    Five orders at 0.98888. The agent named them in one call, which is the
    right thing to do; what it could not get was which of the five the part
    repeats at.
    """
    rows = _annotated([20, 10, 5, 4, 2])
    assert finest_confirmed_order(rows)["order"] == 20
    assert finest_confirmed_order(rows)["period_deg"] == pytest.approx(18.0)


def test_every_coarser_order_says_which_finer_one_accounts_for_it():
    rows = {row["order"]: row for row in _annotated([20, 10, 5, 4, 2])}
    assert rows[20]["explained_by_finer_order"] is None
    for coarser in (10, 5, 4, 2):
        assert rows[coarser]["explained_by_finer_order"] == 20


def test_a_multiple_named_alone_is_still_the_finest_in_that_call():
    """The reply is about the orders named, and says so by construction.

    Naming only 180 degrees cannot reveal that 18 is finer - the probe answers
    what it was asked. That is why the prompt asks for a spread of orders, and
    why `test_finer_periods` exists for settling it afterwards.
    """
    rows = _annotated([2])
    assert finest_confirmed_order(rows)["order"] == 2


def test_a_coarse_order_is_demoted_by_a_finer_one_in_the_same_call():
    """The relation is within the call, not a fact about the part alone."""
    alone = finest_confirmed_order(_annotated([10]))
    together = finest_confirmed_order(_annotated([10, 20]))
    assert alone["order"] == 10
    assert together["order"] == 20


def test_orders_that_are_not_multiples_do_not_explain_each_other():
    """20 and 12 do not divide each other, so neither demotes the other."""
    rows = {row["order"]: row for row in _annotated([20, 12])}
    assert rows[12]["explained_by_finer_order"] is None
    assert rows[20]["explained_by_finer_order"] is None


def test_a_call_with_no_confirmed_period_returns_no_unit():
    """A shortlist that missed is told so rather than given the best of a bad set."""
    assert finest_confirmed_order(_annotated([18, 9, 36])) is None


def test_a_finer_order_that_is_not_a_period_does_not_promote_a_coarse_one():
    """30 degrees is finer than 90 and is not a period, so 90 stands."""
    rows = {row["order"]: row for row in _annotated([4, 12])}
    assert finest_confirmed_order(list(rows.values()))["order"] == 4


# --- the reply never claims a resolution the instrument lacks -----------


def test_an_order_finer_than_the_probe_resolves_is_not_confirmed():
    """Beyond the azimuthal resolution every order matches, so none is evidence."""
    rows = probe_periodicity([], [3600])
    assert rows[0]["below_probe_resolution"] is True
    assert rows[0]["confirmed_period"] is False
    assert rows[0]["explained_by_finer_order"] is None
