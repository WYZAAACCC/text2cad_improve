"""Replay the revise agent on stored findings and a revision workspace.

The source revision supplies `params.json` and `document.json`. A fresh
workspace is created beside the requested output, so the historical revision
is never modified. The result records the patch and the agent summary.

    python replay_revise_agent.py <source-revision-dir> <findings.json> <output.json> \
        [--knowledge knowledge.json] [--max-calls 16]
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

from seekflow_structural.agents import revise  # noqa: E402
from seekflow_structural.case.store import CaseStore  # noqa: E402
from seekflow_structural.pipeline.orchestrator import Budget, RunContext  # noqa: E402
from seekflow_structural.runtime.caller import DEFAULT_MODEL  # noqa: E402
from seekflow_structural.runtime.store import JobStore  # noqa: E402
from seekflow_structural.tools import knowledge, workspace  # noqa: E402

DEFAULT_MASTER = REPO / "_param_experiment" / "turbine_disc_dataset_D01-D32" / "scripts"


def load_findings(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return list(payload.get("findings") or [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_revision", type=Path)
    parser.add_argument("findings", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--master-dir", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--knowledge", type=Path)
    parser.add_argument(
        "--api-key-file", type=Path,
        default=REPO / "_archive" / "apikey.txt",
    )
    parser.add_argument("--max-calls", type=int, default=16)
    args = parser.parse_args()

    source = args.source_revision.resolve()
    params = json.loads((source / "params.json").read_text(encoding="utf-8"))
    document = json.loads((source / "document.json").read_text(encoding="utf-8"))
    findings = load_findings(args.findings)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    root = output.parent / f"{output.stem}_workspace"
    if root.exists():
        raise SystemExit(f"refusing to overwrite existing workspace: {root}")
    space = workspace.Workspace.create(
        master_dir=args.master_dir.resolve(),
        root=root,
        lineage="replay",
        revision="rev-000001",
        params=params,
        document=document,
    )
    job = JobStore(root, "revision")
    ctx = RunContext(
        job=job,
        case_store=CaseStore(job),
        budget=Budget(),
        allow_unconfirmed=True,
    )
    base = (knowledge.KnowledgeBase.load(args.knowledge)
            if args.knowledge else knowledge.KnowledgeBase())
    started = time.monotonic()
    error = ""
    error_code = ""
    try:
        result = revise.revise(
            ctx,
            findings=findings,
            space=space,
            base=base,
            api_key_file=args.api_key_file,
            max_calls=args.max_calls,
        )
    except Exception as exc:  # noqa: BLE001
        # A refusal is an experiment result, not a transport failure. Keep the
        # artifact so the paper metrics can distinguish "agent refused an
        # inconsistent finding" from "the replay never ran".
        result = {}
        error = f"{type(exc).__name__}: {exc}"
        diagnostic = getattr(exc, "diagnostic", None)
        error_code = str(getattr(diagnostic, "code", "") or "")
    payload = {
        "schema_version": "revise_agent_replay_v1",
        "source_revision": str(source),
        "model": DEFAULT_MODEL,
        "wall_s": round(time.monotonic() - started, 3),
        "workspace": str(root),
        "accepted": bool(result) and not error,
        "error": error,
        "error_code": error_code,
        "applied": result.get("applied") or [],
        "skipped": result.get("skipped") or [],
        "document_edits": result.get("document_edits") or [],
        "changed_from_master": result.get("changed_from_master") or [],
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())