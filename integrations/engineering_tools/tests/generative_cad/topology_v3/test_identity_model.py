"""Phase 1 tests — V3 identity model (TopologyIdentityDescriptorV3).

Verifies V3 invariants from docs/G-CAD持久化拓扑V3修复与升级执行规范.md:
  I-01: Identity does not depend on runtime B-Rep enumeration
  I-02: Identity, lifecycle, binding, proof are independent
  I-03: 1:1 modification preserves logical identity
"""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ids import (
    LEGACY_V1_MARKER,
    LEGACY_V2_IRREVERSIBLE,
    PersistentTopoId,
    PersistentTopoIdV2,
    TopologyIdentityDescriptorV3,
    make_persistent_id_v3,
    parse_persistent_id_key,
)
from seekflow_engineering_tools.generative_cad.topology.models import (
    BindingState,
    EntityLifecycle,
    ProofClass,
    TopologyEntityRecord,
)
class TestV3IdentityDescriptor:
    """V3 identity model — descriptor, key computation, invariants."""

    def test_v3_descriptor_deterministic_key(self):
        """Same descriptor → byte-identical key (deterministic canonical JSON)."""
        desc_a = TopologyIdentityDescriptorV3(
            document_lineage_id="doc-lineage-1",
            component_stable_id="disk",
            feature_stable_id="revolve_main",
            entity_type="face",
            semantic_path=("revolved", "from", "edge_left"),
        )
        desc_b = TopologyIdentityDescriptorV3(
            document_lineage_id="doc-lineage-1",
            component_stable_id="disk",
            feature_stable_id="revolve_main",
            entity_type="face",
            semantic_path=("revolved", "from", "edge_left"),
        )
        assert desc_a.to_key() == desc_b.to_key(), (
            "V3 keys must be deterministic for identical descriptors"
        )

    def test_v3_key_changes_on_different_feature(self):
        """Different feature_stable_id → different keys."""
        key_a = TopologyIdentityDescriptorV3(
            document_lineage_id="doc-1",
            component_stable_id="disk",
            feature_stable_id="revolve_main",
            entity_type="face",
            semantic_path=("cap", "start"),
        ).to_key()
        key_b = TopologyIdentityDescriptorV3(
            document_lineage_id="doc-1",
            component_stable_id="disk",
            feature_stable_id="revolve_secondary",
            entity_type="face",
            semantic_path=("cap", "start"),
        ).to_key()
        assert key_a != key_b, (
            "V3 keys must differ when feature_stable_id differs"
        )

    def test_v3_key_stable_across_producer_node_change(self):
        """Simulated 'node rename': same lineage/feature → same key.

        This is the key improvement over v2: V3 does NOT hash producer_node_id.
        Only document_lineage_id + component_stable_id + feature_stable_id
        determine identity. Node renames do not change the key.
        """
        key_a = TopologyIdentityDescriptorV3(
            document_lineage_id="doc-lineage-1",
            component_stable_id="disk",
            feature_stable_id="revolve_main",
            entity_type="face",
            semantic_path=("cap", "start"),
        ).to_key()
        # Same identity — only the producer_node_id (not in V3) differs
        key_b = TopologyIdentityDescriptorV3(
            document_lineage_id="doc-lineage-1",
            component_stable_id="disk",
            feature_stable_id="revolve_main",
            entity_type="face",
            semantic_path=("cap", "start"),
        ).to_key()
        assert key_a == key_b, (
            "V3 keys must be stable when only producer_node_id changes"
        )

    def test_v3_key_preserves_semantic_path_order(self):
        """Different semantic_path ordering → different keys."""
        key_a = TopologyIdentityDescriptorV3(
            document_lineage_id="doc-1",
            component_stable_id="disk",
            feature_stable_id="f1",
            entity_type="face",
            semantic_path=("cap", "start"),
        ).to_key()
        key_b = TopologyIdentityDescriptorV3(
            document_lineage_id="doc-1",
            component_stable_id="disk",
            feature_stable_id="f1",
            entity_type="face",
            semantic_path=("start", "cap"),  # reversed
        ).to_key()
        assert key_a != key_b, (
            "V3 keys must differ when semantic_path order differs"
        )

    def test_v3_descriptor_full_round_trip(self):
        """descriptor → model_dump → from_descriptor_dict → same key."""
        desc = TopologyIdentityDescriptorV3(
            document_lineage_id="doc-1",
            component_stable_id="disk",
            feature_stable_id="f1",
            entity_type="edge",
            semantic_path=("hole", "entry_rim"),
            source_entity_keys=("gct3_src_key",),
            branch_key="branch_a",
            algorithm_version="3.0.0",
        )
        key = desc.to_key()
        # Simulate sidecar round-trip
        restored = TopologyIdentityDescriptorV3.from_descriptor_dict(
            desc.model_dump()
        )
        assert restored.to_key() == key, (
            "V3 descriptor must survive model_dump → from_descriptor_dict round-trip"
        )
        assert restored.semantic_path == ("hole", "entry_rim")
        assert restored.source_entity_keys == ("gct3_src_key",)
        assert restored.branch_key == "branch_a"

    def test_make_persistent_id_v3_factory(self):
        """Factory function produces a key and descriptor."""
        key, desc = make_persistent_id_v3(
            document_lineage_id="doc-1",
            component_stable_id="disk",
            feature_stable_id="f1",
            entity_type="face",
            semantic_path=("cap", "start"),
        )
        assert key.startswith("gct3_")
        assert len(key) == 48  # "gct3_" + 43 char base64url
        assert desc.document_lineage_id == "doc-1"
        assert desc.feature_stable_id == "f1"
        assert desc.semantic_path == ("cap", "start")
        assert key == desc.to_key()


