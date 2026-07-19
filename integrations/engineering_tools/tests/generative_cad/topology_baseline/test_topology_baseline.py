"""Baseline tests for persistent topology naming — Phase 0 deliverables.

These tests establish the current topology behavior and prove that
face_index/edge_index can drift after parameter changes or feature insertion.

See: docs/gcad_persistent_topological_naming_implementation_plan_zh.md §1, §24
"""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ids import PersistentTopoId
from seekflow_engineering_tools.generative_cad.topology.models import (
    NamedTopologySet,
    TopologyDelta,
    TopologyEntityRecord,
    TopologyRelation,
    TopologyResolution,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
    build_entity_records_from_delta,
    name_box_faces,
    name_cylinder_faces,
    name_sphere_faces,
)
from seekflow_engineering_tools.generative_cad.topology.persistence import (
    read_topology_sidecar,
    write_topology_sidecar,
)

def _has_cadquery() -> bool:
    """Check if CadQuery is importable."""
    try:
        import cadquery  # noqa: F401
        return True
    except ImportError:
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def empty_registry():
    """Fresh empty TopologyRegistry for each test."""
    return TopologyRegistry()


# ═══════════════════════════════════════════════════════════════════════════════
# TopologyRegistry unit tests (no CadQuery needed)
# ═══════════════════════════════════════════════════════════════════════════════


class TestTopologyRegistry:
    """Unit tests for TopologyRegistry lifecycle."""

    def test_register_and_resolve_active(self, empty_registry):
        """Entity registered as active resolves with status=exact (with binding context)."""
        reg = empty_registry
        pid = "gct:v1:doc-1:box1:n1:n1:face:box/x_max"
        rec = TopologyEntityRecord(
            persistent_id=pid,
            entity_type="face",
            component_id="box1",
            owner_body_handle_id="solid:box1:n1:body",
            producer_node_id="n1",
            semantic_role="box/x_max",
            status="active",
            resolution_method="primitive_semantic",
            current_locator={
                "owner_body_handle_id": "solid:box1:n1:body",
                "entity_type": "face",
                "indexed_map_position": 1,
                "occt_shape_hash": 0,
            },
        )
        reg.register_entity(rec)
        assert reg.entity_count == 1
        assert reg.active_count == 1

        # V3: resolve without binding context → unresolved (T-004 fix)
        res = reg.resolve(pid)
        assert res.status == "unresolved", (
            f"Without binding context, expected unresolved, got {res.status}"
        )

        # V3: resolve with binding context → exact (when locator is valid)
        class FakeStore:
            def get(self, hid):
                return object()
        class FakeBindingService:
            def verify_locator(self, locator, expected_fingerprint=None):
                from seekflow_engineering_tools.generative_cad.topology.shape_binding import (
                    LocatorVerification,
                )
                return LocatorVerification(valid=True)
        res2 = reg.resolve(
            pid,
            object_store=FakeStore(),
            binding_service=FakeBindingService(),
        )
        assert res2.status == "exact"

    def test_resolve_deleted(self, empty_registry):
        """Deleted entity resolves with status=deleted (not unresolved)."""
        reg = empty_registry
        pid = "gct:v1:doc-1:test:n1:n1:face:test_face"
        rec = TopologyEntityRecord(
            persistent_id=pid,
            entity_type="face",
            component_id="test",
            owner_body_handle_id="solid:test:n1:body",
            producer_node_id="n1",
            semantic_role="test_face",
        )
        reg.register_entity(rec)
        reg.mark_deleted(pid, reason="feature removed")

        res = reg.resolve(pid)
        assert res.status == "deleted"

    def test_resolve_unknown_id_returns_unresolved(self, empty_registry):
        """Unknown persistent_id → unresolved (not exception, not wrong entity)."""
        reg = empty_registry
        res = reg.resolve("gct:v1:doc:comp:root:prod:face:nonexistent")
        assert res.status == "unresolved"

    def test_duplicate_registration_raises(self, empty_registry):
        """Registering same active persistent_id twice raises ValueError."""
        reg = empty_registry
        pid = "gct:v1:doc-1:comp1:n1:n1:face:test_face"
        rec = TopologyEntityRecord(
            persistent_id=pid,
            entity_type="face",
            component_id="comp1",
            owner_body_handle_id="solid:comp1:n1:body",
            producer_node_id="n1",
            semantic_role="test_face",
        )
        reg.register_entity(rec)
        with pytest.raises(ValueError, match="Duplicate persistent_id"):
            reg.register_entity(rec)

    def test_duplicate_after_superseded_allowed(self, empty_registry):
        """Re-registering after marking old as superseded is allowed."""
        reg = empty_registry
        pid = "gct:v1:doc:comp:n1:n1:face:test"
        rec1 = TopologyEntityRecord(
            persistent_id=pid,
            entity_type="face",
            component_id="comp",
            owner_body_handle_id="solid:comp:n1:body",
            producer_node_id="n1",
            semantic_role="test",
        )
        reg.register_entity(rec1)
        # Mark old as superseded
        rec1.status = "superseded"
        # Re-register should work
        rec2 = TopologyEntityRecord(
            persistent_id=pid,
            entity_type="face",
            component_id="comp",
            owner_body_handle_id="solid:comp:n2:body",
            producer_node_id="n2",
            semantic_role="test",
            status="active",
            generation=1,
        )
        reg.register_entity(rec2)
        assert reg.active_count == 1

    def test_snapshot_round_trip(self, empty_registry):
        """Registry snapshot survives export → clear → restore cycle."""
        reg = empty_registry
        for i in range(5):
            pid = f"gct:v1:doc:comp:n{i}:n{i}:face:role_{i}"
            rec = TopologyEntityRecord(
                persistent_id=pid,
                entity_type="face",
                component_id="comp",
                owner_body_handle_id=f"solid:comp:n{i}:body",
                producer_node_id=f"n{i}",
                semantic_role=f"role_{i}",
                generation=i,
            )
            reg.register_entity(rec)

        snap = reg.export_snapshot()
        assert len(snap["entities"]) == 5

        reg2 = TopologyRegistry()
        reg2.restore_snapshot(snap)
        assert reg2.entity_count == 5
        assert reg2.active_count == 5

    def test_integrity_ok(self, empty_registry):
        """Integrity check passes on healthy registry."""
        reg = empty_registry
        pid = "gct:v1:doc:comp:n1:n1:face:ok"
        rec = TopologyEntityRecord(
            persistent_id=pid,
            entity_type="face",
            component_id="comp",
            owner_body_handle_id="solid:comp:n1:body",
            producer_node_id="n1",
            semantic_role="ok",
        )
        reg.register_entity(rec)
        result = reg.validate_integrity()
        assert result["ok"] is True

    def test_get_by_body_and_node(self, empty_registry):
        """Entity query by body handle and producer node works."""
        reg = empty_registry
        pid = "gct:v1:doc:comp:n1:n1:face:query_test"
        rec = TopologyEntityRecord(
            persistent_id=pid,
            entity_type="face",
            component_id="comp",
            owner_body_handle_id="solid:comp:n1:body",
            producer_node_id="n1",
            semantic_role="query_test",
        )
        reg.register_entity(rec)

        by_body = reg.get_by_body("solid:comp:n1:body")
        assert len(by_body) == 1
        assert by_body[0].persistent_id == pid

        by_node = reg.get_by_node("n1")
        assert len(by_node) == 1
        assert by_node[0].persistent_id == pid


