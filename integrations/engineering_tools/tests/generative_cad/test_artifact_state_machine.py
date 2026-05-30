"""P4: Artifact state machine tests."""


class TestArtifactStateMachine:
    def test_artifact_has_state_field(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
        import inspect
        src = inspect.getsource(build_canonical_step_artifact)
        assert '"state"' in src or "'state'" in src
        assert "validated_reference_step" in src

    def test_artifact_step_import_allowed_is_false(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
        import inspect
        src = inspect.getsource(build_canonical_step_artifact)
        assert "step_import_allowed" in src
        assert '"step_import_allowed": False' in src or "'step_import_allowed': False" in src

    def test_artifact_step_import_candidate_is_true(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
        import inspect
        src = inspect.getsource(build_canonical_step_artifact)
        assert "step_import_candidate" in src

    def test_artifact_requires_import_gate_is_true(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
        import inspect
        src = inspect.getsource(build_canonical_step_artifact)
        assert "requires_import_gate" in src

    def test_builder_checks_validated_reference_step_state(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        assert "validated_reference_step" in src

    def test_builder_step_import_allowed_must_be_false(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        assert "step_import_allowed must be False" in src

    def test_import_gate_returns_native_import_eligible(self):
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import import_artifact
        src = inspect.getsource(import_artifact.validate_generative_step_artifact_for_native_import)
        assert "native_import_eligible" in src

    def test_import_gate_success_path_has_all_required_true(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.import_artifact import (
            validate_generative_step_artifact_for_native_import,
        )
        from seekflow_engineering_tools.generative_cad.dialects.registry import dialect_contract_hash
        import json

        ch = dialect_contract_hash("axisymmetric")
        metadata = {
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

        step_file = tmp_path / "test.step"
        step_file.write_text("ISO-10303-21;")
        meta_file = tmp_path / "test.metadata.json"
        meta_file.write_text(json.dumps(metadata))

        result = validate_generative_step_artifact_for_native_import(step_file, meta_file)
        assert result["ok"]
        assert result.get("state") == "native_import_eligible"

    def test_native_rebuild_never_allowed(self):
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import artifact
        src = inspect.getsource(artifact)
        assert '"native_rebuild_allowed": False' in src or "'native_rebuild_allowed': False" in src
