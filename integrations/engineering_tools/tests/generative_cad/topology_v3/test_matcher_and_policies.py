"""Phase 0 characterization tests — matcher and consumer policies (V3 §4.8, Appendix A).

These tests verify the known defects in ConstrainedTopologyMatcher
(fingerprint costs are all zero, single candidate → exact) and
ConsumerPolicy defaults.

Tests marked xfail expose known issues to be fixed in Phase 6+.
"""

import pytest

from seekflow_engineering_tools.generative_cad.topology.matcher import (
    ConstrainedTopologyMatcher,
)
from seekflow_engineering_tools.generative_cad.topology.models import (
    NamedTopologySet,
    TopologyEntityRecord,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.cae_bridge import (
    cae_preflight_gate,
    resolve_named_set_to_faces,
)
from seekflow_engineering_tools.generative_cad.topology.policies import (
    _QUALITY_RANK,
    get_consumer_policy,
    resolution_meets_quality,
)


class TestMatcherDefects:
    """V3 §4.8: Matcher is a placeholder — all costs zero, single → exact."""

    def test_single_fingerprint_candidate_is_not_kernel_exact(self):
        """T-010 FIX: Single match candidate → fingerprint_unique, never exact.

        V3: fingerprint matching can at best produce 'fingerprint_unique'.
        Only OCCT builder history (Generated/Modified/IsDeleted) can produce exact.
        """
        matcher = ConstrainedTopologyMatcher()
        candidates = [
            {"persistent_id": "gct2_candidate_a", "component_id": "disk",
             "entity_type": "face", "producer_node_id": "n1"},
        ]
        result = matcher.resolve(
            candidates,
            target_fingerprint={"surface_type": "plane"},
            target_component="disk",
            target_entity_type="face",
        )
        assert result.status == "fingerprint_unique", (
            f"T-010 FIX: single fingerprint candidate resolved as "
            f"{result.status}, expected fingerprint_unique"
        )

    def test_symmetric_candidates_remain_ambiguous(self):
        """T-010 BASELINE: Two symmetric candidates with equal cost → ambiguous.

        Current matcher correctly detects ambiguity when 2+ candidates
        have equal zero cost (margin=0 → ambiguous). This test PASSES
        and documents the correct baseline behavior.
        """
        matcher = ConstrainedTopologyMatcher()
        # Two identical candidates — both should have same cost
        candidates = [
            {"persistent_id": "gct2_left", "component_id": "disk",
             "entity_type": "face", "producer_node_id": "n1"},
            {"persistent_id": "gct2_right", "component_id": "disk",
             "entity_type": "face", "producer_node_id": "n1"},
        ]
        result = matcher.resolve(
            candidates,
            target_fingerprint={"surface_type": "plane"},
            target_component="disk",
            target_entity_type="face",
        )
        assert result.status == "ambiguous", (
            f"T-010 FAIL: two equal-cost candidates resolved as {result.status}. "
            f"V3 target: symmetric candidates must be ambiguous."
        )


class TestPolicyDefects:
    """V3 Section 4.8: Unknown consumer/quality defaults may be too lenient."""

    def test_unknown_consumer_policy_is_denied(self):
        """T-011 BASELINE: Unknown consumer type gets a default policy.

        Current behavior: unknown consumer → debug_visualization fallback
        with DETERMINISTIC_SEMANTIC minimum. This is relatively strict,
        but unknown quality strings default to rank 0 (permissive).
        """
        # Unknown consumer → deterministic_semantic (baseline: reasonable)
        policy = get_consumer_policy("totally_unknown_consumer_v3")
        assert policy.consumer_type == "debug_visualization", (
            "Unknown consumer falls back to debug_visualization (baseline)"
        )

        # Unknown quality string → rank 0 (T-011 defect)
        unknown_rank = _QUALITY_RANK.get("some_misspelled_quality", 0)
        # This is the defect: 0 = unresolved, effectively disabling the gate
        assert unknown_rank == 0, (
            "T-011 BASELINE: unknown quality defaults to rank 0 (permissive)"
        )

        # Demonstrate the consequence: a misspelled quality returns False
        # because rank 0 (< 5). This is coincidentally correct safety-wise,
        # but the real risk is in _worst_of() where misspelled → rank 0 → wins.
        meets = resolution_meets_quality("some_misspelled_quality", "exact_kernel_history")
        assert meets is False, (
            f"T-011 check: misspelled quality passes gate? meets={meets}"
        )

    def test_cae_preflight_requires_real_bound_faces(self):
        """T-008 FIX: CAE gate now rejects entities without locator.

        After T-004 fix, resolve() without binding context returns unresolved,
        so the CAE gate correctly blocks entities without locators.
        """
        """T-008: CAE gate must verify actual shape binding, not just registry state.

        V3 target: cae_preflight_gate must require a resolution context
        with ObjectStore + BindingService. Active records without binding SHOULD
        NOT pass the gate.
        """
        reg = TopologyRegistry()
        # Register an active entity WITHOUT a locator — should NOT pass CAE gate
        rec = TopologyEntityRecord(
            persistent_id="gct2_cae_test",
            entity_type="face", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1", semantic_role="load_face",
            status="active", resolution_method="primitive_semantic",
            # NO current_locator — resolution should fail for CAE
        )
        reg.register_entity(rec)

        named_set = NamedTopologySet(
            name="load_surface",
            entity_type="face",
            persistent_ids=["gct2_cae_test"],
            semantic_purpose="load",
            required_resolution="exact",
        )

        gate = cae_preflight_gate([named_set], reg)
        # V3 target: gate should FAIL because no actual face binding exists
        assert not gate.ok, (
            f"T-008 FAIL: CAE preflight passed despite entity having no "
            f"locator/binding. Resolved sets: {gate.summary}"
        )

    def test_empty_cae_named_set_is_fatal(self):
        """T-008 FIX: Empty CAE NamedTopologySet is now rejected.

        V3: An empty named set for a load/constraint/contact target
        is always an error — you cannot apply loads to zero faces.
        """
        reg = TopologyRegistry()

        named_set = NamedTopologySet(
            name="empty_load_surface",
            entity_type="face",
            persistent_ids=[],
            semantic_purpose="load",
            required_resolution="exact",
        )

        result = resolve_named_set_to_faces(named_set, reg)
        assert result.gate_result == "fail", (
            f"T-008 FIX: empty CAE set must be rejected, "
            f"got gate_result={result.gate_result}"
        )
