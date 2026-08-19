"""Complex scenario D: symmetric-equivalent faces must resolve uniquely.

Two geometrically identical bolt holes at 0 and 180 degrees are selected
independently. After persistence and across a revision rebuild, each must
resolve UNIQUE, land at its own position, and resolve to a different TShape
than the other hole. This is the strongest check that the naming system picks
the originally selected face, not merely some geometrically equivalent one.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.complex_harness import (
    ComplexModelHarness,
    cylinder_radius,
    shape_summary,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    collect_tnaming_labels,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionPolicy,
    SelectionResolutionStatus,
    TopologyCaptureScope,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_cut,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.revolve import (
    tracked_revolve,
)


def make_disc_profile(r_bore: float, r_outer: float, z_half: float):
    import cadquery as cq

    pts = [(r_bore, 0), (r_bore, z_half), (r_outer, z_half), (r_outer, 0)]
    wp = cq.Workplane("XZ")
    wp = wp.moveTo(pts[0][0], pts[0][1])
    for x, z in pts[1:]:
        wp = wp.lineTo(x, z)
    wp = wp.close()
    return cq.Face.makeFromWires(wp.val())


def build_disc(h, params, *, with_prev=False):
    import cadquery as cq

    r_bore, r_outer, z_half = params["r_bore"], params["r_outer"], params["z_half"]
    pcd, r_hole = params["pcd"], params["r_hole"]

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

    for i, angle_deg in enumerate((0.0, 180.0)):
        rad = math.radians(angle_deg)
        cx, cy = pcd * math.cos(rad), pcd * math.sin(rad)
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
    return body


def find_hole_face(body, cx, cy, r_hole, tol=2.0):
    for f in body.Faces():
        r = cylinder_radius(f.wrapped)
        if r is None or abs(r - r_hole) > 0.5:
            continue
        c = f.Center()
        if abs(c.x - cx) < tol and abs(c.y - cy) < tol:
            return f.wrapped
    return None


def _assert_unique_correct(resolution, expect_centroid, tol=3.0):
    assert resolution.status == SelectionResolutionStatus.UNIQUE, resolution.detail
    assert len(resolution.resolved_shapes) == 1
    c = shape_summary(resolution.resolved_shapes[0])["centroid"]
    assert c is not None
    assert abs(c[0] - expect_centroid[0]) < tol, f"x={c[0]} want ~{expect_centroid[0]}"
    assert abs(c[1] - expect_centroid[1]) < tol, f"y={c[1]} want ~{expect_centroid[1]}"


PARAMS_1 = {"r_bore": 50.0, "r_outer": 200.0, "z_half": 30.0, "pcd": 140.0, "r_hole": 8.0}
PARAMS_2 = {"r_bore": 55.0, "r_outer": 220.0, "z_half": 34.0, "pcd": 150.0, "r_hole": 8.0}


class TestComplexSymmetricHoles:
    def test_symmetric_holes_resolve_distinct_and_correct(self, ascii_tmpdir):
        pytest.importorskip("cadquery")
        xbf1 = Path(ascii_tmpdir) / "sym_holes_rev1.xbf"

        h = ComplexModelHarness("sym")
        h.new_session(revision=1)
        body = build_disc(h, PARAMS_1)

        hole0 = find_hole_face(body, PARAMS_1["pcd"], 0.0, PARAMS_1["r_hole"])
        hole1 = find_hole_face(body, -PARAMS_1["pcd"], 0.0, PARAMS_1["r_hole"])
        assert hole0 is not None and hole1 is not None
        # The two candidates must genuinely be distinct TShapes up front.
        assert not hole0.IsSame(hole1)

        face_policy = SelectionPolicy(entity_kind=TopologyEntityKind.FACE)
        h.create_selection("hole_0", hole0, body.wrapped, face_policy)
        h.create_selection("hole_1", hole1, body.wrapped, face_policy)
        h.save(xbf1)

        # Same-process-equivalent reopen: solve and assert uniqueness, position,
        # and mutual TShape distinctness.
        h.open_session(xbf1)
        svc = h.ensure_service()
        label_map = collect_tnaming_labels(h.session.design_root_label)
        r0 = svc.solve("hole_0", label_map)
        r1 = svc.solve("hole_1", label_map)
        _assert_unique_correct(r0, (PARAMS_1["pcd"], 0.0))
        _assert_unique_correct(r1, (-PARAMS_1["pcd"], 0.0))
        assert not r0.resolved_shapes[0].IsSame(r1.resolved_shapes[0])
        assert not r0.resolved_shapes[0].IsPartner(r1.resolved_shapes[0])

        # Cross-revision rebuild: same identity guarantees still hold.
        body2 = build_disc(h, PARAMS_2, with_prev=True)
        assert body2.Volume() > 0
        label_map2 = collect_tnaming_labels(h.session.design_root_label)
        r0b = svc.solve("hole_0", label_map2)
        r1b = svc.solve("hole_1", label_map2)
        _assert_unique_correct(r0b, (PARAMS_2["pcd"], 0.0))
        _assert_unique_correct(r1b, (-PARAMS_2["pcd"], 0.0))
        assert not r0b.resolved_shapes[0].IsSame(r1b.resolved_shapes[0])
        assert not r0b.resolved_shapes[0].IsPartner(r1b.resolved_shapes[0])
