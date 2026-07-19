"""§10.3 Mutation tests — detect tampered topology state."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyEntityRecord,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.locator import RuntimeTopoLocator


class TestLocatorMutations:
    def test_locator_position_swap_detected(self):
        reg = TopologyRegistry()
        rec_a = TopologyEntityRecord(
            persistent_id="gct2_a", entity_type="face", component_id="disk",
            owner_body_handle_id="body", producer_node_id="n1",
            semantic_role="face_a", status="active",
            current_locator={"owner_body_handle_id": "body", "entity_type": "face",
                             "indexed_map_position": 1, "occt_shape_hash": 0},
        )
        rec_b = TopologyEntityRecord(
            persistent_id="gct2_b", entity_type="face", component_id="disk",
            owner_body_handle_id="body", producer_node_id="n1",
            semantic_role="face_b", status="active",
            current_locator={"owner_body_handle_id": "body", "entity_type": "edge",
                             "indexed_map_position": 1, "occt_shape_hash": 0},
        )
        reg.register_entity(rec_a)
        reg.register_entity(rec_b)
        # Both claim position 1 on same body with conflicting types
        r_a = reg.resolve("gct2_a")
        r_b = reg.resolve("gct2_b")
        assert not (r_a.status == "exact" and r_b.status == "exact"), (
            "Both entities cannot be exact with conflicting types at same position"
        )

    def test_owner_revision_tamper_detected(self):
        loc = RuntimeTopoLocator(
            owner_body_handle_id="body", entity_type="face",
            indexed_map_position=1, occt_shape_hash=0,
            owner_body_revision_id="1",
        )
        assert loc.is_stale_v3(current_revision="3"), (
            "Locator with rev 1 should be stale when current rev is 3"
        )

    def test_entity_type_mismatch_rejected(self):
        rec = TopologyEntityRecord(
            persistent_id="gct2_e", entity_type="face", component_id="disk",
            owner_body_handle_id="body", producer_node_id="n1",
            semantic_role="test", status="active",
            current_locator={"owner_body_handle_id": "body", "entity_type": "edge",
                             "indexed_map_position": 1, "occt_shape_hash": 0},
        )
        reg = TopologyRegistry()
        reg.register_entity(rec)
        r = reg.resolve("gct2_e")
        assert r.status != "exact", "Face record with edge locator cannot be exact"
