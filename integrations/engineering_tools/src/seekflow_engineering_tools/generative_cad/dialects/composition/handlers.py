"""Composition dialect handlers — transform, pattern, boolean only."""

from __future__ import annotations

import math

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
from seekflow_engineering_tools.generative_cad.runtime.resolve import (
    resolve_input_handle_id,
    resolve_input_object,
    resolve_all_input_objects,
)


def _store_solid(node: CanonicalNode, ctx: RuntimeContext, obj) -> str:
    solid_id = f"solid:{node.component}:{node.id}:body"
    handle = SolidHandle(id=solid_id, component_id=node.component, producer_node=node.id)
    ctx.object_store.put_solid(handle, obj)
    ctx.bind_node_output(node.id, "body", solid_id)
    return solid_id


def handle_translate_solid(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    vector = node.params.get("vector_mm", (0, 0, 0))
    return {"body": _store_solid(node, ctx, body.translate(vector))}


def handle_rotate_solid(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    origin = node.params.get("axis_origin_mm", (0, 0, 0))
    axis_dir = node.params.get("axis_dir", (0, 0, 1))
    angle = float(node.params.get("angle_deg", 0))
    return {"body": _store_solid(node, ctx, body.rotate(origin, axis_dir, angle))}


def handle_circular_pattern_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    count = int(node.params.get("count", 1))
    radius = float(node.params.get("radius_mm", 0))
    start_angle = float(node.params.get("start_angle_deg", 0))

    combined = None
    for i in range(count):
        angle = math.radians(start_angle + i * 360.0 / count)
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        placed = body.translate((x, y, 0))
        combined = placed if combined is None else combined.union(placed)

    hid = _store_solid(node, ctx, combined)
    return {"body": hid}


def handle_linear_pattern_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    count = int(node.params.get("count", 1))
    spacing = float(node.params.get("spacing_mm", 0))
    direction = node.params.get("direction", "X")

    dir_vec = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[direction]
    combined = None
    for i in range(count):
        vec = tuple(spacing * i * d for d in dir_vec)
        placed = body.translate(vec)
        combined = placed if combined is None else combined.union(placed)

    hid = _store_solid(node, ctx, combined)
    return {"body": hid}


def handle_boolean_union(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    solids = resolve_all_input_objects(node, ctx)
    if not solids:
        raise ValueError("boolean_union requires at least one input solid")
    result = solids[0]
    for s in solids[1:]:
        result = result.union(s)
    hid = _store_solid(node, ctx, result)
    return {"body": hid}


def handle_boolean_cut(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    solids = resolve_all_input_objects(node, ctx)
    if len(solids) < 2:
        raise ValueError("boolean_cut requires at least two input solids (target, tool)")
    result = solids[0]
    for s in solids[1:]:
        result = result.cut(s)
    hid = _store_solid(node, ctx, result)
    return {"body": hid}


def handle_place_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    pos = node.params.get("position_mm", (0, 0, 0))
    return {"body": _store_solid(node, ctx, body.translate(pos))}


