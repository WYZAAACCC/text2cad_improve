"""Checking a finding's argument, which is the part of the stage that is code.

The agent's judgement is not testable here and is not meant to be. What is
testable is what happens to that judgement afterwards: whether a number it
says it measured is in the field, whether the mechanism it claims matches the
signature that mechanism leaves, and whether the variable it names is one the
generator would accept.

Those three are the whole reason a finding is submitted as an argument rather
than as prose. A model asked to justify a conclusion it has already reached
will produce a plausible number, and the only defence is reading the number
back. Each test below is one way that can fail.
"""
from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from seekflow_structural.agents import feedback
from seekflow_structural.pipeline.stages import REQUIRES, STAGE_ORDER, Stage
from seekflow_structural.tools import knowledge, results


def _node(nid, x, y, z, s_eqv, s_radial=0.0, s_hoop=0.0, s_axial=0.0,
          safety_factor=None):
    node = results.Node(
        nid=nid, x=x, y=y, z=z, r=math.hypot(x, y),
        theta_deg=math.degrees(math.atan2(y, x)),
        ux=0.0, uy=0.0, uz=0.0, u_sum=0.0,
        s_radial=s_radial, s_hoop=s_hoop, s_axial=s_axial,
        s_eqv=s_eqv, stressed=s_eqv != 0.0,
    )
    if safety_factor is not None:
        object.__setattr__(node, "safety_factor", safety_factor)
    return node


def _state(nodes, **kwargs) -> feedback.FeedbackState:
    # Most tests exercise a specialised check, not the submission gate. They
    # start from the state a feedback run has after its mandatory ranking call;
    # the gate itself is tested explicitly below.
    kwargs.setdefault("ranked", True)
    return feedback.FeedbackState(
        field=results.ResultField(nodes=nodes),
        context=kwargs.pop("context", {"metrics": {}, "verdicts": []}),
        solve_dir=kwargs.pop("solve_dir", None) or __import__("pathlib").Path("."),
        job_dir=kwargs.pop("job_dir", None) or __import__("pathlib").Path("."),
        **kwargs,
    )


def _names(comparisons) -> list[str]:
    return [comparison.name for comparison in comparisons]


def _by_name(comparisons, name):
    return next(c for c in comparisons if c.name == name)


# --- evidence is read back ----------------------------------------------


def test_a_claimed_number_that_is_not_in_the_field_is_found_out():
    """A premise that cannot be read again is a recollection."""
    state = _state([_node(1, 60.0, 0.0, 0.0, 1482.0, s_hoop=1480.0)])
    comparisons = feedback._verify_evidence(
        [{"quantity": "s_eqv", "value": 1482.0, "source": "node:1"}], state
    )
    assert comparisons[0].relative == pytest.approx(0.0)


def test_a_claimed_number_that_disagrees_with_the_field_carries_the_residual():
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0, s_hoop=900.0)])
    comparisons = feedback._verify_evidence(
        [{"quantity": "s_hoop", "value": 1480.0, "source": "node:1"}], state
    )
    assert comparisons[0].relative > 0.0
    assert "900" in comparisons[0].right


def test_a_node_that_is_not_in_the_field_is_reported_as_unmeasurable():
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    comparisons = feedback._verify_evidence(
        [{"quantity": "s_eqv", "value": 1000.0, "source": "node:999"}], state
    )
    assert comparisons[0].relative is None
    assert "not in this run's result field" in comparisons[0].note


def test_a_source_that_does_not_say_where_to_look_is_told_how_to_say_it():
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    comparisons = feedback._verify_evidence(
        [{"quantity": "s_eqv", "value": 1000.0, "source": "somewhere"}], state
    )
    assert "node:<id>" in comparisons[0].note
    assert comparisons[0].relative is None


def test_a_reported_scalar_is_read_from_the_metrics_not_remeasured():
    state = _state(
        [_node(1, 60.0, 0.0, 0.0, 1000.0)],
        context={"metrics": {"stress": {"max_von_mises_mpa": 1482.673}},
                 "verdicts": []},
    )
    ok = feedback._verify_evidence(
        [{"quantity": "max_von_mises_mpa", "value": 1482.673,
          "source": "field:max_von_mises_mpa"}], state
    )
    assert ok[0].relative == pytest.approx(0.0, abs=1e-9)
    bad = feedback._verify_evidence(
        [{"quantity": "max_von_mises_mpa", "value": 1200.0,
          "source": "field:max_von_mises_mpa"}], state
    )
    assert bad[0].relative > 0.1


def test_an_aggregate_evidence_source_can_be_replayed():
    state = _state([
        _node(1, 60.0, 0.0, 0.0, 100.0, s_hoop=100.0),
        _node(2, 61.0, 0.0, 0.0, 150.0, s_hoop=150.0),
        _node(3, 62.0, 0.0, 0.0, 200.0, s_hoop=200.0),
    ])
    action = feedback.Action(
        action="snapshot_evidence", quantity="s_hoop", reducer="mean",
        r_min=59.5, r_max=62.5,
    )
    snapshot = feedback._snapshot_evidence(action, state)["result"]
    assert snapshot["value"] == pytest.approx(150.0)
    assert snapshot["node_count"] == 3

    comparisons = feedback._verify_evidence([{
        "quantity": "s_hoop",
        "value": snapshot["value"],
        "source": snapshot["source"],
    }], state)
    assert comparisons[0].relative == pytest.approx(0.0)

    wrong = feedback._verify_evidence([{
        "quantity": "s_hoop",
        "value": 130.0,
        "source": snapshot["source"],
    }], state)
    assert wrong[0].relative > 0.0


