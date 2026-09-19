"""Applying a revision's findings to that revision's copy of the generator.

The feedback agent says what should change and why. This one does it, and the
separation is the point: a stage that both diagnosed a part and rebuilt it
would leave no record of which measurement asked for which edit, and the record
is what the loop learns from.

What it writes to is the revision's own workspace - a copy of the parametric
templates and the CAD document the previous revision produced. The document is
the design, and a change is made to it; the master templates are never opened
for writing, and the workspace's guard is checked after every write rather than
at the end, so a run that reached back into the master fails at the step that
did it.

Three things it will not do, and all three are refusals rather than warnings.

It will not apply a change to anything other than the design the next revision
will be built from. Once a revision has a document, the generator reads that
document and never calls the template layer - so a change written under a
template name, or a replacement of a template copy, reaches nothing. It would
be recorded as an applied change, pass every other check, and leave the next
revision to be built, meshed and solved as the previous geometry, with the
result scored as a test of a change that was never made. This is the failure
the guards below exist for and the one that is hardest to see, because unlike
them it produces a revision that runs and numbers that look like an answer.

It will not apply a change larger than the repair kernel's own budget. The
kernel would refuse it downstream, and a loop that builds a whole revision on
top of a change that will be refused has spent a solve to learn nothing.

It will not accept a finding reported as carried out with no change behind it.
A revision built from an unchanged design produces the same numbers as the one
before it, and the difference between them - zero, or noise - would be written
into the knowledge base as evidence about the finding.

What it does do with a finding it cannot apply is record it. A finding skipped
for a stated reason is a fact about the loop - the same finding arriving next
revision says the diagnosis and the design disagree about what is changeable,
and that is worth being able to see.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.orchestrator import RunContext
from seekflow_structural.runtime.loop import (
    AgentSpec,
    ToolAction,
    dispatch_table,
    exhausted_final,
    run_agent,
)
from seekflow_structural.tools import (
    design_variables,
    document as document_tools,
    knowledge,
    workspace,
)


class Action(ToolAction):
    """The revision agent's tool call."""

    action: Literal[
        "get_findings",
        "get_rules",
        "read_design",
        "read_script",
        "check_change",
        "set_parameter",
        "write_script",
        "submit_revision",
        "needs_input",
    ]

    finding_id: str = Field(
        default="",
        description=(
            "which finding this change is for, e.g. 'F1'. set_parameter and "
            "write_script record it, and submit_revision checks that every "
            "finding reported as applied has one - a finding claimed as "
            "carried out with no change behind it is one that was not."
        ),
    )
    parameter: str = Field(
        default="",
        description=(
            "the design variable to change, by the name the generation side "
            "uses. set_parameter and check_change both take it."
        ),
    )
    value: float | None = Field(
        default=None,
        description=(
            "the value to set that variable to. Give this or "
            "relative_change, not both."
        ),
    )
    relative_change: float | None = Field(
        default=None,
        description=(
            "how far to move the variable, as a fraction of what it is now - "
            "0.15 is fifteen per cent larger, -0.1 is ten per cent smaller. "
            "The current value is read from the design, so a finding that "
            "gives only a percentage is carried out without working the "
            "arithmetic out here."
        ),
    )
    script: str = Field(
        default="",
        description=(
            "which file in the revision's scripts/ directory to read or "
            "replace, e.g. param_templates.py"
        ),
    )
    content: str = Field(
        default="",
        description="the full new text of that script, for write_script",
    )
    applied: list[str] = Field(
        default_factory=list,
        description="the ids of the findings you carried out",
    )
    skipped: list[dict] = Field(
        default_factory=list,
        description=(
            "findings you could not carry out, each as {id, reason}. A "
            "finding left out with no reason reads as one you did not notice."
        ),
    )
    rationale: str = ""
    questions: list[str] = Field(default_factory=list)


@dataclass
class ReviseState:
    """What the tools share: the findings, the rules, the workspace."""

    workspace: workspace.Workspace
    findings: list[dict]
    base: knowledge.KnowledgeBase
    applied: list[dict] = dataclasses.field(default_factory=list)
    skipped: list[dict] = dataclasses.field(default_factory=list)
    checks: list[dict] = dataclasses.field(default_factory=list)
    submitted: dict | None = None

    def finding(self, finding_id: str) -> dict | None:
        return next(
            (item for item in self.findings if str(item.get("id")) == finding_id),
            None,
        )


