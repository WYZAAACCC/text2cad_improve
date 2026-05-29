"""Test generative CAD builder — build path and validation.

CadQuery-dependent tests are skipped when cadquery is not installed.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.generative_cad.ir import GenerativeCADSpec


def _make_valid_axisymmetric_spec():
    return {
        "part_name": "test_disk",
        "selected_bases": [
            {"base_id": "axisymmetric_base", "base_version": "0.1.0"}
        ],
        "feature_graph": {
            "nodes": [
                {
                    "id": "body",
                    "base_id": "axisymmetric_base",
                    "op": "revolve_profile",
                    "phase": "base_solid",
                    "params": {
                        "axis": "Z",
                        "profile_stations": [
                            {"r_mm": 100, "z_front_mm": 0, "z_rear_mm": 5},
                            {"r_mm": 100, "z_front_mm": 5, "z_rear_mm": 10},
                            {"r_mm": 50, "z_front_mm": 10, "z_rear_mm": 15},
                            {"r_mm": 50, "z_front_mm": 15, "z_rear_mm": 20},
                        ],
                    },
                },
                {
                    "id": "bore",
                    "base_id": "axisymmetric_base",
                    "op": "cut_center_bore",
                    "phase": "primary_cut",
                    "params": {"diameter_mm": 20, "axis": "Z"},
                    "depends_on": ["body"],
                },
            ]
        },
    }


def _make_valid_sketch_extrude_spec():
    return {
        "part_name": "test_plate",
        "selected_bases": [
            {"base_id": "sketch_extrude_base", "base_version": "0.1.0"}
        ],
        "feature_graph": {
            "nodes": [
                {
                    "id": "body",
                    "base_id": "sketch_extrude_base",
                    "op": "extrude_rectangle",
                    "phase": "base_solid",
                    "params": {
                        "width_mm": 100,
                        "height_mm": 50,
                        "depth_mm": 10,
                    },
                },
                {
                    "id": "hole1",
                    "base_id": "sketch_extrude_base",
                    "op": "cut_hole",
                    "phase": "primary_cut",
                    "params": {
                        "diameter_mm": 10,
                        "position_mm": [25, 0, 0],
                    },
                    "depends_on": ["body"],
                },
            ]
        },
    }


@pytest.fixture
def temp_config():
    """Config with temp workspace."""
    tmp = tempfile.mkdtemp()
    yield EngineeringToolsConfig(
        workspace_root=Path(tmp),
        allow_overwrite=True,
    )
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


class TestBuilderValidation:
    def test_invalid_graph_fails_before_execution(self, temp_config):
        """Invalid spec should fail during graph validation, before subprocess."""
        from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model
        from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument

        out_step = temp_config.workspace_root / "bad_output.step"
        # Use RawGcadDocument v0.2 with an unknown dialect
        result = build_generative_cad_model(
            spec={
                "schema_version": "g_cad_core_v0.2",
                "document_id": "bad",
                "part_name": "bad",
                "units": "mm",
                "trust_level": "reference_geometry",
                "selected_dialects": [{"dialect": "nonexistent", "version": "0.2.0"}],
                "components": [{"id": "c1", "owner_dialect": "nonexistent", "root_node": "n1"}],
                "nodes": [{
                    "id": "n1", "component": "c1", "dialect": "nonexistent",
                    "op": "fake_op", "op_version": "1.0.0", "phase": "base_solid",
                    "inputs": [], "outputs": [{"name": "body", "type": "solid"}],
                    "params": {}, "required": True, "degradation_policy": "fail",
                }],
                "constraints": {"require_step_file": True, "require_metadata_sidecar": True, "require_closed_solid": True, "expected_body_count": 1, "max_runtime_seconds": 120},
                "safety": {"non_flight_reference_only": True, "not_airworthy": True, "not_certified": True, "not_for_manufacturing": True, "not_for_installation": True, "no_structural_validation": True, "no_life_prediction": True},
            },
            config=temp_config, out_step=out_step, inspect=False,
        )
        assert not result["ok"]
        assert "Validation failed" in result.get("error", "")

    def test_no_output_outside_workspace(self, temp_config):
        """Output path must be inside workspace."""
        from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model

        spec = GenerativeCADSpec.model_validate(_make_valid_axisymmetric_spec())

        with pytest.raises(ValueError, match="outside workspace"):
            build_generative_cad_model(
                spec=spec,
                config=temp_config,
                out_step="/outside/workspace/test.step",
                inspect=False,
            )

    def test_overwrite_respected(self, temp_config):
        """When allow_overwrite=False, existing file should block build."""
        from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model

        config_no_overwrite = EngineeringToolsConfig(
            workspace_root=temp_config.workspace_root,
            allow_overwrite=False,
        )

        spec = GenerativeCADSpec.model_validate(_make_valid_axisymmetric_spec())
        out_step = temp_config.workspace_root / "existing.step"
        out_step.write_text("existing")

        result = build_generative_cad_model(
            spec=spec, config=config_no_overwrite, out_step=out_step, inspect=False,
        )
        assert not result["ok"]
        assert "already exists" in result.get("error", "")


class TestBuilderCadQuery:
    """Tests that require cadquery to be installed."""

    def test_valid_axisymmetric_graph_builds_step(self, temp_config):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model

        spec = GenerativeCADSpec.model_validate(_make_valid_axisymmetric_spec())
        out_step = temp_config.workspace_root / "test_output.step"

        result = build_generative_cad_model(
            spec=spec, config=temp_config, out_step=out_step, inspect=True,
        )
        assert result["ok"], f"Build failed: {result.get('error', 'unknown')}"
        assert out_step.exists()
        assert out_step.stat().st_size > 0

    def test_metadata_sidecar_exists(self, temp_config):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model

        spec = GenerativeCADSpec.model_validate(_make_valid_axisymmetric_spec())
        out_step = temp_config.workspace_root / "test_meta.step"

        result = build_generative_cad_model(
            spec=spec, config=temp_config, out_step=out_step, inspect=True,
        )
        assert result["ok"]
        meta_path = out_step.with_suffix(".metadata.json")
        assert meta_path.exists()
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "generative_metadata" in metadata

    def test_inspection_metrics_present(self, temp_config):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model

        spec = GenerativeCADSpec.model_validate(_make_valid_axisymmetric_spec())
        out_step = temp_config.workspace_root / "test_inspect.step"

        result = build_generative_cad_model(
            spec=spec, config=temp_config, out_step=out_step, inspect=True,
        )
        assert result["ok"]
        assert "inspection" in result.get("metrics", {})

    def test_sketch_extrude_graph_builds_step(self, temp_config):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model

        spec = GenerativeCADSpec.model_validate(_make_valid_sketch_extrude_spec())
        out_step = temp_config.workspace_root / "test_plate.step"

        result = build_generative_cad_model(
            spec=spec, config=temp_config, out_step=out_step, inspect=True,
        )
        assert result["ok"], f"Build failed: {result.get('error', 'unknown')}"
        assert out_step.exists()

    def test_artifact_descriptor_returned(self, temp_config):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model

        spec = GenerativeCADSpec.model_validate(_make_valid_axisymmetric_spec())
        out_step = temp_config.workspace_root / "test_artifact.step"

        result = build_generative_cad_model(
            spec=spec, config=temp_config, out_step=out_step, inspect=True,
        )
        assert result["ok"]
        assert result["software"] == "cadquery"
        assert "files_created" in result
        assert len(result["files_created"]) >= 2  # STEP + metadata + graph + script
