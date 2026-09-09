"""Report writer producing CSV, JSON, and Markdown summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .utils import atomic_write_json


def _markdown_table(rows: Iterable[dict[str, Any]]) -> str:
    rows = list(rows)
    if not rows:
        return "_no rows_"
    headers = list(rows[0].keys())
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def write_report(
    aggregate: dict[str, Any],
    stats: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = {"aggregate": aggregate, "stats": stats}
    json_path = atomic_write_json(out / "report.json", report)

    try:
        import pandas as pd
        csv_path = out / "report.csv"
        pd.DataFrame(aggregate.get("methods", [])).to_csv(csv_path, index=False)
    except Exception:
        csv_path = out / "report.csv"
        csv_path.write_text(json.dumps(aggregate.get("methods", [])), encoding="utf-8")

    sections = ["# Main Experiment Report\n"]
    sections.append("## Methods\n")
    sections.append(_markdown_table(aggregate.get("methods", [])))
    sections.append("\n## Levels\n")
    sections.append(_markdown_table(aggregate.get("levels", [])))
    sections.append("\n## Slot / No Slot\n")
    sections.append(_markdown_table(aggregate.get("slots", [])))
    sections.append("\n## Statistics\n")
    sections.append("```json\n" + json.dumps(stats, ensure_ascii=False, indent=2) + "\n```\n")
    md_path = out / "report.md"
    md_path.write_text("\n".join(sections), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": md_path}
