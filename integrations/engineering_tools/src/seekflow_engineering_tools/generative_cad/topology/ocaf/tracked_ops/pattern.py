"""Tracked Linear Pattern — N copies along direction, fused with per-instance history.

Each copy is made via BRepBuilderAPI_Transform. Per-face history tracks:
  instance_0: original faces
  instance_1..N-1: transformed faces (source_face → copy_face)

The final result is all instances fused via BOPAlgo_FUSE.
"""

from __future__ import annotations

from typing import Any

import math

from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Trsf, gp_Vec, gp_Pnt, gp_Dir, gp_Ax1

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind, TopologyEntityKind, ProofClass,
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation, TrackedShapeResult,
    FaceRoleSpec,
    make_source_ref,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.history_graph import (
    HistoryGraph,
    HistoryComposer,
)


def _capture_fuse_face(relations, scope, fhist, face, si, fi, role, result_shape=None):
    """Query fuse history for one input face (v6.0 §10.1: input, not output).
    Returns (has_gen, has_mod) flags."""
    has_gen = False
    has_mod = False
    # Generated
    gen_list = fhist.Generated(face.wrapped)
    gen_shapes = tuple(gen_list)
    if gen_shapes:
        has_gen = True
        relations.append(LiveEvolutionRelation(
            relation_id=f"{scope.node_id}/pattern/fuse_{si}/{role}_{fi}",
            operation_id=scope.node_id,
            kind=EvolutionKind.GENERATED,
            entity_kind=TopologyEntityKind.FACE,
            source_key=f"fuse_{si}_{role}_{fi}",
            old_shape=face.wrapped,
            new_shapes=gen_shapes,
            proof=ProofClass.EXACT_KERNEL_HISTORY,
        ))
    # Modified
    mod_list = fhist.Modified(face.wrapped)
    mod_shapes = tuple(mod_list)
    if mod_shapes:
        has_mod = True
        relations.append(LiveEvolutionRelation(
            relation_id=f"{scope.node_id}/pattern/fuse_{si}/{role}_mod_{fi}",
            operation_id=scope.node_id,
            kind=EvolutionKind.MODIFIED,
            entity_kind=TopologyEntityKind.FACE,
            source_key=f"fuse_{si}_{role}_{fi}",
            old_shape=face.wrapped,
            new_shapes=mod_shapes,
            proof=ProofClass.EXACT_KERNEL_HISTORY,
        ))
    # IsRemoved
    if fhist.IsRemoved(face.wrapped):
        relations.append(LiveEvolutionRelation(
            relation_id=f"{scope.node_id}/pattern/fuse_{si}/{role}_del_{fi}",
            operation_id=scope.node_id,
            kind=EvolutionKind.DELETED,
            entity_kind=TopologyEntityKind.FACE,
            source_key=f"fuse_{si}_{role}_{fi}",
            old_shape=face.wrapped,
            new_shapes=(),
            proof=ProofClass.EXACT_KERNEL_HISTORY,
        ))
    # v7 Phase 3: BOPAlgo_BOP does NOT populate History() for a disjoint fuse
    # (faces are carried through unchanged). Recognize carry-through as a valid,
    # identity-preserving history instead of flagging the fuse step incomplete.
    # No TNaming relation is written — the face's TShape is unchanged, so its
    # persistent identity already survives.
    if not gen_shapes and not mod_shapes and not fhist.IsRemoved(face.wrapped):
        if result_shape is not None and _find_partner_face(result_shape, face.wrapped) is not None:
            has_mod = True
    return has_gen, has_mod


def _find_partner_face(result_shape, face):
    """Return a face in result_shape sharing the same TShape as ``face``."""
    import cadquery as cq
    for rf in cq.Shape.cast(result_shape).Faces():
        if rf.wrapped.IsPartner(face) or rf.wrapped.IsSame(face):
            return rf.wrapped
    return None