def test_the_prompt_explains_that_aggregate_evidence_has_a_source():
    prompt = feedback.spec().system_prompt
    assert "snapshot_evidence" in prompt
    assert "agg:" in prompt

# --- the mechanism has to match its signature ---------------------------


def test_hoop_driven_claimed_on_a_radial_peak_comes_apart():
    """The failure this check exists for.

    A hoop peak and a radial peak are relieved by different geometry. A
    finding that names one while its own peak shows the other is a finding
    whose reasoning can be seen to have failed before the change is paid for.
    """
    state = _state([_node(1, 210.0, 0.0, 0.0, 1042.0,
                          s_radial=1188.0, s_hoop=268.0)])
    comparisons = feedback._mechanism_consistency(
        {"mechanism": "hoop_driven", "radius_mm": 210.0, "z_mm": 0.0}, state
    )
    check = _by_name(comparisons, "mechanism.hoop_driven")
    assert check.relative > 0.0
    assert "s_radial" in check.left


def test_radial_driven_agrees_with_a_radial_peak():
    state = _state([_node(1, 210.0, 0.0, 0.0, 1042.0,
                          s_radial=1188.0, s_hoop=268.0)])
    comparisons = feedback._mechanism_consistency(
        {"mechanism": "radial_driven", "radius_mm": 210.0, "z_mm": 0.0}, state
    )
    assert _by_name(comparisons, "mechanism.radial_driven").relative == 0.0


def test_a_peak_on_a_symmetry_plane_is_told_it_is_a_property_of_the_model():
    """Changing the part will not move a peak that the idealisation put there."""
    state = _state([_node(1, 60.0, 0.0, 0.0, 1482.0, s_hoop=1480.0)])
    comparisons = feedback._mechanism_consistency(
        {"mechanism": "idealisation_edge", "radius_mm": 60.0, "z_mm": 0.0}, state
    )
    assert _by_name(comparisons, "mechanism.idealisation_edge").relative == 0.0


def test_a_peak_away_from_every_plane_is_not_an_idealisation_edge():
    state = _state([_node(1, 60.0, 0.0, 17.0, 1482.0, s_hoop=1480.0)])
    comparisons = feedback._mechanism_consistency(
        {"mechanism": "idealisation_edge", "radius_mm": 60.0, "z_mm": 17.0}, state
    )
    assert _by_name(comparisons, "mechanism.idealisation_edge").relative > 0.0


def test_a_broad_region_is_not_a_stress_concentration():
    """The ratio that separates a fillet from a thin section."""
    nodes = [_node(0, 100.0, 0.0, 0.0, 1000.0, s_hoop=1000.0)]
    nodes += [_node(i, 100.0 + i * 1.0, 0.0, 0.0,
                    1000.0 * math.exp(-i * 0.01), s_hoop=900.0)
              for i in range(1, 40)]
    state = _state(nodes)
    comparisons = feedback._mechanism_consistency(
        {"mechanism": "stress_concentration", "radius_mm": 100.0, "z_mm": 0.0},
        state,
    )
    assert _by_name(comparisons, "mechanism.stress_concentration").relative > 0.0


def test_a_local_peak_agrees_with_a_stress_concentration():
    nodes = [_node(0, 100.0, 0.0, 0.0, 1000.0, s_hoop=1000.0)]
    nodes += [_node(i, 100.0 + i * 1.0, 0.0, 0.0,
                    1000.0 * math.exp(-i * 2.0), s_hoop=900.0)
              for i in range(1, 40)]
    state = _state(nodes)
    comparisons = feedback._mechanism_consistency(
        {"mechanism": "stress_concentration", "radius_mm": 100.0, "z_mm": 0.0},
        state,
    )
    assert _by_name(comparisons, "mechanism.stress_concentration").relative == 0.0


def test_a_peak_away_from_the_loaded_faces_is_not_a_load_application_problem():
    state = _state(
        [_node(1, 60.0, 0.0, 0.0, 1482.0, s_hoop=1480.0)],
        load_nodes={500, 501},
    )
    comparisons = feedback._mechanism_consistency(
        {"mechanism": "load_application", "radius_mm": 60.0, "z_mm": 0.0}, state
    )
    assert _by_name(comparisons, "mechanism.load_application").relative == 1.0


def test_a_peak_on_the_loaded_faces_is_consistent_with_a_load_application_problem():
    state = _state(
        [_node(500, 210.0, 0.0, 0.0, 1353.0, s_radial=1300.0)],
        load_nodes={500, 501},
    )
    comparisons = feedback._mechanism_consistency(
        {"mechanism": "load_application", "radius_mm": 210.0, "z_mm": 0.0}, state
    )
    assert _by_name(comparisons, "mechanism.load_application").relative == 0.0


def test_a_mechanism_needing_a_location_is_told_when_it_gave_none():
    """Without a location nothing about the mechanism can be measured."""
    state = _state([_node(1, 60.0, 0.0, 0.0, 1482.0, s_hoop=1480.0)])
    comparisons = feedback._mechanism_consistency(
        {"mechanism": "hoop_driven"}, state
    )
    assert _names(comparisons) == ["mechanism.location"]
    assert "1 mm" in comparisons[0].note


def test_unresolved_claims_nothing_and_is_therefore_not_contradicted():
    """Saying "I cannot attribute this" is a real answer, not a failure."""
    state = _state([_node(1, 60.0, 0.0, 0.0, 1482.0, s_hoop=1480.0)])
    assert feedback._mechanism_consistency({"mechanism": "unresolved"}, state) == []


