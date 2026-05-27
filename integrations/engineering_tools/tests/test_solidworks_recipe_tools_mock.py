"""Test SolidWorks tools without requiring actual SW installation."""

import pytest


class TestSolidWorksRecipeTools:
    def test_build_sw_tools_includes_flanged_hub(self):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.solidworks.tools import build_solidworks_tools

        config = EngineeringToolsConfig(solidworks_enabled=True)
        tools = build_solidworks_tools(config)
        tool_names = [t.name for t in tools]
        assert "solidworks_create_flanged_hub_part" in tool_names
        assert "solidworks_create_box_part" in tool_names
        assert "solidworks_health_check" in tool_names
        assert "solidworks_export_step" in tool_names
        assert "solidworks_import_step_as_part" in tool_names
        # Legacy gear tools must NOT be registered
        assert "solidworks_create_spur_gear_part" not in tool_names
        assert "solidworks_create_true_involute_gear_part" not in tool_names
        assert len(tools) == 5

    def test_build_sw_tools_all_have_policies(self):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.solidworks.tools import build_solidworks_tools

        config = EngineeringToolsConfig()
        tools = build_solidworks_tools(config)
        for t in tools:
            assert hasattr(t, "policy"), f"Tool '{t.name}' has no policy"
            assert t.policy.risk is not None, f"Tool '{t.name}' has no risk"

    def test_flanged_hub_tool_has_expected_description(self):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.solidworks.tools import build_solidworks_tools

        tools = build_solidworks_tools(EngineeringToolsConfig())
        hub_tool = next(
            t for t in tools if t.name == "solidworks_create_flanged_hub_part"
        )
        assert "flanged hub" in hub_tool.description.lower()
        assert hasattr(hub_tool, "func")

    def test_spur_gear_tool_has_expected_description(self):
        """Legacy spur_gear tool is removed; verify import_step_as_part exists instead."""
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.solidworks.tools import build_solidworks_tools

        tools = build_solidworks_tools(EngineeringToolsConfig())
        tool_names = {t.name for t in tools}
        # Legacy gear tools must NOT be present
        assert "solidworks_create_spur_gear_part" not in tool_names
        assert "solidworks_create_true_involute_gear_part" not in tool_names
        # STEP import tool must be present
        assert "solidworks_import_step_as_part" in tool_names

    def test_all_sw_tools_return_engineering_action_result(self):
        from seekflow_engineering_tools.common.models import EngineeringActionResult
        result = EngineeringActionResult(
            ok=True, software="solidworks", action="test",
        )
        assert result.software == "solidworks"

    def test_cadquery_backend_tools_exist(self):
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.cadquery_backend.tools import (
            build_cadquery_tools,
        )

        tools = build_cadquery_tools(EngineeringToolsConfig())
        tool_names = [t.name for t in tools]
        assert "cadquery_compile_cad_ir_to_script" in tool_names
        assert "cadquery_inspect_step" in tool_names

    def test_model_accepts_cadquery_software(self):
        from seekflow_engineering_tools.common.models import EngineeringActionResult
        result = EngineeringActionResult(
            ok=True, software="cadquery", action="compile",
        )
        assert result.software == "cadquery"

    def test_model_accepts_generic_software(self):
        from seekflow_engineering_tools.common.models import EngineeringActionResult
        result = EngineeringActionResult(
            ok=True, software="generic", action="validate",
        )
        assert result.software == "generic"
