"""The tool loop, and the criterion that replaced the hard-coded gate.

Everything here runs offline. The loop takes its caller by injection - the
same seam the CFD tests use - so the transcript, the budget and the error
handling can be exercised without a network or a key.

The criterion tests matter more than they look. The validator this replaced
encoded one component's idea of a load face and rejected anything else with
"must be planar", which says nothing about why. What is checked here is that a
clause which is not met comes back as a residual with the value beside the
bound, so the agent can tell a near miss from a face pointing the other way.
"""
from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from seekflow_structural.agents import facefind
from seekflow_structural.case.model import (
    CountClause,
    Criterion,
    NormalClause,
    SymmetryClause,
    Vec3,
)
from seekflow_structural.errors import StructuralError
from seekflow_structural.runtime.loop import (
    AgentSpec,
    dispatch_table,
    run_agent,
)
from seekflow_structural.tools import criteria


class FakeCaller:
    """A caller that replays a scripted list of tool calls.

    Records the messages it was given, so a test can check that the transcript
    the loop builds is the one the protocol requires.
    """

    def __init__(self, script):
        self.script = list(script)
        self.seen = []
        self.seen_schemas = []

    def call_strict_tool(self, *, messages, tool_name, tool_description,
                         tool_schema, model_config):
        from types import SimpleNamespace

        self.seen.append([dict(m) for m in messages])
        self.seen_schemas.append(tool_schema["properties"])
        if not self.script:
            raise AssertionError("the loop asked for more calls than scripted")
        arguments = self.script.pop(0)
        return SimpleNamespace(
            tool_name=tool_name,
            arguments=arguments,
            tool_call_id=f"call_{len(self.seen)}",
            assistant_content="",
            raw_response_id="r",
            model="fake",
            provider="fake",
        )


def a_face(index, *, radius=200.0, theta=10.0, area=50.0,
           radial=-1.0, axial=0.0, surface="plane"):
    """A face whose unit normal has the radial and axial parts asked for.

    The remainder goes into the tangential component, because a face normal is
    a unit vector and the criterion's clauses are on its components. A fixture
    that just sets normal_xyz = [radial, 0, axial] is not a normal at all, and
    the decomposition normalises it - so a "radial component of -0.19" would
    silently come back as -1.
    """
    import math

    tangential = math.sqrt(max(0.0, 1.0 - radial ** 2 - axial ** 2))
    return {
        "face_index": index,
        "surface_type": surface,
        "area_mm2": area,
        "centroid_cyl_mm_deg": [radius, theta, 0.0],
        "centroid_mm": [radius, 0.0, 0.0],
        "normal_xyz": [radial, tangential, axial],
        "normal_cylindrical": {
            "radial": radial, "axial": axial, "tangential": tangential,
        },
    }


def a_state(rows):
    state = facefind.FaceFinderState(session=None)
    state.cache[("f", 0)] = rows
    return state


# --- the loop --------------------------------------------------------------


class EchoAction(BaseModel):
    """A minimal action model so the loop can be tested without an agent."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["look", "stop", "blow_up"]
    value: int = 0
    # Stands in for the free text the real agents write on every call. It is
    # here because the loop is supposed to ignore it when deciding whether a
    # call has been made before, and a test cannot check that without one.
    rationale: str = ""


class EchoCommit(BaseModel):
    """What the last call offers: the two actions that end the run."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["stop", "blow_up"]
    value: int = 0


def echo_spec(max_calls=4, terminal=False) -> AgentSpec:
    return AgentSpec(
        name="echo",
        tool_name="echo_action",
        tool_description="echo",
        action_model=EchoAction,
        system_prompt="s",
        user_prompt="u",
        submit_actions=frozenset({"stop"}),
        max_calls=max_calls,
        # `blow_up` is kept in the narrow model on purpose: the loop has to
        # survive a model that answers the narrowed schema with something the
        # full model would have allowed.
        terminal_model=EchoCommit if terminal else None,
    )


