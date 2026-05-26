"""SolidWorks tool tests (mock COM, no real SolidWorks needed)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.solidworks.tools import build_solidworks_tools


class TestSolidWorksTools:
    @pytest.fixture
    def config(self, tmp_path: Path):
        return EngineeringToolsConfig(
            workspace_root=tmp_path / "ws",
            solidworks_enabled=True,
            solidworks_visible=False,
            solidworks_part_template=tmp_path / "template.prtdot",
            allow_overwrite=False,
        )

    def test_health_check_tool_has_policy(self, config):
        tools = build_solidworks_tools(config)
        health = next(t for t in tools if t.name == "solidworks_health_check")
        assert health.policy is not None
        assert health.policy.risk == "read"

    def test_create_box_part_tool_has_policy(self, config):
        tools = build_solidworks_tools(config)
        box = next(t for t in tools if t.name == "solidworks_create_box_part")
        assert box.policy is not None
        assert box.policy.risk == "write"

    def test_export_step_tool_has_policy(self, config):
        tools = build_solidworks_tools(config)
        export = next(t for t in tools if t.name == "solidworks_export_step")
        assert export.policy is not None
        assert export.policy.risk == "write"

    def test_all_tools_have_policy(self, config):
        tools = build_solidworks_tools(config)
        for t in tools:
            assert t.policy is not None, f"{t.name} has no policy"
            assert t.policy.risk in ("read", "write", "destructive")

    def test_health_check_failure_when_com_unavailable(self, config):
        """When COM is not available, health_check should return ok=False."""
        tools = build_solidworks_tools(config)
        health = next(t for t in tools if t.name == "solidworks_health_check")

        with mock.patch(
            "seekflow_engineering_tools.solidworks.tools.SolidWorksClient",
            side_effect=Exception("COM not available"),
        ):
            result = health.func()
            assert result["ok"] is False
            assert result["software"] == "solidworks"
            assert "COM not available" in result["error"]
