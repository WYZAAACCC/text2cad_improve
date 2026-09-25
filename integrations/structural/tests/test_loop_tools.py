"""The two things the loop keeps between revisions: rules, and a master.

The knowledge base is tested on what it does with evidence rather than on what
it stores - a rule that has been right twice is not the same object as a rule
that has been right three times, and the difference has to be the thing the
code does, not a field someone remembers to update.

The workspace is tested on its guard. The parametric templates it copies have
already drifted twice under this repository - the live `param_templates.py` and
the dataset's snapshot disagree about `kind_hint`, and the stored D27 document
matches neither - which is exactly the failure the guard exists to catch.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from seekflow_structural.tools import (
    document as document_tools,
    face_join,
    knowledge,
    loop_wiring,
    workspace,
)


# --- the knowledge base --------------------------------------------------


def test_a_new_base_starts_from_the_seed_rules_marked_as_hypotheses():
    """A rule that arrived trusted could never be found out."""
    base = knowledge.KnowledgeBase.load(Path("does-not-exist.json"))
    assert base.entries
    assert all(entry.status == "seed" for entry in base.entries)
    assert any(entry.mechanism == "hoop_driven" for entry in base.entries)


def test_a_rule_that_was_right_three_times_becomes_trusted():
    base = knowledge.KnowledgeBase()
    base.upsert(knowledge.KnowledgeEntry(
        id="r", mechanism="hoop_driven", parameter="rim_half_thickness_mm",
        direction="decrease", expected_direction="decrease",
    ))
    for index in range(3):
        base.record("r", knowledge.Observation(
            revision=f"rev-{index}", metric="max_von_mises_mpa",
            predicted_relative_change=-0.05, measured_relative_change=-0.04,
            outcome="confirmed",
        ))
    assert base.get("r").status == "trusted"
    assert base.get("r").confirmations == 3


def test_a_rule_that_was_wrong_twice_is_retired_and_stops_being_offered():
    base = knowledge.KnowledgeBase()
    base.upsert(knowledge.KnowledgeEntry(
        id="r", mechanism="hoop_driven", parameter="rim_half_thickness_mm",
        direction="decrease", expected_direction="decrease",
    ))
    for index in range(2):
        base.record("r", knowledge.Observation(
            revision=f"rev-{index}", metric="max_von_mises_mpa",
            predicted_relative_change=-0.05, measured_relative_change=0.03,
            outcome="refuted",
        ))
    assert base.get("r").status == "refuted"
    assert base.for_mechanism("hoop_driven") == []


def test_a_trusted_rule_that_then_fails_is_demoted_not_kept():
    """A trusted rule failing means it was narrower than it looked."""
    base = knowledge.KnowledgeBase()
    base.upsert(knowledge.KnowledgeEntry(
        id="r", mechanism="hoop_driven", parameter="rim_half_thickness_mm",
        direction="decrease", expected_direction="decrease",
    ))
    for index in range(3):
        base.record("r", knowledge.Observation(
            revision=f"rev-{index}", metric="m",
            predicted_relative_change=-0.05, measured_relative_change=-0.04,
            outcome="confirmed",
        ))
    assert base.get("r").status == "trusted"
    base.record("r", knowledge.Observation(
        revision="rev-9", metric="m", predicted_relative_change=-0.05,
        measured_relative_change=0.02, outcome="refuted",
    ))
    assert base.get("r").status == "candidate"


def test_the_same_rule_proposed_twice_is_one_rule_with_two_tests():
    base = knowledge.KnowledgeBase()
    first = base.upsert(knowledge.KnowledgeEntry(
        id="r", mechanism="hoop_driven", parameter="rim_half_thickness_mm",
        direction="decrease",
    ))
    again = base.upsert(knowledge.KnowledgeEntry(
        id="r", mechanism="hoop_driven", parameter="rim_half_thickness_mm",
        direction="decrease", note="proposed by a later revision",
    ))
    assert again is first
    assert len(base.entries) == 1


def test_an_unknown_mechanism_is_offered_nothing_rather_than_everything():
    base = knowledge.KnowledgeBase.load(Path("nope.json"))
    assert base.for_mechanism("no_such_mechanism") == []


def test_the_two_mechanisms_whose_fix_is_not_a_design_change_say_so():
    """A peak on a loaded face is fixed by the model, not the geometry."""
    base = knowledge.KnowledgeBase.load(Path("nope.json"))
    for mechanism in ("load_application", "idealisation_edge"):
        entry = base.for_mechanism(mechanism)[0]
        assert not entry.is_design_change
        assert "not with the part" in entry.note or "moves nothing" in entry.note


# --- scoring a prediction ------------------------------------------------


def test_a_prediction_that_matched_in_direction_and_size_is_confirmed():
    observation = knowledge.score_prediction(-0.05, -0.048)
    assert observation.outcome == "confirmed"


def test_a_prediction_that_moved_the_other_way_is_refuted_however_small():
    """The direction decides, so a small contrary move is still a refutation.

    Small but outside the noise floor: a move of four parts in a thousand is
    below what a re-mesh does on its own and is read as `unmoved` instead, so
    the contrary move here has to be one the run can actually stand behind.
    """
    assert knowledge.score_prediction(-0.05, 0.02).outcome == "refuted"


def test_a_move_inside_the_mesh_noise_tests_nothing():
    """Calling this a confirmation would be reading a coincidence."""
    observation = knowledge.score_prediction(-0.05, -0.001)
    assert observation.outcome == "unmoved"
    assert "does not say whether" in observation.note


def test_the_right_direction_with_the_wrong_constant_is_partial_not_confirmed():
    """The mechanism is what the next change depends on; the constant is fixable."""
    observation = knowledge.score_prediction(-0.01, -0.40)
    assert observation.outcome == "partial"
    assert "the mechanism held" in observation.note


def test_a_metric_the_run_never_reported_is_unmeasurable_not_a_pass():
    assert knowledge.score_prediction(-0.05, None).outcome == "unmeasurable"


def test_a_change_that_fixed_one_number_by_breaking_another_says_so():
    """A rule that lowers the peak by raising the rim stress is not working."""
    before = {"max_von_mises_mpa": 1482.0, "min_safety_factor": 0.674}
    after = {"max_von_mises_mpa": 1400.0, "min_safety_factor": 0.660}
    found = knowledge.side_effects("max_von_mises_mpa", before, after)
    assert any("min_safety_factor" in entry for entry in found)


def test_a_safety_factor_is_read_in_the_opposite_direction_from_a_stress():
    """Lower is worse for one and better for the other."""
    before = {"max_von_mises_mpa": 1482.0, "min_safety_factor": 0.674}
    after = {"max_von_mises_mpa": 1400.0, "min_safety_factor": 0.700}
    assert knowledge.side_effects("max_von_mises_mpa", before, after) == []


def test_the_base_round_trips_through_a_file(tmp_path):
    path = tmp_path / "k.json"
    base = knowledge.KnowledgeBase.load(path)
    base.save(path)
    again = knowledge.KnowledgeBase.load(path)
    assert len(again.entries) == len(base.entries)
    assert again.summary()["by_status"] == base.summary()["by_status"]


# --- the workspace and its guard -----------------------------------------


def _master(tmp_path: Path) -> Path:
    master = tmp_path / "master"
    master.mkdir()
    (master / "param_templates.py").write_text("def build(p):\n    return p\n",
                                               encoding="utf-8")
    (master / "design_families.py").write_text("FAMILIES = {}\n", encoding="utf-8")
    return master


def test_a_workspace_copies_the_master_and_leaves_it_alone(tmp_path):
    master = _master(tmp_path)
    before = {
        path.name: workspace.sha256_file(path) for path in master.glob("*.py")
    }
    space = workspace.Workspace.create(
        master_dir=master, root=tmp_path / "rev-000001",
        lineage="D27", revision="rev-000001",
        params={"od_mm": 600, "rim_half_thickness_mm": 15.0},
    )
    space.verify_master_untouched()
    after = {
        path.name: workspace.sha256_file(path) for path in master.glob("*.py")
    }
    assert before == after
    assert (space.scripts / "param_templates.py").is_file()


def test_the_design_is_readable_without_running_anything(tmp_path):
    """A person opening the revision directory should see the design."""
    master = _master(tmp_path)
    space = workspace.Workspace.create(
        master_dir=master, root=tmp_path / "rev-000001",
        lineage="D27", revision="rev-000001", params={"od_mm": 600},
    )
    assert json.loads(space.params_path.read_text(encoding="utf-8")) == {"od_mm": 600}
    assert "PARAMS = {" in space.generate.read_text(encoding="utf-8")


def test_changing_the_design_changes_the_copy_and_not_the_master(tmp_path):
    master = _master(tmp_path)
    master_hash = workspace.sha256_file(master / "param_templates.py")
    space = workspace.Workspace.create(
        master_dir=master, root=tmp_path / "rev-000002", lineage="D27",
        revision="rev-000002", params={"rim_half_thickness_mm": 15.0},
    )
    space.set("rim_half_thickness_mm", 13.0)
    assert space.params()["rim_half_thickness_mm"] == 13.0
    assert workspace.sha256_file(master / "param_templates.py") == master_hash


def test_a_master_edited_underneath_a_workspace_is_caught(tmp_path):
    """The failure this guard exists for, and it has already happened here.

    The live `param_templates.py` and the dataset's snapshot disagree about
    `kind_hint`, and the stored D27 document matches neither - so the thing
    every dataset entry is described by has already changed once without
    anything noticing.
    """
    master = _master(tmp_path)
    space = workspace.Workspace.create(
        master_dir=master, root=tmp_path / "rev-000001", lineage="D27",
        revision="rev-000001", params={},
    )
    (master / "param_templates.py").write_text(
        "def build(p):\n    return {'changed': True}\n", encoding="utf-8"
    )
    with pytest.raises(workspace.MasterChanged) as excinfo:
        space.verify_master_untouched()
    assert "param_templates.py" in str(excinfo.value)


def test_a_master_deleted_from_under_a_workspace_is_caught(tmp_path):
    master = _master(tmp_path)
    space = workspace.Workspace.create(
        master_dir=master, root=tmp_path / "rev-000001", lineage="D27",
        revision="rev-000001", params={},
    )
    (master / "param_templates.py").unlink()
    with pytest.raises(workspace.MasterChanged) as excinfo:
        space.verify_master_untouched()
    assert "gone from" in str(excinfo.value)


def test_a_copy_that_drifted_before_being_modified_is_caught(tmp_path):
    """A change has to be a change from the master's text, not from a drift."""
    master = _master(tmp_path)
    space = workspace.Workspace.create(
        master_dir=master, root=tmp_path / "rev-000001", lineage="D27",
        revision="rev-000001", params={},
    )
    (space.scripts / "param_templates.py").write_text("drifted\n", encoding="utf-8")
    with pytest.raises(workspace.MasterChanged) as excinfo:
        space.verify_copy_is_master()
    assert space.changed_files() == ["param_templates.py"]
    assert "restore the copy" in str(excinfo.value)


