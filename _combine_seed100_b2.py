"""Combine the second 100 other-seed runs with corrected reruns."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"
BASE = OUT / "other_seeds_100_b2"
FIX = OUT / "other_seeds_b2_fix"

REPLACE = {("T11", 5), ("T13", 0), ("T14", 0), ("T14", 3), ("T18", 1), ("T20", 4)}


def main() -> None:
    base = json.loads((BASE / "summary.json").read_text(encoding="utf-8"))
    fix = json.loads((FIX / "summary.json").read_text(encoding="utf-8"))
    by_key = {(r["task"], r["seed"]): r for r in fix["records"]}

    rows = []
    replaced = []
    for r in base["records"]:
        key = (r["task"], r["seed"])
        if key in REPLACE:
            rows.append(by_key[key])
            replaced.append(key)
        else:
            rows.append(r)
    rows.sort(key=lambda r: (r["task"], r["seed"]))

    ok = sum(1 for r in rows if r["ok"])
    ok_rows = [r for r in rows if r["ok"]]
    by_level = {}
    for lv in ("L1", "L2", "L3", "L4"):
        sub = [r for r in rows if r.get("level") == lv]
        by_level[lv] = {
            "n": len(sub),
            "ok": sum(1 for r in sub if r["ok"]),
            "rate": sum(1 for r in sub if r["ok"]) / len(sub) if sub else None,
        }
    slot_rows = [r for r in ok_rows if r.get("slot_haus_mm") is not None]
    final = {
        "n": len(rows),
        "ok": ok,
        "rate": ok / len(rows) if rows else None,
        "by_level": by_level,
        "vol_mean_pct": statistics.fmean([r["vol"] for r in ok_rows if r["vol"] is not None]) if ok_rows else None,
        "surf_mean_pct": statistics.fmean([r["surf"] for r in ok_rows if r["surf"] is not None]) if ok_rows else None,
        "key_mean_pct": statistics.fmean([r["key"] for r in ok_rows if r["key"] is not None]) if ok_rows else None,
        "step_pass": sum(1 for r in ok_rows if r["step"] is True),
        "slot_haus_mean_mm": statistics.fmean([r["slot_haus_mm"] for r in slot_rows]) if slot_rows else None,
        "replaced": [f"{t}:{s}" for t, s in sorted(replaced)],
        "records": rows,
    }
    (BASE / "final_summary.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Other-Seed 100 Runs B2 (T11-T20, seeds 0-7/9/10) - Final",
        "",
        f"- Success: {ok}/{len(rows)} = {final['rate'] * 100:.1f}%",
    ]
    for lv in ("L1", "L2", "L3", "L4"):
        b = by_level[lv]
        rate = f"{b['rate'] * 100:.1f}%" if b["rate"] is not None else "N/A"
        lines.append(f"- {lv}: {b['ok']}/{b['n']} = {rate}")
    lines += [
        "",
        f"- Volume error mean: {final['vol_mean_pct']:.4f}%",
        f"- Surface error mean: {final['surf_mean_pct']:.4f}%",
        f"- Key dimension error mean: {final['key_mean_pct']:.4f}%",
        f"- STEP roundtrip pass: {final['step_pass']}/{ok}",
        f"- Slot Hausdorff mean: {final['slot_haus_mean_mm']:.4f} mm",
        "",
        "## Corrected reruns",
    ]
    lines += [f"- {x}" for x in final["replaced"]]
    (BASE / "final_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: v for k, v in final.items() if k != "records"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
