"""v1.0: builder initial metadata — soft validation passes normalized partial proof."""


class TestBuilderInitialMetadataV10:
    def test_runner_partial_metadata_passes_soft_validation(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2

        metadata = {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v2",
                "metadata_schema_minor": "2.1",
                "source_route": "llm_skill_base",
                "schema_version": "g_cad_core_v0.2",
                "canonical_version": "canonical_gcad_v0.2",
                "trust_level": "reference_geometry",
                "part_name": "test",
                "selected_dialects": [{"dialect": "test", "version": "1.0", "contract_hash": "sha256:abc"}],
                "op_versions": [],
                "raw_graph_hash": "sha256:abc",
                "canonical_graph_hash": "sha256:def",
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
                "core_validation": {"ok": False, "stage": "cv", "issues": []},
                "dialect_semantics": {"ok": False, "stage": "ds", "issues": []},
                "geometry_preflight": {"ok": False, "stage": "gp", "issues": []},
                "runtime_postconditions": {"ok": True, "stage": "rp", "issues": []},
                "inspection_validation": {"ok": False, "stage": "iv", "issues": []},
                "geometry_postcheck": {"ok": False, "stage": "gpc", "issues": []},
            },
        }

        result = validate_generative_metadata_v2(
            metadata, canonical=None, registry_check=False, require_validation_ok=False,
        )
        assert result["ok"] is True

    def test_runner_partial_metadata_fails_hard_validation(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2

        metadata = {
            "generative_metadata": {
                "metadata_version": "generative_metadata_v2",
                "metadata_schema_minor": "2.1",
                "source_route": "llm_skill_base",
                "schema_version": "g_cad_core_v0.2",
                "canonical_version": "canonical_gcad_v0.2",
                "trust_level": "reference_geometry",
                "part_name": "test",
                "selected_dialects": [{"dialect": "test", "version": "1.0", "contract_hash": "sha256:abc"}],
                "op_versions": [],
                "raw_graph_hash": "sha256:abc",
                "canonical_graph_hash": "sha256:def",
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
                "core_validation": {"ok": False, "stage": "cv", "issues": []},
                "dialect_semantics": {"ok": False, "stage": "ds", "issues": []},
                "geometry_preflight": {"ok": False, "stage": "gp", "issues": []},
                "runtime_postconditions": {"ok": True, "stage": "rp", "issues": []},
                "inspection_validation": {"ok": False, "stage": "iv", "issues": []},
                "geometry_postcheck": {"ok": False, "stage": "gpc", "issues": []},
            },
        }

        result = validate_generative_metadata_v2(
            metadata, canonical=None, registry_check=False, require_validation_ok=True,
        )
        assert result["ok"] is False
        assert any(i["code"] == "core_validation_not_ok" for i in result["issues"])
