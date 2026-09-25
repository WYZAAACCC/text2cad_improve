"""Replay the feedback agent against a stored structural job without solving again.

This is the feedback-side counterpart to `sweep_one.py`. It reads an existing
job, optionally overrides the bundle document with the revision workspace
document, runs the real agent, and writes the structured findings and trace
summary. It never rewrites the job.

    python replay_feedback_agent.py <job-dir> <document.json> <output.json> \
        [--knowledge knowledge.json] [--api-key-file key.txt] [--max-calls 32]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))
sys.path.insert(0, str(REPO / "integrations" / "engineering_tools" / "src"))

from seekflow_structural.agents import feedback  # noqa: E402
from seekflow_structural.runtime.caller import build_caller  # noqa: E402
from seekflow_structural.runtime.loop import run_agent  # noqa: E402
from seekflow_structural.tools import knowledge, loop_wiring  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("document", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--knowledge", type=Path)
    parser.add_argument(
        "--api-key-file", type=Path,
        default=REPO / "_archive" / "apikey.txt",
    )
    parser.add_argument("--max-calls", type=int, default=32)
    args = parser.parse_args()

    doc = json.loads(args.document.read_text(encoding="utf-8"))
    base = (
        knowledge.KnowledgeBase.load(args.knowledge)
        if args.knowledge is not None else None
    )
    state = feedback._load_state(
        loop_wiring.context_for(args.job_dir),
        base=base,
        document_override=doc,
    )
    caller, config = build_caller(args.api_key_file)
    started = time.monotonic()
    outcome = run_agent(
        feedback.spec(max_calls=args.max_calls),
        caller=caller,
        model_config=config,
        dispatch=feedback.DISPATCH,
        context=state,
    )
    report = feedback.to_case_feedback(state) if state.submitted else None
    payload = {
        "schema_version": "feedback_agent_replay_v1",
        "job_dir": str(args.job_dir.resolve()),
        "document": str(args.document.resolve()),
        "model": config.model,
        "calls": outcome.calls,
        "exhausted": outcome.exhausted,
        "final": outcome.final,
        "rejected": outcome.rejected,
        "wall_s": round(time.monotonic() - started, 3),
        "findings": (
            [
                {
                    **finding.model_dump(mode="json"),
                    "consistency": [
                        comparison.model_dump(mode="json")
                        for comparison in finding.consistency
                    ],
                }
                for finding in report.findings
            ]
            if report is not None else []
        ),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "model": payload["model"],
        "calls": payload["calls"],
        "accepted": bool(report),
        "findings": len(payload["findings"]),
        "wall_s": payload["wall_s"],
        "output": str(args.output.resolve()),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())