def test_a_workspace_reopens_from_its_manifest_with_its_hashes(tmp_path):
    master = _master(tmp_path)
    root = tmp_path / "rev-000001"
    workspace.Workspace.create(
        master_dir=master, root=root, lineage="D27", revision="rev-000001",
        params={"od_mm": 600},
    )
    again = workspace.Workspace.open(root)
    assert again.lineage == "D27"
    assert again.params()["od_mm"] == 600
    again.verify_master_untouched()


def test_a_workspace_inside_the_master_tree_is_refused(tmp_path):
    """The one arrangement the isolation exists to prevent."""
    master = _master(tmp_path)
    with pytest.raises(ValueError) as excinfo:
        workspace.Workspace.create(
            master_dir=master, root=master / "revisions" / "rev-000001",
            lineage="D27", revision="rev-000001", params={},
        )
    assert "read-only to this loop" in str(excinfo.value)
    assert not (master / "revisions").exists()


def test_a_master_directory_with_nothing_recognisable_is_refused(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError) as excinfo:
        workspace.Workspace.create(
            master_dir=empty, root=tmp_path / "rev", lineage="D27",
            revision="rev-000001", params={},
        )
    assert "none of the master templates" in str(excinfo.value)


# --- against the real master ---------------------------------------------


def _real_master() -> Path | None:
    from conftest import REPO_ROOT

    candidate = (
        REPO_ROOT / "_param_experiment" / "turbine_disc_dataset_D01-D32"
        / "scripts"
    )
    return candidate if (candidate / "param_templates.py").is_file() else None


