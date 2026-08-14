"""Dependency closure: scoped valid_labels for multi-component Solve."""

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


class TestDependencyClosure:
    def test_scoped_collect_and_solve(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
            tracked_extrude,
        )

        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)

        extrudes = {}
        for cid in ("compA", "compB"):
            profile = cq.Workplane("XY").rect(40, 30).val()
            extrude = tracked_extrude(
                profile, (0, 0, 20),
                scope=TopologyCaptureScope(node_id="n_extrude", component_id=cid),
            )
            feat = session.ensure_feature(session.ensure_component(cid), "n_extrude")
            writer.write_batch(extrude.batch)
            extrudes[cid] = extrude

        svc = PersistentSelectionService(session)
        plus_x_a = extrudes["compA"].batch.construction_roles["+X"]
        svc.create(
            "x_side_A", plus_x_a, extrudes["compA"].result.wrapped,
            SelectionPolicy(entity_kind=TopologyEntityKind.FACE),
        )

        global_map = collect_tnaming_labels(session.design_root_label)
        scoped_map = session.collect_component_tnaming_labels("compA")
        assert scoped_map.Extent() > 0
        assert scoped_map.Extent() < global_map.Extent()

        resolution = svc.solve("x_side_A", scoped_map)
        assert resolution.status == SelectionResolutionStatus.UNIQUE, (
            f"expected UNIQUE, got {resolution.status}: {resolution.detail}"
        )
