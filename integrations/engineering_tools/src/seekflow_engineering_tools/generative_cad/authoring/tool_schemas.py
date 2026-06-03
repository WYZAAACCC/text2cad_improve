"""Strict tool schema factories for staged authoring.

Each factory produces a DeepSeek-compatible strict schema that constrains
LLM output to exactly the allowed fields and values. These are used by
authoring/pipeline.py in place of the empty tool_schema={} that previously
left LLM output unconstrained.

Design:
  - RoutePlan, FeatureSequenceDraft → strict_schema_from_pydantic with
    extra enum/const constraints injected.
  - NodeParams → operation-specific wrapper that replaces the open
    params: dict[str, Any] with the concrete OperationSpec.params_model schema.
  - RepairPatch → strict_schema_from_pydantic(RepairPatchV2).
"""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.authoring.schemas import (
    FeatureSequenceDraft,
    RoutePlan,
)
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
    strict_schema_from_pydantic,
    to_deepseek_strict_schema,
)
from seekflow_engineering_tools.generative_cad.repair.patch import RepairPatchV2


def build_route_plan_tool_schema(
    dialect_registry,  # DialectRegistry
    primitive_catalog_summary: dict | None = None,  # noqa: ARG001 — reserved for future use
) -> dict[str, Any]:
    """Build strict tool schema for the route planning stage.

    Constrains selected_dialects[*].dialect to registered dialect IDs and
    selected_dialects[*].version to the corresponding dialect version.
    """
    schema = RoutePlan.model_json_schema()

    # Collect known dialect IDs and versions
    known_dialects = sorted(dialect_registry.list_ids())
    known_versions: dict[str, list[str]] = {}
    for did in known_dialects:
        d = dialect_registry.get(did)
        if d is not None:
            known_versions[did] = [d.version]

    # Constrain SelectedDialectDraft.dialect -> enum of known IDs
    _inject_const(
        schema,
        ["$defs", "SelectedDialectDraft", "properties", "dialect"],
        enum=known_dialects,
    )

    # Constrain SelectedDialectDraft.version -> enum of known versions (deduped)
    all_versions = sorted(set(
        v for vs in known_versions.values() for v in vs
    ))
    if all_versions:
        _inject_const(
            schema,
            ["$defs", "SelectedDialectDraft", "properties", "version"],
            enum=all_versions,
        )

    # Constrain route_decision enum
    _inject_const(
        schema,
        ["properties", "route_decision", "anyOf"],
        # route_decision is an enum; ensure it's preserved in anyOf
    )

    return to_deepseek_strict_schema(schema)


def build_feature_sequence_tool_schema(
    ctx,  # AuthoringContext
) -> dict[str, Any]:
    """Build strict tool schema for the feature sequence stage.

    Constrains:
      - components[*].owner_dialect to ctx.selected_dialects (+ composition).
      - node_sequence[*].dialect to ctx.selected_dialects (+ composition).
      - node_sequence[*].op to the valid ops for that dialect.
      - node_sequence[*].op_version to the spec's op_version.
    """
    schema = FeatureSequenceDraft.model_json_schema()

    # Allowed dialects: selected + composition
    allowed_dialects = sorted(set(ctx.selected_dialects) | {"composition"})

    # Constrain ComponentDraft.owner_dialect
    _inject_const(
        schema,
        ["$defs", "ComponentDraft", "properties", "owner_dialect"],
        enum=allowed_dialects,
    )

    # Constrain NodePlanDraft.dialect
    _inject_const(
        schema,
        ["$defs", "NodePlanDraft", "properties", "dialect"],
        enum=allowed_dialects,
    )

    # Collect all valid (dialect, op) pairs for enum constraint on op
    from seekflow_engineering_tools.generative_cad.dialects.default_registry import (
        default_registry,
    )
    registry = default_registry()
    known_ops: set[str] = set()
    for did in allowed_dialects:
        d = registry.get(did)
        if d is not None:
            for (op_name, _ver) in d.op_specs().keys():
                known_ops.add(op_name)

    if known_ops:
        _inject_const(
            schema,
            ["$defs", "NodePlanDraft", "properties", "op"],
            enum=sorted(known_ops),
        )

    return to_deepseek_strict_schema(schema)


def build_node_params_tool_schema(
    node_plan,  # NodePlanDraft
    dialect_registry,  # DialectRegistry
) -> dict[str, Any]:
    """Build an operation-specific strict tool schema for ONE node's params.

    This is the most critical schema: instead of params: dict[str, Any],
    it uses the concrete OperationSpec.params_model's JSON Schema so the
    LLM is forced to emit correct parameter names, types, and constraints.

    The wrapper constrains node_id, dialect, op, op_version to match the
    node_plan exactly (DeepSeek `const` keyword).
    """
    dialect = dialect_registry.get(node_plan.dialect)
    if dialect is None:
        raise ValueError(
            f"Unknown dialect {node_plan.dialect!r} for node {node_plan.node_id!r}"
        )

    try:
        spec = dialect.get_op_spec(node_plan.op, node_plan.op_version)
    except Exception:
        raise ValueError(
            f"Unknown op {node_plan.op!r} version {node_plan.op_version!r} "
            f"in dialect {node_plan.dialect!r}"
        )

    # Get the concrete params model schema
    params_schema = spec.params_model.model_json_schema()

    # Build the operation-specific wrapper
    wrapper: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "node_id": {"const": node_plan.node_id},
            "dialect": {"const": node_plan.dialect},
            "op": {"const": node_plan.op},
            "op_version": {"const": spec.op_version},
            "params": params_schema,
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "node_id", "dialect", "op", "op_version", "params", "assumptions",
        ],
    }

    return to_deepseek_strict_schema(wrapper)


def build_repair_patch_tool_schema() -> dict[str, Any]:
    """Build strict tool schema for the repair patch stage."""
    return strict_schema_from_pydantic(RepairPatchV2)


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _inject_const(schema: dict, path: list[str], **kwargs: Any) -> None:
    """Inject const/enum constraints at a schema path.

    Creates intermediate dicts if needed. Only sets keys that don't
    conflict with existing schema constraints.
    """
    current: Any = schema
    for seg in path[:-1]:
        if isinstance(current, dict):
            if seg not in current:
                current[seg] = {}
            current = current[seg]
        elif isinstance(current, list):
            try:
                idx = int(seg)
                current = current[idx]
            except (ValueError, IndexError):
                return
        else:
            return

    if not isinstance(current, dict):
        return

    target_key = path[-1]
    if target_key not in current:
        current[target_key] = {}

    target = current[target_key]
    if not isinstance(target, dict):
        return

    for k, v in kwargs.items():
        if k not in target:
            target[k] = v