# --- reading -------------------------------------------------------------


def _get_findings(action, state: ReviseState) -> dict:
    """What the last revision's results said, and what was asked for."""
    return {
        "ok": True,
        "result": {
            "lineage": state.workspace.lineage,
            "revision": state.workspace.revision,
            "findings": state.findings,
        },
    }


def _get_rules(action, state: ReviseState) -> dict:
    """The recorded rules for the mechanisms in these findings.

    Two lists, because they answer two different questions. `rules` is what
    the loop currently believes, trusted first - that is advice. `retired` is
    what it tried and had to stop believing, with the observations behind the
    failure - that is a warning, and it is not advice.

    A retired rule used to be dropped from the reply entirely, which left the
    agent with no way to know a change had already been made and had not
    worked. The record was kept and nobody could read it, so the same change
    could be proposed, applied, built and solved again while the one thing
    that would have prevented it sat in a file the agent was never shown.
    """
    wanted: list[str] = []
    for finding in state.findings:
        mechanism = str(finding.get("mechanism") or "")
        if mechanism and mechanism not in wanted:
            wanted.append(mechanism)

    def shape(entry) -> dict:
        return {
            "id": entry.id,
            "status": entry.status,
            "parameter": entry.parameter,
            "direction": entry.direction,
            "expected_direction": entry.expected_direction,
            "at": entry.at,
            "confirmations": entry.confirmations,
            "refutations": entry.refutations,
            "note": entry.note,
        }

    rules: dict[str, list[dict]] = {}
    retired: dict[str, list[dict]] = {}
    for mechanism in wanted:
        entries = state.base.for_mechanism(mechanism, include_refuted=True)
        rules[mechanism] = [
            shape(entry) for entry in entries if entry.status != "refuted"
        ]
        failed = [entry for entry in entries if entry.status == "refuted"]
        if failed:
            retired[mechanism] = [
                {
                    **shape(entry),
                    "observations": [
                        {
                            "revision": observation.revision,
                            "outcome": observation.outcome,
                            "predicted_relative_change": (
                                observation.predicted_relative_change
                            ),
                            "measured_relative_change": (
                                observation.measured_relative_change
                            ),
                            "side_effects": observation.side_effects,
                            "note": observation.note,
                        }
                        for observation in entry.observations
                    ],
                }
                for entry in failed
            ]
    return {
        "ok": True,
        "result": {
            "rules_by_mechanism": rules,
            "retired_by_mechanism": retired,
            "note": (
                "`rules` is what the loop believes and is advice. A rule under "
                "`retired` names a change that was already made and did not do "
                "what it was for - the observations say how it failed. Making "
                "that change again is not forbidden, but it is not a new idea: "
                "if you apply it, say in your rationale what is different this "
                "time, because the loop will record the result against the same "
                "rule and two failures retire it. A rule still in `rules` can "
                "carry a `refutations` count too, and that is the same warning "
                "one failure short of retirement: it names a change that has "
                "been tried and did not work. Weigh it before you repeat it."
            ),
        },
    }


def _read_design(action, state: ReviseState) -> dict:
    """The design, which is the CAD document.

    `params.json` is how this revision was asked for; the document is what it
    is. The distinction matters to what a change can name: the template
    parameters are about a dozen scalar dimensions, and the document holds
    every scalar of every operation - thirty-one of them on D27, including
    seven `fillet_sketch` radii on the fir-tree cutter that no template
    parameter names.
    """
    document = state.workspace.document()
    out: dict = {
        "scripts": sorted(
            path.name for path in state.workspace.scripts.glob("*.py")
        ),
        "changed_from_master": state.workspace.changed_files(),
        "template_params": state.workspace.params(),
    }
    if document is None:
        out["document"] = None
        out["limits"] = [
            "this revision has no document.json yet, so only a template "
            "parameter can be changed. It is written when the revision is "
            "first generated."
        ]
        return {"ok": True, "result": out}
    table = document_tools.editable(document)
    out["document"] = {
        "summary": document_tools.summary(document),
        "editable_count": len(table),
        "editable": table,
    }
    # The one thing a reader has to get right about this revision, said where
    # the two vocabularies are both on screen and look equally usable.
    out["note"] = (
        "This revision is built from `document.json`, and `editable` above is "
        "the whole of what a change may name - an operation parameter or a "
        "profile vertex, as `<node_id>.<param>` or "
        "`<node_id>.points[<i>].<x_mm|y_mm>`. The `template_params` below are "
        "how the first revision was asked for and are not read for this one: "
        "the generator calls the template layer only for a revision that has "
        "no document. A change named after a template parameter is refused."
    )
    return {"ok": True, "result": out}