# --- joining a peak to a face --------------------------------------------


def _face(index, area, bbox):
    return {"index": index, "area_mm2": area, "bbox_mm": bbox,
            "surface_type": "plane"}


def test_the_box_narrows_and_the_biggest_face_is_listed_first():
    """A point where several faces meet returns them largest first.

    The box is a superset by construction, so the order is a convenience - but
    it is the convenience that puts the face being asked about at the top
    rather than one of the fillets around it.
    """
    rows = [
        _face(1, 10.0, [0, 0, 0, 100, 100, 100]),
        _face(2, 500.0, [90, 90, 90, 110, 110, 110]),
        _face(3, 90.0, [0, 0, 0, 10, 10, 10]),
    ]
    out = face_join.locate((100.0, 100.0, 100.0), rows)
    assert out["searched_face_count"] == 3
    assert out["matching_face_count"] == 2
    assert [face["index"] for face in out["faces"]] == [2, 1]


def test_a_point_in_a_void_is_reported_rather_than_returning_nothing_quietly():
    """Empty and silent reads as "no answer"; empty and explained does not."""
    rows = [_face(1, 10.0, [0, 0, 0, 1, 1, 1])]
    out = face_join.locate((500.0, 500.0, 500.0), rows)
    assert out["faces"] == []
    assert "in a void" in out["limits"][0]


