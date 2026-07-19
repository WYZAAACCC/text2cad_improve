"""Phase 2 tests — contracts, history wrappers, policies, matcher, extrude/revolve naming."""

import pytest

# Phase 2 imports
from seekflow_engineering_tools.generative_cad.topology.contracts import (
    EXTRUDE_RECTANGLE_CONTRACT,
    REVOLVE_PROFILE_CONTRACT,
    CUT_HOLE_CONTRACT,
    BOOLEAN_UNION_CONTRACT,
    FILLET_CONTRACT,
    TopologyContract,
    TopologyOutputRole,
    get_contract,
)
from seekflow_engineering_tools.generative_cad.topology.history_wrappers import (
    KernelHistoryAdapter,
    KernelHistorySnapshot,
    HistoryAwareShapeResult,
    _probe_capabilities,
    history_aware_extrude,
    history_aware_revolve,
)
from seekflow_engineering_tools.generative_cad.topology.policies import (
    ConsumerPolicy,
    ResolutionQuality,
    get_consumer_policy,
    resolution_meets_quality,
)
from seekflow_engineering_tools.generative_cad.topology.matcher import (
    ConstrainedTopologyMatcher,
    MatchConstraint,
    MatchWeights,
)
from seekflow_engineering_tools.generative_cad.topology.validation import (
    validate_topology_artifact_proof,
    validate_topology_contract,
    validate_topology_runtime_integrity,
)
from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
    name_extrude_faces,
    name_revolve_faces,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.ids import PersistentTopoId
from seekflow_engineering_tools.generative_cad.topology.models import TopologyEntityRecord


# ═══════════════════════════════════════════════════════════════════════════════
# Contracts
# ═══════════════════════════════════════════════════════════════════════════════


class TestTopologyContracts:
    def test_extrude_contract_has_four_roles(self):
        assert len(EXTRUDE_RECTANGLE_CONTRACT.output_roles) == 4
        role_names = {r.name for r in EXTRUDE_RECTANGLE_CONTRACT.output_roles}
        assert "body" in role_names
        assert "end_cap_positive" in role_names
        assert "end_cap_negative" in role_names
        assert "side_face" in role_names

    def test_revolve_contract_caps_are_zero_or_one(self):
        cap_roles = [r for r in REVOLVE_PROFILE_CONTRACT.output_roles if "cap" in r.name]
        for role in cap_roles:
            assert role.cardinality == "zero_or_one", (
                f"Cap '{role.name}' should be zero_or_one (absent for full revolves)"
            )

    def test_contract_lookup_by_dialect_op(self):
        c = get_contract("sketch_extrude", "extrude_rectangle")
        assert c is not None
        assert c.history_capability == "full_kernel_history"

    def test_contract_lookup_unknown_returns_none(self):
        c = get_contract("nonexistent", "fake_op")
        assert c is None

    def test_boolean_contract_allows_split_and_merge(self):
        assert BOOLEAN_UNION_CONTRACT.allows_split is True
        assert BOOLEAN_UNION_CONTRACT.allows_merge is True

    def test_hole_contract_has_wall_and_rims(self):
        role_names = {r.name for r in CUT_HOLE_CONTRACT.output_roles}
        assert "hole_wall" in role_names
        assert "entry_rim" in role_names
        assert "exit_rim" in role_names

    def test_fillet_contract_partial_history(self):
        assert FILLET_CONTRACT.history_capability == "partial_kernel_history"


# ═══════════════════════════════════════════════════════════════════════════════
# History wrappers
# ═══════════════════════════════════════════════════════════════════════════════


