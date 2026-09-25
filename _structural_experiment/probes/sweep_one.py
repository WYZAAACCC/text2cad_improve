"""Run the face-finding agent once, recording everything it saw and did.

The point of running it many times is that one trace cannot say whether a
failure is typical or a fluke, and the earlier attempts to explain it kept
being guesses. So this captures the whole exchange rather than a summary of
it: every request the model was given, every reply it got back, what it asked
for and how long each turn took.

    python sweep_one.py <tag> <outdir>

Writes <outdir>/run_<tag>.json. Nothing is interpreted here - the analysis is
a separate pass over these files, so a new question about the runs does not
mean running them again.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import traceback

from seekflow_engineering_tools.generative_cad.llm.errors import (
    LlmToolCallError,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))
sys.path.insert(0, str(REPO / "integrations" / "engineering_tools" / "src"))

from seekflow_structural.agents import facefind                    # noqa: E402
from seekflow_structural.agents.assembly import REQUIREMENTS       # noqa: E402
from seekflow_structural.runtime import loop as loop_mod           # noqa: E402
from seekflow_structural.runtime.caller import build_caller        # noqa: E402
from seekflow_structural.tools import geometry                     # noqa: E402

BUNDLE = REPO / "_cfd_experiment" / "input" / "lineage" / "D27"
INDEX = REPO / "_structural_experiment" / "work" / "D27_fast.sqlite"
KEY = REPO / "_structural_experiment" / "input" / ".deepseek_key"

MAX_CALLS = 30
SECTOR = {"theta_low_deg": 9.0, "theta_high_deg": 27.0}


def truncated(text, limit=4000):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"...[{len(text)} chars]"


class Recorder:
    """Pass through to the real caller, keeping every turn.

    The conversation is not recorded per turn - it grows, so the last call's
    message list already contains all of it - but the arguments and the
    latency of each turn are, because those are what a failure is read from.
    """

    def __init__(self, inner):
        self.inner = inner
        self.turns = []
        self.last_messages = []

    def call_strict_tool(self, **kwargs):
        messages = kwargs.get("messages") or []
        started = time.monotonic()
        result = self.inner.call_strict_tool(**kwargs)
        elapsed = time.monotonic() - started
        self.last_messages = [dict(m) for m in messages]
        self.turns.append({
            "turn": len(self.turns) + 1,
            "latency_s": round(elapsed, 2),
            "arguments": result.arguments,
            "assistant_content": result.assistant_content,
        })
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("outdir", nargs="?", type=pathlib.Path,
                        default=REPO / "_structural_experiment" / "output" / "sweep")
    parser.add_argument("--bundle", type=pathlib.Path, default=BUNDLE)
    parser.add_argument("--index", type=pathlib.Path, default=INDEX)
    parser.add_argument("--sector-deg", type=float, default=18.0)
    parser.add_argument("--theta-low-deg", type=float, default=9.0)
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS)
    args = parser.parse_args()
    tag = args.tag
    out_dir = args.outdir
    bundle = args.bundle.resolve()
    sector = {
        "theta_low_deg": args.theta_low_deg,
        "theta_high_deg": (args.theta_low_deg + args.sector_deg) % 360.0,
    }
    evolution_db = args.index.resolve() if args.index.exists() else None
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"run_{tag}.json"

    record: dict = {
        "tag": tag,
        "max_calls": args.max_calls,
        "bundle": str(bundle),
        "sector": sector,
    }
    started = time.monotonic()
    attempts = 0

    # A provider failure is not the thing being measured. The account returns
    # 402 Insufficient Balance intermittently and a truncated tool call comes
    # back as invalid JSON; both killed runs in the first sweep and both are
    # transient. Retried here so a batch measures the agent rather than the
    # weather, and counted so the weather is still reported.
    while attempts < 4:
        attempts += 1
        session = None
        try:
            session = geometry.open_bundle(bundle)
            state = facefind.FaceFinderState(
                session=session, bundle=bundle, evolution_db=evolution_db,
                sector=dict(sector),
                require_planar=True,
                load_direction_rule="flank_surface_normal",
                workdir=(REPO / "_structural_experiment" / "work"
                         / "sweep_analyses" / tag / str(attempts)),
            )
            caller, config = build_caller(KEY)
            recorder = Recorder(caller)
            spec = facefind.spec(
                requirement=REQUIREMENTS["flank_surface_normal"],
                sector_deg=args.sector_deg,
                theta_low_deg=args.theta_low_deg,
                max_calls=args.max_calls,
            )
            outcome = loop_mod.run_agent(
                spec, caller=recorder, model_config=config,
                dispatch=facefind.DISPATCH, context=state,
            )

            final = outcome.final or {}
            record.update({
                "ok": True,
                "attempts": attempts,
                "model": config.model,
                "calls": outcome.calls,
                "exhausted": outcome.exhausted,
                "submitted": bool(final.get("accepted")),
                "final": final,
                "selected": [
                    int(v) for v in (final.get("selected_face_indices") or [])
                ],
                "load_radius_mm": final.get("load_radius_mm"),
                "criterion_satisfied": (
                    (final.get("criterion_residuals") or {}).get("satisfied")
                ),
                "load_normal_alignment": (
                    final.get("submission_readiness") or {}
                ).get("load_normal_alignment"),
                "turns": recorder.turns,
                "trace": outcome.trace,
                "rejected": outcome.rejected,
                "conversation": recorder.last_messages,
                "analyses": state.analyses,
            })
            break
        except LlmToolCallError as exc:
            record.setdefault("transport_errors", []).append(str(exc)[:120])
            time.sleep(3 * attempts)
        except Exception as exc:  # noqa: BLE001
            record.update({
                "ok": False,
                "attempts": attempts,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-2000:],
            })
            break
        finally:
            if session is not None:
                close = getattr(session, "close", None)
                if close is not None:
                    close()

    if "ok" not in record:
        record.update({
            "ok": False,
            "attempts": attempts,
            "error": "all attempts failed at the provider",
        })

    record["wall_s"] = round(time.monotonic() - started, 1)
    out_path.write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )
    print(f"{tag}: attempts={attempts} calls={record.get('calls')} "
          f"submitted={record.get('submitted')} "
          f"wall={record['wall_s']}s -> {out_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
