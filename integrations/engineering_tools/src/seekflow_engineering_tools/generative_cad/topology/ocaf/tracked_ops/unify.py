"""Tracked Unify — wraps ShapeUpgrade_UnifySameDomain with history extraction.

Merges coplanar faces. HAS History() in OCP 7.8.1.1 (verified PR-5 Step 0).
"""

from __future__ import annotations

from typing import Any

from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind, TopologyEntityKind, ProofClass,
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation,
    TrackedShapeResult, FaceRoleSpec,
)


def tracked_unify(
    body: Any,
    *,
    angular_tolerance: float = 1e-5,
    linear_tolerance: float = 1e-5,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Unify coplanar/colinear faces with history capture.

    Args:
        body: CadQuery Shape to unify.
        angular_tolerance: Angular tolerance in radians.
        linear_tolerance: Linear tolerance in mm.
        scope: TopologyCaptureScope.
    """
    import cadquery as cq

    scope = scope or TopologyCaptureScope()

    upgrader = ShapeUpgrade_UnifySameDomain(body.wrapped)
    upgrader.SetAngularTolerance(angular_tolerance)
    upgrader.SetLinearTolerance(linear_tolerance)
    upgrader.Build()

    result_shape = upgrader.Shape()
    result = cq.Shape.cast(result_shape)

    # Extract history — ShapeUpgrade_UnifySameDomain HAS History() in OCP 7.8.1.1!
    history = upgrader.History()
    relations: list[LiveEvolutionRelation] = []
    face_roles: dict[str, FaceRoleSpec] = {}

    # Iterate all original faces, check what happened to each
    exp = TopExp_Explorer(body.wrapped, TopAbs_FACE)
    face_idx = 0
    while exp.More():
        old_face = exp.Current()
        exp.Next()

        # Generated: new merged faces
        gen_list = history.Generated(old_face)
        gen_shapes = tuple(gen_list)
        if gen_shapes:
            relations.append(LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/unify/gen/face_{face_idx}",
                operation_id=scope.node_id,
                kind=EvolutionKind.GENERATED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=f"face_{face_idx}",
                old_shape=old_face,
                new_shapes=gen_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            ))
            for j, new_shape in enumerate(gen_shapes):
                role_key = f"face_{face_idx}/gen/{j}"
                face_roles[role_key] = FaceRoleSpec(
                    role_key=role_key,
                    shape=new_shape,
                    source_shape=old_face,
                    first_evolution=EvolutionKind.GENERATED,
                )

        # Modified: faces that were modified
        mod_list = history.Modified(old_face)
        mod_shapes = tuple(mod_list)
        if mod_shapes:
            relations.append(LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/unify/mod/face_{face_idx}",
                operation_id=scope.node_id,
                kind=EvolutionKind.MODIFIED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=f"face_{face_idx}",
                old_shape=old_face,
                new_shapes=mod_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            ))
            for j, new_shape in enumerate(mod_shapes):
                role_key = f"face_{face_idx}/mod/{j}"
                face_roles[role_key] = FaceRoleSpec(
                    role_key=role_key,
                    shape=new_shape,
                    source_shape=old_face,
                    first_evolution=EvolutionKind.MODIFIED,
                )

        # IsRemoved: only truly-deleted faces (no Generated/Modified) → DELETED.
        # A merged face is both IsRemoved and Generated(old→merged), so it must
        # keep the GENERATED relation instead of being marked DELETED.
        if history.IsRemoved(old_face) and not gen_shapes and not mod_shapes:
            relations.append(LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/unify/del/face_{face_idx}",
                operation_id=scope.node_id,
                kind=EvolutionKind.DELETED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=f"face_{face_idx}",
                old_shape=old_face,
                new_shapes=(),
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            ))

        face_idx += 1

    history_complete = len(relations) > 0
    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="ShapeUpgrade_UnifySameDomain",
        builder_options={
            "angular_tolerance": angular_tolerance,
            "linear_tolerance": linear_tolerance,
        },
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        face_roles=face_roles,
        history_complete=history_complete,
        missing_phases=[] if history_complete else ["no faces were modified by unify"],
    )
    return TrackedShapeResult(result=result, batch=batch)