def echo_dispatch(action, context):
    if action.action == "blow_up":
        raise ValueError("the filter matched nothing")
    return {"ok": True, "result": {"echo": action.value}}


def test_the_loop_feeds_each_result_back_and_stops_on_a_submit():
    caller = FakeCaller([
        {"action": "look", "value": 1},
        {"action": "look", "value": 2},
        {"action": "stop", "value": 3},
    ])
    outcome = run_agent(
        echo_spec(), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": echo_dispatch, "stop": echo_dispatch}),
    )
    assert outcome.calls == 3
    # the dispatch's `result` is what the loop reports as final
    assert outcome.final["echo"] == 3
    assert not outcome.exhausted
    # system + user, then assistant/tool pairs
    assert len(caller.seen[-1]) == 2 + 2 * 2


def test_every_reply_carries_the_remaining_budget():
    caller = FakeCaller([
        {"action": "look"}, {"action": "stop"},
    ])

    def spy(action, context):
        return {"ok": True}

    outcome = run_agent(
        echo_spec(max_calls=3), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": spy, "stop": spy}),
    )
    import json

    transcript = caller.seen[-1]
    tool_messages = [m for m in transcript if m["role"] == "tool"]
    first = json.loads(tool_messages[0]["content"])
    assert first["calls_used"] == 1
    assert first["calls_remaining"] == 2
    assert outcome.calls == 2


def test_a_tool_that_raises_becomes_a_reply_the_agent_can_read():
    """An agent told its bounds matched nothing can widen them.

    An agent whose process died cannot. The loop turns the exception into a
    tool reply and keeps going.
    """
    caller = FakeCaller([
        {"action": "blow_up"},
        {"action": "stop", "value": 7},
    ])
    outcome = run_agent(
        echo_spec(), caller=caller, model_config=None,
        dispatch=dispatch_table({
            "look": echo_dispatch, "blow_up": echo_dispatch,
            "stop": echo_dispatch,
        }),
    )
    import json

    tool_messages = [
        m for m in caller.seen[-1] if m["role"] == "tool"
    ]
    first = json.loads(tool_messages[0]["content"])
    assert first["ok"] is False
    assert "matched nothing" in first["error"]
    assert outcome.calls == 2, "the loop continued after the failure"


def test_an_action_that_does_not_match_the_schema_is_reported_not_fatal():
    caller = FakeCaller([
        {"action": "not_an_action"},
        {"action": "stop"},
    ])
    outcome = run_agent(
        echo_spec(), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": echo_dispatch, "stop": echo_dispatch}),
    )
    import json

    tool_messages = [m for m in caller.seen[-1] if m["role"] == "tool"]
    first = json.loads(tool_messages[0]["content"])
    assert first["ok"] is False
    assert "did not match the schema" in first["error"]
    assert outcome.final is not None


def test_a_call_that_does_not_parse_is_recorded_as_it_arrived():
    """Otherwise the one call that ended the run is nowhere.

    The trace holds the actions the agent decided to do, which is the right
    thing to read a run by - but a run can also end because the model could
    not produce a well-formed call at all, and then the trace is silent about
    the call that mattered. Measured on D27: the meshing agent's final call
    failed to parse, and the job reported only that its budget was gone.
    """
    caller = FakeCaller([
        {"action": "look"},
        {"action": "not_an_action", "extra": 1},
    ])
    outcome = run_agent(
        echo_spec(max_calls=2), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": echo_dispatch}),
    )
    assert [(entry["call"], entry["narrowed"]) for entry in outcome.rejected] == [
        (2, False)
    ]
    assert outcome.rejected[0]["arguments"]["action"] == "not_an_action"
    assert "not_an_action" in outcome.rejected[0]["error"]


