"""Cross-consistency, and the verdicts drawn from it.

The point of these is the classification, which went wrong twice while being
written and was caught both times by exactly these assertions.

First version: a quantity with more evidence was judged more weakly, so two
agreeing measurements came back "suspect" and one came back "unverified".

Second version: a quantity that had moved between mesh levels came back
"confirmed_wrong", which says the number is contradicted when what actually
happened is that it has not settled.

Neither is a hypothetical. Both are the kind of inversion that reads fine in
a report and is wrong.
"""
from __future__ import annotations

import pytest

from seekflow_structural.tools import checks


def test_two_measurements_that_contradict_are_confirmed_wrong():
    comparison = checks.reaction_vs_applied([900.0, 0.0, 0.0],
                                            [-1000.0, 0.0, 0.0])
    assert comparison.relative == pytest.approx(0.1)
    assert checks.classify([comparison]) == "confirmed_wrong"


def test_two_measurements_that_agree_are_not_called_verified():
    """Agreement between two measurements of the same model is not validation.

    Only agreement with something outside the model would be, and this chain
    has no analytic oracle. Reporting "verified" here would overstate exactly
    what a report is for.
    """
    agreeing = checks.reaction_vs_applied([1000.0, 0.0, 0.0],
                                          [-1000.0, 0.0, 0.0])
    assert agreeing.relative < 1e-9
    assert checks.classify([agreeing, checks.temperature_two_sites(0.0, 10)]) \
        == "unverified"


def test_a_quantity_that_moved_between_mesh_levels_is_suspect_not_wrong():
    """Not settled is a different statement from contradicted."""
    moved = checks.mesh_convergence({"max_von_mises_mpa": 8.6})
    assert checks.classify(moved) == "suspect"


def test_a_quantity_that_settled_between_mesh_levels_is_not_suspect():
    settled = checks.mesh_convergence({"max_von_mises_mpa": 0.3})
    assert checks.classify(settled) == "unverified"


def test_more_evidence_never_weakens_a_verdict():
    """The inversion that was written by accident, pinned."""
    agreeing = checks.reaction_vs_applied([1000.0, 0.0, 0.0],
                                          [-1000.0, 0.0, 0.0])
    one = checks.classify([agreeing])
    two = checks.classify([agreeing, checks.temperature_two_sites(0.0, 10)])
    assert two != "suspect", "adding agreeing evidence made the verdict weaker"


def test_nothing_at_all_is_unverified_rather_than_wrong():
    assert checks.classify([]) == "unverified"
    assert checks.classify(checks.mesh_convergence(None)) == "unverified"


def test_a_check_with_no_data_says_so_rather_than_passing():
    comparison = checks.reaction_vs_applied(None, None)
    assert comparison.residual is None
    assert "not available" in comparison.note
    assert checks.classify([comparison]) == "unverified"


def test_the_reaction_check_reports_both_numbers_it_compared():
    comparison = checks.reaction_vs_applied([3.0, 4.0, 0.0],
                                            [-3.0, -4.0, 0.0])
    assert "5" in comparison.left
    assert "5" in comparison.right


def test_the_load_surface_check_reports_its_contamination_rather_than_hiding_it():
    """The ANSYS-side sum includes the centrifugal load of those elements, so
    the estimate of that is shown beside the number and not subtracted out."""
    comparison = checks.load_surface_vs_target(
        11000.0, 1000.0, 10000.0
    )
    assert comparison.relative == pytest.approx(0.0, abs=1e-9)
    assert "1000" in comparison.note
    assert "not subtrac" in comparison.note or "rather than" in comparison.note


def test_every_check_explains_what_it_compared():
    comparisons = [
        checks.reaction_vs_applied([1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]),
        checks.temperature_two_sites(0.0, 5),
        checks.symmetry_residual(0.0, True),
        checks.load_surface_vs_target(10.0, 0.0, 10.0),
        checks.section_equilibrium(10.0, 10.0),
    ] + checks.mesh_convergence({"a": 1.0})
    for comparison in comparisons:
        assert comparison.left
        assert comparison.right
        assert comparison.note, f"{comparison.name} has no note"


def _face(area, radial, tangential=0.0):
    return {
        "area_mm2": area,
        "normal_cylindrical": {
            "radial": radial, "tangential": tangential, "axial": 0.0
        },
    }