def _read_script(action, state: ReviseState) -> dict:
    if not action.script:
        raise StructuralError(
            "no_script", "read_script needs the name of a script to read",
            "revise",
        )
    path = state.workspace.scripts / action.script
    if not path.is_file():
        raise StructuralError(
            "unknown_script",
            f"{action.script!r} is not in this revision's scripts/ directory. "
            "Available: " + ", ".join(
                sorted(p.name for p in state.workspace.scripts.glob("*.py"))
            ),
            "revise",
        )
    return {"ok": True, "result": {"script": action.script,
                                   "content": path.read_text(encoding="utf-8")}}


# --- changing ------------------------------------------------------------


def check_change(
    parameter: str, value: float | None, current: dict,
    base: knowledge.KnowledgeBase, document: dict | None = None,
) -> list[dict]:
    """What the harness can measure about one proposed change.

    The same three questions the feedback stage asks of a finding, asked again
    at the point where the change would actually be written - because the
    finding was written by one agent and this is another, and the second one
    is the one holding the file.
    """
    out: list[dict] = []

    # A model parameter - `<node_id>.<param>` - is checked against the
    # document, which is the layer a change is actually made on. The template
    # parameters are checked against the vocabulary below. Getting the order
    # wrong is what refused the fir-tree fillet change on the fourth run.
    resolved = (
        document_tools.resolve(document, parameter)
        if document is not None and parameter else None
    )
    if resolved is not None and document is not None:
        entry = document_tools.editable(document)[parameter]
        before = entry["current_value"]
        relative = None
        if value is not None and abs(float(before)) > 1e-12:
            relative = (float(value) - float(before)) / abs(float(before))
        ok = relative is None or abs(relative) <= design_variables.MAX_RELATIVE_CHANGE
        out.append({
            "check": "parameter", "ok": True,
            "note": (
                f"{parameter} is a parameter of the {entry['op']} operation "
                f"{entry['node']!r}; it is {before} now. Whether a value is "
                "geometrically possible is the kernel's answer, given when the "
                "document is built"
            ),
        })
        if value is None:
            out.append({"check": "value", "ok": False,
                        "note": "no value was given"})
        else:
            out.append({
                "check": "magnitude", "ok": ok,
                "relative_change": round(relative, 6) if relative is not None else None,
                "note": (
                    f"{parameter}: {before} -> {value}"
                    + (f" is {relative:+.2%}" if relative is not None else "")
                    + ("" if ok else
                       f", more than the "
                       f"{design_variables.MAX_RELATIVE_CHANGE:.0%} the repair "
                       "kernel takes in one step")
                ),
            })
        return out

    # A document exists and the name is not in it. From here on the template
    # vocabulary is dead, and offering it is offering a change that cannot
    # land.
    #
    # What the generator builds a revision from is `document.json`, once the
    # revision has one; `param_templates.build` is called only for a revision
    # that has none. So a value written under a template name goes into
    # `params.json`, which nothing reads, and the revision that follows is the
    # previous geometry again. The guards at `_submit_revision` do not catch
    # it, because there *is* a change recorded - it is recorded against a file
    # the generator never opens.
    #
    # Measured on D27's document: all 18 of the variables this harness
    # otherwise offers as free are absent from it. Not one of them is a change
    # the generator would read, so this is the whole of that vocabulary rather
    # than an edge case in it.
    if document is not None:
        out.append({
            "check": "parameter", "ok": False,
            "note": (
                f"{parameter!r} is not an operation parameter of this "
                "revision's document. This revision is built from "
                "`document.json`, and the template layer is called only for a "
                "revision that has no document yet - so a value written under "
                "that name reaches `params.json`, which nothing reads, and the "
                "next revision would be built from the geometry you already "
                "have while the record said it had been changed. Name an "
                "operation parameter instead: `read_design` lists every one of "
                "them with the radius it acts at. If the finding has no handle "
                "on this revision, put it in `skipped` with that as the reason."
            ),
        })
        return out

    kind = design_variables.kind(parameter)
    if kind is None:
        out.append({
            "check": "parameter", "ok": False,
            "note": (
                f"{parameter!r} is not a variable the generation side takes. "
                "The free ones are: "
                + ", ".join(design_variables.free_variables())
            ),
        })
    elif kind == "derived":
        out.append({
            "check": "parameter", "ok": False,
            "note": (
                f"{parameter!r} is computed by the generator from other "
                "variables, so a value written here is recomputed away. "
                "Change the variable it is derived from instead."
            ),
        })
    elif kind == "categorical":
        out.append({
            "check": "parameter", "ok": False,
            "note": (
                f"{parameter!r} selects between named alternatives and does "
                "not take a magnitude."
            ),
        })
    elif kind == "not_in_template":
        out.append({
            "check": "parameter", "ok": False,
            "note": (
                f"{parameter!r} is real in the authoring vocabulary and this "
                "generator has no control for it. Skip the finding and say so "
                "- the diagnosis may be right and there is nothing here to "
                "carry it out with."
            ),
        })
    else:
        translated = design_variables.template_name(parameter)
        out.append({
            "check": "parameter", "ok": True,
            "note": (
                f"{parameter} is free; the template layer calls it "
                f"{translated}" if translated else
                f"{parameter} is free, and the template layer has no "
                "counterpart for it under another name"
            ),
        })

    if value is None:
        out.append({
            "check": "value", "ok": False, "note": "no value was given",
        })
        return out

    # The finding speaks the planning agent's vocabulary and the design holds
    # the template's. Reading the current value under the wrong one finds
    # nothing, and finding nothing used to mean "it will be added" - so a
    # change to `rim_half_thickness_mm` passed every check, was written as a
    # key `param_templates.build` does not read, and changed the design by
    # nothing at all while reporting success.
    translated = design_variables.template_name(parameter)
    key = translated or parameter
    before = current.get(key)
    if before is None:
        out.append({
            "check": "current_value", "ok": True,
            "note": (
                f"this revision's design does not carry {parameter}, so there "
                "is no relative change to measure. It will be added."
            ),
        })
        return out
    try:
        before_number = float(before)
    except (TypeError, ValueError):
        out.append({
            "check": "current_value", "ok": False,
            "note": f"the current value of {parameter} is not a number",
        })
        return out
    if abs(before_number) < 1e-12:
        out.append({
            "check": "magnitude", "ok": False,
            "note": f"{parameter} is currently {before_number}, so a relative "
                    "change from it is not defined",
        })
        return out

    relative = (float(value) - before_number) / abs(before_number)
    ok = abs(relative) <= design_variables.MAX_RELATIVE_CHANGE
    out.append({
        "check": "magnitude", "ok": ok,
        "relative_change": round(relative, 6),
        "note": (
            f"{key}: {before_number} -> {value} is {relative:+.2%}"
            + (f" (asked for as {parameter})" if translated else "")
            + (
                ""
                if ok else
                f", more than the {design_variables.MAX_RELATIVE_CHANGE:.0%} "
                "the repair kernel takes in one step. It would be refused "
                "downstream; split it across revisions or say why this step "
                "is the one that matters."
            )
        ),
    })
    return out