def test_a_narrowed_call_that_does_not_parse_is_marked_as_such():
    """Which schema was on the table when the model fumbled it.

    The narrowed call is validated against the full action model - a subset of
    it still fits - so a fumble there is a fumble about the arguments, and
    knowing the narrowed schema was in force is what says whether the
    mechanism meant to force a decision is what produced it.
    """
    caller = FakeCaller([
        {"action": "look"},
        {"action": "stop", "value": "not an integer"},
        {"action": "stop", "value": 1},
    ])
    outcome = run_agent(
        echo_spec(max_calls=2, terminal=True), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": echo_dispatch, "stop": echo_dispatch}),
    )
    assert outcome.rejected[0]["narrowed"] is True
    assert outcome.rejected[0]["call"] == 2
    assert outcome.final is not None
    assert outcome.exhausted is False


def test_the_decision_call_is_asked_again_until_it_decides():
    """The narrowing is a request; the loop is what enforces it.

    The provider is called with `strict=False`, so a narrowed enum does not
    stop the model returning an action outside it. Measured on D27: the
    meshing agent's last call came back as `inspect_radial_profile`, was
    dispatched like any other, and the run ended with no plan. A refusal that
    is not enforced is a suggestion.
    """
    caller = FakeCaller([
        {"action": "look"},
        {"action": "look"},
        {"action": "stop", "value": 9},
    ])
    outcome = run_agent(
        echo_spec(max_calls=2, terminal=True), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": echo_dispatch, "stop": echo_dispatch}),
    )
    assert outcome.trace[-1] == {
        "action": "stop", "value": 9, "rationale": "",
    }
    assert outcome.final is not None
    # The refused call is recorded with what was wrong with it, and it is not
    # in the trace, because the agent did not get to do it.
    assert outcome.rejected[-1]["error"].startswith("'look' is not available")
    assert [entry["action"] for entry in outcome.trace] == ["look", "stop"]


def test_a_refused_submission_is_a_reply_and_not_the_end_of_the_run():
    """A submission that was rejected is not a submission.

    The loop's whole point is that a raising handler becomes a tool reply the
    agent can read and react to. Submitting was the exception: a submit action
    that raised ended the run and its error payload was handed on as the
    `final`, which every stage reads as "the agent chose not to decide". So an
    agent that submitted one malformed field lost the run instead of losing a
    call, and the reason it lost was dropped.
    """
    refusals = {"count": 0}

    def dispatch(action, context):
        if action.action == "stop" and refusals["count"] == 0:
            refusals["count"] += 1
            raise ValueError("a submission needs a value above zero")
        return {"ok": True, "result": {"value": action.value}}

    caller = FakeCaller([
        {"action": "stop", "value": 0},
        {"action": "stop", "value": 7},
    ])
    outcome = run_agent(
        echo_spec(max_calls=4), caller=caller, model_config=None,
        dispatch=dispatch,
    )
    # The refusal came back as a reply, and the agent got its next turn.
    import json as _json

    reply = _json.loads(caller.seen[1][-1]["content"])
    assert reply["ok"] is False
    assert "above zero" in reply["error"]
    assert outcome.final == {"value": 7}
    assert outcome.calls == 2


def test_an_agent_with_no_terminal_model_stops_at_its_budget():
    """The allowance belongs to the mechanism, not to every agent."""
    caller = FakeCaller([{"action": "look"}] * 6)
    outcome = run_agent(
        echo_spec(max_calls=3), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": echo_dispatch}),
    )
    assert outcome.calls == 3
    assert outcome.exhausted


def test_the_reasks_are_bounded_so_an_agent_that_will_not_decide_still_ends():
    caller = FakeCaller([{"action": "look"}] * 20)
    outcome = run_agent(
        echo_spec(max_calls=3, terminal=True), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": echo_dispatch}),
    )
    assert outcome.exhausted
    assert outcome.calls == 3 + 3


def test_the_budget_stops_the_loop_and_says_so():
    caller = FakeCaller([{"action": "look"}] * 3)
    outcome = run_agent(
        echo_spec(max_calls=3), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": echo_dispatch}),
    )
    assert outcome.exhausted
    assert outcome.final is None
    assert outcome.calls == 3


