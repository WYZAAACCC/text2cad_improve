"""Run the face-finding agent with the origin tools, against the real part.

The question this answers is whether the provenance dimension is enough on its
own. The reference selection is six faces at r 211.3-213.8 - one slot's
bearing flanks - and the geometric tools cannot separate them from the other
472 faces at r 280-300 that every measurement says are the same kind of thing.

Prints each turn so the trace can be read as it happens, then compares the
submission against the reference.
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

from seekflow_structural.agents import facefind          # noqa: E402
from seekflow_structural.runtime import loop as loop_mod  # noqa: E402
from seekflow_structural.runtime.caller import build_caller  # noqa: E402
from seekflow_structural.tools import geometry            # noqa: E402

REFERENCE = [9, 10, 11, 12, 13, 15]
BUNDLE = REPO / "_cfd_experiment" / "input" / "lineage" / "D27"
INDEX = REPO / "_structural_experiment" / "work" / "D27_fast.sqlite"
KEY = REPO / "_structural_experiment" / "input" / ".deepseek_key"

REQUIREMENT = (
    "the faces that carry the blade load into the body. The load acts normal "
    "to the bearing surface, pressing into the material, so the outward "
    "normal of each of these faces points into the space the blade root "
    "occupies."
)


class Spy:
    """Show every raw turn, then delegate to the real loop."""

    def __init__(self, inner):
        self.inner = inner
        self.n = 0

    def call_strict_tool(self, **kwargs):
        result = self.inner.call_strict_tool(**kwargs)
        self.n += 1
        args = result.arguments
        interesting = {
            key: value for key, value in args.items()
            if key in ("origin_relation", "origin_operand", "surface_type")
            and value
        }
        numeric = {
            key: round(value, 3) for key, value in args.items()
            if isinstance(value, (int, float))
            and key not in ("limit", "offset", "solid_index")
            and value not in (-1e30, 1e30, 0, 60)
        }
        print(f"[{self.n:2d}] {args.get('action')}"
              f"{' ' + str(args.get('feature')) if args.get('feature') else ''}"
              f"{' ' + json.dumps(interesting) if interesting else ''}"
              f"{' ' + json.dumps(numeric) if numeric else ''}")
        if args.get("rationale"):
            print(f"      why: {str(args['rationale'])[:230]}")
        if args.get("code"):
            print(f"      code: {str(args['code'])[:200]}...")
        return result


def main() -> int:
    max_calls = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    session = geometry.open_bundle(BUNDLE)
    state = facefind.FaceFinderState(
        session=session,
        bundle=BUNDLE,
        evolution_db=INDEX,
        sector={"theta_low_deg": 9.0, "theta_high_deg": 27.0},
        workdir=REPO / "_structural_experiment" / "work" / "facefind_origins",
    )
    caller, config = build_caller(KEY)
    spec = facefind.spec(
        requirement=REQUIREMENT, sector_deg=18.0, theta_low_deg=9.0,
        max_calls=max_calls,
    )
    try:
        outcome = loop_mod.run_agent(
            spec, caller=Spy(caller), model_config=config,
            dispatch=facefind.DISPATCH, context=state,
        )
    finally:
        session.close()

    print()
    print("exhausted:", outcome.exhausted, "| calls:", outcome.calls)
    final = outcome.final or {}
    selected = [int(v) for v in (final.get("selected_face_indices") or [])]
    print(f"selected: {len(selected)} faces")
    print(f"  {selected[:24]}{' ...' if len(selected) > 24 else ''}")
    print(f"reference: {REFERENCE}")
    print(f"  exact match: {sorted(selected[:len(REFERENCE)]) == REFERENCE}"
          f"   (whole set == reference: {sorted(selected) == REFERENCE})")
    print(f"  load_radius_mm: {final.get('load_radius_mm')}  "
          f"(reference 212.6664)")
    print(f"  selection_method: {final.get('selection_method')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
