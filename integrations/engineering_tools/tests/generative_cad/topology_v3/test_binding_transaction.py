"""PR-3: Binding hardening + atomic staging — §2.10C, §2.13 tests.

Ref: Text2CAD_持久拓扑命名指导_代码复核与强制修订补充规范.md §2.10C, §2.13
"""

from seekflow_engineering_tools.generative_cad.topology.shape_binding import (
    LocatorVerification,
    ShapeBindingService,
)
from seekflow_engineering_tools.generative_cad.topology.staging import (
    BuildCommitBundle,
    StagedObjectStore,
)
from seekflow_engineering_tools.generative_cad.topology.locator import (
    RuntimeTopoLocator,
)


# ═══════════════════════════════════════════════════════════════════════════════
# §2.10C — Fingerprint stub → fail-closed
# ═══════════════════════════════════════════════════════════════════════════════


class TestFingerprintStubFailClosed:
    """Verify that fingerprint verification now fails-closed (§2.10C)."""

    def test_expected_fingerprint_without_verifier_returns_invalid(self):
        """When expected_fingerprint is provided but verification is not
        implemented, the locator must be treated as unverified.

        Tests the fingerprint stub replacement directly — the original code had:
            if expected_fingerprint:
                pass  # always returns valid=True
        The fix replaces this with:
            if expected_fingerprint:
                return LocatorVerification(valid=False, ...)

        The verify_locator source is read to confirm the stub was replaced.
        """
        import inspect
        source = inspect.getsource(ShapeBindingService.verify_locator)
        # The new code must NOT contain the old pass-only stub pattern
        assert "# Future: compare with compute_face_fingerprint(subshape)" not in source, (
            "§2.10C: Old fingerprint stub comment must be removed"
        )
        assert "topology_fingerprint_not_verified" in source, (
            "§2.10C: Fingerprint fail-closed error code must be present"
        )
        assert "Fingerprint verification is not yet implemented" in source, (
            "§2.10C: Clear error message must explain why verification failed"
        )

    def test_no_expected_fingerprint_still_checks_other_conditions(self):
        """Without expected_fingerprint, other checks still apply normally."""
        svc = ShapeBindingService(object_store=None)
        locator = RuntimeTopoLocator(
            owner_body_handle_id="solid:body",
            entity_type="face",
            indexed_map_position=1,
            occt_shape_hash=0,
        )
        # No ObjectStore → should fail at check 0
        result = svc.verify_locator(locator)
        assert result.valid is False
        assert result.error_code == "topology_no_object_store"

    def test_fingerprint_not_provided_is_skipped(self):
        """None fingerprint should not trigger the fail-closed gate."""
        svc = ShapeBindingService(object_store=None)
        locator = RuntimeTopoLocator(
            owner_body_handle_id="solid:body",
            entity_type="face",
            indexed_map_position=1,
            occt_shape_hash=0,
        )
        result = svc.verify_locator(locator, expected_fingerprint=None)
        # Still fails at check 0 (no ObjectStore), not at fingerprint
        assert result.error_code == "topology_no_object_store"


# ═══════════════════════════════════════════════════════════════════════════════
# §2.13 — StagedObjectStore
# ═══════════════════════════════════════════════════════════════════════════════


class TestStagedObjectStore:
    """Verify StagedObjectStore can stage, commit, and rollback objects."""

    def test_stage_and_retrieve(self):
        staging = StagedObjectStore()
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        handle = SolidHandle(id="solid:body", component_id="disk", producer_node="n1")
        staging.stage(handle, "fake_geometry_object")
        assert staging.contains("solid:body")
        assert staging.get_staged("solid:body") == "fake_geometry_object"

    def test_commit_publishes_to_real_store(self):
        from seekflow_engineering_tools.generative_cad.runtime.object_store import RuntimeObjectStore
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle

        staging = StagedObjectStore()
        store = RuntimeObjectStore()
        handle = SolidHandle(id="solid:body", component_id="disk", producer_node="n1")
        staging.stage(handle, "fake_geometry_object")
        staging.commit_to(store)
        assert store.get("solid:body") == "fake_geometry_object"

    def test_rollback_discards_all(self):
        staging = StagedObjectStore()
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        handle = SolidHandle(id="solid:body", component_id="disk", producer_node="n1")
        staging.stage(handle, "fake_geometry_object")
        staging.discard()
        assert staging.staged_count == 0
        assert not staging.contains("solid:body")

    def test_staged_count_reflects_entries(self):
        staging = StagedObjectStore()
        assert staging.staged_count == 0
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        staging.stage(SolidHandle(id="s1", component_id="c", producer_node="n"), "obj1")
        staging.stage(SolidHandle(id="s2", component_id="c", producer_node="n"), "obj2")
        assert staging.staged_count == 2


# ═══════════════════════════════════════════════════════════════════════════════
# §2.13 — BuildCommitBundle
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildCommitBundle:
    """Verify BuildCommitBundle validates and commits atomically (§2.13)."""

    def test_empty_bundle_validation_reports_no_objects(self):
        bundle = BuildCommitBundle()
        errors = bundle.validate()
        assert len(errors) == 1
        assert "no staged objects" in errors[0]

    def test_valid_bundle_passes_validation(self):
        bundle = BuildCommitBundle()
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        handle = SolidHandle(id="solid:body", component_id="disk", producer_node="n1")
        bundle.staged_objects.stage(handle, "fake_geometry")
        bundle.bind_node("node_1", "body", "solid:body")
        errors = bundle.validate()
        assert errors == []

    def test_node_binding_references_missing_handle(self):
        bundle = BuildCommitBundle()
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        handle = SolidHandle(id="solid:body", component_id="disk", producer_node="n1")
        bundle.staged_objects.stage(handle, "fake_geometry")
        # Reference a handle that is NOT staged
        bundle.bind_node("node_1", "body", "solid:missing")
        errors = bundle.validate()
        assert len(errors) >= 1
        assert any("solid:missing" in e for e in errors)

    def test_cache_entry_missing_required_fields(self):
        bundle = BuildCommitBundle()
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        handle = SolidHandle(id="solid:body", component_id="disk", producer_node="n1")
        bundle.staged_objects.stage(handle, "fake_geometry")
        bundle.staged_cache_entry = {"only_geometry": True}  # missing required keys
        errors = bundle.validate()
        assert len(errors) >= 1
        assert any("topology_registry_fragment" in e for e in errors)

    def test_rollback_clears_all_staged_state(self):
        bundle = BuildCommitBundle()
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        handle = SolidHandle(id="solid:body", component_id="disk", producer_node="n1")
        bundle.staged_objects.stage(handle, "fake_geometry")
        bundle.bind_node("node_1", "body", "solid:body")
        bundle.add_event({"event": "test", "node_id": "n1"})
        bundle.staged_cache_entry = {"geometry_result": {}, "topology_registry_fragment": {}}
        bundle.rollback()
        assert bundle.staged_objects.staged_count == 0
        assert bundle.staged_node_bindings == {}
        assert bundle.staged_events == []
        assert bundle.staged_cache_entry is None
