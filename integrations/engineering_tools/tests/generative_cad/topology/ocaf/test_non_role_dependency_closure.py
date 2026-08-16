"""Non-role selections can resolve a component terminal feature."""

from __future__ import annotations

from pathlib import Path

from seekflow_engineering_tools.generative_cad.pipeline.run import (
    _resolve_component_terminal_node,
)
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.topology.ocaf.capture_session import (
    CaptureSession,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    LiveEvolutionBatch,
    TopologyCaptureScope,
)


def test_terminal_node_resolves_from_capture_order():
    ctx = RuntimeContext(
        out_step=Path("out.step"),
        metadata_path=Path("meta.json"),
        workspace_root=Path("."),
    )
    ctx.capture_session = CaptureSession()
    ctx.capture_session.stage(LiveEvolutionBatch(
        scope=TopologyCaptureScope(node_id="n_first", component_id="comp_a"),
    ))
    ctx.capture_session.stage(LiveEvolutionBatch(
        scope=TopologyCaptureScope(node_id="n_last", component_id="comp_a"),
    ))
    assert _resolve_component_terminal_node(ctx, "comp_a") == "n_last"
