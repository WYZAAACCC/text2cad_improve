"""Test generative metadata validation."""

import pytest

from seekflow_engineering_tools.generative_cad.metadata import validate_generative_metadata_v1


def _make_valid_metadata():
    return {
        "generative_metadata": {
            "metadata_version": "generative_metadata_v1",
            "source_route": "llm_skill_base",
            "trust_level": "reference_geometry",
            "part_name": "test_disk",
            "base_stack": [
                {"base_id": "axisymmetric_base", "base_version": "0.1.0"}
            ],
            "skill_stack": [],
            "feature_graph_hash": "sha256:abcdef1234567890",
            "base_contract_hashes": {},
            "runner_version": "0.1.0",
            "operation_metrics": [],
            "degraded_features": [],
            "repair_attempts": 0,
            "warnings": [],
            "safety": {
                "non_flight_reference_only": True,
                "not_airworthy": True,
                "not_certified": True,
                "not_for_manufacturing": True,
                "not_for_installation": True,
                "no_structural_validation": True,
                "no_life_prediction": True,
            },
        },
        "build_warnings": [],
        "validation": {},
    }


class TestValidateGenerativeMetadataV1:
    def test_valid_metadata_passes(self):
        result = validate_generative_metadata_v1(_make_valid_metadata())
        assert result["ok"], f"Expected ok, got: {result['issues']}"

    def test_missing_generative_metadata_fails(self):
        result = validate_generative_metadata_v1({})
        assert not result["ok"]
        assert any("generative_metadata" in i["message"] for i in result["issues"])

    def test_missing_safety_fails(self):
        meta = _make_valid_metadata()
        del meta["generative_metadata"]["safety"]
        result = validate_generative_metadata_v1(meta)
        assert not result["ok"]
        assert any("safety" in i["message"] for i in result["issues"])

    def test_false_safety_fails(self):
        meta = _make_valid_metadata()
        meta["generative_metadata"]["safety"]["not_airworthy"] = False
        result = validate_generative_metadata_v1(meta)
        assert not result["ok"]
        assert any("not_airworthy" in i["message"] for i in result["issues"])

    def test_missing_base_stack_fails(self):
        meta = _make_valid_metadata()
        meta["generative_metadata"]["base_stack"] = []
        result = validate_generative_metadata_v1(meta)
        assert not result["ok"]
        assert any("base_stack" in i["message"] for i in result["issues"])

    def test_missing_feature_graph_hash_fails(self):
        meta = _make_valid_metadata()
        meta["generative_metadata"]["feature_graph_hash"] = "not-a-hash"
        result = validate_generative_metadata_v1(meta)
        assert not result["ok"]
        assert any("feature_graph_hash" in i["message"] for i in result["issues"])

    def test_missing_build_warnings_fails(self):
        meta = _make_valid_metadata()
        del meta["build_warnings"]
        result = validate_generative_metadata_v1(meta)
        assert not result["ok"]
        assert any("build_warnings" in i["message"] for i in result["issues"])

    def test_invalid_trust_level_fails(self):
        meta = _make_valid_metadata()
        meta["generative_metadata"]["trust_level"] = "manufacturing_ready"
        result = validate_generative_metadata_v1(meta)
        assert not result["ok"]
        assert any("trust_level" in i["message"] for i in result["issues"])

    def test_invalid_source_route_fails(self):
        meta = _make_valid_metadata()
        meta["generative_metadata"]["source_route"] = "direct_cadquery"
        result = validate_generative_metadata_v1(meta)
        assert not result["ok"]

    def test_metadata_version_wrong_fails(self):
        meta = _make_valid_metadata()
        meta["generative_metadata"]["metadata_version"] = "v0_old"
        result = validate_generative_metadata_v1(meta)
        assert not result["ok"]

    def test_generative_metadata_not_dict_fails(self):
        result = validate_generative_metadata_v1({"generative_metadata": "not_a_dict"})
        assert not result["ok"]
