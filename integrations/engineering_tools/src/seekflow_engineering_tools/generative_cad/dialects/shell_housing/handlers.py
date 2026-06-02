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
    try:
        bb = body.val().BoundingBox()
        # Create inner cavity by offsetting
        inner = body.translate((0, 0, bottom)).scale((
            (bb.xlen - 2 * wall) / bb.xlen if bb.xlen > 2 * wall else 0.5,
            (bb.ylen - 2 * wall) / bb.ylen if bb.ylen > 2 * wall else 0.5,
            (bb.zlen - wall - bottom) / bb.zlen if bb.zlen > wall + bottom else 0.5,
        ))
        solid = body.cut(inner)
    except Exception as e:
        raise RuntimeError(f"hollow_body failed on '{node.id}': {e}")
    return {"body": _store_solid(node, ctx, solid)}
