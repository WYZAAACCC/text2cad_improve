"""v1.0: import gate release — postcondition invariants, native_rebuild_allowed guard."""


class TestImportGateReleaseV10:
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
                "safety": {"non_flight_reference_only": True, "not_airworthy": True,
                           "not_certified": True, "not_for_manufacturing": True,
                           "not_for_installation": True, "no_structural_validation": True,
                           "no_life_prediction": True},
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

    def test_import_gate_success_has_all_required_true_flags(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        import json
        from pathlib import Path

        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")
        meta = self._valid_metadata()
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(meta))

        result = validate_generative_step_artifact_for_native_import(step_file, meta_file)
        assert result["ok"]

        required_true = [
            "step_exists", "metadata_exists", "metadata_valid", "safety_valid",
            "contract_hash_valid", "core_validation_ok", "dialect_semantics_ok",
            "geometry_preflight_ok", "runtime_postconditions_ok", "inspection_ok",
            "step_import_allowed",
        ]
        for key in required_true:
            assert result["gate"][key] is True, f"gate.{key} should be True"
        assert result["gate"]["native_rebuild_allowed"] is False

    def test_import_gate_failed_never_allows_step_import(self, tmp_path):
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
        assert result["gate"]["step_import_allowed"] is False

    def test_import_gate_has_native_rebuild_invariant(self):
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import import_artifact
        src = inspect.getsource(import_artifact)
        assert "native_rebuild_allowed" in src
        assert "gate_internal_invariant_failed" in src
