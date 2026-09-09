"""Combine the four new-code batches (seed 0-9) into one 400-run summary."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"

SOURCES = [
    OUT / "rerun_120_t1t40_3seeds" / "summary.json",
    OUT / "rerun_120_t1t40_3seeds_b2" / "summary.json",
    OUT / "rerun_120_t1t40_3seeds_b3" / "summary.json",
    OUT / "rerun_40_t1t40_seed9" / "summary.json",
]
DEST = OUT / "main_400_seed0to9"


def main() -> None:
    rows = []
    for path in SOURCES:
        rows.extend(json.loads(path.read_text(encoding="utf-8")).get("records", []))
    rows = sorted(rows, key=lambda r: (r.get("task"), r.get("seed")))

    ok_rows = [r for r in rows if r["ok"]]
    geo_rows = [
        r for r in ok_rows
        if r.get("vol") is not None and r.get("vol") <= 1.0
        and r.get("surf") is not None and r.get("surf") <= 1.0
    ]

    def levels(sub):
        out = {}
        for lv in ("L1", "L2", "L3", "L4"):
            s = [r for r in sub if r.get("level") == lv]
            out[lv] = {"n": len(s), "ok": len(s)}
        return out

    vol = [r["vol"] for r in geo_rows if r.get("vol") is not None]
    surf = [r["surf"] for r in geo_rows if r.get("surf") is not None]
    summary = {
        "n": len(rows),
        "mcp_ok": len(ok_rows),
        "mcp_rate": len(ok_rows) / len(rows),
        "geometry_ok_1pct": len(geo_rows),
        "geometry_rate_1pct": len(geo_rows) / len(rows),
        "mcp_ok_by_level": levels(ok_rows),
        "geometry_ok_by_level": levels(geo_rows),
        "mcp_failures": [f"{r['task']}:{r['seed']}" for r in rows if not r["ok"]],
        "geometry_failures": [
            {"task": r["task"], "seed": r["seed"], "level": r.get("level"),
             "vol": r.get("vol"), "surf": r.get("surf"),
             "disc_haus_mm": r.get("disc_haus_mm")}
            for r in ok_rows if r not in geo_rows
        ],
        "vol_mean_pct": statistics.fmean(vol) if vol else None,
        "surf_mean_pct": statistics.fmean(surf) if surf else None,
        "records": rows,
    }
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("records", "mcp_failures", "geometry_failures")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
