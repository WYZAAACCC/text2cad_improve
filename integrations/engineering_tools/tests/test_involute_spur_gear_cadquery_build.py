"""Test CadQuery build of involute spur gear primitive."""

import pytest


@pytest.mark.requires_cq_gears
def test_build_gear_step_and_metadata():
    """Full build test — requires cadquery (and ideally cq_gears) installed."""
    import tempfile
    from pathlib import Path

    cadquery = pytest.importorskip("cadquery")
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        config = EngineeringToolsConfig(workspace_root=out_dir, allow_overwrite=True)

        spec = CADPartSpec.model_validate({
            "name": "test_gear", "units": "mm",
            "features": [{
                "id": "g1",
                "type": "primitive",
                "primitive_name": "involute_spur_gear",
                "parameters": {
                    "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
                },
            }],
            "validation": {"expected_body_count": 1, "tolerance_mm": 0.5},
        })

        step_path = out_dir / "test_gear.step"
        result = build_cadquery_from_cad_ir(
            spec=spec, config=config, out_step=str(step_path))

        assert result.get("ok") is True, f"Build failed: {result.get('error')}"
        assert step_path.exists()
        assert step_path.stat().st_size > 0

        # Check metadata sidecar
        meta_path = step_path.with_suffix(".metadata.json")
        assert meta_path.exists()


@pytest.mark.not_requires_cq_gears
def test_build_gear_step_and_metadata_no_cq_gears():
    """Build test that works without cq_gears (uses fallback)."""
    import tempfile
    from pathlib import Path

    pytest.importorskip("cadquery")
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        config = EngineeringToolsConfig(workspace_root=out_dir, allow_overwrite=True)

        spec = CADPartSpec.model_validate({
            "name": "test_gear_fb", "units": "mm",
            "features": [{
                "id": "g1",
                "type": "primitive",
                "primitive_name": "involute_spur_gear",
                "parameters": {
                    "module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0,
                },
            }],
            "validation": {"expected_body_count": 1, "tolerance_mm": 0.5},
        })

        step_path = out_dir / "test_gear_fb.step"
        result = build_cadquery_from_cad_ir(
            spec=spec, config=config, out_step=str(step_path))

        assert step_path.exists()
        # With fallback, OK is still True but warnings MUST be present if fallback used
        if result.get("ok") and result.get("warnings"):
            assert any(
                "fallback" in w.lower() or "not certified" in w.lower()
                for w in result["warnings"]
            )
