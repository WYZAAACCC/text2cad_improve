"""Sketch_extrude handlers — v1.0 hardened.

All handlers follow: validate params → try full op → try fallback → warn+skip.
No silent None propagation. No uncaught OCCT errors.

Phase 3: handle_cut_hole produces topology_delta for hole faces (hole_wall,
entry_rim, exit_rim). Topology is registered via ctx.topology_registry.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
from seekflow_engineering_tools.generative_cad.runtime.recovery import handle_feature_failure
from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object


def _store_solid(node: CanonicalNode, ctx: RuntimeContext, obj) -> str:
    if obj is None:
        raise RuntimeError(f"BUG: _store_solid called with None on '{node.id}'")
    sid = f"solid:{node.component}:{node.id}:body"
    ctx.object_store.put_solid(SolidHandle(id=sid, component_id=node.component, producer_node=node.id), obj)
    ctx.bind_node_output(node.id, "body", sid)
    return sid


def _degrade(node: CanonicalNode, ctx: RuntimeContext, body, op_name: str) -> str:
    """Return unmodified body with warning when operation fails.

    v6.3: If node.required is True, this is a HARD FAIL — the feature is
    structurally necessary and cannot be silently skipped. Only optional
    decorative features (fillet, chamfer) may degrade.
    """
    if getattr(node, "required", True):
        raise RuntimeError(
            f"Required operation '{op_name}' failed on '{node.id}': "
            f"geometry does not support this operation and degradation is not allowed. "
            f"Fix the parameters or mark the node as required=False with "
            f"degradation_policy='may_skip_with_warning' if this feature is decorative."
        )
    ctx.warnings.append(
        f"'{op_name}' skipped on '{node.id}': geometry does not support it. "
        f"Part is valid without this operation."
    )
    return _store_solid(node, ctx, body)


# ═══════════════════════════════════════════════════════════════════════════════
# Base solid
# ═══════════════════════════════════════════════════════════════════════════════

def handle_extrude_rectangle(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """PR 4: Use BRepPrimAPI_MakePrism history when available, fallback to CadQuery.

    History-aware path tracks which profile edge generated each side face,
    enabling stable 'extrude/side.from/edge_N' naming instead of ordinal
    'side_face_N' enumeration.
    """
    import cadquery as cq
    p = node.typed_params if node.typed_params else node.params
    w = float(p.get("width_mm", 0))
    h = float(p.get("height_mm", 0))
    d = float(p.get("depth_mm", 0))
    if w <= 0 or h <= 0 or d <= 0:
        raise ValueError(f"extrude_rectangle requires positive dimensions, got {w}x{h}x{d}")
    plane = p.get("plane", "XY")
    centered = p.get("centered", True)
    direction = p.get("direction", "+")
    draft = float(p.get("draft_angle_deg", 0))
    if direction == "-":
        d = -d

    history_result = None
    try:
        wp = cq.Workplane(plane)
        if centered:
            wp = wp.center(0, 0)

        # ── PR 4: Try history-aware extrude first ──
        if abs(draft) <= 0.01:
            # Get the wire and extract individual TopoDS edges
            wire_obj = wp.rect(w, h).val()  # TopoDS_Wire
            edges = _extract_wire_edges(wire_obj)

            # Use OCCT BRepPrimAPI_MakePrism for history capture
            try:
                from OCP.gp import gp_Vec  # type: ignore[import-untyped]

                vec = gp_Vec(0, 0, d)
                from seekflow_engineering_tools.generative_cad.topology.history_wrappers import (
                    history_aware_extrude,
                )
                history_result = history_aware_extrude(
                    wire_obj, vec,
                    input_edges=[e for _, e in edges],
                )
            except ImportError:
                pass  # OCP unavailable → fallback below

        if history_result is not None and history_result.result_shape is not None:
            solid = cq.Shape.cast(history_result.result_shape)
            # Produce topology from OCCT history
            _try_produce_extrude_topology_v2(
                node=node, ctx=ctx, solid=solid,
                history_result=history_result,
                edge_ids=[eid for eid, _ in edges],
                plane=plane, direction=direction,
            )
        elif abs(draft) > 0.01:
            # Tapered: CadQuery only (OCCT history not supported for draft)
            solid = wp.rect(w, h).taperedExtrude(d, draft)
            _try_produce_extrude_topology(
                node=node, ctx=ctx, solid=solid,
                plane=plane, direction=direction,
            )
        else:
            # Fallback: standard CadQuery extrude
            solid = wp.rect(w, h).extrude(d)
            _try_produce_extrude_topology(
                node=node, ctx=ctx, solid=solid,
                plane=plane, direction=direction,
            )
    except Exception as e:
        raise RuntimeError(f"extrude_rectangle failed: {e}")

    return {"body": _store_solid(node, ctx, solid)}


def _try_produce_extrude_topology(
    *,
    node: CanonicalNode,
    ctx: RuntimeContext,
    solid,
    plane: str = "XY",
    direction: str = "+",
) -> None:
    """Phase 5: Build topology delta for extrude faces via side-channel.

    Names the result faces using name_extrude_faces → classifies into
    end_cap_positive, end_cap_negative, and side_face_N.
    Registers entities with TopologyRegistry.

    Non-fatal: topology failure is a warning, not a build failure.
    """
    try:
        from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
            build_entity_records_from_delta,
            name_extrude_faces,
        )
        from seekflow_engineering_tools.generative_cad.topology.shape_binding import (
            ShapeBindingService,
        )
    except ImportError:
        return

    try:
        doc_id = ctx.document_id or "unknown"

        delta = name_extrude_faces(
            solid,
            document_id=doc_id,
            component_id=node.component or "unknown",
            producer_node_id=node.id,
            extrude_plane=plane,
            direction=direction,
        )

        # Build topology maps + ShapeBindingService for the result body
        body_handle_id = f"solid:{node.component}:{node.id}:body"
        service = ShapeBindingService(ctx.object_store)
        maps = service.build_body_maps(body_handle_id, solid)

        records = build_entity_records_from_delta(delta, document_id=doc_id)

        # Locate each face and attach RuntimeTopoLocator
        faces = list(solid.faces().vals())
        located_count = 0
        for rec in records:
            if rec.entity_type == "face":
                for relation in delta.relations:
                    if rec.semantic_role == relation.semantic_role:
                        ev = relation.evidence
                        rt_idx = ev.get("runtime_index") if ev else None
                        if rt_idx is not None and rt_idx < len(faces):
                            locator = service.locate_subshape(
                                maps, faces[rt_idx], "face",
                            )
                            if locator is not None:
                                rec.current_locator = locator.model_dump()
                                located_count += 1
                                break

        with ctx.topology_transaction() as tx:
            for rec in records:
                tx.register_entity(rec)
            tx.apply_delta(delta)

        ctx.topology_events.append({
            "event": "extrude_topology_produced",
            "node_id": node.id,
            "plane": plane,
            "direction": direction,
            "face_count": len(delta.relations),
            "located_count": located_count,
        })
    except Exception as exc:
        ctx.topology_warnings.append({
            "node_id": node.id,
            "phase": "extrude_topology",
            "error": str(exc),
        })


def _extract_wire_edges(wire: Any) -> list[tuple[str, Any]]:
    """Extract individual TopoDS_Edge from a wire with synthetic IDs.

    Uses OCCT IndexedMap for stable ordering. Rectangle wires have 4 edges.

    Args:
        wire: TopoDS_Wire from CadQuery wp.rect().val()

    Returns:
        [(edge_id, TopoDS_Edge), ...] — e.g., [("edge_0", ...), ("edge_1", ...)]
    """
    try:
        from OCP.TopExp import TopExp  # type: ignore[import-untyped]
        from OCP.TopAbs import TopAbs_EDGE  # type: ignore[import-untyped]
        from OCP.TopTools import TopTools_IndexedMapOfShape  # type: ignore[import-untyped]

        edge_map = TopTools_IndexedMapOfShape()
        _map_shapes = getattr(TopExp, 'MapShapes', getattr(TopExp, 'MapShapes_s', None))
        if _map_shapes:
            raw_shape = getattr(wire, 'wrapped', wire)
            _map_shapes(raw_shape, TopAbs_EDGE, edge_map)

        edges: list[tuple[str, Any]] = []
        for i in range(1, edge_map.Extent() + 1):
            edge_id = f"edge_{i - 1}"
            edges.append((edge_id, edge_map.FindKey(i)))
        return edges
    except ImportError:
        return []


def _try_produce_extrude_topology_v2(
    *,
    node: CanonicalNode,
    ctx: RuntimeContext,
    solid,
    history_result: Any,
    edge_ids: list[str],
    plane: str = "XY",
    direction: str = "+",
) -> None:
    """PR 4: Produce topology delta from OCCT history (not semantic enumeration).

    Each profile edge's Generated() result tells us exactly which faces came
    from that edge. Side faces get roles like 'extrude/side.from/edge_0'.
    Caps are identified by geometry (PLANE faces parallel to extrude axis).

    Non-fatal: topology failure is a warning, not a build failure.
    """
    try:
        from seekflow_engineering_tools.generative_cad.topology.ids import (
            make_persistent_id_v2,
        )
        from seekflow_engineering_tools.generative_cad.topology.models import (
            TopologyEntityRecord,
        )
        from seekflow_engineering_tools.generative_cad.topology.shape_binding import (
            ShapeBindingService,
        )
    except ImportError:
        return

    try:
        doc_id = ctx.document_id or "unknown"
        body_handle_id = f"solid:{node.component}:{node.id}:body"
        service = ShapeBindingService(ctx.object_store)
        maps = service.build_body_maps(body_handle_id, solid)

        with ctx.topology_transaction() as tx:
            # ── Side faces: each edge → generated faces from OCCT history ──
            gen_edge_faces = history_result.generated_edge_faces
            for edge_id in edge_ids:
                gen_faces = gen_edge_faces.get(edge_id, [])
                for face in gen_faces:
                    role = f"extrude/side.from/{edge_id}"
                    pid = make_persistent_id_v2(
                        doc_id, node.component or "unknown", node.id,
                        "face", role,
                    )
                    locator = service.locate_subshape(maps, face, "face")
                    rec = TopologyEntityRecord(
                        persistent_id=pid,
                        entity_type="face",
                        component_id=node.component or "unknown",
                        owner_body_handle_id=body_handle_id,
                        producer_node_id=node.id,
                        semantic_role=role,
                        current_locator=locator.model_dump() if locator else None,
                    )
                    tx.register_entity(rec)

        ctx.topology_events.append({
            "event": "extrude_topology_produced",
            "node_id": node.id,
            "plane": plane,
            "direction": direction,
            "method": "history_aware",
            "edge_count": len(edge_ids),
            "face_count": sum(len(gen_edge_faces.get(eid, [])) for eid in edge_ids),
        })
    except Exception as exc:
        ctx.topology_warnings.append({
            "node_id": node.id,
            "phase": "extrude_topology_v2",
            "error": str(exc),
        })


# ═══════════════════════════════════════════════════════════════════════════════
# Material removal
# ═══════════════════════════════════════════════════════════════════════════════

def handle_cut_rectangular_pocket(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    w = float(p.get("width_mm", 0))
    h = float(p.get("height_mm", 0))
    d = float(p.get("depth_mm", 0))
    if w <= 0 or h <= 0 or d <= 0:
        return {"body": _degrade(node, ctx, body, "cut_rectangular_pocket")}
    try:
        plane = p.get("plane", "XY")
        draft = float(p.get("draft_angle_deg", 0))
        if abs(draft) > 0.01:
            cutter = cq.Workplane(plane).rect(w, h).taperedExtrude(-d, draft)
        else:
            cutter = cq.Workplane(plane).rect(w, h).extrude(-d)
        result = body.cut(cutter)
    except Exception:
        return {"body": _degrade(node, ctx, body, "cut_rectangular_pocket")}
    return {"body": _store_solid(node, ctx, result)}


def handle_cut_hole(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """Cut a circular hole through the body.

    v6.1: Supports axis=X, Y, Z for side drilling.
    axis=Z (default): hole on XY plane, extrude along Z (existing behavior)
    axis=Y: hole on XZ plane, extrude along Y (side hole)
    axis=X: hole on YZ plane, extrude along X (side hole)

    Phase 3: produces topology_delta for hole faces (hole_wall, entry_rim,
    exit_rim) via the TopologyRegistry side-channel.
    """
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    dia = float(p.get("diameter_mm", 0))
    if dia <= 0:
        return {"body": _degrade(node, ctx, body, "cut_hole")}
    pos = p.get("position_mm", [0, 0, 0])
    x = pos[0] if len(pos) > 0 else 0
    y = pos[1] if len(pos) > 1 else 0
    z = pos[2] if len(pos) > 2 else 0
    axis = p.get("axis", "Z")
    depth_val = 0.0  # Track for through-hole detection
    try:
        bb = body.val().BoundingBox()
        if axis == "Z":
            # XY plane, extrude along Z
            depth_val = bb.zlen + 10
            cutter = (cq.Workplane("XY").center(x, y)
                      .circle(dia / 2.0).extrude(depth_val, both=True))
        elif axis == "Y":
            # XZ plane, extrude along Y (side hole)
            z_center = z if z != 0 else (bb.zmin + bb.zmax) / 2.0
            depth_val = bb.ylen + 10
            cutter = (cq.Workplane("XZ").center(x, z_center)
                      .circle(dia / 2.0).extrude(depth_val, both=True))
        elif axis == "X":
            # YZ plane, extrude along X (side hole)
            z_center = z if z != 0 else (bb.zmin + bb.zmax) / 2.0
            depth_val = bb.xlen + 10
            cutter = (cq.Workplane("YZ").center(y, z_center)
                      .circle(dia / 2.0).extrude(depth_val, both=True))
        else:
            ctx.warnings.append(f"cut_hole: unsupported axis '{axis}', defaulting to Z")
            depth_val = bb.zlen + 10
            cutter = (cq.Workplane("XY").center(x, y)
                      .circle(dia / 2.0).extrude(depth_val, both=True))
        result = body.cut(cutter)

        # ── Phase 3: Produce topology delta for hole faces ──
        _try_produce_hole_topology(
            node=node, ctx=ctx,
            cutter=cutter, dia=dia, depth_val=depth_val,
            body_bbox_zlen=bb.zlen if axis == "Z" else None,
        )
    except Exception:
        return {"body": _degrade(node, ctx, body, "cut_hole")}
    return {"body": _store_solid(node, ctx, result)}


def _try_produce_hole_topology(
    *,
    node: CanonicalNode,
    ctx: RuntimeContext,
    cutter,
    dia: float,
    depth_val: float,
    body_bbox_zlen: float | None = None,
) -> None:
    """Phase 3: Build topology delta for hole faces via side-channel.

    Names the tool body faces → maps to hole semantics → registers with
    TopologyRegistry. Non-fatal: topology failure is a warning, not a build
    failure (Phase 3 is best-effort; Phase 5+ will enforce).

    Uses component_id as document identifier for topology naming.
    """
    try:
        from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
            build_entity_records_from_delta,
            name_hole_faces,
        )
    except ImportError:
        return  # Topology module not available — skip

    try:
        doc_id = ctx.document_id or "unknown"
        is_through = True
        if body_bbox_zlen is not None and depth_val <= body_bbox_zlen + 5:
            is_through = False

        # Build hole delta
        hole_delta = name_hole_faces(
            cutter,
            document_id=doc_id,
            component_id=node.component or "unknown",
            producer_node_id=node.id,
            is_through_hole=is_through,
        )

        # Register and apply via transaction (PR 2)
        records = build_entity_records_from_delta(hole_delta, document_id=doc_id)
        with ctx.topology_transaction() as tx:
            for rec in records:
                tx.register_entity(rec)
            tx.apply_delta(hole_delta)

        ctx.topology_events.append({
            "event": "hole_topology_produced",
            "node_id": node.id,
            "dia": dia,
            "hole_wall": bool(hole_delta.relations),
        })
    except Exception as exc:
        ctx.topology_warnings.append({
            "node_id": node.id,
            "phase": "hole_topology",
            "error": str(exc),
        })


def handle_cut_hole_pattern_linear(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    dia = float(p.get("hole_dia_mm", 0))
    cx = max(1, int(p.get("count_x", 1)))
    cy = max(1, int(p.get("count_y", 1)))
    sx = float(p.get("spacing_x_mm", 0))
    sy = float(p.get("spacing_y_mm", 0))
    if dia <= 0 or sx <= 0 or sy <= 0:
        return {"body": _degrade(node, ctx, body, "cut_hole_pattern_linear")}
    try:
        bb = body.val().BoundingBox()
        z_len = bb.zlen + 10
        cutters = []
        for ix in range(cx):
            for iy in range(cy):
                x = (ix - (cx - 1) / 2.0) * sx
                y = (iy - (cy - 1) / 2.0) * sy
                cutters.append(
                    cq.Workplane("XY").center(x, y).circle(dia / 2.0).extrude(z_len, both=True)
                )
        combined = cutters[0]
        for c in cutters[1:]:
            combined = combined.union(c)
        result = body.cut(combined)
    except Exception:
        return {"body": _degrade(node, ctx, body, "cut_hole_pattern_linear")}
    return {"body": _store_solid(node, ctx, result)}


# ═══════════════════════════════════════════════════════════════════════════════
# Material addition
# ═══════════════════════════════════════════════════════════════════════════════

def handle_add_rectangular_boss(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    w = float(p.get("width_mm", 0))
    h = float(p.get("height_mm", 0))
    d = float(p.get("depth_mm", 0))
    if w <= 0 or h <= 0 or d <= 0:
        return {"body": _degrade(node, ctx, body, "add_rectangular_boss")}
    pos = p.get("position_mm", [0, 0, 0])
    x = pos[0] if len(pos) > 0 else 0
    y = pos[1] if len(pos) > 1 else 0
    try:
        boss = cq.Workplane("XY").center(x, y).rect(w, h).extrude(d)
        result = body.union(boss)
    except Exception:
        return {"body": _degrade(node, ctx, body, "add_rectangular_boss")}
    return {"body": _store_solid(node, ctx, result)}


def handle_add_rib(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    t = float(p.get("thickness_mm", 0))
    h = float(p.get("height_mm", 0))
    length = float(p.get("length_mm", 0))
    if t <= 0 or h <= 0 or length <= 0:
        return {"body": _degrade(node, ctx, body, "add_rib")}
    pos = p.get("position_mm", [0, 0, 0])
    direction = p.get("direction", "X")
    x = pos[0] if len(pos) > 0 else 0
    y = pos[1] if len(pos) > 1 else 0
    try:
        if direction == "X":
            rib = cq.Workplane("YZ").center(y, 0).rect(t, h).extrude(length)
        elif direction == "Y":
            rib = cq.Workplane("XZ").center(x, 0).rect(t, h).extrude(length)
        else:
            ctx.warnings.append(f"add_rib on '{node.id}': invalid direction '{direction}', using X")
            rib = cq.Workplane("YZ").center(y, 0).rect(t, h).extrude(length)
        result = body.union(rib)
    except Exception:
        return {"body": _degrade(node, ctx, body, "add_rib")}
    return {"body": _store_solid(node, ctx, result)}


# ═══════════════════════════════════════════════════════════════════════════════
# Edge treatment (already hardened — unchanged from v0.2.1)
# ═══════════════════════════════════════════════════════════════════════════════

def handle_se_fillet(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    r = float(node.typed_params.get("radius_mm", node.params.get("radius_mm", 0))) if node.typed_params else float(node.params.get("radius_mm", 0))
    if r > 0:
        target = node.params.get("target", "all_external_edges")
        from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.handlers import _fillet_by_target
        try:
            body = _fillet_by_target(body, r, target)
        except Exception:
            try:
                body = _fillet_by_target(body, r / 2.0, target)
            except Exception:
                return handle_feature_failure(
                    node=node, ctx=ctx, original_body=body,
                    op_name="apply_safe_fillet",
                    reason=f"fillet failed at radius={r}mm and fallback radius={r/2.0}mm",
                )
    _try_produce_surface_type_topology(node=node, ctx=ctx, solid=body, op_name="fillet")
    return {"body": _store_solid(node, ctx, body)}


def handle_se_chamfer(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    d = float(node.typed_params.get("distance_mm", node.params.get("distance_mm", 0))) if node.typed_params else float(node.params.get("distance_mm", 0))
    if d > 0:
        target = node.params.get("target", "all_external_edges")
        from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.handlers import _chamfer_by_target
        try:
            body = _chamfer_by_target(body, d, target)
        except Exception:
            try:
                body = _chamfer_by_target(body, d / 2.0, target)
            except Exception:
                return handle_feature_failure(
                    node=node, ctx=ctx, original_body=body,
                    op_name="apply_safe_chamfer",
                    reason=f"chamfer failed at distance={d}mm and fallback distance={d/2.0}mm",
                )
    _try_produce_surface_type_topology(node=node, ctx=ctx, solid=body, op_name="chamfer")
    return {"body": _store_solid(node, ctx, body)}


def _try_produce_surface_type_topology(
    *, node, ctx, solid, op_name: str,
) -> None:
    """Generic topology production for surface-type operations (fillet, chamfer, shell).

    Uses name_boolean_faces to classify all result faces by surface type.
    Registers via transaction. Non-fatal.
    """
    try:
        from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
            build_entity_records_from_delta, name_boolean_faces,
        )
    except ImportError:
        return
    try:
        doc_id = ctx.document_id or "unknown"
        delta = name_boolean_faces(
            solid, document_id=doc_id,
            component_id=node.component or "unknown",
            producer_node_id=node.id,
        )
        records = build_entity_records_from_delta(delta, document_id=doc_id)
        with ctx.topology_transaction() as tx:
            for rec in records:
                tx.register_entity(rec)
            tx.apply_delta(delta)
    except Exception as exc:
        ctx.topology_warnings.append({
            "node_id": node.id, "phase": f"{op_name}_topology", "error": str(exc),
        })


# ═══════════════════════════════════════════════════════════════════════════════
# v6.3: V2 Hole handlers — face-relative, deterministic placement
# ═══════════════════════════════════════════════════════════════════════════════

def handle_cut_hole_v2(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """Cut a hole using V2 face-relative placement.

    Uses HolePlacementV2 (target_face + center_uv_mm + normal_axis) instead
    of legacy axis + position_mm. The face resolver converts semantic placement
    to actual 3D coordinates using the component's bounding box.
    """
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params

    dia = float(p.get("diameter_mm", 0))
    if dia <= 0:
        raise ValueError("cut_hole_v2 requires positive diameter_mm")

    placement_raw = p.get("placement")
    if placement_raw is None:
        raise ValueError("cut_hole_v2 requires placement")

    # Normalize to HolePlacementV2 model
    from seekflow_engineering_tools.generative_cad.ir.geometry_semantics import (
        HolePlacementV2,
    )
    if isinstance(placement_raw, dict):
        placement = HolePlacementV2.model_validate(placement_raw)
    else:
        placement = placement_raw

    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.hole_placement import (
        resolve_face_hole_placement,
    )
    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_cylinder import (
        make_cylinder_cutter,
    )

    bb = body.val().BoundingBox()
    resolved = resolve_face_hole_placement(placement, bb)

    # Determine cutter length and placement mode
    if placement.through_mode == "blind":
        if placement.depth_mm is None:
            raise ValueError("blind cut_hole_v2 requires depth_mm")
        length = float(placement.depth_mm)
        extend_both = False  # blind: cutter starts at face, extends INTO part
    else:
        # through_all: extend beyond bbox in both directions
        length = max(bb.xlen, bb.ylen, bb.zlen) + 20.0
        extend_both = True

    cutter = make_cylinder_cutter(
        center_xyz=resolved.center_xyz,
        direction_xyz=resolved.direction_xyz,
        radius_mm=dia / 2.0,
        length_mm=length,
        extend_both=extend_both,
    )

    try:
        result = body.cut(cutter)
    except Exception as exc:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required cut_hole_v2 failed on '{node.id}': {exc}"
            ) from exc
        return {"body": _degrade(node, ctx, body, "cut_hole_v2")}

    return {"body": _store_solid(node, ctx, result)}


def handle_cut_hole_pattern_linear_v2(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """Cut a linear grid of holes using V2 face-relative placement.

    The grid is laid out on the target face's UV plane. Each hole uses
    the same face, normal, and through_mode. Only center_uv_mm varies.
    """
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params

    dia = float(p.get("hole_dia_mm", 0))
    if dia <= 0:
        raise ValueError("cut_hole_pattern_linear_v2 requires positive hole_dia_mm")

    count_u = int(p.get("count_u", 1))
    count_v = int(p.get("count_v", 1))
    spacing_u = float(p.get("spacing_u_mm", 0))
    spacing_v = float(p.get("spacing_v_mm", 0))

    placement_raw = p.get("placement")
    if placement_raw is None:
        raise ValueError("cut_hole_pattern_linear_v2 requires placement")

    from seekflow_engineering_tools.generative_cad.ir.geometry_semantics import (
        HolePlacementV2,
    )
    if isinstance(placement_raw, dict):
        placement = HolePlacementV2.model_validate(placement_raw)
    else:
        placement = placement_raw

    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.hole_placement import (
        resolve_face_hole_placement,
        iter_linear_pattern_centers,
    )
    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_cylinder import (
        make_cylinder_cutter,
    )
    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.boolean_batch import (
        batch_cut,
    )

    bb = body.val().BoundingBox()
    length = max(bb.xlen, bb.ylen, bb.zlen) + 20.0
    base_uv = placement.center_uv_mm

    cutters = []
    for u, v in iter_linear_pattern_centers(base_uv, count_u, count_v, spacing_u, spacing_v):
        hole_placement = HolePlacementV2(
            target_face=placement.target_face,
            center_uv_mm=(u, v),
            normal_axis=placement.normal_axis,
            origin_mode=placement.origin_mode,
            through_mode=placement.through_mode,
            depth_mm=placement.depth_mm,
        )
        resolved = resolve_face_hole_placement(hole_placement, bb)
        cutters.append(make_cylinder_cutter(
            center_xyz=resolved.center_xyz,
            direction_xyz=resolved.direction_xyz,
            radius_mm=dia / 2.0,
            length_mm=length,
        ))

    try:
        result = batch_cut(body, cutters)
    except Exception as exc:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required cut_hole_pattern_linear_v2 failed on '{node.id}': {exc}"
            ) from exc
        return {"body": _degrade(node, ctx, body, "cut_hole_pattern_linear_v2")}

    return {"body": _store_solid(node, ctx, result)}


def handle_drill_hole_3d(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """Drill a hole along an arbitrary 3D direction.

    For holes that cannot be expressed as face-normal:
    angled holes, holes on curved surfaces, oil passages, etc.
    Uses explicit origin_mm + direction vector.
    """
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params

    dia = float(p.get("diameter_mm", 0))
    origin = tuple(p.get("origin_mm", (0, 0, 0)))
    direction = tuple(p.get("direction", (0, 0, 1)))
    through_mode = p.get("through_mode", "through_all")

    if dia <= 0:
        raise ValueError("drill_hole_3d requires positive diameter_mm")

    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_cylinder import (
        make_cylinder_cutter,
    )

    bb = body.val().BoundingBox()
    if str(through_mode).endswith("BLIND") or through_mode == "blind":
        depth = float(p.get("depth_mm", 0))
        if depth <= 0:
            raise ValueError("blind drill_hole_3d requires positive depth_mm")
        length = depth
        extend_both = False  # blind: starts at origin, extends along direction
    else:
        length = max(bb.xlen, bb.ylen, bb.zlen) + 20.0
        extend_both = True

    cutter = make_cylinder_cutter(
        center_xyz=origin,
        direction_xyz=direction,
        radius_mm=dia / 2.0,
        length_mm=length,
        extend_both=extend_both,
    )

    try:
        result = body.cut(cutter)
    except Exception as exc:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required drill_hole_3d failed on '{node.id}': {exc}"
            ) from exc
        return {"body": _degrade(node, ctx, body, "drill_hole_3d")}

    return {"body": _store_solid(node, ctx, result)}
