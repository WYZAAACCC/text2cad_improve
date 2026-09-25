"""The tool loop every agent runs, written once.

Six standalone scripts each carried their own copy of this: build the request,
read the tool call, validate it against a pydantic action model, run it, feed
the result back, count the calls, stop on a submit. The duplicated part was
about 130 lines per file and identical in all six; what differed was the action
enum and what each action does, which is the part worth keeping.

The loop is deliberately thin. It owns the transcript, the budget and the
trace, and nothing else: every decision about what the actions mean lives in
the dispatch the agent supplies.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict, model_validator

from seekflow_engineering_tools.generative_cad.llm.provider import LlmToolCaller

from seekflow_structural.errors import STATUS_FAILED, StructuralError


class ToolAction(BaseModel):
    """An action an agent can take, with `null` read as "not stated".

    The provider is given a schema in its strict subset, which requires every
    property to be present. A model that has nothing to put in `regions` or
    `questions` therefore has to write something, and what it writes is
    `null` - measured on D27, where the meshing agent's `get_geometry` came
    back as `{"regions": null, "questions": null}` and was rejected outright,
    costing the call and telling the agent only that its arguments were
    malformed.

    Dropping the nulls lets each field's own default apply, which is what the
    model meant by them. A field with no default still fails, and that is
    right: a region that does not say how big its elements should be is not a
    region.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _null_means_unset(cls, data):
        if isinstance(data, dict):
            return {key: value for key, value in data.items()
                    if value is not None}
        return data


@dataclass(frozen=True)
class AgentSpec:
    """Everything that varies between one agent and the next."""

    name: str
    tool_name: str
    tool_description: str
    action_model: type[BaseModel]
    system_prompt: str
    user_prompt: str
    # Actions that end the conversation. `needs_input` is one of them: an
    # agent that cannot proceed must be able to say so, and that answer is as
    # final as a submission.
    submit_actions: frozenset[str]
    max_calls: int = 8
    timeout_s: int = 180
    # The action model for the last call, offering only the actions that end
    # the conversation. Without it a budget is spent entirely on looking and
    # the decision never gets a turn - measured on D27, where the agent had
    # every measurement it needed at call nineteen and then asked the same
    # question nine more times until the budget ran out. What this does not do
    # is say which answer is right: the agent still chooses, and `needs_input`
    # stays available.
    terminal_model: type[BaseModel] | None = None


@dataclass
class AgentOutcome:
    final: dict | None
    trace: list[dict] = field(default_factory=list)
    calls: int = 0
    exhausted: bool = False
    last_signature: str = ""
    repeats: int = 0
    # Calls whose arguments did not match the action model, kept as they
    # arrived. The trace holds what the agent decided to do, which is the
    # right thing to read a run by - but when a run ends because the model
    # could not produce a well-formed call, the trace is silent about the one
    # call that mattered, and the job records it nowhere. That happened on
    # D27: the meshing agent's last call failed to parse and the run reported
    # only that its budget was gone.
    rejected: list[dict] = field(default_factory=list)

    def last_rationale(self) -> str:
        for entry in reversed(self.trace):
            rationale = entry.get("rationale")
            if rationale:
                return str(rationale)
        return ""


# A dispatch takes the validated action and returns the payload to show the
# model. Raising inside it is fine and expected: the loop turns the exception
# into a tool reply the agent can read and react to, rather than killing the
# run. An agent that is told its zone is out of bounds can correct it; an agent
# whose process died cannot.
Dispatch = Callable[[BaseModel, Any], dict]

# How many times the decision call may be asked again when the model answers
# with an action that is not one of the ways to end the run. Three is enough
# for a model that is confused about which schema is in front of it and small
# enough that an agent determined to keep exploring still ends.
TERMINAL_REASKS = 3

# A repeated measurement cannot have a new answer. The model gets one
# repeated answer because the provider may have omitted or garbled the
# first reply in its own transcript; after that the call is refused rather
# than executed again. Measured on D27: feedback made ten identical
# query_nodes calls and mesh made ten identical inspect_radial_profile
# calls, spending most of their budgets on answers they already had.
MAX_IDENTICAL_REPEATS = 2


def assistant_message(result) -> dict:
    """The assistant turn the protocol requires before a tool reply.

    The shared caller now returns the call id and any text the model produced
    alongside the call, so the transcript is reconstructed from what was
    actually said rather than from a guess.
    """
    call_id = result.tool_call_id or f"call_{result.tool_name}"
    return {
        "role": "assistant",
        "content": result.assistant_content or "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": result.tool_name,
                    "arguments": json.dumps(result.arguments, ensure_ascii=False),
                },
            }
        ],
    }


