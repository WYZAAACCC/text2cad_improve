"""Generic deterministic tool registry; backend selection remains operator-owned."""

from dataclasses import dataclass
from typing import Any

from .backends import OPERATIONS
from .evidence import DomainReport, MeshReport, ResultReport, SolverReport
from .models import CFDError, Model


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    agent: str
    version: str
    output_model: type[Model] | None
    description: str


class ToolRegistry:
    def __init__(self, backend):
        self.backend = backend
        outputs = {
            "domain.construct": DomainReport,
            "mesh.generate": MeshReport,
            "solver.advance": SolverReport,
            "results.extract": ResultReport,
        }
        descriptions = {
            "domain.construct": "Import named BRep faces and construct declared full/extracted/outer/sector domain with native transfer history.",
            "mesh.generate": "Generate declared volume mesh, inflation and local size fields; export named zones and measured mesh quality.",
            "physics.configure": "Create declared materials, models and boundary conditions against proven named zones.",
            "solver.initialize": "Initialize a case using its exact validated spec and mesh.",
            "solver.advance": "Advance a bounded iteration chunk from a checkpoint and return raw evidence.",
            "solver.stop": "Stop/checkpoint the solver; no hidden daemon may survive.",
            "results.extract": "Apply declared surface reductions and export metrics with units.",
        }
        self.definitions = {
            name: ToolDefinition(
                name,
                agent,
                backend.capabilities.version,
                outputs.get(name),
                descriptions[name],
            )
            for name, agent in OPERATIONS.items()
        }

    def describe(self):
        return [
            {
                "name": d.name,
                "version": d.version,
                "agent": d.agent,
                "description": d.description,
                "output_schema": d.output_model.model_json_schema()
                if d.output_model
                else {"type": "object"},
            }
            for d in self.definitions.values()
        ]

    def invoke(
        self, name: str, agent: str, payload: dict[str, Any], job_dir, timeout_s
    ):
        definition = self.definitions.get(name)
        if definition is None or agent != definition.agent:
            raise CFDError("tool_not_allowed", "Tool/agent not registered", "tools")
        result = self.backend.execute(name, payload, job_dir, timeout_s)
        if definition.output_model:
            return definition.output_model.model_validate(result).model_dump(
                mode="json"
            )
        return result
