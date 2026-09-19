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

import pytest

from seekflow_structural.agents import feedback
from seekflow_structural.pipeline.stages import REQUIRES, STAGE_ORDER, Stage
from seekflow_structural.tools import results


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