def _check_change(action, state: ReviseState) -> dict:
    if not action.parameter:
        raise StructuralError(
            "no_parameter", "check_change needs a parameter to check", "revise"
        )
    checks = check_change(
        action.parameter, _resolve_value(action, state.workspace.params()),
        state.workspace.params(), state.base,
        document=state.workspace.document(),
    )
    state.checks.append({"parameter": action.parameter, "checks": checks})
    return {
        "ok": True,
        "result": {"checks": checks,
                   "would_be_applied": all(item["ok"] for item in checks)},
    }


def _resolve_value(action, current: dict) -> float | None:
    """The value to write, from a value or from a fraction of the current one.

    A finding states how far to move a variable far more often than it states
    what to move it to, and the arithmetic is not the agent's to do: the
    current value is in the design, and a model multiplying it by 1.15 is a
    model that can be wrong by a factor of ten without anything noticing.
    """
    if action.value is not None:
        return float(action.value)
    if action.relative_change is None:
        return None
    key = design_variables.template_name(action.parameter) or action.parameter
    before = current.get(key)
    if before is None:
        return None
    try:
        return float(before) * (1.0 + float(action.relative_change))
    except (TypeError, ValueError):
        return None


def _set_parameter(action, state: ReviseState) -> dict:
    """Change one variable of this revision's design.

    Refused outright rather than applied-with-a-warning when the checks fail,
    because a change that will not survive the generator is not a change - and
    one that is written anyway looks, in the record, exactly like one that
    works.
    """
    if not action.parameter:
        raise StructuralError(
            "no_parameter", "set_parameter needs a parameter to set", "revise"
        )
    value = _resolve_value(action, state.workspace.params())
    if value is None:
        raise StructuralError(
            "no_value",
            f"nothing was given to set {action.parameter} to. Give a value, "
            "or a relative_change to move the current one by - and if the "
            "design does not carry the variable yet, only a value will do, "
            "because there is nothing to take a fraction of.",
            "revise",
        )
    checks = check_change(
        action.parameter, value, state.workspace.params(), state.base,
        document=state.workspace.document(),
    )
    failed = [item for item in checks if not item["ok"]]
    if failed:
        raise StructuralError(
            "change_refused",
            f"{action.parameter} was not changed: "
            + " ".join(item["note"] for item in failed),
            "revise",
        )
    # Two layers, and which one is written to depends on whether there is a
    # document. A document parameter edits the document - the thing with the
    # geometry in it, and the only thing the generator reads for this revision.
    # A template parameter edits `params.json`, which is how the *first*
    # revision was asked for and which nothing reads once a document exists;
    # `check_change` has already refused that case, so the branch below is
    # reached only by a revision that has no document yet.
    document = state.workspace.document()
    resolved = (
        document_tools.resolve(document, action.parameter)
        if document is not None and action.parameter else None
    )
    if resolved is not None and document is not None:
        node_id, param = resolved
        before = document_tools.editable(document)[action.parameter][
            "current_value"
        ]
        patch = document_tools.set_scalar(document, node_id, param, value)
        state.workspace.write_document(document)
        key = action.parameter
    else:
        # Written under the template's name, which is the one `generate.py`
        # passes to `param_templates.build`. Writing the planning agent's name
        # instead would put a key into the design that the generator never
        # reads.
        key = design_variables.template_name(action.parameter) or action.parameter
        before = state.workspace.params().get(key)
        patch = {"path": f"/params/{key}", "old_value": before,
                 "new_value": value}
        state.workspace.set(key, value)
    state.workspace.verify_master_untouched()
    state.applied.append({
        "finding": action.finding_id,
        "parameter": key, "asked_for_as": action.parameter,
        "before": before, "after": value,
        "patch": patch,
    })
    return {
        "ok": True,
        "result": {
            "parameter": key, "asked_for_as": action.parameter,
            "before": before, "after": value, "checks": checks,
        },
    }


