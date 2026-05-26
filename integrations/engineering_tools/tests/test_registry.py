"""Registry / agent integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.registry import (
    ENGINEERING_CAPABILITIES,
    build_engineering_tools,
)
from seekflow_engineering_tools.common.models import EngineeringActionResult


class TestBuildEngineeringTools:
    def test_returns_empty_list_when_all_disabled(self, tmp_path: Path):
        config = EngineeringToolsConfig(
            workspace_root=tmp_path / "ws",
            solidworks_enabled=False,
            nx_enabled=False,
            ansys_enabled=False,
        )
        tools = build_engineering_tools(config)
        assert tools == []

    def test_returns_ansys_tools_when_enabled(self, tmp_path: Path):
        config = EngineeringToolsConfig(
            workspace_root=tmp_path / "ws",
            solidworks_enabled=False,
            nx_enabled=False,
            ansys_enabled=True,
            ansys181_exe=tmp_path / "ansys.exe",
        )
        (tmp_path / "ansys.exe").write_text("")
        tools = build_engineering_tools(config)
        names = {t.name for t in tools}
        assert "ansys_health_check" in names

    def test_returns_solidworks_tools_when_enabled(self, tmp_path: Path):
        config = EngineeringToolsConfig(
            workspace_root=tmp_path / "ws",
            solidworks_enabled=True,
            nx_enabled=False,
            ansys_enabled=False,
        )
        tools = build_engineering_tools(config)
        names = {t.name for t in tools}
        assert "solidworks_health_check" in names

    def test_returns_nx_tools_when_enabled(self, tmp_path: Path):
        config = EngineeringToolsConfig(
            workspace_root=tmp_path / "ws",
            solidworks_enabled=False,
            nx_enabled=True,
            ansys_enabled=False,
        )
        tools = build_engineering_tools(config)
        names = {t.name for t in tools}
        assert "nx_health_check" in names

    def test_all_tools_are_valid_tool_definitions(self, tmp_path: Path):
        (tmp_path / "ansys.exe").write_text("")
        config = EngineeringToolsConfig(
            workspace_root=tmp_path / "ws",
            solidworks_enabled=True,
            nx_enabled=True,
            ansys_enabled=True,
            ansys181_exe=tmp_path / "ansys.exe",
        )
        tools = build_engineering_tools(config)
        assert len(tools) > 0
        for t in tools:
            assert t.name
            assert t.description
            assert t.parameters
            assert t.policy is not None


class TestCapabilities:
    def test_all_required_capabilities_present(self):
        required = {
            "filesystem.read",
            "filesystem.write",
            "cad.solidworks.read",
            "cad.solidworks.write",
            "cad.nx.read",
            "cad.nx.write",
            "cae.ansys.read",
            "cae.ansys.write",
            "cae.ansys.solve",
        }
        assert ENGINEERING_CAPABILITIES == required


class TestEngineeringActionResult:
    def test_ok_result(self):
        r = EngineeringActionResult(
            ok=True,
            software="ansys",
            action="health_check",
            message="all good",
        )
        d = r.model_dump()
        assert d["ok"] is True
        assert d["error"] is None

    def test_failure_result(self):
        r = EngineeringActionResult(
            ok=False,
            software="solidworks",
            action="create_box_part",
            error="COM dispatch failed",
        )
        d = r.model_dump()
        assert d["ok"] is False
        assert d["error"] == "COM dispatch failed"