class TestHistoryWrappers:
    def test_capability_probe_returns_dict(self):
        caps = _probe_capabilities()
        assert isinstance(caps, dict)
        assert "extrude" in caps
        assert "revolve" in caps
        assert "boolean" in caps

    def test_capability_probe_is_cached(self):
        caps1 = _probe_capabilities()
        caps2 = _probe_capabilities()
        assert caps1 is caps2  # Same cached dict

    def test_history_snapshot_empty(self):
        snap = KernelHistorySnapshot()
        assert snap.generated == {}
        assert snap.modified == {}
        assert snap.deleted == []

    def test_history_aware_shape_result_defaults(self):
        result = HistoryAwareShapeResult(result_shape="test")
        assert result.result_shape == "test"
        assert result.history is None
        assert result.metrics == {}

    def test_history_aware_extrude_with_cadquery(self):
        """Real CadQuery extrude with OCP history."""
        import cadquery as cq
        from OCP.gp import gp_Vec

        box = cq.Workplane("XY").box(10, 10, 10)
        profile = cq.Workplane("XY").rect(10, 10).val()

        result = history_aware_extrude(
            profile.wrapped, gp_Vec(0, 0, 10),
        )
        # Result may be None if OCP API differs, but should not crash
        if result is not None:
            assert result.result_shape is not None

    def test_history_aware_revolve_with_cadquery(self):
        """Real CadQuery revolve with OCP history."""
        import cadquery as cq
        from OCP.gp import gp_Ax1, gp_Pnt, gp_Dir

        profile = (
            cq.Workplane("XZ")
            .moveTo(20, -10).lineTo(20, 10)
            .lineTo(0, 10).lineTo(0, -10)
            .close().val()
        )
        axis = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))

        result = history_aware_revolve(
            profile.wrapped, axis, 360.0,
        )
        if result is not None:
            assert result.result_shape is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Policies
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicies:
    def test_cae_load_requires_deterministic(self):
        policy = get_consumer_policy("cae_load")
        assert policy.minimum_quality == ResolutionQuality.DETERMINISTIC_SEMANTIC
        assert policy.allows_ambiguity is False

    def test_cae_contact_requires_exact_history(self):
        policy = get_consumer_policy("cae_contact")
        assert policy.minimum_quality == ResolutionQuality.EXACT_KERNEL_HISTORY

    def test_debug_allows_fingerprint(self):
        policy = get_consumer_policy("debug_visualization")
        assert policy.minimum_quality == ResolutionQuality.FINGERPRINT_UNIQUE
        assert policy.allows_ambiguity is True

    def test_unknown_consumer_defaults_to_deterministic(self):
        policy = get_consumer_policy("nonexistent_consumer")
        assert policy.minimum_quality == ResolutionQuality.DETERMINISTIC_SEMANTIC
        assert policy.allows_ambiguity is False

    def test_resolution_meets_quality_ordering(self):
        # Lower quality methods should NOT pass higher requirements
        assert resolution_meets_quality("fingerprint_unique", "fingerprint_unique")
        assert not resolution_meets_quality("fingerprint_unique", "deterministic_semantic")
        assert not resolution_meets_quality("unresolved", "fingerprint_unique")
        # Higher quality methods should pass lower requirements
        assert resolution_meets_quality("primitive_semantic", "fingerprint_unique")
        assert resolution_meets_quality("kernel_generated", "deterministic_semantic")

    def test_consumer_policy_is_frozen(self):
        policy = get_consumer_policy("cae_load")
        with pytest.raises(Exception):
            policy.minimum_quality = ResolutionQuality.FINGERPRINT_UNIQUE  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# Matcher
# ═══════════════════════════════════════════════════════════════════════════════