def _write_script(action, state: ReviseState) -> dict:
    """Replace one of this revision's copies of the templates.

    For a change that is not a value - a different transition curve, a
    different fillet rule. The copy is the revision's to change; the master is
    checked immediately afterwards, so a path that escaped the workspace fails
    here rather than changing what every later revision is built from.
    """
    if not action.script or not action.content:
        raise StructuralError(
            "incomplete_write",
            "write_script needs both the script name and its full new text",
            "revise",
        )
    # A script copy is how a change that is not a value is made - while the
    # revision is built by the template layer. Once a revision has a document,
    # the driver reads that document and never calls `param_templates.build`,
    # so replacing the copy changes nothing about what is built. Recorded as an
    # applied change, it would look exactly like one that worked.
    if state.workspace.document() is not None:
        raise StructuralError(
            "script_does_not_reach_the_design",
            f"{action.script} was not replaced: this revision is built from "
            "`document.json`, and the template layer is not called for a "
            "revision that has one. A change to the copy would not reach the "
            "geometry, and the revision would report a change it had not made. "
            "Change an operation parameter of the document instead, or skip "
            "the finding and say why.",
            "revise",
        )
    path = state.workspace.scripts / action.script
    if not path.is_file():
        raise StructuralError(
            "unknown_script",
            f"{action.script!r} is not in this revision's scripts/ directory; "
            "write_script replaces a copy rather than adding a file",
            "revise",
        )
    state.workspace.verify_copy_is_master() if not state.applied else None
    path.write_text(action.content, encoding="utf-8")
    state.workspace.verify_master_untouched()
    state.applied.append({
        "finding": action.finding_id,
        "script": action.script, "bytes": len(action.content),
    })
    return {
        "ok": True,
        "result": {
            "script": action.script,
            "changed_from_master": state.workspace.changed_files(),
            "master_untouched": True,
        },
    }