# --- the change has to be one the generator will take -------------------


def test_a_variable_the_generator_does_not_have_is_refused_by_name():
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    comparisons = feedback._change_consistency(
        {"change": {"parameter": "web_thickness_mm", "relative_change": 0.1}},
        state,
    )
    assert "in neither layer" in comparisons[0].note
    assert "web_outer_half_thickness_mm" in comparisons[0].note


def test_a_variable_the_generator_derives_is_refused_because_it_is_recomputed():
    """Writing a value the generator computes away is worse than not trying.

    The groove's inner radius is the rim-web junction by a hard constraint, so
    a change to it would be accepted into a parameter set and then silently
    recomputed. The finding has to name the variable it is derived from.
    """
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    comparisons = feedback._change_consistency(
        {"change": {"parameter": "inner_radius_mm", "relative_change": 0.1}},
        state,
    )
    assert "recomputed away" in comparisons[0].note


def test_a_categorical_variable_cannot_carry_a_magnitude():
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    comparisons = feedback._change_consistency(
        {"change": {"parameter": "rim_transition_type", "relative_change": 0.1}},
        state,
    )
    assert "named alternatives" in comparisons[0].note


def test_a_change_larger_than_the_repair_kernel_accepts_is_reported():
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    comparisons = feedback._change_consistency(
        {"change": {"parameter": "rim_half_thickness_mm", "relative_change": 0.6}},
        state,
    )
    check = next(c for c in comparisons if c.name == "change.magnitude")
    assert check.relative > 1.0
    assert "refused downstream" in check.note


def test_a_change_within_the_budget_is_not_flagged():
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    comparisons = feedback._change_consistency(
        {"change": {"parameter": "rim_half_thickness_mm", "relative_change": 0.1}},
        state,
    )
    assert comparisons == []


def test_a_template_parameter_is_not_an_alternative_once_there_is_a_document():
    """The two vocabularies are not two names for the same change.

    The template layer used to be offered as a second option - "a parameter of
    this model, or a template parameter" - which reads as a choice. It is not
    one. From the revision that has a document onward, the generator reads the
    document and never calls `param_templates.build`, so a template parameter
    is written into `params.json`, which nothing opens: the next revision is
    the previous geometry, and its numbers are recorded as the effect of a
    change that was never made. Measured on D27, none of the 18 template
    variables is present in the document.
    """
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)], document=_aim_doc())
    comparisons = feedback._change_consistency(
        {"change": {"parameter": "rim_half_thickness_mm", "relative_change": 0.1}},
        state,
    )
    problem = next(c for c in comparisons if c.name == "change.parameter")
    assert "never reads" in problem.note
    assert "list_document_params" in problem.note


def test_the_template_vocabulary_still_applies_before_a_document_exists():
    """The name is refused for where it lands, not for what it is called."""
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    comparisons = feedback._change_consistency(
        {"change": {"parameter": "rim_half_thickness_mm", "relative_change": 0.1}},
        state,
    )
    assert comparisons == []


def test_a_document_parameter_is_the_one_that_passes_with_a_document():
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)], document=_aim_doc())
    comparisons = feedback._change_consistency(
        {"change": {"parameter": "disc.points[2].y_mm", "relative_change": 0.1}},
        state,
    )
    assert [c.name for c in comparisons] == ["change.parameter"]
    assert "currently 15.0" in comparisons[0].note


# --- ranking what can actually be acted on -------------------------------


def _rank_action(**kwargs):
    values = {"limit": 6, "relative_threshold": 0.8, "cell_mm": 5.0}
    values.update(kwargs)
    return type("A", (), values)()


def test_a_suspect_global_peak_does_not_outrank_a_stable_actionable_region():
    nodes = [
        _node(1, 210.0, 0.0, 0.0, 1800.0, s_hoop=100.0),
        _node(2, 212.0, 0.0, 0.0, 1750.0, s_hoop=90.0),
        _node(3, 214.0, 0.0, 0.0, 1700.0, s_hoop=80.0),
        _node(100, 60.0, 0.0, 0.0, 1600.0, s_hoop=1550.0),
        _node(101, 62.0, 0.0, 0.0, 1580.0, s_hoop=1530.0),
        _node(102, 64.0, 0.0, 0.0, 1560.0, s_hoop=1510.0),
    ]
    state = _state(nodes, context={
        "metrics": {"stress": {"max_node": 1, "max_von_mises_mpa": 1800.0}},
        "verdicts": [
            {"quantity": "max_von_mises_mpa", "verdict": "suspect"},
            {"quantity": "max_load_surface_von_mises_mpa", "verdict": "suspect"},
        ],
    })

    result = feedback._rank_problem_regions(_rank_action(), state)["result"]

    assert result["selected_region"]["peak_node"] == 100
    suspect = next(item for item in result["ranked_regions"]
                   if item["peak_node"] == 1)
    assert suspect["optimisation_allowed"] is False
    assert any("suspect" in reason for reason in suspect["actionability"])


def test_ranking_links_an_allowed_region_to_editable_parameters():
    nodes = [_node(1, 240.0, 0.0, 0.0, 1500.0, s_radial=1400.0),
             _node(2, 242.0, 0.0, 0.0, 1450.0, s_radial=1350.0)]
    state = _state(nodes, context={
        "metrics": {"stress": {"max_node": 1, "max_von_mises_mpa": 1500.0}},
        "verdicts": [{"quantity": "max_von_mises_mpa", "verdict": "unverified"}],
    }, document=_aim_doc())

    result = feedback._rank_problem_regions(_rank_action(), state)["result"]
    selected = result["selected_region"]

    assert selected["optimisation_allowed"] is True
    assert selected["nearby_editable"]
    assert any(item["parameter"] == "disc.points[2].y_mm"
               for item in selected["nearby_editable"])


