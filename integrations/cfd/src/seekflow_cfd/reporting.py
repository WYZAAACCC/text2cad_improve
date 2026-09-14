"""Portable JSON/CSV/SVG reports and experiment aggregation (no plotting dependency)."""

import csv
import html
import json
import math
from collections import Counter
from pathlib import Path

from .storage import atomic_json


def write_report(job: Path, record: dict, samples: list[dict]):
    keys = sorted({k for s in samples for k in s["residuals"]})
    with (job / "residuals.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["iteration", "physical_time_s", *keys])
        for s in samples:
            writer.writerow(
                [
                    s["iteration"],
                    s["physical_time_s"],
                    *[s["residuals"].get(k, "") for k in keys],
                ]
            )
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="880" height="400" viewBox="0 0 880 400">',
        '<rect width="880" height="400" fill="white"/>',
        '<text x="30" y="25" font-family="sans-serif" font-size="16">'
        + (
            "MOCK synthetic residuals"
            if record["is_mock"]
            else "Solver residual evidence"
        )
        + "</text>",
    ]
    if samples:
        ymax = max(s["iteration"] for s in samples)
        for j, key in enumerate(keys):
            color = ["#1f77b4", "#e6550d", "#238b45", "#756bb1", "#636363"][j % 5]
            points = " ".join(
                f"{50 + 650 * s['iteration'] / ymax:.1f},{330 - 22 * (max(-12, min(2, math.log10(max(s['residuals'].get(key, 1), 1e-12))))) - 264:.1f}"
                for s in samples
            )
            svg.append(
                f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.5"/>'
            )
            svg.append(
                f'<text x="715" y="{55 + 20 * j}" fill="{color}" font-family="sans-serif" font-size="12">{html.escape(key)}</text>'
            )
        for exponent in range(-12, 3, 2):
            y = 66 - 22 * exponent
            svg.append(
                f'<text x="2" y="{y}" font-family="sans-serif" font-size="10">1e{exponent}</text>'
            )
        svg.append(
            f'<text x="300" y="385" font-family="sans-serif">Iteration (last: {ymax})</text>'
        )
    svg.append("</svg>")
    (job / "residuals.svg").write_text("\n".join(svg), encoding="utf-8")
    lines = [
        "# CFD 仿真记录",
        "",
        f"- record_id: `{record['record_id']}`",
        f"- 状态：{record['status']}",
        f"- 数据来源：{'Mock 合成数据，不是物理仿真' if record['is_mock'] else '真实后端'}",
        f"- CAD revision: `{record['cad_revision_id']}`",
        f"- Spec SHA-256: `{record['simulation_spec_hash']}`",
        f"- 耗时：{record['elapsed_s']:.3f} s",
        "",
        "## 结果",
        "",
        "| 指标 | 数值 | 单位 | 边界 |",
        "| --- | ---: | --- | --- |",
    ]
    for name, metric in record["metrics"].items():
        lines.append(
            f"| {name} | {metric['value']} | {metric['unit']} | {metric['boundary']} |"
        )
    lines.extend(
        [
            "",
            "## 验证与限制",
            "",
            "网格无关性未由单次求解证明；需要独立三网格比较。",
            "",
        ]
    )
    lines.extend("- " + warning for warning in record["warnings"])
    if record["error_message"]:
        lines.extend(["", "失败原因：" + record["error_message"]])
    lines.extend(
        [
            "",
            "![残差证据](residuals.svg)",
            "",
            "完整证据：record.json、events.jsonl、calls/、manifest.json。",
        ]
    )
    (job / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def aggregate(root: Path):
    records = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((root / "jobs").glob("*/record.json"))
    ]
    counts = dict(Counter(r["status"] for r in records))
    real = [r for r in records if not r["is_mock"]]
    summary = {
        "count": len(records),
        "status_counts": counts,
        "real_count": len(real),
        "real_success_rate": sum(r["status"] == "success" for r in real) / len(real)
        if real
        else None,
        "mean_elapsed_s": sum(r["elapsed_s"] for r in records) / len(records)
        if records
        else None,
        "failure_codes": dict(
            Counter(r["diagnostic"]["code"] for r in records if r["diagnostic"])
        ),
    }
    atomic_json(root / "records.json", records)
    atomic_json(root / "summary.json", summary)
    return summary
