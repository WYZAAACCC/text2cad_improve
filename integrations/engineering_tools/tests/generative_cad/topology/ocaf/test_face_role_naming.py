"""Per-face naming infrastructure regression tests."""

from __future__ import annotations

import pytest

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
    OcafDocumentSession,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
    FEATURE_TAG_RESULT_ROOT,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_cut,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.mirror import (
    tracked_mirror,
)


class TestFaceRoleIndex:
    def test_face_role_tag_is_stable_and_under_result_root(self):
        session = OcafDocumentSession.create()
        comp = session.ensure_component("comp_a")
        feat = session.ensure_feature(comp, "extrude_node")
        e1 = session.label_index.allocate_face_role(
            comp.Tag(), feat.Tag(), "feature:extrude_node", "face_0", 1,
        )
        e2 = session.label_index.allocate_face_role(
            comp.Tag(), feat.Tag(), "feature:extrude_node", "face_0", 2,
        )
        assert e1.tag_path.tags == e2.tag_path.tags
        assert e1.tag_path.tags[-2] == FEATURE_TAG_RESULT_ROOT


class TestTrackedExtrudeOrdinaryFaces:
    def test_non_axis_aligned_side_faces_are_named(self):
        pytest.importorskip("cadquery")
        wire = (
            cq.Workplane("XY")
            .polyline([(0, 0), (20, 0), (10, 15)])
            .close()
            .wires()
            .val()
        )
        tracked = tracked_extrude(
            wire,
            (0, 0, 10),
            scope=TopologyCaptureScope(node_id="extrude_node", component_id="comp_a"),
        )
        assert tracked.batch.face_roles
        assert len(tracked.batch.face_roles) >= 2


class TestExactHistoryOperationsFaceRoles:
    def test_cut_populates_face_roles(self):
        target = cq.Workplane("XY").box(20, 20, 10).val()
        tool = cq.Workplane("XY").transformed(offset=(5, 5, -5)).box(8, 8, 12).val()
        tracked = tracked_cut(
            target,
            tool,
            scope=TopologyCaptureScope(node_id="cut_node", component_id="comp_a"),
        )
        assert tracked.batch.face_roles

    def test_mirror_populates_face_roles(self):
        body = cq.Workplane("XY").box(20, 10, 5).val()
        tracked = tracked_mirror(
            body,
            origin=(0, 0, 0),
            normal=(0, 1, 0),
            scope=TopologyCaptureScope(node_id="mirror_node", component_id="comp_a"),
        )
        assert len(tracked.batch.face_roles) == 6
