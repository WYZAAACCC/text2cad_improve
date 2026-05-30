"""OperationResult ABI — strongly-typed operation handler output.

Replaces legacy dict[str, str] returns with structured results that carry
outputs, warnings, degraded features, metrics, and postcondition results.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode


class OperationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    handle_id: str
    value_type: str


class OperationMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    op: str
    elapsed_ms: float | None = None
    details: dict = Field(default_factory=dict)


class OperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    outputs: list[OperationOutput]
    warnings: list[str] = Field(default_factory=list)
    degraded_features: list[dict] = Field(default_factory=list)
    metrics: list[OperationMetric] = Field(default_factory=list)
    postcondition_results: list[dict] = Field(default_factory=list)


# ── Legacy adapter ──


def adapt_legacy_handler_result(
    result: dict[str, str],
    node: CanonicalNode,
) -> OperationResult:
    """Adapt a legacy dict[str,str] handler result to OperationResult."""
    declared_outputs: dict[str, str] = {}
    for out_decl in node.outputs:
        declared_outputs[out_decl.name] = out_decl.type

    outputs = [
        OperationOutput(name=name, handle_id=handle_id, value_type=declared_outputs.get(name, "unknown"))
        for name, handle_id in result.items()
    ]
    return OperationResult(ok=True, outputs=outputs)
