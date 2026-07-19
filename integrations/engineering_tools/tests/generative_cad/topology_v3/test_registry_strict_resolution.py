"""Phase 0 characterization tests — registry strict resolution (V3 §4.3, Appendix A).

These tests verify the TopologyRegistry's known defects in resolution,
lineage closure, delta validation, and sidecar restore.

Tests marked xfail expose known issues to be fixed in Phase 2+.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyDelta,
    TopologyEntityRecord,
    TopologyRelation,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.persistence import (
    read_topology_sidecar,
    write_topology_sidecar,
)


class TestRegistryStrictResolution:
    """V3 §4.3: resolve() must require actual B-Rep binding evidence."""

    def test_resolve_without_binding_context_returns_exact(self):
        """T-004 BASELINE: Without ObjectStore, active → exact (current behavior).

        This PASSES on current code — it documents the baseline behavior.
        Phase 2 will change this to require explicit binding context.
        """
        reg = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct2_baseline",
            entity_type="face", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1", semantic_role="cap/start",
            status="active", resolution_method="primitive_semantic",
            current_locator={"owner_body_handle_id": "solid:disk:n1:body",
                             "entity_type": "face", "indexed_map_position": 1},
        )
        reg.register_entity(rec)
        # No explicit object_store or binding_service
        result = reg.resolve("gct2_baseline")
        # Current baseline: returns exact
        # Future (Phase 2): should return unresolved without binding context
        assert result.status == "exact"

    @pytest.mark.xfail(
        reason=(
            "T-006: IndexedMap position has no owner body revision. "
            "No mechanism to detect stale locators after owner replacement."
        ),
        strict=True,
    )
    def test_strict_resolve_rejects_stale_owner_revision(self):
        """T-006: Owner body replacement must invalidate old locators.

        V3 target: locator carries owner_body_revision_id. When owner body
        changes, old locators become stale and resolve() returns unresolved.
        """
        # Current code: locator has no revision token. We test that two
        # locators with different owner_body_handle_id are treated differently.
        reg = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct2_owner_test",
            entity_type="face", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1", semantic_role="cap/start",
            status="active", resolution_method="primitive_semantic",
            current_locator={
                "owner_body_handle_id": "solid:disk:n1:body",
                "entity_type": "face", "indexed_map_position": 1,
                # No revision token — this is the V2 defect
            },
        )
        reg.register_entity(rec)
        # Simulate: owner body was rebuilt → new handle
        # In V3, this should return unresolved because the owner revision
        # in the locator no longer matches.
        result = reg.resolve("gct2_owner_test")
        assert result.status == "unresolved", (
            f"T-006 FAIL: expected unresolved (stale owner), got {result.status}"
        )

    @pytest.mark.xfail(
        reason=(
            "T-005: entity_type mismatch between record and locator is not "
            "consistently enforced in all resolve paths."
        ),
        strict=True,
    )
    def test_strict_resolve_rejects_wrong_entity_type(self):
        """T-005: Face record with edge locator → type_mismatch, not exact.

        V3 target: entity_type in record MUST match locator.entity_type.
        """
        reg = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct2_type_test",
            entity_type="face",  # record says face
            component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1", semantic_role="rim",
            status="active", resolution_method="primitive_semantic",
            current_locator={
                "owner_body_handle_id": "solid:disk:n1:body",
                "entity_type": "edge",  # locator says edge — MISMATCH
                "indexed_map_position": 1,
            },
        )
        reg.register_entity(rec)
        result = reg.resolve("gct2_type_test")
        assert result.status in ("type_mismatch", "unresolved"), (
            f"T-005 FAIL: face record with edge locator resolved as {result.status}"
        )

    @pytest.mark.xfail(
        reason=(
            "T-003: no global assignment/integrity check prevents two entities "
            "from sharing the same locator position (swap undetected)."
        ),
        strict=True,
    )
    def test_locator_swap_is_detected(self):
        """T-003: Swapping locators between two entities must be detected.

        V3 target: integrity check or resolve() detects when two entities
        claim the same owner_body + position with conflicting types.
        """
        reg = TopologyRegistry()
        rec_a = TopologyEntityRecord(
            persistent_id="gct2_swap_a",
            entity_type="face", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1", semantic_role="face_a",
            status="active", resolution_method="primitive_semantic",
            current_locator={
                "owner_body_handle_id": "solid:disk:n1:body",
                "entity_type": "edge", "indexed_map_position": 1,
                # This locator claims position 1 is an edge
            },
        )
        rec_b = TopologyEntityRecord(
            persistent_id="gct2_swap_b",
            entity_type="edge", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1", semantic_role="edge_a",
            status="active", resolution_method="primitive_semantic",
            current_locator={
                "owner_body_handle_id": "solid:disk:n1:body",
                "entity_type": "face", "indexed_map_position": 1,
                # Same position, conflicting type → SWAP DETECTED
            },
        )
        reg.register_entity(rec_a)
        reg.register_entity(rec_b)

        # Run integrity check — should detect the conflict
        integrity = reg.validate_integrity()
        assert not integrity["ok"], (
            "T-003 FAIL: locator swap undetected — integrity check passed "
            "despite two entities claiming same position with conflicting types"
        )


class TestSidecarRestore:
    """V3 §4.9: Sidecar restore must leave entities unbound."""

    @pytest.mark.xfail(
        reason=(
            "T-009: restore_snapshot() clears locator but keeps status=active. "
            "Subsequent resolve() returns exact for any active record. "
            "rebind_after_restore() must be called explicitly but is not enforced."
        ),
        strict=True,
    )
    def test_sidecar_restore_requires_rebind(self):
        """T-009: After sidecar restore, entities MUST NOT resolve as exact.

        V3 target: restore → all entities are unbound (stale or unresolved).
        Exact resolution requires successful rebind.
        """
        reg_a = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct2_sr_test",
            entity_type="face", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1", semantic_role="lateral",
            status="active", resolution_method="kernel_generated",
            current_locator={
                "owner_body_handle_id": "solid:disk:n1:body",
                "entity_type": "face", "indexed_map_position": 1,
            },
        )
        reg_a.register_entity(rec)

        with TemporaryDirectory() as tmp:
            sidecar_path = Path(tmp) / "test.topology.json"
            write_topology_sidecar(
                reg_a, sidecar_path,
                document_id="doc-1",
                canonical_graph_hash="sha256:deadbeef",
                runtime_version="0.2.0",
            )

            reg_b = TopologyRegistry()
            read_topology_sidecar(sidecar_path, reg_b)

            # After restore, locator is gone (stripped by export_snapshot)
            # but status is still active → resolve returns exact (T-009)
            result = reg_b.resolve("gct2_sr_test")
            assert result.status != "exact", (
                f"T-009 FAIL: after sidecar restore, entity resolved as {result.status}. "
                f"V3 target: all entities must be unbound after restore."
            )


class TestLineageAndDelta:
    """V3 §4.3: Lineage closure and delta validation."""

    @pytest.mark.xfail(
        reason=(
            "Registry.resolve() returns immediate descendants for superseded, "
            "not terminal closure (V3 §4.3 Lineage 闭包)."
        ),
        strict=True,
    )
    def test_recursive_terminal_lineage_closure(self):
        """V3 §4.3: superseded → recursive terminal descendants, skipping intermediates.

        V3 target: resolve(superseded) walks full descendant DAG to terminals.
        Deleted terminals are excluded from resolvable set.
        """
        reg = TopologyRegistry()
        # Chain: A (superseded) → B (superseded) → C (active)
        rec_a = TopologyEntityRecord(
            persistent_id="gct2_chain_a",
            entity_type="face", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1", semantic_role="original",
            status="superseded", descendant_ids=["gct2_chain_b"],
            resolution_method="set_expansion",
        )
        rec_b = TopologyEntityRecord(
            persistent_id="gct2_chain_b",
            entity_type="face", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n2", semantic_role="intermediate",
            status="superseded", descendant_ids=["gct2_chain_c"],
            ancestor_ids=["gct2_chain_a"],
            resolution_method="set_expansion",
        )
        rec_c = TopologyEntityRecord(
            persistent_id="gct2_chain_c",
            entity_type="face", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n3", semantic_role="terminal",
            status="active", ancestor_ids=["gct2_chain_b"],
        )
        reg.register_entity(rec_a)
        reg.register_entity(rec_b)
        reg.register_entity(rec_c)

        result = reg.resolve("gct2_chain_a")
        # V3 target: should return set with terminal C (gct2_chain_c),
        # not immediate descendant B
        assert "gct2_chain_c" in result.resolved_entity_ids, (
            f"T-LINEAGE FAIL: recursive closure did not reach terminal C. "
            f"Got: {result.resolved_entity_ids}"
        )
        assert "gct2_chain_b" not in result.resolved_entity_ids, (
            f"T-LINEAGE FAIL: intermediate superseded entity B should not be "
            f"in resolved set. Got: {result.resolved_entity_ids}"
        )

    @pytest.mark.xfail(
        reason=(
            "T-013: apply_delta records unknown source as event only. "
            "Should be a validation error in strict mode."
        ),
        strict=True,
    )
    def test_unknown_delta_source_is_fatal(self):
        """T-013: Unknown source_id in delta must be a validation error.

        V3 target: delta with unknown source → integrity error or rollback.
        """
        reg = TopologyRegistry()
        delta = TopologyDelta(
            node_id="n1", component_id="disk",
            history_provider="operation_semantics",
            relations=[
                TopologyRelation(
                    relation="modified",
                    source_ids=["gct2_nonexistent"],  # never registered
                    result_entity_keys=["gct2_new_entity"],
                ),
            ],
        )

        # V3 target: apply_delta should detect the unknown source and fail
        # Current behavior: records event "modify_unknown_source" and continues
        reg.apply_delta(delta)

        # Check that the issue was recorded as an error, not just an event
        events = [e for e in reg._events if e["event"] == "modify_unknown_source"]
        assert len(events) == 0, (
            f"T-013 FAIL: unknown delta source should be fatal, "
            f"not silently recorded as event. Events: {events}"
        )

    @pytest.mark.xfail(
        reason=(
            "T-013: 'unchanged' relation is a pass-through in apply_delta. "
            "Entities that pass through unchanged still need to be tracked."
        ),
        strict=True,
    )
    def test_unchanged_relation_is_applied(self):
        """T-013: 'unchanged' relation must be tracked in delta processing.

        V3 target: unchanged entities are explicitly tracked (not silently
        dropped), enabling pass-through verification.
        """
        reg = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct2_unchanged",
            entity_type="face", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1", semantic_role="survivor",
            status="active", resolution_method="kernel_generated",
        )
        reg.register_entity(rec)

        delta = TopologyDelta(
            node_id="n2", component_id="disk",
            history_provider="occt_boolean_history",
            relations=[
                TopologyRelation(
                    relation="unchanged",
                    source_ids=["gct2_unchanged"],
                ),
            ],
        )
        reg.apply_delta(delta)

        # V3 target: unchanged entity should be explicitly recorded as
        # passed-through in the delta evidence
        updated = reg.get_entity("gct2_unchanged")
        assert updated is not None
        # Evidence should contain an "unchanged" event for pass-through tracking
        has_unchanged_evidence = any(
            e.get("event") == "unchanged" for e in updated.evidence
        )
        assert has_unchanged_evidence, (
            f"T-013 FAIL: unchanged relation not applied. "
            f"Entity evidence: {updated.evidence}"
        )