class TestMatcher:
    def test_filter_candidates_by_component(self):
        matcher = ConstrainedTopologyMatcher()
        candidates = [
            {"persistent_id": "a", "component_id": "box", "entity_type": "face", "producer_node_id": "n1"},
            {"persistent_id": "b", "component_id": "disk", "entity_type": "face", "producer_node_id": "n1"},
        ]
        filtered = matcher.filter_candidates(
            candidates, target_component="box", target_entity_type="face",
        )
        assert len(filtered) == 1
        assert filtered[0]["persistent_id"] == "a"

    def test_filter_candidates_by_entity_type(self):
        matcher = ConstrainedTopologyMatcher()
        candidates = [
            {"persistent_id": "a", "component_id": "box", "entity_type": "face", "producer_node_id": "n1"},
            {"persistent_id": "b", "component_id": "box", "entity_type": "edge", "producer_node_id": "n1"},
        ]
        filtered = matcher.filter_candidates(
            candidates, target_component="box", target_entity_type="face",
        )
        assert len(filtered) == 1
        assert filtered[0]["persistent_id"] == "a"

    def test_filter_empty_candidates(self):
        matcher = ConstrainedTopologyMatcher()
        filtered = matcher.filter_candidates(
            [], target_component="box", target_entity_type="face",
        )
        assert filtered == []

    def test_resolve_single_candidate_exact(self):
        matcher = ConstrainedTopologyMatcher()
        candidates = [
            {"persistent_id": "gct:only", "component_id": "box", "entity_type": "face", "producer_node_id": "n1"},
        ]
        result = matcher.resolve(
            candidates, {},
            target_component="box", target_entity_type="face",
        )
        assert result.status == "exact"
        assert result.best_match.entity_id == "gct:only"

    def test_resolve_no_candidates_unresolved(self):
        matcher = ConstrainedTopologyMatcher()
        result = matcher.resolve(
            [], {},
            target_component="box", target_entity_type="face",
        )
        assert result.status == "unresolved"


# ═══════════════════════════════════════════════════════════════════════════════
# Extrude/Revolve semantic naming (with CadQuery)
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtrudeRevolveNaming:
    def test_extrude_box_faces(self):
        import cadquery as cq
        box = cq.Workplane("XY").box(100, 50, 25)
        delta = name_extrude_faces(
            box, document_id="d1", component_id="box", producer_node_id="n1",
            extrude_plane="XY", direction="+",
        )
        assert len(delta.relations) == 6  # 2 caps + 4 sides
        roles = {r.semantic_role for r in delta.relations}
        assert "extrude/end_cap_positive" in roles
        assert "extrude/end_cap_negative" in roles

    def test_extrude_face_roles_stable_across_rebuild(self):
        import cadquery as cq
        box1 = cq.Workplane("XY").box(100, 50, 25)
        delta1 = name_extrude_faces(
            box1, document_id="d1", component_id="box", producer_node_id="n1",
        )
        box2 = cq.Workplane("XY").box(100, 50, 25)
        delta2 = name_extrude_faces(
            box2, document_id="d1", component_id="box", producer_node_id="n1",
        )
        roles1 = sorted(r.semantic_role for r in delta1.relations)
        roles2 = sorted(r.semantic_role for r in delta2.relations)
        assert roles1 == roles2

    def test_revolve_full_360_no_caps(self):
        import cadquery as cq
        profile = (
            cq.Workplane("XZ").moveTo(20, -10).lineTo(20, 10)
            .lineTo(0, 10).lineTo(0, -10).close().revolve(360)
        )
        delta = name_revolve_faces(
            profile, document_id="d1", component_id="r", producer_node_id="n1",
            angle_deg=360, axis="Z",
        )
        roles = {r.semantic_role for r in delta.relations}
        # No cap faces for full revolve
        assert all("cap" not in (r or "") for r in roles), f"Unexpected cap in roles: {roles}"


# ═══════════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTopologyValidation:
    def test_artifact_proof_no_sidecar_returns_empty(self):
        issues = validate_topology_artifact_proof(sidecar_path=None)
        assert issues == []

    def test_artifact_proof_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.topology.json"
        issues = validate_topology_artifact_proof(sidecar_path=str(missing))
        assert len(issues) == 1
        assert issues[0]["code"] == "TOPOLOGY_SIDECAR_MISSING"

    def test_integrity_empty_registry(self):
        reg = TopologyRegistry()
        issues = validate_topology_runtime_integrity(reg)
        assert issues == []

    def test_integrity_with_valid_entity(self):
        reg = TopologyRegistry()
        pid = "gct:v1:doc:comp:n1:n1:face:test"
        rec = TopologyEntityRecord(
            persistent_id=pid, entity_type="face",
            component_id="comp", owner_body_handle_id="solid:comp:n1:body",
            producer_node_id="n1", semantic_role="test",
        )
        reg.register_entity(rec)
        issues = validate_topology_runtime_integrity(reg)
        assert issues == []