def test_the_last_call_offers_only_the_actions_that_end_the_run():
    """The decision has to get a turn.

    Measured on D27: the face-finding agent had built the table it needed by
    call nineteen, asked the same question nine more times, and ended with no
    selection - with the faces it wanted sitting in its own transcript. A
    budget that can be spent entirely on looking is a budget that never
    reaches a decision, so the final call is narrowed to the actions that
    end the run. Which answer is right is still the agent's to choose.

    The schema, not a note: an advisory sentence in the reply is a number to
    weigh, and a number to weigh is what the looping run ignored.
    """
    caller = FakeCaller([
        {"action": "look"}, {"action": "look"}, {"action": "stop", "value": 1},
    ])
    run_agent(
        echo_spec(max_calls=3, terminal=True), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": echo_dispatch, "stop": echo_dispatch}),
    )
    offered = [entry["action"]["enum"] for entry in caller.seen_schemas]

    # Wide while there is room to explore ...
    assert sorted(offered[0]) == ["blow_up", "look", "stop"]
    assert sorted(offered[1]) == ["blow_up", "look", "stop"]
    # ... and on the last call only what ends the run.
    assert sorted(offered[2]) == ["blow_up", "stop"]


def test_a_spec_without_a_terminal_model_is_never_narrowed():
    """The mechanism is opt-in, so an agent that has not thought about its
    last call keeps the behaviour it had."""
    caller = FakeCaller([
        {"action": "look"}, {"action": "stop"},
    ])
    run_agent(
        echo_spec(max_calls=2), caller=caller, model_config=None,
        dispatch=dispatch_table({"look": echo_dispatch, "stop": echo_dispatch}),
    )
    for schema in caller.seen_schemas:
        assert sorted(schema["action"]["enum"]) == ["blow_up", "look", "stop"]


# --- the criterion, which replaced the fixed gate --------------------------


def convex_criterion() -> Criterion:
    return Criterion(
        intent="load faces",
        surface_types=["plane"],
        normal_clauses=[
            NormalClause(component="radial", maximum=-0.2),
            NormalClause(component="axial", minimum=-1e-6, maximum=1e-6),
        ],
        count=CountClause(min_count=2, even=True),
    )


def test_a_face_that_meets_every_clause_reports_no_residual():
    rows = [a_face(0), a_face(1)]
    result = criteria.check_selection(
        convex_criterion(), rows, Vec3(x=0, y=0, z=0), Vec3(x=0, y=0, z=1)
    )
    assert result["satisfied"] is True
    assert result["faces_failing_a_normal_clause"] == []


def test_a_clause_that_is_not_met_reports_the_value_beside_the_bound():
    """A near miss and a face pointing the other way are different numbers."""
    rows = [a_face(0, radial=-0.19), a_face(1, radial=+0.9)]
    result = criteria.check_selection(
        convex_criterion(), rows, Vec3(x=0, y=0, z=0), Vec3(x=0, y=0, z=1)
    )
    assert result["satisfied"] is False
    assert set(result["faces_failing_a_normal_clause"]) == {0, 1}

    near_miss = result["per_face"][0][0]
    opposite = result["per_face"][1][0]
    assert near_miss["within"] is False
    assert near_miss["value"] == pytest.approx(-0.19)
    # both fail, but by very different amounts - which is the point of
    # reporting the residual rather than a boolean
    assert near_miss["excess_fraction"] < opposite["excess_fraction"]


def test_a_surface_type_outside_the_declared_set_is_reported():
    rows = [a_face(0, surface="cylinder"), a_face(1)]
    result = criteria.check_selection(
        convex_criterion(), rows, Vec3(x=0, y=0, z=0), Vec3(x=0, y=0, z=1)
    )
    assert result["surface_types_within_declared"] is False
    assert result["surface_types_seen"] == ["cylinder", "plane"]
    assert result["satisfied"] is False


def test_an_odd_count_fails_an_even_count_clause():
    rows = [a_face(0), a_face(1), a_face(2)]
    result = criteria.check_selection(
        convex_criterion(), rows, Vec3(x=0, y=0, z=0), Vec3(x=0, y=0, z=1)
    )
    assert result["count_clause"]["satisfied"] is False
    assert result["satisfied"] is False


