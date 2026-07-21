"""PR-2: Kernel/Identity layering + TrustCertificate — §2.5, §2.9, §2.11 tests.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.5, §2.9, §2.11
"""

from seekflow_engineering_tools.generative_cad.topology.kernel_identity import (
    IdentityDecision,
    IdentityRelation,
    IdentityTransferPolicy,
    KernelHistoryEdge,
    KernelRelation,
)
from seekflow_engineering_tools.generative_cad.topology.trust_certificate import (
    TopologyTrustCertificate,
    TrustLevel,
    trust_meets_quality,
)
from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyEntityRecord,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry


# ═══════════════════════════════════════════════════════════════════════════════
# §2.9 — Kernel relation → Identity decision layering
# ═══════════════════════════════════════════════════════════════════════════════


class TestKernelHistoryEdge:
    """Verify KernelHistoryEdge captures pure OCCT observations."""

    def test_kernel_edge_construction(self):
        edge = KernelHistoryEdge(
            source_pid="gct3_aaa",
            result_occurrence_key="body_1:face:3",
            kernel_relation=KernelRelation.MODIFIED,
        )
        assert edge.source_pid == "gct3_aaa"
        assert edge.kernel_relation == KernelRelation.MODIFIED

    def test_all_kernel_relations_defined(self):
        assert KernelRelation.SAME.value == "same"
        assert KernelRelation.MODIFIED.value == "modified"
        assert KernelRelation.GENERATED.value == "generated"
        assert KernelRelation.REMOVED.value == "removed"


class TestIdentityTransferPolicy:
    """Verify the 8-dimension decision engine (§2.9)."""

    def test_target_face_modified_keeps_identity(self):
        """Default rule: target face + kernel modified → modified_same_identity."""
        edges = [KernelHistoryEdge(
            source_pid="disk.hub",
            result_occurrence_key="body:face:0",
            kernel_relation=KernelRelation.MODIFIED,
        )]
        decision = IdentityTransferPolicy.decide(
            edges, source_role="target", operation_kind="boolean_cut",
        )
        assert decision.identity_relation == IdentityRelation.MODIFIED_SAME_IDENTITY
        assert decision.preserves_identity is True

    def test_tool_face_modified_becomes_generated_from_tool(self):
        """KEY RULE (§2.9): tool face + kernel modified → generated_from_tool."""
        edges = [KernelHistoryEdge(
            source_pid="cutter.slot_017",
            result_occurrence_key="body:face:42",
            kernel_relation=KernelRelation.MODIFIED,
        )]
        decision = IdentityTransferPolicy.decide(
            edges, source_role="tool", operation_kind="boolean_cut",
        )
        assert decision.identity_relation == IdentityRelation.GENERATED_FROM_TOOL
        assert decision.preserves_identity is False
        assert decision.creates_new_identity is True

    def test_target_face_split_detected_by_cardinality(self):
        """Cardinality 1:N → split regardless of kernel relation."""
        edges = [KernelHistoryEdge(
            source_pid="disk.rim",
            result_occurrence_key="body:face:5",
            kernel_relation=KernelRelation.MODIFIED,
        )]
        decision = IdentityTransferPolicy.decide(
            edges, source_role="target", cardinality=(1, 3),
        )
        assert decision.identity_relation == IdentityRelation.SPLIT

    def test_tool_face_removed_is_consumed(self):
        """Tool face + kernel removed → consumed."""
        edges = [KernelHistoryEdge(
            source_pid="cutter.slot_017",
            result_occurrence_key="",
            kernel_relation=KernelRelation.REMOVED,
        )]
        decision = IdentityTransferPolicy.decide(
            edges, source_role="tool",
        )
        assert decision.identity_relation == IdentityRelation.CONSUMED

    def test_profile_generated_creates_new_identity(self):
        """Profile + generated → generated_new_identity."""
        edges = [KernelHistoryEdge(
            source_pid="profile.edge_left",
            result_occurrence_key="body:face:2",
            kernel_relation=KernelRelation.GENERATED,
        )]
        decision = IdentityTransferPolicy.decide(
            edges, source_role="profile",
        )
        assert decision.identity_relation == IdentityRelation.GENERATED_NEW_IDENTITY

    def test_provenance_edges_preserved_in_decision(self):
        """All kernel edges are carried through in provenance_edges."""
        edges = [
            KernelHistoryEdge(
                source_pid="disk.hub",
                result_occurrence_key="body:face:1",
                kernel_relation=KernelRelation.MODIFIED,
            ),
        ]
        decision = IdentityTransferPolicy.decide(edges, source_role="target")
        assert len(decision.provenance_edges) == 1
        assert decision.provenance_edges[0].source_pid == "disk.hub"


