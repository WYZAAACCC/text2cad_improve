"""Shared runtime input resolver — single source of truth for all handlers."""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext


def resolve_input_handle_id(node: CanonicalNode, ctx: RuntimeContext, index: int = 0) -> str:
    """Resolve a single input reference to a handle id.

    Resolves in order: producer_node > producer_component.
    Raises KeyError if input index out of range or reference cannot be resolved.
    """
    if index >= len(node.inputs):
        raise KeyError(f"node {node.id!r} has no input at index {index}")
    inp = node.inputs[index]
    if inp.producer_node:
        return ctx.resolve_node_output(inp.producer_node, inp.output)
    if inp.producer_component:
        return ctx.resolve_component_output(inp.producer_component, inp.output)
    raise KeyError(f"node {node.id!r} input[{index}] has no producer")


def resolve_input_object(node: CanonicalNode, ctx: RuntimeContext, index: int = 0) -> Any:
    """Resolve a single input reference to a runtime object (CadQuery shape etc)."""
    hid = resolve_input_handle_id(node, ctx, index)
    return ctx.object_store.get(hid)


def resolve_all_input_objects(node: CanonicalNode, ctx: RuntimeContext) -> list[Any]:
    """Resolve all input references to runtime objects."""
    objs = []
    for i in range(len(node.inputs)):
        hid = resolve_input_handle_id(node, ctx, i)
        objs.append(ctx.object_store.get(hid))
    return objs
