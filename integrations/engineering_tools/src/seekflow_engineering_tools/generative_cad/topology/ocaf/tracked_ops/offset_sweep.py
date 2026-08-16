"""Tracked shell / sweep / loft — offset and swept-solid history capture."""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    LiveEvolutionBatch,
    LiveEvolutionRelation,
    ProofClass,
    TopologyCaptureScope,
    TopologyEntityKind,
    TrackedShapeResult,
    FaceRoleSpec,
    make_relation_key, make_source_ref,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops._carry import (
    all_faces_accounted,
    carry_unchanged_faces,
    find_partner_face,
)


def _capture_generated_modified(
    relations: list[LiveEvolutionRelation],
    scope: TopologyCaptureScope,
    builder: Any,
    input_shape: Any,
    source_key: str,
    *,
    face_roles: dict[str, FaceRoleSpec] | None = None,
    component_id: str = "",
    feature_id: str = "",
) -> None:
    gen_list = builder.Generated(input_shape)
    gen_shapes = tuple(gen_list)
    if gen_shapes:
        relations.append(LiveEvolutionRelation(
            relation_id=f"{scope.node_id}/{source_key}/gen/{len(relations)}",
            operation_id=scope.node_id,
            kind=EvolutionKind.GENERATED,
            entity_kind=TopologyEntityKind.FACE,
            source_key=source_key,
            old_shape=input_shape,
            new_shapes=gen_shapes,
            proof=ProofClass.EXACT_KERNEL_HISTORY,
            relation_key=make_relation_key(
                component_id, feature_id, source_key,
                EvolutionKind.GENERATED, relation_role="sweep",
            ) if component_id and feature_id else None,
        ))
        if face_roles is not None:
            for j, new_shape in enumerate(gen_shapes):
                role_key = f"{source_key}/gen/{j}"
                face_roles[role_key] = FaceRoleSpec(
                    role_key=role_key,
                    shape=new_shape,
                    source_shape=input_shape,
                    first_evolution=EvolutionKind.GENERATED,
                    source_ref=make_source_ref(
                        component_id, feature_id, source_key,
                    ) if component_id and feature_id else None,
                )

    mod_list = builder.Modified(input_shape)
    mod_shapes = tuple(mod_list)
    if mod_shapes:
        relations.append(LiveEvolutionRelation(
            relation_id=f"{scope.node_id}/{source_key}/mod/{len(relations)}",
            operation_id=scope.node_id,
            kind=EvolutionKind.MODIFIED,
            entity_kind=TopologyEntityKind.FACE,
            source_key=source_key,
            old_shape=input_shape,
            new_shapes=mod_shapes,
            proof=ProofClass.EXACT_KERNEL_HISTORY,
            relation_key=make_relation_key(
                component_id, feature_id, source_key,
                EvolutionKind.MODIFIED, relation_role="sweep",
            ) if component_id and feature_id else None,
        ))
        if face_roles is not None:
            for j, new_shape in enumerate(mod_shapes):
                role_key = f"{source_key}/mod/{j}"
                face_roles[role_key] = FaceRoleSpec(
                    role_key=role_key,
                    shape=new_shape,
                    source_shape=input_shape,
                    first_evolution=EvolutionKind.MODIFIED,
                    source_ref=make_source_ref(
                        component_id, feature_id, source_key,
                    ) if component_id and feature_id else None,
                )