# --- the record the loop has already built ------------------------------


def _rules_action(**kwargs):
    values = {"mechanism": ""}
    values.update(kwargs)
    return type("A", (), values)()


def _refuted_entry(entry_id="hoop_driven::rim_half_thickness_mm"):
    entry = knowledge.KnowledgeEntry(
        id=entry_id, mechanism="hoop_driven",
        parameter="rim_half_thickness_mm", direction="decrease",
        at="bore", status="refuted",
    )
    for measured in (0.081, 0.114):
        entry.observations.append(knowledge.Observation(
            revision="rev-000001", metric="max_von_mises_mpa",
            predicted_relative_change=-0.05,
            measured_relative_change=measured, outcome="refuted",
        ))
    return entry


def test_the_loop_record_is_readable_and_names_what_it_has_never_tested():
    """The agent that chooses what to test can see what has been tested.

    Measured on D27: six revisions ran, the record held nothing but its eight
    seed rules, and the rule the loop actually made progress on stayed a
    candidate with one confirmation. A rule settles only when the same
    direction is proposed and measured more than once, and the stage that
    decides what to propose had no sight of the record at all.
    """
    base = knowledge.KnowledgeBase.load(__import__("pathlib").Path("none.json"))
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)], base=base)

    result = feedback._get_rules(
        _rules_action(mechanism="hoop_driven"), state
    )["result"]

    assert result["attached"] is True
    held = result["mechanisms"]["hoop_driven"]
    assert [entry["id"] for entry in held["rules"]] == [
        "bore-hoop-rim-mass", "bore-hoop-bore-radius",
    ]
    assert held["untested"] == ["bore-hoop-rim-mass", "bore-hoop-bore-radius"]
    assert "bore-hoop-rim-mass" in result["untested"]
    assert held["retired"] == []


def test_a_change_that_was_tried_and_failed_is_reported_apart_from_advice():
    base = knowledge.KnowledgeBase()
    base.entries = [_refuted_entry()]
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)], base=base)

    held = feedback._get_rules(
        _rules_action(mechanism="hoop_driven"), state
    )["result"]["mechanisms"]["hoop_driven"]

    assert held["rules"] == []
    assert [entry["id"] for entry in held["retired"]] == [
        "hoop_driven::rim_half_thickness_mm",
    ]
    assert len(held["retired"][0]["observations"]) == 2
    assert held["retired"][0]["refutations"] == 2


def test_no_record_is_reported_as_no_record_rather_than_as_an_empty_one():
    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    result = feedback._get_rules(_rules_action(), state)["result"]
    assert result["attached"] is False
    assert "no knowledge base is attached" in result["limits"][0]


# --- what the load actually reached --------------------------------------


def _audit_context():
    return {
        "metrics": {"stress": {"max_von_mises_mpa": 1000.0}},
        "verdicts": [],
        "load_audit": {
            "emission": {
                "mechanism": "surface_pressure",
                "pressure_mpa": 285.2,
                "occ_area_total_mm2": 130.0,
                "mapped_area_total_mm2": 50.0,
                "limits": [
                    "selected face(s) [2] produced no element face. Either the "
                    "mesh does not reach them, or they are not planar",
                ],
            },
            "area_accounting_by_face": {
                "1": {"occ_area_mm2": 100.0, "mapped_area_mm2": 50.0,
                      "element_face_count": 40},
                "2": {"occ_area_mm2": 30.0, "mapped_area_mm2": 0.0,
                      "element_face_count": 0},
            },
        },
    }


def test_a_face_the_load_never_reached_is_reported_apart_from_a_partial_model():
    """The two reasons a face is not fully pressed are not the same reason.

    A face with no element face at all received nothing. A face whose element
    faces cover half its CAD area is what a half-thickness model looks like,
    and reporting the two as one number - the raw fraction in the audit - is
    how a correct run reads as a load shortfall.
    """
    state = _state(
        [_node(1, 60.0, 0.0, 0.0, 1000.0)], context=_audit_context()
    )
    integrity = feedback._load_integrity(state)

    assert integrity["pressed_area_mm2"] == pytest.approx(50.0)
    assert integrity["reached_selection_area_mm2"] == pytest.approx(100.0)
    assert integrity["declared_selection_area_mm2"] == pytest.approx(130.0)
    assert integrity["mesh_coverage_of_reached_faces"] == pytest.approx(0.5)
    assert integrity["lowest_single_face_coverage"] == pytest.approx(0.5)
    assert integrity["faces_with_no_element_face"] == [2]
    assert integrity["faces_with_no_element_face_area_mm2"] == pytest.approx(30.0)
    joined = " ".join(integrity["limits"])
    assert "no load reached them at all" in joined
    assert "half of every face that straddles the mid-plane" in joined


def test_the_result_context_carries_what_the_load_reached():
    state = _state(
        [_node(1, 60.0, 0.0, 0.0, 1000.0)], context=_audit_context()
    )
    context = feedback._get_result_context(
        type("A", (), {})(), state
    )["result"]
    assert context["load_integrity"]["faces_with_no_element_face"] == [2]


