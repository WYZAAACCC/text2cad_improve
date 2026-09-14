import pytest
from seekflow_cfd.backends import MockBackend
from seekflow_cfd.models import CFDError
from seekflow_cfd.reporting import aggregate
from seekflow_cfd.storage import JobStore


def test_end_to_end_and_audit(spec, make_runner):
    runner = make_runner()
    result = runner.run(spec, job_id="e2e")
    assert result["status"] == "success", result
    assert result["is_mock"] and result["requires_manual_review"]
    assert result["metrics"]["outlet_pressure"]["unit"] == "Pa"
    assert result["solver_log_summary"]["convergence"]["state"] == "converged"
    assert not result["mesh_independence"]["verified"]
    store = JobStore(runner.output_root, "e2e")
    store.verify_events()
    store.verify_manifest()
    assert (store.path / "residuals.svg").is_file()
    assert aggregate(runner.output_root)["real_success_rate"] is None


@pytest.mark.parametrize(
    "fault,code",
    [
        ("bad_mesh", "mesh_quality"),
        ("stagnation", "stagnated"),
        ("mass_imbalance", "iteration_budget"),
    ],
)
def test_failure_never_succeeds(spec, make_runner, fault, code):
    backend = MockBackend(fault)
    record = make_runner(backend).run(spec)
    assert record["status"] == "failed", record
    assert record["diagnostic"]["code"] == code
    assert record["metrics"] == {}
    if fault == "bad_mesh":
        assert "solver.initialize" not in backend.calls


def test_missing_confirmation(spec, make_runner):
    spec.expert_confirmed = False
    backend = MockBackend()
    record = make_runner(backend).run(spec)
    assert record["status"] == "rejected"
    assert not backend.calls


def test_tool_budget(spec, make_runner):
    spec.budget.max_tool_calls = 3
    record = make_runner().run(spec)
    assert record["diagnostic"]["code"] == "tool_budget"


def test_capability_gap(spec, make_runner):
    backend = MockBackend()
    backend.capabilities = backend.capabilities.model_copy(deep=True)
    backend.capabilities.mesh_methods = []
    record = make_runner(backend).run(spec)
    assert record["status"] == "capability_gap"
    assert not backend.calls


def test_pause_resume_and_replay(spec, make_runner):
    runner = make_runner()
    paused = runner.run(spec, job_id="resume", pause_after="solver")
    assert paused["status"] == "paused"
    assert runner.run(spec, job_id="resume", resume=True)["status"] == "success"
    result = runner.run(spec, job_id="replay")
    assert (
        result["metrics"] == runner.run(spec, job_id="resume", resume=True)["metrics"]
    )
    assert result["record_id"] != paused["record_id"]


def test_modified_artifact_blocks_resume(spec, make_runner):
    runner = make_runner()
    runner.run(spec, job_id="tamper", pause_after="mesh")
    (runner.output_root / "jobs/tamper/mesh_report.json").write_text("{}")
    with pytest.raises(CFDError, match="modified"):
        runner.run(spec, job_id="tamper", resume=True)


def test_changed_spec_blocks_resume(spec, make_runner):
    runner = make_runner()
    runner.run(spec, job_id="mismatch", pause_after="mesh")
    spec.solver_control.relaxation = 0.2
    with pytest.raises(CFDError):
        runner.run(spec, job_id="mismatch", resume=True)


def test_path_escape_rejected(spec, make_runner):
    with pytest.raises(CFDError):
        make_runner().run(spec, job_id="../../escape")


def test_stale_mesh_blocks_solver(spec, make_runner):
    class Stale(MockBackend):
        def execute(self, operation, *args):
            out = super().execute(operation, *args)
            if operation == "mesh.generate":
                out["spec_hash"] = "f" * 64
            return out

    backend = Stale()
    r = make_runner(backend).run(spec)
    assert r["diagnostic"]["code"] == "mesh_binding_mismatch"
    assert "solver.initialize" not in backend.calls


def test_missing_logs_blocks_success(spec, make_runner):
    class Missing(MockBackend):
        def execute(self, operation, *args):
            out = super().execute(operation, *args)
            if operation == "solver.advance":
                out["log_paths"] = ["absent.log"]
            return out

    assert make_runner(Missing()).run(spec)["diagnostic"]["code"] == "missing_artifact"


def test_repair_budget_and_hard_inputs(spec, make_runner):
    backend = MockBackend("bad_mesh")
    spec.allowed_repairs = ["refine_mesh"]
    spec.budget.max_repairs = 1
    r = make_runner(backend).run(spec)
    assert backend.calls.count("mesh.generate") == 2
    assert r["status"] == "failed"
    assert r["simulation_spec"]["physics_spec"] == spec.physics_spec.model_dump(
        mode="json"
    )
    assert r["simulation_spec"]["boundary_specs"] == [
        b.model_dump(mode="json") for b in spec.boundary_specs
    ]


def test_unproved_domain_transfer_rejected(spec, make_runner):
    class Wrong(MockBackend):
        def execute(self, operation, *args):
            out = super().execute(operation, *args)
            if operation == "domain.construct":
                old = out["boundary_map"]["inlet"]["entity_ids"][0]
                out["boundary_map"]["inlet"]["entity_ids"] = ["wrong"]
                out["exterior_entity_ids"] = [
                    "wrong" if k == old else k for k in out["exterior_entity_ids"]
                ]
            return out

    assert make_runner(Wrong()).run(spec)["diagnostic"]["code"] == "domain_history"


def test_output_budget_is_structured(spec, make_runner):
    spec.budget.max_output_bytes = 100
    result = make_runner().run(spec)
    assert result["status"] == "failed"
    assert result["diagnostic"]["code"] == "output_budget"
