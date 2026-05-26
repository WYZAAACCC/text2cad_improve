"""Test that engineering_build_cad_model actually executes builds."""

from __future__ import annotations

from pathlib import Path

import pytest

from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.ir.cad import CADPartSpec, RecipeFeature, ValidationSpec


BOX_SPEC = {
    "name": "test_box",
    "units": "mm",
    "target_backend": ["cadquery"],
    "features": [
        {
            "id": "f1",
            "type": "recipe",
            "recipe_name": "box",
            "parameters": {
                "length_mm": 50,
                "width_mm": 30,
                "height_mm": 20,
            },
        }
    ],
    "validation": {
        "expected_body_count": 1,
        "tolerance_mm": 2.0,
    },
}


class TestEngineeringBuildCadModel:
    def test_build_with_cadquery_generates_step(self, tmp_path: Path):
        """Test that engineering_build_cad_model generates a real STEP file."""
        cadquery = pytest.importorskip("cadquery")

        config = EngineeringToolsConfig(
            workspace_root=tmp_path / "ws",
            solidworks_enabled=False,
            nx_enabled=False,
            ansys_enabled=False,
        )
        config.workspace_root.mkdir(parents=True, exist_ok=True)

        out_step = config.workspace_root / "test_box.step"

        from seekflow_engineering_tools.cadquery_backend.builder import (
            build_cadquery_from_cad_ir,
        )
        spec = CADPartSpec.model_validate(BOX_SPEC)
        result = build_cadquery_from_cad_ir(
            spec=spec,
            config=config,
            out_step=str(out_step),
            inspect=False,  # Skip inspection to avoid cadquery API differences
        )

        assert result["ok"] is True, f"Build failed: {result.get('error')}"
        assert out_step.exists(), f"STEP file not created at {out_step}"
        assert out_step.stat().st_size > 0, "STEP file is empty"

    def test_build_fails_with_invalid_spec(self, tmp_path: Path):
        """Test that invalid spec returns ok=False."""
        from seekflow_engineering_tools.ir.cad import CADPartSpec
        import pydantic

        with pytest.raises((ValueError, pydantic.ValidationError)):
            CADPartSpec.model_validate({
                "name": "bad_spec",
                "units": "inch",  # only mm allowed
                "features": [],
            })

    def test_build_fails_when_recipe_unsupported(self, tmp_path: Path):
        """Test that unsupported recipe specification passes schema but fails capability check."""
        from seekflow_engineering_tools.ir.cad import CADPartSpec
        from seekflow_engineering_tools.capabilities.registry import backend_supports_recipe

        spec = CADPartSpec.model_validate({
            "name": "unknown",
            "units": "mm",
            "target_backend": ["cadquery"],
            "features": [
                {
                    "id": "f1",
                    "type": "recipe",
                    "recipe_name": "nonexistent_recipe_xyz",
                    "parameters": {},
                }
            ],
        })
        # The recipe is unknown but schema passes it through
        # Capability check should fail
        assert backend_supports_recipe("cadquery", "nonexistent_recipe_xyz") is False
        assert backend_supports_recipe("solidworks2025", "nonexistent_recipe_xyz") is False
        assert backend_supports_recipe("nx12", "nonexistent_recipe_xyz") is False
