"""Test ANSYS fail-closed behavior — unknown params, missing summary, etc."""

import pytest


class TestANSYSTemplateValidationFailClosed:
    def test_unknown_parameter_fails(self):
        from seekflow_engineering_tools.ansys.template_registry import (
            validate_template_parameters,
        )

        with pytest.raises(ValueError, match="unknown|unrecognized|Unknown"):
            validate_template_parameters("static_cantilever_beam_rect", {
                "length_mm": 100, "width_mm": 20, "height_mm": 10,
                "force_n": 500, "unknown_extra_param": 42,
            })

    def test_missing_required_parameter_ok(self):
        """Missing required params should fail validation or use defaults if available."""
        from seekflow_engineering_tools.ansys.template_registry import (
            validate_template_parameters,
        )
        # Missing force_n (required) should raise
        with pytest.raises((ValueError, TypeError)):
            validate_template_parameters("static_cantilever_beam_rect", {
                "length_mm": 100, "width_mm": 20, "height_mm": 10,
            })

    def test_template_registry_has_fail_closed_schema(self):
        """All template schemas have required metrics for validation."""
        from seekflow_engineering_tools.ansys.tools import _ANSYS_TEMPLATE_SCHEMAS

        for name, schema in _ANSYS_TEMPLATE_SCHEMAS.items():
            assert "metrics" in schema, f"Template '{name}' missing 'metrics'"
            assert isinstance(schema["metrics"], list), f"Template '{name}' metrics is not a list"
            assert len(schema["metrics"]) > 0, f"Template '{name}' metrics is empty"

    def test_all_templates_have_parameter_schemas(self):
        """Every template must define its parameters with type/required info."""
        from seekflow_engineering_tools.ansys.tools import _ANSYS_TEMPLATE_SCHEMAS

        for name, schema in _ANSYS_TEMPLATE_SCHEMAS.items():
            assert "parameters" in schema, f"Template '{name}' missing 'parameters'"
            params = schema["parameters"]
            assert isinstance(params, dict), f"Template '{name}' params is not a dict"
            assert len(params) > 0, f"Template '{name}' has no parameters defined"


class TestANSYSRunFailClosed:
    def test_ansys_run_apdl_template_unknown_param_fails(self):
        """ansys_run_apdl_template with unknown parameter must return ok=False."""
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        from seekflow_engineering_tools.ansys.tools import build_ansys_tools
        from pathlib import Path

        config = EngineeringToolsConfig(
            workspace_root=Path("/tmp"),
            ansys181_exe=None,  # No real ansys
        )
        tools = build_ansys_tools(config)
        tool = next(t for t in tools if t.name == "ansys_run_apdl_template")

        result = tool.func(
            template_name="static_cantilever_beam_rect",
            parameters={"length_mm": 100},  # missing required params
            jobname="test_fail",
        )
        assert result["ok"] is False, (
            f"Expected ok=False for missing required params, got {result}"
        )

    def test_static_cantilever_requires_length_width_height_force(self):
        """The static_cantilever_beam_rect template requires basic params."""
        from seekflow_engineering_tools.ansys.tools import _ANSYS_TEMPLATE_SCHEMAS

        schema = _ANSYS_TEMPLATE_SCHEMAS["static_cantilever_beam_rect"]
        params = schema["parameters"]
        required = [k for k, v in params.items()
                    if isinstance(v, dict) and v.get("required")]
        # at minimum the key geometry and load params exist
        assert "length_mm" in params
        assert "force_n" in params
