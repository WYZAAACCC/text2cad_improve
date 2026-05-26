"""Parse ANSYS APDL result summary files."""

from __future__ import annotations

import re
from pathlib import Path


_MM_RE = re.compile(r"MAX_DISPLACEMENT_MM\s*=\s*([\d.+\-Ee]+)")
_STRESS_RE = re.compile(r"MAX_STRESS_MPA\s*=\s*([\d.+\-Ee]+)")
_KT_RE = re.compile(r"STRESS_CONCENTRATION_Kt\s*=\s*([\d.+\-Ee.]+)")
_TEMP_RE = re.compile(r"TMIN_C\s*=\s*([\d.+\-Ee]+).*TMAX_C\s*=\s*([\d.+\-Ee]+).*TMID_C\s*=\s*([\d.+\-Ee]+)")


def parse_result_summary(path: Path) -> dict:
    """Extract key metrics from ``result_summary.txt``."""
    metrics: dict = {}
    if not path.exists():
        return metrics

    text = path.read_text(errors="ignore")

    for pat, key in [
        (_MM_RE, "max_displacement_mm"),
        (_STRESS_RE, "max_stress_mpa"),
        (_KT_RE, "stress_concentration_kt"),
    ]:
        m = pat.search(text)
        if m:
            try:
                metrics[key] = float(m.group(1))
            except ValueError:
                metrics[key] = None

    # Temperature fields (3 values)
    m = _TEMP_RE.search(text)
    if m:
        try:
            metrics["tmin_c"] = float(m.group(1))
            metrics["tmax_c"] = float(m.group(2))
            metrics["tmid_c"] = float(m.group(3))
        except ValueError:
            pass

    return metrics


def scan_out_for_errors(out_path: Path) -> list[str]:
    """Return every line from *out_path* containing '*** ERROR ***'."""
    if not out_path.exists():
        return []
    errors: list[str] = []
    for line in out_path.read_text(errors="ignore").splitlines():
        if "*** ERROR ***" in line:
            errors.append(line.strip())
    return errors