def test_a_face_with_no_box_is_not_claimed_to_contain_anything():
    """A bound nobody could check is not a bound that was satisfied."""
    rows = [{"index": 1, "area_mm2": 5.0, "bbox_mm": None}]
    out = face_join.locate((0.0, 0.0, 0.0), rows)
    assert out["matching_face_count"] == 0


def test_more_candidates_than_the_limit_are_counted_not_dropped():
    rows = [
        _face(index, float(index), [-1, -1, -1, 1, 1, 1])
        for index in range(40)
    ]
    out = face_join.locate((0.0, 0.0, 0.0), rows, limit=5)
    assert out["matching_face_count"] == 40
    assert len(out["faces"]) == 5
    assert any("only the 5 largest" in note for note in out["limits"])


def test_a_box_is_widened_by_the_tolerance_so_a_node_on_a_face_is_inside_it():
    """The mesh and the kernel are two models of one surface."""
    rows = [_face(1, 10.0, [0.0, 0.0, 0.0, 1.0, 1.0, 1.0])]
    outside = face_join.locate((1.0 + 1e-2, 0.5, 0.5), rows, tolerance_mm=0.0)
    assert outside["faces"] == []
    inside = face_join.locate((1.0 + 1e-4, 0.5, 0.5), rows, tolerance_mm=1e-3)
    assert [face["index"] for face in inside["faces"]] == [1]


# --- the CAD document, which is what a change is made to -----------------


def _doc():
    return {"nodes": [
        {"id": "n_fillet_cutter_0", "op": "fillet_sketch",
         "component": "slot_cutter",
         "params": {"radius_mm": 0.698, "at_vertex_index": [6]}},
        {"id": "n_disc_fillet_0", "op": "fillet_sketch", "component": "disc_body",
         "params": {"radius_mm": 12.0, "at_vertex_index": [1]}},
        {"id": "n_poly", "op": "add_polyline", "component": "disc_body",
         "params": {"points": [[0, 0], [1, 1], [2, 0]]}},
    ]}


def test_the_fir_tree_fillet_is_a_parameter_the_document_has():
    """The one that cost a run.

    The feedback agent asked for the fir-tree root fillet to be enlarged. The
    template's parameter dict has no such name, the harness refused the
    finding against that dict, and the agent filed it as something the
    generator could not do. The document has seven of them.
    """
    table = document_tools.editable(_doc())
    assert "n_fillet_cutter_0.radius_mm" in table
    assert table["n_fillet_cutter_0.radius_mm"]["current_value"] == 0.698
    assert table["n_fillet_cutter_0.radius_mm"]["op"] == "fillet_sketch"


def test_a_point_list_is_not_offered_as_a_scalar():
    """A profile is edited as a contour, not one number at a time."""
    assert "n_poly.points" not in document_tools.editable(_doc())


def test_a_name_resolves_only_when_the_document_has_it():
    doc = _doc()
    assert document_tools.resolve(doc, "n_disc_fillet_0.radius_mm") == (
        "n_disc_fillet_0", "radius_mm")
    assert document_tools.resolve(doc, "n_fillet_cutter_9.radius_mm") is None
    assert document_tools.resolve(doc, "radius_mm") is None
    assert document_tools.resolve(doc, "n_poly.points") is None


def test_setting_a_scalar_records_a_patch_in_the_generators_own_shape():
    doc = _doc()
    patch = document_tools.set_scalar(doc, "n_fillet_cutter_0", "radius_mm", 1.05)
    assert patch["path"] == "/nodes/n_fillet_cutter_0/params/radius_mm"
    assert patch["old_value"] == 0.698 and patch["new_value"] == 1.05
    assert doc["nodes"][0]["params"]["radius_mm"] == 1.05


def test_setting_a_parameter_the_operation_has_not_got_lists_what_it_has():
    with pytest.raises(KeyError) as excinfo:
        document_tools.set_scalar(_doc(), "n_fillet_cutter_0", "depth_mm", 1.0)
    assert "radius_mm" in str(excinfo.value)


def test_a_point_list_cannot_be_set_as_a_scalar():
    with pytest.raises(ValueError) as excinfo:
        document_tools.set_scalar(_doc(), "n_poly", "points", 1.0)
    assert "set_points" in str(excinfo.value)


# --- wiring the two agents in --------------------------------------------


def test_the_context_finds_the_case_beside_a_job_that_exists(tmp_path):
    """`JobStore` lays a job out at `<output_root>/jobs/<job_id>`.

    Reading the directory as `<output_root>/<job_id>` finds nothing on a job
    that exists, and the failure then reads as a stage that never ran.
    """
    from seekflow_structural.case.model import BundleRef, Case

    job = tmp_path / "jobs" / "D27-rev-000001"
    (job / "solve").mkdir(parents=True)
    (job / "case.json").write_text(
        Case(case_id="D27", bundle=BundleRef(path=".")).model_dump_json(),
        encoding="utf-8",
    )
    ctx = loop_wiring.context_for(job)
    assert ctx.case is not None
    assert ctx.case.case_id == "D27"
    assert ctx.path == job


