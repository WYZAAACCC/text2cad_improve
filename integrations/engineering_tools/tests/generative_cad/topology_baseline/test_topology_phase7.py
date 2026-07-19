"""Phase 7 tests — CAD topology adapters for STEP, SolidWorks, NX."""

import json
import tempfile
import os

from seekflow_engineering_tools.generative_cad.topology.cad_adapters import (
    CrossBackendTopologyProof,
    NXTopologyAdapter,
    SolidWorksTopologyAdapter,
    TopologyStepExporter,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.models import TopologyEntityRecord


def _make_test_registry(n: int = 3) -> TopologyRegistry:
    reg = TopologyRegistry()
    for i in range(n):
        pid = f"gct:v1:doc:c:n{i}:n{i}:face:role_{i}"
        reg.register_entity(TopologyEntityRecord(
            persistent_id=pid, entity_type="face", component_id="c",
            owner_body_handle_id=f"solid:c:n{i}:body", producer_node_id=f"n{i}",
            semantic_role=f"role_{i}", status="active",
            resolution_method="primitive_semantic",
        ))
    return reg


class TestTopologyStepExporter:
    def test_export_manifest(self):
        reg = _make_test_registry(3)
        manifest = TopologyStepExporter.build_export_manifest("test.step", "test.topology.json", reg)
        assert manifest["entity_count"] == 3
        assert manifest["has_topology_sidecar"] is True

    def test_consistency_ok(self):
        d = tempfile.mkdtemp()
        sp = os.path.join(d, "test.topology.json")
        json.dump({"schema": "gcad_topology_v1", "canonical_graph_hash": "sha256:abc"}, open(sp, "w"))
        result = TopologyStepExporter.validate_export_consistency("test.step", sp, "sha256:abc")
        assert result["ok"] is True

    def test_consistency_hash_mismatch(self):
        d = tempfile.mkdtemp()
        sp = os.path.join(d, "test.topology.json")
        json.dump({"schema": "gcad_topology_v1", "canonical_graph_hash": "sha256:abc"}, open(sp, "w"))
        result = TopologyStepExporter.validate_export_consistency("test.step", sp, "sha256:wrong")
        assert result["ok"] is False

    def test_consistency_no_sidecar(self):
        result = TopologyStepExporter.validate_export_consistency("test.step", None, "sha256:abc")
        assert result["ok"] is True  # Warning only
        assert len(result["issues"]) >= 1


class TestSolidWorksAdapter:
    def test_attribute_map(self):
        reg = _make_test_registry(3)
        attr_map = SolidWorksTopologyAdapter.build_face_attribute_map(reg)
        assert len(attr_map) == 3

    def test_full_match_proof(self):
        reg = _make_test_registry(3)
        attr_map = SolidWorksTopologyAdapter.build_face_attribute_map(reg)
        proof = SolidWorksTopologyAdapter.build_import_proof(reg, list(attr_map.keys()))
        assert proof.ok is True
        assert proof.match_rate == 1.0

    def test_partial_match_below_threshold(self):
        reg = _make_test_registry(3)
        attr_map = SolidWorksTopologyAdapter.build_face_attribute_map(reg)
        sw_names = list(attr_map.keys())[:2] + ["UNKNOWN"]
        proof = SolidWorksTopologyAdapter.build_import_proof(reg, sw_names)
        assert abs(proof.match_rate - 2 / 3) < 0.001
        assert proof.ok is False  # Below 80%
        assert len(proof.unmatched_ids) == 1

    def test_validation_spec(self):
        reg = _make_test_registry(3)
        spec = SolidWorksTopologyAdapter.build_import_validation_spec(reg)
        assert spec["expected_active_faces"] == 3


class TestNXAdapter:
    def test_journal_commands(self):
        reg = _make_test_registry(3)
        cmds = NXTopologyAdapter.build_journal_attribute_commands(reg)
        assert len(cmds) == 3
        assert cmds[0]["action"] == "set_face_attribute"

    def test_validation_commands(self):
        reg = _make_test_registry(3)
        cmds = NXTopologyAdapter.build_journal_validation_commands(reg)
        assert len(cmds) == 3
        assert cmds[0]["action"] == "validate_face_attribute"

    def test_import_proof(self):
        reg = _make_test_registry(2)
        results = [
            {"ok": True, "expected_value": "gct:v1:doc:c:n0:n0:face:role_0"},
            {"ok": False, "expected_value": "bad"},
        ]
        proof = NXTopologyAdapter.build_import_proof(reg, results)
        assert proof.match_rate == 0.5
        assert proof.ok is False


class TestCrossBackendProof:
    def test_model(self):
        proof = CrossBackendTopologyProof(
            source_backend="gcad_cadquery", target_backend="solidworks2025",
            entity_mapping={"a": "b"}, ok=True, match_rate=1.0,
        )
        assert proof.source_backend == "gcad_cadquery"
        assert proof.ok is True