# ═══════════════════════════════════════════════════════════════════════════════
# §2.11 — TopologyTrustCertificate
# ═══════════════════════════════════════════════════════════════════════════════


class TestTopologyTrustCertificate:
    """Verify multi-dimensional trust assessment replaces string ranking (§2.11)."""

    def test_full_verification_yields_strong_kernel_history(self):
        """All 5 flags + kernel_generated → strong_kernel_history."""
        rec = TopologyEntityRecord(
            persistent_id="gct3_test",
            entity_type="face",
            component_id="disk",
            owner_body_handle_id="solid:disk:body",
            producer_node_id="revolve_main",
            semantic_role="revolved/cylindrical",
            resolution_method="kernel_generated",
        )
        cert = TopologyTrustCertificate.assess(
            rec,
            binding_verified=True,
            coverage_verified=True,
            orientation_verified=True,
            event_chain_verified=True,
            provider_capability_verified=True,
        )
        assert cert.trust_level == TrustLevel.STRONG_KERNEL_HISTORY
        assert cert.is_strong is True
        assert cert.verified_count == 5

    def test_partial_verification_yields_operation_semantic_exact(self):
        """3 flags + deterministic_semantic → operation_semantic_exact."""
        rec = TopologyEntityRecord(
            persistent_id="gct3_test",
            entity_type="face",
            component_id="disk",
            owner_body_handle_id="solid:disk:body",
            producer_node_id="revolve_main",
            semantic_role="revolved/cylindrical",
            resolution_method="kernel_selected",
        )
        cert = TopologyTrustCertificate.assess(
            rec,
            binding_verified=True,
            coverage_verified=True,
            orientation_verified=True,
            event_chain_verified=False,
            provider_capability_verified=False,
        )
        assert cert.trust_level == TrustLevel.OPERATION_SEMANTIC_EXACT
        assert cert.is_strong is False
        assert cert.verified_count == 3

    def test_primitive_semantic_without_verification_is_unresolved(self):
        """§2.11 rule 4: primitive_semantic without verified flags → unresolved."""
        rec = TopologyEntityRecord(
            persistent_id="gct3_test",
            entity_type="face",
            component_id="disk",
            owner_body_handle_id="solid:disk:body",
            producer_node_id="boolean_union",
            semantic_role="boolean/face/0",
            resolution_method="primitive_semantic",
        )
        cert = TopologyTrustCertificate.assess(rec)
        assert cert.trust_level == TrustLevel.UNRESOLVED, (
            "§2.11 rule 4: primitive_semantic must NOT auto-prove trust — "
            f"got {cert.trust_level.value}"
        )

    def test_ambiguity_overrides_all_other_evidence(self):
        """Ambiguity count > 0 → ambiguous regardless of other flags."""
        rec = TopologyEntityRecord(
            persistent_id="gct3_test",
            entity_type="face",
            component_id="disk",
            owner_body_handle_id="solid:disk:body",
            producer_node_id="revolve_main",
            semantic_role="revolved/cylindrical",
            resolution_method="kernel_generated",
        )
        cert = TopologyTrustCertificate.assess(
            rec,
            binding_verified=True,
            coverage_verified=True,
            orientation_verified=True,
            event_chain_verified=True,
            provider_capability_verified=True,
            ambiguity_count=3,
        )
        assert cert.trust_level == TrustLevel.AMBIGUOUS


class TestTrustMeetsQuality:
    """Verify trust_meets_quality bridges V3 trust to V2 consumer policies."""

    def test_strong_kernel_history_meets_exact_requirement(self):
        assert trust_meets_quality("strong_kernel_history", "exact_kernel_history") is True

    def test_fingerprint_unique_does_not_meet_exact(self):
        assert trust_meets_quality("fingerprint_unique", "exact_kernel_history") is False

    def test_operation_semantic_exact_meets_deterministic(self):
        assert trust_meets_quality("operation_semantic_exact", "deterministic_semantic") is True