def test_symmetry_is_reported_and_never_refuses():
    """A set that is not closed may be exactly what the agent meant."""
    criterion = Criterion(
        intent="one flank",
        symmetry=SymmetryClause(kind="rotational_order", ref="20"),
    )
    rows = [a_face(0, theta=10.0)]
    result = criteria.check_selection(
        criterion, rows, Vec3(x=0, y=0, z=0), Vec3(x=0, y=0, z=1)
    )
    symmetry = result["symmetry"]
    assert symmetry["declared"] is True
    assert symmetry["unmatched_fraction"] == 1.0


def test_a_criterion_with_no_clauses_accepts_anything():
    """The harness has no opinion of its own about what was selected."""
    rows = [a_face(0, surface="bspline", radial=0.4, axial=0.9)]
    result = criteria.check_selection(
        Criterion(intent="whatever the agent meant"),
        rows, Vec3(x=0, y=0, z=0), Vec3(x=0, y=0, z=1),
    )
    assert result["satisfied"] is True


# --- the face-finding agent's own guards -----------------------------------


def test_submitting_without_a_criterion_is_refused():
    state = a_state([a_face(0)])
    with pytest.raises(StructuralError) as exc:
        facefind._submit_faces(
            facefind.Action(
                action="submit_faces", feature="f", solid_index=0,
                face_indices=[0],
            ),
            state,
        )
    assert exc.value.diagnostic.code == "no_criterion"
    assert "criterion" in exc.value.diagnostic.message


def test_submitting_a_face_index_that_does_not_exist_is_refused():
    state = a_state([a_face(0), a_face(1)])
    with pytest.raises(StructuralError) as exc:
        facefind._submit_faces(
            facefind.Action(
                action="submit_faces", feature="f", solid_index=0,
                face_indices=[0, 99], criterion=convex_criterion(),
            ),
            state,
        )
    assert exc.value.diagnostic.code == "face_index_out_of_range"
    assert "99" in exc.value.diagnostic.message


def test_submitting_without_naming_the_feature_is_refused():
    """A face index means nothing on its own."""
    state = a_state([a_face(0), a_face(1)])
    with pytest.raises(StructuralError) as exc:
        facefind._submit_faces(
            facefind.Action(
                action="submit_faces", feature="", solid_index=0,
                face_indices=[0, 1], criterion=convex_criterion(),
            ),
            state,
        )
    assert exc.value.diagnostic.code == "no_feature"


def test_a_submission_reports_the_measured_radius_of_what_was_chosen():
    """The number the meshing stage will read, measured where it is decided."""
    state = a_state([
        a_face(0, radius=210.0, area=50.0),
        a_face(1, radius=214.0, area=150.0),
    ])
    payload = facefind._submit_faces(
        facefind.Action(
            action="submit_faces", feature="f", solid_index=0,
            face_indices=[0, 1], criterion=convex_criterion(),
            rationale="the flanks the load enters through",
        ),
        state,
    )["result"]

    # area-weighted: the bigger face pulls the mean toward itself
    expected = (210.0 * 50.0 + 214.0 * 150.0) / 200.0
    assert payload["load_radius_mm"] == pytest.approx(expected)
    assert payload["radius_min_mm"] == pytest.approx(210.0)
    assert payload["area_mm2_total"] == pytest.approx(200.0)
    assert payload["criterion_residuals"]["satisfied"] is True


def test_a_query_that_matches_nothing_says_so_rather_than_raising():
    state = a_state([a_face(0, radius=100.0)])
    payload = facefind._query_faces(
        facefind.Action(
            action="query_faces", feature="f", solid_index=0,
            radial_min=500.0, radial_max=600.0,
        ),
        state,
    )["result"]
    assert payload["matched"] == 0
    assert "widen them" in payload["note"]


