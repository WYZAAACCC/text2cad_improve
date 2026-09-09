"""Isolated smoke runner for the 320 semantically-equivalent instruction suite.

Run a small representative subset without touching the official
``semantics_results_agentic.jsonl``. The raw per-run artifacts still land under
``_main_experiment/output/runs/semantics_agentic_*``.
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

from _main_experiment._semantics_run import _run_one

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "_main_experiment" / "output"

SMOKE_IDS = [
    "T01_baseline",
    "T06_order_change",
    "T10_term_swap",
    "T15_unit_mix",
    "T25_ratio_abs",
    "T31_fuzzy",
    "T36_split_sentence",
    "T40_table_conflict",
]


def main() -> int:
    items = json.loads(
        (OUT / "suites" / "semantics" / "tasks.json").read_text(encoding="utf-8")
    )
    pending = [i for i in items if i["semantic_id"] in SMOKE_IDS]
    if len(pending) != len(SMOKE_IDS):
        missing = [x for x in SMOKE_IDS if x not in {i["semantic_id"] for i in pending}]
        raise SystemExit(f"missing smoke ids: {missing}")

    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=4, maxtasksperchild=2) as pool:
        results = list(pool.imap_unordered(_run_one, pending))

    results.sort(key=lambda r: r["semantic_id"])
    summary = {
        "smoke_size": len(results),
        "engineering_ok": sum(1 for r in results if r["engineering_ok"]),
        "param_consistent": sum(1 for r in results if r["param_consistent"]),
        "param_consistent_clean": sum(1 for r in results if r["param_consistent_clean"]),
        "fdg_isomorphic": sum(1 for r in results if r["fdg_isomorphic"]),
        "status_failed": [r["semantic_id"] for r in results if r["status"] != "completed"],
    }
    dest = OUT / "suites" / "semantics" / "semantics_smoke_latest.json"
    dest.write_text(
        json.dumps({"summary": summary, "records": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    for r in results:
        print(
            r["semantic_id"],
            "status=", r["status"],
            "eng=", r["engineering_ok"],
            "param=", r["param_consistent"],
            "param_clean=", r["param_consistent_clean"],
            "fdg=", r["fdg_isomorphic"],
            "err=", (r.get("error_message") or "")[:120],
            flush=True,
        )
    return 0 if not summary["status_failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