def run_agent(
    spec: AgentSpec,
    *,
    caller: LlmToolCaller,
    model_config,
    dispatch: Dispatch,
    context: Any = None,
    messages: list[dict] | None = None,
) -> AgentOutcome:
    """Run the loop until an action ends it or the budget runs out."""
    conversation = list(messages) if messages else [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": spec.user_prompt},
    ]

    outcome = AgentOutcome(final=None)
    # The last call offers only the actions that end the run, and this is how
    # many times it may be asked again if the model answers with something
    # else. The narrowing is a request: the provider is called with
    # `strict=False`, so nothing stops the model returning an action outside
    # the narrowed enum, and on D27 it did - the meshing agent's final call
    # came back as `inspect_radial_profile`, was dispatched like any other,
    # and the run ended with no plan after twelve calls of looking. A refusal
    # that is not enforced is a suggestion, so the loop enforces it.
    reasks = TERMINAL_REASKS if spec.terminal_model is not None else 0
    force_terminal = False
    while outcome.calls < spec.max_calls + reasks:
        remaining = spec.max_calls - outcome.calls
        narrowed = (
            force_terminal
            or (remaining <= 1 and spec.terminal_model is not None)
        )
        schema_model = spec.terminal_model if narrowed else spec.action_model
        try:
            result = caller.call_strict_tool(
                messages=conversation,
                tool_name=spec.tool_name,
                tool_description=spec.tool_description,
                tool_schema=schema_model.model_json_schema(),
                model_config=model_config,
            )
        except Exception as exc:
            # A call the provider could not parse is a call the agent can
            # still make again. Every other malformed submission is already
            # answered with a tool reply the model can react to - a schema
            # mismatch is caught below and costs a turn, not the run - and a
            # malformed JSON body is the same kind of failure arriving one
            # step earlier.
            #
            # Measured on the fifth real run: the model emitted a call whose
            # arguments were 2,139 characters and not valid JSON, and the
            # whole revision ended with no result at all - the solve, the
            # mesh and the diagnosis were all thrown away over a stray
            # character in the model's own output.
            outcome.calls += 1
            outcome.rejected.append({
                "call": outcome.calls,
                "narrowed": narrowed,
                "arguments": None,
                "error": f"{type(exc).__name__}: {exc}",
            })
            conversation.append({
                "role": "user",
                "content": (
                    f"That call could not be read: {exc}\n\n"
                    "The arguments have to be one valid JSON object matching "
                    "the schema. Nothing was run. Send it again, and if it is "
                    "long, send it shorter - a call that is too large to "
                    "serialise reliably is one worth splitting or trimming."
                ),
            })
            continue
        outcome.calls += 1

        try:
            action = spec.action_model.model_validate(result.arguments)
        except Exception as exc:
            outcome.rejected.append({
                "call": outcome.calls,
                "narrowed": narrowed,
                "arguments": result.arguments,
                "error": str(exc),
            })
            payload = {
                "ok": False,
                "error": f"the action did not match the schema: {exc}",
            }
            conversation.append(assistant_message(result))
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id
                    or f"call_{spec.tool_name}",
                    "content": json.dumps(payload, ensure_ascii=False),
                }
            )
            continue

        if narrowed and action.action not in spec.submit_actions:
            # The decision call, answered with something that is not a
            # decision. It is not dispatched, because dispatching it is what
            # lets a run spend its last call looking - and the reply says why,
            # so the next attempt has something to act on.
            outcome.rejected.append({
                "call": outcome.calls,
                "narrowed": True,
                "arguments": result.arguments,
                "error": (
                    f"{action.action!r} is not available on the last call. "
                    "Only "
                    + " or ".join(sorted(spec.submit_actions))
                    + " end the run."
                ),
            })
            conversation.append(assistant_message(result))
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id
                    or f"call_{spec.tool_name}",
                    "content": json.dumps({
                        "ok": False,
                        "error_code": "must_decide_now",
                        "error": (
                            "there is no budget left to explore with. The "
                            "only actions available now are "
                            + " and ".join(sorted(spec.submit_actions))
                            + ". Submit what you have, or say what you need."
                        ),
                    }, ensure_ascii=False),
                }
            )
            continue

        entry = action.model_dump(mode="json")
        outcome.trace.append(entry)

        # Whether this exact call has been made before, and how many times.
        # An agent has the transcript and could work this out, and one that is
        # looping demonstrably is not doing so - measured on the reference
        # part, one run asked the identical question twenty-seven times in a
        # row, got the identical answer each time, and used its whole budget.
        # The count is a fact about the conversation rather than about the
        # part, which is why it is the loop that reports it.
        #
        # The prose is left out of the signature. `rationale` and `purpose`
        # are what the agent says about a call, not what it asks: two calls
        # that differ only in their justification are one question asked
        # twice, and counting them as two hid exactly the repetition this
        # exists to catch. Measured on D27, where four consecutive
        # `query_faces` calls carried identical filters and four different
        # rationales, and the note never fired.
        signature = json.dumps(
            {k: v for k, v in entry.items()
             if k not in ("rationale", "purpose")},
            sort_keys=True,
        )
        outcome.repeats = (
            outcome.repeats + 1 if signature == outcome.last_signature else 0
        )
        outcome.last_signature = signature

        # A repeated call is not a new measurement. The first repeat gets the
        # answer again and a note; after MAX_IDENTICAL_REPEATS it is refused
        # without touching the dispatch. The call still costs a turn, so an
        # agent that ignores the signal cannot spend the rest of its budget
        # re-running the same deterministic question.
        if outcome.repeats >= MAX_IDENTICAL_REPEATS:
            # The agent has already been told this answer cannot change. Give
            # it one final chance to decide from the evidence it has instead
            # of letting repeated queries consume the rest of the budget.
            force_terminal = spec.terminal_model is not None
            error = (
                "this call has the same arguments as one you have already "
                "made twice. Its answer cannot change until the arguments "
                "do, so it was not run again. Change what you are measuring, "
                "or submit the decision the evidence already supports."
            )
            outcome.rejected.append({
                "call": outcome.calls,
                "narrowed": narrowed,
                "arguments": result.arguments,
                "error": error,
            })
            payload = {
                "ok": False,
                "error_code": "duplicate_call_refused",
                "error": error,
                "calls_used": outcome.calls,
                "calls_remaining": spec.max_calls - outcome.calls,
                "identical_to_the_previous_call": True,
                "how_many_times_now": outcome.repeats + 1,
            }
            conversation.append(assistant_message(result))
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id
                    or f"call_{spec.tool_name}",
                    "content": json.dumps(payload, ensure_ascii=False),
                }
            )
            continue

        # Whether the call actually did anything, as opposed to being refused.
        # The difference decides whether a submission counts as one: see the
        # submit check below.
        answered = True
        try:
            payload = dispatch(action, context)
            if not isinstance(payload, dict):
                payload = {"ok": True, "result": payload}
        except Exception as exc:
            answered = False
            payload = {"ok": False, "error": str(exc)}
            # The code travels with the message. "no_faces" and
            # "filters_match_nothing" are both refusals, and they call for
            # opposite next actions - state a set at all, or widen the bounds
            # that described none. Handed one flat sentence, an agent can only
            # guess which it is, and the detail is already computed here.
            diagnostic = getattr(exc, "diagnostic", None)
            if diagnostic is not None:
                payload["error_code"] = diagnostic.code

        # The remaining budget travels with every reply. Measurement is
        # open-ended by nature - there is always one more period to rule out,
        # one more zone to try - so the constraint has to be visible while the
        # agent is deciding what to spend the next call on, not only when it
        # has run out.
        payload["calls_used"] = outcome.calls
        payload["calls_remaining"] = spec.max_calls - outcome.calls

        if outcome.repeats:
            payload["identical_to_the_previous_call"] = True
            payload["how_many_times_now"] = outcome.repeats + 1
            payload["note"] = (
                "these are exactly the arguments of the previous call, so "
                "this answer is the one you already have. Nothing changes "
                "until the arguments do: change a filter, ask a different "
                "question, or act on what you have."
            )

        conversation.append(assistant_message(result))
        conversation.append(
            {
                "role": "tool",
                "tool_call_id": result.tool_call_id or f"call_{spec.tool_name}",
                "content": json.dumps(payload, ensure_ascii=False),
            }
        )

        # A submission that was refused is not a submission. It ends the run
        # only if the handler accepted it, so an agent whose submission is
        # rejected - a criterion it forgot, a section it left out - gets the
        # refusal as a reply and another turn to fix it. Without this the
        # refusal was returned as the run's `final`, which reads downstream as
        # "the agent decided not to decide" rather than "the agent's decision
        # was malformed", and the reason was dropped on the floor.
        if answered and action.action in spec.submit_actions:
            outcome.final = payload.get("result") or payload
            return outcome

    outcome.exhausted = True
    outcome.final = None
    return outcome


def exhausted_final(agent: str) -> dict:
    """What a run reports when the agent never decided.

    Deliberately not a guess dressed as an answer: the caller has to handle
    `accepted: False`, and the reason names the budget so it is clear the
    agent was cut off rather than unable.
    """
    return {
        "accepted": False,
        "reason": "tool_call_budget_exhausted",
        "questions": [
            f"the {agent} agent used its whole tool-call budget without "
            "reaching a decision"
        ],
    }


def require(condition: bool, message: str) -> None:
    """Raise the error the loop will hand back to the agent as a tool reply."""
    if not condition:
        raise StructuralError(
            "invalid_action", message, "agent", status=STATUS_FAILED
        )


def dispatch_table(mapping: Mapping[str, Dispatch]) -> Dispatch:
    """Turn a name-to-function map into the single dispatch the loop wants."""

    def dispatch(action, context):
        handler = mapping.get(action.action)
        if handler is None:
            raise StructuralError(
                "unknown_action",
                f"{action.action!r} is not an action this agent has",
                "agent",
            )
        return handler(action, context)

    return dispatch
