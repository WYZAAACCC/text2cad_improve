"""Applying a finding to a revision's copy, and the three ways it is refused.

The refusals are the whole value of this stage. A change to a variable the
generator derives is written, accepted, and then silently recomputed away - so
the revision reports a change it did not make and the solve that follows tests
a design nobody asked for. A change larger than the repair kernel takes is
refused downstream, after a revision has been spent. And a finding that ends up
in neither the applied nor the skipped list is one nobody read.

Each is a refusal here rather than a warning, because a warning would still
leave the change on disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from seekflow_structural.agents import revise
from seekflow_structural.errors import StructuralError
from seekflow_structural.tools import knowledge, workspace


def _master(tmp_path: Path) -> Path:
    master = tmp_path / "master"
    master.mkdir(exist_ok=True)
    (master / "param_templates.py").write_text(
        "def build(p):\n    return p\n", encoding="utf-8"
    )
    (master / "design_families.py").write_text(
        "FAMILIES = {}\n", encoding="utf-8"
    )
    return master


def _state(tmp_path: Path, findings=None, params=None) -> revise.ReviseState:
    space = workspace.Workspace.create(
        master_dir=_master(tmp_path), root=tmp_path / "rev-000002",
        lineage="D27", revision="rev-000002",
        params=params or {"rim_mm": 30.0, "bore_mm": 120.0, "od_mm": 600.0},
    )
    return revise.ReviseState(
        workspace=space,
        findings=findings or [
            {"id": "F1", "mechanism": "hoop_driven",
             "feature": "bore",
             "change": {"parameter": "rim_half_thickness_mm",
                        "relative_change": -0.1}},
        ],
        base=knowledge.KnowledgeBase.load(tmp_path / "none.json"),
    )


class _Call:
    """Stands in for a validated Action, without the pydantic model."""

    def __init__(self, **fields):
        for name, default in (
            ("parameter", ""), ("value", None), ("script", ""),
            ("content", ""), ("applied", []), ("skipped", []),
            ("finding_id", ""), ("rationale", ""), ("questions", []),
        ):
            setattr(self, name, fields.pop(name, default))
        for name, value in fields.items():
            setattr(self, name, value)


# --- what the generator will take ----------------------------------------


def test_a_variable_the_generator_derives_is_refused_with_the_reason(tmp_path):
    """Written, accepted, then recomputed away - a change that reports success."""
    state = _state(tmp_path)
    checks = revise.check_change(
        "neck_half_width_mm", 9.0, state.workspace.params(), state.base
    )
    assert not checks[0]["ok"]
    assert "recomputed away" in checks[0]["note"]


def test_a_variable_the_generator_does_not_have_is_refused_by_name(tmp_path):
    state = _state(tmp_path)
    checks = revise.check_change(
        "web_thickness_mm", 12.0, state.workspace.params(), state.base
    )
    assert not checks[0]["ok"]
    assert "rim_mm" in checks[0]["note"]


def test_a_categorical_variable_cannot_take_a_number(tmp_path):
    state = _state(tmp_path)
    checks = revise.check_change(
        "form", 3.0, state.workspace.params(), state.base
    )
    assert not checks[0]["ok"]
    assert "named alternatives" in checks[0]["note"]


def test_a_change_the_template_calls_something_else_says_what_it_calls_it(tmp_path):
    """The plan's vocabulary and the template's are not the same words."""
    state = _state(tmp_path)
    checks = revise.check_change(
        "rim_half_thickness_mm", 27.0, state.workspace.params(), state.base
    )
    assert checks[0]["ok"]
    assert "rim_mm" in checks[0]["note"]


def test_a_change_bigger_than_one_step_is_refused_before_it_is_made(tmp_path):
    state = _state(tmp_path)
    checks = revise.check_change(
        "rim_half_thickness_mm", 20.0, state.workspace.params(), state.base
    )
    magnitude = next(item for item in checks if item["check"] == "magnitude")
    assert not magnitude["ok"]
    assert "refused downstream" in magnitude["note"]


def test_the_change_is_measured_against_the_template_variable_it_translates_to(tmp_path):
    """30 mm of rim read as `rim_mm`, not as a variable that is not there.

    Reading the current value under the planning agent's name found nothing,
    which used to mean "it will be added" - so the change skipped the size
    check, was written as a key `param_templates.build` does not read, and
    changed the design by nothing while reporting success.
    """
    state = _state(tmp_path)
    checks = revise.check_change(
        "rim_half_thickness_mm", 20.0, state.workspace.params(), state.base
    )
    magnitude = next(item for item in checks if item["check"] == "magnitude")
    assert magnitude["relative_change"] == pytest.approx(-1 / 3, rel=1e-6)
    assert "rim_mm" in magnitude["note"]


def test_a_change_within_the_budget_passes_every_check(tmp_path):
    state = _state(tmp_path)
    checks = revise.check_change(
        "rim_half_thickness_mm", 28.0, state.workspace.params(), state.base
    )
    assert all(item["ok"] for item in checks)


def test_a_parameter_not_yet_in_the_design_is_added_rather_than_refused(tmp_path):
    state = _state(tmp_path)
    checks = revise.check_change(
        "rim_arc_radius_mm", 20.0, state.workspace.params(), state.base
    )
    assert all(item["ok"] for item in checks)


# --- making the change ---------------------------------------------------


def test_setting_a_refused_parameter_leaves_the_design_alone(tmp_path):
    """A refusal has to be a refusal, or the record cannot tell it from a change."""
    state = _state(tmp_path)
    before = state.workspace.params()
    with pytest.raises(StructuralError) as excinfo:
        revise._set_parameter(
            _Call(parameter="neck_half_width_mm", value=9.0), state
        )
    assert "change_refused" in str(excinfo.value.diagnostic.code)
    assert state.workspace.params() == before


def test_setting_a_permitted_parameter_changes_only_the_copy(tmp_path):
    state = _state(tmp_path)
    master_hash = workspace.sha256_file(
        state.workspace.master_dir / "param_templates.py"
    )
    revise._set_parameter(
        _Call(parameter="rim_half_thickness_mm", value=28.0), state
    )
    # Written under the template's name, which is the one `generate.py` passes
    # to `param_templates.build`; the planning agent's name would be a key the
    # generator never reads.
    params = state.workspace.params()
    assert params["rim_mm"] == 28.0
    assert "rim_half_thickness_mm" not in params
    assert workspace.sha256_file(
        state.workspace.master_dir / "param_templates.py"
    ) == master_hash
    assert state.applied[-1]["parameter"] == "rim_mm"
    assert state.applied[-1]["asked_for_as"] == "rim_half_thickness_mm"


def test_rewriting_a_script_changes_the_copy_and_checks_the_master(tmp_path):
    state = _state(tmp_path)
    revise._write_script(
        _Call(script="param_templates.py",
              content="def build(p):\n    return {'revised': True}\n"),
        state,
    )
    assert state.workspace.changed_files() == ["param_templates.py"]
    assert state.workspace.verify_master_untouched() is None


def test_rewriting_a_script_that_is_not_in_the_workspace_is_refused(tmp_path):
    state = _state(tmp_path)
    with pytest.raises(StructuralError) as excinfo:
        revise._write_script(
            _Call(script="not_a_template.py", content="x = 1\n"), state
        )
    assert "unknown_script" in str(excinfo.value.diagnostic.code)


# --- accounting for every finding ----------------------------------------


def test_a_finding_in_neither_list_is_refused(tmp_path):
    """A finding dropped without a reason is one nobody read."""
    state = _state(tmp_path)
    with pytest.raises(StructuralError) as excinfo:
        revise._submit_revision(_Call(applied=[], skipped=[]), state)
    assert "nothing_reported" in str(excinfo.value.diagnostic.code)


def test_reporting_a_finding_that_does_not_exist_is_refused(tmp_path):
    state = _state(tmp_path)
    with pytest.raises(StructuralError) as excinfo:
        revise._submit_revision(_Call(applied=["F99"], skipped=[]), state)
    assert "unknown_finding" in str(excinfo.value.diagnostic.code)


def test_a_finding_reported_as_applied_with_no_change_behind_it_is_refused(tmp_path):
    """The second real run, where the loop believed a report of nothing.

    The agent submitted `applied: ["F1"]`, no parameter had been set and no
    script replaced, and the loop built the next revision from an unchanged
    design - then generated, meshed and solved it, and would have recorded the
    result as a test of a prediction nothing had been done to test.
    """
    state = _state(tmp_path)
    with pytest.raises(StructuralError) as excinfo:
        revise._submit_revision(_Call(applied=["F1"], skipped=[]), state)
    assert "applied_without_a_change" in str(excinfo.value.diagnostic.code)
    assert "F1" in str(excinfo.value)


def test_a_change_records_the_finding_it_was_made_for(tmp_path):
    state = _state(tmp_path)
    revise._set_parameter(
        _Call(parameter="rim_half_thickness_mm", value=28.0, finding_id="F1"),
        state,
    )
    assert state.applied[-1]["finding"] == "F1"
    revise._submit_revision(_Call(applied=["F1"], skipped=[]), state)
    assert state.submitted["applied"] == ["F1"]


def test_a_change_made_for_one_finding_does_not_back_another(tmp_path):
    """The check is which finding each change was for, not how many there are."""
    state = _state(tmp_path)
    revise._set_parameter(
        _Call(parameter="rim_half_thickness_mm", value=28.0, finding_id="F1"),
        state,
    )
    with pytest.raises(StructuralError) as excinfo:
        revise._submit_revision(_Call(applied=["F1", "F2"], skipped=[]), state)
    assert "F2" in str(excinfo.value)
    assert "F1" not in str(excinfo.value).split(":")[-1]


def test_a_change_made_for_a_finding_has_to_be_the_one_it_asked_for(tmp_path):
    """A substituted variable is scored as evidence about a change nobody made.

    The prediction mechanism keeps a result attached to the reasoning that
    asked for it. An agent that quietly changes a variable it prefers has
    tested a different hypothesis, and the loop would credit the answer to the
    finding that was never acted on.
    """
    state = _state(tmp_path, findings=[
        {"id": "F1", "mechanism": "hoop_driven", "feature": "bore",
         "change": {"parameter": "bore_mm", "relative_change": 0.1}},
    ])
    revise._set_parameter(
        _Call(parameter="rim_mm", value=28.0, finding_id="F1"), state,
    )
    with pytest.raises(StructuralError) as excinfo:
        revise._submit_revision(_Call(applied=["F1"], skipped=[]), state)
    assert "applied_a_different_change" in str(excinfo.value.diagnostic.code)
    assert "bore_mm" in str(excinfo.value)


def test_the_change_the_finding_asked_for_is_accepted(tmp_path):
    state = _state(tmp_path, findings=[
        {"id": "F1", "mechanism": "hoop_driven", "feature": "rim",
         "change": {"parameter": "rim_mm", "relative_change": -0.1}},
    ])
    revise._set_parameter(
        _Call(parameter="rim_mm", value=28.0, finding_id="F1"), state,
    )
    revise._submit_revision(_Call(applied=["F1"], skipped=[]), state)
    assert state.submitted["applied"] == ["F1"]


def test_a_skip_with_a_reason_is_accepted_and_recorded(tmp_path):
    state = _state(tmp_path)
    revise._set_parameter(
        _Call(parameter="rim_half_thickness_mm", value=28.0, finding_id="F1"),
        state,
    )
    revise._submit_revision(
        _Call(
            applied=["F1"],
            skipped=[{"id": "F2",
                      "reason": "the generator derives this variable"}],
            rationale="carried out the one that can be applied",
        ),
        state,
    )
    assert state.submitted["applied"] == ["F1"]
    assert state.submitted["skipped"][0]["id"] == "F2"


# --- what it can see -----------------------------------------------------


def test_the_rules_offered_are_the_ones_the_loop_still_believes(tmp_path):
    """A refuted rule is kept so it is not proposed again, not so it is offered."""
    state = _state(tmp_path)
    retired = state.base.get("bore-hoop-rim-mass")
    assert retired is not None
    for index in range(2):
        state.base.record("bore-hoop-rim-mass", knowledge.Observation(
            revision=f"rev-{index}", metric="max_von_mises_mpa",
            predicted_relative_change=-0.05, measured_relative_change=0.03,
            outcome="refuted",
        ))
    assert retired.status == "refuted"

    offered = revise._get_rules(_Call(), state)["result"]["rules_by_mechanism"]
    ids = [entry["id"] for entry in offered["hoop_driven"]]
    assert "bore-hoop-rim-mass" not in ids
    # The other hoop rule is untouched, so the mechanism is still offered
    # something - an empty list would mean hoop problems had no rules at all.
    assert "bore-hoop-bore-radius" in ids


def test_two_findings_with_the_same_mechanism_ask_for_the_rules_once(tmp_path):
    state = _state(tmp_path, findings=[
        {"id": "F1", "mechanism": "hoop_driven"},
        {"id": "F2", "mechanism": "hoop_driven"},
    ])
    offered = revise._get_rules(_Call(), state)["result"]["rules_by_mechanism"]
    assert list(offered) == ["hoop_driven"]


def test_a_failed_rule_is_reported_as_a_warning_rather_than_hidden(tmp_path):
    """Kept out of the advice, and not out of sight.

    A retired rule was dropped from the reply altogether, so the agent could
    not tell a change it was about to make from one that had already been made
    and had not worked. The record existed and nothing could read it.
    """
    state = _state(tmp_path)
    for index in range(2):
        state.base.record("bore-hoop-rim-mass", knowledge.Observation(
            revision=f"rev-{index}", metric="max_von_mises_mpa",
            predicted_relative_change=-0.05, measured_relative_change=0.03,
            outcome="refuted", note="the peak rose",
        ))
    payload = revise._get_rules(_Call(), state)["result"]

    assert "bore-hoop-rim-mass" not in [
        entry["id"] for entry in payload["rules_by_mechanism"]["hoop_driven"]
    ]
    retired = payload["retired_by_mechanism"]["hoop_driven"]
    assert [entry["id"] for entry in retired] == ["bore-hoop-rim-mass"]
    assert retired[0]["status"] == "refuted"
    assert retired[0]["refutations"] == 2
    assert [o["outcome"] for o in retired[0]["observations"]] == [
        "refuted", "refuted"
    ]
    assert "not a new idea" in payload["note"]


def test_mechanisms_with_nothing_retired_get_no_retired_bucket(tmp_path):
    """An empty list would read as "everything here failed"."""
    state = _state(tmp_path)
    payload = revise._get_rules(_Call(), state)["result"]
    assert payload["retired_by_mechanism"] == {}


def test_a_mechanism_is_named_in_the_retired_bucket_only_when_one_failed(tmp_path):
    state = _state(tmp_path, findings=[
        {"id": "F1", "mechanism": "hoop_driven"},
        {"id": "F2", "mechanism": "stress_concentration"},
    ])
    state.base.record("concentration-root-fillet", knowledge.Observation(
        revision="rev-1", metric="max_von_mises_mpa",
        predicted_relative_change=-0.05, measured_relative_change=0.2,
        outcome="refuted",
    ))
    state.base.record("concentration-root-fillet", knowledge.Observation(
        revision="rev-2", metric="max_von_mises_mpa",
        predicted_relative_change=-0.05, measured_relative_change=0.2,
        outcome="refuted",
    ))
    payload = revise._get_rules(_Call(), state)["result"]
    assert list(payload["retired_by_mechanism"]) == ["stress_concentration"]


def test_the_design_is_readable_without_running_the_generator(tmp_path):
    state = _state(tmp_path)
    payload = revise._read_design(_Call(), state)["result"]
    assert payload["template_params"]["od_mm"] == 600.0
    assert "param_templates.py" in payload["scripts"]
    assert payload["changed_from_master"] == []


def test_reading_a_script_that_is_not_there_lists_what_is(tmp_path):
    state = _state(tmp_path)
    with pytest.raises(StructuralError) as excinfo:
        revise._read_script(_Call(script="nope.py"), state)
    assert "param_templates.py" in str(excinfo.value)


# --- the design a revision is built from ---------------------------------
#
# Once a revision has a document, the document is the design and the template
# parameters are not: the driver reads `document.json` and never calls
# `param_templates.build`. So a change named after a template parameter is
# written into `params.json`, which nothing opens, and the next revision is
# built from the geometry before it - while every guard above reports that a
# change was made. The prediction is scored against an unchanged design, and
# the result goes into the knowledge base as evidence about it.
#
# Measured on D27: all 18 of the variables offered as free are absent from the
# document, so this is the whole of that vocabulary rather than a corner of it.


def _document() -> dict:
    """A document with the three things a change can be aimed at."""
    return {
        "schema_version": "text_to_cad_v1",
        "document_id": "d27",
        "part_name": "turbine_disc",
        "units": "mm",
        "components": [{"id": "disc"}],
        "nodes": [
            {"id": "disc_poly", "op": "add_polyline", "component": "disc",
             "phase": "profile",
             "params": {"points": [
                 {"x_mm": 160.0, "y_mm": 0.0},
                 {"x_mm": 240.0, "y_mm": 38.0},
                 {"x_mm": 160.0, "y_mm": 38.0},
             ]}},
            {"id": "n_fillet_0", "op": "fillet_sketch", "component": "disc",
             "phase": "fillet",
             "params": {"radius_mm": 0.5, "at_vertex_index": [1]}},
        ],
        "constraints": {}, "safety": {}, "llm_validation_hints": {},
    }


def _document_state(tmp_path: Path, findings=None) -> revise.ReviseState:
    space = workspace.Workspace.create(
        master_dir=_master(tmp_path), root=tmp_path / "rev-000002",
        lineage="D27", revision="rev-000002",
        params={"rim_mm": 30.0},
        document=_document(),
    )
    return revise.ReviseState(
        workspace=space,
        findings=findings or [
            {"id": "F1", "mechanism": "concentration",
             "feature": "lightening hole",
             "change": {"parameter": "disc_poly.points[1].y_mm",
                        "relative_change": 0.1}},
        ],
        base=knowledge.KnowledgeBase.load(tmp_path / "none.json"),
    )


def test_a_template_parameter_cannot_be_changed_once_a_document_exists(tmp_path):
    """The name is real and the file it reaches is not read."""
    state = _document_state(tmp_path)
    checks = revise.check_change(
        "rim_half_thickness_mm", 28.0, state.workspace.params(), state.base,
        document=state.workspace.document(),
    )
    parameter = next(item for item in checks if item["check"] == "parameter")
    assert not parameter["ok"]
    assert "params.json" in parameter["note"]
    assert "read_design" in parameter["note"]


def test_setting_a_template_parameter_is_refused_while_a_document_exists(tmp_path):
    state = _document_state(tmp_path)
    with pytest.raises(StructuralError) as excinfo:
        revise._set_parameter(
            _Call(parameter="rim_half_thickness_mm", value=28.0,
                  finding_id="F1"),
            state,
        )
    assert "change_refused" in str(excinfo.value.diagnostic.code)
    assert state.workspace.document_edits() == []
    assert state.workspace.params() == {"rim_mm": 30.0}


def test_the_template_path_still_works_before_a_document_exists(tmp_path):
    """The refusal is about which file the generator reads, not the name."""
    state = _state(tmp_path)
    revise._set_parameter(
        _Call(parameter="rim_mm", value=28.0, finding_id="F1"), state,
    )
    assert state.workspace.params()["rim_mm"] == 28.0


def test_replacing_a_script_is_refused_while_a_document_exists(tmp_path):
    """The template copy is not called for a revision built from a document."""
    state = _document_state(tmp_path)
    with pytest.raises(StructuralError) as excinfo:
        revise._write_script(
            _Call(script="param_templates.py", content="def build(p): ...",
                  finding_id="F1"),
            state,
        )
    assert "script_does_not_reach_the_design" in str(
        excinfo.value.diagnostic.code
    )
    assert state.workspace.changed_files() == []


def test_changing_a_document_parameter_lands_and_is_recorded(tmp_path):
    state = _document_state(tmp_path)
    revise._set_parameter(
        _Call(parameter="disc_poly.points[1].y_mm", value=41.0,
              finding_id="F1"),
        state,
    )
    revise._submit_revision(_Call(applied=["F1"], skipped=[]), state)
    assert state.workspace.document()["nodes"][0]["params"]["points"][1] == {
        "x_mm": 240.0, "y_mm": 41.0,
    }
    edits = state.workspace.document_edits()
    assert [edit["path"] for edit in edits] == [
        "/nodes/disc_poly/params/points/1/y_mm"
    ]
    assert edits[0]["old_value"] == 38.0
    assert edits[0]["new_value"] == 41.0


def test_applying_no_change_to_a_document_does_not_count_as_one(tmp_path):
    """The guard the metrics cannot supply: the design has to have moved.

    This is the case that used to pass. A finding was reported as applied, a
    change was recorded against `params.json`, every check said yes, and the
    document the next revision was built from was byte-for-byte the one before
    it.
    """
    state = _document_state(tmp_path)
    state.applied.append({
        "finding": "F1", "parameter": "rim_mm", "before": 30.0, "after": 28.0,
        "patch": {"path": "/params/rim_mm", "old_value": 30.0,
                  "new_value": 28.0},
    })
    with pytest.raises(StructuralError) as excinfo:
        revise._submit_revision(_Call(applied=["F1"], skipped=[]), state)
    assert "change_did_not_reach_the_document" in str(
        excinfo.value.diagnostic.code
    )


def test_a_document_nothing_was_written_to_is_refused(tmp_path):
    """Even a change logged against a document path has to show up in the file."""
    state = _document_state(tmp_path)
    state.applied.append({
        "finding": "F1", "parameter": "disc_poly.points[1].y_mm",
        "before": 38.0, "after": 41.0,
        "patch": {"path": "/nodes/disc_poly/params/points/1/y_mm",
                  "old_value": 38.0, "new_value": 41.0},
    })
    with pytest.raises(StructuralError) as excinfo:
        revise._submit_revision(_Call(applied=["F1"], skipped=[]), state)
    assert "document_unchanged" in str(excinfo.value.diagnostic.code)


def test_a_revision_that_carries_out_nothing_is_accepted(tmp_path):
    """The feedback agent may conclude no editable parameter can help.

    Measured on the fourth loop run: the finding carried `change: null` - the
    peak had moved to the fir-tree slot flank at r=210.4, where no operation
    parameter acts - and its rationale said so. The honest revision of that
    finding is to skip it and change nothing.

    The guard that asks for a changed document has to let that through. It did
    not, so the agent had no legal move; it submitted `needs_input` instead,
    asking whether it should make a change the finding said was unjustified,
    and the run died on a question nobody could answer.
    """
    state = _document_state(tmp_path)
    revise._submit_revision(
        _Call(applied=[], skipped=[{
            "id": "F1",
            "reason": "no editable parameter acts at r=210.4; the nearest are "
                      "the lightening-hole vertices",
        }]),
        state,
    )
    assert state.submitted["applied"] == []
    assert [entry["id"] for entry in state.submitted["skipped"]] == ["F1"]
    assert state.workspace.document_edits() == []
    assert state.workspace.document() == state.workspace.document_base()


def test_reading_the_design_says_which_surface_is_the_design(tmp_path):
    state = _document_state(tmp_path)
    payload = revise._read_design(_Call(), state)["result"]
    assert payload["document"]["summary"]["node_count"] == 2
    assert "disc_poly.points[1].y_mm" in payload["document"]["editable"]
    assert "built from `document.json`" in payload["note"]


def test_a_document_diff_is_empty_until_something_is_written(tmp_path):
    state = _document_state(tmp_path)
    assert state.workspace.document_edits() == []
    document = state.workspace.document()
    document["nodes"][1]["params"]["radius_mm"] = 0.8
    state.workspace.write_document(document)
    edits = state.workspace.document_edits()
    assert [edit["path"] for edit in edits] == [
        "/nodes/n_fillet_0/params/radius_mm"
    ]

