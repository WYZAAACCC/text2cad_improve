"""The audit, budget and resume machinery, before any stage depends on it.

Everything here is a guarantee a later stage will lean on. If the hash chain
does not detect an edited event, then "the audit trail says this ran" means
nothing. If `confined` lets a path escape, then a job can write outside itself.
If resume does not notice a different model, it will happily continue a job
against the wrong geometry and nothing downstream will object.
"""
from __future__ import annotations

import json

import pytest

from seekflow_structural.case.model import (
    BundleRef,
    Case,
    DomainDecision,
    LoadSurface,
    MeshPlan,
    ModelFacts,
    Physics,
    SolveRecord,
    Vec3,
    Written,
)
from seekflow_structural.case.store import CaseStore
from seekflow_structural.cli import _confirmation_gate
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.orchestrator import (
    Budget,
    Orchestrator,
    RunContext,
)
from seekflow_structural.pipeline.stages import STAGE_ORDER, Stage
from seekflow_structural.runtime.store import JobStore, atomic_json, confined


def _written(group: str) -> Written:
    return Written(by_stage="test", kind="derived", source=group)


def a_case(
    name: str = "unit",
    bundle_path: str = "/tmp/bundle",
    *,
    complete: bool = True,
    omit: str | None = None,
) -> Case:
    """A case with every group the stage requirements ask for.

    `omit` drops one group so a test can check the rejection names it.
    """
    zero = Vec3(x=0.0, y=0.0, z=0.0)

    def group(field: str):
        if not complete or omit == field:
            return None
        return {
            "model": ModelFacts(
                bounds_min_mm=zero, bounds_max_mm=zero, r_max_mm=1.0,
                written=_written("model"),
            ),
            "domain": DomainDecision(written=_written("domain")),
            "load_surface": LoadSurface(
                feature="f", written=_written("load_surface")
            ),
            "physics": Physics(written=_written("physics")),
            "mesh": MeshPlan(written=_written("mesh")),
            "solve": SolveRecord(written=_written("solve")),
        }[field]

    return Case(
        case_id=name,
        bundle=BundleRef(path=bundle_path, lineage_id="D", revision_id="rev-1"),
        model=group("model"),
        domain=group("domain"),
        load_surface=group("load_surface"),
        physics=group("physics"),
        mesh=group("mesh"),
        solve=group("solve"),
    )


def all_noop(orchestrator: Orchestrator) -> None:
    """Register a do-nothing stage for everything the loop will reach."""
    for stage in STAGE_ORDER:
        if stage in (Stage.PREFLIGHT, Stage.COMPLETE):
            continue
        orchestrator.register(stage, lambda ctx: None)


# --- storage ---------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["../escape", "a/../../b", "C:/abs", "a\\b", "/abs/path"]
)
def test_confined_refuses_anything_that_could_escape(tmp_path, bad):
    with pytest.raises(StructuralError) as exc:
        confined(tmp_path, bad)
    assert exc.value.diagnostic.code == "unsafe_path"


def test_confined_accepts_a_plain_relative_path(tmp_path):
    assert confined(tmp_path, "calls/abc.json") == (
        tmp_path.resolve() / "calls" / "abc.json"
    )


@pytest.mark.parametrize("bad", ["", "has space", "a/b", "semi;colon"])
def test_job_id_is_restricted_to_a_safe_alphabet(tmp_path, bad):
    with pytest.raises(StructuralError) as exc:
        JobStore(tmp_path, bad)
    assert exc.value.diagnostic.code == "invalid_job_id"


