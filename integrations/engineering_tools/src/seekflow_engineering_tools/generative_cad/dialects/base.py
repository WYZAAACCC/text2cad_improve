"""BaseDialect protocol — every dialect must implement this."""

from __future__ import annotations

from typing import Any, Protocol

from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalComponent, CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


class BaseDialect(Protocol):
    dialect_id: str
    version: str
    phase_order: tuple[str, ...]

    def manifest(self) -> dict[str, Any]: ...
    def contract(self) -> dict[str, Any]: ...
    def op_specs(self) -> dict[tuple[str, str], OperationSpec]: ...

    def default_op_version(self, op: str) -> str: ...

    def get_op_spec(self, op: str, op_version: str | None = None) -> OperationSpec: ...

    def validate_component(
        self,
        component: CanonicalComponent,
        nodes: list[CanonicalNode],
    ) -> ValidationReport: ...

    def preflight_component(
        self,
        component: CanonicalComponent,
        nodes: list[CanonicalNode],
    ) -> ValidationReport: ...

    def run_component(
        self,
        component: CanonicalComponent,
        nodes: list[CanonicalNode],
        ctx: RuntimeContext,
    ) -> dict[str, str]: ...
