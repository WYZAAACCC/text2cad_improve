"""Shared helpers for sub-experiment suites (kept inside the isolated module)."""
from __future__ import annotations

import json
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..adapters import call_mcp_tool, load_design_families
from ..config import ExperimentConfig
from ..paths import experiment_output_root, task_gold_dir
from ..schemas import TaskSpec
from ..utils import atomic_write_json


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_id(prefix: str, **parts: Any) -> str:
    """Stable, human-readable record id: <prefix>_<sha1 of identity parts>."""
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def stamp_record(record: dict[str, Any], prefix: str, schema: str) -> dict[str, Any]:
    """Attach a uniform identity + timestamp + schema to a collected record."""
    identity = {k: v for k, v in record.items()
                if k not in ("record_id", "collected_at", "schema_version")}
    out = dict(record)
    out["record_id"] = out.get("record_id") or record_id(prefix, **identity)
    out["collected_at"] = out.get("collected_at") or iso_now()
    out["schema_version"] = out.get("schema_version") or schema
    return out


def collection_manifest(
    experiment_id: str,
    schema: str,
    records: list[dict[str, Any]],
    *,
    config: Any = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": schema,
        "experiment_id": experiment_id,
        "generated_at": iso_now(),
        "record_count": len(records),
        "record_ids": [r.get("record_id") for r in records if r.get("record_id")],
    }
    if config is not None:
        try:
            manifest["config"] = config.model_dump(mode="json")
        except Exception:  # noqa: BLE001
            manifest["config"] = str(config)
    if extra:
        manifest["extra"] = extra
    return manifest


def write_collection(
    root: Path,
    experiment_id: str,
    schema: str,
    records: list[dict[str, Any]],
    aggregate: dict[str, Any] | None = None,
    *,
    config: Any = None,
    prefix: str = "rec",
) -> dict[str, Path]:
    """Write records.json + manifest.json + report.md with uniform formatting."""
    root.mkdir(parents=True, exist_ok=True)
    stamped = [stamp_record(r, prefix, schema) for r in records]
    records_path = atomic_write_json(root / "records.json", stamped)
    manifest = collection_manifest(experiment_id, schema, stamped, config=config)
    if aggregate is not None:
        manifest["aggregate"] = aggregate
    manifest_path = atomic_write_json(root / "manifest.json", manifest)
    if aggregate is not None:
        md = report_markdown(experiment_id, schema, aggregate, stamped)
        md_path = root / "report.md"
        md_path.write_text(md, encoding="utf-8")
    else:
        md_path = root / "report.md"
        md_path.write_text(f"# {experiment_id}\n\nschema: {schema}\n", encoding="utf-8")
    return {"records": records_path, "manifest": manifest_path, "report": md_path}


def report_markdown(
    experiment_id: str,
    schema: str,
    aggregate: dict[str, Any],
    records: list[dict[str, Any]],
) -> str:
    lines = [
        f"# {experiment_id}",
        "",
        f"- schema_version: `{schema}`",
        f"- generated_at: {iso_now()}",
        f"- records: {len(records)}",
        "",
    ]
    for key, value in aggregate.items():
        if key == "rows" and isinstance(value, list):
            for row in value:
                if not isinstance(row, dict):
                    continue
                lines.append(f"## {row.get('method_id') or row.get('category') or row.get('level') or row.get('interface') or row.get('margin_group') or row.get('group') or 'overall'}")
                lines.append("")
                lines.append("| 指标 | 值 |")
                lines.append("|---|---|")
                for k, v in row.items():
                    if k in ("method_id", "category", "level", "interface", "margin_group", "group"):
                        continue
                    lines.append(f"| {k} | {v} |")
                lines.append("")
        else:
            lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## 记录示例")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(records[0], ensure_ascii=False, indent=2)[:1200] if records else "[]")
    lines.append("```")
    return "\n".join(lines)


def suite_root(config: ExperimentConfig, suite: str) -> Path:
    root = experiment_output_root(config) / "suites" / suite
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_suite_tasks(path: Path, tasks: Iterable[dict[str, Any]]) -> Path:
    return atomic_write_json(path, list(tasks))


def load_suite_tasks(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_golden(task: TaskSpec, config: ExperimentConfig) -> Path:
    """Build golden artifacts for a benchmark task if missing, then return dir."""
    gold_dir = task_gold_dir(task.task_id, config)
    if not (gold_dir / "canonical_ir.json").exists():
        from ..tasks.golden_builder import build_golden_for_task
        build_golden_for_task(task, config)
    return gold_dir


def copy_run_dir(src: Path, dst: Path) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("raw_fixed.json", "canonical_ir.json", "output.step",
                 "output.metadata.json", "validation_seed.json"):
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    return dst


_QUALITY_SUBSET = [
    "check_solid_validity",
    "check_degenerate_geometry",
    "validate_slot_step_roundtrip",
    "check_slot_pitch_and_ligament",
    "check_adjacent_feature_clearance",
    "validate_slot_pattern_periodicity",
]


def quality_ok(base_dir: Path) -> dict[str, Any]:
    try:
        return call_mcp_tool("generate_quality_report", {
            "base_dir": str(base_dir),
            "tool_subset": _QUALITY_SUBSET,
        })
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "failed_checks": [f"gate_error:{exc}"]}


def families(config: ExperimentConfig) -> dict[str, dict[str, Any]]:
    return load_design_families()
