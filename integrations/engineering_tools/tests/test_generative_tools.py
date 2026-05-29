"""Test generative CAD tool registration and behavior."""

import tempfile
from pathlib import Path

import pytest

from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.registry import (
    ENGINEERING_CAPABILITIES,
    build_engineering_tools,
)


class TestToolRegistration:
    def test_generative_capabilities_present(self):
        """Generative capabilities should be in ENGINEERING_CAPABILITIES."""
        assert "cad.generative.read" in ENGINEERING_CAPABILITIES
        assert "cad.generative.write" in ENGINEERING_CAPABILITIES

    def test_generative_tools_registered(self):
        """build_engineering_tools should include generative tools."""
        with tempfile.TemporaryDirectory() as tmp:
            config = EngineeringToolsConfig(
                workspace_root=Path(tmp),
                solidworks_enabled=False,
                nx_enabled=False,
                ansys_enabled=False,
            )
            tools = build_engineering_tools(config)
            tool_names = [t.name for t in tools]

            assert "generative_cad_list_bases" in tool_names
            assert "generative_cad_get_base_contract" in tool_names
            assert "generative_cad_validate_ir" in tool_names
            assert "generative_cad_build_from_ir" in tool_names

    def test_existing_tool_names_unchanged(self):
        """Existing CadQuery tool names should not change."""
        with tempfile.TemporaryDirectory() as tmp:
            config = EngineeringToolsConfig(
                workspace_root=Path(tmp),
                solidworks_enabled=False,
                nx_enabled=False,
                ansys_enabled=False,
            )
            tools = build_engineering_tools(config)
            tool_names = [t.name for t in tools]

            # Existing tools still there
            assert "cadquery_compile_cad_ir_to_script" in tool_names
            assert "cadquery_build_from_cad_ir" in tool_names
            assert "cadquery_inspect_step" in tool_names
