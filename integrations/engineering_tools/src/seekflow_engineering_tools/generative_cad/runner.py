"""Fixed runner harness for generative CAD graph execution.

The runner executes feature graph nodes through registered base operation handlers.
It never contains LLM-generated CadQuery code — it only calls registered handlers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GenerativeBuildContext:
    """Runtime context passed to base operation handlers."""

    out_step: Path
    metadata_path: Path
    workspace_root: Path
    bodies: dict[str, Any] = field(default_factory=dict)
    active_body_id: str | None = None
    frames: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    degraded_features: list[dict[str, Any]] = field(default_factory=list)
    operation_metrics: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GenerativeRunResult:
    """Result from a base runner execution."""

    ok: bool
    step_path: Path | None = None
    metadata_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    degraded_features: list[dict[str, Any]] = field(default_factory=list)
    operation_metrics: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def run_generative_cad_from_files(
    graph_path: str | Path,
    out_step: str | Path,
    metadata_path: str | Path,
) -> GenerativeRunResult:
    """Fixed harness entry point — loads graph JSON and delegates to base runners.

    This is the ONLY function that should be in a generated harness script.
    It loads the graph from JSON, resolves the base, and calls the base's run().
    """
    graph_path = Path(graph_path)
    out_step = Path(out_step)
    metadata_path = Path(metadata_path)

    if not graph_path.exists():
        return GenerativeRunResult(
            ok=False,
            error=f"Graph file not found: {graph_path}",
        )

    try:
        graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return GenerativeRunResult(
            ok=False,
            error=f"Failed to load graph JSON: {exc}",
        )

    # ── Resolve base ──
    from seekflow_engineering_tools.generative_cad.registry import BASE_REGISTRY

    nodes = graph_data.get("nodes", [])
    if not nodes:
        return GenerativeRunResult(
            ok=False,
            error="Feature graph has no nodes",
        )

    # Use the base_id from the first node (v0: single base per graph)
    base_id = nodes[0].get("base_id")
    if not base_id:
        return GenerativeRunResult(
            ok=False,
            error="First node has no base_id",
        )

    base = BASE_REGISTRY.get(base_id)
    if base is None:
        return GenerativeRunResult(
            ok=False,
            error=f"Unknown base: {base_id!r}",
        )

    workspace_root = out_step.parent

    # Verify all nodes use the same base (v0 constraint)
    for node in nodes:
        if node.get("base_id") != base_id:
            return GenerativeRunResult(
                ok=False,
                error=(
                    f"Node {node.get('id', '?')!r} uses base {node.get('base_id', '?')!r} "
                    f"but graph owner is {base_id!r}. v0 supports one base per graph."
                ),
            )

    context = GenerativeBuildContext(
        out_step=out_step,
        metadata_path=metadata_path,
        workspace_root=workspace_root,
    )

    return base.run(graph_data, context)
