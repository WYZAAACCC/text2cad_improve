"""Unified operation executor — v2.0: typed OperationResult ABI enforcement.

Every dialect run_component must call execute_operation, not invoke
handler directly. This ensures output names, types, handle existence,
and handle value_type are validated at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.dialects.results import (
    OperationResult,
    adapt_legacy_handler_result,
)
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext


@dataclass(frozen=True)
class ExecutedNode:
    node_id: str
    outputs: dict[str, str] = field(default_factory=dict)


def execute_operation(
    *,
    node: CanonicalNode,
    op_spec: OperationSpec,
    ctx: RuntimeContext,
) -> ExecutedNode:
    """Execute a single operation node through the unified executor.

    1. Call handler (supports v1_dict legacy and v2_result)
    2. Normalize to OperationResult
    3. Validate output names, types, handle existence, handle value_type
    4. Propagate warnings, degraded_features, metrics
    5. Bind node outputs and return ExecutedNode
    """
    raw_result = op_spec.handler(node, ctx)

    # Normalize to OperationResult
    if isinstance(raw_result, OperationResult):
        result = raw_result
    elif isinstance(raw_result, dict) and op_spec.handler_kind == "v1_dict":
        result = adapt_legacy_handler_result(raw_result, node)
    else:
        raise RuntimeError(
            f"Handler for {node.dialect}.{node.op}@{node.op_version} returned "
            f"unsupported result type {type(raw_result).__name__} "
            f"(handler_kind={op_spec.handler_kind})"
        )

    # Validate
    _validate_operation_result(node=node, op_spec=op_spec, result=result, ctx=ctx)

    # Propagate side-channel data
    for w in result.warnings:
        ctx.warnings.append(w)
    for d in result.degraded_features:
        ctx.degraded_features.append(d)
    for metric in result.metrics:
        ctx.operation_metrics.append(metric.model_dump())

    # Bind outputs
    outputs: dict[str, str] = {}
    for output in result.outputs:
        ctx.bind_node_output(node.id, output.name, output.handle_id)
        outputs[output.name] = output.handle_id

    return ExecutedNode(node_id=node.id, outputs=outputs)


def _validate_operation_result(
    *,
    node: CanonicalNode,
    op_spec: OperationSpec,
    result: OperationResult,
    ctx: RuntimeContext,
) -> None:
    """Validate OperationResult against CanonicalNode declarations and stored handles."""
    if result.ok is not True:
        raise RuntimeError(f"Operation {node.id} ({node.op}) returned ok=False")

    declared_by_name = {o.name: o.type for o in node.outputs}
    result_by_name = {o.name: o for o in result.outputs}

    missing = sorted(set(declared_by_name) - set(result_by_name))
    extra = sorted(set(result_by_name) - set(declared_by_name))

    if missing:
        raise RuntimeError(
            f"Operation {node.id} ({node.op}) missing declared output(s): {missing}"
        )
    if extra:
        raise RuntimeError(
            f"Operation {node.id} ({node.op}) returned undeclared output(s): {extra}"
        )

    # Verify output types match declared types
    for output_decl in node.outputs:
        result_output = result_by_name[output_decl.name]
        if result_output.value_type != output_decl.type:
            raise RuntimeError(
                f"Operation {node.id}.{output_decl.name} returned type "
                f"{result_output.value_type!r}, expected {output_decl.type!r}"
            )

        # Verify handle exists and value_type matches
        stored = ctx.object_store.get_typed(result_output.handle_id)
        if stored.value_type != output_decl.type:
            raise RuntimeError(
                f"Handle {result_output.handle_id!r} has type {stored.value_type!r}, "
                f"expected {output_decl.type!r}"
            )
