"""v0.7: import gate flag accuracy tests."""


class TestImportGateFlags:
    def _valid_metadata(self):
        from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash
        ch = dialect_contract_hash("axisymmetric")
        return {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v3",
                "source_route": "llm_skill_base",
                "schema_version": "g_cad_core_v0.2",
                "canonical_version": "canonical_gcad_v0.2",
                "trust_level": "reference_geometry",
                "part_name": "test",
                "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0", "contract_hash": ch}],
                "op_versions": [{"node_id": "n1", "dialect": "axisymmetric", "op": "revolve_profile", "op_version": "1.0.0"}],
                "raw_graph_hash": "sha256:def",
                "canonical_graph_hash": "sha256:ghi",
                "paths": {
                    "canonical_ir_path": "/tmp/canonical.json",
                    "validation_seed_path": "/tmp/validation.json",
                    "step_path": "/tmp/test.step",
                    "metadata_path": "/tmp/test.metadata.json",
                },
                "runtime": {
                    "runner_version": "0.2.0",
                    "geometry_runtime": "cadquery",
                    "geometry_runtime_version": "cadquery_runtime_v1",
                },
                "artifact": {
                    "step_sha256": "sha256:f173fe44447b57a79ca85a732c31c5fb5fca41fcef440054a099df01e02a037b",
                },
                "import_policy": {
                    "native_rebuild_allowed": False,
                    "requires_import_gate": True,
                    "step_import_candidate": True,
                    "step_import_allowed": False,
                },
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
                "geometry_preflight": {"ok": False, "issues": [{"code": "preflight_failed", "message": "bad"}]},
                "runtime_postconditions": {"ok": True},
                "inspection_validation": {"ok": None, "skipped": True},
                "geometry_postcheck": {"ok": True},
            },
        }

    def test_import_gate_contract_hash_flag_false_on_mismatch(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        import json
        from pathlib import Path

        # Create minimal STEP
        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")

        # Metadata with bad contract hash
        meta = self._valid_metadata()
        meta["generative_metadata"]["selected_dialects"][0]["contract_hash"] = "sha256:badbad"
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(meta))

        result = validate_generative_step_artifact_for_native_import(step_file, meta_file)
        assert not result["ok"]
        assert result["gate"]["contract_hash_valid"] is False

    def test_import_gate_geometry_preflight_flag_reflects_actual_state(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        import json
        from pathlib import Path

        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")

        meta = self._valid_metadata()
        # geometry_preflight is ok=False in fixture
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(meta))

        result = validate_generative_step_artifact_for_native_import(
            step_file, meta_file,
            require_geometry_preflight_ok=False,
        )
        # Gate should still reflect actual geometry_preflight state
        assert result["gate"]["geometry_preflight_ok"] is False

    def test_import_gate_inspection_flag_reflects_actual_state(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        import json
        from pathlib import Path

        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")

        meta = self._valid_metadata()
        meta["validation"]["inspection_validation"] = {"ok": False, "issues": [{"code": "fail", "message": "bad"}]}
        meta["validation"]["geometry_preflight"]["ok"] = True
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(meta))

        result = validate_generative_step_artifact_for_native_import(
            step_file, meta_file,
            require_inspection_ok=False,
        )
        # Gate should still reflect actual inspection state
        assert result["gate"]["inspection_ok"] is False

    def test_import_gate_pass_with_valid_metadata(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        import json
        from pathlib import Path

        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")

        meta = self._valid_metadata()
        meta["validation"]["geometry_preflight"]["ok"] = True
        meta["validation"]["inspection_validation"]["ok"] = True
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(meta))

        result = validate_generative_step_artifact_for_native_import(step_file, meta_file)
        assert result["ok"]
        assert result["gate"]["geometry_preflight_ok"] is True
        assert result["gate"]["inspection_ok"] is True
        assert result["gate"]["contract_hash_valid"] is True
        assert result["gate"]["metadata_valid"] is True