def test_a_revision_document_overrides_the_bundle_fallback(monkeypatch, tmp_path):
    """Feedback sees the design revise will actually edit.

    Some stored jobs carry a bundle path without document.json. The loop has
    the revision workspace, so it passes that document explicitly; otherwise
    feedback can propose a template parameter that revise must later reject.
    """
    from seekflow_structural.case.model import BundleRef, Case

    monkeypatch.setattr(
        results.ResultField, "load",
        classmethod(lambda cls, solve_dir, material_points=None: results.ResultField(nodes=[])),
    )
    monkeypatch.setattr(results, "load_context", lambda solve_dir, job_dir=None: {})
    case = Case(case_id="probe", bundle=BundleRef(path="."))
    ctx = SimpleNamespace(path=Path(tmp_path), case=case)
    document = {"schema_version": "probe", "nodes": []}
    state = feedback._load_state(ctx, document_override=document)
    assert state.document == document


# --- the report the stage writes ----------------------------------------


def test_the_report_records_which_quantities_were_not_allowed_to_carry_a_finding():
    """Optimising a number that has not settled is how a loop converges on an artefact."""
    state = _state(
        [_node(1, 60.0, 0.0, 0.0, 1000.0)],
        context={
            "metrics": {},
            "verdicts": [
                {"quantity": "max_von_mises_mpa", "verdict": "suspect"},
                {"quantity": "max_displacement_mm", "verdict": "unverified"},
            ],
        },
    )
    feedback._submit_feedback(
        type("A", (), {
            "findings": [{
                "mechanism": "unresolved",
                "evidence": [{"quantity": "s_eqv", "value": 1000.0,
                              "source": "node:1"}],
            }],
            "summary": "", "limits": [], "rationale": "",
        })(),
        state,
    )
    report = feedback.to_case_feedback(state)
    assert any("max_von_mises_mpa" in entry for entry in report.excluded_quantities)
    assert not any("max_displacement_mm" in entry
                   for entry in report.excluded_quantities)


def test_filing_nothing_is_refused_with_the_alternative_spelled_out():
    """An empty submission is a claim, not a no-op."""
    from seekflow_structural.errors import StructuralError

    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    with pytest.raises(StructuralError) as excinfo:
        feedback._submit_feedback(
            type("A", (), {"findings": [], "summary": "", "limits": [],
                           "rationale": ""})(),
            state,
        )
    assert "unresolved" in str(excinfo.value)


def test_a_finding_with_no_evidence_is_refused():
    from seekflow_structural.errors import StructuralError

    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    with pytest.raises(StructuralError) as excinfo:
        feedback._submit_feedback(
            type("A", (), {
                "findings": [{"mechanism": "stress_concentration", "evidence": []}],
                "summary": "", "limits": [], "rationale": "",
            })(),
            state,
        )
    assert "no evidence" in str(excinfo.value)


def test_submission_re_reads_evidence_instead_of_trusting_the_claim():
    """`check_finding` is a convenience, not the gate.

    The agent may skip the dry-run tool. The submission path therefore has to
    re-read the evidence itself; otherwise a fabricated number can be filed by
    simply not asking the checker.
    """
    from seekflow_structural.errors import StructuralError

    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    with pytest.raises(StructuralError) as excinfo:
        feedback._submit_feedback(
            type("A", (), {
                "findings": [{
                    "mechanism": "unresolved",
                    "evidence": [{"quantity": "s_eqv", "value": 1482.0,
                                  "source": "node:1"}],
                }],
                "summary": "", "limits": [], "rationale": "",
            })(),
            state,
        )
    assert "does not re-read" in str(excinfo.value)


def test_submission_rejects_evidence_that_cannot_be_read_back():
    from seekflow_structural.errors import StructuralError

    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    with pytest.raises(StructuralError) as excinfo:
        feedback._submit_feedback(
            type("A", (), {
                "findings": [{
                    "mechanism": "unresolved",
                    "evidence": [{"quantity": "s_eqv", "value": 1000.0,
                                  "source": "node:999"}],
                }],
                "summary": "", "limits": [], "rationale": "",
            })(),
            state,
        )
    assert "cannot be re-read" in str(excinfo.value)


def test_a_geometry_change_without_a_prediction_is_refused():
    state = _state([_node(1, 210.0, 0.0, 0.0, 1000.0,
                          s_radial=900.0, s_hoop=100.0)])
    problems = feedback.finding_argument_problems({
        "mechanism": "radial_driven",
        "radius_mm": 210.0,
        "z_mm": 0.0,
        "evidence": [{"quantity": "s_radial", "value": 900.0,
                      "source": "node:1"}],
        "change": {"parameter": "rim_half_thickness_mm",
                   "relative_change": 0.1},
    }, state)
    assert any("states no prediction" in item for item in problems)


def test_a_prediction_must_name_a_metric_this_solve_reported():
    state = _state(
        [_node(1, 210.0, 0.0, 0.0, 1000.0,
               s_radial=900.0, s_hoop=100.0)],
        context={
            "metrics": {"stress": {"max_von_mises_mpa": 1000.0}},
            "verdicts": [],
        },
    )
    problems = feedback.finding_argument_problems({
        "mechanism": "radial_driven",
        "radius_mm": 210.0,
        "z_mm": 0.0,
        "evidence": [{"quantity": "s_radial", "value": 900.0,
                      "source": "node:1"}],
        "change": {"parameter": "rim_half_thickness_mm",
                   "relative_change": 0.1},
        "prediction": {"metric": "not_a_reported_metric",
                       "direction": "decrease",
                       "expected_relative_change": 0.1},
    }, state)
    assert any("did not report" in item for item in problems)


