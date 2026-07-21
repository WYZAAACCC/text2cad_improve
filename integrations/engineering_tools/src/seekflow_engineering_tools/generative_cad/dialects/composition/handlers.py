"""Composition dialect handlers — transform, pattern, boolean.

v1.0: hardened with input validation, degradation chains, and safe defaults.
All handlers follow the same pattern: validate → try full op → try fallback → warn+skip.
"""

from __future__ import annotations

import math
from typing import Any

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
from seekflow_engineering_tools.generative_cad.runtime.resolve import (
    resolve_input_object,
)


def _store_solid(node: CanonicalNode, ctx: RuntimeContext, obj) -> str:
    if obj is None:
        raise RuntimeError(
            f"BUG: _store_solid called with None on '{node.id}'. "
            f"This should never happen — handler must guard against None."
        )
    solid_id = f"solid:{node.component}:{node.id}:body"
    handle = SolidHandle(id=solid_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_solid(handle, obj)
    ctx.bind_node_output(node.id, "body", solid_id)
    return solid_id


def _get_feature_stable_ids(ctx: RuntimeContext) -> dict[str, str] | None:
    """Extract feature_stable_ids from the DesignIdentityContext if available."""
    dctx = getattr(ctx, 'design_identity_context', None)
    if dctx is not None:
        fids = getattr(dctx, 'feature_stable_ids', None)
        if fids:
            return fids
    return None


def _degraded_store(node: CanonicalNode, ctx: RuntimeContext, original_body, op_name: str) -> str:
    """Store original body when operation fails — logs warning, preserves geometry.

    v6.3: Required features hard fail — only optional/decorative features may degrade.
    """
    if getattr(node, "required", True):
        raise RuntimeError(
            f"Required operation '{op_name}' failed on '{node.id}': "
            f"operation cannot be skipped for required features. "
            f"Fix the parameters or mark the node as required=False."
        )
    ctx.warnings.append(
        f"'{op_name}' failed on '{node.id}': returning unmodified solid. "
        f"Part is valid without this operation."
    )
    return _store_solid(node, ctx, original_body)


# ═══════════════════════════════════════════════════════════════════════════════
# V3 Transform topology preservation
# ═══════════════════════════════════════════════════════════════════════════════


def _register_transform_topology_preservation(
    *, node, ctx, source_body, result_body, transform_op, transform_params,
) -> None:
    """Preserve topology identity across rigid-body transforms (Phase 3+15b).

    Rigid-body transforms (translate/rotate/place) preserve the IndexedMap
    structure — face N in the source body IS face N in the result body.
    We rebuild locators at the same position on the result body and update
    owner_body_handle_id, without geometric matching.
    """
    try:
        from seekflow_engineering_tools.generative_cad.topology.shape_binding import (
            ShapeBindingService,
        )
    except ImportError:
        return

    reg = ctx.topology_registry
    if reg.entity_count == 0:
        return

    service = ShapeBindingService(ctx.object_store)
    source_handle = f"solid:{node.component}:{node.id}:body"

    # Build maps for result body only (source body maps only needed to verify
    # that the position exists in the result — which it does for rigid transforms)
    res_raw = result_body.val().wrapped if hasattr(result_body, 'val') else result_body
    res_maps = service.build_body_maps(source_handle, res_raw)

    relocated = 0
    no_locator = 0
    with ctx.topology_transaction() as tx:
        staged = tx.staged
        for pid, rec in staged._entities.items():
            if rec.status != "active" or rec.entity_type != "face":
                continue

            # ── Update owner_body_handle_id: all active faces now belong to
            # the transformed body.  Rigid transforms don't change topology,
            # so every entity from the source body carries over.
            if rec.owner_body_handle_id != source_handle:
                rec.owner_body_handle_id = source_handle

            loc = rec.current_locator
            if loc is None:
                no_locator += 1
                continue
            src_pos = loc.get("indexed_map_position")
            if src_pos is None:
                continue

            # ── Rebuild locator at the same IndexedMap position on the result
            # body.  Rigid transforms preserve face ordering, so the face at
            # position N in the source is position N in the result.
            res_face = res_maps.face_map.get(src_pos)
            if res_face is None:
                continue
            new_locator = service.locate_subshape(res_maps, res_face, "face")
            if new_locator is not None:
                rec.current_locator = new_locator.model_dump()
                relocated += 1

            rec.evidence.append({
                "event": "relocated",
                "node_id": node.id,
                "transform": transform_op,
                "params": transform_params,
            })

    ctx.topology_events.append({
        "event": "transform_topology_preserved",
        "node_id": node.id,
        "transform": transform_op,
        "params": transform_params,
        "relocated": relocated,
        "no_locator": no_locator,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Transform handlers
# ═══════════════════════════════════════════════════════════════════════════════

def handle_translate_solid(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    vector = node.params.get("vector_mm", (0, 0, 0))
    if not (isinstance(vector, (list, tuple)) and len(vector) == 3):
        if getattr(node, "required", True):
            raise ValueError(
                f"required translate_solid on '{node.id}': "
                f"invalid vector_mm (expected 3D tuple, got {type(vector).__name__})"
            )
        ctx.warnings.append(f"translate_solid on '{node.id}': invalid vector, using (0,0,0)")
        vector = (0, 0, 0)
    if all(v == 0 for v in vector):
        if getattr(node, "required", True):
            ctx.warnings.append(
                f"translate_solid on '{node.id}': zero vector — no-op translation"
            )
        _register_transform_topology_preservation(
            node=node, ctx=ctx, source_body=body, result_body=body,
            transform_op="translate", transform_params={"vector_mm": (0, 0, 0)},
        )
        return {"body": _store_solid(node, ctx, body)}  # no-op
    try:
        result = body.translate(vector)
        _register_transform_topology_preservation(
            node=node, ctx=ctx, source_body=body, result_body=result,
            transform_op="translate", transform_params={"vector_mm": tuple(vector)},
        )
        return {"body": _store_solid(node, ctx, result)}
    except Exception as e:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required translate_solid failed on '{node.id}': {e}"
            ) from e
        ctx.warnings.append(f"translate_solid failed on '{node.id}': {e}")
        return {"body": _store_solid(node, ctx, body)}


def handle_rotate_solid(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    origin = node.params.get("axis_origin_mm", (0, 0, 0))
    axis_dir = node.params.get("axis_dir", (0, 0, 1))
    angle = float(node.params.get("angle_deg", 0))
    if angle == 0:
        if getattr(node, "required", True):
            ctx.warnings.append(
                f"rotate_solid on '{node.id}': angle=0deg — no-op rotation"
            )
        _register_transform_topology_preservation(
            node=node, ctx=ctx, source_body=body, result_body=body,
            transform_op="rotate", transform_params={"angle_deg": 0},
        )
        return {"body": _store_solid(node, ctx, body)}
    # Guard zero axis
    axis = tuple(float(x) for x in axis_dir) if isinstance(axis_dir, (list, tuple)) else (0, 0, 1)
    if all(v == 0 for v in axis):
        if getattr(node, "required", True):
            raise ValueError(
                f"required rotate_solid on '{node.id}': zero axis vector"
            )
        ctx.warnings.append(f"rotate_solid on '{node.id}': zero axis vector, skipping")
        return {"body": _store_solid(node, ctx, body)}
    try:
        result = body.rotate(origin, axis, angle)
        _register_transform_topology_preservation(
            node=node, ctx=ctx, source_body=body, result_body=result,
            transform_op="rotate",
            transform_params={"origin": origin, "axis": axis, "angle_deg": angle},
        )
        return {"body": _store_solid(node, ctx, result)}
    except Exception as e:
        return {"body": _degraded_store(node, ctx, body, "rotate_solid")}


def handle_place_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """Place a component at the specified position.

    v6.3: Priority order for placement:
      1. ctx.spatial_placements[target_component_id] (ConstraintResolver output)
      2. node.params["position_mm"] (LLM-provided fallback)

    The ConstraintResolver runs after all leaf components are built and
    computes numeric placements from symbolic constraints + actual bboxes.
    This handler now consumes those computed placements.
    """
    body = resolve_input_object(node, ctx, 0)

    # ── v6.3: Preferred path — solver-computed placement ──
    pos = None
    placements = getattr(ctx, 'spatial_placements', None)
    if placements:
        # Determine target component ID:
        # 1. Explicit component_id param (v6.3)
        # 2. producer_component of first input (the solid being placed)
        target_cid = node.params.get("component_id")
        if not target_cid and node.inputs:
            target_cid = node.inputs[0].producer_component

        if target_cid and target_cid in placements:
            p = placements[target_cid]
            if not p.is_pending:
                pos = tuple(p.translation_mm)
                if p.rotation_deg_xyz and any(v != 0 for v in p.rotation_deg_xyz):
                    ctx.warnings.append(
                        f"place_component on '{node.id}': rotation from solver "
                        f"({p.rotation_deg_xyz}) ignored — rotation not yet "
                        f"supported in place_component handler"
                    )

    # ── Fallback: LLM-provided position ──
    if pos is None:
        pos = node.params.get("position_mm", (0, 0, 0))

    if not isinstance(pos, (list, tuple)) or len(pos) != 3:
        raise ValueError(f"place_component requires 3D position, got {pos}")

    pos_f = tuple(float(v) for v in pos)

    try:
        placed = body.translate(pos_f)
    except Exception as exc:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required place_component failed on '{node.id}': {exc}"
            ) from exc
        return {"body": _degraded_store(node, ctx, body, "place_component")}

    # ── V3: preserve topology identity across placement transform ──
    _register_transform_topology_preservation(
        node=node, ctx=ctx, source_body=body, result_body=placed,
        transform_op="place", transform_params={"position_mm": pos_f},
    )

    # ── v6.3: Track placed bbox for downstream spatial audit ──
    target_cid = node.params.get("component_id") or (
        node.inputs[0].producer_component if node.inputs else None
    )
    if target_cid and hasattr(ctx, "placed_component_bboxes"):
        try:
            bb = placed.val().BoundingBox() if hasattr(placed, 'val') else placed.BoundingBox()
            ctx.placed_component_bboxes[target_cid] = bb
        except Exception:
            pass

    return {"body": _store_solid(node, ctx, placed)}


# ═══════════════════════════════════════════════════════════════════════════════
# V3 Pattern topology recording
# ═══════════════════════════════════════════════════════════════════════════════


def _record_pattern_topology_event(
    *, node, ctx, count, pattern_type, pattern_params,
) -> None:
    """Record pattern topology event with seed entity references (Phase 4)."""
    reg = ctx.topology_registry
    seed_pids = [
        pid for pid, rec in reg._entities.items()
        if rec.status == "active" and rec.entity_type == "face"
    ]
    ctx.topology_events.append({
        "event": "pattern_topology_produced",
        "node_id": node.id,
        "pattern_type": pattern_type,
        "occurrence_count": count,
        "seed_face_count": len(seed_pids),
        "seed_pids_sample": seed_pids[:20],
        "params": pattern_params,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Pattern handlers
# ═══════════════════════════════════════════════════════════════════════════════

def handle_circular_pattern_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    count = max(1, int(node.params.get("count", 1)))
    radius = float(node.params.get("radius_mm", 0))
    start_angle = float(node.params.get("start_angle_deg", 0))

    if count <= 1 or radius <= 0:
        msg = f"circular_pattern on '{node.id}': count={count} radius={radius} — invalid params"
        if getattr(node, "required", True):
            raise ValueError(msg)
        ctx.warnings.append(msg)
        return {"body": _store_solid(node, ctx, body)}

    rotate = bool(node.params.get("rotate_copies", True))
    try:
        import cadquery as cq
        result = None
        for i in range(count):  # include i=0, all copies properly placed
            angle_deg = start_angle + i * 360.0 / count
            angle = math.radians(angle_deg)
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            placed = body
            if rotate:
                placed = placed.rotate((0, 0, 0), (0, 0, 1), angle_deg)
            placed = placed.translate((x, y, 0))
            if result is None:
                result = placed
            else:
                result = result.union(placed)
        _record_pattern_topology_event(
            node=node, ctx=ctx, count=count,
            pattern_type="circular",
            pattern_params={"radius_mm": radius, "start_angle_deg": start_angle,
                          "rotate_copies": rotate},
        )
        return {"body": _store_solid(node, ctx, result)}
    except Exception as e:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required circular_pattern failed on '{node.id}': {e}"
            ) from e
        ctx.warnings.append(f"circular_pattern failed on '{node.id}': {e}")
        return {"body": _store_solid(node, ctx, body)}


def handle_linear_pattern_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    count = max(1, int(node.params.get("count", 1)))
    spacing = float(node.params.get("spacing_mm", 0))
    direction = node.params.get("direction", "X")

    if count <= 1 or spacing <= 0:
        msg = f"linear_pattern on '{node.id}': count={count} spacing={spacing} — invalid params"
        if getattr(node, "required", True):
            raise ValueError(msg)
        ctx.warnings.append(msg)
        return {"body": _store_solid(node, ctx, body)}

    dir_map = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}
    dir_vec = dir_map.get(direction, (1, 0, 0))

    try:
        result = body
        for i in range(1, count):
            vec = tuple(spacing * i * d for d in dir_vec)
            result = result.union(body.translate(vec))
        _record_pattern_topology_event(
            node=node, ctx=ctx, count=count,
            pattern_type="linear",
            pattern_params={"spacing_mm": spacing, "direction": direction},
        )
        return {"body": _store_solid(node, ctx, result)}
    except Exception as e:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required linear_pattern failed on '{node.id}': {e}"
            ) from e
        ctx.warnings.append(f"linear_pattern failed on '{node.id}': {e}")
        return {"body": _store_solid(node, ctx, body)}


# ═══════════════════════════════════════════════════════════════════════════════
# Boolean handlers
# ═══════════════════════════════════════════════════════════════════════════════

def handle_boolean_union(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """Boolean union with three-layer fallback for OCCT stability.

    Attempt 1: CadQuery a.union(b)
    Attempt 2: OCCT BRepAlgoAPI_Fuse via a.fuse(b)
    Attempt 3 (v6.1): tolerance-expanded fuse for near-tangent/grazing contact
    Degradation: return first solid with detailed diagnostic record

    v6.1 adds Attempt 3 to handle thin-wall tube + shaft unions (tm07_roller)
    and other cases where OCCT boolean ops fail on grazing contact.
    """
    if len(node.inputs) != 2:
        raise ValueError(f"boolean_union requires exactly 2 inputs, got {len(node.inputs)}")
    a = resolve_input_object(node, ctx, 0)
    b = resolve_input_object(node, ctx, 1)

    # Pre-boolean diagnostic
    from seekflow_engineering_tools.generative_cad.validation.geometry_validate import pre_boolean_check
    pre = pre_boolean_check(a, b, ctx.tolerance)
    if pre.reason:
        ctx.warnings.append(f"boolean_union pre-check on '{node.id}': {pre.reason}")

    # ── Attempt 1: CadQuery union ──
    try:
        result = a.union(b)
        # Verify: check if result is still multi-solid
        if hasattr(result, 'Solids'):
            n_result = len(list(result.Solids()))
            n_a = len(list(a.Solids())) if hasattr(a, 'Solids') else 1
            n_b = len(list(b.Solids())) if hasattr(b, 'Solids') else 1
            if n_result < n_a + n_b:
                return _finish_boolean_op(node, ctx, result, "boolean_union")
            ctx.warnings.append(
                f"boolean_union: CadQuery union produced {n_result} solids "
                f"(a={n_a}, b={n_b}) — trying fuse"
            )
        else:
            return _finish_boolean_op(node, ctx, result, "boolean_union")
    except Exception:
        pass

    # ── Attempt 2: OCCT BRepAlgoAPI_Fuse ──
    try:
        result = a.fuse(b)
        if hasattr(result, 'Solids'):
            n_result = len(list(result.Solids()))
            n_a = len(list(a.Solids())) if hasattr(a, 'Solids') else 1
            n_b = len(list(b.Solids())) if hasattr(b, 'Solids') else 1
            if n_result < n_a + n_b:
                ctx.warnings.append(
                    f"boolean_union: OCCT fuse succeeded ({n_result} solids)"
                )
                return _finish_boolean_op(node, ctx, result, "boolean_union")
            ctx.warnings.append(
                f"boolean_union: OCCT fuse produced {n_result} solids "
                f"(expected < {n_a + n_b}) — trying tolerance-expanded fuse"
            )
        else:
            return _finish_boolean_op(node, ctx, result, "boolean_union")
    except Exception:
        pass

    # ── Attempt 3 (v6.3): OCCT fuzzy fuse — no geometry movement ──
    # Replaces the old translate-margin hack which moved solid B.
    # Uses SetFuzzyValue() for proper tolerance-based coincidence detection.
    try:
        from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.boolean_safe import (
            boolean_union_safe,
        )
        result, _strategy = boolean_union_safe(a, b, ctx.tolerance, allow_compound=False)
        ctx.warnings.append(
            f"boolean_union: fuzzy fuse succeeded "
            f"(clearance={_fmt_clr(pre.clearance_mm)})"
        )
        return _finish_boolean_op(node, ctx, result, "boolean_union")
    except Exception:
        pass

    # ── Degradation: HARD FAIL for required boolean_union ──
    # v6.3: boolean_union is a structurally critical operation.
    # Silently dropping solid B means the assembly is INCOMPLETE.
    # This is no longer allowed — we must fail-closed.
    ctx.degraded_features.append({
        "node_id": node.id, "op": "boolean_union",
        "reason": "all_fuse_strategies_failed",
        "clearance_mm": pre.clearance_mm,
        "lost_volume_mm3": pre.b_volume_mm3,
        "lost_bbox_mm": pre.b_bbox_mm,
        "kept_volume_mm3": pre.a_volume_mm3,
    })
    raise RuntimeError(
        f"boolean_union FAILED on '{node.id}': "
        f"Could not merge solid B ({_fmt_vol(pre.b_volume_mm3)}) with solid A "
        f"({_fmt_vol(pre.a_volume_mm3)}). "
        f"Clearance={_fmt_clr(pre.clearance_mm)}. "
        f"Check for non-intersecting geometry or grazing contact."
    )


def handle_boolean_cut(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    if len(node.inputs) != 2:
        raise ValueError(f"boolean_cut requires exactly 2 inputs, got {len(node.inputs)}")
    target = resolve_input_object(node, ctx, 0)
    tool = resolve_input_object(node, ctx, 1)

    from seekflow_engineering_tools.generative_cad.validation.geometry_validate import pre_boolean_check
    pre = pre_boolean_check(target, tool, ctx.tolerance)

    try:
        result = target.cut(tool)
    except Exception:
        try:
            result = target.cut(tool, ctx.tolerance.boolean_fallback_tolerance)
        except Exception:
            ctx.degraded_features.append({
                "node_id": node.id, "op": "boolean_cut",
                "reason": "cut_failed",
                "clearance_mm": pre.clearance_mm,
                "target_volume_mm3": pre.a_volume_mm3,
                "tool_volume_mm3": pre.b_volume_mm3,
            })
            raise RuntimeError(
                f"boolean_cut FAILED on '{node.id}': "
                f"cut was NOT applied. "
                f"Target={_fmt_vol(pre.a_volume_mm3)}, "
                f"Tool={_fmt_vol(pre.b_volume_mm3)}. "
                f"Clearance={_fmt_clr(pre.clearance_mm)}."
            )
    # V3 Phase 10: capture OCCT history with PID-keyed source snapshots
    history_result = None
    try:
        from seekflow_engineering_tools.generative_cad.topology.history_wrappers import (
            history_aware_boolean_cut,
        )
        from seekflow_engineering_tools.generative_cad.topology.shape_binding import (
            ShapeBindingService, build_operation_input_snapshot,
        )
        service = ShapeBindingService(ctx.object_store)
        # Build PID→face binding tables for target and tool
        target_handle = f"solid:{node.component}:{node.inputs[0].producer_node}:body"
        tool_handle = f"solid:{node.component}:{node.inputs[1].producer_node}:body"
        target_pids = build_operation_input_snapshot(
            target.val().wrapped, target_handle, ctx.topology_registry, service,
        )
        tool_pids = build_operation_input_snapshot(
            tool.val().wrapped, tool_handle, ctx.topology_registry, service,
        )
        history_result = history_aware_boolean_cut(
            target.val().wrapped, tool.val().wrapped,
            input_target_faces=[f.wrapped for f in target.faces().vals()],
            input_tool_faces=[f.wrapped for f in tool.faces().vals()],
            input_target_pids=target_pids,
            input_tool_pids=tool_pids,
        )
    except Exception:
        pass
    return _finish_boolean_op(node, ctx, result, "boolean_cut",
                              history_result=history_result)


def _apply_boolean_identity_decisions(
    *, tx, node, op_name: str, history_result: Any,
    res_maps: Any = None,
    pos_to_pid: dict[int, str] | None = None,
) -> None:
    """V3 Phase 15c+16: Apply OCCT history-driven identity decisions on top of
    semantic naming entities.  Updates generation counts, marks consumed/
    deleted entities, and records provenance evidence.

    When res_maps and pos_to_pid are provided (Phase 16), OCCT result faces
    are correlated to semantic naming entities via IndexedMap position,
    enabling accurate ancestor/descendant lineage links.

    Source role detection uses a precise PID-keyed approach: if the source PID
    appears in the history result's PID-keyed dicts (gct3_ keys), it's a known
    entity from the target or tool body.  Falls back to string heuristics only
    when positional keys are used (no PID-keyed results available).
    """
    try:
        from seekflow_engineering_tools.generative_cad.topology.kernel_identity import (
            IdentityTransferPolicy, KernelHistoryEdge, KernelRelation,
        )
        # Determine if the history result has PID-keyed data (gct3_ keys)
        has_pid_keys = any(
            str(k).startswith("gct3_")
            for k in history_result.generated_faces.keys()
        )
        # Build a set of known PIDs from the result for source-role detection
        known_pids = set()
        if has_pid_keys:
            for k in history_result.generated_faces.keys():
                known_pids.add(str(k))
            for k in history_result.modified_faces.keys():
                known_pids.add(str(k))
            for k in history_result.deleted_entities:
                known_pids.add(str(k))

        decisions = []

        # Build deleted PID set for tool detection in PID-keyed results
        is_deleted = set(
            str(k) for k in history_result.deleted_entities
            if str(k).startswith("gct3_")
        )

        # ── Helper: map an OCCT result face to a gct3_ PID via IndexedMap position ──
        def _resolve_result_pid(face) -> str | None:
            if res_maps is None or not pos_to_pid:
                return None
            try:
                from seekflow_engineering_tools.generative_cad.topology.shape_binding import (
                    ShapeBindingService,
                )
                # locate_subshape is a method, need a service instance
                # Use FindIndex directly on the stored indexed map
                idx_map = res_maps._face_indexed_map
                if idx_map is None:
                    return None
                raw_face = getattr(face, "wrapped", face)
                pos = idx_map.FindIndex(raw_face)
                if pos == 0:
                    return None
                return pos_to_pid.get(pos)
            except Exception:
                return None

        # ── Generated faces ──
        for src_key, gen_faces in history_result.generated_faces.items():
            for fi, face in enumerate(gen_faces):
                result_key = f"bool_gen:{node.id}:{src_key}:{fi}"
                src_str = str(src_key)
                if src_str.startswith("gct3_"):
                    is_tool = src_str in is_deleted
                    kernel_rel = KernelRelation.GENERATED if is_tool else KernelRelation.MODIFIED
                else:
                    is_tool = src_str.startswith("tool_")
                    kernel_rel = KernelRelation.GENERATED
                edge = KernelHistoryEdge(
                    source_pid=src_str,
                    result_occurrence_key=result_key,
                    kernel_relation=kernel_rel,
                )
                decision = IdentityTransferPolicy.decide(
                    [edge],
                    source_role="tool" if is_tool else "target",
                    operation_kind=op_name,
                    entity_dimension="face",
                )
                # ── Phase 16: link result face to semantic naming entity ──
                result_pid = _resolve_result_pid(face)
                if result_pid:
                    decision.result_keys.append(result_pid)
                decisions.append(decision)

        # ── Modified faces → MODIFIED_SAME_IDENTITY ──
        for src_key, mod_faces in history_result.modified_faces.items():
            for fi, face in enumerate(mod_faces):
                edge = KernelHistoryEdge(
                    source_pid=str(src_key),
                    result_occurrence_key=f"bool_mod:{node.id}:{src_key}",
                    kernel_relation=KernelRelation.MODIFIED,
                )
                decision = IdentityTransferPolicy.decide(
                    [edge],
                    source_role="target",
                    operation_kind=op_name,
                    entity_dimension="face",
                )
                # ── Phase 16: link result face to semantic naming entity ──
                result_pid = _resolve_result_pid(face)
                if result_pid:
                    decision.result_keys.append(result_pid)
                decisions.append(decision)

        # ── Deleted entities → DELETED/CONSUMED ──
        for del_key in history_result.deleted_entities:
            if has_pid_keys:
                is_tool = str(del_key) not in {
                    str(k) for k in history_result.modified_faces.keys()
                }
            else:
                is_tool = str(del_key).startswith("tool_")
            edge = KernelHistoryEdge(
                source_pid=str(del_key),
                result_occurrence_key="",
                kernel_relation=KernelRelation.REMOVED,
            )
            decision = IdentityTransferPolicy.decide(
                [edge],
                source_role="tool" if is_tool else "target",
                operation_kind=op_name,
                entity_dimension="face",
            )
            decisions.append(decision)

        if decisions:
            # ── Phase 17a: deduplicate by source_pid to prevent generation inflation.
            # One source PID appears in N OCCT result faces → N decisions →
            # generation += N (incorrect).  Dedup to 1 decision per source.
            seen_sources: set[tuple[str, ...]] = set()
            deduped = []
            for d in decisions:
                key = tuple(sorted(d.source_pids))
                if key not in seen_sources:
                    seen_sources.add(key)
                    deduped.append(d)
            decisions = deduped

            tx.staged.apply_identity_decisions(
                decisions,
                node_id=node.id,
                component_id=node.component or "unknown",
            )
    except Exception:
        pass  # identity decisions are supplementary; delta is authoritative


def _try_produce_boolean_topology(
    *, node: CanonicalNode, ctx: RuntimeContext, solid, op_name: str,
    history_result: Any = None,
) -> None:
    """PR 6 + V3 Phase 15c: Hybrid Boolean topology — semantic naming for entity
    creation, OCCT history for lineage and generation enrichment.

    Always runs semantic naming to create gct3_ entities with full descriptor
    coverage.  When OCCT history is available with PID-keyed results, it also
    calls apply_identity_decisions to update generation counts, mark consumed/
    deleted entities, and establish ancestor/descendant lineage.
    """
    try:
        from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
            build_entity_records_from_delta, name_boolean_faces,
        )
    except ImportError:
        return
    try:
        doc_id = ctx.document_id or "unknown"

        # ── Step 1 (always): semantic naming creates base gct3_ entities ──
        fuid = None
        dctx = getattr(ctx, 'design_identity_context', None)
        if dctx is not None:
            fuid = dctx.feature_stable_id_for(node.id, component_id=node.component or "")
        delta = name_boolean_faces(
            solid, document_id=doc_id,
            component_id=node.component or "unknown",
            producer_node_id=node.id,
            feature_uid=fuid,
        )

        records = build_entity_records_from_delta(
            delta, document_id=doc_id,
            feature_stable_ids=_get_feature_stable_ids(ctx),
        )
        body_handle_id = f"solid:{node.component}:{node.id}:body"

        # Locator and lineage correlation state (populated in Step 1.5)
        res_maps = None
        pos_to_pid: dict[int, str] = {}

        with ctx.topology_transaction() as tx:
            for rec in records:
                tx.register_entity(rec)
            tx.apply_delta(delta)

            # ── Step 1.5: build locators for result entities ──
            # name_boolean_faces iterates solid.faces().vals() in order;
            # the IndexedMap enumerates faces in the same deterministic order.
            # So records[i] corresponds to solid.faces().vals()[i].
            # Build locators via IndexedMap position to enable downstream
            # OCCT history face → PID correlation for lineage.
            pos_to_pid: dict[int, str] = {}
            try:
                from seekflow_engineering_tools.generative_cad.topology.shape_binding import (
                    ShapeBindingService,
                )
                service_bl = ShapeBindingService(ctx.object_store)
                raw_solid = solid.val().wrapped if hasattr(solid, 'val') else solid
                res_maps = service_bl.build_body_maps(body_handle_id, raw_solid)
                res_faces = list(solid.faces().vals())
                for idx, rec in enumerate(records):
                    if idx < len(res_faces):
                        locator = service_bl.locate_subshape(res_maps, res_faces[idx], "face")
                        if locator is not None:
                            rec.current_locator = locator.model_dump()
                            pos = locator.indexed_map_position
                            if pos is not None:
                                pos_to_pid[pos] = rec.persistent_id
            except Exception:
                pass  # locator building is best-effort

            # ── Step 2 (optional): OCCT history enriches lineage + generation ──
            if history_result is not None and history_result.generated_faces:
                _apply_boolean_identity_decisions(
                    tx=tx, node=node, op_name=op_name,
                    history_result=history_result,
                )

            # ── Step 2.5: establish batch lineage ──
            # All new boolean entities are descendants of surviving source faces.
            # Collect surviving source PIDs (not deleted, with gct3_ keys in history).
            surviving_sources: list[str] = []
            if history_result is not None:
                deleted_set = set(str(k) for k in history_result.deleted_entities)
                for src_key in history_result.generated_faces:
                    src_str = str(src_key)
                    if src_str.startswith("gct3_") and src_str not in deleted_set:
                        if src_str not in surviving_sources:
                            surviving_sources.append(src_str)
                for src_key in history_result.modified_faces:
                    src_str = str(src_key)
                    if src_str.startswith("gct3_") and src_str not in surviving_sources:
                        surviving_sources.append(src_str)
            # Link each new boolean entity to all surviving sources
            if surviving_sources:
                for rec in records:
                    for src_pid in surviving_sources:
                        if src_pid not in rec.ancestor_ids:
                            rec.ancestor_ids.append(src_pid)
                        src_rec = tx.staged._entities.get(src_pid)
                        if src_rec is not None and rec.persistent_id not in src_rec.descendant_ids:
                            src_rec.descendant_ids.append(rec.persistent_id)

        ctx.record_topology_event(
            event="boolean_topology_produced",
            node_id=node.id,
            op=op_name,
            face_count=len(delta.relations),
            method="semantic" if history_result is None else "hybrid_semantic_plus_history",
            deleted_count=len(history_result.deleted_entities) if history_result is not None else 0,
            generated_count=sum(len(v) for v in history_result.generated_faces.values()) if history_result is not None else 0,
            modified_count=sum(len(v) for v in history_result.modified_faces.values()) if history_result is not None else 0,
        )
    except Exception as exc:
        ctx.topology_warnings.append({
            "node_id": node.id, "phase": "boolean_topology", "op": op_name,
            "error": str(exc),
        })


def _finish_boolean_op(node, ctx, solid, op_name: str,
                      history_result: Any = None) -> dict[str, str]:
    """Store solid + produce topology delta, then return result map."""
    body_id = _store_solid(node, ctx, solid)
    _try_produce_boolean_topology(node=node, ctx=ctx, solid=solid, op_name=op_name,
                                   history_result=history_result)
    return {"body": body_id}


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_vol(v: float | None) -> str:
    return f"{v:.1f} mm³" if v is not None else "unknown"


def _fmt_clr(c: float | None) -> str:
    return f"{c:.3f} mm" if c is not None else "unknown"
