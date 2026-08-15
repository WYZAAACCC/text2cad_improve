"""Regression: a fillet-modified adjacent face follows the fillet Modify chain.

Before per-face naming, a selection created on a box/extrude top face before
fillet resolved to the stale pre-fillet face (area 600.0) instead of the
filleted adjacent face (area ~599.142). This test locks the corrected behavior.
"""

from __future__ import annotations

from pathlib import Path

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
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import (
    tracked_fillet,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
    TopologyNamingWriter,
)


def _area(shape) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return round(float(props.Mass()), 3)


def _build_extrude(height: float):
    wire = cq.Workplane("XY").rect(20, 30).wires().val()
    return tracked_extrude(
        wire,
        (0, 0, height),
        scope=TopologyCaptureScope(node_id="extrude_node", component_id="comp_a"),
    )


def _write(session, tracked, previous_result=None):
    TopologyNamingWriter(session).write_batch(
        tracked.batch, previous_result=previous_result,
    )


def _write_fillet(session, body, previous_result=None):
    tracked = tracked_fillet(
        body,
        [body.Edges()[0].wrapped],
        2.0,
        scope=TopologyCaptureScope(node_id="fillet_node", component_id="comp_a"),
    )
    TopologyNamingWriter(session).write_batch(
        tracked.batch, previous_result=previous_result,
    )
    return tracked.result


class TestFilletAdjacentFace:
    def test_adjacent_face_follows_fillet_across_revisions(self, tmp_path):
        pytest.importorskip("cadquery")

        rev1 = tmp_path / "rev1.xbf"
        rev2 = tmp_path / "rev2.xbf"
        rev3 = tmp_path / "rev3.xbf"

        # rev1: extrude base + select top face.
        s1 = OcafDocumentSession.create()
        tr1 = _build_extrude(10)
        _write(s1, tr1)
        body1 = tr1.result
        top1 = body1.faces(">Z").wrapped
        PersistentSelectionService(s1).create(
            "top", top1, body1.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )
        s1.label_index.save_to_ocaf(s1.main_label)
        s1.repository.save_to(rev1)
        s1.close()

        # rev2: modify extrude, then fillet.
        s2 = OcafDocumentSession.open(rev1)
        comp = s2.ensure_component("comp_a")
        feat = s2.ensure_feature(comp, "extrude_node")
        previous_extrude = s2.get_current_result_shape(feat)
        tr2 = _build_extrude(14)
        _write(s2, tr2, previous_result=previous_extrude)
        filleted2 = _write_fillet(s2, tr2.result)

        label_map = collect_tnaming_labels(s2.design_root_label)
        resolution2 = PersistentSelectionService(s2).solve("top", label_map)
        assert resolution2.status == SelectionResolutionStatus.UNIQUE
        assert len(resolution2.resolved_shapes) == 1
        assert _area(resolution2.resolved_shapes[0]) == pytest.approx(
            _area(filleted2.faces(">Z").wrapped), abs=0.001
        )
        s2.label_index.save_to_ocaf(s2.main_label)
        s2.repository.save_to(rev2)
        s2.close()

        # rev3: modify again, and modify the same fillet feature.
        s3 = OcafDocumentSession.open(rev2)
        comp = s3.ensure_component("comp_a")
        extrude_feat = s3.ensure_feature(comp, "extrude_node")
        fillet_feat = s3.ensure_feature(comp, "fillet_node")
        previous_extrude3 = s3.get_current_result_shape(extrude_feat)
        previous_fillet3 = s3.get_current_result_shape(fillet_feat)
        tr3 = _build_extrude(18)
        _write(s3, tr3, previous_result=previous_extrude3)
        filleted3 = _write_fillet(
            s3, tr3.result, previous_result=previous_fillet3,
        )

        label_map = collect_tnaming_labels(s3.design_root_label)
        resolution3 = PersistentSelectionService(s3).solve("top", label_map)
        assert resolution3.status == SelectionResolutionStatus.UNIQUE
        assert len(resolution3.resolved_shapes) == 1
        assert _area(resolution3.resolved_shapes[0]) == pytest.approx(
            _area(filleted3.faces(">Z").wrapped), abs=0.001
        )
        s3.label_index.save_to_ocaf(s3.main_label)
        s3.repository.save_to(rev3)
        s3.close()