def test_a_non_design_mechanism_cannot_carry_a_geometry_change():
    state = _state([_node(1, 210.0, 0.0, 0.0, 1000.0,
                          s_radial=900.0, s_hoop=100.0)])
    problems = feedback.finding_argument_problems({
        "mechanism": "load_application",
        "radius_mm": 210.0,
        "z_mm": 0.0,
        "evidence": [{"quantity": "s_radial", "value": 900.0,
                      "source": "node:1"}],
        "change": {"parameter": "rim_half_thickness_mm",
                   "relative_change": 0.1},
        "prediction": {"metric": "max_von_mises_mpa",
                       "direction": "decrease",
                       "expected_relative_change": 0.1},
    }, state)
    assert any("not a geometry-change diagnosis" in item for item in problems)


def test_an_unknown_document_parameter_is_refused_at_submission():
    state = _state(
        [_node(1, 208.09, 0.0, 0.0, 1000.0,
               s_radial=900.0, s_hoop=100.0)],
        document=_aim_doc(),
    )
    problems = feedback.finding_argument_problems({
        "mechanism": "radial_driven",
        "radius_mm": 208.09,
        "z_mm": 0.0,
        "evidence": [{"quantity": "s_radial", "value": 900.0,
                      "source": "node:1"}],
        "change": {"parameter": "not_a_node.radius_mm",
                   "relative_change": 0.1},
        "prediction": {"metric": "max_von_mises_mpa",
                       "direction": "decrease",
                       "expected_relative_change": 0.1},
    }, state)
    assert any("has no such operation parameter" in item for item in problems)


def test_a_change_written_under_guessed_key_names_is_recognised():
    """The regression that ended the first end-to-end run.

    Measured on D27: the change came back as `{'variable': 'rim_fillet_radius',
    'current': None, 'proposed': None, 'relative': None}`. Every name was a
    reasonable guess at what the harness wanted, none of them was read, and
    the validation error that followed destroyed a solve that had already
    finished.
    """
    change, dropped = feedback.normalise_change({
        "variable": "rim_fillet_radius", "current": 15.0,
        "proposed": 13.5, "relative": -0.1,
    })
    assert change["parameter"] == "rim_fillet_radius"
    assert change["current_value"] == 15.0
    assert change["proposed_value"] == 13.5
    assert change["relative_change"] == -0.1
    assert dropped == []


def test_a_change_key_that_means_nothing_is_dropped_and_reported():
    """Dropped rather than fatal: a solve costs minutes to hours."""
    change, dropped = feedback.normalise_change({
        "parameter": "rim_half_thickness_mm", "units": "mm", "note": "why",
    })
    assert change["parameter"] == "rim_half_thickness_mm"
    assert sorted(dropped) == ["note", "units"]


def test_a_finding_whose_change_names_no_parameter_is_refused_with_the_keys():
    problems = feedback.finding_shape_problems({
        "mechanism": "hoop_driven",
        "evidence": [{"quantity": "s_hoop", "value": 1.0, "source": "node:1"}],
        "change": {"magnitude": 0.1},
    })
    assert any("names no parameter" in problem for problem in problems)
    assert any("magnitude" in problem for problem in problems)


def test_a_change_naming_a_variable_the_generator_has_not_got_is_refused():
    """The second real run: right geometry, invented variable.

    The agent located the peak on the fir-tree flanks correctly and then asked
    for `fir_tree_flank_fillet_radius_mm`. The generator has never heard of it
    - the variable meant is `root_fillet_mm` - so the geometry was right and
    nothing downstream could apply the finding.
    """
    problems = feedback.finding_shape_problems({
        "mechanism": "stress_concentration",
        "evidence": [{"quantity": "s_eqv", "value": 1.0, "source": "node:1"}],
        "change": {"parameter": "fir_tree_flank_fillet_radius_mm",
                   "relative_change": -0.1},
    })
    assert any("not a variable the generation side takes" in problem
               for problem in problems)
    assert any("rim_mm" in problem for problem in problems)


def test_a_variable_the_authoring_side_knows_and_this_generator_has_not():
    """`root_fillet_mm` is real where the LLM authors and absent here.

    Measured on the third real run: the agent located the peak on the
    fir-tree flanks correctly and asked for a root fillet. The template has no
    such control - the profile is built from half-widths and angles - so the
    diagnosis was right and the finding could not be carried out. The agent is
    told that, rather than that it mistyped, because the difference decides
    whether the finding is skipped or reworded.
    """
    problems = feedback.finding_shape_problems({
        "mechanism": "stress_concentration",
        "evidence": [{"quantity": "s_eqv", "value": 1.0, "source": "node:1"}],
        "change": {"parameter": "root_fillet_mm", "relative_change": 0.15},
    })
    assert any("no control for" in problem for problem in problems)
    assert any("file it without a change" in problem for problem in problems)


def test_a_change_naming_a_variable_the_generator_derives_is_refused():
    problems = feedback.finding_shape_problems({
        "mechanism": "stress_concentration",
        "evidence": [{"quantity": "s_eqv", "value": 1.0, "source": "node:1"}],
        "change": {"parameter": "neck_half_width_mm", "relative_change": -0.1},
    })
    assert any("recomputed away" in problem for problem in problems)


def test_a_change_that_says_what_to_change_but_not_what_to_is_refused():
    """A change with no value asks for the revision that already exists."""
    problems = feedback.finding_shape_problems({
        "mechanism": "hoop_driven",
        "evidence": [{"quantity": "s_hoop", "value": 1.0, "source": "node:1"}],
        "change": {"parameter": "bore_radius_mm", "current_value": 60.0},
    })
    assert any("not what to change it to" in problem for problem in problems)


