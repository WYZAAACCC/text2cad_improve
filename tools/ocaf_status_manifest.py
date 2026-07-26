"""Generate OCAF_BUILD_MANIFEST.json for CI reproducibility (v5.0 §4).

Usage:
    cd integrations/engineering_tools
    python ../../tools/ocaf_status_manifest.py

Output:
    docs/generated/OCAF_BUILD_MANIFEST.json

The manifest records exact environment, test counts (passed/failed/skipped/ignored),
and a SHA256 of the combined test output — making it impossible to accidentally
count ignored tests as passed.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path


def _find_repo_root() -> Path:
    p = Path(__file__).resolve().parent.parent  # tools → auto_detection_process
    return p


def _get_git_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _get_ocp_version() -> str:
    try:
        import OCP
        return getattr(OCP, "__version__", "unknown")
    except Exception:
        return "unknown"


def _get_occt_version() -> str:
    try:
        from OCP import __occt_version__
        return str(__occt_version__)
    except Exception:
        return "unknown"


def _get_cadquery_version() -> str:
    try:
        import cadquery
        return cadquery.__version__
    except Exception:
        return "unknown"


def _run_tests(repo_root: Path) -> dict:
    """Run the OCAF test suite and parse JSON report."""
    test_dir = repo_root / "integrations" / "engineering_tools" / "tests" / "generative_cad" / "topology" / "ocaf"
    cwd = repo_root / "integrations" / "engineering_tools"
    python_exe = repo_root / ".conda" / "python.exe"
    if not python_exe.exists():
        python_exe = repo_root / ".conda" / "python"
    if not python_exe.exists():
        python_exe = Path(sys.executable)

    t0 = time.perf_counter()

    result = subprocess.run(
        [
            str(python_exe), "-m", "pytest",
            str(test_dir),
            "--ignore", str(test_dir / "smoke" / "test_tnaming_roundtrip.py"),
            "-v", "--tb=short",
        ],
        cwd=str(cwd),
        capture_output=True, text=True,
        timeout=300,
    )

    elapsed = round(time.perf_counter() - t0, 2)
    raw_output = result.stdout + result.stderr
    output_hash = hashlib.sha256(raw_output.encode()).hexdigest()

    # Parse test counts from pytest output
    passed = 0
    failed = 0
    skipped = 0

    # Last line: "= X passed, Y failed, Z warnings in N.Ns ="
    for line in reversed(raw_output.splitlines()):
        if "passed" in line and "=" in line:
            import re
            m_passed = re.search(r"(\d+)\s+passed", line)
            m_failed = re.search(r"(\d+)\s+failed", line)
            m_skipped = re.search(r"(\d+)\s+skipped", line)
            if m_passed:
                passed = int(m_passed.group(1))
            if m_failed:
                failed = int(m_failed.group(1))
            if m_skipped:
                skipped = int(m_skipped.group(1))
            break

    # Collect test file list
    test_files = sorted(
        str(p.relative_to(repo_root)).replace("\\", "/")
        for p in Path(test_dir).rglob("test_*.py")
    )

    return {
        "command": f"pytest tests/generative_cad/topology/ocaf/ --ignore=...test_tnaming_roundtrip.py -v",
        "test_files": test_files,
        "ignored_tests": ["smoke/test_tnaming_roundtrip.py (2 tests, known-fragile: TNaming destructor crash)"],
        "skipped_tests": skipped,
        "passed": passed,
        "failed": failed,
        "duration_seconds": elapsed,
        "report_sha256": output_hash,
    }


def main():
    repo_root = _find_repo_root()

    manifest = {
        "schema": "ocaf_status_manifest_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": _get_git_sha(repo_root),
        "python": sys.version.split()[0],
        "ocp": _get_ocp_version(),
        "occt": _get_occt_version(),
        "cadquery": _get_cadquery_version(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "tests": _run_tests(repo_root),
    }

    out_dir = repo_root / "docs" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "OCAF_BUILD_MANIFEST.json"

    out_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Manifest written to: {out_path}")
    print(f"Tests: {manifest['tests']['passed']} passed, "
          f"{manifest['tests']['failed']} failed, "
          f"{manifest['tests']['skipped_tests']} skipped")
    print(f"SHA256: {manifest['tests']['report_sha256'][:16]}...")


if __name__ == "__main__":
    main()
