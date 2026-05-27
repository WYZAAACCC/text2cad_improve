"""Test NX STEP import strategy for gear primitives."""

import pytest


def test_nx_primitive_strategy_is_cadquery_step_import():
    from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

    assert get_primitive_strategy("nx12", "involute_spur_gear") == "cadquery_step_import"


def test_nx_import_step_action_is_allowed():
    from seekflow_engineering_tools.nx.job_queue import ALLOWED_ACTIONS

    assert "import_step_as_prt" in ALLOWED_ACTIONS


def test_nx_import_step_handler_exists():
    from seekflow_engineering_tools.nx.nx_bridge_bootstrap import ACTION_HANDLERS

    assert "import_step_as_prt" in ACTION_HANDLERS
    assert callable(ACTION_HANDLERS["import_step_as_prt"])


def test_nx_direct_recipe_rejects_spur_gear():
    from seekflow_engineering_tools.natural_language.backend_builders import (
        build_nx_direct_recipe,
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
        result = build_nx_direct_recipe(spec, config, str(Path(tmp) / "out.step"))
        assert result["ok"] is False
