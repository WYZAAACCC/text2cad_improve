"""Test SolidWorks STEP import strategy for gear primitives."""

import pytest


def test_sw_legacy_gear_tools_not_registered():
    """solidworks_create_spur_gear_part and solidworks_create_true_involute_gear_part
    must NOT be in the tool registry."""
    from seekflow_engineering_tools.solidworks.tools import build_solidworks_tools
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from pathlib import Path

    config = EngineeringToolsConfig(workspace_root=Path("/tmp"))
    tools = build_solidworks_tools(config)
    names = {t.name for t in tools}

    assert "solidworks_create_spur_gear_part" not in names, \
        "legacy star-polygon gear tool must NOT be registered"
    assert "solidworks_create_true_involute_gear_part" not in names, \
        "legacy involute gear tool must NOT be registered"
    assert "solidworks_import_step_as_part" in names, \
        "STEP import tool must be registered"


def test_sw_primitive_strategy_is_cadquery_step_import():
    from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

    assert get_primitive_strategy("solidworks2025", "involute_spur_gear") == "cadquery_step_import"


def test_sw_direct_recipe_rejects_spur_gear():
    from seekflow_engineering_tools.natural_language.backend_builders import (
        build_solidworks_direct_recipe,
    )
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from pathlib import Path
    import tempfile

    spec = CADPartSpec(name="test", features=[{
        "id": "f1", "type": "recipe", "recipe_name": "spur_gear",
        "parameters": {"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0, "bore_dia_mm": 10.0},
    }])

    with tempfile.TemporaryDirectory() as tmp:
        config = EngineeringToolsConfig(workspace_root=Path(tmp), allow_overwrite=True)
        result = build_solidworks_direct_recipe(spec, config, str(Path(tmp) / "out.step"))
        assert result["ok"] is False
        assert "spur_gear" in result.get("error", "")


def test_sw_import_step_as_part_method_exists():
    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
    assert hasattr(SolidWorksClient, "import_step_as_part"), \
        "SolidWorksClient must have import_step_as_part method"
