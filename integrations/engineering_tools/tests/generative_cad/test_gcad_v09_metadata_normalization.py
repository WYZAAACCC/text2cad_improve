"""v0.9: metadata normalization — partial validation dicts get fail-closed defaults."""


class TestMetadataNormalization:
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

    def test_build_metadata_normalizes_partial_validation(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import build_generative_metadata

        metadata = build_generative_metadata(
            canonical=self._canonical(),
            ctx=self._ctx(tmp_path),
            validation={
                "runtime_postconditions": {
                    "ok": True,
                    "stage": "runtime_postconditions",
                    "issues": [],
                }
            },
        )

        val = metadata["validation"]
        assert val["core_validation"]["ok"] is False
        assert val["dialect_semantics"]["ok"] is False
        assert val["geometry_preflight"]["ok"] is False
        assert val["runtime_postconditions"]["ok"] is True
        assert val["inspection_validation"]["ok"] is False

    def test_partial_validation_passes_structure_not_hard_gate(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import (
            validate_generative_metadata_v2,
        )

        # Construct minimal metadata dict directly with one valid dialect entry
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

        soft = validate_generative_metadata_v2(
            metadata, canonical=None,
            registry_check=False, require_validation_ok=False,
        )
        hard = validate_generative_metadata_v2(
            metadata, canonical=None,
            registry_check=False, require_validation_ok=True,
        )

        assert soft["ok"] is True
        assert hard["ok"] is False
        assert any(i["code"] == "core_validation_not_ok" for i in hard["issues"])

    def test_build_metadata_none_validation_gets_defaults(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import build_generative_metadata

        metadata = build_generative_metadata(
            canonical=self._canonical(),
            ctx=self._ctx(tmp_path),
            validation=None,
        )

        val = metadata["validation"]
        for stage in ["core_validation", "dialect_semantics", "geometry_preflight",
                       "runtime_postconditions", "inspection_validation"]:
            assert stage in val
            assert val[stage]["ok"] is False

    def test_normalize_validation_proof_preserves_extra_sections(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import normalize_validation_proof

        normalized = normalize_validation_proof({
            "runtime_postconditions": {"ok": True, "stage": "rp", "issues": []},
            "custom_diagnostic": {"ok": True, "info": "extra"},
        })

        assert normalized["runtime_postconditions"]["ok"] is True
        assert normalized["core_validation"]["ok"] is False
        assert "custom_diagnostic" in normalized
