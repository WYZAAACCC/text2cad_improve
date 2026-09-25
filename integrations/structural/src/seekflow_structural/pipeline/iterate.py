"""Running the loop: generate, solve, diagnose, change, and do it again.

Each revision is the previous one plus whatever the last solve said to change.
The loop owns four things beyond the chain that already exists.

It owns the workspace, so every revision is a copy and the master templates
are never written to.

It owns the prediction check. A finding commits to a direction before the
change is made; the next solve measures whether the direction was right; and
the comparison is what the loop actually learns from. A revision that improved
without its prediction having said so has not confirmed anything, and a
revision that got worse while the prediction said it would improve has
refuted something - those are different, and both are recorded.

It owns the knowledge base, which accumulates across lineages rather than
within one. A rule about what relieves bore hoop stress is not a fact about
D27; it is a hypothesis the third disc that tests it is in a better position
to judge than the first.

It owns the stopping. Three revisions is the default because the first
observation of a rule cannot distinguish a mechanism from a coincidence, and
the default is stated rather than inferred from a tolerance - the loop does
not know when the design is good, because what counts as good is an
engineering decision about a specific component.

What it does not own is generating a model or solving one. Both arrive as
callables, because both are the existing system's and this module has no
business knowing how they work. That is also what makes the loop testable
without a CAD kernel or a solver.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
import inspect
from typing import Callable

from seekflow_structural.tools import knowledge, results, workspace

# What a generated revision is handed to, and what comes back. The generate
# step gets the revision's workspace and returns whatever the solve step will
# need to find the model; the solve step gets that and returns the run, whose
# `job` names the directory the diagnose step has to read.
#
# The diagnose and revise steps get the workspace as well, because both write
# into the revision they belong to - one files what it found, the other edits
# the design - and neither should have to guess which revision it is working
# on.
GenerateFn = Callable[[workspace.Workspace], Path]
SolveFn = Callable[[Path, workspace.Workspace], dict]
DiagnoseFn = Callable[[dict, dict, workspace.Workspace, Path], list[dict]]
ReviseFn = Callable[[list[dict], workspace.Workspace], dict]
DesignProbeFn = Callable[..., dict]

DEFAULT_REVISIONS = 3


@dataclass
class RevisionOutcome:
    """One pass round the loop."""

    revision: str
    workspace_root: str
    params: dict
    metrics: dict = field(default_factory=dict)
    verdicts: dict = field(default_factory=dict)
    findings: list[dict] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    # What the revision actually changed about the document it was handed, as
    # a diff. The record of a change and the change itself are two different
    # claims, and this is the second one: a revision whose `applied` is
    # non-empty and whose `document_edits` is empty did not change the design,
    # and the next revision would be the one before it again.
    document_edits: list[dict] = field(default_factory=list)
    # The prediction checks this revision produced about the *previous* one.
    observations: list[dict] = field(default_factory=list)
    # How far each reported metric moved between this run's two mesh levels.
    # Empty means no convergence study was run, which is not the same as a
    # floor of zero.
    noise_floors: dict = field(default_factory=dict)
    changed_from_master: list[str] = field(default_factory=list)
    design_facts: dict = field(default_factory=dict)
    design_effect: dict = field(default_factory=dict)
    limits: list[str] = field(default_factory=list)


@dataclass
class LoopResult:
    lineage: str
    revisions: list[RevisionOutcome] = field(default_factory=list)
    knowledge: dict = field(default_factory=dict)
    limits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": "structural_iteration_v1",
            "lineage": self.lineage,
            "knowledge": self.knowledge,
            "limits": self.limits,
            "revisions": [
                {
                    "revision": item.revision,
                    "workspace_root": item.workspace_root,
                    "params": item.params,
                    "metrics": item.metrics,
                    "verdicts": item.verdicts,
                    "findings": item.findings,
                    "applied": item.applied,
                    "skipped": item.skipped,
                    "document_edits": item.document_edits,
                    "observations": item.observations,
                    "noise_floors": item.noise_floors,
                    "changed_from_master": item.changed_from_master,
                    "design_facts": item.design_facts,
                    "design_effect": item.design_effect,
                    "limits": item.limits,
                }
                for item in self.revisions
            ],
        }


def score_applied(
    applied_findings: list[dict],
    before: dict,
    after: dict,
    *,
    revision: str,
    base: knowledge.KnowledgeBase,
    noise_floors: dict | None = None,
) -> list[dict]:
    """Check every change the last revision made against what it predicted.

    Only findings that were actually applied are scored. A finding that was
    skipped produced no change, so the metric moving or not says nothing about
    it - and recording it either way would put a result into the knowledge base
    that the run did not produce.

    A finding with no prediction is recorded as untested rather than as
    confirmed. The loop cannot tell whether it worked, and saying so is the
    difference between a record and a tally.
    """
    out: list[dict] = []
    before_scalars = results.reported_scalars(before)
    after_scalars = results.reported_scalars(after)
    for finding in applied_findings:
        change = finding.get("change") or {}
        parameter = str(change.get("parameter") or "")
        prediction = finding.get("prediction") or {}
        metric = str(prediction.get("metric") or "max_von_mises_mpa")
        finding_id = str(finding.get("id") or "")
        proposed = change.get("proposed_value")
        current = change.get("current_value")
        relative = change.get("relative_change")
        if proposed is not None and current is not None:
            direction = "increase" if float(proposed) > float(current) else "decrease"
        elif relative is not None:
            direction = "increase" if float(relative) >= 0.0 else "decrease"
        else:
            direction = (
                "increase" if prediction.get("direction") == "increase"
                else "decrease"
            )

        base_id = f"{finding.get('mechanism')}::{parameter}"
        conflict_id = f"{base_id}::{direction}"
        entry_id = conflict_id
        entry = base.get(entry_id)
        if entry is None:
            entry = base.get(base_id)
            if (entry is not None and entry.direction
                    and direction and entry.direction != direction):
                # An opposite change is a different hypothesis. Keeping it on
                # the same entry would mix observations that tested opposite
                # actions, so give the conflicting direction its own rule.
                entry = None
            else:
                entry_id = base_id
        if entry is not None and not entry.direction:
            entry.direction = direction
        if entry is None:
            entry = base.upsert(knowledge.KnowledgeEntry(
                id=entry_id,
                mechanism=str(finding.get("mechanism") or "unresolved"),
                parameter=parameter,
                direction=direction,
                at=str(finding.get("feature") or ""),
                expected_metric=metric,
                expected_direction=(
                    "increase"
                    if prediction.get("direction") == "increase" else "decrease"
                ),
                status="candidate",
                note=f"first proposed by {revision}",
            ))

        if not prediction:
            out.append({
                "entry": entry_id, "finding": finding_id,
                "outcome": "untested",
                "note": (
                    "the finding carried no prediction, so this run cannot say "
                    "whether the change did what it was for"
                ),
            })
            entry.observations.append(knowledge.Observation(
                revision=revision, metric=metric,
                predicted_relative_change=0.0, measured_relative_change=None,
                outcome="unmeasurable",
                note="no prediction was stated, so nothing was tested",
            ))
            entry.status = _restatus(entry)
            continue

        # `direction` says which way and `expected_relative_change` says how
        # far, so the sign comes from the first and the size from the second.
        # Reading the size as the sign made every "decrease" prediction come
        # out positive, and so every change that worked was recorded as having
        # moved the wrong way.
        magnitude = abs(float(prediction.get("expected_relative_change") or 0.0))
        signed = -magnitude if prediction.get("direction") == "decrease" else magnitude
        measured = knowledge.relative_change(
            before_scalars.get(metric), after_scalars.get(metric)
        )
        # The floor comes from the run that measured the change, because that
        # is the run whose mesh moved. A revision compared against a floor
        # measured somewhere else is comparing against a different part.
        observation = knowledge.score_prediction(
            signed, measured, metric=metric, revision=revision,
            noise_floor=(noise_floors or {}).get(metric),
        )
        observation.side_effects = knowledge.side_effects(
            metric, before_scalars, after_scalars
        )
        entry.observations.append(observation)
        entry.status = _restatus(entry)
        out.append({
            "entry": entry_id,
            "finding": finding_id,
            "outcome": observation.outcome,
            "predicted_relative_change": signed,
            "measured_relative_change": measured,
            "side_effects": observation.side_effects,
            "note": observation.note,
        })
    return out


def _restatus(entry: knowledge.KnowledgeEntry) -> str:
    # Delegated so the promotion rules live in one place. `_status_for` is the
    # private spelling of them; calling it here keeps the two from drifting,
    # which they would if the thresholds were re-stated.
    return knowledge._status_for(entry)


class Loop:
    """The iteration, with the two heavy steps supplied from outside."""

    def __init__(
        self,
        *,
        master_dir: Path,
        root: Path,
        lineage: str,
        params: dict,
        document: dict | None = None,
        generate: GenerateFn,
        solve: SolveFn,
        diagnose: DiagnoseFn,
        revise: ReviseFn,
        knowledge_path: Path,
        metric: str = "max_von_mises_mpa",
        design_probe: DesignProbeFn | None = None,
    ):
        self.master_dir = Path(master_dir)
        self.root = Path(root)
        self.lineage = lineage
        self.params = dict(params)
        # The design, once a revision has one. `params` is how the first
        # revision was asked for; from the second on, this is what is built.
        self.document = document
        self.generate = generate
        self.solve = solve
        self.diagnose = diagnose
        self.revise = revise
        self.knowledge_path = Path(knowledge_path)
        self.metric = metric
        self.design_probe = design_probe
        self.base = knowledge.KnowledgeBase.load(self.knowledge_path)

    def _design_probe(
        self, bundle: Path, space: workspace.Workspace, target: dict
    ) -> dict:
        """Call a probe with optional target context, preserving old callers."""
        if self.design_probe is None:
            return {}
        try:
            arity = len(inspect.signature(self.design_probe).parameters)
        except (TypeError, ValueError):
            arity = 2
        if arity >= 3:
            return self.design_probe(bundle, space, target)
        return self.design_probe(bundle, space)

    def run(self, revisions: int = DEFAULT_REVISIONS) -> LoopResult:
        result = LoopResult(lineage=self.lineage)
        if revisions < 1:
            raise ValueError("a loop needs at least one revision")
        if revisions < 2:
            result.limits.append(
                "one revision tests nothing: the first observation of a rule "
                "cannot tell a mechanism from a coincidence, and no prediction "
                "is checked without a second run to check it against"
            )

        previous_metrics: dict | None = None
        previous_floors: dict = {}
        previous_design_facts: dict = {}
        applied_findings: list[dict] = []

        for index in range(1, revisions + 1):
            revision = f"rev-{index:06d}"
            space = workspace.Workspace.create(
                master_dir=self.master_dir,
                root=self.root / revision,
                lineage=self.lineage,
                revision=revision,
                params=self.params,
                document=self.document,
            )
            outcome = RevisionOutcome(
                revision=revision,
                workspace_root=str(space.root),
                params=space.params(),
            )

            # The change the previous revision asked for is checked by this
            # one, and the check happens before anything about this revision
            # is diagnosed - otherwise the new findings and the old prediction
            # are read out of the same numbers and neither is evidence.
            #
            # A revision that cannot be generated or solved ends the loop with
            # that recorded, and it does not touch the knowledge base. The
            # distinction matters more than it looks: a run that failed to
            # produce a number has tested nothing, and an agent stage that
            # exhausted its budget is not evidence that a design change failed.
            # Measured on the first end-to-end attempt, where the domain agent
            # spent its whole budget sweeping sector angles and the revision
            # produced no result at all - through no fault of the design.
            try:
                bundle = self.generate(space)
                target_context = {
                    "findings": list(applied_findings),
                    "changed_from_master": list(
                        outcome.document_edits or []
                    ),
                    "revision": revision,
                }
                if self.design_probe is not None:
                    outcome.design_facts = self._design_probe(
                        bundle, space, target_context
                    )
                # The final solid is measured before the solve, because a
                # change that did not reach the STEP must not buy a solver
                # run and must not be recorded as a tested prediction.
                if (
                    previous_design_facts
                    and outcome.design_facts
                    and applied_findings
                ):
                    from seekflow_structural.pipeline.design_effect import (
                        compare_design,
                    )

                    outcome.design_effect = compare_design(
                        previous_design_facts,
                        outcome.design_facts,
                        applied_findings,
                        self.document,
                    )
                    if outcome.design_effect.get("target_changed") is False:
                        outcome.limits.append(
                            "the generated STEP did not change in the target "
                            "window of the applied finding; the solve was "
                            "stopped before it could score a prediction "
                            "against an unchanged solid"
                        )
                        result.revisions.append(outcome)
                        result.limits.append(
                            f"the loop stopped at {revision}: the document "
                            "edit did not reach the measured STEP target"
                        )
                        break
                run = self.solve(bundle, space)
            except Exception as exc:
                outcome.limits.append(
                    f"{revision} produced no result: {type(exc).__name__}: "
                    f"{exc}. Nothing is recorded against any rule - a revision "
                    "that did not run has not tested one."
                )
                result.revisions.append(outcome)
                result.limits.append(
                    f"the loop stopped at {revision}, which produced no result"
                )
                break
            space.verify_master_untouched()
            outcome.metrics = run.get("metrics") or {}
            outcome.verdicts = run.get("verdicts") or {}

            # How far this run's own numbers move when only the mesh changes,
            # read off the two resolutions the meshing stage already solved.
            # Without it a difference between revisions cannot be told from a
            # difference in how they were meshed, and the comparison would be
            # reported as a design effect either way.
            noise = results.mesh_noise_floor(Path(run.get("job") or "."))
            floors = {
                metric: entry["relative_spread"]
                for metric, entry in (noise.get("floors") or {}).items()
            }
            outcome.noise_floors = floors
            outcome.limits.extend(noise.get("limits") or [])

            if previous_metrics is not None and applied_findings:
                if len(applied_findings) != 1:
                    # One solve produces one outcome. A revision that changed
                    # several variables cannot tell which prediction owns that
                    # outcome, so record the limitation instead of crediting
                    # every finding with the same result.
                    outcome.limits.append(
                        f"{len(applied_findings)} design changes were applied "
                        "together; their predictions are not scored because "
                        "the result cannot be attributed to one change"
                    )
                else:
                    # The larger of the two: either revision's mesh could have
                    # moved the number, so the smaller floor would understate
                    # how much of the difference is meshing.
                    combined = {
                        metric: max(floors.get(metric, 0.0),
                                    previous_floors.get(metric, 0.0))
                        for metric in set(floors) | set(previous_floors)
                    }
                    outcome.observations = score_applied(
                        applied_findings, previous_metrics, outcome.metrics,
                        revision=revision, base=self.base,
                        noise_floors=combined,
                    )
            else:
                outcome.limits.append(
                    "this is the first revision, so there was nothing to check"
                )

            findings = self.diagnose(
                outcome.metrics, outcome.verdicts, space,
                Path(run.get("job") or "."),
            )
            outcome.findings = findings
            decided: dict = {}
            if findings:
                decided = self.revise(findings, space)
                outcome.applied = list(decided.get("applied") or [])
                outcome.skipped = list(decided.get("skipped") or [])
                outcome.params = decided.get("params") or space.params()
                outcome.document_edits = list(
                    decided.get("document_edits") or []
                )
                applied_findings = [
                    finding for finding in findings
                    if str(finding.get("id")) in outcome.applied
                ]
            else:
                applied_findings = []
                outcome.limits.append(
                    "nothing was diagnosed as worth changing, so the next "
                    "revision would be this one again"
                )

            outcome.changed_from_master = space.changed_files()
            outcome.limits.extend(space.limits)
            result.revisions.append(outcome)
            previous_metrics = outcome.metrics
            previous_floors = floors
            previous_design_facts = outcome.design_facts

            # The next revision starts from this one's design, and every
            # revision after the first exists because a change was applied -
            # so a revision that applied nothing has nothing new to run.
            #
            # "Applied nothing" includes the case the metrics cannot show: a
            # revision that reported a change and left the document it was
            # handed untouched. Running the next revision then would produce
            # the same numbers, and the difference between the two - which is
            # zero, or noise - would be recorded against the finding as the
            # effect of a change that was never made. The revision agent
            # refuses to submit one, so reaching here means it was got around.
            unchanged_design = (
                bool(outcome.applied)
                and space.document() is not None
                and not outcome.document_edits
            )
            if unchanged_design:
                result.limits.append(
                    f"{revision} reported {len(outcome.applied)} change(s) and "
                    "its document is identical to the one it was handed, so the "
                    "design was not changed"
                )
                result.limits.append(
                    f"{revision} left the design unchanged, so the loop stopped "
                    "rather than building and solving the same geometry again"
                )
                break
            if not outcome.applied and index < revisions:
                result.limits.append(
                    f"{revision} applied no change, so the loop stopped rather "
                    "than running the same design again"
                )
                break
            self.params = outcome.params
            # The design the next revision starts from is the document this one
            # ended with - the change applied to it, not a re-description of the
            # result. A revision built any other way is a different part, and
            # the comparison against this one would be between two unrelated
            # models rather than between a design and the same design changed.
            if decided.get("document") is not None:
                self.document = decided["document"]

        self.base.save(self.knowledge_path)
        result.knowledge = self.base.summary()
        return result


def report_lines(result: LoopResult) -> list[str]:
    """What the loop contributes to the written report.

    A revision's own limits are printed under it, not only the loop-level ones.
    They used to be written into `loop_result.json` and left out of the report,
    which put the reason a run stopped in the machine-readable copy and not in
    the one a person reads. Measured: a revision failed at generation because
    the OCAF save could not write, and the report said only "produced no
    result" - the exception that said why was one key away in the JSON.
    """
    out = ["", "## Iterations", ""]
    for item in result.revisions:
        peak = (item.metrics or {}).get("stress", {}).get("max_von_mises_mpa")
        out.append(
            f"- **{item.revision}**: peak {peak} MPa; "
            f"applied {len(item.applied)}, skipped {len(item.skipped)}"
        )
        for observation in item.observations:
            out.append(
                f"  - {observation['entry']}: {observation['outcome']} — "
                f"{observation.get('note', '')}"
            )
        for note in item.limits:
            out.append(f"  - this revision: {note}")
    if result.knowledge:
        out.append("")
        out.append(f"- Knowledge: {json.dumps(result.knowledge, ensure_ascii=False)}")
    for note in result.limits:
        out.append(f"- Limit: {note}")
    return out
