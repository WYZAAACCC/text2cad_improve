"""Repair patch v0.8 — RepairPatchV2 with old_value verification, applied count, give_up."""

from __future__ import annotations

import copy, re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _old_value_matches(current, expected) -> bool:
    """Return True if expected is None (no check) or current == expected."""
    return expected is None or current == expected


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

    Raises ValueError if target node/component not found, old_value mismatches,
    or applied count does not match change count.
    """
    ok, issues = validate_repair_patch_v2(patch)
    if not ok:
        raise ValueError("invalid repair patch: " + "; ".join(i["message"] for i in issues))

    # give_up: return unchanged deep copy, no changes required
    if patch.give_up:
        return copy.deepcopy(raw)

    updated = copy.deepcopy(raw)
    applied = 0

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
                    current = node.setdefault("params", {}).get(field)
                    if not _old_value_matches(current, change.old_value):
                        raise ValueError(
                            f"repair old_value mismatch at {path}: "
                            f"expected {change.old_value!r}, got {current!r}"
                        )
                    node.setdefault("params", {})[field] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target node not found: {node_id}")
            applied += 1
            continue

        # /nodes/<node_id>/inputs
        m = re.match(r"^/nodes/([^/]+)/inputs$", path)
        if m:
            node_id = m.group(1)
            found = False
            for node in updated.get("nodes", []):
                if node.get("id") == node_id:
                    if not _old_value_matches(node.get("inputs"), change.old_value):
                        raise ValueError(
                            f"repair old_value mismatch at {path}: "
                            f"expected {change.old_value!r}, got {node.get('inputs')!r}"
                        )
                    node["inputs"] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target node not found: {node_id}")
            applied += 1
            continue

        # /nodes/<node_id>/outputs
        m = re.match(r"^/nodes/([^/]+)/outputs$", path)
        if m:
            node_id = m.group(1)
            found = False
            for node in updated.get("nodes", []):
                if node.get("id") == node_id:
                    if not _old_value_matches(node.get("outputs"), change.old_value):
                        raise ValueError(
                            f"repair old_value mismatch at {path}: "
                            f"expected {change.old_value!r}, got {node.get('outputs')!r}"
                        )
                    node["outputs"] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target node not found: {node_id}")
            applied += 1
            continue

        # /nodes/<node_id>/required
        m = re.match(r"^/nodes/([^/]+)/required$", path)
        if m:
            node_id = m.group(1)
            found = False
            for node in updated.get("nodes", []):
                if node.get("id") == node_id:
                    if not _old_value_matches(node.get("required"), change.old_value):
                        raise ValueError(
                            f"repair old_value mismatch at {path}: "
                            f"expected {change.old_value!r}, got {node.get('required')!r}"
                        )
                    node["required"] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target node not found: {node_id}")
            applied += 1
            continue

        # /nodes/<node_id>/degradation_policy
        m = re.match(r"^/nodes/([^/]+)/degradation_policy$", path)
        if m:
            node_id = m.group(1)
            found = False
            for node in updated.get("nodes", []):
                if node.get("id") == node_id:
                    if not _old_value_matches(node.get("degradation_policy"), change.old_value):
                        raise ValueError(
                            f"repair old_value mismatch at {path}: "
                            f"expected {change.old_value!r}, got {node.get('degradation_policy')!r}"
                        )
                    node["degradation_policy"] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target node not found: {node_id}")
            applied += 1
            continue

        # /components/<component_id>/root_node
        m = re.match(r"^/components/([^/]+)/root_node$", path)
        if m:
            comp_id = m.group(1)
            found = False
            for comp in updated.get("components", []):
                if comp.get("id") == comp_id:
                    if not _old_value_matches(comp.get("root_node"), change.old_value):
                        raise ValueError(
                            f"repair old_value mismatch at {path}: "
                            f"expected {change.old_value!r}, got {comp.get('root_node')!r}"
                        )
                    comp["root_node"] = change.new_value
                    found = True
                    break
            if not found:
                raise ValueError(f"repair target component not found: {comp_id}")
            applied += 1
            continue

        # /llm_validation_hints
        if path == "/llm_validation_hints":
            if not isinstance(change.new_value, dict):
                raise ValueError("/llm_validation_hints repair value must be dict")
            if not _old_value_matches(updated.get("llm_validation_hints"), change.old_value):
                raise ValueError(
                    f"repair old_value mismatch at {path}: "
                    f"expected {change.old_value!r}, got {updated.get('llm_validation_hints')!r}"
                )
            updated["llm_validation_hints"] = change.new_value
            applied += 1
            continue

        raise ValueError(f"unsupported repair path: {path}")

    if applied != len(patch.changes):
        raise ValueError(
            f"repair patch applied {applied} of {len(patch.changes)} change(s)"
        )

    return updated
