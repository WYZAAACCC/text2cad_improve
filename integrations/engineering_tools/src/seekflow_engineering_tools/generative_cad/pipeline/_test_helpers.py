"""Private test helpers — NOT for production use.

Provides an unverified canonical runner entrypoint that bypasses the
validation_seed requirement. Only tests may import this module.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.pipeline.artifact import build_canonical_step_artifact
from seekflow_engineering_tools.generative_cad.pipeline.metadata import build_generative_metadata
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.runtime.results import GcadRunResult


def _run_canonical_gcad_unverified_for_tests(
    canonical: CanonicalGcadDocument,
    out_step: str | Path,
    metadata_path: str | Path,
) -> GcadRunResult:
    """Test-only entrypoint — runs canonical IR without validation_seed.

    DO NOT USE IN PRODUCTION. Validation proof is required for all
    production paths. This exists solely so tests can exercise runner
    internals without constructing a full ValidationBundle.
    """
    out_step = Path(out_step)
    metadata_path = Path(metadata_path)
    ctx = RuntimeContext(
        out_step=out_step,
        metadata_path=metadata_path,
        workspace_root=out_step.parent,
    )
    ctx.warnings.append(
        "UNVERIFIED RUNNER (test-only): executed without validation_seed."
    )

    try:
        from seekflow_engineering_tools.generative_cad.pipeline.run import (
            _run_components,
            _run_composition_or_select_final,
        )
        _run_components(canonical, ctx)
        final_handle_id = _run_composition_or_select_final(canonical, ctx)

        from seekflow_engineering_tools.generative_cad.runtime.postconditions import (
            validate_runtime_postconditions,
        )
        runtime_pc = validate_runtime_postconditions(canonical, ctx, final_handle_id)
        if not runtime_pc["ok"]:
            return GcadRunResult(
                ok=False,
                error="runtime postconditions failed: "
                + "; ".join(i["message"] for i in runtime_pc["issues"]),
                warnings=ctx.warnings,
                degraded_features=ctx.degraded_features,
                operation_metrics=ctx.operation_metrics,
            )

        from seekflow_engineering_tools.generative_cad.pipeline.run import (
            _export_final_solid,
        )
        _export_final_solid(final_handle_id, ctx)

        validation = {"runtime_postconditions": runtime_pc}

        metadata = build_generative_metadata(
            canonical=canonical, ctx=ctx, validation=validation,
        )
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        artifact = build_canonical_step_artifact(
            canonical=canonical, step_path=out_step,
            metadata_path=metadata_path,
            validation=metadata["validation"],
            ctx=ctx,
        )

        return GcadRunResult(
            ok=True,
            step_path=out_step,
            metadata_path=metadata_path,
            artifact=artifact,
            metadata=metadata,
            warnings=ctx.warnings,
            degraded_features=ctx.degraded_features,
            operation_metrics=ctx.operation_metrics,
        )

    except Exception as exc:
        return GcadRunResult(
            ok=False,
            error=str(exc),
            warnings=ctx.warnings,
            degraded_features=ctx.degraded_features,
            operation_metrics=ctx.operation_metrics,
        )
