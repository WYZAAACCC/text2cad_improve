"""Subprocess XBF verification — v5.0 §6.6.

Runs XBF validation in an isolated subprocess so that OCP native crashes
(ACCESS VIOLATION, TNaming destructor crash) do not bring down the main
pipeline process.

The worker is designed to be called BOTH:
  1. As a Python module via `verify_xbf(path)` — returns VerifyResult
  2. As a standalone script via `subprocess.run([python, "-c", code])`
     for true crash isolation

Output format (JSON on stdout):
  {"ok": true/false, "errors": [...], "native_crash": false, ...}
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[5])  # seekflow_engineering_tools src dir

# ---------------------------------------------------------------------------
# Worker script template — runs in a subprocess for crash isolation
# ---------------------------------------------------------------------------

_WORKER_SCRIPT = r'''
import json, sys, os
sys.path.insert(0, r"{src}")
from pathlib import Path

xbf_path = Path(r"{xbf_path}")

result = {{
    "ok": False,
    "xbf_path": str(xbf_path),
    "errors": [],
    "warnings": [],
    "native_crash": False,
    "design_root_present": False,
    "schema_version": None,
    "index_entry_count": 0,
    "manifest_sha256": None,
}}

try:
    from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
        OcafDocumentSession,
    )
    session = OcafDocumentSession.open(xbf_path)

    # DesignRoot check
    root = session.design_root_label
    result["design_root_present"] = not root.IsNull()

    # Schema version
    from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
        read_ascii_string,
    )
    from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
        TAGPATH_STABLE_ID_INDEX, INDEX_TAG_METADATA, INDEX_META_SCHEMA_VERSION,
    )
    idx_root = TAGPATH_STABLE_ID_INDEX.resolve(session.main_label)
    if not idx_root.IsNull():
        meta = idx_root.FindChild(INDEX_TAG_METADATA, False)
        if not meta.IsNull():
            sv = read_ascii_string(meta.FindChild(INDEX_META_SCHEMA_VERSION, False))
            result["schema_version"] = sv

    # Index entries
    result["index_entry_count"] = session.label_index.entry_count

    # TNaming attribute presence
    from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
        collect_tnaming_labels,
    )
    label_map = collect_tnaming_labels(session.design_root_label)
    result["tnaming_label_count"] = label_map.Extent()

    session.close()
    result["ok"] = True

except Exception as e:
    result["errors"].append(str(e)[:500])
    result["ok"] = False

print(json.dumps(result), flush=True)
'''


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifyResult:
    """Structured result of XBF subprocess verification."""
    ok: bool
    xbf_path: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    native_crash: bool = False
    design_root_present: bool = False
    schema_version: str | None = None
    index_entry_count: int = 0
    tnaming_label_count: int = 0
    manifest_sha256: str | None = None
    raw_stdout: str = ""
    raw_stderr: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_xbf(xbf_path: Path, timeout: int = 30) -> VerifyResult:
    """Verify an XBF file in an isolated subprocess.

    Native crashes (ACCESS VIOLATION) are caught and reported as
    ``native_crash=True`` — they never propagate to the caller.

    Args:
        xbf_path: Path to the XBF file to verify.
        timeout: Subprocess timeout in seconds.

    Returns:
        VerifyResult with structured verification outcome.
    """
    p = Path(xbf_path).resolve()

    if not p.exists():
        return VerifyResult(
            ok=False,
            xbf_path=str(p),
            errors=[f"File does not exist: {p}"],
        )

    # Safety check: reject empty/corrupted files
    try:
        if p.stat().st_size < 8:
            return VerifyResult(
                ok=False,
                xbf_path=str(p),
                errors=[f"File too small ({p.stat().st_size} bytes)"],
            )
    except OSError as exc:
        return VerifyResult(
            ok=False,
            xbf_path=str(p),
            errors=[f"Cannot stat file: {exc}"],
        )

    code = _WORKER_SCRIPT.format(src=SRC, xbf_path=str(p))

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return VerifyResult(
            ok=False,
            xbf_path=str(p),
            errors=["Subprocess timed out"],
        )

    raw_stdout = proc.stdout.strip()
    raw_stderr = proc.stderr.strip()

    # Parse JSON result from worker
    try:
        data = json.loads(raw_stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        # Native crash likely — no valid JSON output
        return VerifyResult(
            ok=False,
            xbf_path=str(p),
            errors=[f"No valid JSON from worker (returncode={proc.returncode})"],
            warnings=[raw_stderr[:500]] if raw_stderr else [],
            native_crash=proc.returncode != 0,
            raw_stdout=raw_stdout[:500],
            raw_stderr=raw_stderr[:500],
        )

    return VerifyResult(
        ok=data.get("ok", False),
        xbf_path=data.get("xbf_path", str(p)),
        errors=data.get("errors", []),
        warnings=data.get("warnings", []),
        native_crash=data.get("native_crash", False),
        design_root_present=data.get("design_root_present", False),
        schema_version=data.get("schema_version"),
        index_entry_count=data.get("index_entry_count", 0),
        tnaming_label_count=data.get("tnaming_label_count", 0),
        manifest_sha256=data.get("manifest_sha256"),
        raw_stdout=raw_stdout,
        raw_stderr=raw_stderr,
    )