def _submit_revision(action, state: ReviseState) -> dict:
    if not action.applied and not action.skipped:
        raise StructuralError(
            "nothing_reported",
            "no finding was carried out and none was skipped. Every finding "
            "has to end up in one list or the other - a finding dropped "
            "without a reason is indistinguishable from one nobody read.",
            "revise",
        )
    unknown = [
        finding_id for finding_id in action.applied
        if state.finding(finding_id) is None
    ]
    if unknown:
        raise StructuralError(
            "unknown_finding",
            "these ids are not findings from this revision: "
            + ", ".join(unknown),
            "revise",
        )

    # A finding reported as applied has to have a change behind it.
    #
    # Measured on the second real run: the agent submitted `applied: ["F1"]`,
    # nothing had been written - no parameter set, no script replaced - and
    # the loop took it at its word and built the next revision from an
    # unchanged design. The revision was generated, meshed and solved to
    # produce the same numbers as the one before it, and the prediction it was
    # supposed to test was never tested. Checking the count is not enough:
    # what has to line up is which finding each change was made for.
    recorded = {
        entry.get("finding") for entry in state.applied if entry.get("finding")
    }
    unbacked = [
        finding_id for finding_id in action.applied
        if finding_id not in recorded
    ]
    if unbacked:
        raise StructuralError(
            "applied_without_a_change",
            "these findings were reported as carried out and no change was "
            "made for them: " + ", ".join(unbacked)
            + ". Every change records the finding it is for - pass "
            "`finding_id` to set_parameter or write_script - and a finding "
            "with no change behind it belongs in `skipped` with the reason.",
            "revise",
        )

    # And the change has to be the one the finding asked for.
    #
    # A change made for a finding is evidence about that finding's reasoning,
    # and it is only evidence if it is the change the finding proposed. An
    # agent that quietly substitutes a variable it prefers has tested a
    # different hypothesis, and the loop would credit the result to the one
    # the feedback agent stated - which is the one thing the prediction
    # mechanism exists to keep straight.
    for entry in state.applied:
        finding_id = entry.get("finding")
        if finding_id not in action.applied:
            continue
        asked_for_as = entry.get("asked_for_as")
        if not asked_for_as:
            continue
        finding = state.finding(finding_id) or {}
        proposed = ((finding.get("change") or {}).get("parameter") or "")
        if proposed and proposed != asked_for_as:
            raise StructuralError(
                "applied_a_different_change",
                f"finding {finding_id} asked for {proposed!r} and "
                f"{asked_for_as!r} was changed instead. The next revision "
                "tests whichever change is made, and the loop records the "
                "result against the finding - so a substituted variable is "
                "scored as evidence about a change that was never made. If "
                "the finding's variable is wrong, skip it and say why.",
                "revise",
            )

    # And the change has to have landed in the document the *next* revision
    # will be built from.
    #
    # This is the guard one layer below the two above, and it is the one that
    # decides whether any of this is real. `document.json` is what the
    # generator builds from once a revision has one; the template parameters
    # are read only before that. A change recorded against `params.json`
    # therefore satisfies "every applied finding has a change behind it" and
    # still moves nothing - the loop would generate, mesh and solve the
    # previous geometry, score the prediction against it, and write the result
    # into the knowledge base as evidence about a change that was never made.
    #
    # Checked as a diff rather than against the change log, because the change
    # log is the thing being checked. `document.base.json` is the document this
    # revision was handed; if a change was claimed and the two are identical,
    # nothing was changed, no matter what was reported.
    #
    # Guarded on `state.applied` being non-empty, and that guard is load
    # bearing. A revision may legitimately carry out nothing: the feedback
    # agent is entitled to conclude that no editable parameter can relieve the
    # peak, and the honest revision of that finding is to skip it. Asking for
    # an unchanged document then reads as a failure and leaves the agent with
    # no legal move - measured, where it submitted `needs_input` instead and
    # the run died on a question it should never have had to ask.
    if state.workspace.document() is not None:
        unlanded = [
            str(entry.get("finding") or entry.get("parameter") or "?")
            for entry in state.applied
            if not str((entry.get("patch") or {}).get("path") or "")
            .startswith("/nodes/")
        ]
        if unlanded:
            raise StructuralError(
                "change_did_not_reach_the_document",
                "these findings were carried out by changes that do not touch "
                "this revision's document: " + ", ".join(unlanded)
                + ". This revision is built from `document.json`, so a change "
                "written anywhere else - a template parameter in `params.json`, "
                "a replaced script - is not read by the generator. The next "
                "revision would be built from the geometry you already have, "
                "and its result would be recorded against the finding as though "
                "the change had been tested. Name an operation parameter of the "
                "document, or skip the finding and say why it has no handle.",
                "revise",
            )
        if state.applied and not state.workspace.document_edits():
            raise StructuralError(
                "document_unchanged",
                "changes were reported as applied but this revision's document "
                "is identical to the one it was handed, so the next revision "
                "would be built from the same geometry. Nothing was changed.",
                "revise",
            )
    state.skipped = list(action.skipped)
    state.submitted = {
        "applied": list(action.applied),
        "skipped": list(action.skipped),
        "rationale": action.rationale,
    }
    return {
        "ok": True,
        "result": {
            "accepted": True,
            "applied": len(action.applied),
            "skipped": len(action.skipped),
            "params": state.workspace.params(),
        },
    }


