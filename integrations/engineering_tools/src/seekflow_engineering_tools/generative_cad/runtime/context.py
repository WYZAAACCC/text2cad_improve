"""RuntimeContext — binds node/component outputs to handle ids for resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from seekflow_engineering_tools.generative_cad.runtime.cadquery_runtime import CadQueryRuntime
from seekflow_engineering_tools.generative_cad.runtime.geometry_runtime import GeometryRuntime
from seekflow_engineering_tools.generative_cad.runtime.object_store import RuntimeObjectStore


@dataclass
class RuntimeContext:
    out_step: Path
    metadata_path: Path
    workspace_root: Path
    object_store: RuntimeObjectStore = field(default_factory=RuntimeObjectStore)
    geometry_runtime: GeometryRuntime = field(default_factory=CadQueryRuntime)

    node_outputs: dict[str, dict[str, str]] = field(default_factory=dict)
    component_outputs: dict[str, dict[str, str]] = field(default_factory=dict)

    warnings: list[str] = field(default_factory=list)
    degraded_features: list[dict[str, Any]] = field(default_factory=list)
    operation_metrics: list[dict[str, Any]] = field(default_factory=list)

    runner_version: str = "0.2.0"

    @property
    def geometry_runtime_name(self) -> str:
        return self.geometry_runtime.runtime_id

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
