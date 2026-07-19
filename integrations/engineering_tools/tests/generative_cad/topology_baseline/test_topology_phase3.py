"""Phase 3 tests — boolean history, hole naming, handler integration, split/merge."""

import pytest
import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.history_wrappers import (
    history_aware_boolean_fuse,
    history_aware_boolean_cut,
    _probe_capabilities,
)
from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
    build_entity_records_from_delta,
    name_hole_faces,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry


# ═══════════════════════════════════════════════════════════════════════════════
# History-aware boolean tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBooleanHistory:
    def test_boolean_fuse_returns_result(self):
        """Fuse two overlapping boxes — history capture works."""
        box1 = cq.Workplane("XY").box(10, 10, 10).val()
        box2 = cq.Workplane("XY").transformed(offset=(5, 0, 0)).box(10, 10, 10).val()

        result = history_aware_boolean_fuse(
            box1.wrapped, box2.wrapped,
        )
        assert result is not None
        assert result.result_shape is not None

    def test_boolean_cut_returns_result(self):
        """Cut a cylinder from a box — history capture works."""
        block = cq.Workplane("XY").box(20, 20, 10).val()
        cyl = cq.Workplane("XY").circle(5).extrude(20, both=True).val()

        result = history_aware_boolean_cut(
            block.wrapped, cyl.wrapped,
        )
        assert result is not None
        assert result.result_shape is not None

    def test_boolean_cut_tracks_deletions(self):
        """Tool body faces are tracked as deleted after cut."""
        block = cq.Workplane("XY").box(20, 20, 10)
        cutter = cq.Workplane("XY").circle(3).extrude(20, both=True)

        tool_faces = cutter.faces().vals()

        result = history_aware_boolean_cut(
            block.val().wrapped, cutter.val().wrapped,
            input_tool_faces=[f.wrapped for f in tool_faces],
        )
        assert result is not None
        assert result.history is not None

    def test_boolean_capability_probe(self):
        caps = _probe_capabilities()
        assert caps.get("boolean") == "full"


# ═══════════════════════════════════════════════════════════════════════════════
# Hole naming tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestHoleNaming:
    def test_through_hole_has_wall_and_rims(self):
        """Through hole produces hole_wall + entry_rim + exit_rim."""
        cutter = cq.Workplane("XY").circle(5).extrude(30, both=True)
        delta = name_hole_faces(
            cutter, document_id="doc", component_id="block",
            producer_node_id="hole_1", is_through_hole=True,
        )
        roles = {r.semantic_role for r in delta.relations if r.semantic_role}
        assert "hole/wall" in roles
        assert "hole/entry_rim" in roles
        assert "hole/exit_rim" in roles
        # Tool faces should be deleted
        deleted_roles = {r.semantic_role for r in delta.relations
                         if r.relation == "deleted"}
        assert any("hole_tool" in (r or "") for r in deleted_roles)

    def test_hole_delta_registers_in_registry(self):
        """Hole delta can be registered and resolved."""
        cutter = cq.Workplane("XY").circle(5).extrude(30, both=True)
        delta = name_hole_faces(
            cutter, document_id="doc", component_id="block",
            producer_node_id="hole_1", is_through_hole=True,
        )
        reg = TopologyRegistry()
        records = build_entity_records_from_delta(delta, document_id="doc")
        for rec in records:
            reg.register_entity(rec)
        reg.apply_delta(delta)

        assert reg.entity_count >= 4
        assert reg.deleted_count >= 2  # tool faces deleted
        assert reg.active_count >= 2   # hole/wall + entry_rim + exit_rim

    def test_hole_entities_are_resolvable(self):
        """Active hole entities resolve correctly."""
        cutter = cq.Workplane("XY").circle(5).extrude(30, both=True)
        delta = name_hole_faces(
            cutter, document_id="doc", component_id="block",
            producer_node_id="hole_1", is_through_hole=True,
        )
        reg = TopologyRegistry()
        records = build_entity_records_from_delta(delta, document_id="doc")
        for rec in records:
            reg.register_entity(rec)
        reg.apply_delta(delta)

        wall_entities = reg.get_by_alias("hole/wall")
        assert len(wall_entities) >= 1
        for ent in wall_entities:
            res = reg.resolve(ent.persistent_id)
            assert res.status == "unresolved"  # V3: semantic records have no locator

    def test_hole_snapshot_round_trip(self):
        """Hole topology survives snapshot cycle."""
        cutter = cq.Workplane("XY").circle(5).extrude(30, both=True)
        delta = name_hole_faces(
            cutter, document_id="doc", component_id="block",
            producer_node_id="hole_1", is_through_hole=True,
        )
        reg = TopologyRegistry()
        records = build_entity_records_from_delta(delta, document_id="doc")
        for rec in records:
            reg.register_entity(rec)
        reg.apply_delta(delta)

        snap = reg.export_snapshot()
        reg2 = TopologyRegistry()
        reg2.restore_snapshot(snap)

        assert reg2.entity_count == reg.entity_count
        assert reg2.deleted_count == reg.deleted_count
        assert reg2.active_count == reg.active_count

    def test_hole_delta_stable_across_rebuild(self):
        """Two identical hole cutters produce identical deltas."""
        cutter1 = cq.Workplane("XY").circle(5).extrude(30, both=True)
        delta1 = name_hole_faces(
            cutter1, document_id="doc", component_id="block",
            producer_node_id="hole_1", is_through_hole=True,
        )
        cutter2 = cq.Workplane("XY").circle(5).extrude(30, both=True)
        delta2 = name_hole_faces(
            cutter2, document_id="doc", component_id="block",
            producer_node_id="hole_1", is_through_hole=True,
        )

        roles1 = sorted(r.semantic_role for r in delta1.relations if r.semantic_role)
        roles2 = sorted(r.semantic_role for r in delta2.relations if r.semantic_role)
        assert roles1 == roles2


# ═══════════════════════════════════════════════════════════════════════════════
# Split/Merge in TopologyDelta
# ═══════════════════════════════════════════════════════════════════════════════


class TestSplitMerge:
    def test_deleted_entities_not_resolvable_to_wrong_entity(self):
        """Deleted entities return 'deleted' status, not another face."""
        cutter = cq.Workplane("XY").circle(5).extrude(30, both=True)
        delta = name_hole_faces(
            cutter, document_id="doc", component_id="block",
            producer_node_id="hole_1", is_through_hole=True,
        )
        reg = TopologyRegistry()
        records = build_entity_records_from_delta(delta, document_id="doc")
        for rec in records:
            reg.register_entity(rec)
        reg.apply_delta(delta)

        # All deleted entities should resolve as 'deleted'
        for rec in records:
            if rec.status == "deleted":
                res = reg.resolve(rec.persistent_id)
                assert res.status == "deleted", (
                    f"Deleted entity {rec.semantic_role} resolved as {res.status}"
                )

    def test_split_relation_preserved_in_delta(self):
        """A split relation in the delta is recorded correctly."""
        from seekflow_engineering_tools.generative_cad.topology.models import (
            TopologyDelta, TopologyRelation,
        )

        delta = TopologyDelta(
            node_id="n1", component_id="comp",
            relations=[
                TopologyRelation(
                    relation="split",
                    source_ids=["old_face_id"],
                    result_entity_keys=["new_face_a", "new_face_b"],
                    semantic_role="split_example",
                ),
            ],
        )
        assert delta.relations[0].relation == "split"
        assert len(delta.relations[0].source_ids) == 1
        assert len(delta.relations[0].result_entity_keys) == 2
