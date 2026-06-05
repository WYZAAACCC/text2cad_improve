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
    # Check cache before executing handler
    cached = ctx.cache.get(node)
    if cached is not None:
        # Re-wrap cached result — it was already validated
        if isinstance(cached, OperationResult):
            raw_result = cached
        elif isinstance(cached, dict) and op_spec.handler_kind == "v1_dict":
            raw_result = cached
        else:
            raw_result = op_spec.handler(node, ctx)
    else:
        raw_result = op_spec.handler(node, ctx)
        # Cache the result for future incremental rebuilds
        if isinstance(raw_result, (OperationResult, dict)):
            ctx.cache.put(node, raw_result)

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

    # Runtime geometry validation (BRepCheck, closed solid, positive volume)
    # v6.3: run on ALL geometry-modifying ops, not just creates_solid/modifies_solid.
    # cuts_material and adds_material also produce/modify solids and must be checked.
    if any(e in ("creates_solid", "modifies_solid", "cuts_material", "adds_material")
           for e in op_spec.effects):
        _validate_geometry(node=node, result=result, ctx=ctx)

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


def _validate_geometry(*, node, result, ctx) -> None:
    """Run BRepCheck + closed solid + volume checks on geometry-producing ops.

    v6.3 Phase 2: Records GeometryHealth in ctx.geometry_health_log.
    If health.status == "error" and node.required is True, raises RuntimeError.
    Legacy warnings behavior is preserved for backward compatibility.
    """
    try:
        from seekflow_engineering_tools.generative_cad.runtime.health import (
            GeometryHealth,
            inspect_geometry_health,
        )
        for output in result.outputs:
            if output.value_type != "solid":
                continue
            try:
                solid = ctx.object_store.get(output.handle_id)
            except KeyError:
                ctx.warnings.append(f"Geometry check skipped on '{node.id}': handle not found")
                continue

            # ── v6.3 Phase 2: Structured health assessment ──
            try:
                health = inspect_geometry_health(
                    solid_obj=solid,
                    geometry_runtime=ctx.geometry_runtime,
                    tolerance=ctx.tolerance,
                )
            except Exception as exc:
                health = GeometryHealth(
                    status="unknown",
                    issues=[{"code": "health_inspection_failed", "message": str(exc), "severity": "warning"}],
                )

            # Record in context
            health_key = f"{node.id}.{output.name}"
            ctx.geometry_health_log[health_key] = health.model_dump()

            # Log issues as warnings (preserve legacy behavior)
            for issue in health.issues:
                prefix = "Geometry error" if issue.get("severity") == "error" else "Geometry warning"
                ctx.warnings.append(
                    f"{prefix} on '{node.id}.{output.name}': [{issue.get('code', '?')}] {issue.get('message', '?')}"
                )

            # ── v6.3 Phase 2: required feature health enforcement ──
            if health.status == "error":
                if getattr(node, "required", True):
                    raise RuntimeError(
                        f"Required operation '{node.op}' on node '{node.id}' "
                        f"produced unhealthy geometry (status={health.status}): "
                        f"closed={health.closed}, volume={health.volume_mm3}, "
                        f"bodies={health.body_count}. "
                        f"Issues: {[i.get('code') for i in health.issues]}. "
                        f"Mark the node as required=False with "
                        f"degradation_policy='may_skip_with_warning' if this "
                        f"defect is acceptable."
                    )
    except ImportError:
        pass  # OCCT bindings not available — skip geometry validation
    except RuntimeError:
        raise  # Re-raise required enforcement errors
    except Exception as e:
        ctx.warnings.append(f"Geometry validation skipped on '{node.id}': {e}")
