import pytest
from seekflow_cfd.backends import MockBackend
from seekflow_cfd.models import CFDError
from seekflow_cfd.service import CFDService, register_mcp_tools
from seekflow_cfd.tools import ToolRegistry
from seekflow_cfd.topology import MockTopology


def test_service_job_roundtrip(spec, make_runner, tmp_path):
    service = CFDService(make_runner, tmp_path / "output", max_workers=1)
    try:
        task = service.submit(spec.model_dump(mode="json"))
        service.futures[task["job_id"]].result(timeout=10)
        assert service.status(task["job_id"])["status"] == "success"
        service.resume(task["job_id"])
        assert service.futures[task["job_id"]].result(timeout=10)["status"] == "success"
    finally:
        service.close()


def test_mcp_tools_register_independently(spec, make_runner, tmp_path):
    class MCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def register(fn):
                self.tools[fn.__name__] = fn
                return fn

            return register

    server = MCP()
    service = CFDService(make_runner, tmp_path / "output")
    try:
        topology = MockTopology(spec.geometry_ref, ["coolant_inlet"])
        register_mcp_tools(server, service, topology)
        assert len(server.tools) == 8
        result = server.tools["cfd_resolve_role_to_faces"]("coolant_inlet")
        assert result["status"] == "unique"
        assert "solver.advance" not in server.tools
    finally:
        service.close()


def test_tool_role_rejected_before_backend(tmp_path, spec):
    backend = MockBackend()
    registry = ToolRegistry(backend)
    assert len(registry.describe()) == 7
    with pytest.raises(CFDError):
        registry.invoke(
            "solver.advance",
            "physics_boundary",
            {"spec": spec.model_dump(mode="json")},
            tmp_path,
            10,
        )
    assert backend.calls == []


def test_http_api_contract(spec, make_runner, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from seekflow_cfd.api import create_app

    service = CFDService(make_runner, tmp_path / "output")
    try:
        with TestClient(create_app(service)) as client:
            assert client.get("/cfd/schema").status_code == 200
            assert client.post("/cfd/jobs", json={"unexpected": 1}).status_code == 422
            response = client.post("/cfd/jobs", json=spec.model_dump(mode="json"))
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            service.futures[job_id].result(timeout=10)
            assert client.get("/cfd/jobs/" + job_id).json()["status"] == "success"
    finally:
        service.close()