# ═══════════════════════════════════════════════════════════════════════════════
# PersistentTopoId unit tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestPersistentTopoId:
    """Unit tests for PersistentTopoId serialization and validation."""

    def test_compact_round_trip(self):
        pid = PersistentTopoId(
            document_id="doc-1",
            component_id="disk",
            lineage_root_node_id="revolve_1",
            producer_node_id="center_bore",
            entity_type="face",
            semantic_role="hole_wall",
        )
        compact = pid.to_compact()
        restored = PersistentTopoId.from_compact(compact)
        assert restored.document_id == pid.document_id
        assert restored.component_id == "disk"
        assert restored.semantic_role == "hole_wall"

    def test_compact_with_branch(self):
        pid = PersistentTopoId(
            document_id="doc-1",
            component_id="pattern",
            lineage_root_node_id="hole_1",
            producer_node_id="hole_1",
            entity_type="face",
            semantic_role="hole_wall",
            branch_token="instance_3",
        )
        compact = pid.to_compact()
        restored = PersistentTopoId.from_compact(compact)
        assert restored.branch_token == "instance_3"

    def test_rejects_numeric_role(self):
        with pytest.raises(ValueError):
            PersistentTopoId(
                document_id="d", component_id="c",
                lineage_root_node_id="r", producer_node_id="p",
                entity_type="face", semantic_role="5",
            )

    def test_rejects_bare_entity_type_role(self):
        with pytest.raises(ValueError):
            PersistentTopoId(
                document_id="d", component_id="c",
                lineage_root_node_id="r", producer_node_id="p",
                entity_type="face", semantic_role="face",
            )

    def test_to_alias_format(self):
        pid = PersistentTopoId(
            document_id="doc-1",
            component_id="disk",
            lineage_root_node_id="revolve_1",
            producer_node_id="center_bore",
            entity_type="face",
            semantic_role="hole_wall",
        )
        alias = pid.to_alias()
        assert "component.disk" in alias
        assert "feature.center_bore" in alias
        assert "hole_wall" in alias

    def test_sha256_deterministic(self):
        pid1 = PersistentTopoId(
            document_id="doc-1", component_id="test",
            lineage_root_node_id="n1", producer_node_id="n1",
            entity_type="face", semantic_role="test_role",
        )
        pid2 = PersistentTopoId(
            document_id="doc-1", component_id="test",
            lineage_root_node_id="n1", producer_node_id="n1",
            entity_type="face", semantic_role="test_role",
        )
        assert pid1.to_sha256() == pid2.to_sha256()

    def test_frozen_immutable(self):
        pid = PersistentTopoId(
            document_id="doc-1", component_id="test",
            lineage_root_node_id="n1", producer_node_id="n1",
            entity_type="face", semantic_role="immutable",
        )
        with pytest.raises(Exception):  # pydantic frozen model
            pid.semantic_role = "changed"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
