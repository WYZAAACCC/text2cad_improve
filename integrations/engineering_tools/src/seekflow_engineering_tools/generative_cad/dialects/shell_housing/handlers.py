"""ShellHousing CadQuery handlers — shell, thicken, hollow."""
from __future__ import annotations
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle


def _store_solid(node, ctx, obj) -> str:
    sid = f"solid:{node.component}:{node.id}:body"
    ctx.object_store.put_solid(SolidHandle(id=sid, component_id=node.component, producer_node=node.id), obj)
    ctx.bind_node_output(node.id, "body", sid)
    return sid


def handle_shell_body(node, ctx) -> dict:
    """Shell a solid body to create thin walls."""
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    body = resolve_input_object(node, ctx, 0)
    thickness = float(node.params.get("thickness_mm", 1.0))
    if thickness <= 0:
        raise ValueError("thickness_mm must be positive")
    try:
        if (
            getattr(ctx, "enable_topology_capture", False)
            and ctx.capture_session is not None
        ):
            import cadquery as cq
            from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.offset_sweep import (
                tracked_shell,
            )
            from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
                TopologyCaptureScope,
            )
            scope = TopologyCaptureScope(
                node_id=node.id, component_id=node.component,
                dialect=node.dialect, operation=node.op,
                operation_version=node.op_version,
            )
            body_shape = body.val() if hasattr(body, "val") else body
            tracked = tracked_shell(
                body_shape, thickness,
                faces_to_remove=list(body.faces("<Z")),
                scope=scope,
            )
            ctx.capture_session.stage(tracked.batch)
            solid = cq.Workplane("XY").newObject([tracked.result])
        else:
            solid = body.faces("<Z").shell(thickness)
            # If that fails, try shelling all faces
            if solid is None:
                solid = body.shell(thickness)
    except Exception:
        try:
            solid = body.shell(thickness)
        except Exception as e:
            raise RuntimeError(f"shell_body failed on '{node.id}': {e}")
    return {"body": _store_solid(node, ctx, solid)}


def handle_hollow_body(node, ctx) -> dict:
    """Hollow a solid leaving specified wall thickness."""
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    import cadquery as cq
    body = resolve_input_object(node, ctx, 0)
    wall = float(node.params.get("wall_thickness_mm", 1.0))
    bottom = float(node.params.get("bottom_thickness_mm", wall))
    if wall <= 0:
        raise ValueError("wall_thickness_mm must be positive")
    # Normalize Workplane input to its underlying Shape/Solid so Shape-level
    # translate/scale/cut operations work uniformly below.
    if hasattr(body, "val") and not hasattr(body, "wrapped"):
        body = body.val()
    try:
        bb = body.BoundingBox()
        sx = (bb.xlen - 2 * wall) / bb.xlen if bb.xlen > 2 * wall else 0.5
        sy = (bb.ylen - 2 * wall) / bb.ylen if bb.ylen > 2 * wall else 0.5
        sz = (bb.zlen - wall - bottom) / bb.zlen if bb.zlen > wall + bottom else 0.5

        # Create the inner cavity by raising its bottom and applying a
        # non-uniform scale about the origin. CadQuery Shape.scale() is uniform
        # only, so use OCCT's general transform for per-axis scaling.
        from OCP.BRepBuilderAPI import BRepBuilderAPI_GTransform
        from OCP.gp import gp_GTrsf
        gtrsf = gp_GTrsf()
        gtrsf.SetValue(1, 1, sx)
        gtrsf.SetValue(2, 2, sy)
        gtrsf.SetValue(3, 3, sz)
        translated = body.translate((0, 0, bottom))
        gbuilder = BRepBuilderAPI_GTransform(translated.wrapped, gtrsf)
        gbuilder.Build()
        inner = cq.Shape.cast(gbuilder.Shape())
        if (
            getattr(ctx, "enable_topology_capture", False)
            and ctx.capture_session is not None
        ):
            from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops import (
                tracked_cut,
            )
            from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
                TopologyCaptureScope,
            )
            scope = TopologyCaptureScope(
                node_id=node.id, component_id=node.component,
                dialect=node.dialect, operation=node.op,
                operation_version=node.op_version,
            )
            tracked = tracked_cut(body, inner, scope=scope)
            ctx.capture_session.stage(tracked.batch)
            solid = cq.Workplane("XY").newObject([tracked.result])
        else:
            solid = body.cut(inner)
    except Exception as e:
        raise RuntimeError(f"hollow_body failed on '{node.id}': {e}")
    return {"body": _store_solid(node, ctx, solid)}
