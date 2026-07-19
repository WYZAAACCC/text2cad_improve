"""RuntimeContext — binds node/component outputs to handle ids for resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from seekflow_engineering_tools.generative_cad.runtime.cadquery_runtime import CadQueryRuntime
from seekflow_engineering_tools.generative_cad.runtime.geometry_runtime import GeometryRuntime
from seekflow_engineering_tools.generative_cad.runtime.object_store import RuntimeObjectStore
from seekflow_engineering_tools.generative_cad.runtime.tolerance import DEFAULT_TOLERANCE, GeometryTolerance
from seekflow_engineering_tools.generative_cad.runtime.cache import OperationCache
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry


@dataclass
class RuntimeContext:
    out_step: Path
    metadata_path: Path
    workspace_root: Path
    object_store: RuntimeObjectStore = field(default_factory=RuntimeObjectStore)
    topology_registry: TopologyRegistry = field(default_factory=TopologyRegistry)
    geometry_runtime: GeometryRuntime = field(default_factory=CadQueryRuntime)
    tolerance: GeometryTolerance = field(default=DEFAULT_TOLERANCE)
    cache: OperationCache = field(default_factory=OperationCache)

    node_outputs: dict[str, dict[str, str]] = field(default_factory=dict)
    component_outputs: dict[str, dict[str, str]] = field(default_factory=dict)

    warnings: list[str] = field(default_factory=list)
    degraded_features: list[dict[str, Any]] = field(default_factory=list)
    operation_metrics: list[dict[str, Any]] = field(default_factory=list)

    runner_version: str = "0.2.0"

    # v6: Spatial intent resolution
    spatial_placements: dict[str, Any] = field(default_factory=dict)
    spatial_audit_report: Any = None
    spatial_contract_hash: str | None = None
    # v6.3: Track post-placement bboxes for spatial audit
    placed_component_bboxes: dict[str, Any] = field(default_factory=dict)
    # v6.3: Enforce strict geometry semantics (reject ambiguous legacy hole params)
    strict_geometry_semantics: bool = True
    # v6.3: Compiler middle-end diagnostics (populated by CompilerModule)
    compiler_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    # v6.3: Planning report from compiler middle-end (Phase 3+)
    planning_report: dict[str, Any] | None = None
    # ── Document identity (v2 persistent topology) ──
    document_id: str = ""
    canonical_graph_hash: str = ""

    # ── Persistent topology (Phase 1+) ──
    topology_events: list[dict[str, Any]] = field(default_factory=list)
    topology_warnings: list[dict[str, Any]] = field(default_factory=list)
    topology_validation: dict[str, Any] = field(default_factory=dict)

    # v6.3 Phase 2: Per-operation geometry health records
    # Key: "{node_id}.{output_name}", Value: GeometryHealth.model_dump()
    geometry_health_log: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Per-component mutable state (workplane, last_point, etc.)
    # Key: component_id → {field_name: value}
    component_state: dict[str, dict[str, object]] = field(default_factory=dict)

    @property
    def geometry_runtime_name(self) -> str:
        return self.geometry_runtime.runtime_id

    @property
    def geometry_runtime_version(self) -> str:
        return self.geometry_runtime.runtime_version

    def bind_node_output(self, node_id: str, output_name: str, handle_id: str) -> None:
        self.node_outputs.setdefault(node_id, {})[output_name] = handle_id

    def resolve_node_output(self, node_id: str, output_name: str) -> str:
        try:
            return self.node_outputs[node_id][output_name]
        except KeyError as exc:
            raise KeyError(f"missing node output {node_id}.{output_name}") from exc

    def bind_component_output(self, component_id: str, output_name: str, handle_id: str) -> None:
        self.component_outputs.setdefault(component_id, {})[output_name] = handle_id

    def resolve_component_output(self, component_id: str, output_name: str) -> str:
        try:
            return self.component_outputs[component_id][output_name]
        except KeyError as exc:
            raise KeyError(f"missing component output {component_id}.{output_name}") from exc

    def set_component_state(self, component_id: str, key: str, value: object) -> None:
        self.component_state.setdefault(component_id, {})[key] = value

    def get_component_state(self, component_id: str, key: str, default: object = None) -> object:
        return self.component_state.get(component_id, {}).get(key, default)

    def topology_transaction(self):
        """Create a topology transaction for atomic registry updates.

        V3: Transaction carries ObjectStore reference for geometry verification.
        Before commit, verifies that all body handles in the delta exist in
        the ObjectStore (preventing split-brain: Registry with records for
        non-existent bodies).

        Usage:
            with ctx.topology_transaction() as tx:
                tx.register_entity(rec)
                tx.apply_delta(delta)
            # Automatically validates integrity and commits on success,
            # rolls back on exception.
        """
        from seekflow_engineering_tools.generative_cad.topology.transaction import (
            TopologyTransaction,
        )
        return TopologyTransaction(
            self.topology_registry,
            object_store=self.object_store,
        )
