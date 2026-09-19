"""Why rev-2's domain agent swept theta_low and found nothing.

rev-1's agent settled in four calls: probe_periodicity named order 20,
test_finer_periods confirmed nothing finer, and preview_domain accepted
theta_low = 9. rev-2's agent did the same four calls - and then spent its
remaining ten sweeping theta_low from 0 to 8 one degree at a time, one
preview_domain each, and ran out of budget without submitting.

preview_domain draws the sector and counts the faces on each of its two cut
planes; the agent is looking for a theta_low where the two counts are equal,
because a cyclic sector is solved by tying those two faces to each other. This
sweeps the whole period on rev-2's geometry and prints what each angle gives.

    .conda\\python.exe -u _structural_experiment/check_sector_sweep.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

# The runs were moved off the working disk; see _store.py.
from _store import loop_test  # noqa: E402

from seekflow_structural.core.domain_preview import DomainPreviewer  # noqa: E402

REV2 = (loop_test() / "run2" / "revisions" / "rev-000002" / "lineage"
        / "lineage" / "D27-rev-000002" / "revisions" / "rev-000001" / "model.step")
REV1 = (loop_test() / "run2" / "revisions" / "rev-000001" / "lineage"
        / "lineage" / "D27-rev-000001" / "revisions" / "rev-000001" / "model.step")

SECTOR = 18.0


def sweep(step: Path, angles) -> None:
    print(f"\n=== {step.parent.parent.parent.name} : {step.name} ===", flush=True)
    t = time.time()
    previewer = DomainPreviewer(step, 300.0, 38.0)
    print(f"STEP loaded in {time.time() - t:.0f}s", flush=True)
    try:
        print(f"{'theta_low':>10} {'low':>5} {'high':>5} {'sym':>5} "
              f"{'area_low':>10} {'area_high':>10} {'vol_err%':>9}  verdict",
              flush=True)
        for theta in angles:
            started = time.time()
            try:
                out = previewer.preview(SECTOR, theta, True)
            except Exception as exc:
                print(f"{theta:>10.1f}  raised {type(exc).__name__}: {exc}",
                      flush=True)
                continue
            if out.get("error"):
                print(f"{theta:>10.1f}  {out['error']}", flush=True)
                continue
            counts = out["cut_plane_faces"]
            areas = out["cut_plane_area_mm2"]
            ok = counts["low"] == counts["high"] and counts["low"] > 0
            print(f"{theta:>10.1f} {counts['low']:>5} {counts['high']:>5} "
                  f"{counts['sym']:>5} {areas['low']:>10.3f} "
                  f"{areas['high']:>10.3f} {out['volume_error_percent']:>9.3f}  "
                  f"{'ACCEPT' if ok else 'reject'}  "
                  f"({time.time() - started:.0f}s)", flush=True)
    finally:
        previewer.close()


def main() -> int:
    angles = [float(a) for a in sys.argv[1:]] or [
        0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0,
    ]
    sweep(REV2, angles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