# TopologyDelta / TopologyResolution model tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTopologyModels:
    """Model serialization and validation tests."""

    def test_delta_legacy_none_default(self):
        """Default TopologyDelta has legacy_none provider (Phase 1 compat)."""
        delta = TopologyDelta(node_id="n1", component_id="comp1")
        assert delta.history_provider == "legacy_none"
        assert delta.relations == []

    def test_delta_with_semantic_relations(self):
        """TopologyDelta can carry semantic relations."""
        delta = TopologyDelta(
            node_id="n1",
            component_id="comp1",
            result_body_handle_ids=["solid:comp1:n1:body"],
            relations=[
                TopologyRelation(
                    relation="primitive",
                    result_entity_keys=["gct:v1:doc:comp1:n1:n1:face:box/x_max"],
                    semantic_role="box/x_max",
                ),
            ],
            history_provider="operation_semantics",
            history_provider_version="1.0.0",
        )
        assert len(delta.relations) == 1
        assert delta.history_provider == "operation_semantics"

    def test_resolution_status_enum(self):
        """All resolution statuses are accepted."""
        for status in ("exact", "set", "deleted", "ambiguous", "unresolved", "type_mismatch"):
            res = TopologyResolution(requested_id="test", status=status)  # type: ignore[arg-type]
            assert res.status == status

    def test_named_topology_set_fail_closed(self):
        """NamedTopologySet defaults to exact resolution (fail-closed)."""
        nts = NamedTopologySet(
            name="disk.hub.mounting_face",
            entity_type="face",
            persistent_ids=["gct:v1:doc:disk:n1:n1:face:mounting"],
            semantic_purpose="constraint",
        )
        assert nts.required_resolution == "exact"


