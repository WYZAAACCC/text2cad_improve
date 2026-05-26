"""Test NX tools with mocked job queue -- no NX installation needed."""

import pytest


class TestNXToolsRegistration:
    def test_build_nx_tools_includes_all_tools(self):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools

        config = EngineeringToolsConfig(nx_enabled=True)
        tools = build_nx_tools(config)
        tool_names = [t.name for t in tools]
        assert "nx_health_check" in tool_names
        assert "nx_create_block_part" in tool_names
        assert "nx_create_block_with_hole" in tool_names
        assert "nx_create_l_bracket" in tool_names
        assert "nx_create_stepped_block" in tool_names
        assert "nx_export_step" in tool_names
        assert len(tools) == 6

    def test_build_nx_tools_all_have_policies(self):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools

        tools = build_nx_tools(EngineeringToolsConfig())
        for t in tools:
            assert hasattr(t, "policy"), f"Tool '{t.name}' has no policy"
            assert t.policy.risk is not None, f"Tool '{t.name}' has no risk"

    def test_nx_create_block_with_hole_has_description(self):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools

        tools = build_nx_tools(EngineeringToolsConfig())
        tool = next(t for t in tools if t.name == "nx_create_block_with_hole")
        assert "through-hole" in tool.description.lower()
        assert hasattr(tool, "func")

    def test_nx_create_l_bracket_has_description(self):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools

        tools = build_nx_tools(EngineeringToolsConfig())
        tool = next(t for t in tools if t.name == "nx_create_l_bracket")
        assert "l-bracket" in tool.description.lower()
        assert hasattr(tool, "func")

    def test_nx_create_stepped_block_has_description(self):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools

        tools = build_nx_tools(EngineeringToolsConfig())
        tool = next(t for t in tools if t.name == "nx_create_stepped_block")
        assert "stepped block" in tool.description.lower()
        assert hasattr(tool, "func")


class TestNXJobQueueMock:
    def test_submit_and_wait_mocked(self, monkeypatch, tmp_path):
        submitted = {}

        class FakeQueue:
            def __init__(self, root):
                self.root = root
            def submit(self, action, params):
                submitted["action"] = action
                submitted["params"] = params
                return "job_123"
            def wait(self, job_id, timeout_s):
                return {
                    "ok": True, "files_created": ["test.prt"],
                    "metrics": {"type": "l_bracket"}, "error": None,
                }

        monkeypatch.setattr(
            "seekflow_engineering_tools.nx.tools.NXJobQueue", FakeQueue,
        )

        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools

        config = EngineeringToolsConfig(
            nx_enabled=True, workspace_root=tmp_path, allow_overwrite=True,
        )
        tools = build_nx_tools(config)
        l_bracket_tool = next(
            t for t in tools if t.name == "nx_create_l_bracket"
        )

        result = l_bracket_tool.func(
            base_length_mm=100, base_width_mm=60,
            thickness_mm=15, leg_height_mm=60,
            out_prt=str(tmp_path / "bracket.prt"),
        )

        assert result["ok"] is True
        assert submitted["action"] == "create_l_bracket"
        assert submitted["params"]["base_length"] == 100
        assert submitted["params"]["base_width"] == 60

    def test_block_with_hole_submits_correct_action(self, monkeypatch, tmp_path):
        submitted = {}

        class FakeQueue:
            def __init__(self, root):
                self.root = root
            def submit(self, action, params):
                submitted["action"] = action
                submitted["params"] = params
                return "job_456"
            def wait(self, job_id, timeout_s):
                return {"ok": True, "files_created": ["test.prt"], "metrics": {}, "error": None}

        monkeypatch.setattr(
            "seekflow_engineering_tools.nx.tools.NXJobQueue", FakeQueue,
        )

        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools

        config = EngineeringToolsConfig(
            nx_enabled=True, workspace_root=tmp_path, allow_overwrite=True,
        )
        tools = build_nx_tools(config)
        tool = next(t for t in tools if t.name == "nx_create_block_with_hole")

        result = tool.func(
            length_mm=100, width_mm=60, height_mm=40,
            hole_dia_mm=16, hole_x_mm=50, hole_z_mm=30,
            out_prt=str(tmp_path / "block_hole.prt"),
        )

        assert result["ok"] is True
        assert submitted["action"] == "create_block_with_hole"
        assert submitted["params"]["hole_dia_mm"] == 16

    def test_stepped_block_submits_correct_action(self, monkeypatch, tmp_path):
        submitted = {}

        class FakeQueue:
            def __init__(self, root):
                self.root = root
            def submit(self, action, params):
                submitted["action"] = action
                submitted["params"] = params
                return "job_789"
            def wait(self, job_id, timeout_s):
                return {"ok": True, "files_created": ["test.prt"], "metrics": {}, "error": None}

        monkeypatch.setattr(
            "seekflow_engineering_tools.nx.tools.NXJobQueue", FakeQueue,
        )

        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools

        config = EngineeringToolsConfig(
            nx_enabled=True, workspace_root=tmp_path, allow_overwrite=True,
        )
        tools = build_nx_tools(config)
        tool = next(t for t in tools if t.name == "nx_create_stepped_block")

        result = tool.func(
            base_length_mm=80, base_width_mm=80, base_height_mm=20,
            top_length_mm=60, top_width_mm=60, top_height_mm=30,
            out_prt=str(tmp_path / "stepped.prt"),
        )

        assert result["ok"] is True
        assert submitted["action"] == "create_stepped_block"

    def test_error_when_overwrite_disabled(self, tmp_path):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools

        out_file = tmp_path / "block.prt"
        out_file.write_text("existing")

        config = EngineeringToolsConfig(
            nx_enabled=True, workspace_root=tmp_path, allow_overwrite=False,
        )
        tools = build_nx_tools(config)
        tool = next(t for t in tools if t.name == "nx_create_block_part")

        result = tool.func(
            length_mm=100, width_mm=50, height_mm=30,
            out_prt="block.prt",
        )

        assert result["ok"] is False
        assert "already exists" in result["error"]

    def test_nx_health_check_reports_bridge_status(self, tmp_path):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.nx.tools import build_nx_tools

        config = EngineeringToolsConfig(
            nx_enabled=True, nx_job_root=tmp_path / "nx_jobs",
        )
        tools = build_nx_tools(config)
        health_tool = next(t for t in tools if t.name == "nx_health_check")

        result = health_tool.func()

        assert result["ok"] is True
        assert "metrics" in result
        assert "job_root" in result["metrics"]
        assert "bridge_running" in result["metrics"]