class TestLoadDirection:
    """A magnitude cannot carry a direction, and the load checks only had one.

    Measured over twenty-four runs of the face-finding agent, nine submissions
    were wrong and every one passed every check the chain had - four of them
    having put the load on the disc's outer cylindrical face, where the
    pressure acts inward and a blade load is centrifugal and pulls outward.
    """

    def test_inward_facing_flanks_push_the_disc_outward(self):
        """The bearing faces: outward normals point at the axis, so pressure
        pushes away from it. That is what carries a blade."""
        per_face = {
            "9": _face(82.2, -0.982, 0.190),
            "10": _face(82.6, -0.840, 0.542),
            "12": _face(83.3, -0.574, 0.819),
        }
        result = checks.load_pushes_outward(per_face)
        assert result.residual is not None and result.residual > 0.5
        assert "outward" in result.right

    def test_the_outer_cylinder_pushes_the_disc_inward(self):
        """The wrong answer this was written for."""
        per_face = {"3960": _face(1166.1, 1.0), "3961": _face(1166.1, 1.0)}
        result = checks.load_pushes_outward(per_face)
        assert result.residual == pytest.approx(-1.0, abs=1e-9)

    def test_a_ring_of_facets_cancels(self):
        """A hole's wall faces every way at once, so its resultant is nothing
        radial - which is not a blade load either."""
        per_face = {
            "0": _face(50.0, -0.98, 0.19),
            "1": _face(50.0, 0.98, -0.19),
        }
        result = checks.load_pushes_outward(per_face)
        assert result.residual == pytest.approx(0.0, abs=1e-6)

    def test_an_empty_mapping_reports_rather_than_raises(self):
        result = checks.load_pushes_outward({})
        assert result.residual is None
        assert "no selected faces" in result.left

    def test_faces_without_a_measured_normal_are_counted_not_guessed(self):
        per_face = {
            "0": _face(50.0, -0.9),
            "1": {"area_mm2": 50.0, "normal_cylindrical": {"radial": None}},
        }
        result = checks.load_pushes_outward(per_face)
        assert result.residual == pytest.approx(0.9, abs=1e-6)
        assert "1 faces had no measured normal" in result.note

    def test_it_does_not_catch_the_right_kind_of_face_in_the_wrong_place(self):
        """The limit, pinned so nobody reads the name as a guarantee.

        A selection of inward-facing flanks at the wrong radius scores much
        the same as one at the right radius: measured on the real part, a
        wrong submission on the mid-web faces scored +0.652 against the
        correct answer's +0.742. The check sees which way the pressure
        pushes, not where it pushes, and which of two similarly-facing
        surfaces a blade bears on is engineering knowledge.
        """
        # The correct answer and a wrong one, both inward-facing flank sets.
        correct = {"a": _face(82.2, -0.982, 0.190),
                   "b": _face(82.6, -0.840, 0.542),
                   "c": _face(83.3, -0.574, 0.819)}
        elsewhere = {"a": _face(82.2, -0.760, 0.650),
                     "b": _face(82.6, -0.574, 0.819)}
        right = checks.load_pushes_outward(correct).residual
        wrong = checks.load_pushes_outward(elsewhere).residual
        assert right is not None and wrong is not None
        assert right > 0.5 and wrong > 0.5
        # Both pass; the check does not tell them apart.
        assert abs(right - wrong) < 0.3
        assert "not where it pushes" in checks.load_pushes_outward.__doc__

    def test_the_area_weights_the_direction(self):
        """A big face pointing the wrong way is not outvoted by a small one."""
        per_face = {
            "0": _face(1000.0, 1.0),      # large, pushes inward
            "1": _face(1.0, -1.0),        # tiny, pushes outward
        }
        result = checks.load_pushes_outward(per_face)
        assert result.residual is not None and result.residual < 0

    def test_an_outward_load_is_not_a_contradiction(self):
        per_face = {"0": _face(50.0, -0.9), "1": _face(50.0, -0.8)}
        result = checks.load_pushes_outward(per_face)
        assert result.relative == 0.0
        assert checks.classify([result]) == "unverified"

    def test_an_inward_load_contradicts_the_physics_it_was_given(self):
        """The verdict this check could not produce until it had a relative.

        `classify` drops every comparison whose `relative` is None before it
        looks for a contradiction, so a check that reported only a residual
        was carried beside a quantity without ever being able to decide it -
        reported, and inert. A load driven by rotation pushes outward; one
        that resolves inward contradicts the stated premise.
        """
        per_face = {"0": _face(1000.0, 1.0), "1": _face(1000.0, 1.0)}
        result = checks.load_pushes_outward(per_face)
        assert result.relative == pytest.approx(1.0, abs=1e-9)
        assert checks.classify([result]) == "confirmed_wrong"

    def test_a_cancelling_selection_is_not_called_a_contradiction(self):
        """A set that resolves to nothing radial is a different fault.

        It is not pushing the wrong way; there is no push. The force-versus-
        target check is the one that has something to say about it.
        """
        per_face = {
            "0": _face(50.0, -0.98, 0.19),
            "1": _face(50.0, 0.98, -0.19),
        }
        result = checks.load_pushes_outward(per_face)
        assert result.relative == pytest.approx(0.0, abs=1e-6)
        assert checks.classify([result]) == "unverified"
