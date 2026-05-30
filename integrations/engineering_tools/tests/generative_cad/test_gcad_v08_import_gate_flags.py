"""v0.8: import gate flags — complete flags, fail-closed defaults, contract hash."""


class TestImportGateFlagsV08:
    def _valid_metadata(self):
        from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash
        ch = dialect_contract_hash("axisymmetric")
        return {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v2",
                "metadata_schema_minor": "2.1",
                "source_route": "llm_skill_base",
                "schema_version": "g_cad_core_v0.2",
                "canonical_version": "canonical_gcad_v0.2",
                "trust_level": "reference_geometry",
                "part_name": "test",
                "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0", "contract_hash": ch}],
                "op_versions": [{"node_id": "n1", "dialect": "axisymmetric", "op": "revolve_profile", "op_version": "1.0.0"}],
                "raw_graph_hash": "sha256:def",
                "canonical_graph_hash": "sha256:ghi",
                "runner_version": "0.2.0",
                "geometry_runtime": "cadquery",
                "operation_metrics": [],
                "degraded_features": [],
                "repair_attempts": 0,
                "warnings": [],
                "safety": {
                    "non_flight_reference_only": True, "not_airworthy": True, "not_certified": True,
                    "not_for_manufacturing": True, "not_for_installation": True,
                    "no_structural_validation": True, "no_life_prediction": True,
                },
            },
            "build_warnings": [],
            "validation": {
                "core_validation": {"ok": True},
                "dialect_semantics": {"ok": True},
                "geometry_preflight": {"ok": True},
                "runtime_postconditions": {"ok": True},
                "inspection_validation": {"ok": True},
            },
        }

    def test_import_gate_required_flags_defined(self):
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import REQUIRED_GATE_FLAGS
        assert "step_exists" in REQUIRED_GATE_FLAGS
        assert "step_import_allowed" in REQUIRED_GATE_FLAGS
        assert len(REQUIRED_GATE_FLAGS) == 12

    def test_step_import_allowed_defaults_false(self):
        """step_import_allowed must be False by default in all early-return paths."""
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        from pathlib import Path
        import tempfile

        # Non-existent step → early return
        result = validate_generative_step_artifact_for_native_import(
            Path(tempfile.gettempdir()) / "nonexistent.step",
            Path(tempfile.gettempdir()) / "nonexistent.json",
        )
        assert "gate" in result
        assert result["gate"]["step_import_allowed"] is False

    def test_import_gate_optional_inspection_records_false_state(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        import json
        from pathlib import Path

        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")

        meta = self._valid_metadata()
        meta["validation"]["inspection_validation"] = {"ok": False, "issues": []}
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(meta))

        result = validate_generative_step_artifact_for_native_import(
            step_file, meta_file,
            require_inspection_ok=False,
        )
        assert result["gate"]["inspection_ok"] is False

    def test_import_gate_contract_hash_flag_false_on_mismatch(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        import json
        from pathlib import Path

        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")

        meta = self._valid_metadata()
        meta["generative_metadata"]["selected_dialects"][0]["contract_hash"] = "sha256:bad"
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(meta))

        result = validate_generative_step_artifact_for_native_import(step_file, meta_file)
        assert not result["ok"]
        assert result["gate"]["contract_hash_valid"] is False
