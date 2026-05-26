"""Test that natural language and CadQuery tools are properly registered."""

from __future__ import annotations

from pathlib import Path

from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.registry import build_engineering_tools


class TestNaturalLanguageAndCadQueryToolsRegistered:
    """Verify all required tools are registered by build_engineering_tools."""

    def test_all_required_tool_names_present(self, tmp_path: Path):
        config = EngineeringToolsConfig(
            workspace_root=tmp_path / "ws",
            solidworks_enabled=False,
            nx_enabled=False,
            ansys_enabled=False,
        )
        tools = build_engineering_tools(config)
        names = {t.name for t in tools}

        required = {
            "engineering_validate_cad_ir",
            "engineering_build_cad_model",
            "cadquery_build_from_cad_ir",
            "cadquery_compile_cad_ir_to_script",
            "cadquery_inspect_step",
        }
        missing = required - names
        assert not missing, f"Missing tools: {missing}"

    def test_natural_language_tools_registered_without_hardware(self, tmp_path: Path):
        config = EngineeringToolsConfig(
            workspace_root=tmp_path / "ws",
            solidworks_enabled=False,
            nx_enabled=False,
            ansys_enabled=False,
        )
        tools = build_engineering_tools(config)
        names = {t.name for t in tools}
        assert "engineering_validate_cad_ir" in names
        assert "engineering_build_cad_model" in names

    def test_cadquery_tools_registered_without_hardware(self, tmp_path: Path):
        config = EngineeringToolsConfig(
            workspace_root=tmp_path / "ws",
            solidworks_enabled=False,
            nx_enabled=False,
            ansys_enabled=False,
        )
        tools = build_engineering_tools(config)
        names = {t.name for t in tools}
        assert "cadquery_build_from_cad_ir" in names
        assert "cadquery_compile_cad_ir_to_script" in names
        assert "cadquery_inspect_step" in names
