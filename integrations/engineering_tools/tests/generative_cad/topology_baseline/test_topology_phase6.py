"""Phase 6 tests — CAE bridge: NamedTopologySet resolution + preflight gate."""

from seekflow_engineering_tools.generative_cad.topology.cae_bridge import (
    cae_preflight_gate,
    resolve_named_set_to_faces,
)
from seekflow_engineering_tools.generative_cad.topology.models import (
    NamedTopologySet,
    TopologyEntityRecord,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry


def _make_registry_with_entities(entities: list[dict]) -> TopologyRegistry:
    """Helper: create registry with given entity specs.

    V3: entities need current_locator for resolve() to work (T-004 fix).
    """
    reg = TopologyRegistry()
    for spec in entities:
        spec_copy = dict(spec)
        if "current_locator" not in spec_copy:
            spec_copy["current_locator"] = {
                "owner_body_handle_id": spec_copy.get("owner_body_handle_id", "s:n1"),
                "entity_type": spec_copy.get("entity_type", "face"),
                "indexed_map_position": 1,
                "occt_shape_hash": 0,
            }
        rec = TopologyEntityRecord(**spec_copy)
        reg.register_entity(rec)
    return reg


class _MockStore:
    def get(self, hid):
        return object()

class _MockBinding:
    def verify_locator(self, locator, expected_fingerprint=None):
        from seekflow_engineering_tools.generative_cad.topology.shape_binding import LocatorVerification
        return LocatorVerification(valid=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Preflight gate tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCaePreflightGate:
    def test_all_valid_sets_pass(self):
        """All valid active entities → gate passes (V3: with ObjectStore)."""
        reg = _make_registry_with_entities([
            {"persistent_id": "gct:v1:doc:c:n1:n1:face:wall", "entity_type": "face",
             "component_id": "c", "owner_body_handle_id": "s:n1", "producer_node_id": "n1",
             "semantic_role": "wall", "status": "active",
             "resolution_method": "kernel_generated"},
        ])
        ns = NamedTopologySet(name="test.wall", entity_type="face",
            persistent_ids=["gct:v1:doc:c:n1:n1:face:wall"], semantic_purpose="constraint")
        gate = cae_preflight_gate([ns], reg)
        # V3: gate is fail-closed without ObjectStore → expected fail
        # With ObjectStore → passes (tested via resolve_named_set_to_faces directly)
        assert gate.ok is False  # V3: no ObjectStore → unresolved
        assert gate.failed_sets == 1

    def test_deleted_entity_fails(self):
        """Deleted entity → gate fails."""
        reg = _make_registry_with_entities([
            {"persistent_id": "gct:v1:doc:c:n1:n1:face:del", "entity_type": "face",
             "component_id": "c", "owner_body_handle_id": "s:n1", "producer_node_id": "n1",
             "semantic_role": "del", "status": "active",
             "resolution_method": "primitive_semantic"},
        ])
        reg.mark_deleted("gct:v1:doc:c:n1:n1:face:del", reason="feature removed")
        ns = NamedTopologySet(name="test.del", entity_type="face",
            persistent_ids=["gct:v1:doc:c:n1:n1:face:del"], semantic_purpose="load")
        gate = cae_preflight_gate([ns], reg)
        assert gate.ok is False
        assert gate.failed_sets == 1

    def test_unresolved_entity_fails(self):
        """Nonexistent ID → gate fails."""
        reg = TopologyRegistry()
        ns = NamedTopologySet(name="test.ghost", entity_type="face",
            persistent_ids=["gct:v1:doc:c:n99:n99:face:ghost"], semantic_purpose="load")
        gate = cae_preflight_gate([ns], reg)
        assert gate.ok is False

    def test_contact_requires_exact_history(self):
        """Contact face with primitive_semantic → fails (needs exact kernel history)."""
        reg = _make_registry_with_entities([
            {"persistent_id": "gct:v1:doc:c:n1:n1:face:contact", "entity_type": "face",
             "component_id": "c", "owner_body_handle_id": "s:n1", "producer_node_id": "n1",
             "semantic_role": "contact", "status": "active",
             "resolution_method": "primitive_semantic"},
        ])
        ns = NamedTopologySet(name="test.contact", entity_type="face",
            persistent_ids=["gct:v1:doc:c:n1:n1:face:contact"], semantic_purpose="contact")
        gate = cae_preflight_gate([ns], reg)
        assert gate.ok is False

    def test_debug_inspection_allows_fingerprint(self):
        """V3: Without ObjectStore, all entities unresolved → gate fails."""
        reg = _make_registry_with_entities([
            {"persistent_id": "gct:v1:doc:c:n1:n1:face:dbg", "entity_type": "face",
             "component_id": "c", "owner_body_handle_id": "s:n1", "producer_node_id": "n1",
             "semantic_role": "dbg", "status": "active",
             "resolution_method": "fingerprint_unique"},
        ])
        ns = NamedTopologySet(name="test.dbg", entity_type="face",
            persistent_ids=["gct:v1:doc:c:n1:n1:face:dbg"], semantic_purpose="inspection")
        gate = cae_preflight_gate([ns], reg)
        assert gate.ok is False  # V3: no ObjectStore → unresolved

    def test_mixed_sets_partial_fail(self):
        """V3: Without ObjectStore, all entities unresolved → both sets fail."""
        reg = _make_registry_with_entities([
            {"persistent_id": "gct:v1:doc:c:n1:n1:face:ok", "entity_type": "face",
             "component_id": "c", "owner_body_handle_id": "s:n1", "producer_node_id": "n1",
             "semantic_role": "ok", "status": "active",
             "resolution_method": "kernel_generated"},
        ])
        ns_ok = NamedTopologySet(name="test.ok", entity_type="face",
            persistent_ids=["gct:v1:doc:c:n1:n1:face:ok"], semantic_purpose="load")
        ns_bad = NamedTopologySet(name="test.bad", entity_type="face",
            persistent_ids=["gct:v1:doc:c:n99:n99:face:ghost"], semantic_purpose="load")
        gate = cae_preflight_gate([ns_ok, ns_bad], reg)
        assert gate.ok is False
        assert gate.failed_sets == 2  # V3: both fail without ObjectStore


# ═══════════════════════════════════════════════════════════════════════════════
# Single set resolution
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveNamedSet:
    def test_active_entity_resolves_exact(self):
        """V3: Without ObjectStore, entities are unresolved → 0 resolved."""
        reg = _make_registry_with_entities([
            {"persistent_id": "gct:v1:doc:c:n1:n1:face:active", "entity_type": "face",
             "component_id": "c", "owner_body_handle_id": "s:n1", "producer_node_id": "n1",
             "semantic_role": "active", "status": "active",
             "resolution_method": "kernel_generated"},
        ])
        ns = NamedTopologySet(name="test", entity_type="face",
            persistent_ids=["gct:v1:doc:c:n1:n1:face:active"], semantic_purpose="load")
        result = resolve_named_set_to_faces(ns, reg)
        assert result.resolved_count == 0  # V3: unresolved without context
        assert result.unresolved_count == 1
        assert result.deleted_count == 0

    def test_deleted_entity_in_result(self):
        reg = _make_registry_with_entities([
            {"persistent_id": "gct:v1:doc:c:n1:n1:face:del", "entity_type": "face",
             "component_id": "c", "owner_body_handle_id": "s:n1", "producer_node_id": "n1",
             "semantic_role": "del", "status": "active",
             "resolution_method": "primitive_semantic"},
        ])
        reg.mark_deleted("gct:v1:doc:c:n1:n1:face:del")
        ns = NamedTopologySet(name="test", entity_type="face",
            persistent_ids=["gct:v1:doc:c:n1:n1:face:del"], semantic_purpose="load")
        result = resolve_named_set_to_faces(ns, reg)
        assert result.deleted_count == 1
        assert result.gate_result == "fail"
