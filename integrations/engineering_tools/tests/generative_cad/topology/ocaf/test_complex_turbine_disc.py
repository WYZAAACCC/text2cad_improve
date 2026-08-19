"""Complex scenario A: turbine-disc style multi-op chain.

revolve disc -> 6 bolt-hole cuts -> fillet one hole edge, then persist
selections for bore/rim/hole surfaces and the rim top edge. Rebuild with
different dimensions across revisions and verify each selection against an
objective geometric oracle while monitoring capture/write/solve/verify.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.complex_harness import (
    ComplexModelHarness,
    SelectionExpectation,
    cylinder_radius,
    edge_length,
    shape_summary,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionPolicy,
    TopologyCaptureScope,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_cut,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import (
    tracked_fillet,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.revolve import (
    tracked_revolve,
)


def make_disc_profile(r_bore: float, r_outer: float, z_half: float):
    """Ring cross-section in XZ as a Face: bore inner -> rim outer.

    Revolving a Face (not a bare wire) yields a solid disc; a wire yields a
    hollow shell.
    """
    import cadquery as cq

    pts = [
        (r_bore, 0),
        (r_bore, z_half),
        (r_outer, z_half),
        (r_outer, 0),
    ]
    wp = cq.Workplane("XZ")
    wp = wp.moveTo(pts[0][0], pts[0][1])
    for x, z in pts[1:]:
        wp = wp.lineTo(x, z)
    wp = wp.close()
    return cq.Face.makeFromWires(wp.val())


def find_cylinder_face(body, radius: float, tol: float = 0.5):
    """Return the first cylindrical face whose radius is within tol."""
    for f in body.Faces():
        r = cylinder_radius(f.wrapped)
        if r is not None and abs(r - radius) < tol:
            return f.wrapped
    return None


def find_circle_edge(body, radius: float, z: float, tol: float = 1.0):
    """Return the first circular edge at radius/z within tol."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS

    for e in body.Edges():
        try:
            adaptor = BRepAdaptor_Curve(TopoDS.Edge_s(e.wrapped))
            if int(adaptor.GetType()) != 1:  # GeomAbs_Circle
                continue
            if abs(float(adaptor.Circle().Radius()) - radius) > tol:
                continue
            f = adaptor.FirstParameter()
            l = adaptor.LastParameter()
            mid = adaptor.Value((f + l) / 2.0)
            if abs(mid.Z() - z) < tol:
                return e.wrapped
        except Exception:
            continue
    return None


def build_disc_chain(h, params, *, with_prev=False):
    """revolve -> bolt holes -> fillet, writing each feature."""
    import cadquery as cq

    r_bore, r_outer, z_half = params["r_bore"], params["r_outer"], params["z_half"]
    pcd, r_hole, hole_count = params["pcd"], params["r_hole"], params["hole_count"]

    def prev(feature_id):
        if not with_prev:
            return None
        feat_label = h.session.ensure_feature(
            h.comp_label, feature_id, component_id=h.component_id,
        )
        return h.session.get_current_result_shape(feat_label)

    profile = make_disc_profile(r_bore, r_outer, z_half)
    rev = tracked_revolve(
        profile, (0, 0, 0), (0, 0, 1), 360,
        scope=TopologyCaptureScope(node_id="n_revolve", component_id=h.component_id),
    )
    h.write_feature("n_revolve", rev.batch, previous_result=prev("n_revolve"))
    body = rev.result

    for i in range(hole_count):
        angle = math.radians(i * 360.0 / hole_count)
        cx, cy = pcd * math.cos(angle), pcd * math.sin(angle)
        tool = (
            cq.Workplane("XY")
            .transformed(offset=(cx, cy, 0))
            .cylinder(z_half + 10, r_hole, centered=(True, True, False))
            .val()
        )
        cut = tracked_cut(
            body, tool,
            scope=TopologyCaptureScope(
                node_id=f"n_cut_hole_{i}", component_id=h.component_id,
            ),
        )
        h.write_feature(
            f"n_cut_hole_{i}", cut.batch, previous_result=prev(f"n_cut_hole_{i}"),
        )
        body = cut.result

    hole_edge = find_circle_edge(body, r_hole, z_half, tol=1.5)
    assert hole_edge is not None, "bolt-hole top edge not found"
    fillet = tracked_fillet(
        body, [hole_edge], 1.5,
        scope=TopologyCaptureScope(node_id="n_fillet", component_id=h.component_id),
    )
    h.write_feature("n_fillet", fillet.batch, previous_result=prev("n_fillet"))
    return fillet.result


