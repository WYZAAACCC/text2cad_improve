"""Build golden reference artifacts for a task from deterministic templates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..adapters import build_template_document
from ..config import ExperimentConfig
from ..paths import task_gold_dir
from ..schemas import TaskSpec
from ..utils import atomic_write_json


def build_golden_for_task(
    task_spec: TaskSpec,
    config: ExperimentConfig,
    *,
    run_mcp_gate: bool = True,
) -> dict[str, Any]:
    gold_dir = task_gold_dir(task_spec.task_id, config)
    gold_dir.mkdir(parents=True, exist_ok=True)

    raw = build_template_document(task_spec.normalized_params)
    atomic_write_json(gold_dir / "llm_raw.json", raw)
    atomic_write_json(gold_dir / "raw_fixed.json", raw)

    from seekflow_engineering_tools.generative_cad.validation.pipeline import (
        validate_and_canonicalize_with_bundle,
    )
    from seekflow_engineering_tools.generative_cad.pipeline.run import (
        run_canonical_gcad,
    )

    canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
    if canonical is None or not report.ok:
        errors = "; ".join(i.message for i in report.issues if i.severity == "error")
        raise RuntimeError(f"golden validation failed: {errors}")

    canonical_path = gold_dir / "canonical_ir.json"
    canonical_path.write_text(canonical.model_dump_json(indent=2), encoding="utf-8")
    seed_path = gold_dir / "validation_seed.json"
    seed_path.write_text(
        json.dumps(bundle.to_metadata_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    step_path = gold_dir / "output.step"
    metadata_path = gold_dir / "output.metadata.json"
    result = run_canonical_gcad(
        canonical,
        out_step=step_path,
        metadata_path=metadata_path,
        validation_seed=bundle.to_metadata_dict(),
        canonical_ir_path=canonical_path,
        validation_seed_path=seed_path,
        require_full_validation_seed=False,
    )
    if not result.ok:
        raise RuntimeError(f"golden runtime failed: {result.error}")

    summary: dict[str, Any] = {
        "task_id": task_spec.task_id,
        "ok": True,
        "canonical_ir": str(canonical_path),
        "step": str(step_path),
        "metadata": str(metadata_path),
        "key_dimensions": [d.model_dump(mode="json") for d in task_spec.gold.key_dimensions],
    }
    if task_spec.gold.slot_reference is not None:
        summary["slot_reference"] = task_spec.gold.slot_reference.model_dump(mode="json")

    if run_mcp_gate:
        try:
            from ..pipeline import run_mcp_quality_gate
            gate = run_mcp_quality_gate(gold_dir)
            atomic_write_json(gold_dir / "mcp_gate.json", gate)
            summary["mcp_gate"] = gate["summary"]
            if not gate["summary"]["ok"]:
                summary["ok"] = False
        except Exception as exc:  # noqa: BLE001
            summary["mcp_gate_error"] = str(exc)

    atomic_write_json(gold_dir / "golden.json", summary)
    return summary


def build_all_golden(
    tasks: list[TaskSpec],
    config: ExperimentConfig,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected = tasks[:limit] if limit is not None else tasks
    results = []
    for task in selected:
        results.append(build_golden_for_task(task, config))
    return results
