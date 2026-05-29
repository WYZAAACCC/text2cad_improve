"""Base definition protocol for generative CAD grammar bases.

Bases are grammar, not part templates. Each base declares operations,
phase order, and provides validation/execution hooks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class OperationDefinition:
    """A single operation within a generative CAD base."""

    op: str
    phase: str
    params_model: type[BaseModel]
    description: str
    required_context_flags: tuple[str, ...] = ()
    produced_context_flags: tuple[str, ...] = ()
    optional: bool = False


class BaseDefinition(Protocol):
    """Protocol that every generative CAD base must satisfy."""

    base_id: str
    version: str
    phase_order: tuple[str, ...]
    operation_definitions: dict[str, OperationDefinition]

    def export_manifest(self) -> dict[str, Any]: ...
    def export_contract(self) -> dict[str, Any]: ...
    def validate_semantics(self, graph: dict[str, Any]) -> list[dict[str, Any]]: ...
    def preflight(self, graph: dict[str, Any]) -> list[dict[str, Any]]: ...
    def run(
        self, graph: dict[str, Any], context: GenerativeBuildContext
    ) -> GenerativeRunResult: ...


# Forward reference — resolved at runtime
from seekflow_engineering_tools.generative_cad.legacy.runner_v01 import (  # noqa: E402, F811
    GenerativeBuildContext,
    GenerativeRunResult,
)
