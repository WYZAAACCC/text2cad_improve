"""Feature/3 FACE GENERATED/MODIFIED relations are no longer TNaming."""

from __future__ import annotations

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
    OcafDocumentSession,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    LiveEvolutionBatch,
    LiveEvolutionRelation,
    ProofClass,
    TopologyCaptureScope,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
    TopologyNamingWriter,
)


def test_face_modified_relation_is_audit_only():
    box = cq.Workplane("XY").box(10, 10, 10).val()
    face = list(box.Faces())[0]
    relation = LiveEvolutionRelation(
        relation_id="n_box/face_0/mod",
        operation_id="n_box",
        kind=EvolutionKind.MODIFIED,
        entity_kind=TopologyEntityKind.FACE,
        source_key="face_0",
        old_shape=face.wrapped,
        new_shapes=(face.wrapped,),
        proof=ProofClass.EXACT_KERNEL_HISTORY,
    )
    batch = LiveEvolutionBatch(
        scope=TopologyCaptureScope(node_id="n_box", component_id="comp_a"),
        result_shape=box.wrapped,
        context_shape=box.wrapped,
        relations=[relation],
    )

    session = OcafDocumentSession.create()
    count = TopologyNamingWriter(session).write_batch(batch)
    # Only the feature result is TNaming; the FACE MODIFIED relation is skipped.
    assert count == 1
