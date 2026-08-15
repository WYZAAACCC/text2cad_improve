"""Stage 1: box edge roles survive across revisions."""

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


class TestEdgeRoleLineage:
    def test_box_edge_survives_resize(self, ascii_tmpdir):
        pytest.importorskip("cadquery")
        import cadquery as cq

        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
            TopologyNamingWriter,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
            create_selection_from_edge_role,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
            collect_tnaming_labels,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            SelectionPolicy,
            TopologyEntityKind,
            SelectionResolutionStatus,
            TopologyCaptureScope,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
            tracked_extrude,
        )

        path = Path(ascii_tmpdir) / "edge_lineage.xbf"
        edge_key = edge_role_key("end_cap", "+Y")

        # ---- Rev1: build a box and name its edge roles. ----
        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        comp = session.ensure_component("box")
        feat = session.ensure_feature(comp, "n_extrude")

        extrude1 = tracked_extrude(
            cq.Workplane("XY").rect(20, 20).val(), (0, 0, 10),
            scope=TopologyCaptureScope(node_id="n_extrude", component_id="box"),
        )
        assert edge_key in extrude1.batch.edge_roles
        writer.write_batch(extrude1.batch)
        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(path)
        session.close()

        # ---- Post-generation: select an edge role. ----
        session_pg = OcafDocumentSession.open(path)
        create_selection_from_edge_role(
            session_pg, "top_y_edge", "box", "n_extrude", edge_key,
            policy=SelectionPolicy(entity_kind=TopologyEntityKind.EDGE),
        )
        session_pg.label_index.save_to_ocaf(session_pg.main_label)
        session_pg.repository.save_to(path)
        session_pg.close()

        # ---- Rev2: resize the box, then solve the edge selection. ----
        session2 = OcafDocumentSession.open(path)
        writer2 = TopologyNamingWriter(session2)
        comp2 = session2.ensure_component("box")
        feat2 = session2.ensure_feature(comp2, "n_extrude")

        prev = session2.get_current_result_shape(feat2)
        assert prev is not None
        extrude2 = tracked_extrude(
            cq.Workplane("XY").rect(30, 30).val(), (0, 0, 10),
            scope=TopologyCaptureScope(node_id="n_extrude", component_id="box"),
        )
        writer2.write_batch(extrude2.batch, previous_result=prev)

        label_map = collect_tnaming_labels(session2.design_root_label)
        service = PersistentSelectionService(session2)
        resolution = service.solve("top_y_edge", label_map)

        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
        assert len(resolution.resolved_shapes) == 1
        assert _edge_length(resolution.resolved_shapes[0]) == 30.0, (
            f"expected resized edge length 30.0, "
            f"got {_edge_length(resolution.resolved_shapes[0])}"
        )
        session2.close()
