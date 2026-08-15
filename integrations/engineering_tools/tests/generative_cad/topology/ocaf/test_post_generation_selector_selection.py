"""Post-generation arbitrary face/edge selection from persisted XBF."""

from __future__ import annotations

import pytest

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    collect_tnaming_labels,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
    OcafDocumentSession,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionResolutionStatus,
    TopologyCaptureScope,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService,
    create_selection_from_selector,
    create_selection_from_edge_selector,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
    TopologyNamingWriter,
)


class TestPostGenerationSelectorSelection:
    def test_face_and_edge_selector_after_reopen(self, tmp_path):
        pytest.importorskip("cadquery")
        xbf = tmp_path / "design.xbf"

        wire = cq.Workplane("XY").rect(20, 30).wires().val()
        tracked = tracked_extrude(
            wire,
            (0, 0, 10),
            scope=TopologyCaptureScope(node_id="extrude_node", component_id="comp_a"),
        )

        s1 = OcafDocumentSession.create()
        TopologyNamingWriter(s1).write_batch(tracked.batch)
        s1.label_index.save_to_ocaf(s1.main_label)
        s1.repository.save_to(xbf)
        s1.close()

        s2 = OcafDocumentSession.open(xbf)
        create_selection_from_selector(
            s2, "top_face", "comp_a", "extrude_node", ">Z",
        )
        create_selection_from_edge_selector(
            s2, "top_edge", "comp_a", "extrude_node", ">Z",
        )

        label_map = collect_tnaming_labels(s2.design_root_label)
        service = PersistentSelectionService(s2)
        face_result = service.solve("top_face", label_map)
        edge_result = service.solve("top_edge", label_map)

        assert face_result.status == SelectionResolutionStatus.UNIQUE
        assert edge_result.status == SelectionResolutionStatus.UNIQUE
        s2.close()