def test_a_change_that_gives_only_a_relative_change_is_accepted():
    assert feedback.finding_shape_problems({
        "mechanism": "hoop_driven",
        "evidence": [{"quantity": "s_hoop", "value": 1.0, "source": "node:1"}],
        "change": {"parameter": "bore_radius_mm", "relative_change": 0.1},
    }) == []


def test_the_prompt_carries_the_variables_the_generator_actually_takes():
    """A name the agent has to guess is a name it will get wrong."""
    from seekflow_structural.tools import design_variables

    prompt = feedback.spec().system_prompt
    for name in design_variables.free_variables():
        assert f"    {name}\n" in prompt, name
    # And not the ones it must not name.
    assert "    inner_radius_mm\n" not in prompt


def test_a_prediction_whose_direction_is_not_a_direction_is_refused():
    problems = feedback.finding_shape_problems({
        "mechanism": "hoop_driven",
        "evidence": [{"quantity": "s_hoop", "value": 1.0, "source": "node:1"}],
        "prediction": {"metric": "max_von_mises_mpa", "direction": "down"},
    })
    assert any("'increase' or 'decrease'" in problem for problem in problems)


def test_a_prediction_without_a_size_is_refused_at_submission():
    problems = feedback.finding_shape_problems({
        "mechanism": "radial_driven",
        "evidence": [{"quantity": "s_radial", "value": 1.0,
                      "source": "node:1"}],
        "change": {"parameter": "rim_half_thickness_mm",
                   "relative_change": 0.1},
        "prediction": {"metric": "max_von_mises_mpa",
                       "direction": "decrease"},
    })
    assert any("expected_relative_change" in problem for problem in problems)


def test_a_citation_with_no_number_is_refused_at_submission():
    problems = feedback.finding_shape_problems({
        "mechanism": "hoop_driven",
        "evidence": [{"quantity": "s_hoop", "value": "high", "source": "node:1"}],
    })
    assert any("not a number" in problem for problem in problems)


def test_a_well_formed_finding_has_no_problems():
    assert feedback.finding_shape_problems({
        "mechanism": "hoop_driven",
        "evidence": [{"quantity": "s_hoop", "value": 1482.0, "source": "node:469"}],
        "change": {"parameter": "rim_half_thickness_mm",
                   "current_value": 15.0, "proposed_value": 13.5,
                   "relative_change": -0.1},
        "prediction": {"metric": "max_von_mises_mpa", "direction": "decrease",
                       "expected_relative_change": 0.05},
    }) == []


def _actionable_finding(finding_id: str, parameter: str) -> dict:
    return {
        "id": finding_id,
        "mechanism": "radial_driven",
        "feature": "rim",
        "radius_mm": 210.0,
        "z_mm": 0.0,
        "evidence": [{"quantity": "s_radial", "value": 900.0,
                      "source": "node:1"}],
        "change": {"parameter": parameter, "relative_change": 0.1},
        "prediction": {"metric": "max_von_mises_mpa",
                       "direction": "decrease",
                       "expected_relative_change": 0.1},
    }


def test_one_feedback_revision_can_test_only_one_design_change():
    from seekflow_structural.errors import StructuralError

    state = _state(
        [_node(1, 210.0, 0.0, 0.0, 1000.0,
               s_radial=900.0, s_hoop=100.0)],
        context={
            "metrics": {"stress": {"max_von_mises_mpa": 1000.0}},
            "verdicts": [],
        },
    )
    with pytest.raises(StructuralError) as excinfo:
        feedback._submit_feedback(
            type("A", (), {
                "findings": [
                    _actionable_finding("F1", "rim_half_thickness_mm"),
                    _actionable_finding("F2", "web_outer_half_thickness_mm"),
                ],
                "summary": "", "limits": [], "rationale": "",
            })(),
            state,
        )
    assert "multiple_design_changes" in str(excinfo.value.diagnostic.code)


def test_duplicate_finding_ids_are_refused():
    from seekflow_structural.errors import StructuralError

    state = _state(
        [_node(1, 210.0, 0.0, 0.0, 1000.0,
               s_radial=900.0, s_hoop=100.0)],
        context={
            "metrics": {"stress": {"max_von_mises_mpa": 1000.0}},
            "verdicts": [],
        },
    )
    with pytest.raises(StructuralError) as excinfo:
        feedback._submit_feedback(
            type("A", (), {
                "findings": [
                    _actionable_finding("F1", "rim_half_thickness_mm"),
                    _actionable_finding("F1", "web_outer_half_thickness_mm"),
                ],
                "summary": "", "limits": [], "rationale": "",
            })(),
            state,
        )
    assert "duplicate_finding_id" in str(excinfo.value.diagnostic.code)


def test_a_mechanism_outside_the_vocabulary_is_refused_with_the_list():
    from seekflow_structural.errors import StructuralError

    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)])
    with pytest.raises(StructuralError) as excinfo:
        feedback._submit_feedback(
            type("A", (), {
                "findings": [{"mechanism": "too_much_stress",
                              "evidence": [{"quantity": "s_eqv", "value": 1.0,
                                            "source": "node:1"}]}],
                "summary": "", "limits": [], "rationale": "",
            })(),
            state,
        )
    assert "stress_concentration" in str(excinfo.value)


# --- the stage is wired in ----------------------------------------------


def test_the_feedback_stage_runs_after_verification_and_needs_its_verdicts():
    """Reading the results before they are judged is reading them twice."""
    assert STAGE_ORDER.index(Stage.FEEDBACK) == STAGE_ORDER.index(Stage.VERIFY) + 1
    assert "verdicts" in REQUIRES[Stage.FEEDBACK]
    assert "solve" in REQUIRES[Stage.FEEDBACK]

