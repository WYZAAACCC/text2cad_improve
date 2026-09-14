"""Read the sweep's records and say where the failures actually happen.

One trace tells you what happened once. A sweep says which of it is the
behaviour and which is the draw, and the difference matters: three separate
guesses about this agent were made from single traces and all three were
wrong.

Reports the rate, the failure modes by shape, and - the part worth having -
the call at which a failing run stops making progress, together with the set
it was looking at when it did.
"""
from __future__ import annotations

import collections
import json
import pathlib

import sys

SWEEP = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else (
    pathlib.Path(__file__).resolve().parents[1] / "output" / "sweep"
)


def load_all() -> list[dict]:
    out = []
    for path in sorted(
        SWEEP.glob("run_*.json"),
        key=lambda p: int(p.stem.split("_")[1]) if p.stem.split("_")[1].isdigit() else 0,
    ):
        out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def actions(run: dict) -> list[str]:
    return [t["arguments"].get("action") for t in run.get("turns") or []]


def collapse_point(run: dict, threshold: int = 5) -> int | None:
    """The turn where a run starts repeating itself and never recovers.

    "Repeating" means the same arguments as the previous call - the agent
    asking a question it already has the answer to. The point is the first
    call of the final such run, because the interesting question is not that
    it repeated but what it was looking at when it began.
    """
    turns = run.get("turns") or []
    best = None
    index = 1
    while index < len(turns):
        if turns[index]["arguments"] == turns[index - 1]["arguments"]:
            start = index - 1
            while (index < len(turns)
                   and turns[index]["arguments"] == turns[start]["arguments"]):
                index += 1
            if index - start >= threshold:
                best = start + 1  # 1-based turn number
        else:
            index += 1
    return best


def last_query(run: dict, upto: int | None) -> dict:
    turns = (run.get("turns") or [])[:upto] if upto else (run.get("turns") or [])
    for turn in reversed(turns):
        if turn["arguments"].get("action") == "query_faces":
            return {
                k: v for k, v in turn["arguments"].items()
                if v not in ("", 0, 0.0, -1e30, 1e30, [], None, False)
            }
    return {}


def main() -> int:
    print(f"--- {SWEEP.name} ---")
    runs = load_all()
    good = [r for r in runs if r.get("ok")]
    submitted = [r for r in good if r["submitted"]]
    exhausted = [r for r in good if not r["submitted"]]
    errored = [r for r in runs if not r.get("ok")]

    print(f"runs {len(runs)}   submitted {len(submitted)}   "
          f"exhausted {len(exhausted)}   errored {len(errored)}")
    if good:
        low, high = _wilson(len(submitted), len(good))
        print(f"success rate {len(submitted)}/{len(good)} = "
              f"{100*len(submitted)/len(good):.0f}%   "
              f"(95% interval {100*low:.0f}-{100*high:.0f}%)")
    print()

    print("=== 动作构成 ===")
    for label, group in (("SUBMITTED", submitted), ("EXHAUSTED", exhausted)):
        total = collections.Counter()
        for run in group:
            total.update(actions(run))
        n = sum(total.values()) or 1
        print(f"  {label:10s} n={len(group)}  " + "  ".join(
            f"{k}={100*v//n}%" for k, v in total.most_common(5)
        ))
    print()

    print("=== 卡死点：从第几次调用开始反复问同一个问题 ===")
    for run in exhausted:
        point = collapse_point(run)
        acts = actions(run)
        tail = collections.Counter(acts[point - 1:]) if point else {}
        query = last_query(run, point)
        print(f"  run {run['tag']:>3}  calls={run['calls']:>2}  "
              f"collapse at call {point}  then {dict(tail)}")
        if query:
            print(f"           was looking at: {json.dumps(query, ensure_ascii=False)[:150]}")
    print()

    print("=== 提交的用时与轮数 ===")
    if submitted:
        print("  calls:", sorted(r["calls"] for r in submitted))
        print("  wall :", sorted(r["wall_s"] for r in submitted))
        radii = [float(r["load_radius_mm"]) for r in submitted
                 if r.get("load_radius_mm") is not None]
        if radii:
            print("  load_radius_mm:", [round(v, 2) for v in sorted(radii)])
        print("  face counts   :", sorted(len(r["selected"]) for r in submitted))
        print("  criterion_satisfied:",
              collections.Counter(r.get("criterion_satisfied") for r in submitted))
    print()

    print("=== rationale 什么时候消失 ===")
    for label, group in (("SUBMITTED", submitted), ("EXHAUSTED", exhausted)):
        gaps = []
        for run in group:
            turns = run.get("turns") or []
            first_empty = next(
                (i + 1 for i, t in enumerate(turns)
                 if not (t["arguments"].get("rationale") or "").strip()),
                None,
            )
            gaps.append(first_empty)
        print(f"  {label:10s} 首次空 rationale 的调用序号: {gaps}")
    print()

    print("=== 报错 ===")
    for run in errored:
        print(f"  run {run['tag']}: {run.get('error','')[:110]}")
    return 0


def _wilson(successes: int, total: int) -> tuple[float, float]:
    """A proportion interval that behaves at small n, which this is."""
    if total == 0:
        return 0.0, 1.0
    z = 1.96
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    spread = z * ((phat * (1 - phat) / total
                   + z * z / (4 * total * total)) ** 0.5) / denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


if __name__ == "__main__":
    raise SystemExit(main())