class TestV3SemanticPathValidation:
    """I-01: semantic_path rejects runtime index tokens."""

    def test_valid_semantic_paths_accepted(self):
        """Descriptive tokens are valid."""
        valid_cases = [
            ("cap", "start"),
            ("cap", "end"),
            ("revolved", "from", "edge_left"),
            ("hole", "wall"),
            ("body",),
            ("extrude", "side", "from_edge_front"),
        ]
        for path in valid_cases:
            desc = TopologyIdentityDescriptorV3(
                document_lineage_id="d1",
                component_stable_id="c1",
                feature_stable_id="f1",
                entity_type="face",
                semantic_path=path,
            )
            assert desc.semantic_path == path

    def test_pure_numeric_token_rejected(self):
        """Bare integer tokens are runtime indices — rejected."""
        with pytest.raises(ValueError, match="raw index|semantic_path"):
            TopologyIdentityDescriptorV3(
                document_lineage_id="d1",
                component_stable_id="c1",
                feature_stable_id="f1",
                entity_type="face",
                semantic_path=("face", "3"),
            )

    def test_bare_entity_type_token_rejected(self):
        """'face', 'edge', 'vertex' alone are not descriptive."""
        with pytest.raises(ValueError, match="bare entity type|semantic_path"):
            TopologyIdentityDescriptorV3(
                document_lineage_id="d1",
                component_stable_id="c1",
                feature_stable_id="f1",
                entity_type="face",
                semantic_path=("face",),
            )

    def test_runtime_index_pattern_accepted_as_legacy(self):
        """V3: ordinal patterns accepted as legacy (deferred to Phase 4+ OCP migration).

        Tokens like 'side_face_3', 'face_0' pass validation — they will be
        rejected at source when handlers stop producing them.
        """
        legacy_paths = [
            ("side_face_3",),
            ("face_0",),
            ("edge_12",),
        ]
        for path in legacy_paths:
            desc = TopologyIdentityDescriptorV3(
                document_lineage_id="d1", component_stable_id="c1",
                feature_stable_id="f1", entity_type="face",
                semantic_path=path,
            )
            assert desc.semantic_path == path

    def test_empty_semantic_path_rejected(self):
        """At least one token required."""
        with pytest.raises(ValueError, match="at least one token"):
            TopologyIdentityDescriptorV3(
                document_lineage_id="d1",
                component_stable_id="c1",
                feature_stable_id="f1",
                entity_type="face",
                semantic_path=(),
            )


