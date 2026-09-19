"""Connecting the loop to the two agents, which is the last seam.

`iterate.Loop` takes `generate`, `solve`, `diagnose` and `revise` as callables
so that it can be tested without a CAD kernel, a solver or a model. `parametric`
fills in the first two. This fills in the other two.

Neither agent was written to be called from a loop. Both are stage functions:
they take a `RunContext`, they write what they decided into that context's job,
and the orchestrator reads the case afterwards. A loop has no orchestrator and
no case of its own - it has a revision's workspace and the structural job that
was run on it - so the adapters below build the small amount of context each
agent needs and read the decision back out of the record the agent wrote.

Reading it back out of the file rather than out of a return value is
deliberate. `feedback.json` and `agent/revise.json` are the artifacts a person
reads to find out what happened; if the loop took the answer from memory and
the file disagreed, the file would be the one that was wrong.

A stage that cannot decide raises. The loop catches that and records the
revision as one that produced no result, which is the correct outcome - an
agent that exhausted its budget has tested nothing about the design.
"""
from __future__ import annotations

import json
from pathlib import Path

from seekflow_structural.case.store import CaseStore
from seekflow_structural.pipeline.orchestrator import Budget, RunContext
from seekflow_structural.runtime.store import JobStore
from seekflow_structural.tools import knowledge, workspace


def context_for(job_dir: Path) -> RunContext:
    """A context around a structural job that has already been run.

    `JobStore` lays a job out at `<output_root>/jobs/<job_id>`, which is the
    one thing that has to be got right here: reading the directory as
    `<output_root>/<job_id>` finds nothing on a job that exists, and the
    failure then reads as a stage that never ran.
    """
    job_dir = Path(job_dir)
    job = JobStore(job_dir.parent.parent, job_dir.name)
    store = CaseStore(job)
    case = store.load()
    if case is None:
        raise FileNotFoundError(
            f"{job_dir} holds no case.json, so there is nothing for an agent "
            "to read: the structural run did not get far enough to write one"
        )
    return RunContext(
        job=job, case_store=store, budget=Budget(), case=case,
        allow_unconfirmed=True,
    )


def make_diagnose(
    *,
    api_key_file: Path | None = None,
    max_calls: int = 24,
):
    """The loop's `diagnose`, backed by the feedback agent.

    Returns the findings in the shape the loop scores them in, read back from
    the file the agent wrote. An agent that filed nothing - because the honest
    answer was that nothing should change - returns an empty list, which the
    loop reports as a revision with nothing to do.
    """
    from seekflow_structural.agents import feedback as feedback_stage

    def diagnose(metrics: dict, verdicts: dict, space: workspace.Workspace,
                 job_dir: Path) -> list[dict]:
        # The metrics and verdicts the loop passes are not used: the agent
        # reads the field and the verdicts from the job itself, which is the
        # same place the report was written from. Passing them in as well
        # would give the agent two sources for one number.
        ctx = context_for(job_dir)
        record = ctx.path / "feedback.json"

        # Read the diagnosis if the run already made one.
        #
        # `feedback` is registered as the last stage of the chain, so a run
        # that reached COMPLETE has already diagnosed itself by the time the
        # loop asks. Calling the stage again is not a repeat of the same
        # answer: measured on the first end-to-end run, the second call
        # produced a different set of findings, wrote them over the first, and
        # left the revision agent acting on a diagnosis the run had not made -
        # and paid for two rounds of the model to do it. The stage is for a
        # job that has not been diagnosed; this is for one that has.
        if not record.is_file():
            feedback_stage.feedback(ctx, api_key_file=api_key_file,
                                     max_calls=max_calls)
        if not record.is_file():
            raise RuntimeError(
                f"the feedback stage finished without writing {record}"
            )
        return json.loads(record.read_text(encoding="utf-8")).get(
            "findings"
        ) or []

    return diagnose


def make_revise(
    *,
    base: knowledge.KnowledgeBase,
    api_key_file: Path | None = None,
    max_calls: int = 16,
):
    """The loop's `revise`, backed by the revision agent.

    The agent writes into the revision's own workspace - its copy of the
    templates and its `generate.py` - which is why it is handed the workspace
    and not a job. Its run record goes beside the revision rather than into
    the structural job, because it is a fact about the design and not about
    the solve.
    """
    from seekflow_structural.agents import revise as revise_stage

    def revise(findings: list[dict], space: workspace.Workspace) -> dict:
        job = JobStore(space.root, "revision")
        ctx = RunContext(
            job=job,
            # This stage keeps no case of its own - it edits a design, and the
            # design is the workspace - but the context carries one, and an
            # empty store over the revision's own job is the honest filler.
            case_store=CaseStore(job),
            budget=Budget(),
            allow_unconfirmed=True,
        )
        return revise_stage.revise(
            ctx, findings=findings, space=space, base=base,
            api_key_file=api_key_file, max_calls=max_calls,
        )

    return revise
