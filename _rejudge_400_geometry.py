"""Re-judge the 400 initial runs with an explicit geometry error gate.

Success requires: MCP gate passed AND volume_relative_error <= threshold
AND surface_relative_error <= threshold. Records failing only this geometry
gate are marked as failures (error_stage = geometry_gate) but their raw
records remain untouched.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(r"E:\text_to_cad_improve\auto_detection_process")
OUT = ROOT / "_main_experiment" / "output"
SRC = OUT / "combined_400_initial" / "summary.json"
DEST = OUT / "combined_400_geometry_gate"
VOL_TH = 1.0   # percent
SURF_TH = 1.0  # percent


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    rows = data["records"]
    rejudged = []
    for r in rows:
        r = dict(r)
        if r["ok"]:
            vol = r.get("vol")
            surf = r.get("surf")
            if vol is not None and (vol > VOL_TH or (surf is not None and surf > SURF_TH)):
                r["ok"] = False
                r["error_stage"] = "geometry_gate"
                r["geometry_gate"] = {
                    "vol_pct": vol, "surf_pct": surf,
                    "rule": f"vol>{VOL_TH}% or surf>{SURF_TH}%",
                }
        rejudged.append(r)

    ok_rows = [r for r in rejudged if r["ok"]]
    fail_rows = [r for r in rejudged if not r["ok"]]
    geo_fails = [r for r in fail_rows if r.get("error_stage") == "geometry_gate"]
    mcp_fails = [r for r in fail_rows if r.get("error_stage") != "geometry_gate"]

    by_level = {}
    for lv in ("L1", "L2", "L3", "L4"):
        sub = [r for r in rejudged if r.get("level") == lv]
        by_level[lv] = {
            "n": len(sub),
            "ok": sum(1 for r in sub if r["ok"]),
            "fail": sum(1 for r in sub if not r["ok"]),
            "rate": sum(1 for r in sub if r["ok"]) / len(sub) if sub else None,
        }

    slot_rows = [r for r in ok_rows if r.get("slot_haus_mm") is not None]
    summary = {
        "threshold_pct": {"vol": VOL_TH, "surf": SURF_TH},
        "n": len(rejudged),
        "ok": len(ok_rows),
        "fail": len(fail_rows),
        "rate": len(ok_rows) / len(rejudged) if rejudged else None,
        "mcp_only_fail": len(mcp_fails),
        "geometry_gate_fail": len(geo_fails),
        "by_level": by_level,
        "vol_mean_pct": statistics.fmean([r["vol"] for r in ok_rows if r.get("vol") is not None]) if ok_rows else None,
        "surf_mean_pct": statistics.fmean([r["surf"] for r in ok_rows if r.get("surf") is not None]) if ok_rows else None,
        "key_mean_pct": statistics.fmean([r["key"] for r in ok_rows if r.get("key") is not None]) if ok_rows else None,
        "step_pass": sum(1 for r in ok_rows if r.get("step") is True),
        "slot_haus_mean_mm": statistics.fmean([r["slot_haus_mm"] for r in slot_rows]) if slot_rows else None,
        "geometry_gate_failures": [
            {"task": r["task"], "seed": r["seed"], "level": r.get("level"),
             "vol": r.get("vol"), "surf": r.get("surf"),
             "slot_haus_mm": r.get("slot_haus_mm"), "disc_haus_mm": r.get("disc_haus_mm")}
            for r in sorted(geo_fails, key=lambda x: x["task"])
        ],
        "mcp_failures": [f"{r['task']}:{r['seed']}" for r in mcp_fails],
        "records": rejudged,
    }
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 400 Initial Runs Re-judged with Geometry Gate",
        "",
        f"- Rule: success = MCP gate passed AND vol<=1% AND surf<=1%",
        f"- Total: {len(rejudged)}",
        f"- Success: {len(ok_rows)} = {summary['rate'] * 100:.1f}%",
        f"- Failed: {len(fail_rows)} (MCP {len(mcp_fails)}, geometry gate {len(geo_fails)})",
        "",
        "## By level",
        "| Level | n | ok | fail | rate |",
    ]
    for lv in ("L1", "L2", "L3", "L4"):
        b = by_level[lv]
        rate = f"{b['rate'] * 100:.1f}%" if b["rate"] is not None else "N/A"
        lines.append(f"| {lv} | {b['n']} | {b['ok']} | {b['fail']} | {rate} |")
    lines += ["", "## Geometry gate failures"]
    for x in summary["geometry_gate_failures"]:
        lines.append(
            f"- {x['task']}:{x['seed']} vol={x['vol']} surf={x['surf']} "
            f"slot_haus={x['slot_haus_mm']} disc_haus={x['disc_haus_mm']}"
        )
    lines += ["", "## MCP failures"]
    lines += [f"- {x}" for x in summary["mcp_failures"]]
    (DEST / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("records", "geometry_gate_failures", "mcp_failures")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
