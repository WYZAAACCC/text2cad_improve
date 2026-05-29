"""Repair patch v0.4 — RepairPatchV2 with path validators and apply logic."""

from __future__ import annotations

import copy, re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RepairChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    old_value: Any | None = None
    new_value: Any
    reason: str


class RepairPatchV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_node: str | None = None
    target_component: str | None = None
    changes: list[RepairChange]
    reason: str
    give_up: bool = False


# Forbidden exact path prefixes
FORBIDDEN_EXACT_PREFIXES = [
    "/schema_version",
    "/selected_dialects",
    "/safety",
    "/constraints/require_step_file",
    "/constraints/require_metadata_sidecar",
    "/constraints/require_closed_solid",
]

# Forbidden node field patterns
FORBIDDEN_NODE_FIELDS = {"dialect", "op", "op_version"}

# Forbidden component fields
FORBIDDEN_COMPONENT_FIELDS = {"owner_dialect"}

# Allowed path patterns
ALLOWED_PATH_PATTERNS = [
    re.compile(r"^/nodes/[^/]+/params/.+$"),
    re.compile(r"^/nodes/[^/]+/inputs$"),
    re.compile(r"^/nodes/[^/]+/outputs$"),
    re.compile(r"^/nodes/[^/]+/required$"),
    re.compile(r"^/nodes/[^/]+/degradation_policy$"),
    re.compile(r"^/components/[^/]+/root_node$"),
    re.compile(r"^/llm_validation_hints$"),
]


def is_forbidden_repair_path(path: str) -> bool:
    """Check if a path matches any forbidden pattern."""
    for prefix in FORBIDDEN_EXACT_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True

    # Check forbidden node fields: /nodes/<id>/dialect, /nodes/<id>/op, /nodes/<id>/op_version
    m = re.match(r"^/nodes/([^/]+)/(\w+)$", path)
    if m:
        field = m.group(2)
        if field in FORBIDDEN_NODE_FIELDS:
            return True

    # Check forbidden component fields
    m = re.match(r"^/components/([^/]+)/(\w+)$", path)
    if m:
        field = m.group(2)
        if field in FORBIDDEN_COMPONENT_FIELDS:
            return True

    return False


def is_allowed_repair_path(path: str) -> bool:
    """Check if a path matches any allowed pattern."""
    for pattern in ALLOWED_PATH_PATTERNS:
        if pattern.match(path):
            return True
    return False


def validate_repair_patch_v2(patch: RepairPatchV2) -> tuple[bool, list[dict]]:
    """Validate a repair patch against allowed/forbidden path rules."""
    issues = []
    if patch.give_up:
        return True, []

    if not patch.changes:
        issues.append({"code": "empty_repair_patch", "message": "repair patch has no changes"})
        return False, issues

    for change in patch.changes:
        if is_forbidden_repair_path(change.path):
            issues.append({"code": "forbidden_repair_path", "message": f"path {change.path!r} is forbidden"})
        elif not is_allowed_repair_path(change.path):
            issues.append({"code": "unsupported_repair_path", "message": f"path {change.path!r} is not allowed"})

    return len(issues) == 0, issues


def apply_repair_patch_v2(raw: dict, patch: RepairPatchV2) -> dict:
    """Apply a validated RepairPatchV2 to a raw document dict.

    Raises ValueError if target node/component not found.
    """
    ok, issues = validate_repair_patch_v2(patch)
    if not ok:
        raise ValueError("invalid repair patch: " + "; ".join(i["message"] for i in issues))

    updated = copy.deepcopy(raw)

    for change in patch.changes:
        path = change.path

        # /nodes/<node_id>/params/<field>
        m = re.match(r"^/nodes/([^/]+)/params/(.+)$", path)
        if m:
            node_id = m.group(1)
            field = m.group(2)
            found = False
            for node in updated.get("nodes", []):
                if node.get("id") == node_id:
                    node.setdefault("params", {})[field] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target node not found: {node_id}")
            continue

        # /nodes/<node_id>/inputs
        m = re.match(r"^/nodes/([^/]+)/inputs$", path)
        if m:
            node_id = m.group(1)
            found = False
            for node in updated.get("nodes", []):
                if node.get("id") == node_id:
                    node["inputs"] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target node not found: {node_id}")
            continue

        # /nodes/<node_id>/outputs
        m = re.match(r"^/nodes/([^/]+)/outputs$", path)
        if m:
            node_id = m.group(1)
            found = False
            for node in updated.get("nodes", []):
                if node.get("id") == node_id:
                    node["outputs"] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target node not found: {node_id}")
            continue

        # /nodes/<node_id>/required
        m = re.match(r"^/nodes/([^/]+)/required$", path)
        if m:
            node_id = m.group(1)
            found = False
            for node in updated.get("nodes", []):
                if node.get("id") == node_id:
                    node["required"] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target node not found: {node_id}")
            continue

        # /nodes/<node_id>/degradation_policy
        m = re.match(r"^/nodes/([^/]+)/degradation_policy$", path)
        if m:
            node_id = m.group(1)
            found = False
            for node in updated.get("nodes", []):
                if node.get("id") == node_id:
                    node["degradation_policy"] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target node not found: {node_id}")
            continue

        # /components/<component_id>/root_node
        m = re.match(r"^/components/([^/]+)/root_node$", path)
        if m:
            comp_id = m.group(1)
            found = False
            for comp in updated.get("components", []):
                if comp.get("id") == comp_id:
                    comp["root_node"] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target component not found: {comp_id}")
            continue

        # /llm_validation_hints
        if path == "/llm_validation_hints":
            if not isinstance(change.new_value, dict):
                raise ValueError("/llm_validation_hints repair value must be dict")
            updated["llm_validation_hints"] = change.new_value
            continue

    return updated
