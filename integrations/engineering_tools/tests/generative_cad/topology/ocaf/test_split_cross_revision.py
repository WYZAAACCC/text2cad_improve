"""Split largest_area survives a cross-revision cut."""

from __future__ import annotations

import pytest

import cadquery as cq

from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    collect_tnaming_labels,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
    OcafDocumentSession,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionPolicy,
    TopologyCaptureScope,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
    PersistentSelectionService,
    SelectionResolutionStatus,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_cut,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
    TopologyNamingWriter,
)


def _build(height):
    wire = cq.Workplane("XY").rect(40, 40).wires().val()
    return tracked_extrude(
        wire,
        (0, 0, height),
        scope=TopologyCaptureScope(node_id="n_extrude", component_id="comp"),
    )


def _cut(body, height):
    tool = cq.Workplane("XY").transformed(offset=(0, 0, -2)).box(5, 40, height + 4).val()
    return tracked_cut(
        body,
        tool,
        scope=TopologyCaptureScope(node_id="n_cut", component_id="comp"),
    )


def test_split_cross_revision(tmp_path):
    pytest.importorskip("cadquery")
    rev1 = tmp_path / "rev1.xbf"
    rev2 = tmp_path / "rev2.xbf"

    s1 = OcafDocumentSession.create()
    writer = TopologyNamingWriter(s1)
    tr1 = _build(10)
    writer.write_batch(tr1.batch)
    top = tr1.result.faces(">Z").wrapped
    PersistentSelectionService(s1).create(
        "top",
        top,
        tr1.result.wrapped,
        SelectionPolicy(
            entity_kind=TopologyEntityKind.FACE,
            split_strategy="largest_area",
        ),
    )
    cut1 = _cut(tr1.result, 10)
    writer.write_batch(cut1.batch)
    s1.label_index.save_to_ocaf(s1.main_label)
    s1.repository.save_to(rev1)
    s1.close()

    s2 = OcafDocumentSession.open(rev1)
    comp = s2.ensure_component("comp")
    extrude_feat = s2.ensure_feature(comp, "n_extrude")
    cut_feat = s2.ensure_feature(comp, "n_cut")
    prev_extrude = s2.get_current_result_shape(extrude_feat)
    prev_cut = s2.get_current_result_shape(cut_feat)
    tr2 = _build(14)
    TopologyNamingWriter(s2).write_batch(tr2.batch, previous_result=prev_extrude)
    cut2 = _cut(tr2.result, 14)
    TopologyNamingWriter(s2).write_batch(cut2.batch, previous_result=prev_cut)

    resolution = PersistentSelectionService(s2).solve(
        "top", collect_tnaming_labels(s2.design_root_label),
    )
    assert resolution.status == SelectionResolutionStatus.UNIQUE
    assert len(resolution.resolved_shapes) == 1
    s2.label_index.save_to_ocaf(s2.main_label)
    s2.repository.save_to(rev2)
    s2.close()