def test_a_directory_with_no_case_is_refused_with_that_reason(tmp_path):
    """A run that never wrote a case did not get far enough to be diagnosed."""
    job = tmp_path / "jobs" / "D27-rev-000001"
    job.mkdir(parents=True)
    with pytest.raises(FileNotFoundError) as excinfo:
        loop_wiring.context_for(job)
    assert "holds no case.json" in str(excinfo.value)


def test_a_run_that_already_diagnosed_itself_is_not_diagnosed_again(tmp_path):
    """The diagnosis is part of the chain, so a completed run has one.

    Measured on the first end-to-end run: the feedback stage ran as the last
    stage of the chain and again from the loop, the second call produced a
    different set of findings, it wrote them over the first, and the revision
    agent acted on a diagnosis the run had not made - at the price of two
    rounds of the model. `feedback_filed` appears twice in that run's event
    log, which is how it was found.
    """
    from seekflow_structural.case.model import BundleRef, Case

    job = tmp_path / "jobs" / "D27-rev-000001"
    (job / "solve").mkdir(parents=True)
    (job / "case.json").write_text(
        Case(case_id="D27", bundle=BundleRef(path=".")).model_dump_json(),
        encoding="utf-8",
    )
    existing = [{"id": "F1", "mechanism": "hoop_driven",
                 "evidence": [{"quantity": "s_hoop", "value": 1.0,
                               "source": "node:1"}]}]
    (job / "feedback.json").write_text(
        json.dumps({"findings": existing}), encoding="utf-8"
    )

    # No key and no reachable model: if this tried to run the agent it would
    # fail, so returning the findings at all proves it read them.
    diagnose = loop_wiring.make_diagnose(api_key_file=tmp_path / "absent.key")
    found = diagnose({}, {}, None, job)
    assert found == existing


def test_the_feedback_adapter_defaults_to_the_measured_flash_budget():
    import inspect

    from seekflow_structural.agents import feedback

    assert inspect.signature(loop_wiring.make_diagnose).parameters[
        "max_calls"
    ].default == 32
    assert inspect.signature(feedback.feedback).parameters[
        "max_calls"
    ].default == 32


def test_the_two_adapters_have_the_signatures_the_loop_calls(tmp_path):
    """The loop calls these positionally; a mismatch is a TypeError mid-run."""
    import inspect

    diagnose = loop_wiring.make_diagnose()
    revise = loop_wiring.make_revise(
        base=knowledge.KnowledgeBase.load(tmp_path / "none.json")
    )
    assert list(inspect.signature(diagnose).parameters) == [
        "metrics", "verdicts", "space", "job_dir",
    ]
    assert list(inspect.signature(revise).parameters) == ["findings", "space"]


@pytest.mark.skipif(_real_master() is None, reason="the dataset snapshot is absent")
def test_the_real_master_copies_and_holds_still(tmp_path):
    master = _real_master()
    assert master is not None
    before = {
        path.name: workspace.sha256_file(path) for path in master.glob("*.py")
    }
    space = workspace.Workspace.create(
        master_dir=master, root=tmp_path / "rev-000001", lineage="D27",
        revision="rev-000001", params={"od_mm": 600, "bore_mm": 120},
    )
    space.verify_copy_is_master()
    space.verify_master_untouched()
    after = {
        path.name: workspace.sha256_file(path) for path in master.glob("*.py")
    }
    assert before == after
    assert "param_templates.py" in space.masters