# --- whether a change can reach the peak it is filed for -----------------


def _aim_doc():
    """The D27 shape of the problem: fillets at the rim, the peak in the web."""
    return {"nodes": [
        {"id": "sk_d", "op": "create_2d_sketch", "params": {"plane": "XZ"}},
        {"id": "disc", "op": "add_polyline", "component": "disc_body",
         "inputs": [{"node": "sk_d"}],
         "params": {"points": [{"x_mm": 60.0, "y_mm": -38.0},
                               {"x_mm": 160.0, "y_mm": 22.8},
                               {"x_mm": 240.0, "y_mm": 15.0},
                               {"x_mm": 300.0, "y_mm": 30.0}]}},
        {"id": "close_d", "op": "close_profile",
         "inputs": [{"node": "disc"}], "params": {}},
        {"id": "web_rim", "op": "fillet_sketch",
         "inputs": [{"node": "close_d"}],
         "params": {"radius_mm": 10.0, "at_vertex_index": [2]}},
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


def _aim(parameter, peak_r):
    return {
        "mechanism": "stress_concentration",
        "radius_mm": peak_r,
        "evidence": [{"quantity": "s_eqv", "value": 1.0, "source": "node:1"}],
        "change": {"parameter": parameter, "relative_change": 0.1},
    }


def test_a_fillet_far_from_the_peak_is_refused_with_the_distance():
    """The failure this exists for, measured on D27.

    The peak is at r = 208.09 on the web. The run found
    `n_fillet_cutter_0.radius_mm` in the parameter list and asked for it,
    because it is a fillet and the run had decided the problem was a fillet
    problem. That parameter acts at r = 284.3. The change was made, built,
    solved, and came back at -0.00%, and nothing said why.
    """
    problems = feedback.finding_shape_problems(
        _aim("tooth.radius_mm", 208.09), _aim_doc()
    )
    assert len(problems) == 1
    assert "76.2" in problems[0]
    assert "r = 208.09" in problems[0]


def test_a_profile_vertex_whose_edge_spans_the_peak_is_allowed():
    """Moving a vertex pivots the edges that meet it, and that span is read
    from the document rather than assumed."""
    problems = feedback.finding_shape_problems(
        _aim("disc.points[2].y_mm", 208.09), _aim_doc()
    )
    assert problems == []


def test_the_same_fillet_is_allowed_when_the_peak_is_where_it_acts():
    """The check refuses an aim, not a kind of parameter."""
    assert feedback.finding_shape_problems(
        _aim("tooth.radius_mm", 284.3), _aim_doc()
    ) == []


def test_a_disc_fillet_at_the_wrong_radius_is_refused_too():
    """The web-rim fillet is at r = 240 and does not reach r = 208 either."""
    problems = feedback.finding_shape_problems(
        _aim("web_rim.radius_mm", 208.09), _aim_doc()
    )
    assert len(problems) == 1
    assert "31.9" in problems[0]


def test_without_a_document_the_aim_is_not_judged_rather_than_passed():
    """Not judged and passed are different, and only one of them is honest."""
    assert feedback.finding_shape_problems(
        _aim("tooth.radius_mm", 208.09), None
    ) == []


def test_the_reach_reports_where_a_parameter_acts_and_what_it_spans():
    reach = feedback._reach(_aim("tooth.radius_mm", 208.09), _aim_doc())
    assert reach["acts_at_r_mm"] == pytest.approx(284.28, abs=0.1)
    assert reach["spans_r_mm"] == pytest.approx([274.28, 294.28], abs=0.1)
    assert reach["reaches"] is False
    assert reach["distance_mm"] == pytest.approx(76.19, abs=0.1)


def test_a_change_with_no_peak_to_aim_at_is_not_judged():
    """A finding that states no radius cannot be checked against one."""
    finding = _aim("tooth.radius_mm", 208.09)
    finding.pop("radius_mm")
    assert feedback._reach(finding, _aim_doc()) is None


def test_filing_findings_requires_the_region_ranking_first():
    """The ranking is a stage guarantee, not optional prose advice."""
    from seekflow_structural.errors import StructuralError

    state = _state([_node(1, 60.0, 0.0, 0.0, 1000.0)], ranked=False)
    action = type("A", (), {
        "findings": [{
            "mechanism": "unresolved",
            "evidence": [{"quantity": "s_eqv", "value": 1000.0,
                          "source": "node:1"}],
        }],
        "summary": "",
        "limits": [],
        "rationale": "",
    })()
    with pytest.raises(StructuralError) as excinfo:
        feedback._submit_feedback(action, state)
    assert excinfo.value.diagnostic.code == "missing_region_ranking"
    assert "rank_problem_regions" in str(excinfo.value)


def test_proposed_value_and_relative_change_must_not_disagree():
    state = _state([_node(1, 210.0, 0.0, 0.0, 1000.0,
                          s_radial=900.0, s_hoop=100.0)])
    problems = feedback.finding_argument_problems({
        "mechanism": "radial_driven",
        "radius_mm": 210.0,
        "z_mm": 0.0,
        "evidence": [{"quantity": "s_radial", "value": 900.0,
                      "source": "node:1"}],
        "change": {
            "parameter": "rim_half_thickness_mm",
            "current_value": 63.0,
            "proposed_value": 66.0,
            "relative_change": 0.2,
        },
        "prediction": {"metric": "max_von_mises_mpa",
                       "direction": "decrease",
                       "expected_relative_change": 0.05},
    }, state)
    assert any("disagree" in item for item in problems)