def test_the_agent_can_be_driven_end_to_end_offline():
    """The whole two-stage path, with the model replaced by a script."""
    caller = FakeCaller([
        {"action": "list_features"},
        {"action": "list_solids", "feature": "f"},
        {"action": "query_faces", "feature": "f", "solid_index": 0,
         "radial_min": 200.0},
        {"action": "check_criterion", "feature": "f", "solid_index": 0,
         "face_indices": [0, 1], "criterion": convex_criterion().model_dump()},
        {"action": "submit_faces", "feature": "f", "solid_index": 0,
         "face_indices": [0, 1], "criterion": convex_criterion().model_dump(),
         "rationale": "the two flanks"},
    ])
    state = a_state([a_face(0), a_face(1), a_face(2, radius=90.0)])
    state.session = None

    import seekflow_structural.agents.facefind as module

    original = module.geometry.features
    module.geometry.features = lambda session: [{"feature": "f"}]
    module.geometry.solids = lambda session, feature: [{"solid_index": 0}]
    try:
        outcome = run_agent(
            facefind.spec(requirement="the faces the load enters through"),
            caller=caller, model_config=None,
            dispatch=facefind.DISPATCH, context=state,
        )
    finally:
        module.geometry.features = original

    assert outcome.final is not None
    assert outcome.final["accepted"] is True
    assert outcome.final["selected_face_indices"] == [0, 1]
    assert outcome.calls == 5


def test_a_repeated_call_is_told_that_it_repeats():
    """An agent that is looping is told so, in the reply.

    Measured on the reference part: one run asked the identical question
    twenty-seven times in a row, got the identical answer each time, and used
    its whole budget without deciding. The count is a fact about the
    conversation rather than about the part, and the loop is the only thing
    that knows it - so the loop is what reports it.
    """
    import json as _json

    def dispatch(action, context):
        return {"ok": True, "result": {"value": action.value}}

    same = {"action": "look", "value": 7}
    caller = FakeCaller([same, same, same, {"action": "stop"}])
    run_agent(
        echo_spec(max_calls=6), caller=caller, model_config=None,
        dispatch=dispatch,
    )

    def last_tool_reply(call_index):
        messages = caller.seen[call_index]
        return _json.loads(messages[-1]["content"])

    # The first call is not a repeat and says nothing about repeats.
    assert "identical_to_the_previous_call" not in last_tool_reply(1)
    # The second repeats the first, so its reply says so once.
    second = last_tool_reply(2)
    assert second["identical_to_the_previous_call"] is True
    assert second["how_many_times_now"] == 2
    assert "until the arguments do" in second["note"]


def test_a_changed_argument_clears_the_repeat_count():
    import json as _json

    def dispatch(action, context):
        return {"ok": True, "result": {"value": action.value}}

    caller = FakeCaller([
        {"action": "look", "value": 7},
        {"action": "look", "value": 7},
        {"action": "look", "value": 8},
        {"action": "stop"},
    ])
    run_agent(
        echo_spec(max_calls=6), caller=caller, model_config=None,
        dispatch=dispatch,
    )
    # The call after the changed one is not a repeat of anything.
    assert "identical_to_the_previous_call" not in _json.loads(
        caller.seen[3][-1]["content"]
    )


def test_a_call_rewritten_in_different_words_is_still_the_same_call():
    """The prose is what the agent says about a call, not what it asks.

    `rationale` and `purpose` are free text the agent writes to justify
    itself. Counting them as part of the question made the repeat detector
    blind to exactly the looping it exists to catch: on D27 four consecutive
    `query_faces` calls carried identical filters under four different
    rationales, and the note never fired once.
    """
    import json as _json

    def dispatch(action, context):
        return {"ok": True, "result": {"value": action.value}}

    caller = FakeCaller([
        {"action": "look", "value": 7, "rationale": "because of the radius"},
        {"action": "look", "value": 7, "rationale": "because of the height"},
        {"action": "stop"},
    ])
    run_agent(
        echo_spec(max_calls=4), caller=caller, model_config=None,
        dispatch=dispatch,
    )
    # The reply to the second call is the last message the third call sees.
    assert _json.loads(caller.seen[2][-1]["content"])[
        "identical_to_the_previous_call"
    ] is True

