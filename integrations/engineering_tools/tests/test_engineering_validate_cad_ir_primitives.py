"""Test engineering_validate_cad_ir with primitive features."""

import pytest


def test_validate_primitive_fills_defaults():
    from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from pathlib import Path

    config = EngineeringToolsConfig(workspace_root=Path("/tmp"))
    tools_list = build_natural_language_tools(config)
    validate_tool = next(t for t in tools_list if t.name == "engineering_validate_cad_ir")
    validate_fn = getattr(validate_tool, "func", validate_tool)  # ToolDefinition.func

    result = validate_fn({
        "name": "test_gear", "units": "mm",
        "features": [{"id": "g1", "type": "primitive",
                       "primitive_name": "involute_spur_gear",
                       "parameters": {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}}],
    })

    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    metrics = result.get("metrics", {})
    norm_params = metrics.get("normalized_parameters", {}).get("g1", {})
    assert norm_params.get("pressure_angle_deg") == 20.0
    assert norm_params.get("addendum_coefficient") == 1.0
    assert norm_params.get("clearance_coefficient") == 0.25
    assert norm_params.get("quality_grade") == "industrial_brep"


def test_validate_primitive_rejects_unknown_parameter():
    from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from pathlib import Path

    config = EngineeringToolsConfig(workspace_root=Path("/tmp"))
    tools_list = build_natural_language_tools(config)
    validate_tool = next(t for t in tools_list if t.name == "engineering_validate_cad_ir")
    validate_fn = getattr(validate_tool, "func", validate_tool)  # ToolDefinition.func

    result = validate_fn({
        "name": "test_gear", "units": "mm",
        "features": [{"id": "g1", "type": "primitive",
                       "primitive_name": "involute_spur_gear",
                       "parameters": {"module_mm": 2.0, "teeth": 24,
                                       "face_width_mm": 15.0, "foo": 123}}],
    })

    assert result["ok"] is False, f"Expected ok=False for unknown param, got: {result}"


def test_validate_primitive_rejects_teeth_lt_6():
    from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from pathlib import Path

    config = EngineeringToolsConfig(workspace_root=Path("/tmp"))
    tools_list = build_natural_language_tools(config)
    validate_tool = next(t for t in tools_list if t.name == "engineering_validate_cad_ir")
    validate_fn = getattr(validate_tool, "func", validate_tool)  # ToolDefinition.func

    result = validate_fn({
        "name": "test_gear", "units": "mm",
        "features": [{"id": "g1", "type": "primitive",
                       "primitive_name": "involute_spur_gear",
                       "parameters": {"module_mm": 2.0, "teeth": 5, "face_width_mm": 15.0}}],
    })

    assert result["ok"] is False, f"Expected ok=False for teeth<6, got: {result}"


def test_validate_rewrites_spur_gear_recipe_to_primitive():
    from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from pathlib import Path

    config = EngineeringToolsConfig(workspace_root=Path("/tmp"))
    tools_list = build_natural_language_tools(config)
    validate_tool = next(t for t in tools_list if t.name == "engineering_validate_cad_ir")
    validate_fn = getattr(validate_tool, "func", validate_tool)  # ToolDefinition.func

    result = validate_fn({
        "name": "test_gear", "units": "mm",
        "features": [{"id": "f1", "type": "recipe", "recipe_name": "spur_gear",
                       "parameters": {"module_mm": 2.0, "teeth": 24,
                                       "face_width_mm": 15.0, "bore_dia_mm": 10.0}}],
    })

    # After rewrite, spur_gear becomes primitive involute_spur_gear
    assert result["ok"] is True, f"Rewrite should succeed: {result}"
    assert "spur_gear" in str(result.get("warnings", "")) or any(
        "rewritten" in w.lower() for w in result.get("warnings", [])
    ), f"Should have rewrite warning: {result}"


def test_validate_does_not_swallow_rewrite_failure(monkeypatch):
    from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from pathlib import Path

    def _raise(*args, **kwargs):
        raise RuntimeError("Simulated rewrite failure")

    monkeypatch.setattr(
        "seekflow_engineering_tools.natural_language.tools.rewrite_deprecated_recipes_to_primitives",
        _raise,
    )

    config = EngineeringToolsConfig(workspace_root=Path("/tmp"))
    tools_list = build_natural_language_tools(config)
    validate_tool = next(t for t in tools_list if t.name == "engineering_validate_cad_ir")
    validate_fn = getattr(validate_tool, "func", validate_tool)  # ToolDefinition.func

    result = validate_fn({
        "name": "test", "units": "mm",
        "features": [{"id": "f1", "type": "recipe", "recipe_name": "box",
                       "parameters": {"length_mm": 10, "width_mm": 10, "height_mm": 10}}],
    })

    assert result["ok"] is False, f"Rewrite failure must cause ok=False, got: {result}"
    assert "rewrite failed" in result.get("error", "").lower()


def test_backend_support_uses_backend_supports_feature():
    from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from pathlib import Path

    config = EngineeringToolsConfig(workspace_root=Path("/tmp"))
    tools_list = build_natural_language_tools(config)
    validate_tool = next(t for t in tools_list if t.name == "engineering_validate_cad_ir")
    validate_fn = getattr(validate_tool, "func", validate_tool)

    # Primitive involute_spur_gear should be supported on cadquery backend
    result = validate_fn({
        "name": "test_gear", "units": "mm",
        "target_backend": ["cadquery"],
        "features": [{"id": "g1", "type": "primitive",
                       "primitive_name": "involute_spur_gear",
                       "parameters": {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0}}],
    })

    assert result["ok"] is True, f"cadquery should support involute_spur_gear: {result}"