def _needs_input(action, state: ReviseState) -> dict:
    return {
        "ok": True,
        "result": {"accepted": False, "questions": action.questions},
    }


class CommitAction(Action):
    """The last call: report what was changed, or say what is missing."""

    action: Literal["submit_revision", "needs_input"]


DISPATCH = dispatch_table({
    "get_findings": _get_findings,
    "get_rules": _get_rules,
    "read_design": _read_design,
    "read_script": _read_script,
    "check_change": _check_change,
    "set_parameter": _set_parameter,
    "write_script": _write_script,
    "submit_revision": _submit_revision,
    "needs_input": _needs_input,
})

SYSTEM_PROMPT = """\
You are revising a turbine disc design. A structural analysis of the previous
revision has been done, the results have been judged, and someone has read them
and said what should change and why. Your job is to carry that out.

You are editing the design that was already generated, not asking for a new
one. The previous revision produced a CAD document - every sketch, every
cutting tool, every pattern, each with its own parameters - and that document
is what this revision is built from. Your change is applied to it and the
result is built from the modified document. Nothing runs a generator again: a
model regenerated from a description is a different model, and the comparison
against the previous revision would be between two unrelated parts rather than
between a design and the same design with one thing changed.

So the design is `document.json`. Its operations are the vocabulary:

- `read_design`    every parameter you may name, as
  `<node_id>.<param>` or `<node_id>.points[<i>].<x_mm|y_mm>`, each with the
  operation it belongs to and, where it can be worked out, the radius it acts
  at. Read this first and change things by these names.
- `set_parameter`  change one of them. Refused with the reason if the name is
  not in the document or the change is too large.
- `check_change`   measure a change before making it.
- `get_findings`   the findings from the last revision - where the problem is,
  what mechanism it is, the measurements behind it, and the change asked for.
- `get_rules`      two lists. `rules_by_mechanism` is what the loop currently
  believes for these mechanisms, with how often each has held. `retired_by_
  mechanism` is what it tried and had to stop believing, with the observations
  that retired it. Read the second one before you apply anything: it names
  changes that were already made and did not do what they were for, and
  repeating one is not a new idea.
- `read_script`    one of this revision's copies of the templates, if you need
  to see how the document was produced.
- `submit_revision` report what you carried out and what you did not.

A change has to land in the document. It is the only thing the generator
reads for this revision, and a change that does not reach it is a change that
did not happen - the next revision would be built from the geometry you
already have, and its result recorded as a test of something nothing was done
to test. A template parameter, or a replaced script, is not read once a
document exists and is refused.

What you are editing is a copy. The parametric templates in `scripts/` beside
your `generate.py` are a copy of the master, taken when this revision was
opened; the master itself is never written to and is checked after every write
you make.

Four things to hold to:

- Account for every finding. `submit_revision` takes an `applied` list and a
  `skipped` list, and a finding in neither is one nobody read. A skip needs a
  reason - "nothing in the document acts there", "the change is larger than
  one step allows", "the rule for this mechanism has already failed twice".
- Pass `finding_id` to `set_parameter` so each change says which finding it is
  for. A finding reported as applied with no change behind it is refused: the
  loop would otherwise build the next revision from an unchanged design, solve
  it, and record the result as a test of a prediction nothing had been done to
  test. Measured on the second real run, where that is exactly what happened.
- A change larger than the repair kernel accepts in one step will be refused
  downstream. Do not make it; skip the finding and say so.
- If a finding cannot be carried out, skip it and say why. Do not report it as
  applied to make the revision look productive.

Do not invent changes of your own. If you believe a finding is wrong, skip it
and say why; the record of a diagnosis being declined is worth more than a
change nobody asked for.

Your last call offers only submit_revision and needs_input. Budget accordingly.
"""