def test_atomic_json_leaves_no_temporary_behind(tmp_path):
    target = tmp_path / "state.json"
    atomic_json(target, {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


# --- audit -----------------------------------------------------------------


def test_the_event_chain_detects_an_edited_event(tmp_path):
    job = JobStore(tmp_path, "j")
    job.event({"kind": "one"})
    job.event({"kind": "two"})
    job.verify_events()

    path = job.path / "events.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["kind"] = "something else"
    lines[0] = json.dumps(tampered, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(StructuralError) as exc:
        job.verify_events()
    assert exc.value.diagnostic.code == "audit_corrupt"


def test_the_event_chain_detects_a_removed_event(tmp_path):
    job = JobStore(tmp_path, "j")
    job.event({"kind": "one"})
    job.event({"kind": "two"})
    path = job.path / "events.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[1] + "\n", encoding="utf-8")

    with pytest.raises(StructuralError):
        job.verify_events()


def test_the_manifest_notices_a_changed_artifact(tmp_path):
    job = JobStore(tmp_path, "j")
    job.write("calls/a.json", {"x": 1})
    job.write("manifest.json", job.manifest(10_000_000))
    job.verify_manifest()

    job.write("calls/a.json", {"x": 2})
    with pytest.raises(StructuralError) as exc:
        job.verify_manifest()
    assert exc.value.diagnostic.code == "artifact_changed"


# --- budgets ---------------------------------------------------------------


def test_the_tool_budget_is_enforced(tmp_path):
    job = JobStore(tmp_path, "j")
    ctx = RunContext(
        job=job, case_store=CaseStore(job), budget=Budget(max_tool_calls=2)
    )
    ctx.tool_call()
    ctx.tool_call()
    with pytest.raises(StructuralError) as exc:
        ctx.tool_call()
    assert exc.value.diagnostic.code == "tool_budget"


def test_the_output_budget_is_enforced(tmp_path):
    job = JobStore(tmp_path, "j")
    job.write("big.json", {"pad": "x" * 5000})
    with pytest.raises(StructuralError) as exc:
        job.manifest(100)
    assert exc.value.diagnostic.code == "output_budget"


def test_a_cancel_request_stops_the_run(tmp_path):
    job = JobStore(tmp_path, "j")
    (job.path / "cancel.request").write_text("", encoding="utf-8")
    ctx = RunContext(job=job, case_store=CaseStore(job), budget=Budget())
    with pytest.raises(StructuralError) as exc:
        ctx.check_wall_time()
    assert exc.value.diagnostic.code == "cancelled"


# --- confirmation gate -----------------------------------------------------


def test_unconfirmed_inputs_need_an_explicit_override():
    with pytest.raises(StructuralError) as exc:
        _confirmation_gate({"confirmation_status": "unconfirmed"}, False)
    assert exc.value.diagnostic.code == "needs_confirmation"


def test_the_override_stamps_the_run_as_synthetic():
    assert _confirmation_gate(
        {"confirmation_status": "unconfirmed_synthetic"}, True
    ) == "synthetic_or_unconfirmed_pipeline_validation"


def test_a_confirmed_case_needs_no_override():
    assert _confirmation_gate(
        {"confirmation_status": "confirmed"}, False
    ) == "confirmed_case"


def test_a_missing_status_is_treated_as_unconfirmed():
    with pytest.raises(StructuralError):
        _confirmation_gate({}, False)


# --- the run loop ----------------------------------------------------------


def test_a_run_walks_every_stage_and_records_what_it_did(tmp_path):
    orchestrator = Orchestrator(tmp_path, budget=Budget())
    all_noop(orchestrator)
    record = orchestrator.run("job1", case=a_case())

    assert record["status"] == "success"
    job = JobStore(tmp_path, "job1")
    assert job.exists("case.json")
    assert job.exists("state.json")
    assert job.exists("manifest.json")
    assert job.exists("record.json")
    job.verify_events()
    job.verify_manifest()

    events = job.events()
    assert events[0]["kind"] == "run_start"
    assert events[-1]["kind"] == "run_end"
    stages = [e["stage"] for e in events if e["kind"] == "stage_complete"]
    assert stages == [s.value for s in STAGE_ORDER]


def test_a_stage_that_is_not_registered_fails_by_name(tmp_path):
    """An unfinished chain says which stage is missing, not that it crashed."""
    orchestrator = Orchestrator(tmp_path, budget=Budget())
    with pytest.raises(StructuralError) as exc:
        orchestrator.run("job1", case=a_case())
    assert exc.value.diagnostic.code == "stage_not_registered"
    assert exc.value.diagnostic.stage == "frame"


def test_a_stage_that_needs_a_missing_group_is_rejected(tmp_path):
    """Not an attribute error deep inside - a named rejection."""
    orchestrator = Orchestrator(tmp_path, budget=Budget())
    all_noop(orchestrator)
    # `mesh` requires load_surface; the case has none.
    with pytest.raises(StructuralError) as exc:
        orchestrator.run("job1", case=a_case(omit="load_surface"))
    assert exc.value.diagnostic.code == "case_incomplete"
    assert "load_surface" in exc.value.diagnostic.message


def test_rerunning_a_finished_job_is_refused(tmp_path):
    orchestrator = Orchestrator(tmp_path, budget=Budget())
    all_noop(orchestrator)
    orchestrator.run("job1", case=a_case())
    with pytest.raises(StructuralError) as exc:
        orchestrator.run("job1", case=a_case())
    assert exc.value.diagnostic.code == "job_exists"


def test_resume_on_a_different_bundle_is_refused(tmp_path):
    orchestrator = Orchestrator(tmp_path, budget=Budget())
    all_noop(orchestrator)
    orchestrator.run("job1", case=a_case(bundle_path="/tmp/one"))
    with pytest.raises(StructuralError) as exc:
        orchestrator.run(
            "job1", case=a_case(bundle_path="/tmp/two"), resume=True
        )
    assert exc.value.diagnostic.code == "resume_mismatch"


def test_resume_continues_from_the_stored_case(tmp_path):
    orchestrator = Orchestrator(tmp_path, budget=Budget())
    all_noop(orchestrator)
    orchestrator.run("job1", case=a_case())

    seen: list[str] = []

    def record_stage(ctx):
        seen.append(ctx.stage.value)

    fresh = Orchestrator(tmp_path, budget=Budget())
    all_noop(fresh)
    fresh.register(Stage.VERIFY, record_stage)
    fresh.run("job1", case=a_case(), resume=True)

    # verify is the last real stage, so a finished job resumes into nothing
    # but complete - the point is that it did not re-run the whole chain.
    assert seen == []
    state = JobStore(tmp_path, "job1").read("state.json")
    assert state["stage"] == "complete"


def test_stage_hashes_are_recorded_per_stage(tmp_path):
    orchestrator = Orchestrator(tmp_path, budget=Budget())
    all_noop(orchestrator)
    orchestrator.run("job1", case=a_case())
    hashes = JobStore(tmp_path, "job1").read("state.json")["stage_hashes"]
    assert set(hashes) == {s.value for s in STAGE_ORDER}
    # every stage over an unchanged case hashes the same
    assert len(set(hashes.values())) == 1
