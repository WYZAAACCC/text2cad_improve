"""The loop, with the CAD kernel and the solver replaced by fakes.

What is tested is what the loop owns: that each revision is a copy, that a
prediction is checked against the run that followed it rather than against the
run that made it, that a rule only becomes trusted on evidence, and that a
revision which changed nothing stops the loop rather than re-running the same
design.

The two heavy steps arrive as callables, so none of that needs generating a
step file or waiting for ANSYS - and the same seam is what keeps the loop from
knowing how the existing generation system works.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seekflow_structural.pipeline import iterate
from seekflow_structural.tools import knowledge, workspace


def _master(tmp_path: Path) -> Path:
    master = tmp_path / "master"
    master.mkdir(exist_ok=True)
    (master / "param_templates.py").write_text(
        "def build(p):\n    return p\n", encoding="utf-8"
    )
    return master


class _System:
    """A stand-in for generate-and-solve, with a scripted peak per revision."""

    def __init__(self, peaks: list[float]):
        self.peaks = peaks
        self.calls = 0

    def generate(self, space: workspace.Workspace) -> Path:
        return space.output

    def solve(self, bundle: Path, space: workspace.Workspace) -> dict:
        peak = self.peaks[min(self.calls, len(self.peaks) - 1)]
        self.calls += 1
        return {
            "metrics": {"stress": {"max_von_mises_mpa": peak},
                        "displacement": {"max_mm": 3.0}},
            "verdicts": {"max_von_mises_mpa": "unverified"},
        }


def _diagnose_factory(predictions: list[float | None]):
    """A diagnosis that asks for one change each revision."""
    state = {"index": 0}

    def diagnose(metrics, verdicts, space, job_dir) -> list[dict]:
        index = state["index"]
        state["index"] += 1
        expected = predictions[min(index, len(predictions) - 1)]
        finding = {
            "id": f"F{index + 1}",
            "mechanism": "hoop_driven",
            "feature": "bore",
            "change": {
                "parameter": "rim_half_thickness_mm",
                "current_value": 30.0,
                "proposed_value": 28.0,
                "relative_change": -0.0667,
            },
        }
        if expected is not None:
            finding["prediction"] = {
                "metric": "max_von_mises_mpa",
                "direction": "decrease" if expected < 0 else "increase",
                "expected_relative_change": abs(expected),
                "at": "bore",
            }
        return [finding]

    return diagnose


def _revise_ok(findings: list[dict], space=None) -> dict:
    """Applies the change by hand, the way the real agent's tools would."""
    return {
        "applied": [finding["id"] for finding in findings],
        "skipped": [],
        "params": {"rim_mm": 28.0},
    }


def _loop(tmp_path, peaks, predictions, **kwargs) -> iterate.Loop:
    system = _System(peaks)
    return iterate.Loop(
        master_dir=_master(tmp_path),
        root=tmp_path / "revisions",
        lineage="D27",
        params={"rim_mm": 30.0},
        generate=system.generate,
        solve=system.solve,
        diagnose=_diagnose_factory(predictions),
        revise=kwargs.pop("revise", _revise_ok),
        knowledge_path=tmp_path / "knowledge.json",
        **kwargs,
    )


# --- the shape of the loop -----------------------------------------------


def test_each_revision_gets_its_own_copy(tmp_path):
    result = _loop(tmp_path, [1482.0, 1400.0], [-0.05]).run(2)
    roots = [Path(item.workspace_root) for item in result.revisions]
    assert roots == [tmp_path / "revisions" / "rev-000001",
                     tmp_path / "revisions" / "rev-000002"]
    for root in roots:
        assert (root / "scripts" / "param_templates.py").is_file()


def test_a_prediction_is_checked_against_the_run_that_followed_it(tmp_path):
    """Not against the run that made it - that would be checking itself."""
    result = _loop(tmp_path, [1482.0, 1400.0], [-0.0554]).run(2)
    first, second = result.revisions
    assert first.observations == []
    assert len(second.observations) == 1
    observation = second.observations[0]
    assert observation["outcome"] == "confirmed"
    measured = observation["measured_relative_change"]
    assert measured == pytest.approx((1400.0 - 1482.0) / 1482.0, rel=1e-6)


def test_a_change_that_moved_the_wrong_way_refutes_the_rule(tmp_path):
    result = _loop(tmp_path, [1482.0, 1500.0], [-0.05]).run(2)
    assert result.revisions[1].observations[0]["outcome"] == "refuted"
    entry = result.knowledge["entries"]
    assert entry >= 1


def _write_convergence(job: Path, coarse: float, fine: float) -> None:
    """A convergence study on disk, as the meshing stage leaves one."""
    for name, peak, nodes in (("convergence_coarse", coarse, 181_362),
                              ("convergence_fine", fine, 194_011)):
        level = job / "mesh" / "convergence" / name
        level.mkdir(parents=True, exist_ok=True)
        (level / "structural_metrics.json").write_text(
            json.dumps({
                "node_count": nodes,
                "stress_sampling": {"mesh_node_count": nodes},
                "stress": {"max_von_mises_mpa": peak},
            }),
            encoding="utf-8",
        )


