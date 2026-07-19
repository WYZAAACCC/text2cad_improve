"""CAE bridge — resolve NamedTopologySet to mesh-ready faces with preflight gate.

Phase 6 core: replaces coordinate-based RegionDef with persistent topology IDs.
The preflight gate blocks ANSYS execution if any high-stakes topology reference
(unresolved, deleted, ambiguous) would cause incorrect load/constraint application.

Usage (from fea_pipeline.py, when ANSYS is available):
    from seekflow_engineering_tools.generative_cad.topology.cae_bridge import (
        cae_preflight_gate, resolve_named_set_to_faces,
    )
    gate = cae_preflight_gate(named_sets, registry)
    if not gate.ok:
        raise RuntimeError(f"CAE preflight failed: {gate.summary}")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.topology.models import NamedTopologySet
from seekflow_engineering_tools.generative_cad.topology.policies import (
    _QUALITY_RANK,
    get_consumer_policy,
    resolution_meets_quality,
)

if TYPE_CHECKING:
    from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry


# ═══════════════════════════════════════════════════════════════════════════════
# CAE-specific result models
# ═══════════════════════════════════════════════════════════════════════════════


class CaeResolvedSet(BaseModel):
    """Result of resolving one NamedTopologySet through the TopologyRegistry."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="NamedTopologySet name, e.g. 'disk.center_bore.wall'")
    persistent_ids: list[str] = Field(description="Input persistent topology IDs")
    semantic_purpose: str = Field(description="load | constraint | contact | mesh_control")
    resolution_quality: str = Field(description="Worst (minimum) resolution method — CAE gate uses this")

    resolved_count: int = 0
    unresolved_count: int = 0
    deleted_count: int = 0
    ambiguous_count: int = 0

    gate_result: Literal["pass", "fail", "warn"] = "pass"

    issues: list[dict] = Field(default_factory=list)