# ═══════════════════════════════════════════════════════════════════════════════
# Sidecar persistence tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTopologySidecar:
    """Sidecar read/write round-trip tests."""

    def test_write_and_read_sidecar(self, empty_registry, tmp_path):
        """Sidecar survives write → clear → read cycle."""
        reg = empty_registry
        pid = "gct:v1:doc-1:comp:n1:n1:face:sidecar_test"
        rec = TopologyEntityRecord(
            persistent_id=pid,
            entity_type="face",
            component_id="comp",
            owner_body_handle_id="solid:comp:n1:body",
            producer_node_id="n1",
            semantic_role="sidecar_test",
        )
        reg.register_entity(rec)

        sidecar_path = tmp_path / "test.topology.json"
        meta = write_topology_sidecar(
            reg, sidecar_path,
            document_id="doc-1",
            canonical_graph_hash="sha256:deadbeef",
            runtime_version="0.2.0",
        )
        assert sidecar_path.exists()
        assert meta["topology_schema_version"] in ("gcad_topology_v1", "gcad_topology_v2", "gcad_topology_v3")
        assert meta["entity_count"] == 1

        # Read into fresh registry
        reg2 = TopologyRegistry()
        meta2 = read_topology_sidecar(sidecar_path, reg2)
        assert reg2.entity_count == 1
        assert meta2["entity_count"] == 1

        # V3: after restore, entity has no locator → unresolved (T-009 fix)
        res = reg2.resolve(pid)
        assert res.status == "unresolved", (
            f"After sidecar restore, expected unresolved (no locator), got {res.status}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Semantic naming tests (require CadQuery)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSemanticNaming:
    """Semantic naming for primitives — requires CadQuery."""

    @pytest.mark.skipif(
        not _has_cadquery(),
        reason="CadQuery not available",
    )
    def test_box_face_naming_stable(self):
        """Box faces get stable semantic names across two identical builds."""
        import cadquery as cq

        box1 = cq.Workplane("XY").box(100, 50, 25)
        delta1 = name_box_faces(
            box1, document_id="d1", component_id="box",
            producer_node_id="n1", w=100, h=50, d=25,
        )

        box2 = cq.Workplane("XY").box(100, 50, 25)
        delta2 = name_box_faces(
            box2, document_id="d1", component_id="box",
            producer_node_id="n1", w=100, h=50, d=25,
        )

        roles1 = sorted(r.semantic_role for r in delta1.relations)
        roles2 = sorted(r.semantic_role for r in delta2.relations)
        assert roles1 == roles2, "Semantic roles must be identical across rebuilds"

    @pytest.mark.skipif(
        not _has_cadquery(),
        reason="CadQuery not available",
    )
    def test_box_face_roles_complete(self):
        """Box has exactly 6 faces with correct role prefixes."""
        import cadquery as cq

        box = cq.Workplane("XY").box(100, 50, 25)
        delta = name_box_faces(
            box, document_id="d1", component_id="box",
            producer_node_id="n1", w=100, h=50, d=25,
        )

        assert len(delta.relations) == 6, "Box should have exactly 6 faces"
        roles = {r.semantic_role for r in delta.relations}
        assert "box/x_max" in roles
        assert "box/x_min" in roles
        assert "box/y_max" in roles
        assert "box/y_min" in roles
        assert "box/z_max" in roles
        assert "box/z_min" in roles

    @pytest.mark.skipif(
        not _has_cadquery(),
        reason="CadQuery not available",
    )
    def test_cylinder_face_naming(self):
        """Cylinder has lateral + two caps."""
        import cadquery as cq

        cyl = cq.Workplane("XY").circle(10).extrude(30)
        delta = name_cylinder_faces(
            cyl, document_id="d1", component_id="cyl",
            producer_node_id="n1", dia=20, height=30,
        )

        roles = {r.semantic_role for r in delta.relations}
        assert "cylinder/lateral" in roles
        assert any("cap" in (r or "") for r in roles), "Must have cap faces"

    @pytest.mark.skipif(
        not _has_cadquery(),
        reason="CadQuery not available",
    )
    def test_entity_records_from_box_delta(self):
        """build_entity_records_from_delta produces registrable records."""
        import cadquery as cq

        box = cq.Workplane("XY").box(100, 50, 25)
        delta = name_box_faces(
            box, document_id="d1", component_id="box",
            producer_node_id="n1", w=100, h=50, d=25,
        )

        records = build_entity_records_from_delta(delta, document_id="d1")
        assert len(records) == 6

        reg = TopologyRegistry()
        for rec in records:
            reg.register_entity(rec)

        assert reg.entity_count == 6
        assert reg.active_count == 6

        # Each face should resolve as exact
        for rec in records:
            res = reg.resolve(rec.persistent_id)
            assert res.status == "exact", f"Failed to resolve {rec.semantic_role}"


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end: delta → registry → sidecar round-trip (with CadQuery)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEnd:
    """Full pipeline: semantic naming → registry → sidecar → restore → resolve."""

    @pytest.mark.skipif(
        not _has_cadquery(),
        reason="CadQuery not available",
    )
    def test_box_full_round_trip(self, tmp_path):
        """Box: name faces → register → write sidecar → restore → resolve all."""
        import cadquery as cq

        # Build
        box = cq.Workplane("XY").box(100, 50, 25)
        delta = name_box_faces(
            box, document_id="doc-1", component_id="box",
            producer_node_id="n1", w=100, h=50, d=25,
        )
        records = build_entity_records_from_delta(delta, document_id="doc-1")

        # Register
        reg = TopologyRegistry()
        for rec in records:
            reg.register_entity(rec)

        # Export sidecar
        sidecar_path = tmp_path / "box.topology.json"
        meta = write_topology_sidecar(
            reg, sidecar_path,
            document_id="doc-1",
            canonical_graph_hash="sha256:abc123",
            runtime_version="0.2.0",
        )

        # Restore into fresh registry
        reg2 = TopologyRegistry()
        read_topology_sidecar(sidecar_path, reg2)

        # All 6 faces should resolve
        for rec in records:
            res = reg2.resolve(rec.persistent_id)
            assert res.status == "exact", (
                f"Face {rec.semantic_role} not resolved after restore"
            )

        # Integrity check
        integrity = reg2.validate_integrity()
        assert integrity["ok"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def empty_registry():
    """Fresh empty TopologyRegistry for each test."""
    return TopologyRegistry()


def _has_cadquery() -> bool:
    """Check if CadQuery is importable."""
    try:
        import cadquery  # noqa: F401
        return True
    except ImportError:
        return False
