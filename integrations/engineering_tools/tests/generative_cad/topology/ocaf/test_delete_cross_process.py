"""Cross-process DELETED selection detection (no native Solve crash)."""

from pathlib import Path

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService,
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


class TestDeleteCrossProcess:
    def test_deleted_selection_after_reopen(self, ascii_tmpdir):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
            tracked_cut,
        )

        xbf = Path(ascii_tmpdir) / "deleted.xbf"

        # Rev1: select top face, then cut it away entirely.
        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        box = cq.Workplane("XY").box(20, 20, 20).val()
        face = box.faces(">Z")
        comp = session.ensure_component("comp")
        feat = session.ensure_feature(comp, "n_box")
        writer.write_feature_result(feat, box.wrapped)
        svc = PersistentSelectionService(session)
        svc.create(
            "top", face.wrapped, box.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.FACE, allow_deleted=True),
        )
        tool = cq.Workplane("XY").transformed(offset=(0, 0, 12)).box(24, 24, 15).val()
        cut = tracked_cut(
            box, tool, scope=TopologyCaptureScope(node_id="n_cut", component_id="comp"),
        )
        writer.write_batch(cut.batch)
        session.label_index.save_to_ocaf(session.main_label)
        session.repository.save_to(xbf)
        session.close()

        # Reopen (fresh session = cross-process equivalent) and solve.
        session2 = OcafDocumentSession.open(xbf)
        svc2 = PersistentSelectionService(session2)
        label_map = collect_tnaming_labels(session2.design_root_label)
        resolution = svc2.solve("top", label_map)
        assert resolution.status == SelectionResolutionStatus.DELETED, (
            f"expected DELETED, got {resolution.status}: {resolution.detail}"
        )
        session2.close()
