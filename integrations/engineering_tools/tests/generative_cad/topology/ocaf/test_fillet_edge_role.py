"""Stage 2a: fillet can reference a persistent box edge role."""

from pathlib import Path

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import edge_role_key


def _edge_length(edge):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    props = GProp_GProps()
    BRepGProp.LinearProperties_s(TopoDS.Edge_s(edge), props)
    return round(float(props.Mass()), 3)


def _make_capture_ctx():
    import cadquery as cq
    from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
    from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
    from seekflow_engineering_tools.generative_cad.topology.ocaf.capture_session import CaptureSession
    from seekflow_engineering_tools.generative_cad.topology.ocaf.models import TopologyCaptureScope
    from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
        tracked_extrude,
    )

    ctx = RuntimeContext(
        out_step=Path("out.step"),
        metadata_path=Path("meta.json"),
        workspace_root=Path("."),
    )
    ctx.enable_topology_capture = True
    ctx.capture_session = CaptureSession()

    extrude = tracked_extrude(
        cq.Workplane("XY").rect(20, 20).val(), (0, 0, 10),
        scope=TopologyCaptureScope(node_id="n_extrude", component_id="part"),
    )
    ctx.capture_session.stage(extrude.batch)
    return ctx, extrude.result


class TestFilletEdgeRole:
    def test_resolve_edge_role(self):
        pytest.importorskip("cadquery")
        from seekflow_engineering_tools.generative_cad.pipeline.run import (
            _resolve_edge_role,
        )

        ctx, _body = _make_capture_ctx()
        edge = _resolve_edge_role(ctx, "part", edge_role_key("end_cap", "+Y"))
        assert edge is not None
        assert _edge_length(edge) == 20.0

    def test_fillet_single_edge_role(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.pipeline.run import (
            _resolve_edge_role,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            EvolutionKind,
            TopologyEntityKind,
            TopologyCaptureScope,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import (
            tracked_fillet,
        )

        ctx, body = _make_capture_ctx()
        edge = _resolve_edge_role(ctx, "part", edge_role_key("end_cap", "+Y"))

        fillet = tracked_fillet(
            body, [edge], 2.0,
            scope=TopologyCaptureScope(node_id="n_fillet", component_id="part"),
        )

        generated_faces = [
            r for r in fillet.batch.relations
            if r.kind == EvolutionKind.GENERATED
            and r.entity_kind == TopologyEntityKind.FACE
        ]
        assert len(generated_faces) == 1

        fillet_face = fillet.batch.construction_roles["fillet"]
        assert fillet_face is not None
        center = cq.Shape.cast(fillet_face).Center()
        assert abs(center.y - 10.0) < 3.0
        assert abs(center.z - 10.0) < 3.0
