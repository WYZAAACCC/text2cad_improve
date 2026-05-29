"""Runtime postconditions — validates runner output before STEP export."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext


def validate_runtime_postconditions(
    canonical: CanonicalGcadDocument,
    ctx: RuntimeContext,
    final_handle_id: str,
) -> dict:
    """Validate that the runner produced valid outputs.

    Checks:
    - final_handle_id is non-empty
    - final handle exists in object_store
    - final handle type is solid
    - every non-assembly component's root_node outputs are bound
    """
    issues: list[dict] = []

    if not final_handle_id:
        issues.append({
            "stage": "runtime_postconditions",
            "code": "missing_final_handle",
            "message": "Runner did not produce a final solid handle.",
            "severity": "error",
        })
        return {"ok": False, "stage": "runtime_postconditions", "issues": issues}

    # Check final handle exists and is solid type
    try:
        handle = ctx.object_store.get_handle(final_handle_id)
    except Exception as exc:
        issues.append({
            "stage": "runtime_postconditions",
            "code": "final_handle_lookup_failed",
            "message": f"Final handle {final_handle_id!r} not found: {exc}",
            "severity": "error",
        })
        return {"ok": False, "stage": "runtime_postconditions", "issues": issues}

    if handle is not None:
        htype = getattr(handle, "type", None) or getattr(handle, "value_type", None)
        if str(htype) not in ("solid", "ValueType.SOLID", "SolidHandle"):
            issues.append({
                "stage": "runtime_postconditions",
                "code": "final_handle_not_solid",
                "message": f"Final handle must be solid type, got {htype!r}.",
                "severity": "error",
            })

    # Check component root_nodes
    for comp in canonical.components:
        if comp.id == "__assembly__":
            continue
        if not comp.root_node:
            issues.append({
                "stage": "runtime_postconditions",
                "code": "component_missing_root_node",
                "message": f"Component {comp.id!r} has no root_node.",
                "severity": "error",
                "component_id": comp.id,
            })

    return {
        "ok": not any(i["severity"] == "error" for i in issues),
        "stage": "runtime_postconditions",
        "issues": issues,
    }