# ═══════════════════════════════════════════════════════════════════════════════
# §2.9 — Registry apply_identity_decisions integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegistryApplyIdentityDecisions:
    """Verify TopologyRegistry.apply_identity_decisions() dispatches correctly."""

    def test_unchanged_decision_increments_generation(self):
        """Unchanged decision → generation++, kernel edge recorded in evidence."""
        reg = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct3_disk_hub",
            entity_type="face",
            component_id="disk",
            owner_body_handle_id="solid:disk:body",
            producer_node_id="revolve_main",
            semantic_role="disk/hub",
        )
        reg.register_entity(rec)

        edges = [KernelHistoryEdge(
            source_pid="gct3_disk_hub",
            result_occurrence_key="body:face:0",
            kernel_relation=KernelRelation.SAME,
        )]
        decision = IdentityDecision(
            source_pids=["gct3_disk_hub"],
            result_keys=[],
            identity_relation=IdentityRelation.UNCHANGED,
            provenance_edges=edges,
        )
        reg.apply_identity_decisions([decision], node_id="cut_bore", component_id="disk")
        updated = reg._entities["gct3_disk_hub"]
        assert updated.generation == 1

    def test_generated_from_tool_records_evidence_on_source(self):
        """V3 Phase 14: apply_identity_decisions() no longer creates new records.
        Instead it records evidence on the tool source and lets the delta path
        (build_entity_records_from_delta) create proper gct3_ PIDs."""
        reg = TopologyRegistry()
        tool = TopologyEntityRecord(
            persistent_id="gct3_cutter_slot",
            entity_type="face",
            component_id="disk",
            owner_body_handle_id="solid:cutter:body",
            producer_node_id="extrude_cutter",
            semantic_role="cutter/pressure_face",
        )
        reg.register_entity(tool)

        decision = IdentityDecision(
            source_pids=["gct3_cutter_slot"],
            result_keys=["gct3_disk_slot_wall"],
            identity_relation=IdentityRelation.GENERATED_FROM_TOOL,
        )
        reg.apply_identity_decisions([decision], node_id="boolean_cut", component_id="disk")
        # V3: no new records created; evidence is recorded on source
        assert reg.get_entity("gct3_cutter_slot") is not None
        assert "gct3_disk_slot_wall" not in reg._entities

    def test_consumed_marks_tool_as_deleted(self):
        """Consumed decision → tool entity marked as deleted."""
        reg = TopologyRegistry()
        tool = TopologyEntityRecord(
            persistent_id="gct3_cutter_slot",
            entity_type="face",
            component_id="disk",
            owner_body_handle_id="solid:cutter:body",
            producer_node_id="extrude_cutter",
            semantic_role="cutter/pressure_face",
        )
        reg.register_entity(tool)

        decision = IdentityDecision(
            source_pids=["gct3_cutter_slot"],
            result_keys=[],
            identity_relation=IdentityRelation.CONSUMED,
        )
        reg.apply_identity_decisions([decision], node_id="boolean_cut", component_id="disk")
        assert reg._entities["gct3_cutter_slot"].status == "deleted"


# ═══════════════════════════════════════════════════════════════════════════════
# §2.5 — IdentityDecision preserves orientation/location tracking
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdentityDecisionOrientationTracking:
    """Verify §2.5 orientation/location fields on IdentityDecision."""

    def test_unchanged_decision_defaults_to_none_occurrence_change(self):
        decision = IdentityDecision(
            source_pids=["gct3_face"],
            result_keys=[],
            identity_relation=IdentityRelation.UNCHANGED,
        )
        assert decision.occurrence_change == "none"

    def test_reoriented_decision_tracks_orientation(self):
        decision = IdentityDecision(
            source_pids=["gct3_face"],
            result_keys=[],
            identity_relation=IdentityRelation.REORIENTED,
            orientation_before="Forward",
            orientation_after="Reversed",
            occurrence_change="reoriented",
        )
        assert decision.orientation_before == "Forward"
        assert decision.orientation_after == "Reversed"
        assert decision.identity_relation == IdentityRelation.REORIENTED
