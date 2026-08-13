"""Tracked Linear Pattern — N copies along direction, fused with per-instance history.

Each copy is made via BRepBuilderAPI_Transform. Per-face history tracks:
  instance_0: original faces
  instance_1..N-1: transformed faces (source_face → copy_face)

The final result is all instances fused via BOPAlgo_FUSE.
"""

from __future__ import annotations

from typing import Any

from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Trsf, gp_Vec

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind, TopologyEntityKind, ProofClass,
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation, TrackedShapeResult,
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
        history_complete=history_complete,
        missing_phases=missing_phases,
    )
    return TrackedShapeResult(result=result, batch=batch)
