import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from seekflow_cfd.agents import ExpertTeam
from seekflow_cfd.backends import OPERATIONS, Capabilities
from seekflow_cfd.local import LocalWorkerBackend
from seekflow_cfd.models import CFDError
from seekflow_cfd.process import run_worker


class FakeCaller:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def call_strict_tool(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(arguments=self.data)


def test_agent_plan_cannot_self_approve(spec):
    caller = FakeCaller(
        {
            "disposition": "ready",
            "summary": "plan",
            "spec": spec.model_dump(mode="json"),
        }
    )
    team = ExpertTeam(caller, None)
    proposal = team.plan("cooling flow", spec.geometry_ref, [])
    assert not proposal.spec.expert_confirmed
    assert team.trace[0]["output_hash"]
    assert "tool_schema" in caller.calls[0]


def test_agent_missing_inputs_and_budget(spec):
    caller = FakeCaller(
        {
            "disposition": "needs_input",
            "summary": "missing inlet",
            "questions": ["What is the mass flow?"],
        }
    )
    team = ExpertTeam(caller, None, max_calls=1)
    assert team.plan("flow", spec.geometry_ref, []).questions
    with pytest.raises(CFDError):
        team.plan("flow", spec.geometry_ref, [])


def test_all_expert_roles_review(spec):
    caller = FakeCaller({"decision": "accept", "rationale": "test only"})
    team = ExpertTeam(caller, None)
    trace = team.review(spec)
    assert len(trace) == 5 and len({e["agent"] for e in trace}) == 5


def test_review_normalizes_null_questions_and_rationale_alias(spec):
    caller = FakeCaller(
        {
            "decision": "accept",
            "rationalive": "accepted after review",
            "questions": None,
        }
    )
    review = ExpertTeam(caller, None).review_results(spec, {}, {})
    assert review.rationale == "accepted after review"
    assert review.questions == []


def test_agent_cannot_mutate_hard_boundary(spec):
    caller = FakeCaller(
        {
            "disposition": "ready",
            "summary": "plan",
            "spec": spec.model_dump(mode="json"),
        }
    )
    with pytest.raises(CFDError):
        ExpertTeam(caller, None).plan(
            "flow", spec.geometry_ref, [], {"solver_control": {"max_iterations": 1}}
        )


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not Path("/proc/self/stat").is_file(),
    reason="Linux process supervisor",
)
def test_worker_timeout_kills_process_group(tmp_path):
    script = tmp_path / "sleep_worker.py"
    script.write_text("import time\ntime.sleep(30)\n")
    with pytest.raises(CFDError) as error:
        run_worker(
            [sys.executable, str(script)], tmp_path, 0.2, 1, 256, 100000, "sleep"
        )
    assert error.value.diagnostic.status == "timeout"


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not Path("/proc/self/stat").is_file(),
    reason="Linux process supervisor",
)
def test_worker_command_no_shell_or_credentials(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text(
        "import os,sys,json\nprint(json.dumps({'arg':sys.argv[1],'secret':os.getenv('DEEPSEEK_API_KEY')}))\n"
    )
    run_worker(
        [sys.executable, str(script), "$(touch should_not_exist)"],
        tmp_path,
        5,
        1,
        256,
        100000,
        "literal",
    )
    data = json.loads((tmp_path / "literal.stdout").read_text())
    assert data["arg"] == "$(touch should_not_exist)" and data["secret"] is None
    assert not (tmp_path / "should_not_exist").exists()


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not Path("/proc/self/stat").is_file(),
    reason="Linux process supervisor",
)
def test_ansys_stub_returns_capability_gap(tmp_path, spec):
    capabilities = Capabilities(
        name="ansys-local",
        version="site-1",
        is_mock=False,
        operations=list(OPERATIONS),
        domain_strategies=["extract"],
        mesh_methods=["tetra"],
        turbulence_models=["laminar"],
        heat_models=["isothermal"],
        time_modes=["steady"],
        rotation_models=["none"],
        resource_limits_enforced=True,
    )
    script = Path(__file__).parents[1] / "examples/ansys_worker.py"
    backend = LocalWorkerBackend([sys.executable, str(script)], capabilities)
    with pytest.raises(CFDError) as error:
        backend.execute(
            "domain.construct", {"spec": spec.model_dump(mode="json")}, tmp_path, 10
        )
    assert error.value.diagnostic.status == "capability_gap"


def test_output_path_boundary(tmp_path):
    from seekflow_cfd.storage import confined

    for path in ["../secret", "/etc/passwd", "C:\\secret", "a\\..\\secret"]:
        with pytest.raises(CFDError):
            confined(tmp_path, path)


def test_unavailable_isolation_is_capability_gap(tmp_path):
    if Path("/proc/self/stat").is_file() and sys.platform.startswith("linux"):
        pytest.skip("This platform has the default isolation facilities")
    if sys.platform.startswith("win"):
        import importlib.util

        if importlib.util.find_spec("win32job") is not None:
            pytest.skip("This platform has the Windows Job Object supervisor")
    with pytest.raises(CFDError) as error:
        run_worker([sys.executable], tmp_path, 1, 1, 256, 10000, "unavailable")
    assert error.value.diagnostic.status == "capability_gap"


def test_local_worker_rpc_without_solver(tmp_path, spec):
    # Protocol test only, not a certification of resource isolation.
    import subprocess

    from seekflow_cfd.storage import atomic_json

    script = Path(__file__).parents[1] / "examples/ansys_worker.py"
    atomic_json(
        tmp_path / "request.json",
        {
            "protocol": "cfd_worker_v1",
            "call_id": "test",
            "input_hash": "abc",
            "operation": "domain.construct",
            "payload": {"spec": spec.model_dump(mode="json")},
        },
    )
    subprocess.run(
        [sys.executable, str(script), "request.json", "response.json"],
        cwd=tmp_path,
        check=True,
        timeout=10,
    )
    data = json.loads((tmp_path / "response.json").read_text())
    assert data["error"]["status"] == "capability_gap"
    assert data["call_id"] == "test"
