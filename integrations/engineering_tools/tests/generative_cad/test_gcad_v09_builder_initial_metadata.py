"""v0.9: builder initial metadata validation — soft mode accepts normalized partial proof."""


class TestBuilderInitialMetadata:
    def _canonical(self):
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalGcadDocument, CanonicalNode, CanonicalComponent,
        )
        return CanonicalGcadDocument(
            schema_version="g_cad_core_v0.2",
            canonical_version="canonical_gcad_v0.2",
            document_id="test", part_name="test", units="mm",
            trust_level="reference_geometry",
            raw_graph_hash="sha256:abc", canonical_graph_hash="sha256:def",
            selected_dialects=[],
            components=[CanonicalComponent(id="disk", owner_dialect="axisymmetric", root_node="n_body")],
            nodes=[CanonicalNode(
                id="n_body", component="disk", dialect="axisymmetric",
                op="revolve_profile", op_version="1.0.0", phase="base_solid",
                inputs=[], outputs=[{"name": "body", "type": "solid", "value_id": "v1"}],
                params={}, typed_params={},
            )],
            constraints={"require_step_file": True, "require_metadata_sidecar": True,
                         "require_closed_solid": True, "expected_body_count": 1,
                         "max_runtime_seconds": 120},
            safety={"non_flight_reference_only": True, "not_airworthy": True,
                    "not_certified": True, "not_for_manufacturing": True,
                    "not_for_installation": True, "no_structural_validation": True,
                    "no_life_prediction": True},
        )

    def _ctx(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        from pathlib import Path
        return RuntimeContext(
            out_step=Path(tmp_path / "test.step"),
            metadata_path=Path(tmp_path / "test.json"),
            workspace_root=Path(tmp_path),
        )

    def test_builder_initial_metadata_soft_validation_accepts_normalized_partial_proof(self, tmp_path):
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
                "safety": {
                    "non_flight_reference_only": True, "not_airworthy": True, "not_certified": True,
                    "not_for_manufacturing": True, "not_for_installation": True,
                    "no_structural_validation": True, "no_life_prediction": True,
                },
            },
            "build_warnings": [],
            "validation": {
                "core_validation": {"ok": False, "stage": "core_validation", "issues": []},
                "dialect_semantics": {"ok": False, "stage": "ds", "issues": []},
                "geometry_preflight": {"ok": False, "stage": "gp", "issues": []},
                "runtime_postconditions": {"ok": True, "stage": "rp", "issues": []},
                "inspection_validation": {"ok": False, "stage": "in", "issues": []},
            },
        }

        result = validate_generative_metadata_v2(
            metadata,
            canonical=None,
            registry_check=False,
            require_validation_ok=False,
        )

        assert result["ok"] is True

    def test_builder_initial_metadata_hard_validation_rejects_partial_proof(self, tmp_path):
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
                "safety": {
                    "non_flight_reference_only": True, "not_airworthy": True, "not_certified": True,
                    "not_for_manufacturing": True, "not_for_installation": True,
                    "no_structural_validation": True, "no_life_prediction": True,
                },
            },
            "build_warnings": [],
            "validation": {
                "core_validation": {"ok": False, "stage": "core_validation", "issues": []},
                "dialect_semantics": {"ok": False, "stage": "ds", "issues": []},
                "geometry_preflight": {"ok": False, "stage": "gp", "issues": []},
                "runtime_postconditions": {"ok": True, "stage": "rp", "issues": []},
                "inspection_validation": {"ok": False, "stage": "in", "issues": []},
            },
        }

        result = validate_generative_metadata_v2(
            metadata,
            canonical=None,
            registry_check=False,
            require_validation_ok=True,
        )

        assert result["ok"] is False