@pytest.mark.skipif(_real_master() is None, reason="the dataset snapshot is absent")
def test_a_full_change_cycle_leaves_every_real_master_file_byte_identical(tmp_path):
    """The whole point of the copy, checked against the files that exist.

    A revision changes the design and rewrites one of its template copies.
    Afterwards the master is compared file by file, including the parts of it
    the loop never reads.
    """
    master = _real_master()
    assert master is not None
    before = {
        path.name: workspace.sha256_file(path) for path in master.rglob("*")
        if path.is_file()
    }
    space = workspace.Workspace.create(
        master_dir=master, root=tmp_path / "rev-000007", lineage="D27",
        revision="rev-000007", params={"rim_mm": 30.0, "od_mm": 600.0},
    )
    space.set("rim_mm", 28.0)
    (space.scripts / "param_templates.py").write_text(
        "# revised\n", encoding="utf-8"
    )
    space.verify_master_untouched()

    after = {
        path.name: workspace.sha256_file(path) for path in master.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert space.changed_files() == ["param_templates.py"]
    # And the change is in the copy, where it belongs.
    assert (space.scripts / "param_templates.py").read_text(
        encoding="utf-8"
    ) == "# revised\n"

def _placed_doc():
    """A document with both placements the generator produces."""
    return {"nodes": [
        {"id": "sk_d", "op": "create_2d_sketch", "params": {"plane": "XZ"}},
        {"id": "disc", "op": "add_polyline", "component": "disc_body",
         "inputs": [{"node": "sk_d"}],
         "params": {"points": [{"x_mm": 60.0, "y_mm": -38.0},
                               {"x_mm": 160.0, "y_mm": -22.8},
                               {"x_mm": 240.0, "y_mm": -15.0}]}},
        {"id": "close_d", "op": "close_profile",
         "inputs": [{"node": "disc"}], "params": {}},
        {"id": "dfil", "op": "fillet_sketch",
         "inputs": [{"node": "close_d"}],
         "params": {"radius_mm": 12.0, "at_vertex_index": [1]}},
        {"id": "sk_c", "op": "create_2d_sketch", "params": {"plane": "XY"}},
        {"id": "cut", "op": "add_polyline", "component": "slot_cutter",
         "inputs": [{"node": "sk_c"}],
         "params": {"points": [{"x_mm": 0.0, "y_mm": 6.0},
                               {"x_mm": -5.76, "y_mm": 7.56},
                               {"x_mm": -22.093, "y_mm": 1.44}]}},
        {"id": "close_c", "op": "close_profile",
         "inputs": [{"node": "cut"}], "params": {}},
        {"id": "cfil", "op": "fillet_sketch",
         "inputs": [{"node": "close_c"}],
         "params": {"radius_mm": 0.7, "at_vertex_index": [1]}},
        {"id": "ext", "op": "extrude_profile",
         "inputs": [{"node": "cfil"}], "params": {"depth_mm": 80.0}},
        {"id": "pat", "op": "circular_pattern_component",
         "inputs": [{"node": "ext"}],
         "params": {"count": 60, "radius_mm": 300.0, "axis": "Z"}},
    ]}


def test_dependency_graph_links_features_without_a_family_template():
    graph = document_tools.dependency_graph(_placed_doc())
    kinds = {edge["kind"] for edge in graph["edges"]}
    assert {"consumes", "rounds_vertex", "pattern_source"} <= kinds
    assert "disc_body" in graph["feature_groups"]
    assert "slot_cutter" in graph["feature_groups"]


def test_a_meridional_profile_reports_its_points_as_radius_and_axial():
    """The disc sketch is XZ, so its points are (r, z) already."""
    out = document_tools.world_positions(_placed_doc(), "disc")
    assert out["placement"]["kind"] == "meridional"
    assert out["vertices"][2] == {"index": 2, "r_mm": 240.0, "z_mm": -15.0}


def test_a_patterned_profile_reports_where_the_pattern_puts_it():
    """`r = pattern radius + local x`, which is the whole transform.

    Checked against what actually moved on D27 rather than assumed: enlarging
    one cutter fillet moved 1,064 faces running from r = 283.7 to r = 295.4,
    and this rule puts that fillet's vertices at 284.28, 289.11 and 294.24.
    """
    out = document_tools.world_positions(_placed_doc(), "cut")
    assert out["placement"]["kind"] == "patterned_about_axis"
    assert out["placement"]["radius_mm"] == 300.0
    radii = {row["index"]: row["r_mm"] for row in out["vertices"]}
    assert radii[0] == pytest.approx(math.hypot(300.0, 6.0), abs=0.01)
    assert radii[2] == pytest.approx(300.0 - 22.093, abs=0.05)


def test_a_fillet_is_reported_where_the_vertices_it_rounds_are():
    """A radius with no place attached is what let a rim fillet be proposed
    for a peak 70 mm away on the web."""
    table = document_tools.editable(_placed_doc())
    assert table["dfil.radius_mm"]["at_r_mm"] == 160.0
    # hypot(300 - 5.76, 7.56), which is where the pattern puts that vertex.
    assert table["cfil.radius_mm"]["at_r_mm"] == pytest.approx(294.34, abs=0.05)


def test_a_placement_this_cannot_read_yields_no_position_rather_than_a_guess():
    """A guessed position would be acted on, which is worse than none."""
    doc = {"nodes": [
        {"id": "sk", "op": "create_2d_sketch", "params": {"plane": "XY"}},
        {"id": "p", "op": "add_polyline", "inputs": [{"node": "sk"}],
         "params": {"points": [{"x_mm": 1.0, "y_mm": 2.0}]}},
    ]}
    out = document_tools.world_positions(doc, "p")
    assert out["placed"] is False
    assert out["placement"]["kind"] == "unknown"
    assert "at_r_mm" not in document_tools.editable(doc)["p.points[0].x_mm"]


def test_a_profile_vertex_is_settable_and_keeps_the_shape_it_was_written_in():
    """The generator writes `{"x_mm": ..}`; rewriting it as a pair would leave
    a profile the reader sees no vertices in."""
    doc = _placed_doc()
    patch = document_tools.set_scalar(doc, "disc", "points[1].y_mm", -20.0)
    assert patch["path"] == "/nodes/disc/params/points/1"
    assert doc["nodes"][1]["params"]["points"][1] == {"x_mm": 160.0, "y_mm": -20.0}


def test_a_vertex_name_resolves_as_a_parameter_does():
    doc = _placed_doc()
    assert document_tools.resolve(doc, "disc.points[1].y_mm") == (
        "disc", "points[1].y_mm")
    assert document_tools.resolve(doc, "disc.points[9].y_mm") is None


def test_the_web_is_addressable_which_is_where_the_peak_was():
    """The measurement that started this.

    On D27 the peak sits at r = 208.09, z = 18.11, which is on the disc
    profile's 160-to-240 edge: interpolating half-thickness there gives 18.12.
    Every fillet in the document is at r = 160, r = 240 or r >= 277.9, so none
    of them is near it - and before vertices were settable there was no handle
    on that edge at all.
    """
    doc = _placed_doc()
    table = document_tools.editable(doc)
    radii = {name: entry.get("at_r_mm") for name, entry in table.items()
             if name.endswith("radius_mm") and entry.get("at_r_mm")}
    assert radii, "the fillets should carry a position"
    assert all(abs(r - 208.09) > 5 for r in radii.values())
    # And the edge itself is editable, at both ends.
    assert "disc.points[1].y_mm" in table
    assert table["disc.points[1].y_mm"]["at_r_mm"] == 160.0
    assert table["disc.points[2].y_mm"]["at_r_mm"] == 240.0

def _hole_doc():
    """A disc with lightening holes - the D27 arrangement.

    Twenty holes of 6 mm radius on a 208 mm pitch circle, which is where the
    peak is: r = 208.087, on the edge of one of them.
    """
    points = []
    for index in range(16):
        angle = 2 * 3.141592653589793 * index / 16
        points.append({"x_mm": round(6.0 * math.cos(angle), 3),
                       "y_mm": round(6.0 * math.sin(angle), 3)})
    return {"nodes": [
        {"id": "sk_h", "op": "create_2d_sketch", "params": {"plane": "XY"}},
        {"id": "feat_holes_poly", "op": "add_polyline",
         "component": "feat_holes", "inputs": [{"node": "sk_h"}],
         "params": {"points": points}},
        {"id": "feat_holes_extrude", "op": "extrude_profile",
         "inputs": [{"node": "feat_holes_poly"}],
         "params": {"depth_mm": 800.0, "direction": "both"}},
        {"id": "n_pat_holes", "op": "circular_pattern_component",
         "inputs": [{"node": "feat_holes_extrude"}],
         "params": {"count": 20, "radius_mm": 208.0, "axis": "Z"}},
        {"id": "sk_c", "op": "create_2d_sketch", "params": {"plane": "XY"}},
        {"id": "cut", "op": "add_polyline", "component": "slot_cutter",
         "inputs": [{"node": "sk_c"}],
         "params": {"points": [{"x_mm": 0.0, "y_mm": 6.0},
                               {"x_mm": -15.721, "y_mm": 4.128}]}},
        {"id": "close_c", "op": "close_profile",
         "inputs": [{"node": "cut"}], "params": {}},
        {"id": "tooth", "op": "fillet_sketch",
         "inputs": [{"node": "close_c"}],
         "params": {"radius_mm": 0.698, "at_vertex_index": [1]}},
        {"id": "ext", "op": "extrude_profile",
         "inputs": [{"node": "tooth"}], "params": {"depth_mm": 80.0}},
        {"id": "pat", "op": "circular_pattern_component",
         "inputs": [{"node": "ext"}],
         "params": {"count": 60, "radius_mm": 300.0, "axis": "Z"}},
    ]}


def test_a_pattern_reports_the_radius_it_places_things_on():
    """`n_pat_holes.radius_mm` is 208 on D27 and means nothing until read as a
    radius - which is the number the peak is at."""
    table = document_tools.editable(_hole_doc())
    assert table["n_pat_holes.radius_mm"]["at_r_mm"] == 208.0
    assert table["n_pat_holes.radius_mm"]["current_value"] == 208.0


def test_asking_what_acts_at_a_radius_returns_the_hole_not_the_other_161():
    """The question an agent has is about one radius.

    Measured: given all 161 numbers, a run looked at the fillets and the disc
    profile, found both too far away, and concluded nothing could be done. The
    hole edge sits exactly on the peak and it never saw it, because nothing
    about the name `feat_holes_poly` says "at r = 208".
    """
    doc = _hole_doc()
    table = document_tools.editable(doc)
    near = document_tools.reaching(doc, 208.087)
    assert len(near) < len(table) / 3, (
        f"the filter returned {len(near)} of {len(table)}; the point of it is "
        "to be short enough to read"
    )
    # The vertex nearest the peak radius, and the pitch circle itself. The
    # outermost vertex is correctly absent: it sits at r = 214 and spans
    # 213.6 to 214, which does not reach 208.
    assert "feat_holes_poly.points[12].x_mm" in near
    assert "n_pat_holes.radius_mm" in near
    assert "feat_holes_poly.points[0].x_mm" not in near


def test_a_vertex_reaches_across_the_edges_that_meet_it_not_only_itself():
    """The span is what decides reach, and a vertex at r = 240 reaches to 160.

    The hole's vertices sit between r = 202 and r = 214, so a peak at 208 is
    inside the span of several of them even though none of them is *at* 208.
    """
    doc = _hole_doc()
    near = document_tools.reaching(doc, 208.087)
    radii = [entry["at_r_mm"] for entry in near.values()
             if "at_r_mm" in entry and entry.get("vertex_index") is not None]
    assert radii, "the vertices should be listed"
    assert any(abs(r - 208.087) > 1.0 for r in radii), (
        "some listed vertex should reach the peak without sitting on it"
    )


def test_something_far_away_is_not_returned():
    doc = _hole_doc()
    near = document_tools.reaching(doc, 208.087)
    assert "tooth.radius_mm" not in near, (
        "the fir-tree fillet is at r = 284 and cannot reach r = 208"
    )

def _feature_doc():
    return {"nodes": [
        {"id": "disc_sketch", "op": "create_2d_sketch", "component": "disc_body",
         "params": {"plane": "XZ", "origin_x_mm": 0.0, "origin_y_mm": 0.0}},
        {"id": "disc_poly", "op": "add_polyline", "component": "disc_body",
         "inputs": [{"node": "disc_sketch", "output": "sketch"}],
         "params": {"points": [
             {"x_mm": 60.0, "y_mm": -38.0},
             {"x_mm": 240.0, "y_mm": 0.0},
             {"x_mm": 60.0, "y_mm": 38.0},
         ]}},
        {"id": "disc_fillet", "op": "fillet_sketch", "component": "disc_body",
         "params": {"radius_mm": 2.0, "at_vertex_index": [1]}},
        {"id": "hole_poly", "op": "add_polyline", "component": "feat_holes",
         "params": {"points": [
             {"x_mm": -6.0, "y_mm": -6.0},
             {"x_mm": 6.0, "y_mm": -6.0},
             {"x_mm": 6.0, "y_mm": 6.0},
             {"x_mm": -6.0, "y_mm": 6.0},
         ]}},
        {"id": "slot_fillet_0", "op": "fillet_sketch",
         "component": "slot_cutter",
         "params": {"radius_mm": 0.5, "at_vertex_index": [1]}},
        {"id": "slot_fillet_1", "op": "fillet_sketch",
         "component": "slot_cutter",
         "params": {"radius_mm": 0.6, "at_vertex_index": [2]}},
        {"id": "hole_pattern", "op": "circular_pattern_component",
         "component": "__assembly__",
         "inputs": [{"node": "hole_poly", "output": "body"}],
         "params": {"count": 20, "radius_mm": 208.0,
                    "start_angle_deg": 0.0}},
    ]}


def test_the_dependency_graph_exposes_feature_level_joint_edits():
    graph = document_tools.dependency_graph(_feature_doc())
    kinds = {group["kind"] for group in graph["joint_edit_groups"]}
    assert {"mirror_vertex_pair", "fillet_family", "pattern_instances",
            "profile_contour", "feature_bundle"} <= kinds
    assert graph["feature_groups"]["slot_cutter"] == [
        "slot_fillet_0", "slot_fillet_1"
    ]


def test_joint_parameters_separates_mandatory_pairs_from_optional_families():
    document = _feature_doc()
    assert document_tools.joint_parameters(
        document, "disc_poly.points[0].x_mm", required_only=True
    ) == ["disc_poly.points[2].x_mm"]
    optional = document_tools.joint_parameters(
        document, "slot_fillet_0.radius_mm"
    )
    assert "slot_fillet_1.radius_mm" in optional
    assert "slot_fillet_0.radius_mm" not in optional

