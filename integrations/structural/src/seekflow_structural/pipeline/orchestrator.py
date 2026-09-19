"""Runs the stages in order, and keeps an audit trail that can be checked.

The pattern is taken from the CFD orchestrator, which is the only end-to-end
runner this repository already had: a stage field in `state.json` checkpointed
at every boundary, an append-only hash-chained `events.jsonl`, per-call records
under `calls/`, budgets that are actually enforced, and a resume that refuses
to continue when the inputs have moved.

Two things are specific to this chain. The case is checkpointed at every stage
boundary with its digest, so a changed decision invalidates exactly the
downstream stages that consumed it. And an interrupted external call is never
retried blindly - a solve that was killed mid-run has left state on disk that
nobody has looked at.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from seekflow_structural.case.model import Case
from seekflow_structural.case.store import CaseStore
from seekflow_structural.errors import (
    STATUS_FAILED,
    StructuralError,
)
from seekflow_structural.pipeline.stages import (
    REQUIRES,
    STAGE_ORDER,
    Stage,
    next_stage,
)
from seekflow_structural.runtime.store import JobStore, now
from seekflow_structural.serialize import digest

# A stage is a function that takes the context and returns the case it wants
# written - or None when it wrote the case itself, which agents do because
# their work is spread over several tool calls.
StageFn = Callable[["RunContext"], "Case | None"]


@dataclass
class Budget:
    max_tool_calls: int = 200
    max_output_bytes: int = 8 * 1024 * 1024 * 1024
    # The solve has its own clock: a large model can legitimately run for an
    # hour while everything else finishes in minutes, and one shared wall-time
    # budget cannot express that without being useless for one of them.
    max_ansys_wall_s: int = 4000
    wall_time_s: int = 24 * 3600


@dataclass
class RunContext:
    job: JobStore
    case_store: CaseStore
    budget: Budget
    allow_unconfirmed: bool = False
    stage: Stage = Stage.PREFLIGHT
    case: Case | None = None
    # The user's parameter file, verbatim. Stages read their inputs from here
    # rather than from arguments, so there is one description of the case and
    # not one per stage.
    params: dict = field(default_factory=dict)
    params_path: str = ""
    # The same description, in prose, for a run whose parameters were not
    # written out by hand. The setup stage turns one or the other into the
    # case's physics; supplying both is allowed and the written values win,
    # because a person who typed a number meant that number.
    brief: str = ""
    brief_path: str = ""
    # A meshing plan to use instead of asking the agent for one. It exists so
    # that two revisions can be meshed by the same rule: the size field is a
    # function of space, not of the model, so holding it fixed is what makes a
    # peak difference between two designs attributable to the designs rather
    # than to one of them having been resolved more finely.
    mesh_plan: dict | None = None
    # A load surface to use instead of asking the face-finding agent for one.
    # It exists for the same reason as `mesh_plan`: two revisions have to be
    # loaded the same way before a difference between their stresses can be
    # attributed to their geometry. Measured on D27, revision one applied the
    # blade load to 24 faces totalling 2,679 mm2 and revision two to 8 faces
    # totalling 665 mm2 - the same resultant force pressed onto a quarter of
    # the area, at 4.6 times the pressure, which put the peak on the loaded
    # face and raised it by 122%.
    face_selection: dict | None = None
    # A domain decision to use instead of asking the agent for one: which
    # piece of the part is analysed, and where the sector starts. It belongs
    # with the other two - an experiment is the same experiment only if the
    # same piece of the part was cut out of it.
    #
    # Measured: on the fourth run of one disc the domain agent spent its whole
    # budget calling `probe_periodicity` ten times with identical arguments and
    # never decided, which ended a revision that the solve would otherwise
    # have measured.
    domain_decision: dict | None = None
    started: float = field(default_factory=time.monotonic)
    calls: int = 0

    @property
    def path(self) -> Path:
        return self.job.path

    def tool_call(self) -> None:
        """Charge one tool call against the budget, or refuse."""
        self.calls += 1
        if self.calls > self.budget.max_tool_calls:
            raise StructuralError(
                "tool_budget",
                f"Tool-call budget of {self.budget.max_tool_calls} exhausted",
                "budget",
                status=STATUS_FAILED,
            )

    def charge_tool_calls(self, count: int, agent: str) -> None:
        """Put an agent's calls on the run's ledger.

        The agent loop counts its own calls against its own limit, and the
        stage wrote that number into `agent/<name>.json` - but never charged
        it here. So every agent stage closed with `tool_calls: 0` in the
        events, reporting that nothing had been spent after the model had been
        called nine times, and the run's own budget never saw an agent's calls
        at all. A ledger that under-reports is worse than no ledger: it is
        read as evidence.
        """
        for _ in range(count):
            self.tool_call()
        self.job.event({
            "kind": "agent_spend",
            "stage": self.stage.value,
            "agent": agent,
            "calls": count,
            "calls_total": self.calls,
        })

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

    def check_wall_time(self) -> None:
        if self.elapsed_s() > self.budget.wall_time_s:
            raise StructuralError(
                "wall_time_budget",
                f"Wall-clock budget of {self.budget.wall_time_s}s exhausted",
                "budget",
                status=STATUS_FAILED,
            )
        if (self.path / "cancel.request").exists():
            raise StructuralError(
                "cancelled", "Cancellation was requested", "budget",
                status=STATUS_FAILED,
            )

    def record_call(self, name: str, payload: dict) -> None:
        """One artifact per tool call, alongside the audit event."""
        call_id = uuid.uuid4().hex
        self.job.write(f"calls/{call_id}.json", payload)
        self.job.event(
            {"kind": "tool_call", "stage": self.stage.value, "name": name,
             "call_id": call_id}
        )


def _diagnose(exc: Exception, stage: Stage) -> dict:
    """A failure in the shape a record carries, whatever raised it.

    This package's own errors already say which stage they came from and
    whether a retry is safe. Anything else - a dropped connection, a missing
    file - is reported against the stage that was running, and marked failed
    rather than rejected: something outside may already be in flight.
    """
    if isinstance(exc, StructuralError):
        return exc.diagnostic.model_dump(mode="json")
    return {
        "code": type(exc).__name__,
        "message": str(exc),
        "stage": stage.value,
        "status": STATUS_FAILED,
        "recoverable": False,
        "details": {},
    }


class Orchestrator:
    def __init__(
        self,
        output_root: Path,
        stages: dict[Stage, StageFn] | None = None,
        budget: Budget | None = None,
    ):
        self.output_root = Path(output_root)
        self.stages = dict(stages or {})
        self.budget = budget or Budget()

    def register(self, stage: Stage, fn: StageFn) -> None:
        self.stages[stage] = fn

    def run(
        self,
        job_id: str,
        *,
        case: Case,
        resume: bool = False,
        allow_unconfirmed: bool = False,
        params: dict | None = None,
        params_path: str = "",
        brief: str = "",
        brief_path: str = "",
        mesh_plan: dict | None = None,
        face_selection: dict | None = None,
        domain_decision: dict | None = None,
    ) -> dict:
        job = JobStore(self.output_root, job_id)
        with job.lock():
            return self._run_locked(
                job, case, resume, allow_unconfirmed, params or {}, params_path,
                brief, brief_path, mesh_plan, face_selection,
                domain_decision,
            )

    def _run_locked(
        self,
        job: JobStore,
        case: Case,
        resume: bool,
        allow_unconfirmed: bool,
        params: dict,
        params_path: str = "",
        brief: str = "",
        brief_path: str = "",
        mesh_plan: dict | None = None,
        face_selection: dict | None = None,
        domain_decision: dict | None = None,
    ) -> dict:
        store = CaseStore(job)
        state = store.state()

        if resume:
            self._check_resume(job, case, state)
        elif job.exists("state.json"):
            raise StructuralError(
                "job_exists",
                f"job {job.job_id} already has state; pass resume to continue "
                "it or choose another job id",
                "preflight",
            )

        start = Stage.PREFLIGHT
        if resume and state.get("stage"):
            start = next_stage(Stage(state["stage"]))

        context = RunContext(
            job=job,
            case_store=store,
            budget=self.budget,
            allow_unconfirmed=allow_unconfirmed,
            case=case,
            params=params,
            params_path=params_path,
            brief=brief,
            brief_path=brief_path,
            mesh_plan=mesh_plan,
            face_selection=face_selection,
            domain_decision=domain_decision,
        )
        job.event(
            {
                "kind": "run_start",
                "job_id": job.job_id,
                "from_stage": start.value,
                "resume": resume,
                "params_hash": digest(params),
                # Hashed rather than stored: a brief is prose a person wrote
                # about a machine, and the audit needs to say which one was
                # used without copying their words into the record.
                "brief_hash": digest(brief) if brief else "",
            }
        )

        # A resumed run continues from the stored case, not the one handed in:
        # the stored one is what the upstream stages actually produced.
        if resume:
            stored = store.load()
            if stored is not None:
                case = stored

        try:
            for stage in STAGE_ORDER[STAGE_ORDER.index(start):]:
                context.stage = stage
                context.case = case
                context.check_wall_time()

                if stage in (Stage.PREFLIGHT, Stage.COMPLETE):
                    pass
                elif stage not in self.stages:
                    raise StructuralError(
                        "stage_not_registered",
                        f"no implementation registered for stage {stage.value}",
                        stage.value,
                    )

                required = REQUIRES[stage]
                if required:
                    missing = [
                        name for name in required
                        if getattr(case, name, None) is None
                    ]
                    if missing:
                        raise StructuralError(
                            "case_incomplete",
                            f"stage {stage.value} needs {', '.join(missing)}",
                            stage.value,
                        )

                result = None
                if stage in self.stages:
                    result = self.stages[stage](context)
                if result is not None:
                    case = result

                store.save(
                    stage.value, case, elapsed_s=round(context.elapsed_s(), 3)
                )
                job.event(
                    {
                        "kind": "stage_complete",
                        "stage": stage.value,
                        "case_hash": digest(case),
                        "tool_calls": context.calls,
                    }
                )
                context.case = case
        except Exception as exc:
            # Any failure, not only this package's own error type. A network
            # error from the model provider used to escape this handler, which
            # meant the run ended without closing its manifest - and the next
            # resume then reported a healthy job as tampered with, because the
            # audit log had moved on and the manifest had not. A job has to be
            # left consistent however it ends.
            diagnostic = _diagnose(exc, context.stage)
            job.event({
                "kind": "run_failed",
                "stage": diagnostic["stage"],
                "code": diagnostic["code"],
                "message": diagnostic["message"],
            })
            self._finish(job, case, status=diagnostic["status"],
                         diagnostic=diagnostic)
            raise

        record = self._finish(job, case, status="success", diagnostic=None)
        return record

    def _check_resume(self, job: JobStore, case: Case, state: dict) -> None:
        """Refuse to continue a job that is not the job we think it is.

        A resume on a different model is the expensive kind of mistake: the
        stored case describes faces and a mesh belonging to the old bundle,
        and nothing downstream would notice they no longer match.
        """
        recorded = state.get("bundle_hash")
        incoming = digest(case.bundle.model_dump(mode="json"))
        if recorded is not None and recorded != incoming:
            raise StructuralError(
                "resume_mismatch",
                "the model bundle differs from the one this job ran on",
                "preflight",
            )
        job.verify_events()
        if job.exists("manifest.json"):
            job.verify_manifest()

    def _finish(
        self, job: JobStore, case: Case, status: str, diagnostic: dict | None
    ) -> dict:
        """Close the run: record, then the closing event, then the manifest.

        The order matters and is the whole point. The manifest hashes every
        artifact in the job, so anything written after it makes the manifest
        stale and the next resume reports a healthy job as tampered with -
        which is exactly what happened when the manifest was written first.
        Nothing may be written after the manifest.
        """
        record = {
            "schema_version": "structural_run_v1",
            "job_id": job.job_id,
            "case_id": case.case_id,
            "status": status,
            "diagnostic": diagnostic,
            "case_hash": digest(case),
            "scientific_status": (
                case.solve.scientific_status if case.solve else ""
            ),
            "finished_at_utc": now(),
        }
        job.write("record.json", record)
        job.event({"kind": "run_end", "status": status})
        job.write("manifest.json", job.manifest(self.budget.max_output_bytes))
        return record
