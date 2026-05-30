"""v0.9: import gate release semantics — postcondition invariants, flag completeness."""


class TestImportGateRelease:
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
            assert result["gate"][key] is True, f"gate flag {key} should be True"

        assert result["gate"]["native_rebuild_allowed"] is False

    def test_import_gate_failed_metadata_never_allows_step_import(self, tmp_path):
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

    def test_import_gate_has_invariant_postcondition(self):
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import import_artifact
        src = inspect.getsource(import_artifact)
        assert "gate_internal_invariant_failed" in src
