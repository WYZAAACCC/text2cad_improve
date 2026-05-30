"""Runtime postconditions — validates runner output before STEP export. v0.7: root output binding."""

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
    - final handle exists in object_store and is retrievable
    - final handle type is solid
    - every non-assembly component's root_node outputs are bound
    - every non-assembly component's root_node can resolve its body output
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

    # Check final object is retrievable from object store
    try:
        ctx.object_store.get(final_handle_id)
    except Exception as exc:
        issues.append({
            "stage": "runtime_postconditions",
            "code": "final_object_lookup_failed",
            "message": f"Final object {final_handle_id!r} not found in object store: {exc}",
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
            continue

        # Check root node exists and its outputs are bound
        root = next((n for n in canonical.nodes if n.id == comp.root_node), None)
        if root is None:
            issues.append({
                "stage": "runtime_postconditions",
                "code": "component_root_node_not_found",
                "message": f"Component {comp.id!r} root_node {comp.root_node!r} not found.",
                "severity": "error",
                "component_id": comp.id,
            })
            continue

        for output in root.outputs:
            try:
                ctx.resolve_node_output(root.id, output.name)
            except Exception as exc:
                issues.append({
                    "stage": "runtime_postconditions",
                    "code": "component_root_output_not_bound",
                    "message": f"Root output {root.id}.{output.name} for component {comp.id!r} is not bound: {exc}",
                    "severity": "error",
                    "component_id": comp.id,
                    "node_id": root.id,
                })

    return {
        "ok": not any(i["severity"] == "error" for i in issues),
        "stage": "runtime_postconditions",
        "issues": issues,
    }
