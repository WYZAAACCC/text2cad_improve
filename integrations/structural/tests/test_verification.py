"""Which reported numbers may be quoted, and what can take that away.

The verification stage turns evidence into a verdict per quantity. The thing
worth pinning is which evidence reaches which quantity, because a check that
is real and a check that is decorative look identical in a report: both are
printed beside the number.

The case this exists for: a load applied to the wrong faces. The deck is built
by scaling the pressure until the resultant hits the target force, so the
magnitude of the applied load is the target *by construction* - the reaction
check cannot see a wrong selection, and neither can the force-versus-target
check. The direction of the pressure is the only evidence there is, and until
it carried a `relative` it was filtered out of the verdict before it could
contradict anything.
"""
from __future__ import annotations

import json

from seekflow_structural.agents.verify import build_verdicts
from seekflow_structural.pipeline.orchestrator import Budget, RunContext
from seekflow_structural.runtime.store import JobStore

# A face whose pressure pushes outward: the outward normal points away from
# the axis, so the force the face puts on the body runs inward - wait, the
# other way. Pressure acts along the inward normal, so a face whose outward
# normal has a positive radial component pushes the material inward. The
# correct answer is a set of faces whose pressure resolves outward.
OUTWARD_FACE = {
    "area_mm2": 100.0,
    "normal_cylindrical": {"radial": -0.9, "tangential": 0.4, "axial": 0.0},
}
INWARD_FACE = {
    "area_mm2": 100.0,
    "normal_cylindrical": {"radial": 1.0, "tangential": 0.0, "axial": 0.0},
}


def a_context(tmp_path, *, per_face: dict, reaction_n: float = 10000.0,
              applied_n: float = 10000.0) -> RunContext:
    job = JobStore(tmp_path, "verify-test")
    solve = job.path / "solve"
    solve.mkdir(parents=True, exist_ok=True)
    (solve / "result_summary.txt").write_text(
        "MAX_DISPLACEMENT_MM =   0.32274564E+01\n"
        "MAX_VON_MISES_MPA =   0.14831269E+04\n"
        f"REACTION_SUM_N =   {reaction_n:.8E}  0.0  0.0\n",
        encoding="utf-8",
    )
    (solve / "structural_metrics.json").write_text(json.dumps({
        "stress": {
            "max_von_mises_mpa": 812.5,
            "max_load_surface_von_mises_mpa": 640.0,
            "min_safety_factor": 1.21,
            "max_radius_mm": 288.0,
        },
        "displacement": {"max_mm": 0.44},
        "temperature_provenance": {
            "max_abs_delta_c": 0.0, "compared_node_count": 1000,
        },
        "axial_symmetry": {"max_abs_uz_mm": 0.0, "node_count": 500},
    }), encoding="utf-8")
    (solve / "load_audit.json").write_text(json.dumps({
        "applied_resultant_n": [applied_n, 0.0, 0.0],
        "target_force_n_per_slot": applied_n,
    }), encoding="utf-8")
    (solve / "selected_face_nodes.json").write_text(
        json.dumps({"per_face": per_face}), encoding="utf-8"
    )
    return RunContext(job=job, case_store=None, budget=Budget())


def verdicts_of(ctx) -> dict:
    return {v.quantity: v.verdict for v in build_verdicts(ctx, None)}


def test_an_outward_load_leaves_the_numbers_standing(tmp_path):
    ctx = a_context(tmp_path, per_face={"0": OUTWARD_FACE, "1": OUTWARD_FACE})
    assert verdicts_of(ctx) == {
        "max_von_mises_mpa": "unverified",
        "max_load_surface_von_mises_mpa": "unverified",
        "min_safety_factor": "unverified",
        "max_displacement_mm": "unverified",
    }


def test_an_inward_load_condemns_every_stress_derived_number(tmp_path):
    """Not only the peak on the loaded surface.

    The load is on the wrong faces, so the whole field is the answer to a
    different question. A verdict that condemns the load-surface peak and
    leaves the minimum safety factor saying "unverified" is a report that
    invites someone to quote it.
    """
    ctx = a_context(tmp_path, per_face={"0": INWARD_FACE, "1": INWARD_FACE})
    verdicts = verdicts_of(ctx)
    for quantity in (
        "max_von_mises_mpa", "max_load_surface_von_mises_mpa",
        "min_safety_factor", "max_displacement_mm",
    ):
        assert verdicts[quantity] == "confirmed_wrong", quantity


def test_the_direction_check_reaches_the_verdict_at_all(tmp_path):
    """The regression, stated directly.

    The comparison was reported beside the numbers and never consulted: a
    comparison whose `relative` is None is dropped before the contradiction
    test, so this one could not change a verdict however wrong the load was.
    """
    ctx = a_context(tmp_path, per_face={"0": INWARD_FACE})
    peak = [
        v for v in build_verdicts(ctx, None)
        if v.quantity == "max_load_surface_von_mises_mpa"
    ][0]
    named = {check.name: check for check in peak.checks}
    assert "load_pushes_outward" in named
    direction = named["load_pushes_outward"]
    assert direction.relative is not None, (
        "a comparison with no relative is filtered out of `classify` and is "
        "reported without ever being able to contradict anything"
    )
    assert direction.relative > 0


def test_a_selection_with_no_measured_normals_is_not_a_contradiction(tmp_path):
    """Nothing measured is not the same as measured wrong."""
    ctx = a_context(tmp_path, per_face={
        "0": {"area_mm2": 10.0, "normal_cylindrical": {"radial": None}},
    })
    assert verdicts_of(ctx)["min_safety_factor"] == "unverified"


def test_a_closed_ring_is_not_asked_for_its_reactions(tmp_path):
    """The check that condemned both headline numbers on a healthy D27 run.

    A deck written with `CPCYC` makes one sector stand for a complete ring.
    The blade load is carried by hoop tension in the neighbouring sectors the
    constraint supplies - a force inside the model, not a reaction to it - so
    the net reaction over the nodes is zero by construction. On D27 the deck's
    only external supports were the z=0 symmetry plane in UZ and a single
    anchored node in UY, and the solver reported 0.0004 N of reaction against
    10 000 N applied. Compared anyway, that is a 100% disagreement.
    """
    from seekflow_structural.agents import verify

    # The numbers D27 actually produced: 0.0004 N of reaction against 10 000 N
    # applied, which is 100% disagreement if it is read as one.
    ctx = a_context(tmp_path, per_face={"0": OUTWARD_FACE}, reaction_n=0.0004)
    reaction = [
        check for check in verify.build_verdicts(ctx, None)[0].checks
        if check.name == "reaction_vs_applied"
    ][0]
    assert reaction.relative is not None, (
        "with nothing to say the ring is closed, the comparison stands"
    )
    assert verdicts_of(ctx)["max_von_mises_mpa"] == "confirmed_wrong"

    from seekflow_structural.case.model import (
        Case, ConstraintBinding, Physics, Written,
    )
    from seekflow_structural.case.model import BundleRef

    case = Case(
        case_id="c", bundle=BundleRef(path="E:/b", lineage_id="D",
                                      revision_id="r"),
        physics=Physics(
            constraints=ConstraintBinding(cyclic_symmetry=True),
            written=Written(by_stage="assembly", kind="user_input"),
        ),
    )
    closed = [
        check for check in verify.build_verdicts(ctx, case)[0].checks
        if check.name == "reaction_vs_applied"
    ][0]
    assert closed.relative is None
    assert "cyclic symmetry" in closed.note
    assert "nothing is concluded" in closed.note
