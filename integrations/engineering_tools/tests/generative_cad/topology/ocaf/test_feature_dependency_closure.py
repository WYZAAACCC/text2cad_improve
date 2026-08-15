"""Feature-level dependency closure for tighter Solve scopes."""

from __future__ import annotations

import pytest

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
    OcafDocumentSession,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
    TopologyNamingWriter,
)


class TestFeatureDependencyClosure:
    def test_closure_is_tighter_than_component_subtree(self):
        pytest.importorskip("cadquery")
        session = OcafDocumentSession.create()
        writer = TopologyNamingWriter(session)
        profile = cq.Workplane("XY").rect(20, 10).val()

        for node_id in ("n_extrude_a", "n_extrude_b"):
            tracked = tracked_extrude(
                profile,
                (0, 0, 10),
                scope=TopologyCaptureScope(
                    node_id=node_id,
                    component_id="comp_a",
                ),
            )
            writer.write_batch(tracked.batch)

        component_map = session.collect_component_tnaming_labels("comp_a")
        feature_map = session.collect_feature_dependency_labels(
            [("comp_a", "n_extrude_a")],
            {},
        )
        assert feature_map.Extent() > 0
        assert feature_map.Extent() < component_map.Extent()
