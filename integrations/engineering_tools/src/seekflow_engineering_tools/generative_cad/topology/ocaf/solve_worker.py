"""Subprocess Selection Solve — v5.0 §9.6.

Runs TNaming_Selector.Solve() in an isolated subprocess so that OCP native
crashes (ACCESS VIOLATION on deleted-face Solve) do not bring down the
main pipeline process.

Pattern: same as verify_worker.py — template script → subprocess.run → JSON parse.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[5])

_WORKER_SCRIPT = r'''
import json, sys
sys.path.insert(0, r"{src}")
from pathlib import Path

xbf_path = Path(r"{xbf_path}")
selection_id = "{selection_id}"

result = {{
    "ok": False,
    "selection_id": selection_id,
    "status": "unresolved",
    "resolved_count": 0,
    "native_crash": False,
    "errors": [],
}}

try:
    from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
        OcafDocumentSession,
    )
    from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
        PersistentSelectionService,
    )
    from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
        collect_tnaming_labels,
    )

    session = OcafDocumentSession.open(xbf_path)
    label_map = collect_tnaming_labels(session.design_root_label)
    service = PersistentSelectionService(session)
    resolution = service.solve(selection_id, label_map)

    result["status"] = resolution.status.value
    result["resolved_count"] = len(resolution.resolved_shapes)
    result["ok"] = True
    session.close()

except Exception as e:
    result["errors"].append(str(e)[:500])
    result["ok"] = False

print(json.dumps(result), flush=True)
'''


@dataclass(frozen=True)
class SolveWorkerResult:
    """Structured result of subprocess Selection Solve."""
    ok: bool
    selection_id: str
    status: str = "unresolved"
    resolved_count: int = 0
    native_crash: bool = False
    errors: list[str] = field(default_factory=list)
    raw_stdout: str = ""
    raw_stderr: str = ""


def solve_in_subprocess(
    xbf_path: Path, selection_id: str, *, timeout: int = 30,
) -> SolveWorkerResult:
    """Execute TNaming_Selector.Solve() in an isolated subprocess.

    Args:
        xbf_path: Path to the XBF file.
        selection_id: Stable selection identifier to solve.
        timeout: Subprocess timeout in seconds.

    Returns:
        SolveWorkerResult — native_crash=True if ACCESS VIOLATION.
    """
    p = Path(xbf_path).resolve()
    if not p.exists():
        return SolveWorkerResult(
            ok=False, selection_id=selection_id,
            errors=[f"XBF not found: {p}"],
        )

    code = _WORKER_SCRIPT.format(src=SRC, xbf_path=str(p), selection_id=selection_id)

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return SolveWorkerResult(
            ok=False, selection_id=selection_id,
            errors=["Subprocess timed out"],
        )

    raw_stdout = proc.stdout.strip()
    raw_stderr = proc.stderr.strip()

    try:
        data = json.loads(raw_stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return SolveWorkerResult(
            ok=False, selection_id=selection_id,
            errors=[f"No valid JSON (returncode={proc.returncode})"],
            native_crash=proc.returncode != 0,
            raw_stdout=raw_stdout[:500],
            raw_stderr=raw_stderr[:500],
        )

    return SolveWorkerResult(
        ok=data.get("ok", False),
        selection_id=data.get("selection_id", selection_id),
        status=data.get("status", "unresolved"),
        resolved_count=data.get("resolved_count", 0),
        native_crash=data.get("native_crash", False),
        errors=data.get("errors", []),
        raw_stdout=raw_stdout,
        raw_stderr=raw_stderr,
    )
