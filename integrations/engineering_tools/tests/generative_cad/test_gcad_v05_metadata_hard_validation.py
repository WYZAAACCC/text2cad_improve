"""v0.5 metadata hard validation tests — require_validation_ok, contract hash check."""

import pytest


class TestMetadataHardValidation:
    def _valid_meta(self):
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
                "operation_metrics": [], "degraded_features": [], "repair_attempts": 0, "warnings": [],
                "safety": {
                    "non_flight_reference_only": True, "not_airworthy": True, "not_certified": True,
                    "not_for_manufacturing": True, "not_for_installation": True,
                    "no_structural_validation": True, "no_life_prediction": True,
                },
            },
            "build_warnings": [],
            "validation": {
                "core_validation": {"ok": True}, "dialect_semantics": {"ok": True},
                "geometry_preflight": {"ok": True}, "runtime_postconditions": {"ok": True},
                "inspection_validation": {"ok": True},
            },
        }

    def test_metadata_empty_validation_fails_when_required(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2

        meta = self._valid_meta()
        meta["validation"] = {
            "core_validation": {}, "dialect_semantics": {},
            "geometry_preflight": {}, "runtime_postconditions": {},
            "inspection_validation": {},
        }
        result = validate_generative_metadata_v2(meta, registry_check=True, require_validation_ok=True)
        assert not result["ok"]
        assert any(i["code"] == "core_validation_not_ok" for i in result["issues"])

    def test_metadata_contract_hash_checked_without_canonical(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2

        meta = self._valid_meta()
        meta["generative_metadata"]["selected_dialects"][0]["contract_hash"] = "sha256:bad"
        result = validate_generative_metadata_v2(meta, canonical=None, registry_check=True)
        assert not result["ok"]
        assert any(i["code"] == "contract_hash_mismatch" for i in result["issues"])

    def test_metadata_missing_runtime_postconditions_fails(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2

        meta = self._valid_meta()
        del meta["validation"]["runtime_postconditions"]
        result = validate_generative_metadata_v2(meta, require_validation_ok=True)
        assert not result["ok"]
        assert any("runtime_postconditions" in i["code"] for i in result["issues"])

    def test_metadata_safety_false_rejected(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import validate_generative_metadata_v2

        meta = self._valid_meta()
        meta["generative_metadata"]["safety"]["not_airworthy"] = False
        result = validate_generative_metadata_v2(meta)
        assert not result["ok"]

    def test_metadata_default_validation_is_fail_closed(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata import build_generative_metadata

        # Create minimal canonical-like object and context-like object
        class FakeNode:
            id = "n1"; component = "c1"; dialect = "axisymmetric"; op = "revolve_profile"
            op_version = "1.0.0"; phase = "base_solid"
            inputs = []; outputs = []; params = {}; typed_params = {}
            required = True; degradation_policy = "fail"

        class FakeDialect:
            dialect = "axisymmetric"; version = "0.2.0"; contract_hash = "sha256:abc"

        class FakeCanonical:
            schema_version = "g_cad_core_v0.2"; canonical_version = "canonical_gcad_v0.2"
            trust_level = "reference_geometry"; part_name = "test"; units = "mm"
            raw_graph_hash = "sha256:def"; canonical_graph_hash = "sha256:ghi"
            nodes = [FakeNode()]
            selected_dialects = [FakeDialect()]
            safety = type("s", (), {"model_dump": lambda self=None: {
                "non_flight_reference_only": True, "not_airworthy": True, "not_certified": True,
                "not_for_manufacturing": True, "not_for_installation": True,
                "no_structural_validation": True, "no_life_prediction": True,
            }})()

        class FakeCtx:
            runner_version = "0.2.0"; geometry_runtime_name = "cadquery"
            operation_metrics = []; degraded_features = []; warnings = []

        meta = build_generative_metadata(FakeCanonical(), FakeCtx())
        val = meta["validation"]
        # Default validation without explicit input must have ok: False
        assert val["core_validation"]["ok"] is False
        assert val["dialect_semantics"]["ok"] is False
        assert val["geometry_preflight"]["ok"] is False
        assert val["runtime_postconditions"]["ok"] is False
        assert val["inspection_validation"]["ok"] is False
