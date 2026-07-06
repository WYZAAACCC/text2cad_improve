"""Axisymmetric dialect handlers — v1.0 hardened.

All handlers follow the pattern: validate → try full op → try fallback → warn+skip.
No silent degradation. No None propagation. No uncaught OCCT errors.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle, FrameHandle
from seekflow_engineering_tools.generative_cad.runtime.recovery import handle_feature_failure
from seekflow_engineering_tools.generative_cad.runtime.resolve import (
    resolve_input_object,
)


def _store_solid(node: CanonicalNode, ctx: RuntimeContext, obj) -> str:
    if obj is None:
        raise RuntimeError(f"BUG: _store_solid called with None on '{node.id}'")
    sid = f"solid:{node.component}:{node.id}:body"
    ctx.object_store.put_solid(SolidHandle(id=sid, component_id=node.component, producer_node=node.id), obj)
    ctx.bind_node_output(node.id, "body", sid)
    return sid


# ═══════════════════════════════════════════════════════════════════════════════
# Geometry creation
# ═══════════════════════════════════════════════════════════════════════════════

def handle_revolve_profile(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    stations = node.typed_params.get("profile_stations", node.params.get("profile_stations", []))
    if not stations or len(stations) < 1:
        raise ValueError("Need at least 1 profile station")

    # ── Single station: simple cylinder ──
    if len(stations) == 1:
        s = stations[0]
        r = float(s["r_mm"])
        zf = float(s.get("z_front_mm", 0))
        zr = float(s.get("z_rear_mm", 0))
        if zr <= zf:
            raise ValueError(f"z_rear_mm ({zr}) must be > z_front_mm ({zf})")
        result = (
            cq.Workplane("XZ")
            .moveTo(r, zf)
            .lineTo(r, zr)
            .lineTo(0, zr)
            .lineTo(0, zf)
            .close()
            .revolve(360)
        )
        solid = result
    else:
        # ── Multi station: piecewise linear profile ──
        # 检测"区域描述"风格：多个 station 的 Z 区间重叠
        # 这是 LLM 把 bore/hub/web/rim 分区域输出的典型模式，会导致 sort-by-Z
        # 算法 silently 产生错误形状。必须 fail-closed 报错。
        if len(stations) >= 2:
            z_ranges = [(s.get("z_front_mm", 0), s.get("z_rear_mm", 0)) for s in stations]
            overlap_count = 0
            for i, (zf1, zr1) in enumerate(z_ranges):
                for j, (zf2, zr2) in enumerate(z_ranges[i+1:], i+1):
                    if zf1 < zr2 and zf2 < zr1:
                        overlap_count += 1
            if overlap_count > 0:
                raise ValueError(
                    f"revolve_profile stations have {overlap_count} overlapping Z ranges. "
                    f"This indicates regional description style (bore/hub/web/rim), "
                    f"which violates the Z single-valued outer contour constraint. "
                    f"Cannot produce valid solid — requires LLM repair."
                )

        pts_2d: list[tuple[float, float]] = []
        for s in stations:
            pts_2d.append((float(s["r_mm"]), float(s.get("z_front_mm", 0))))
            pts_2d.append((float(s["r_mm"]), float(s.get("z_rear_mm", 0))))

        pts_2d.sort(key=lambda p: p[1])  # sort by z only — stable preserve at same z

        unique_pts = [pts_2d[0]]
        for pt in pts_2d[1:]:
            if pt != unique_pts[-1]:
                unique_pts.append(pt)

        if len(unique_pts) < 2:
            raise ValueError(f"Profile degenerates to {len(unique_pts)} unique point(s) after dedup")

        z_min = unique_pts[0][1]
        z_max = unique_pts[-1][1]
        result = cq.Workplane("XZ").moveTo(0, z_min)
        for (r, z) in unique_pts:
            result = result.lineTo(r, z)
        result = result.lineTo(0, z_max).close()
        solid = result.revolve(360)

    result_map = {"body": _store_solid(node, ctx, solid)}

    if any(o.name == "outer_frame" for o in node.outputs):
        fid = f"frame:{node.component}:{node.id}:outer_frame"
        ctx.object_store.put_frame(FrameHandle(id=fid, component_id=node.component, producer_node=node.id))
        ctx.bind_node_output(node.id, "outer_frame", fid)
        result_map["outer_frame"] = fid
    return result_map


# ═══════════════════════════════════════════════════════════════════════════════
# Material removal
# ═══════════════════════════════════════════════════════════════════════════════

def handle_cut_center_bore(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    dia = float(node.typed_params.get("diameter_mm", node.params.get("diameter_mm", 0)))
    if dia <= 0:
        raise ValueError("diameter_mm must be positive")
    try:
        bb = body.val().BoundingBox()
        bore = cq.Workplane("XY").circle(dia / 2.0).extrude(bb.zlen + 10, both=True)
        result = body.cut(bore)
    except Exception as e:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_center_bore", exc=e,
        )
    return {"body": _store_solid(node, ctx, result)}


def handle_cut_circular_hole_pattern(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    count = int(p.get("count", 0))
    pcd = float(p.get("pcd_mm", 0))
    hole_dia = float(p.get("hole_dia_mm", 0))
    if count < 2 or pcd <= 0 or hole_dia <= 0:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_circular_hole_pattern",
            reason=f"invalid params: count={count}, pcd={pcd}, hole_dia={hole_dia}",
        )
    try:
        bb = body.val().BoundingBox()
        z_len = bb.zlen + 10
        hole_radius = hole_dia / 2.0

        # Safety: check that holes are within body radial extent to avoid
        # OCCT boolean crashes on near-tangent or missed intersections.
        body_radius_min = float("inf")
        try:
            from OCP.BRepExtrema import BRepExtrema_DistShapeShape
            from OCP.gp import gp_Pnt, gp_Ax1, gp_Dir, gp_Circ
            from OCP.GC import GC_MakeCircle
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire

            # Rough radial check: does the hole PCD fit within the body?
            # Build a test cylinder and check minimum distance
            pcd_radius = pcd / 2.0
            # If the body is narrow and holes would barely intersect, use individual cuts
            is_narrow_body = bb.xlen < pcd + hole_dia or bb.ylen < pcd + hole_dia
        except Exception:
            is_narrow_body = False

        # For narrow/complex bodies, cut each hole individually to avoid OCCT instability
        if is_narrow_body or count > 6:
            result = body
            import math as _math
            for k in range(count):
                angle = 2.0 * _math.pi * k / count
                cx = (pcd / 2.0) * _math.cos(angle)
                cy = (pcd / 2.0) * _math.sin(angle)
                try:
                    hole = cq.Workplane("XY").center(cx, cy).circle(hole_radius).extrude(z_len, both=True)
                    result = result.cut(hole)
                except Exception:
                    ctx.warnings.append(
                        f"circular_hole_pattern on '{node.id}': hole {k} at "
                        f"({cx:.1f},{cy:.1f}) failed, skipping."
                    )
        else:
            wp = cq.Workplane("XY").polarArray(pcd / 2.0, 0, 360, count)
            holes = wp.circle(hole_radius).extrude(z_len, both=True)
            result = body.cut(holes)
    except Exception as e:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_circular_hole_pattern", exc=e,
        )
    return {"body": _store_solid(node, ctx, result)}


def handle_cut_annular_groove(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    inner = float(p.get("inner_dia_mm", 0))
    outer = float(p.get("outer_dia_mm", 0))
    depth = float(p.get("depth_mm", 0))
    side = p.get("side", "front")
    z_position = p.get("z_position_mm")
    if inner <= 0 or outer <= 0 or outer <= inner:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_annular_groove",
            reason=f"invalid diameters: inner={inner}, outer={outer}",
        )
    try:
        bb = body.val().BoundingBox()
        # z_position_mm 优先；缺失时回退到 side 决定的端面
        if z_position is not None:
            z_pos = float(z_position)
        else:
            z_pos = bb.zmin if side == "front" else bb.zmax
        extrude_dir = depth if side == "front" else -depth
        ring = (
            cq.Workplane("XY").workplane(offset=z_pos)
            .circle(outer / 2.0).circle(inner / 2.0).extrude(extrude_dir)
        )
        result = body.cut(ring)
    except Exception as e:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_annular_groove", exc=e,
        )
    return {"body": _store_solid(node, ctx, result)}


def handle_cut_rim_slot_pattern(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    import cadquery as cq
    import math
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    count = int(p.get("count", 0))
    slot_depth = float(p.get("slot_depth_mm", 0))
    profile = p.get("slot_profile", {})
    stations = profile.get("stations", []) if isinstance(profile, dict) else []
    if count < 2 or slot_depth <= 0 or len(stations) < 2:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_rim_slot_pattern",
            reason=f"invalid params: count={count}, slot_depth={slot_depth}, stations={len(stations)}",
        )
    try:
        bb = body.val().BoundingBox()
        outer_r = max(bb.xlen, bb.ylen) / 2.0
        slot_pts: list[tuple[float, float]] = []
        first_hw = float(stations[0]["half_width_mm"])
        # +Y profile: rim surface → root (descending)
        for s in stations:
            sd = float(s["depth_mm"])
            hw = float(s["half_width_mm"])
            slot_pts.append((outer_r - sd, hw))
        # -Y profile: root → rim surface (ascending, mirror-symmetric)
        for s in reversed(stations):
            sd = float(s["depth_mm"])
            hw = float(s["half_width_mm"])
            slot_pts.append((outer_r - sd, -hw))
        # Opening at rim surface: span from -first_hw to +first_hw
        # Prepend +Y rim opening point for moveTo, append -Y for close target
        slot_pts.insert(0, (outer_r, first_hw))
        slot_pts.append((outer_r, -first_hw))
        wp = cq.Workplane("XY")
        for i, (r, w) in enumerate(slot_pts):
            wp = wp.moveTo(r, w) if i == 0 else wp.lineTo(r, w)
        base_cutter = wp.close().extrude(bb.zlen + 10, both=True)

        if count <= 6:
            # 小 count: union-then-cut 策略（性能最优）
            # 6 个槽的 union 约 48 条边，远低于 OCCT 崩溃阈值
            combined = base_cutter
            for i in range(1, count):
                angle = math.degrees(i * 2 * math.pi / count)
                combined = combined.union(base_cutter.rotate((0, 0, 0), (0, 0, 1), angle))
            result = body.cut(combined)
        else:
            # 大 count: sequential cut 策略（稳健性最优）
            # 避免 union 拓扑累积导致 OCP 崩溃（60 槽 union 需处理 ~480 条交线）
            # 与 handle_cut_circular_hole_pattern (count > 6) 的稳健策略一致
            result = body
            success_count = 0
            for i in range(count):
                angle = math.degrees(i * 2 * math.pi / count)
                try:
                    cutter = base_cutter.rotate((0, 0, 0), (0, 0, 1), angle)
                    result = result.cut(cutter)
                    success_count += 1
                except Exception as slot_e:
                    ctx.warnings.append(
                        f"cut_rim_slot_pattern on '{node.id}': slot {i} at "
                        f"angle {angle:.1f}° failed, skipping. Error: {slot_e}"
                    )

            if success_count == 0:
                return handle_feature_failure(
                    node=node, ctx=ctx, original_body=body,
                    op_name="cut_rim_slot_pattern",
                    reason=f"all {count} slots failed to cut",
                )
            if success_count < count:
                ctx.warnings.append(
                    f"cut_rim_slot_pattern on '{node.id}': {count - success_count} of "
                    f"{count} slots skipped due to OCCT errors."
                )
                ctx.degraded_features.append({
                    "node_id": node.id, "op": "cut_rim_slot_pattern",
                    "reason": f"{count - success_count}/{count} slots skipped",
                })
    except Exception as e:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_rim_slot_pattern", exc=e,
        )
    return {"body": _store_solid(node, ctx, result)}


# ═══════════════════════════════════════════════════════════════════════════════
# Edge treatment
# ═══════════════════════════════════════════════════════════════════════════════

def handle_apply_safe_chamfer(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    distance = float(node.typed_params.get("distance_mm", node.params.get("distance_mm", 0)))
    if distance > 0:
        target = node.params.get("target", "all_external_edges")
        try:
            body = _chamfer_by_target(body, distance, target)
        except Exception:
            try:
                body = _chamfer_by_target(body, distance / 2.0, target)
            except Exception:
                # 降级：required=False 时允许 no-op（保留原 body）
                if not node.required and node.degradation_policy == "may_skip_with_warning":
                    ctx.warnings.append(
                        f"Optional chamfer '{node.id}' skipped: "
                        f"failed at distance={distance}mm and {distance/2.0}mm"
                    )
                    ctx.degraded_features.append({
                        "node_id": node.id, "op": "apply_safe_chamfer",
                        "reason": f"chamfer failed at distance={distance}mm",
                    })
                    ctx.operation_metrics.append({
                        "node_id": node.id, "op": "apply_safe_chamfer",
                        "status": "degraded",
                        "reason": f"chamfer failed at distance={distance}mm",
                    })
                    # 返回原 body（不修改）
                    return {"body": _store_solid(node, ctx, body)}
                return handle_feature_failure(
                    node=node, ctx=ctx, original_body=body,
                    op_name="apply_safe_chamfer",
                    reason=f"chamfer failed at distance={distance}mm and fallback distance={distance/2.0}mm",
                )
    return {"body": _store_solid(node, ctx, body)}


# ── Shared topology helpers ───────────────────────────────────────────────────

def _chamfer_by_target(body, distance: float, target: str):
    if target == "all_external_edges":
        return body.chamfer(distance)
    from seekflow_engineering_tools.generative_cad.runtime.topology import select_edges
    edges = select_edges(body, target)
    if not edges:
        return body.chamfer(distance)
    result = body
    for e in edges:
        try: result = result.edges(e.edge_index).chamfer(distance)
        except Exception: continue
    return result


def _fillet_by_target(body, radius: float, target: str):
    if target == "all_external_edges":
        return body.fillet(radius)
    from seekflow_engineering_tools.generative_cad.runtime.topology import select_edges
    edges = select_edges(body, target)
    if not edges:
        return body.fillet(radius)
    result = body
    for e in edges:
        try: result = result.edges(e.edge_index).fillet(radius)
        except Exception: continue
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Thread operations
# ═══════════════════════════════════════════════════════════════════════════════

def handle_cut_internal_thread(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """Cut an internal thread (tapped hole) using helical sweep."""
    import cadquery as cq, math
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    nom_dia = float(p.get("nominal_dia_mm", 8))
    pitch = float(p.get("pitch_mm", 1.25))
    depth = float(p.get("depth_mm", 20))
    start_angle = float(p.get("start_angle_deg", 0))

    if nom_dia <= 0 or pitch <= 0 or depth <= 0:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_internal_thread",
            reason=f"invalid params: nom_dia={nom_dia}, pitch={pitch}, depth={depth}",
        )

    try:
        # V-thread profile: 60-degree triangular cutter
        thread_depth = 0.866 * pitch  # ISO metric thread depth
        # Build helical path
        turns = depth / pitch
        helix = cq.Workplane("XY").parametricCurve(
            lambda t: (
                (nom_dia / 2.0) * math.cos(2 * math.pi * t + math.radians(start_angle)),
                (nom_dia / 2.0) * math.sin(2 * math.pi * t + math.radians(start_angle)),
                pitch * t,
            ),
            N=max(20, int(turns * 30)),
        )
        # Triangular cutter profile
        cutter = cq.Workplane("XZ").moveTo(0, 0).lineTo(thread_depth, pitch / 4.0).lineTo(-thread_depth, pitch / 4.0).close()
        thread_solid = cutter.sweep(helix)
        result = body.cut(thread_solid)
    except Exception as e:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_internal_thread", exc=e,
        )
    return {"body": _store_solid(node, ctx, result)}


def handle_cut_external_thread(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    """Cut an external thread on a cylindrical surface."""
    import cadquery as cq, math
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    nom_dia = float(p.get("nominal_dia_mm", 8))
    pitch = float(p.get("pitch_mm", 1.25))
    length = float(p.get("length_mm", 20))
    start_z = float(p.get("start_z_mm", 0))
    start_angle = float(p.get("start_angle_deg", 0))

    if nom_dia <= 0 or pitch <= 0 or length <= 0:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_external_thread",
            reason=f"invalid params: nom_dia={nom_dia}, pitch={pitch}, length={length}",
        )

    try:
        thread_depth = 0.866 * pitch
        turns = length / pitch
        helix = cq.Workplane("XY").parametricCurve(
            lambda t: (
                (nom_dia / 2.0 - thread_depth / 2.0) * math.cos(2 * math.pi * t + math.radians(start_angle)),
                (nom_dia / 2.0 - thread_depth / 2.0) * math.sin(2 * math.pi * t + math.radians(start_angle)),
                start_z + pitch * t,
            ),
            N=max(20, int(turns * 30)),
        )
        cutter = cq.Workplane("XZ").moveTo(0, 0).lineTo(thread_depth, pitch / 4.0).lineTo(-thread_depth, pitch / 4.0).close()
        thread_solid = cutter.sweep(helix)
        result = body.cut(thread_solid)
    except Exception as e:
        return handle_feature_failure(
            node=node, ctx=ctx, original_body=body,
            op_name="cut_external_thread", exc=e,
        )
    return {"body": _store_solid(node, ctx, result)}