def tracked_shell(
    body: Any,
    thickness: float,
    *,
    faces_to_remove: list[Any] | None = None,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Shell a solid via BRepOffsetAPI_MakeThickSolid with history capture."""
    import cadquery as cq
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from OCP.GeomAbs import GeomAbs_JoinType
    from OCP.TopTools import TopTools_ListOfShape

    scope = scope or TopologyCaptureScope()
    occ_faces = TopTools_ListOfShape()
    for f in (faces_to_remove or []):
        occ_faces.Append(f.wrapped if hasattr(f, "wrapped") else f)

    builder = BRepOffsetAPI_MakeThickSolid()
    builder.MakeThickSolidByJoin(
        body.wrapped, occ_faces, thickness, 0.0001,
        Intersection=True, Join=GeomAbs_JoinType.GeomAbs_Arc,
    )
    builder.Build()
    if not builder.IsDone():
        raise RuntimeError("BRepOffsetAPI_MakeThickSolid failed")

    faces = list(faces_to_remove or [])
    if faces:
        result = cq.Shape.cast(builder.Shape())
    else:
        # Match CadQuery's watertight-solid construction for the no-opening case.
        s1 = cq.Shape.cast(builder.Shape()).Shells()[0].wrapped
        s2 = body.Shells()[0].wrapped
        if thickness > 0:
            solid = BRepBuilderAPI_MakeSolid(s1, s2)
        else:
            solid = BRepBuilderAPI_MakeSolid(s2, s1)
        result = cq.Solid(solid.Shape()).fix()

    relations: list[LiveEvolutionRelation] = []
    face_roles: dict[str, FaceRoleSpec] = {}
    face_roles: dict[str, FaceRoleSpec] = {}
    for i, face in enumerate(body.Faces()):
        _capture_generated_modified(
            relations, scope, builder, face.wrapped, f"face_{i}",
            face_roles=face_roles,
            component_id=scope.component_id, feature_id=scope.node_id,
        )

    carry_unchanged_faces(relations, scope, result.wrapped, list(body.Faces()), "shell")
    for i, face in enumerate(body.Faces()):
        role_key = f"face_{i}/carry"
        if any(key == role_key for key in face_roles):
            continue
        partner = find_partner_face(result.wrapped, face.wrapped)
        if partner is not None:
            face_roles[role_key] = FaceRoleSpec(
                role_key=role_key,
                shape=partner,
                source_shape=face.wrapped,
                first_evolution=EvolutionKind.MODIFIED,
            )
    history_complete = all_faces_accounted(relations, list(body.Faces()))

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="BRepOffsetAPI_MakeThickSolid",
        builder_options={"thickness": thickness},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        face_roles=face_roles,
        history_complete=history_complete,
        missing_phases=[] if history_complete else ["some input faces are not accounted for"],
    )
    return TrackedShapeResult(result=result, batch=batch)


def tracked_sweep(
    profile: Any,
    path_wire: Any,
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Sweep a face/wire profile along a wire via BRepOffsetAPI_MakePipe."""
    import cadquery as cq
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.TopAbs import TopAbs_WIRE

    scope = scope or TopologyCaptureScope()
    profile_wrapped = profile.wrapped if hasattr(profile, "wrapped") else profile
    if profile_wrapped.ShapeType() == TopAbs_WIRE:
        fb = BRepBuilderAPI_MakeFace(profile_wrapped, False)
        fb.Build()
        profile_wrapped = fb.Face()

    builder = BRepOffsetAPI_MakePipe(path_wire, profile_wrapped)
    builder.Build()
    if not builder.IsDone():
        raise RuntimeError("BRepOffsetAPI_MakePipe failed")

    result = cq.Shape.cast(builder.Shape())
    relations: list[LiveEvolutionRelation] = []
    face_roles: dict[str, FaceRoleSpec] = {}
    if profile_wrapped.ShapeType() == 5:  # TopAbs_FACE
        _capture_generated_modified(
            relations, scope, builder, profile_wrapped, "profile",
            face_roles=face_roles,
            component_id=scope.component_id, feature_id=scope.node_id,
        )
    else:
        # Wire/edge profile: capture per edge.
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_EDGE
        exp = TopExp_Explorer(profile_wrapped, TopAbs_EDGE)
        idx = 0
        while exp.More():
            _capture_generated_modified(
                relations, scope, builder, exp.Current(), f"edge_{idx}",
                face_roles=face_roles,
                component_id=scope.component_id, feature_id=scope.node_id,
            )
            idx += 1
            exp.Next()
    history_complete = len(relations) > 0

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="BRepOffsetAPI_MakePipe",
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        face_roles=face_roles,
        history_complete=history_complete,
        missing_phases=[] if history_complete else ["no profile history captured"],
    )
    return TrackedShapeResult(result=result, batch=batch)


def tracked_loft(
    section_wires: list[Any],
    *,
    ruled: bool = False,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Loft through section wires via BRepOffsetAPI_ThruSections."""
    import cadquery as cq
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE

    scope = scope or TopologyCaptureScope()
    builder = BRepOffsetAPI_ThruSections(True, ruled)
    for w in section_wires:
        builder.AddWire(w.wrapped if hasattr(w, "wrapped") else w)
    builder.Build()
    if not builder.IsDone():
        raise RuntimeError("BRepOffsetAPI_ThruSections failed")

    result = cq.Shape.cast(builder.Shape())
    relations: list[LiveEvolutionRelation] = []
    face_roles: dict[str, FaceRoleSpec] = {}
    for i, w in enumerate(section_wires):
        ww = w.wrapped if hasattr(w, "wrapped") else w
        exp = TopExp_Explorer(ww, TopAbs_EDGE)
        idx = 0
        while exp.More():
            _capture_generated_modified(
                relations, scope, builder, exp.Current(), f"section_{i}_edge_{idx}",
                face_roles=face_roles,
                component_id=scope.component_id, feature_id=scope.node_id,
            )
            idx += 1
            exp.Next()
    history_complete = len(relations) > 0

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="BRepOffsetAPI_ThruSections",
        builder_options={"ruled": ruled},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        face_roles=face_roles,
        history_complete=history_complete,
        missing_phases=[] if history_complete else ["no section history captured"],
    )
    return TrackedShapeResult(result=result, batch=batch)
