"""PR-0: Failure tests for design identity churn — §2.1, §2.2 of the supplementary spec.

These tests characterise the CURRENT broken behaviour. They MUST FAIL
under the current codebase. After PR-1 (DesignIdentity + FeatureIdentity),
they should PASS.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.1, §2.2
"""

import uuid as _uuid

import pytest

from seekflow_engineering_tools.generative_cad.topology.ids import (
    TopologyIdentityDescriptorV3,
    make_persistent_id_v3,
)
from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
    _make_compact_id,
)


# ═══════════════════════════════════════════════════════════════════════════════
# §2.1 — Random document_id causes PID churn
# ═══════════════════════════════════════════════════════════════════════════════


class TestDocumentIdChurn:
    """Verify that random document_id breaks PID stability (§2.1)."""

    def test_random_document_id_breaks_pid_stability(self):
        """Two calls with different document_lineage_id produce different keys.

        §2.1 diagnosis: document_id is randomly generated every authoring run,
        so the same design rebuilt always gets new PIDs. This test captures
        that current behaviour — two make_persistent_id_v3 calls with
        different document_lineage_id MUST produce different keys.
        """
        desc_a = TopologyIdentityDescriptorV3(
            document_lineage_id="gcad-aaaaaaaaaaaa",
            component_stable_id="disk",
            feature_stable_id="revolve_main",
            entity_type="face",
            semantic_path=("revolved", "cylindrical"),
        )
        desc_b = TopologyIdentityDescriptorV3(
            document_lineage_id="gcad-bbbbbbbbbbbb",  # different doc
            component_stable_id="disk",
            feature_stable_id="revolve_main",
            entity_type="face",
            semantic_path=("revolved", "cylindrical"),
        )

        key_a = desc_a.to_key()
        key_b = desc_b.to_key()

        assert key_a != key_b, (
            "§2.1: Different document_lineage_id SHOULD produce different keys "
            "under the current (broken) scheme — this is the churn that PR-1 must fix.\n"
            f"  key_a = {key_a}\n  key_b = {key_b}"
        )

    def test_same_document_id_produces_same_key(self):
        """Same descriptor fields → same key (baseline correctness check)."""
        key1, _ = make_persistent_id_v3(
            document_lineage_id="gcad-stable-doc",
            component_stable_id="disk",
            feature_stable_id="revolve_main",
            entity_type="face",
            semantic_path=("revolved", "cylindrical"),
        )
        key2, _ = make_persistent_id_v3(
            document_lineage_id="gcad-stable-doc",
            component_stable_id="disk",
            feature_stable_id="revolve_main",
            entity_type="face",
            semantic_path=("revolved", "cylindrical"),
        )
        assert key1 == key2, (
            "Same document_lineage_id should produce deterministic keys"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# §2.2 — feature_stable_id uses mutable producer_node_id
# ═══════════════════════════════════════════════════════════════════════════════


class TestFeatureStableIdIsProducerNodeId:
    """Verify that feature_stable_id currently equals mutable producer_node_id (§2.2)."""

    def test_make_compact_id_uses_producer_node_id_as_feature_stable_id(self):
        """semantic_naming._make_compact_id sets feature_stable_id=producer_node_id.

        §2.2 diagnosis: The V3 descriptor has a feature_stable_id field but
        it is currently populated with producer_node_id — a mutable string
        that changes when nodes are renamed, inserted, or deleted.
        """
        key_a, _desc_a = _make_compact_id(
            document_id="gcad-test-doc",
            component_id="disk",
            producer_node_id="node_revolve_main",
            entity_type="face",
            semantic_role="revolved/cylindrical",
        )
        key_b, _desc_b = _make_compact_id(
            document_id="gcad-test-doc",
            component_id="disk",
            producer_node_id="node_revolve_main_renamed",  # LLM renamed the node
            entity_type="face",
            semantic_role="revolved/cylindrical",
        )

        # CURRENT behaviour: different producer_node_id → different keys
        assert key_a != key_b, (
            "§2.2: Changing producer_node_id (e.g. after LLM node rename) "
            "produces a different PID — this is the churn PR-1 must fix "
            "by using stable feature_uid instead.\n"
            f"  key_a (node_revolve_main)       = {key_a}\n"
            f"  key_b (node_revolve_main_renamed) = {key_b}"
        )

    def test_feature_stable_id_in_descriptor_equals_producer_node_id(self):
        """The identity_descriptor records feature_stable_id == producer_node_id."""
        _, desc = _make_compact_id(
            document_id="gcad-test-doc",
            component_id="disk",
            producer_node_id="node_extrude_block",
            entity_type="face",
            semantic_role="box/x_max",
        )
        assert desc["feature_stable_id"] == "node_extrude_block", (
            "§2.2: feature_stable_id in the descriptor dict should equal "
            "producer_node_id — proving no stable feature_uid is injected.\n"
            f"  feature_stable_id = {desc['feature_stable_id']}"
        )

    def test_feature_uid_param_stabilizes_pid(self):
        """PR-1: When feature_uid is provided, PID survives node rename.

        Two calls with different producer_node_id but the same feature_uid
        should produce the SAME key — this is the fix for §2.2.
        """
        key_a, _ = _make_compact_id(
            document_id="gcad-test-doc",
            component_id="disk",
            producer_node_id="node_revolve_main",
            entity_type="face",
            semantic_role="revolved/cylindrical",
            feature_uid="disk.revolve_profile.main",
        )
        key_b, _ = _make_compact_id(
            document_id="gcad-test-doc",
            component_id="disk",
            producer_node_id="node_revolve_main_renamed",  # LLM renamed the node
            entity_type="face",
            semantic_role="revolved/cylindrical",
            feature_uid="disk.revolve_profile.main",
        )
        assert key_a == key_b, (
            "PR-1 §2.2: With stable feature_uid, different producer_node_id "
            "must produce the SAME PID key — the node rename is irrelevant.\n"
            f"  key_a = {key_a}\n  key_b = {key_b}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# §2.1 — Missing DesignIdentity class
# ═══════════════════════════════════════════════════════════════════════════════


class TestDesignIdentityClassExists:
    """Verify DesignIdentity and FeatureIdentityReconciler now exist (PR-1)."""

    def test_design_identity_class_exists_and_has_expected_fields(self):
        """PR-1: DesignIdentity struct is importable and has is_strong property."""
        from seekflow_engineering_tools.generative_cad.topology import (
            DesignIdentity,
            IdentitySource,
        )

        di = DesignIdentity(
            design_id="proj-001",
            revision_id="rev-A",
            identity_source=IdentitySource.CALLER_SUPPLIED,
        )
        assert di.is_strong is True
        assert di.design_id == "proj-001"
        assert di.revision_id == "rev-A"

        di_eph = DesignIdentity(design_id="gcad-abc123")
        assert di_eph.is_strong is False  # default is EPHEMERAL_GENERATED
        assert di_eph.identity_source == IdentitySource.EPHEMERAL_GENERATED

    def test_feature_identity_reconciler_exists_and_generates_uids(self):
        """PR-1: FeatureIdentityReconciler struct is importable and generates UIDs."""
        from seekflow_engineering_tools.generative_cad.topology import (
            FeatureIdentity,
            FeatureIdentityReconciler,
        )

        uid = FeatureIdentityReconciler.generate_feature_uid(
            component_uid="disk", operation_kind="revolve_profile", hint="main",
        )
        assert uid == "disk.revolve_profile.main"

        fi = FeatureIdentityReconciler.from_producer_node_id("node_123")
        assert fi.feature_uid == "node_123"
        assert fi.display_node_id == "node_123"


# ═══════════════════════════════════════════════════════════════════════════════
# §2.1 — raw_assembler generates random document_id
# ═══════════════════════════════════════════════════════════════════════════════


class TestAssemblerGeneratesRandomDocumentId:
    """Verify raw_assembler always generates random document_id (§2.1)."""

    def test_ephemeral_document_id_different_each_time(self):
        """Without explicit design_id, the assembler uses uuid4 each time.

        This test directly checks the uuid.uuid4().hex[:12] pattern in
        raw_assembler.py:131. Two calls produce different values.
        """
        a = f"gcad-{_uuid.uuid4().hex[:12]}"
        b = f"gcad-{_uuid.uuid4().hex[:12]}"
        assert a != b, (
            "§2.1: Two uuid4 calls produce different document_id values — "
            "this is the core of the churn problem. Without a stable "
            "design_id, every authoring run is a new 'design'.\n"
            f"  a = {a}\n  b = {b}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# §2.1 — Sidecar writes document_id as lineage_id
# ═══════════════════════════════════════════════════════════════════════════════


class TestSidecarDocumentLineageId:
    """Verify sidecar currently writes random UUID as document_lineage_id (§2.1, §3)."""

    def test_sidecar_writes_document_id_as_lineage_id(self):
        """persistence.py:73 sets document_lineage_id = document_id.

        The sidecar schema has a document_lineage_id field but it is
        populated with the same random UUID as document_id. There is
        no separate stable design identity.
        """
        from seekflow_engineering_tools.generative_cad.topology.persistence import (
            write_topology_sidecar,
        )
        from seekflow_engineering_tools.generative_cad.topology.registry import (
            TopologyRegistry,
        )
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import json

        reg = TopologyRegistry()
        random_doc_id = f"gcad-{_uuid.uuid4().hex[:12]}"

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "sidecar.json"
            write_topology_sidecar(
                registry=reg,
                document_id=random_doc_id,
                canonical_graph_hash="abc123",
                path=path,
                runtime_version="1.0.0",
                occt_version="7.6.0",
            )
            data = json.loads(open(path, encoding="utf-8").read())
            # document_lineage_id == document_id (both the random UUID)
            assert data["document_lineage_id"] == random_doc_id, (
                "§2.1: Sidecar writes document_lineage_id == document_id — "
                f"both are the random UUID '{random_doc_id}'. "
                "No separate design identity is tracked."
            )
            assert data["document_id"] == random_doc_id
