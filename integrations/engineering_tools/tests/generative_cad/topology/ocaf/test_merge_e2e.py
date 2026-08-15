"""Merge (N→1) fix verification with process monitoring."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    TopologyCaptureScope,
)


def _rect_face(x1, x2, y1, y2, z):
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_MakeFace,
    )

    wb = BRepBuilderAPI_MakeWire()
    pts = [(x1, y1, z), (x2, y1, z), (x2, y2, z), (x1, y2, z)]
    for i in range(4):
        a = pts[i]
        b = pts[(i + 1) % 4]
        wb.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge())
    fb = BRepBuilderAPI_MakeFace(wb.Wire(), False)
    fb.Build()
    return fb.Face()


def _sew(faces):
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing

    sewer = BRepBuilderAPI_Sewing(1e-5)
    for f in faces:
        sewer.Add(f)
    sewer.Perform()
    return cq.Shape.cast(sewer.SewedShape())


class TestMergeEndToEnd:
    def test_merge_records_modified_not_deleted(self):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.unify import (
            tracked_unify,
        )

        left = _rect_face(-10, 0, -10, 10, 10)
        right = _rect_face(0, 10, -10, 10, 10)
        shell = _sew([left, right])

        print(f"[merge] shell faces before unify: {len(list(shell.Faces()))}")
        unified = tracked_unify(shell, scope=TopologyCaptureScope(node_id="n_unify"))
        print(f"[merge] shell faces after unify: {len(list(unified.result.Faces()))}")

        by_kind = {}
        for r in unified.batch.relations:
            by_kind.setdefault(r.kind.value, []).append(r.source_key)
            print(f"[merge] relation kind={r.kind.value} source={r.source_key}")
        print(f"[merge] relation summary: { {k: len(v) for k, v in by_kind.items()} }")

        # The merge must be recorded as MODIFIED (identity continues into the
        # merged face), not DELETED.
        assert EvolutionKind.DELETED.value not in by_kind
        assert EvolutionKind.MODIFIED.value in by_kind
        assert len(list(unified.result.Faces())) == 1
