"""Tracked Chamfer — wraps BRepFilletAPI_MakeChamfer with history extraction.

Same pattern as fillet: Generated(edge) → chamfer faces, Modified(face) → adjacent faces.
"""

from __future__ import annotations

from typing import Any

from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer
from OCP.TopoDS import TopoDS

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind, TopologyEntityKind, ProofClass,
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation,
    TrackedShapeResult, FaceRoleSpec,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops._carry import (
    all_faces_accounted,
    carry_unchanged_faces,
    find_partner_face,
)


def tracked_chamfer(
    body: Any,
    edge_shapes: list[Any],   # TopoDS_Edge shapes
    distance: float,
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Apply chamfer to persistent edges with history capture.

    Args:
        body: CadQuery Shape to chamfer.
        edge_shapes: List of TopoDS_Edge shapes (resolved via persistent Selection).
        distance: Chamfer distance in mm.
        scope: TopologyCaptureScope.
    """
    import cadquery as cq

    scope = scope or TopologyCaptureScope()
    body_faces = list(body.Faces())

    if not edge_shapes:
        raise ValueError("No edge shapes specified for chamfer")

    builder = BRepFilletAPI_MakeChamfer(body.wrapped)
    for edge_shape in edge_shapes:
        edge = TopoDS.Edge_s(edge_shape)
        builder.Add(distance, edge)

    builder.Build()
    if not builder.IsDone():
        raise RuntimeError("BRepFilletAPI_MakeChamfer failed")

    result_shape = builder.Shape()
    result = cq.Shape.cast(result_shape)

    relations: list[LiveEvolutionRelation] = []
    face_roles: dict[str, FaceRoleSpec] = {}
    chamfer_face = None

    for i, edge_shape in enumerate(edge_shapes):
        edge = TopoDS.Edge_s(edge_shape)
        gen_list = builder.Generated(edge)
        gen_shapes = tuple(gen_list)
        if gen_shapes:
            if chamfer_face is None:
                chamfer_face = gen_shapes[0]
            relations.append(LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/chamfer/gen/edge_{i}",
                operation_id=scope.node_id,
                kind=EvolutionKind.GENERATED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=f"edge_{i}",
                old_shape=edge,
                new_shapes=gen_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            ))

    for i, face in enumerate(body_faces):
        mod_list = builder.Modified(face.wrapped)
        mod_shapes = tuple(mod_list)
        if mod_shapes:
            role_key = f"face_{i}"
            relations.append(LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/chamfer/mod/face_{i}",
                operation_id=scope.node_id,
                kind=EvolutionKind.MODIFIED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=f"face_{i}",
                old_shape=face.wrapped,
                new_shapes=mod_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            ))
            face_roles[role_key] = FaceRoleSpec(
                role_key=role_key,
                shape=mod_shapes[0],
                source_shape=face.wrapped,
                first_evolution=EvolutionKind.MODIFIED,
            )

    carry_unchanged_faces(relations, scope, result.wrapped, body_faces, "chamfer")
    for i, face in enumerate(body_faces):
        role_key = f"face_{i}"
        if role_key in face_roles:
            continue
        partner = find_partner_face(result.wrapped, face.wrapped)
        if partner is not None:
            face_roles[role_key] = FaceRoleSpec(
                role_key=role_key,
                shape=partner,
                source_shape=face.wrapped,
                first_evolution=EvolutionKind.MODIFIED,
            )
    history_complete = all_faces_accounted(relations, body_faces)

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="BRepFilletAPI_MakeChamfer",
        builder_options={"distance": distance},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        construction_roles={"chamfer": chamfer_face},
        face_roles=face_roles,
        history_complete=history_complete,
        missing_phases=[] if history_complete else ["some input faces are not accounted for"],
    )
    return TrackedShapeResult(result=result, batch=batch)