class CaePreflightResult(BaseModel):
    """Result of preflight gate check across all NamedTopologySets.

    If ok=False, ANSYS execution MUST be blocked — applying loads/constraints
    to incorrectly resolved faces is a safety hazard.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool = False
    resolved_sets: list[CaeResolvedSet] = Field(default_factory=list)
    blocked_sets: list[dict] = Field(default_factory=list)
    summary: str = ""
    total_sets: int = 0
    passed_sets: int = 0
    failed_sets: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Resolution and gate functions
# ═══════════════════════════════════════════════════════════════════════════════


def resolve_named_set_to_faces(
    named_set: NamedTopologySet,
    registry: "TopologyRegistry",
    *,
    object_store: Any = None,
    binding_service: Any = None,
) -> CaeResolvedSet:
    """Resolve a NamedTopologySet through the TopologyRegistry.

    Checks each persistent_id: active/deleted/ambiguous/unresolved.
    Aggregates counts and determines the best resolution quality.

    Args:
        named_set: The named topology set to resolve.
        registry: TopologyRegistry with entity records.

    Returns:
        CaeResolvedSet with resolution status and issue details.
    """
    issues: list[dict] = []
    resolved = 0
    unresolved = 0
    deleted = 0
    ambiguous = 0
    worst_quality = "exact_kernel_history"  # start high, degraded by any lower quality

    # V3: empty persistent_ids → fail (cannot apply load/constraint to nothing)
    if not named_set.persistent_ids:
        return CaeResolvedSet(
            name=named_set.name,
            persistent_ids=[],
            semantic_purpose=named_set.semantic_purpose,
            resolution_quality="unresolved",
            gate_result="fail",
            issues=[{
                "code": "TOPOLOGY_EMPTY_SET",
                "severity": "error",
                "message": f"NamedTopologySet '{named_set.name}' has no persistent_ids — "
                           f"cannot apply {named_set.semantic_purpose} to zero entities.",
            }],
        )

    for pid in named_set.persistent_ids:
        result = registry.resolve(
            pid, object_store=object_store, binding_service=binding_service,
        )

        if result.status == "exact":
            resolved += 1
            worst_quality = _worst_of(worst_quality, result.method)
        elif result.status == "set":
            resolved += len(result.resolved_entity_ids)
            worst_quality = _worst_of(worst_quality, "set_expansion")
            issues.append({
                "code": "TOPOLOGY_SET_EXPANSION",
                "persistent_id": pid,
                "message": f"ID '{pid}' resolved to a set of {len(result.resolved_entity_ids)} entities",
            })
        elif result.status == "deleted":
            deleted += 1
            issues.append({
                "code": "TOPOLOGY_REF_DELETED",
                "persistent_id": pid,
                "severity": "error",
                "message": f"ID '{pid}' was deleted — cannot apply CAE load/constraint",
            })
        elif result.status == "ambiguous":
            ambiguous += 1
            issues.append({
                "code": "TOPOLOGY_REF_AMBIGUOUS",
                "persistent_id": pid,
                "severity": "error",
                "message": f"ID '{pid}' is ambiguous — cannot determine correct face for CAE",
            })
        else:
            unresolved += 1
            issues.append({
                "code": "TOPOLOGY_REF_UNRESOLVED",
                "persistent_id": pid,
                "severity": "error",
                "message": f"ID '{pid}' not found in topology registry",
            })

    # Determine gate result
    consumer_policy = get_consumer_policy(_purpose_to_consumer(named_set.semantic_purpose))

    if unresolved > 0 or deleted > 0:
        gate_result = "fail"
    elif ambiguous > 0 and not consumer_policy.allows_ambiguity:
        gate_result = "fail"
    elif ambiguous > 0:
        gate_result = "warn"
    elif not resolution_meets_quality(worst_quality, consumer_policy.minimum_quality):
        gate_result = "fail"
        issues.append({
            "code": "TOPOLOGY_QUALITY_INSUFFICIENT",
            "severity": "error",
            "message": (
                f"Resolution quality '{worst_quality}' does not meet "
                f"consumer minimum '{consumer_policy.minimum_quality.value}' "
                f"for purpose '{named_set.semantic_purpose}'"
            ),
        })
    # V3: enforce required_resolution — exact mode rejects non-exact results
    elif named_set.required_resolution == "exact" and worst_quality != "exact_kernel_history":
        gate_result = "fail"
        issues.append({
            "code": "TOPOLOGY_RESOLUTION_NOT_EXACT",
            "severity": "error",
            "message": (
                f"NamedTopologySet '{named_set.name}' requires exact resolution "
                f"but best quality is '{worst_quality}'"
            ),
        })
    else:
        gate_result = "pass"

    return CaeResolvedSet(
        name=named_set.name,
        persistent_ids=named_set.persistent_ids,
        semantic_purpose=named_set.semantic_purpose,
        resolution_quality=worst_quality,
        resolved_count=resolved,
        unresolved_count=unresolved,
        deleted_count=deleted,
        ambiguous_count=ambiguous,
        gate_result=gate_result,
        issues=issues,
    )


def cae_preflight_gate(
    named_sets: list[NamedTopologySet],
    registry: "TopologyRegistry",
) -> CaePreflightResult:
    """Preflight gate — blocks ANSYS execution if any topology ref is unsafe.

    Fail conditions (any of these → block execution):
      - Any persistent_id in a high-stakes set is unresolved
      - Any persistent_id in a high-stakes set is deleted
      - Any persistent_id in a load/constraint/contact set is ambiguous
      - Resolution quality below consumer minimum for that purpose

    Pass: all IDs resolve with adequate quality, no ambiguity in critical sets.

    Args:
        named_sets: List of NamedTopologySet (loads, constraints, contacts, mesh).
        registry: TopologyRegistry with entity records.

    Returns:
        CaePreflightResult with per-set resolution and overall gate status.
    """
    resolved = []
    failed = 0
    for ns in named_sets:
        result = resolve_named_set_to_faces(ns, registry)
        resolved.append(result)
        if result.gate_result == "fail":
            failed += 1

    blocked = [
        {"name": r.name, "issues": r.issues}
        for r in resolved if r.gate_result == "fail"
    ]

    if failed > 0:
        summary = (
            f"CAE preflight FAILED: {failed}/{len(named_sets)} sets blocked. "
            f"Fix unresolved/deleted/ambiguous topology references before "
            f"running ANSYS. Blocked: {[b['name'] for b in blocked]}"
        )
        ok = False
    else:
        warnings = [r for r in resolved if r.gate_result == "warn"]
        if warnings:
            summary = (
                f"CAE preflight PASSED with {len(warnings)} warning(s). "
                f"Warnings: {[w.name for w in warnings]}"
            )
        else:
            summary = f"CAE preflight PASSED: all {len(named_sets)} sets resolved."
        ok = True

    return CaePreflightResult(
        ok=ok,
        resolved_sets=resolved,
        blocked_sets=blocked,
        summary=summary,
        total_sets=len(named_sets),
        passed_sets=len(named_sets) - failed,
        failed_sets=failed,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _worst_of(a: str, b: str) -> str:
    """Return the lower-quality of two resolution methods (PR 12: worst quality gate)."""
    return a if _QUALITY_RANK.get(a, 0) <= _QUALITY_RANK.get(b, 0) else b


def _purpose_to_consumer(purpose: str) -> str:
    """Map NamedTopologySet.semantic_purpose → consumer_type for policy lookup."""
    mapping = {
        "load": "cae_load",
        "constraint": "cae_constraint",
        "contact": "cae_contact",
        "mesh_control": "cae_mesh_control",
        "result_path": "debug_visualization",
        "inspection": "debug_visualization",
    }
    return mapping.get(purpose, "debug_visualization")
