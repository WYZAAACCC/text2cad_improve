"""§10.5 Registry reindexing tests — superseded overwrite consistency."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyDelta,
    TopologyEntityRecord,
    TopologyRelation,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry


class TestRegistryReindex:
    def test_superseded_overwrite_index_consistency(self):
        reg = TopologyRegistry()
        rec_a = TopologyEntityRecord(
            persistent_id="gct2_a", entity_type="face", component_id="disk",
            owner_body_handle_id="body_a", producer_node_id="n1",
            semantic_role="original", status="active",
        )
        reg.register_entity(rec_a)
        assert "gct2_a" in reg._body_index.get("body_a", [])
        # Supersede via split
        delta = TopologyDelta(
            node_id="n2", component_id="disk",
            history_provider="operation_semantics",
            relations=[TopologyRelation(
                relation="split", source_ids=["gct2_a"],
                result_entity_keys=["gct2_b", "gct2_c"],
            )],
        )
        rec_b = TopologyEntityRecord(
            persistent_id="gct2_b", entity_type="face", component_id="disk",
            owner_body_handle_id="body_b", producer_node_id="n2",
            semantic_role="branch_b",
        )
        rec_c = TopologyEntityRecord(
            persistent_id="gct2_c", entity_type="face", component_id="disk",
            owner_body_handle_id="body_b", producer_node_id="n2",
            semantic_role="branch_c",
        )
        reg.register_entity(rec_b)
        reg.register_entity(rec_c)
        reg.apply_delta(delta)
        assert reg.get_entity("gct2_a").status == "superseded"
        integrity = reg.validate_integrity()
        assert integrity["ok"], f"Integrity issues: {integrity['issues']}"

    def test_reindex_after_restore(self):
        reg = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct2_r", entity_type="face", component_id="disk",
            owner_body_handle_id="body_r", producer_node_id="n1",
            semantic_role="test",
        )
        reg.register_entity(rec)
        snap = reg.export_snapshot()
        reg2 = TopologyRegistry()
        reg2.restore_snapshot(snap)
        assert reg2.entity_count == 1
        assert reg2.get_entity("gct2_r").status == "active"
