"""Write full-40 rerun stats and a readable Markdown report."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output" / "full_40_rerun"


def main() -> None:
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    rows = summary["records"]
    ok_rows = [r for r in rows if r["ok"]]
    slot_rows = [r for r in rows if r.get("slot_haus_mm") is not None]
    disc_haus = [r["disc_haus_mm"] for r in ok_rows if r.get("disc_haus_mm") is not None]

    stats = {
        "n": summary["n"],
        "ok": summary["ok"],
        "rate": summary["rate"],
        "by_level": summary["by_level"],
        "vol_mean_pct": summary["vol_mean"],
        "surf_mean_pct": summary["surf_mean"],
        "key_mean_pct": summary["key_mean"],
        "step_pass": summary["step_pass"],
        "slot_haus_mean_mm": statistics.fmean(r["slot_haus_mm"] for r in slot_rows) if slot_rows else None,
        "slot_haus_max_mm": max(r["slot_haus_mm"] for r in slot_rows) if slot_rows else None,
        "slot_n": len(slot_rows),
        "disc_haus_mean_mm": statistics.fmean(disc_haus) if disc_haus else None,
        "disc_haus_max_mm": max(disc_haus) if disc_haus else None,
        "key_nonzero": [(r["task"], r["key"]) for r in rows
                        if r.get("key") not in (None, 0)],
    }
    (OUT / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Full 40 Task Rerun (seed 8)",
        "",
        f"- Success: {summary['ok']}/{summary['n']} = {summary['rate'] * 100:.1f}%",
    ]
    for lv in ("L1", "L2", "L3", "L4"):
        b = summary["by_level"][lv]
        lines.append(f"- {lv}: {b['ok']}/{b['n']} = {b['rate'] * 100:.1f}%")
    lines += [
        "",
        f"- Volume error mean: {summary['vol_mean']:.4f}%",
        f"- Surface error mean: {summary['surf_mean']:.4f}%",
        f"- Key dimension error mean: {summary['key_mean']:.4f}%",
        f"- STEP roundtrip pass: {summary['step_pass']}/{summary['ok']}",
        f"- Slot Hausdorff mean: {stats['slot_haus_mean_mm']:.4f} mm (n={stats['slot_n']})",
        f"- Slot Hausdorff max: {stats['slot_haus_max_mm']:.4f} mm",
        f"- Disc contour Hausdorff mean: {stats['disc_haus_mean_mm']:.4f} mm",
        "",
        "## Per-task",
        "| Task | Level | OK | Vol% | Surf% | Key% | SlotHaus(mm) |",
    ]
    for r in sorted(rows, key=lambda x: x["task"]):
        lines.append(
            f"| {r['task']} | {r['level']} | {r['ok']} | {r['vol'] or 0:.6f} "
            f"| {r['surf'] or 0:.6f} | {r['key'] or 0:.6f} "
            f"| {r['slot_haus_mm'] if r['slot_haus_mm'] is not None else ''} |"
        )
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