def test_a_change_smaller_than_the_runs_own_mesh_noise_tests_nothing(tmp_path):
    """The measurement that decides whether a comparison means anything.

    Measured on D27: the same part meshed at 181,362 nodes and again at
    194,011 moved the peak stress by 5.09%. A change of 1.7% between two
    revisions is a third of that, so it is inside what re-meshing does on its
    own and this run cannot say the design caused it.
    """
    system = _System([1482.0, 1457.0])  # -1.69%, the D27 measurement
    original = system.solve
    jobs: list[Path] = []

    def solve(bundle, space):
        run = original(bundle, space)
        job = tmp_path / f"job{len(jobs)}"
        # Both revisions mesh differently, and both say so: 5.09% coarse to
        # fine, which is what D27 measured.
        _write_convergence(job, 1789.481, 1880.635)
        jobs.append(job)
        run["job"] = str(job)
        return run

    loop = iterate.Loop(
        master_dir=_master(tmp_path), root=tmp_path / "revisions",
        lineage="D27", params={"rim_mm": 30.0},
        generate=system.generate, solve=solve,
        diagnose=_diagnose_factory([-0.05]), revise=_revise_ok,
        knowledge_path=tmp_path / "knowledge.json",
    )
    result = loop.run(2)
    observation = result.revisions[1].observations[0]
    assert observation["outcome"] == "unmoved"
    assert "re-meshing this same part moved it" in observation["note"]
    assert result.revisions[1].noise_floors["max_von_mises_mpa"] == pytest.approx(
        (1880.635 - 1789.481) / 1789.481, rel=1e-6
    )


def test_a_change_larger_than_the_mesh_noise_is_scored_normally(tmp_path):
    """A floor that swallowed every result would be as useless as none."""
    system = _System([1482.0, 1150.0])  # -22%, well outside a 5% floor
    original = system.solve
    jobs: list[Path] = []

    def solve(bundle, space):
        run = original(bundle, space)
        job = tmp_path / f"job{len(jobs)}"
        _write_convergence(job, 1789.481, 1880.635)
        jobs.append(job)
        run["job"] = str(job)
        return run

    loop = iterate.Loop(
        master_dir=_master(tmp_path), root=tmp_path / "revisions",
        lineage="D27", params={"rim_mm": 30.0},
        generate=system.generate, solve=solve,
        diagnose=_diagnose_factory([-0.22]), revise=_revise_ok,
        knowledge_path=tmp_path / "knowledge.json",
    )
    result = loop.run(2)
    assert result.revisions[1].observations[0]["outcome"] == "confirmed"


def test_a_run_with_no_convergence_study_says_it_has_no_floor(tmp_path):
    """No study is not the same as a floor of zero."""
    result = _loop(tmp_path, [1482.0, 1400.0], [-0.055]).run(2)
    assert result.revisions[1].noise_floors == {}
    assert any("cannot say how far its own reported numbers move" in note
               for note in result.revisions[1].limits)


def test_a_finding_with_no_prediction_is_recorded_as_untested(tmp_path):
    """The loop cannot tell whether it worked, and saying so is the point."""
    result = _loop(tmp_path, [1482.0, 1400.0], [None]).run(2)
    observation = result.revisions[1].observations[0]
    assert observation["outcome"] == "untested"
    assert "no prediction" in observation["note"]


def test_a_change_that_also_made_something_else_worse_says_so(tmp_path):
    """A rule that lowers the peak by raising the displacement is not working."""
    system = _System([1482.0, 1400.0])
    original = system.solve

    def solve(bundle, space):
        run = original(bundle, space)
        if system.calls > 1:
            run["metrics"]["displacement"] = {"max_mm": 4.0}
        return run

    loop = iterate.Loop(
        master_dir=_master(tmp_path), root=tmp_path / "revisions",
        lineage="D27", params={"rim_mm": 30.0},
        generate=system.generate, solve=solve,
        diagnose=_diagnose_factory([-0.05]), revise=_revise_ok,
        knowledge_path=tmp_path / "knowledge.json",
    )
    result = loop.run(2)
    observation = result.revisions[1].observations[0]
    assert observation["outcome"] == "confirmed"
    assert any("max_displacement_mm" in entry
               for entry in observation["side_effects"])


def test_a_rule_that_holds_three_times_becomes_trusted(tmp_path):
    """The whole point of keeping the record."""
    _loop(
        tmp_path, [1482.0, 1400.0, 1320.0, 1250.0], [-0.055, -0.057, -0.053],
    ).run(4)
    base = knowledge.KnowledgeBase.load(tmp_path / "knowledge.json")
    entry = base.get("hoop_driven::rim_half_thickness_mm")
    assert entry is not None
    assert entry.confirmations >= 3
    assert entry.status == "trusted"


# --- when the loop should stop -------------------------------------------


