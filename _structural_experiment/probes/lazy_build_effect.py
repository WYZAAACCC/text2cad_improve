"""Does building the index inside the agent's turn change what the agent sees?

The standalone probe pre-builds the index and succeeds; the chain builds it
lazily inside the agent's second tool call and fails, twice, identically. The
one thing that differs is when the second OCAF session is opened, so this
measures whether that changes any reply the agent reads.

The first version of this test was wrong: it pointed at a path that already
held an index, so nothing was built and the comparison proved nothing. This
one deletes the file first and asserts that a build actually happened.
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

from seekflow_structural.agents import facefind          # noqa: E402
from seekflow_structural.tools import geometry           # noqa: E402

BUNDLE = REPO / "_cfd_experiment" / "input" / "lineage" / "D27"
FRESH = REPO / "_structural_experiment" / "work" / "lazy_probe.sqlite"

QUERIES = [
    dict(action="query_faces", feature="n_final_cut"),
    dict(action="query_faces", feature="n_final_cut", surface_type="plane",
         normal_radial_max=-0.5),
    dict(action="query_faces", feature="n_final_cut", origin_relation="carry",
         origin_operand="target"),
]


def replies(state):
    """Every reply the agent would read, as the agent would read it."""
    out = []
    for spec in QUERIES:
        result = facefind._query_faces(facefind.Action(**spec), state)["result"]
        out.append((spec, result.get("matched"), result.get("summary")))
    result = facefind._list_origins(
        facefind.Action(action="list_origins", feature="n_final_cut"), state
    )["result"]
    out.append(("list_origins", result.get("face_count"),
                [(c["origin_relation"], c["origin_operand"], c["faces"])
                 for c in result.get("classes", [])]))
    return out


def main() -> int:
    for leftover in FRESH.parent.glob("lazy_probe.sqlite*"):
        leftover.unlink()
    assert not FRESH.exists()

    session = geometry.open_bundle(BUNDLE)
    state = facefind.FaceFinderState(
        session=session, bundle=BUNDLE, evolution_db=FRESH,
        sector={"theta_low_deg": 9.0, "theta_high_deg": 27.0},
    )
    try:
        before = replies(state)
        built = FRESH.exists()
        print("index built during those calls:", built)
        if not built:
            print("NOTHING WAS BUILT - this test proves nothing")
            return 2
        after = replies(state)
    finally:
        session.close()

    print()
    same = True
    for (spec, m0, s0), (_, m1, s1) in zip(before, after):
        label = spec if isinstance(spec, str) else spec["action"]
        if (m0, s0) != (m1, s1):
            same = False
            print(f"CHANGED  {label}")
            print(f"   before: matched={m0} summary={str(s0)[:120]}")
            print(f"   after : matched={m1} summary={str(s1)[:120]}")
        else:
            print(f"same     {label}: matched={m0}")
    print()
    print("every reply identical before and after the build:", same)
    shutil.rmtree(FRESH.parent / "unused", ignore_errors=True)
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
