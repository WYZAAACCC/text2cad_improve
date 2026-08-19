"""Complex scenario B: machined housing style chain.

extrude left + right blocks -> fuse -> [select split top face] -> unify
(merge coplanar top) -> fillet a vertical edge. Persist selections for the
pre-merge top face and a side face, rebuild with different dimensions across
revisions, and verify each selection against an objective geometric oracle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.complex_harness import (
    ComplexModelHarness,
    SelectionExpectation,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionPolicy,
    TopologyCaptureScope,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_fuse,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import (
    tracked_fillet,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.unify import (
    tracked_unify,
)


def find_side_face(body, x, tol=0.5):
    """Return the planar face whose centroid x is near the target side."""
    for f in body.Faces():
        c = f.Center()
        if abs(c.x - x) < tol:
            return f.wrapped
    return None


def find_vertical_edge(body, x, y, tol=0.5):
    """Return a vertical (Z-aligned) line edge near (x, y)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS

    for e in body.Edges():
        try:
            adaptor = BRepAdaptor_Curve(TopoDS.Edge_s(e.wrapped))
            if int(adaptor.GetType()) != 0:  # GeomAbs_Line
                continue
            d = adaptor.Line().Direction()
            if abs(abs(d.Z()) - 1.0) > 0.01:
                continue
            first = adaptor.FirstParameter()
            last = adaptor.LastParameter()
            mid = adaptor.Value((first + last) / 2.0)
            if abs(mid.X() - x) < tol and abs(mid.Y() - y) < tol:
                return e.wrapped
        except Exception:
            continue
    return None


def build_blocks(h, params, *, with_prev=False):
    """left extrude -> right extrude -> fuse; returns fused body."""
    import cadquery as cq

    width, depth, height = params["width"], params["depth"], params["height"]

    def prev(feature_id):
        if not with_prev:
            return None
        feat_label = h.session.ensure_feature(
            h.comp_label, feature_id, component_id=h.component_id,
        )
        return h.session.get_current_result_shape(feat_label)

    left_profile = (
        cq.Workplane("XY")
        .transformed(offset=(-width / 4, 0, 0))
        .rect(width / 2, depth)
        .val()
    )
    left = tracked_extrude(
        left_profile, (0, 0, height),
        scope=TopologyCaptureScope(node_id="n_left", component_id=h.component_id),
    )
    h.write_feature("n_left", left.batch, previous_result=prev("n_left"))

    right_profile = (
        cq.Workplane("XY")
        .transformed(offset=(width / 4, 0, 0))
        .rect(width / 2, depth)
        .val()
    )
    right = tracked_extrude(
        right_profile, (0, 0, height),
        scope=TopologyCaptureScope(node_id="n_right", component_id=h.component_id),
    )
    h.write_feature("n_right", right.batch, previous_result=prev("n_right"))

    fused = tracked_fuse(
        left.result, right.result,
        scope=TopologyCaptureScope(node_id="n_fuse", component_id=h.component_id),
    )
    h.write_feature("n_fuse", fused.batch, previous_result=prev("n_fuse"))
    return fused.result


def build_finish(h, body, params, *, with_prev=False):
    """unify -> fillet; returns final body."""
    width, depth, height = params["width"], params["depth"], params["height"]

    def prev(feature_id):
        if not with_prev:
            return None
        feat_label = h.session.ensure_feature(
            h.comp_label, feature_id, component_id=h.component_id,
        )
        return h.session.get_current_result_shape(feat_label)

    unified = tracked_unify(
        body,
        scope=TopologyCaptureScope(node_id="n_unify", component_id=h.component_id),
    )
    h.write_feature("n_unify", unified.batch, previous_result=prev("n_unify"))
    body = unified.result

    edge = find_vertical_edge(body, width / 2, depth / 2)
    assert edge is not None, "vertical edge for fillet not found"
    fillet = tracked_fillet(
        body, [edge], 1.5,
        scope=TopologyCaptureScope(node_id="n_fillet", component_id=h.component_id),
    )
    h.write_feature("n_fillet", fillet.batch, previous_result=prev("n_fillet"))
    return fillet.result


def create_housing_selections(h, body, params):
    width, depth, height = params["width"], params["depth"], params["height"]

    # Left half of the pre-merge top face: centroid x = -width/4, z = height.
    top_left = None
    for f in body.Faces():
        c = f.Center()
        if abs(c.z - height) < 0.5 and c.x < -0.5:
            top_left = f.wrapped
            break
    assert top_left is not None, "pre-merge left top face not found"

    side = find_side_face(body, width / 2)
    assert side is not None, "right side face not found"

    face_policy = SelectionPolicy(entity_kind=TopologyEntityKind.FACE)
    h.create_selection("left_top", top_left, body.wrapped, face_policy)
    h.create_selection("right_side", side, body.wrapped, face_policy)


def housing_expectations(params):
    width, depth, height = params["width"], params["depth"], params["height"]
    merged_area = width * depth
    side_area = depth * height
    return [
        SelectionExpectation(
            "left_top", status="unique", count=1,
            area_range=(merged_area * 0.95, merged_area * 1.05),
            label="merged top",
        ),
        SelectionExpectation(
            "right_side", status="unique", count=1,
            area_range=(side_area * 0.95, side_area * 1.05),
            label="right side",
        ),
    ]


PARAMS_1 = {"width": 40.0, "depth": 30.0, "height": 10.0}
PARAMS_2 = {"width": 50.0, "depth": 40.0, "height": 12.0}


class TestComplexMachinedHousing:
    def test_cross_revision_chain_with_oracle(self, ascii_tmpdir):
        pytest.importorskip("cadquery")
        xbf1 = Path(ascii_tmpdir) / "housing_rev1.xbf"

        h = ComplexModelHarness("housing")
        h.new_session(revision=1)
        body = build_blocks(h, PARAMS_1)
        create_housing_selections(h, body, PARAMS_1)
        body = build_finish(h, body, PARAMS_1)
        h.save(xbf1)

        h.open_session(xbf1)
        outcomes1 = h.solve_and_check(housing_expectations(PARAMS_1))
        for exp, ok, detail in outcomes1:
            assert ok, f"[rev1] {exp.label}: {detail}"

        body = build_blocks(h, PARAMS_2, with_prev=True)
        body = build_finish(h, body, PARAMS_2, with_prev=True)
        assert body.Volume() > 0
        outcomes2 = h.solve_and_check(housing_expectations(PARAMS_2))
        for exp, ok, detail in outcomes2:
            assert ok, f"[rev2] {exp.label}: {detail}"

        report = h.monitor.report()
        assert report["passed"], report
        assert len(report["capture"]) >= 5  # left + right + fuse + unify + fillet
        assert len(report["write"]) >= 5
        assert len(report["solve"]) == 4  # 2 selections x 2 revisions
        assert all(c["ok"] for c in report["checks"])