def tracked_linear_pattern(
    body: Any,
    direction: tuple[float, float, float],
    count: int,
    spacing: float,
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Create N-1 copies along direction, spaced by `spacing`, fused together.

    Per-instance face history:
      source_key = "face_{face_idx}_inst_{instance_idx}"
      instance 0 = original body faces (PRIMITIVE)
      instance 1..N-1 = transformed copies (MODIFIED)

    Args:
        body: CadQuery Shape to pattern.
        direction: Direction vector (dx, dy, dz).
        count: Total number of instances (including original).
        spacing: Distance between instances in mm.
        scope: TopologyCaptureScope.
    """
    import cadquery as cq

    scope = scope or TopologyCaptureScope()
    relations: list[LiveEvolutionRelation] = []
    face_roles: dict[str, FaceRoleSpec] = {}

    # Compute direction vector
    dx, dy, dz = direction
    length = (dx*dx + dy*dy + dz*dz) ** 0.5
    if length < 1e-9:
        raise ValueError("Direction vector has zero length")
    ux, uy, uz = dx/length, dy/length, dz/length

    # Create transforms and collect shapes
    instance_shapes: list[Any] = []

    for inst in range(count):
        if inst == 0:
            # Original — no transform
            instance_shapes.append(body.wrapped)
        else:
            dist = spacing * inst
            trsf = gp_Trsf()
            trsf.SetTranslation(gp_Vec(ux * dist, uy * dist, uz * dist))
            builder = BRepBuilderAPI_Transform(body.wrapped, trsf)
            builder.Build()

            if not builder.IsDone():
                raise RuntimeError(f"BRepBuilderAPI_Transform failed for instance {inst}")

            copy_shape = builder.Shape()
            instance_shapes.append(copy_shape)

            # Per-face history: source face → copy face
            for fi, face in enumerate(body.Faces()):
                mod_list = builder.Modified(face.wrapped)
                mod_shapes = tuple(mod_list)
                if mod_shapes:
                    relations.append(LiveEvolutionRelation(
                        relation_id=f"{scope.node_id}/pattern/inst_{inst}/face_{fi}",
                        operation_id=scope.node_id,
                        kind=EvolutionKind.GENERATED,
                        entity_kind=TopologyEntityKind.FACE,
                        source_key=f"face_{fi}_inst_{inst}",
                        old_shape=face.wrapped,
                        new_shapes=mod_shapes,
                        proof=ProofClass.EXACT_KERNEL_HISTORY,
                    ))

    # Fuse all instances with history capture (P1-03)
    history_complete = True
    missing_phases: list[str] = []
    if len(instance_shapes) > 1:
        from OCP.BOPAlgo import BOPAlgo_BOP, BOPAlgo_FUSE
        fused = instance_shapes[0]
        for si, s in enumerate(instance_shapes[1:]):
            fuser = BOPAlgo_BOP()
            fuser.SetOperation(BOPAlgo_FUSE)
            fuser.SetToFillHistory(True)
            fuser.AddArgument(fused)
            fuser.AddTool(s)
            fuser.Perform()
            new_fused = fuser.Shape()

            # ★ v6.0 §10.1: query history on INPUT shapes, not output
            fhist = fuser.History()
            if fhist is not None:
                has_gen = False
                has_mod = False
                # Query on argument (previous_fused) faces
                for fi, face in enumerate(cq.Shape.cast(fused).Faces()):
                    g, m = _capture_fuse_face(relations, scope, fhist, face, si, fi, "arg", new_fused)
                    has_gen = has_gen or g; has_mod = has_mod or m
                # Query on tool faces
                for fi, face in enumerate(cq.Shape.cast(s).Faces()):
                    g, m = _capture_fuse_face(relations, scope, fhist, face, si, fi, "tool", new_fused)
                    has_gen = has_gen or g; has_mod = has_mod or m
                if not has_gen and not has_mod:
                    history_complete = False
                    missing_phases.append(f"fuse_step_{si}_no_history")
            else:
                history_complete = False
                missing_phases.append(f"fuse_step_{si}")
            fused = new_fused
        result = cq.Shape.cast(fused)

        # v7 Phase 3: history is only "complete" if every original face can be
        # traced through the arg chain to a final output (or is explicitly
        # deleted). A dangling face means the multi-stage fuse history cannot
        # be composed into original->final, so the CAE complete-history gate
        # must not pass.
        graph = HistoryGraph.from_relations(relations)
        composer = HistoryComposer()
        for fi, face in enumerate(body.Faces()):
            finals = composer.compose(
                graph, [face.wrapped], follow_tokens=("_arg_",),
            )
            deleted = graph.successors(
                face.wrapped,
                follow_kinds=(EvolutionKind.DELETED,),
                follow_tokens=("_arg_",),
            )
            if not finals and not deleted:
                history_complete = False
                missing_phases.append(f"face_{fi}_not_composable")
            for j, final_shape in enumerate(finals):
                role_key = f"face_{fi}/final/{j}"
                face_roles[role_key] = FaceRoleSpec(
                    role_key=role_key,
                    shape=final_shape,
                    source_shape=face.wrapped,
                    first_evolution=EvolutionKind.MODIFIED,
                    source_ref=make_source_ref(
                        scope.component_id, scope.node_id, f"face_{fi}",
                    ),
                )
    else:
        result = body

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="LinearPattern",
        builder_options={
            "direction": direction,
            "count": count,
            "spacing": spacing,
        },
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        face_roles=face_roles,
        history_complete=history_complete,
        missing_phases=missing_phases,
    )
    return TrackedShapeResult(result=result, batch=batch)


def tracked_circular_pattern(
    body: Any,
    axis_origin: tuple[float, float, float],
    axis_dir: tuple[float, float, float],
    count: int,
    *,
    radius_mm: float = 0.0,
    start_angle_deg: float = 0.0,
    rotate_copies: bool = True,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Create ``count`` copies on a circle and fuse them with history capture.

    Each copy is rotate-then-translate transformed; per-face history records
    source face -> copy face, then all instances are fused with BOPAlgo_FUSE.
    """
    import cadquery as cq

    scope = scope or TopologyCaptureScope()
    relations: list[LiveEvolutionRelation] = []
    face_roles: dict[str, FaceRoleSpec] = {}

    if count < 2:
        batch = LiveEvolutionBatch(
            scope=scope, builder_kind="CircularPattern",
            result_shape=body.wrapped if hasattr(body, "wrapped") else body,
            context_shape=body.wrapped if hasattr(body, "wrapped") else body,
            relations=[], history_complete=True,
        )
        return TrackedShapeResult(result=cq.Shape.cast(body) if hasattr(body, "wrapped") else body, batch=batch)

    instance_shapes: list[Any] = [body.wrapped if hasattr(body, "wrapped") else body]

    for i in range(1, count):
        angle_deg = start_angle_deg + i * (360.0 / count)
        angle = math.radians(angle_deg)
        x = radius_mm * math.cos(angle)
        y = radius_mm * math.sin(angle)

        rot = gp_Trsf()
        rot.SetRotation(gp_Ax1(gp_Pnt(*axis_origin), gp_Dir(*axis_dir)), angle)
        combined = gp_Trsf()
        if rotate_copies:
            combined.SetTranslation(gp_Vec(x, y, 0.0))  # combined = T
            combined.Multiply(rot)  # T * R: rotate first, then translate
        else:
            combined.SetTranslation(gp_Vec(x, y, 0.0))

        builder = BRepBuilderAPI_Transform(instance_shapes[0], combined)
        builder.Build()
        if not builder.IsDone():
            raise RuntimeError(f"circular_pattern instance {i} transform failed")
        copy_shape = builder.Shape()
        instance_shapes.append(copy_shape)

        for fi, face in enumerate(cq.Shape.cast(instance_shapes[0]).Faces()):
            mod_list = builder.Modified(face.wrapped)
            mod_shapes = tuple(mod_list)
            if mod_shapes:
                relations.append(LiveEvolutionRelation(
                    relation_id=f"{scope.node_id}/circular/inst_{i}/face_{fi}",
                    operation_id=scope.node_id,
                    kind=EvolutionKind.MODIFIED,
                    entity_kind=TopologyEntityKind.FACE,
                    source_key=f"face_{fi}_inst_{i}",
                    old_shape=face.wrapped,
                    new_shapes=mod_shapes,
                    proof=ProofClass.EXACT_KERNEL_HISTORY,
                ))

    # Fuse all instances with history.
    from OCP.BOPAlgo import BOPAlgo_BOP, BOPAlgo_FUSE
    fused = instance_shapes[0]
    history_complete = True
    missing_phases: list[str] = []
    for si, s in enumerate(instance_shapes[1:]):
        fuser = BOPAlgo_BOP()
        fuser.SetOperation(BOPAlgo_FUSE)
        fuser.SetToFillHistory(True)
        fuser.AddArgument(fused)
        fuser.AddTool(s)
        fuser.Perform()
        new_fused = fuser.Shape()
        fhist = fuser.History()
        if fhist is not None:
            has_gen = False
            has_mod = False
            for fi, face in enumerate(cq.Shape.cast(fused).Faces()):
                g, m = _capture_fuse_face(relations, scope, fhist, face, si, fi, "arg", new_fused)
                has_gen = has_gen or g
                has_mod = has_mod or m
            for fi, face in enumerate(cq.Shape.cast(s).Faces()):
                g, m = _capture_fuse_face(relations, scope, fhist, face, si, fi, "tool", new_fused)
                has_gen = has_gen or g
                has_mod = has_mod or m
            if not has_gen and not has_mod:
                history_complete = False
                missing_phases.append(f"fuse_step_{si}_no_history")
        else:
            history_complete = False
            missing_phases.append(f"fuse_step_{si}")
        fused = new_fused

    result = cq.Shape.cast(fused)

    # Same completeness contract as linear_pattern: every seed face must compose
    # forward through the arg chain to a final output (or be explicitly deleted).
    graph = HistoryGraph.from_relations(relations)
    composer = HistoryComposer()
    for fi, face in enumerate(body.Faces()):
        finals = composer.compose(graph, [face.wrapped], follow_tokens=("_arg_",))
        deleted = graph.successors(
            face.wrapped,
            follow_kinds=(EvolutionKind.DELETED,),
            follow_tokens=("_arg_",),
        )
        if not finals and not deleted:
            history_complete = False
            missing_phases.append(f"face_{fi}_not_composable")
        for j, final_shape in enumerate(finals):
            role_key = f"face_{fi}/final/{j}"
            face_roles[role_key] = FaceRoleSpec(
                role_key=role_key,
                shape=final_shape,
                source_shape=face.wrapped,
                first_evolution=EvolutionKind.MODIFIED,
                source_ref=make_source_ref(
                    scope.component_id, scope.node_id, f"face_{fi}",
                ),
            )

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="CircularPattern",
        builder_options={"count": count, "radius_mm": radius_mm, "start_angle_deg": start_angle_deg, "rotate_copies": rotate_copies},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        face_roles=face_roles,
        history_complete=history_complete,
        missing_phases=missing_phases,
    )
    return TrackedShapeResult(result=result, batch=batch)
