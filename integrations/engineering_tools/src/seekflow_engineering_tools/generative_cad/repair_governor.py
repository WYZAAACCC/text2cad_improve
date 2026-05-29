"""Repair governor — deterministic repair state tracking and stop conditions.

Prevents infinite repair loops. v0: returns diagnostics for external orchestrator.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field


class RepairPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_node: str
    changes: list[dict]
    reason: str


class RepairState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempts: int = 0
    max_attempts: int = 3
    graph_hashes: list[str] = Field(default_factory=list)
    error_signature_hashes: list[str] = Field(default_factory=list)
    last_stage_rank: int = 0


# Allowed JSON patch paths for repair
ALLOWED_REPAIR_PATHS = frozenset({
    "/feature_graph/nodes",
    "params",
    "depends_on",
    "required",
    "degradation_policy",
})

# Forbidden top-level keys to modify
FORBIDDEN_REPAIR_KEYS = frozenset({
    "ir_version",
    "generation_route",
    "selected_bases",
    "system_validation_contract",
    "safety",
})


def _hash_graph(spec) -> str:
    """Deterministic hash of the feature graph JSON."""
    import json
    graph_json = json.dumps(
        spec.feature_graph.model_dump(), sort_keys=True, default=str,
    )
    return "sha256:" + hashlib.sha256(graph_json.encode()).hexdigest()


def _hash_error_signature(issues: list[dict]) -> str:
    """Hash of error codes to detect repeated failures."""
    codes = sorted(set(i.get("code", "") for i in issues))
    sig = "|".join(codes)
    return "sha256:" + hashlib.sha256(sig.encode()).hexdigest()


def can_repair(state: RepairState, spec=None, issues: list[dict] | None = None) -> tuple[bool, str]:
    """Check whether repair is allowed.

    Returns (allowed: bool, reason: str).
    """
    if state.attempts >= state.max_attempts:
        return False, f"Max repair attempts ({state.max_attempts}) reached."

    if spec is not None:
        gh = _hash_graph(spec)
        if gh in state.graph_hashes:
            return False, "Graph hash repeated — repair loop detected."

    if issues is not None:
        eh = _hash_error_signature(issues)
        count = state.error_signature_hashes.count(eh)
        if count >= 2:
            return False, "Same error signature repeated twice — repair not helping."

    return True, ""


def apply_repair_patch(spec, patch: RepairPatch) -> tuple:
    """Apply a repair patch to the spec's feature graph.

    Returns (updated_spec, error_message).

    v0: validates patch targets but relies on external LLM to produce the patch.
    This function applies a validated patch, not trusts arbitrary input.
    """
    nodes = list(spec.feature_graph.nodes)
    target_found = False

    for i, node in enumerate(nodes):
        if node.id != patch.target_node:
            continue
        target_found = True

        node_dict = node.model_dump()

        for change in patch.changes:
            path = change.get("path", "")
            value = change.get("value")

            # Only allow whitelisted sub-paths
            if path == "params":
                if not isinstance(value, dict):
                    return spec, f"params must be dict, got {type(value).__name__}"
                node_dict["params"] = value
            elif path == "depends_on":
                if not isinstance(value, list):
                    return spec, f"depends_on must be list, got {type(value).__name__}"
                node_dict["depends_on"] = value
            elif path == "required":
                if not isinstance(value, bool):
                    return spec, f"required must be bool, got {type(value).__name__}"
                node_dict["required"] = value
            elif path == "degradation_policy":
                if value not in ("fail", "may_skip_with_warning"):
                    return spec, f"invalid degradation_policy: {value!r}"
                node_dict["degradation_policy"] = value
            else:
                return spec, f"Repair path {path!r} not in allowed repair scope."

        # Reconstruct node
        from seekflow_engineering_tools.generative_cad.ir import FeatureGraphNode
        try:
            nodes[i] = FeatureGraphNode.model_validate(node_dict)
        except Exception as exc:
            return spec, f"Repair patch produced invalid node: {exc}"

    if not target_found:
        return spec, f"Target node {patch.target_node!r} not found in feature graph."

    # Rebuild spec with updated nodes
    new_graph = spec.feature_graph.model_copy(update={"nodes": nodes})
    return spec.model_copy(update={"feature_graph": new_graph}), ""


def check_forbidden_modifications(spec_before, spec_after) -> list[str]:
    """Check that forbidden keys have not been modified by repair."""
    issues: list[str] = []
    for key in FORBIDDEN_REPAIR_KEYS:
        before = getattr(spec_before, key, None)
        after = getattr(spec_after, key, None)
        if before != after:
            issues.append(f"Forbidden key {key!r} was modified by repair.")
    return issues


def update_repair_state(
    state: RepairState,
    spec,
    issues: list[dict] | None = None,
    stage_rank: int = 0,
) -> RepairState:
    """Update repair state after an attempt."""
    gh = _hash_graph(spec)
    graph_hashes = list(state.graph_hashes) + [gh]

    error_hashes = list(state.error_signature_hashes)
    if issues is not None:
        error_hashes.append(_hash_error_signature(issues))

    return RepairState(
        attempts=state.attempts + 1,
        max_attempts=state.max_attempts,
        graph_hashes=graph_hashes,
        error_signature_hashes=error_hashes,
        last_stage_rank=stage_rank,
    )