def create_disc_selections(h, body, params):
    r_bore, r_outer, z_half = params["r_bore"], params["r_outer"], params["z_half"]
    r_hole = params["r_hole"]

    bore_face = find_cylinder_face(body, r_bore)
    rim_face = find_cylinder_face(body, r_outer)
    hole_face = find_cylinder_face(body, r_hole)
    rim_edge = find_circle_edge(body, r_outer, z_half)

    assert bore_face is not None, "bore face not found"
    assert rim_face is not None, "rim face not found"
    assert hole_face is not None, "hole face not found"
    assert rim_edge is not None, "rim top edge not found"

    face_policy = SelectionPolicy(entity_kind=TopologyEntityKind.FACE)
    edge_policy = SelectionPolicy(entity_kind=TopologyEntityKind.EDGE)
    h.create_selection("bore_surface", bore_face, body.wrapped, face_policy)
    h.create_selection("rim_surface", rim_face, body.wrapped, face_policy)
    h.create_selection("hole_inner_0", hole_face, body.wrapped, face_policy)
    h.create_selection("rim_top_edge", rim_edge, body.wrapped, edge_policy)


def disc_expectations(params):
    r_bore, r_outer, z_half = params["r_bore"], params["r_outer"], params["z_half"]
    r_hole = params["r_hole"]
    return [
        SelectionExpectation(
            "bore_surface", status="unique", count=1,
            radius_range=(r_bore - 0.5, r_bore + 0.5), label="bore",
        ),
        SelectionExpectation(
            "rim_surface", status="unique", count=1,
            radius_range=(r_outer - 0.5, r_outer + 0.5), label="rim",
        ),
        SelectionExpectation(
            "hole_inner_0", status="unique", count=1,
            radius_range=(r_hole - 0.5, r_hole + 0.5), label="hole",
        ),
        SelectionExpectation(
            "rim_top_edge", status="unique", count=1,
            length_range=(2 * math.pi * r_outer - 8, 2 * math.pi * r_outer + 8),
            label="rim edge",
        ),
    ]


PARAMS_1 = {
    "r_bore": 50.0, "r_outer": 200.0, "z_half": 30.0,
    "pcd": 140.0, "r_hole": 8.0, "hole_count": 6,
}
PARAMS_2 = {
    "r_bore": 60.0, "r_outer": 220.0, "z_half": 35.0,
    "pcd": 150.0, "r_hole": 8.0, "hole_count": 6,
}


class TestComplexTurbineDisc:
    def test_cross_revision_chain_with_oracle(self, ascii_tmpdir):
        pytest.importorskip("cadquery")
        xbf1 = Path(ascii_tmpdir) / "disc_rev1.xbf"

        h = ComplexModelHarness("disc")
        h.new_session(revision=1)
        body1 = build_disc_chain(h, PARAMS_1)
        create_disc_selections(h, body1, PARAMS_1)
        h.save(xbf1)

        # Rev1: solve in a fresh process-equivalent session.
        h.open_session(xbf1)
        outcomes1 = h.solve_and_check(disc_expectations(PARAMS_1))
        for exp, ok, detail in outcomes1:
            assert ok, f"[rev1] {exp.label}: {detail}"

        # Rev2: same features, different dimensions, previous_result chaining.
        body2 = build_disc_chain(h, PARAMS_2, with_prev=True)
        assert body2.Volume() > 0
        outcomes2 = h.solve_and_check(disc_expectations(PARAMS_2))
        for exp, ok, detail in outcomes2:
            assert ok, f"[rev2] {exp.label}: {detail}"

        report = h.monitor.report()
        assert report["passed"], report
        # The monitor must have observed every stage of the system.
        assert len(report["capture"]) >= 8  # revolve + 6 cuts + fillet
        assert len(report["write"]) >= 8
        assert len(report["solve"]) == 8  # 4 selections x 2 revisions
        assert all(c["ok"] for c in report["checks"])
