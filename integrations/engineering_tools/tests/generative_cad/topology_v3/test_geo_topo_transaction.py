"""Phase 3 tests — geometry-topology transaction verification."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.transaction import TopologyTransaction
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyDelta,
    TopologyEntityRecord,
    TopologyRelation,
)
from seekflow_engineering_tools.generative_cad.runtime.object_store import RuntimeObjectStore


class TestGeometryTopologyTransaction:
    """V3: Transaction validates geometry exists before committing topology."""

    def test_transaction_has_object_store(self):
        store = RuntimeObjectStore()
        reg = TopologyRegistry()
        tx = TopologyTransaction(reg, object_store=store)
        assert tx._object_store is store

    def test_transaction_without_object_store_is_legacy_compat(self):
        reg = TopologyRegistry()
        tx = TopologyTransaction(reg)  # no object_store
        assert tx._object_store is None
        # Should not raise — legacy mode
        delta = TopologyDelta(
            node_id='n1', component_id='disk',
            result_body_handle_ids=['solid:nonexistent:body'],
            history_provider='operation_semantics',
            relations=[TopologyRelation(relation='primitive', result_entity_keys=['gct2_key'])]
        )
        # Legacy: no object_store → validation skipped
        tx.validate_geometry_bindings(delta)

    def test_missing_body_in_delta_is_detected(self):
        store = RuntimeObjectStore()
        reg = TopologyRegistry()

        # Register the entity first (required by strict delta)
        rec = TopologyEntityRecord(
            persistent_id='gct2_key',
            entity_type='face', component_id='disk',
            owner_body_handle_id='solid:missing:body',
            producer_node_id='n1', semantic_role='test',
        )
        reg.register_entity(rec)

        tx = TopologyTransaction(reg, object_store=store)
        delta = TopologyDelta(
            node_id='n1', component_id='disk',
            result_body_handle_ids=['solid:missing:body'],
            history_provider='operation_semantics',
            relations=[TopologyRelation(relation='primitive', result_entity_keys=['gct2_key'])]
        )
        with pytest.raises(ValueError, match='not found.*ObjectStore|Geometry must be'):
            tx.validate_geometry_bindings(delta)

    def test_existing_body_in_delta_passes(self):
        store = RuntimeObjectStore()
        handle = type('Handle', (), {'id': 'solid:present:body', 'type': 'solid'})()
        store.put(handle, object())

        reg = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id='gct2_key',
            entity_type='face', component_id='disk',
            owner_body_handle_id='solid:present:body',
            producer_node_id='n1', semantic_role='test',
        )
        reg.register_entity(rec)

        tx = TopologyTransaction(reg, object_store=store)
        delta = TopologyDelta(
            node_id='n1', component_id='disk',
            result_body_handle_ids=['solid:present:body'],
            history_provider='operation_semantics',
            relations=[TopologyRelation(relation='primitive', result_entity_keys=['gct2_key'])]
        )
        # Should not raise — body exists in ObjectStore
        tx.validate_geometry_bindings(delta)
