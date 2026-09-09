"""Combine all initial runs (340 + final 60) without corrected reruns."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"

SOURCES = [
    OUT / "full_40_rerun" / "summary.json",
    OUT / "other_seeds_100" / "summary.json",
    OUT / "other_seeds_100_b2" / "summary.json",
    OUT / "other_seeds_100_b3" / "summary.json",
    OUT / "other_seeds_60_T31_T40" / "summary.json",
]
DEST = OUT / "combined_400_initial"


def main() -> None:
    rows = []
    for path in SOURCES:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(data.get("records", []))
    seen = set()
    unique = []
    for r in rows:
        key = (r.get("task"), r.get("seed"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    rows = sorted(unique, key=lambda r: (r.get("task"), r.get("seed")))

    tasks = {t["task_id"]: t for t in
             json.loads((OUT / "tasks.json").read_text(encoding="utf-8"))}
    for r in rows:
        if not r.get("level"):
            r["level"] = (tasks.get(r.get("task")) or {}).get("level")

    ok_rows = [r for r in rows if r["ok"]]
    fail_rows = [r for r in rows if not r["ok"]]
    slot_rows = [r for r in ok_rows if r.get("slot_haus_mm") is not None]
    bad_rows = [
        r for r in ok_rows
        if (r.get("vol") is not None and r["vol"] > 1.0)
        or (r.get("surf") is not None and r["surf"] > 1.0)
        or (r.get("slot_haus_mm") is not None and r["slot_haus_mm"] > 0.05)
        or (r.get("disc_haus_mm") is not None and r["disc_haus_mm"] > 0.05)
    ]

    by_level = {}
    for lv in ("L1", "L2", "L3", "L4"):
        sub = [r for r in rows if r.get("level") == lv]
        by_level[lv] = {
            "n": len(sub),
            "ok": sum(1 for r in sub if r["ok"]),
            "fail": sum(1 for r in sub if not r["ok"]),
            "rate": sum(1 for r in sub if r["ok"]) / len(sub) if sub else None,
        }

    vol_ok = [r["vol"] for r in ok_rows if r.get("vol") is not None]
    surf_ok = [r["surf"] for r in ok_rows if r.get("surf") is not None]
    key_ok = [r["key"] for r in ok_rows if r.get("key") is not None]
    final = {
        "n": len(rows),
        "ok": len(ok_rows),
        "fail": len(fail_rows),
        "rate": len(ok_rows) / len(rows) if rows else None,
        "by_level": by_level,
        "vol_mean_pct": statistics.fmean(vol_ok) if vol_ok else None,
        "vol_max_pct": max(vol_ok) if vol_ok else None,
        "surf_mean_pct": statistics.fmean(surf_ok) if surf_ok else None,
        "surf_max_pct": max(surf_ok) if surf_ok else None,
        "key_mean_pct": statistics.fmean(key_ok) if key_ok else None,
        "step_pass": sum(1 for r in ok_rows if r.get("step") is True),
        "slot_haus_mean_mm": statistics.fmean([r["slot_haus_mm"] for r in slot_rows]) if slot_rows else None,
        "slot_haus_max_mm": max(r["slot_haus_mm"] for r in slot_rows) if slot_rows else None,
        "slot_n": len(slot_rows),
        "failures": [f"{r['task']}:{r['seed']} ({r.get('error_stage')})" for r in fail_rows],
        "high_error_success": [
            {"task": r["task"], "seed": r["seed"], "vol": r.get("vol"),
             "surf": r.get("surf"), "slot_haus_mm": r.get("slot_haus_mm"),
             "disc_haus_mm": r.get("disc_haus_mm")}
            for r in sorted(bad_rows, key=lambda x: x["task"])
        ],
        "records": rows,
    }
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "summary.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Combined 400 Initial Runs (no corrected reruns)",
        "",
        f"- Total: {len(rows)}",
        f"- Success: {len(ok_rows)} = {final['rate'] * 100:.1f}%",
        f"- Failed: {len(fail_rows)}",
        "",
        "## By level",
        "| Level | n | ok | fail | rate |",
    ]
    for lv in ("L1", "L2", "L3", "L4"):
        b = by_level[lv]
        rate = f"{b['rate'] * 100:.1f}%" if b["rate"] is not None else "N/A"
        lines.append(f"| {lv} | {b['n']} | {b['ok']} | {b['fail']} | {rate} |")
    lines += [
        "",
        f"- Volume error mean: {final['vol_mean_pct']:.4f}% (max {final['vol_max_pct']:.4f}%)",
        f"- Surface error mean: {final['surf_mean_pct']:.4f}% (max {final['surf_max_pct']:.4f}%)",
        f"- Key dimension error mean: {final['key_mean_pct']:.4f}%",
        f"- STEP roundtrip pass: {final['step_pass']}/{len(ok_rows)}",
        f"- Slot Hausdorff mean: {final['slot_haus_mean_mm']:.4f} mm (max {final['slot_haus_max_mm']:.4f} mm, n={final['slot_n']})",
        "",
        "## Failures",
    ]
    lines += [f"- {x}" for x in final["failures"]]
    lines += ["", "## High-error successes (vol>1% or surf>1% or slot_haus>0.05 or disc_haus>0.05)"]
    for x in final["high_error_success"]:
        lines.append(
            f"- {x['task']}:{x['seed']} vol={x['vol']} surf={x['surf']} "
            f"slot_haus={x['slot_haus_mm']} disc_haus={x['disc_haus_mm']}"
        )
    (DEST / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: v for k, v in final.items() if k not in ("records", "failures", "high_error_success")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
