"""Tracked Fillet — wraps BRepFilletAPI_MakeFillet with history extraction.

PR-5 fix: edge_shapes: list[TopoDS_Shape] instead of list[int] (R-06).
Caller must resolve persistent EDGE identity to TopoDS_Shape before calling.
"""

from __future__ import annotations

from typing import Any

from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.TopoDS import TopoDS

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind, TopologyEntityKind, ProofClass,
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation,
    TrackedShapeResult, FaceRoleSpec,
    make_relation_key, make_source_ref,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops._carry import (
    all_faces_accounted,
    carry_unchanged_faces,
    find_partner_face,
)


def tracked_fillet(
    body: Any,
    edge_shapes: list[Any],   # ★ TopoDS_Edge shapes, NOT indices
    radius: float,
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Apply fillet to persistent edges with history capture.

    Args:
        body: CadQuery Shape to fillet.
        edge_shapes: List of TopoDS_Edge shapes (NOT indices — resolved via persistent Selection).
        radius: Fillet radius in mm.
        scope: TopologyCaptureScope.
    """
    import cadquery as cq

    scope = scope or TopologyCaptureScope()
    body_faces = list(body.Faces())

    if not edge_shapes:
        raise ValueError("No edge shapes specified for fillet")

    builder = BRepFilletAPI_MakeFillet(body.wrapped)
    for edge_shape in edge_shapes:
        edge = TopoDS.Edge_s(edge_shape)
        builder.Add(radius, edge)

    builder.Build()
    if not builder.IsDone():
        raise RuntimeError("BRepFilletAPI_MakeFillet failed")

    result_shape = builder.Shape()
    result = cq.Shape.cast(result_shape)

    relations: list[LiveEvolutionRelation] = []
    face_roles: dict[str, FaceRoleSpec] = {}
    fillet_face = None

    # Generated: each filleted edge produces a fillet face
    for i, edge_shape in enumerate(edge_shapes):
        edge = TopoDS.Edge_s(edge_shape)
        gen_list = builder.Generated(edge)
        gen_shapes = tuple(gen_list)
        if gen_shapes:
            if fillet_face is None:
                fillet_face = gen_shapes[0]
            relations.append(LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/fillet/gen/edge_{i}",
                operation_id=scope.node_id,
                kind=EvolutionKind.GENERATED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=f"edge_{i}",
                old_shape=edge,
                new_shapes=gen_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
                relation_key=make_relation_key(
                    scope.component_id, scope.node_id, f"edge_{i}",
                    EvolutionKind.GENERATED, relation_role="fillet_edge",
                ),
            ))

    # Modified: adjacent faces modified by fillet
    for i, face in enumerate(body_faces):
        mod_list = builder.Modified(face.wrapped)
        mod_shapes = tuple(mod_list)
        if mod_shapes:
            role_key = f"face_{i}"
            relations.append(LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/fillet/mod/face_{i}",
                operation_id=scope.node_id,
                kind=EvolutionKind.MODIFIED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=f"face_{i}",
                old_shape=face.wrapped,
                new_shapes=mod_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
                relation_key=make_relation_key(
                    scope.component_id, scope.node_id, f"face_{i}",
                    EvolutionKind.MODIFIED, relation_role="fillet_adjacent",
                ),
            ))
            face_roles[role_key] = FaceRoleSpec(
                role_key=role_key,
                shape=mod_shapes[0],
                source_shape=face.wrapped,
                first_evolution=EvolutionKind.MODIFIED,
                source_ref=make_source_ref(
                    scope.component_id, scope.node_id, f"face_{i}",
                ),
            )

    # Faces untouched by the fillet keep their TShape; record that explicitly
    # so history_complete is an honest signal rather than a hardcoded True.
    carry_unchanged_faces(relations, scope, result.wrapped, body_faces, "fillet")
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
                source_ref=make_source_ref(
                    scope.component_id, scope.node_id, f"face_{i}",
                ),
            )
    history_complete = all_faces_accounted(relations, body_faces)

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="BRepFilletAPI_MakeFillet",
        builder_options={"radius": radius},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        construction_roles={"fillet": fillet_face},
        edge_roles={f"edge_{i}": edge_shape for i, edge_shape in enumerate(edge_shapes)},
        face_roles=face_roles,
        history_complete=history_complete,
        missing_phases=[] if history_complete else ["some input faces are not accounted for"],
    )
    return TrackedShapeResult(result=result, batch=batch)
