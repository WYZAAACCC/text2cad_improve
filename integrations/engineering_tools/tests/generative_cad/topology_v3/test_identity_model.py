"""Phase 0 characterization tests — identity model invariants (V3 §4.1, Appendix A).

These tests verify the V2 identity model's known defects.
Tests marked xfail expose known issues to be fixed in Phase 1+.

DO NOT lower the bar in these tests when the implementation changes —
the assertions represent the V3 target behavior.
"""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ids import (
    PersistentTopoId,
    make_persistent_id_v2,
)
from seekflow_engineering_tools.generative_cad.topology.models import TopologyEntityRecord
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry


class TestIdentityModelInvariants:
    """V3 §4.1: Identity descriptor must not depend on mutable fields."""

    @pytest.mark.xfail(
        reason=(
            "T-002: V2 key includes mutable fields (producer_node_id). "
            "Renaming a node changes the identity key, violating I-03."
        ),
        strict=True,
    )
    def test_v2_key_changes_when_node_renamed(self):
        """T-002: producer_node_id should NOT determine persistent identity.

        V3 target: stable_feature_id is the identity anchor; producer_node_id
        is provenance only. Renaming a node should NOT change the persistent key.
        """
        # Create two IDs identical except for producer_node_id (simulating node rename)
        pid_a = make_persistent_id_v2(
            document_id="doc-1",
            component_id="disk",
            producer_node_id="n1_original",
            entity_type="face",
            semantic_role="cap/start",
        )
        pid_b = make_persistent_id_v2(
            document_id="doc-1",
            component_id="disk",
            producer_node_id="n1_renamed",  # node ID changed
            entity_type="face",
            semantic_role="cap/start",
        )
        # V3 target: keys should be equal (node ID is provenance, not identity)
        assert pid_a == pid_b, (
            f"V2 keys differ when only producer_node_id changes:\n"
            f"  original: {pid_a}\n"
            f"  renamed:  {pid_b}\n"
            f"  This means node renames break all persistent topology references."
        )

    @pytest.mark.xfail(
        reason=(
            "T-003/T-004: active entity without locator returns exact. "
            "See TopologyRegistry.resolve() L312-418."
        ),
        strict=True,
    )
    def test_active_unbound_entity_never_resolves_exact(self):
        """T-003/T-004: active + no locator → must NOT be exact.

        V3 target: exact requires ALL of: bound state, locator valid,
        owner body present, content hash match, type match.
        """
        reg = TopologyRegistry()
        rec = TopologyEntityRecord(
            persistent_id="gct2_test_key",
            entity_type="face",
            component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1",
            semantic_role="cap/start",
            status="active",
            resolution_method="primitive_semantic",
            # NO current_locator ← key point
        )
        reg.register_entity(rec)

        result = reg.resolve("gct2_test_key")
        # V3 target: unresolved (no binding evidence)
        assert result.status != "exact", (
            f"T-003/T-004 FAIL: active entity without locator "
            f"incorrectly resolved as exact (status={result.status}). "
            f"V3 requires: bound + locator valid + owner present → exact."
        )

    @pytest.mark.xfail(
        reason=(
            "I-01: semantic_role validator rejects bare numbers and 'face'/'edge', "
            "but does NOT reject runtime index tokens like 'side_face_3'. "
            "See PersistentTopoId._no_runtime_index validator."
        ),
        strict=True,
    )
    def test_runtime_index_token_rejected_in_semantic_role(self):
        """I-01: Runtime index tokens like 'side_face_3' must be rejected.

        V3 target: semantic_role grammar must not contain runtime indices.
        Tokens like 'side_face_3', 'lateral_2', 'top_face_0' should fail validation.
        """
        # These should all be valid (no runtime index)
        valid_roles = ["cap/start", "revolved.from/edge_left", "hole_wall", "body"]
        for role in valid_roles:
            PersistentTopoId(
                document_id="d1", component_id="c1",
                lineage_root_node_id="r1", producer_node_id="p1",
                entity_type="face", semantic_role=role,
            )

        # These should be rejected (contain runtime index patterns)
        invalid_roles = [
            "side_face_3",
            "lateral_2",
            "face_0",
            "edge_12",
            "top_face_7",
        ]
        for role in invalid_roles:
            with pytest.raises(ValueError, match=f"runtime.*index|ordinal|semantic_role"):
                PersistentTopoId(
                    document_id="d1", component_id="c1",
                    lineage_root_node_id="r1", producer_node_id="p1",
                    entity_type="face", semantic_role=role,
                )