class TestV3EntityRecordInvariants:
    """I-02/I-03: TopologyEntityRecord V3 field invariants."""

    def test_entity_record_rejects_active_unbound(self):
        """lifecycle=ACTIVE with binding_state=UNBOUND is illegal."""
        with pytest.raises(ValueError, match="ACTIVE.*UNBOUND|active.*unbound"):
            TopologyEntityRecord(
                persistent_id="gct3_test_key",
                entity_type="face",
                component_id="disk",
                owner_body_handle_id="solid:disk:n1:body",
                producer_node_id="n1",
                semantic_role="cap/start",
                lifecycle=EntityLifecycle.ACTIVE,
                binding_state=BindingState.UNBOUND,
                proof_class=ProofClass.NONE,
            )

    def test_entity_record_accepts_active_bound(self):
        """lifecycle=ACTIVE with binding_state=BOUND is valid."""
        rec = TopologyEntityRecord(
            persistent_id="gct3_test_bound",
            entity_type="face",
            component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1",
            semantic_role="cap/start",
            lifecycle=EntityLifecycle.ACTIVE,
            binding_state=BindingState.BOUND,
            proof_class=ProofClass.EXACT_GENERATED_HISTORY,
        )
        assert rec.lifecycle == EntityLifecycle.ACTIVE
        assert rec.binding_state == BindingState.BOUND

    def test_entity_record_rejects_superseded_bound(self):
        """lifecycle=SUPERSEDED with binding_state=BOUND is illegal."""
        with pytest.raises(ValueError, match="SUPERSEDED.*BOUND|superseded.*bound"):
            TopologyEntityRecord(
                persistent_id="gct3_old",
                entity_type="face",
                component_id="disk",
                owner_body_handle_id="solid:disk:n1:body",
                producer_node_id="n1",
                semantic_role="old_face",
                lifecycle=EntityLifecycle.SUPERSEDED,
                binding_state=BindingState.BOUND,
            )

    def test_entity_record_rejects_deleted_bound(self):
        """lifecycle=DELETED with binding_state=BOUND is illegal."""
        with pytest.raises(ValueError, match="DELETED.*BOUND|deleted.*bound"):
            TopologyEntityRecord(
                persistent_id="gct3_gone",
                entity_type="face",
                component_id="disk",
                owner_body_handle_id="solid:disk:n1:body",
                producer_node_id="n1",
                semantic_role="gone",
                lifecycle=EntityLifecycle.DELETED,
                binding_state=BindingState.BOUND,
            )

    def test_entity_record_backward_compat_no_v3_fields(self):
        """Records without V3 fields still work (backward compat)."""
        rec = TopologyEntityRecord(
            persistent_id="gct2_old_style",
            entity_type="face",
            component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1",
            semantic_role="cap/start",
            status="active",
            resolution_method="primitive_semantic",
        )
        assert rec.lifecycle is None
        assert rec.binding_state is None
        assert rec.proof_class is None
        assert rec.status == "active"


class TestV3MigrationReader:
    """V3 §4.1 + Phase 1: parse_persistent_id_key() for v1/v2/v3 migration."""

    def test_parse_v3_key(self):
        key, _ = make_persistent_id_v3(
            document_lineage_id="doc-1",
            component_stable_id="disk",
            feature_stable_id="f1",
            entity_type="face",
            semantic_path=("cap", "start"),
        )
        result = parse_persistent_id_key(key)
        assert result["version"] == "v3"
        assert result["scheme"] == "gcad_topo_v3"

    def test_parse_v2_key(self):
        pid = PersistentTopoIdV2(
            document_id="doc-1",
            component_id="disk",
            lineage_root_node_id="n1",
            producer_node_id="n1",
            entity_type="face",
            semantic_role="cap/start",
        )
        result = parse_persistent_id_key(pid.to_key())
        assert result["version"] == "v2"
        assert result["legacy_status"] == LEGACY_V2_IRREVERSIBLE

    def test_parse_v1_key(self):
        pid = PersistentTopoId(
            document_id="doc-1-long-id",
            component_id="disk",
            lineage_root_node_id="n1",
            producer_node_id="n1",
            entity_type="face",
            semantic_role="box/x_max",
        )
        result = parse_persistent_id_key(pid.to_compact())
        assert result["version"] == "v1"
        assert result["legacy_status"] == LEGACY_V1_MARKER

    def test_parse_unknown_key(self):
        result = parse_persistent_id_key("totally_random_string")
        assert result["version"] == "unknown"

    def test_parse_empty_key(self):
        result = parse_persistent_id_key("")
        assert result["version"] == "unknown"


class TestV2Regression:
    """Existing v1/v2 classes still work (deprecated but not removed)."""

    def test_v1_to_compact_still_works(self):
        pid = PersistentTopoId(
            document_id="doc-1", component_id="disk",
            lineage_root_node_id="n1", producer_node_id="n1",
            entity_type="face", semantic_role="box/x_max",
        )
        compact = pid.to_compact()
        assert compact.startswith("gct:v1:")
        assert "box/x_max" in compact

    def test_v2_to_key_still_works(self):
        pid = PersistentTopoIdV2(
            document_id="doc-1", component_id="disk",
            lineage_root_node_id="n1", producer_node_id="n1",
            entity_type="face", semantic_role="cap/start",
        )
        key = pid.to_key()
        assert key.startswith("gct2_")
        assert len(key) == 48
