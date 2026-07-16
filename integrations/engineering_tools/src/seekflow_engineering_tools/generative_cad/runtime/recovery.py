"""Structured recovery — unified degradation decision for handler failures.

Handlers MUST use handle_feature_failure() instead of custom try/except
blocks that silently return the original body. This ensures:

1. required=True features → always raise (fail-closed)
2. required=False + degradation_policy="may_skip_with_warning" → warn + record
3. Any other combination → raise (fail-closed)

Phase 2: enforcement for axisymmetric destructive ops.
Phase 3+: extends to all dialects.
"""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext


def handle_feature_failure(
    *,
    node: CanonicalNode,
    ctx: RuntimeContext,
    original_body: Any,
    op_name: str,
    exc: Exception | None = None,
    reason: str = "",
) -> dict[str, str]:
    """Unified recovery decision for a failed feature operation.

    Called by handlers when a geometry operation fails (boolean cut,
    chamfer, thread, etc.). The decision is:

    - required=True → RuntimeError (HARD FAIL — feature is structurally necessary)
    - required=False + may_skip_with_warning → warn + record + return original body
    - anything else → RuntimeError (fail-closed)

    Args:
        node: The CanonicalNode that failed.
        ctx: RuntimeContext for recording warnings/degraded_features.
        original_body: The solid body BEFORE the failed operation.
        op_name: Human-readable operation name for error messages.
        exc: The exception that was caught (optional).
        reason: Additional context about why the operation failed.

    Returns:
        dict mapping "body" → handle_id of the stored (original) body.
        Only returned for non-required may_skip_with_warning nodes.

    Raises:
        RuntimeError: If the feature is required or degradation is not allowed.
    """
    from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
    from seekflow_engineering_tools.generative_cad.runtime.diagnostics import RuntimeIssue
    from seekflow_engineering_tools.generative_cad.runtime.errors import GcadRuntimeError

    error_detail = str(exc) if exc else reason
    if not error_detail:
        error_detail = "unknown error"

    # ── Required feature → HARD FAIL ──
    if getattr(node, "required", True):
        raise GcadRuntimeError(RuntimeIssue(
            stage="operation_execution",
            code="REQUIRED_FEATURE_FAILED",
            message=(
                f"Required operation '{op_name}' failed on node '{node.id}': "
                f"{error_detail}. "
                f"This feature is structurally necessary and cannot be skipped. "
                f"Fix the parameters or mark the node as required=False with "
                f"degradation_policy='may_skip_with_warning' if this feature is decorative."
            ),
            node_id=node.id,
            component_id=getattr(node, "component", None),
            dialect=getattr(node, "dialect", None),
            operation=node.op,
            operation_version=getattr(node, "op_version", None),
            exception_type=type(exc).__name__ if exc else None,
            repairability="repairable",   # §6.1: 参数因果明确
            suggested_paths=[f"/nodes/{node.id}/params"],
            evidence={"error_detail": error_detail, "op_name": op_name},
        ))

    # ── Optional feature with skip policy → degrade gracefully ──
    if getattr(node, "degradation_policy", "fail") == "may_skip_with_warning":
        ctx.warnings.append(
            f"Optional feature '{op_name}' skipped on node '{node.id}': "
            f"{error_detail}. Part is valid without this feature."
        )
        ctx.degraded_features.append({
            "node_id": node.id,
            "op": node.op,
            "op_name": op_name,
            "reason": error_detail,
        })
        ctx.operation_metrics.append({
            "node_id": node.id,
            "op": node.op,
            "status": "degraded",
            "reason": error_detail,
        })

        # Store original body under the node's output handle
        sid = f"solid:{node.component}:{node.id}:body"
        ctx.object_store.put_solid(
            SolidHandle(
                id=sid,
                component_id=node.component,
                producer_node=node.id,
            ),
            original_body,
        )
        ctx.bind_node_output(node.id, "body", sid)
        return {"body": sid}

    # ── Fail-closed default ──
    raise GcadRuntimeError(RuntimeIssue(
        stage="operation_execution",
        code="DEGRADATION_POLICY_INVALID",
        message=(
            f"Operation '{op_name}' failed on node '{node.id}': "
            f"{error_detail}. "
            f"Node is marked required=False but degradation_policy is "
            f"'{getattr(node, 'degradation_policy', 'fail')}' "
            f"— only 'may_skip_with_warning' is allowed for graceful degradation."
        ),
        node_id=node.id,
        component_id=getattr(node, "component", None),
        dialect=getattr(node, "dialect", None),
        operation=node.op,
        operation_version=getattr(node, "op_version", None),
        exception_type=type(exc).__name__ if exc else None,
        repairability="conditionally_repairable",
        evidence={"error_detail": error_detail, "op_name": op_name},
    ))