def spec(*, max_calls: int = 16) -> AgentSpec:
    return AgentSpec(
        name="revise",
        tool_name="revise_action",
        tool_description=(
            "Read the findings and the recorded rules, check a change, apply "
            "it to this revision's copy, or report what was done."
        ),
        action_model=Action,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            "The previous revision has been solved and diagnosed. Carry out "
            "what the findings ask for in this revision's design, and report "
            "every finding as applied or skipped with a reason.\n\n"
            "Start with get_findings, then get_rules, then read_design. Check "
            "each change before making it."
        ),
        submit_actions=frozenset({"submit_revision", "needs_input"}),
        max_calls=max_calls,
        timeout_s=600,
        terminal_model=CommitAction,
    )


def revise(
    ctx: RunContext,
    *,
    findings: list[dict],
    space: workspace.Workspace,
    base: knowledge.KnowledgeBase,
    api_key_file: Path | None = None,
    max_calls: int = 16,
) -> dict:
    """The stage function: apply the findings to the workspace's copy."""
    from seekflow_structural.runtime.caller import build_caller

    space.verify_master_untouched()
    state = ReviseState(workspace=space, findings=findings, base=base)
    caller, model_config = build_caller(api_key_file)
    outcome = run_agent(
        spec(max_calls=max_calls), caller=caller,
        model_config=model_config, dispatch=DISPATCH, context=state,
    )
    ctx.charge_tool_calls(outcome.calls, "revise")
    space.verify_master_untouched()

    final = outcome.final or exhausted_final("revise")
    # What actually changed about the design, as a diff of the document this
    # revision was handed against the one it now holds. Recorded beside the
    # change log rather than derived from it, because the two answer different
    # questions and the difference is the one that matters: `applied_changes`
    # is what the agent reported, this is what the file says. A revision whose
    # reported changes do not appear here changed nothing.
    edits = space.document_edits()
    # Written before the decision is acted on, so a run that ends badly still
    # leaves what it changed on disk with the reasoning that asked for it.
    ctx.job.write("agent/revise.json", {
        "schema_version": "revise_run_v1",
        "lineage": space.lineage,
        "revision": space.revision,
        "design_surface": (
            "document" if space.document() is not None else "template_params"
        ),
        "trace": outcome.trace,
        "rejected_calls": outcome.rejected,
        "final": outcome.final,
        "checks": state.checks,
        "applied_changes": state.applied,
        "document_edits": edits,
        "changed_from_master": space.changed_files(),
        "calls": outcome.calls,
        "exhausted": outcome.exhausted,
    })
    if not final.get("accepted"):
        raise StructuralError(
            "revision_not_reported",
            "the revision agent did not report what it changed: "
            + "; ".join(final.get("questions", [])),
            "revise",
        )
    if state.submitted is None:
        raise StructuralError(
            "revision_not_reported",
            "the revision agent reported a submission it did not make",
            "revise",
        )
    # The document is handed back as the design, because that is what was
    # changed. The next revision is built from it; a caller that took only
    # `params` would build the previous design again and compare two runs of
    # the same geometry.
    return {
        "applied": state.submitted["applied"],
        "skipped": state.submitted["skipped"],
        "rationale": state.submitted["rationale"],
        "params": space.params(),
        "document": space.document(),
        "document_edits": edits,
        "changed_from_master": space.changed_files(),
    }


def report_lines(result: dict) -> list[str]:
    """What a revision contributes to the written report."""
    out = ["", "## What this revision changed", ""]
    if result.get("applied"):
        out.append(f"- Applied: {', '.join(result['applied'])}")
    else:
        out.append("- Applied: nothing")
    for entry in result.get("skipped") or []:
        out.append(f"- Skipped {entry.get('id')}: {entry.get('reason')}")
    if result.get("changed_from_master"):
        out.append(
            "- Template copies changed from the master: "
            + ", ".join(result["changed_from_master"])
        )
    return out
