"""G9: verify_xbf actually solves persisted selections."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.verify_worker import verify_xbf


class TestVerifySelectionRoundtrip:
    def test_verify_reports_unique_selection(self, ascii_tmpdir):
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
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            SelectionPolicy,
            TopologyEntityKind,
        )

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        box = cq.Workplane("XY").box(20, 20, 10).val()
        face = box.faces(">Z")
        comp = session.ensure_component("comp")
        feat = session.ensure_feature(comp, "n_box")
        writer.write_feature_result(feat, box.wrapped)

        svc = PersistentSelectionService(session)
        svc.create(
            "top_face", face.wrapped, box.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )
        session.label_index.save_to_ocaf(session.main_label)

        path = ascii_tmpdir / "sel.xbf"
        session.repository.save_to(path)
        session.close()

        result = verify_xbf(path)
        assert result.ok
        assert result.selection_count == 1
        assert result.selection_ok_count == 1
        assert result.selection_statuses.get("top_face") == "unique"

    def test_verify_no_selections(self, ascii_tmpdir):
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )

        session = OcafDocumentSession.create()
        session.ensure_component("comp")
        session.label_index.save_to_ocaf(session.main_label)

        path = ascii_tmpdir / "no_sel.xbf"
        session.repository.save_to(path)
        session.close()

        result = verify_xbf(path)
        assert result.ok
        assert result.selection_count == 0
        assert result.selection_ok_count == 0