def test_the_changed_document_reaches_the_next_revision(tmp_path):
    """The change is made to the document, so the document has to travel.

    Measured on the sixth real run: the feedback agent named
    `n_fillet_cutter_0.radius_mm`, the revision agent wrote it into revision
    one's document, and revision two was built from the template parameters
    again - the original radii. The loop would then have compared two runs of
    the same geometry and recorded the difference as the effect of a change it
    had thrown away.
    """
    edited = {"nodes": [{"id": "n_fillet_cutter_0", "op": "fillet_sketch",
                         "params": {"radius_mm": 0.85}}]}

    def revise(findings, space=None):
        return {"applied": [f["id"] for f in findings], "skipped": [],
                "params": {"rim_mm": 28.0}, "document": edited}

    result = _loop(tmp_path, [1482.0, 1400.0], [-0.05], revise=revise).run(2)
    second = Path(result.revisions[1].workspace_root) / "document.json"
    assert second.is_file()
    assert json.loads(second.read_text(encoding="utf-8")) == edited
    # And the first revision, which carried the template's document, is not
    # overwritten by it.
    first = Path(result.revisions[0].workspace_root) / "document.json"
    assert not first.is_file()


def test_a_revision_that_changed_nothing_stops_the_loop(tmp_path):
    """Re-running the same design is a solve spent to learn nothing."""
    loop = _loop(
        tmp_path, [1482.0, 1482.0], [-0.05],
        revise=lambda findings, space=None: {
            "applied": [], "skipped": [], "params": {}},
    )
    result = loop.run(4)
    assert len(result.revisions) == 1
    assert any("applied no change" in note for note in result.limits)


def test_one_revision_is_allowed_but_says_it_tested_nothing(tmp_path):
    result = _loop(tmp_path, [1482.0], [-0.05]).run(1)
    assert len(result.revisions) == 1
    assert any("one revision tests nothing" in note for note in result.limits)


def test_a_loop_with_no_revisions_is_refused(tmp_path):
    with pytest.raises(ValueError):
        _loop(tmp_path, [1482.0], [-0.05]).run(0)


# --- what it leaves behind -----------------------------------------------


def test_the_master_is_untouched_after_a_full_loop(tmp_path):
    master = _master(tmp_path)
    before = workspace.sha256_file(master / "param_templates.py")
    _loop(tmp_path, [1482.0, 1400.0, 1320.0], [-0.05, -0.05]).run(3)
    assert workspace.sha256_file(master / "param_templates.py") == before


def test_the_knowledge_base_survives_the_loop_as_a_readable_file(tmp_path):
    _loop(tmp_path, [1482.0, 1400.0], [-0.05]).run(2)
    path = tmp_path / "knowledge.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "structural_knowledge_v1"
    # The seed rules are kept alongside whatever the loop learned, so a rule
    # that has not been tested yet is still there to be tested.
    assert any(entry["status"] == "seed" for entry in payload["entries"])


def test_a_second_lineage_keeps_what_the_first_one_learned(tmp_path):
    """A rule about bore hoop stress is not a fact about D27."""
    _loop(tmp_path, [1482.0, 1400.0], [-0.05]).run(2)
    first = knowledge.KnowledgeBase.load(tmp_path / "knowledge.json")
    count = len(first.entries)

    _loop(tmp_path, [900.0, 850.0], [-0.05]).run(2)
    second = knowledge.KnowledgeBase.load(tmp_path / "knowledge.json")
    assert len(second.entries) >= count


def test_the_loop_reports_itself_without_a_cad_kernel(tmp_path):
    result = _loop(tmp_path, [1482.0, 1400.0], [-0.05]).run(2)
    payload = result.to_dict()
    assert payload["schema_version"] == "structural_iteration_v1"
    assert len(payload["revisions"]) == 2
    lines = iterate.report_lines(result)
    assert any("rev-000001" in line for line in lines)


def test_why_a_revision_failed_is_in_the_report_not_only_the_json(tmp_path):
    """The report is the copy a person reads, and it was the one without the reason.

    Measured: a revision produced no result because the OCAF save could not
    write - the machine's system drive was full - and the printed report said
    only "produced no result". The exception naming the cause was in
    `loop_result.json` under the revision's own `limits`, one key away from
    where anyone was looking.
    """
    system = _System([1482.0])

    def refuse(bundle, space):
        raise RuntimeError("SaveAs failed with status PCDM_SS_WriteFailure")

    result = iterate.Loop(
        master_dir=_master(tmp_path),
        root=tmp_path / "revisions",
        lineage="D27",
        params={"rim_mm": 30.0},
        generate=system.generate,
        solve=refuse,
        diagnose=_diagnose_factory([-0.05]),
        revise=_revise_ok,
        knowledge_path=tmp_path / "knowledge.json",
    ).run(2)

    assert result.revisions[0].limits, "the revision recorded no reason"
    blob = "\n".join(iterate.report_lines(result))
    assert "PCDM_SS_WriteFailure" in blob
    assert "RuntimeError" in blob
