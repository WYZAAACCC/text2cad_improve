"""§10.5 Sidecar V3 tests — integrity, migration, schema validation."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from seekflow_engineering_tools.generative_cad.topology.models import TopologyEntityRecord
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.persistence import (
    read_topology_sidecar,
    write_topology_sidecar,
)


class TestSidecarV3Integrity:
    def test_sidecar_byte_identical_rebuild(self):
        """Same registry → same sidecar content."""
        reg = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct2_s", entity_type="face", component_id="disk",
            owner_body_handle_id="body", producer_node_id="n1",
            semantic_role="test",
        )
        reg.register_entity(rec)

        with TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "v1.topology.json"
            p2 = Path(tmp) / "v2.topology.json"
            write_topology_sidecar(reg, p1, document_id="d1",
                                   canonical_graph_hash="sha256:abcd", runtime_version="1")
            write_topology_sidecar(reg, p2, document_id="d1",
                                   canonical_graph_hash="sha256:abcd", runtime_version="1")
            assert p1.read_bytes() == p2.read_bytes(), (
                "Same registry must produce byte-identical sidecars"
            )

    def test_sidecar_hash_mismatch_detected(self):
        reg_a = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct2_s", entity_type="face", component_id="disk",
            owner_body_handle_id="body", producer_node_id="n1",
            semantic_role="test",
        )
        reg_a.register_entity(rec)

        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.topology.json"
            write_topology_sidecar(reg_a, p, document_id="d1",
                                   canonical_graph_hash="sha256:abcd", runtime_version="1")
            data = json.loads(p.read_text())
            data["topology_registry_hash"] = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            p.write_text(json.dumps(data))
            reg_b = TopologyRegistry()
            with pytest.raises(ValueError, match="hash mismatch"):
                read_topology_sidecar(p, reg_b)

    def test_sidecar_schema_v3(self):
        reg = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct2_s", entity_type="face", component_id="disk",
            owner_body_handle_id="body", producer_node_id="n1",
            semantic_role="test",
        )
        reg.register_entity(rec)
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.topology.json"
            meta = write_topology_sidecar(reg, p, document_id="d1",
                                          canonical_graph_hash="sha256:abcd", runtime_version="1")
            assert meta["topology_schema_version"] == "gcad_topology_v3"


class TestSidecarMigration:
    def test_v1_key_parsed_as_legacy(self):
        from seekflow_engineering_tools.generative_cad.topology.ids import (
            parse_persistent_id_key, LEGACY_V1_MARKER,
        )
        result = parse_persistent_id_key("gct:v1:doc123:comp:n1:n1:face:role")
        assert result["version"] == "v1"
        assert result["legacy_status"] == LEGACY_V1_MARKER

    def test_v2_key_irreversible(self):
        from seekflow_engineering_tools.generative_cad.topology.ids import (
            PersistentTopoIdV2, parse_persistent_id_key, LEGACY_V2_IRREVERSIBLE,
        )
        pid = PersistentTopoIdV2(
            document_id="d1", component_id="c1", lineage_root_node_id="n1",
            producer_node_id="n1", entity_type="face", semantic_role="test",
        )
        result = parse_persistent_id_key(pid.to_key())
        assert result["version"] == "v2"
        assert result["legacy_status"] == LEGACY_V2_IRREVERSIBLE