class _FlakyCaller(FakeCaller):
    """A caller whose first call comes back unparseable, and whose next does not.

    The provider raises before the loop ever sees arguments, so this is a
    failure arriving one step earlier than a schema mismatch - and the loop
    used to let it end the run.
    """

    def call_strict_tool(self, **kwargs):
        if not self.seen:
            self.seen.append(kwargs["messages"])
            raise RuntimeError(
                "Tool call arguments were not valid JSON: Expecting ':' "
                "delimiter: line 1 column 2139 (char 2138)"
            )
        return super().call_strict_tool(**kwargs)


def test_a_call_the_provider_cannot_parse_costs_a_turn_not_the_run():
    """Measured on the fifth real run: the model emitted a call whose
    arguments were 2,139 characters and not valid JSON, and the whole
    revision ended with no result - the mesh, the solve and the diagnosis all
    thrown away over a stray character in the model's own output.

    Every other malformed submission is answered with a reply the model can
    act on. This is the same failure arriving earlier, and it gets the same
    treatment: a rejection in the record, and another turn.
    """
    import json as _json

    from seekflow_structural.runtime.loop import run_agent

    caller = _FlakyCaller([
        {"action": "look", "rationale": "second attempt"},
        {"action": "stop", "rationale": "done"},
    ])
    spec = AgentSpec(
        name="t", tool_name="t", tool_description="t",
        action_model=EchoAction, system_prompt="s", user_prompt="u",
        submit_actions=frozenset({"stop"}), max_calls=6,
    )
    outcome = run_agent(
        spec, caller=caller, model_config=None,
        dispatch=lambda action, context: {"ok": True, "result": action.action},
    )
    # The dispatch returns the action name as its result, so a run that
    # survived the bad call and then decided ends with "stop".
    assert outcome.final == "stop"
    assert len(outcome.rejected) == 1
    assert "not valid JSON" in outcome.rejected[0]["error"]
    # And the model is told what went wrong, in the transcript it is given
    # next - otherwise it has no way to know the call was never run.
    transcript = _json.dumps(caller.seen, ensure_ascii=False)
    assert "could not be read" in transcript


def test_repeated_queries_force_the_agent_to_decide():
    import json as _json

    dispatched: list[int] = []

    def dispatch(action, context):
        if action.action == "look":
            dispatched.append(action.value)
        return {"ok": True, "result": action.action}

    same = {"action": "look", "value": 7}
    caller = FakeCaller([
        same, same, same,
        {"action": "look", "value": 8},
        {"action": "stop"},
    ])
    outcome = run_agent(
        echo_spec(max_calls=10, terminal=True), caller=caller,
        model_config=None, dispatch=dispatch,
    )

    assert dispatched == [7, 7]
    assert outcome.final == "stop"
    transcript = _json.dumps(caller.seen, ensure_ascii=False)
    assert "must_decide_now" in transcript
    assert "look" not in caller.seen_schemas[3]["action"]["enum"]


def test_an_identical_call_is_refused_after_two_prior_answers():
    """A deterministic tool must not be allowed to consume the budget."""
    import json as _json

    dispatched: list[int] = []

    def dispatch(action, context):
        if action.action == "look":
            dispatched.append(action.value)
        return {"ok": True, "result": action.action}

    same = {"action": "look", "value": 7}
    caller = FakeCaller([same, same, same, {"action": "stop"}])
    outcome = run_agent(
        echo_spec(max_calls=6), caller=caller, model_config=None,
        dispatch=dispatch,
    )

    assert dispatched == [7, 7]
    assert outcome.final == "stop"
    reply = _json.loads(caller.seen[3][-1]["content"])
    assert reply["error_code"] == "duplicate_call_refused"
    assert reply["identical_to_the_previous_call"] is True
    assert outcome.rejected[-1]["error"].startswith("this call has the same")
