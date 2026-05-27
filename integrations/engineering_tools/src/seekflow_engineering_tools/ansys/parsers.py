"""Parse ANSYS APDL result summary files."""

from __future__ import annotations

import re
from pathlib import Path


_MM_RE = re.compile(r"MAX_DISPLACEMENT_MM\s*=\s*([\d.+\-Ee]+)")
_STRESS_RE = re.compile(r"MAX_STRESS_MPA\s*=\s*([\d.+\-Ee]+)")
_VON_MISES_RE = re.compile(r"MAX_VON_MISES_MPA\s*=\s*([\d.+\-Ee]+)")
_KT_RE = re.compile(r"STRESS_CONCENTRATION_Kt\s*=\s*([\d.+\-Ee.]+)")
_TEMP_RE = re.compile(r"TMIN_C\s*=\s*([\d.+\-Ee]+).*TMAX_C\s*=\s*([\d.+\-Ee]+).*TMID_C\s*=\s*([\d.+\-Ee]+)")
_MODE_RE = re.compile(r"MODE_(\d+)_HZ\s*=\s*([\d.+\-Ee]+)")
_MODAL_FREQ_RE = re.compile(r"MODAL_FREQUENCIES_HZ\s*=\s*([\d.+\-Ee, ]+)")
# Also match the raw APDL output format: "MODE  N. FREQ_HZ= value"
_MODE_RAW_RE = re.compile(r"MODE\s+\d+\.\s+FREQ_HZ=\s*([\d.+\-Ee]+)")
_MODE_BLF_RE = re.compile(r"MODE\s+\d+\.\s+BLF=\s*([\d.+\-Ee]+)")
_PCR_RAW_RE = re.compile(r"Pcr_N=\s*([\d.+\-Ee]+)")
_BUCKLING_RE = re.compile(r"BUCKLING_LOAD_FACTOR\s*=\s*([\d.+\-Ee]+)")
_BLF_FALLBACK_RE = re.compile(r"BLF\s*=\s*([\d.+\-Ee]+)")
_PCR_RE = re.compile(r"PCR_N\s*=\s*([\d.+\-Ee]+)")
_PLASTIC_STRAIN_RE = re.compile(r"MAX_PLASTIC_STRAIN\s*=\s*([\d.+\-Ee]+)")
_TIP_DISP_RE = re.compile(r"TIP_DISPLACEMENT_MM\s*=\s*([\d.+\-Ee]+)")
_STRESS_FACTOR_RE = re.compile(r"STRESS_CONCENTRATION_FACTOR\s*=\s*([\d.+\-Ee.]+)")


def parse_result_summary(path: Path) -> dict:
    """Extract key metrics from the output file or ``result_summary.txt``.

    Supports: static, thermal, modal, buckling, and bilinear plastic analysis types.
    If *path* points to a .out file, also checks for ``result_summary.txt`` in the same directory.
    """
    metrics: dict = {}
    if not path.exists():
        return metrics

    text = path.read_text(errors="ignore")

    # Also check result_summary.txt in the same directory (APDL /OUTPUT creates separate file)
    summary_path = path.parent / "result_summary.txt"
    if summary_path.exists():
        text = text + "\n" + summary_path.read_text(errors="ignore")

    # Static structural metrics
    for pat, key in [
        (_MM_RE, "max_displacement_mm"),
        (_STRESS_RE, "max_stress_mpa"),
        (_VON_MISES_RE, "max_von_mises_mpa"),
        (_KT_RE, "stress_concentration_kt"),
        (_STRESS_FACTOR_RE, "stress_concentration_factor"),
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

    # Modal metrics (both structured and raw APDL formats)
    modal_hz = []
    for m in _MODE_RE.finditer(text):
        try:
            mode_num = int(m.group(1))
            freq = float(m.group(2))
            metrics[f"mode_{mode_num}_hz"] = freq
            modal_hz.append(freq)
        except ValueError:
            pass

    # Fallback: raw APDL format "MODE  N. FREQ_HZ= value"
    if not modal_hz:
        for m in _MODE_RAW_RE.finditer(text):
            try:
                freq = float(m.group(1))
                modal_hz.append(freq)
            except ValueError:
                pass

    if modal_hz:
        metrics["modal_frequencies_hz"] = modal_hz

    # Buckling metrics (both structured and raw APDL formats)
    m = _BUCKLING_RE.search(text)
    if m:
        try:
            metrics["buckling_load_factor"] = float(m.group(1))
        except ValueError:
            pass

    # Fallback: raw APDL format "MODE  N. BLF= value Pcr_N= value"
    if "buckling_load_factor" not in metrics:
        m = _MODE_BLF_RE.search(text)
        if m:
            try:
                metrics["buckling_load_factor"] = float(m.group(1))
            except ValueError:
                pass

    # Second fallback for BLF
    if "buckling_load_factor" not in metrics:
        m = _BLF_FALLBACK_RE.search(text)
        if m:
            try:
                metrics["buckling_load_factor"] = float(m.group(1))
            except ValueError:
                pass

    m = _PCR_RE.search(text)
    if m:
        try:
            metrics["pcr_n"] = float(m.group(1))
        except ValueError:
            pass

    # Fallback for Pcr_N
    if "pcr_n" not in metrics:
        m = _PCR_RAW_RE.search(text)
        if m:
            try:
                metrics["pcr_n"] = float(m.group(1))
            except ValueError:
                pass

    # Bilinear plastic metrics
    m = _PLASTIC_STRAIN_RE.search(text)
    if m:
        try:
            metrics["max_plastic_strain"] = float(m.group(1))
        except ValueError:
            pass

    m = _TIP_DISP_RE.search(text)
    if m:
        try:
            metrics["tip_displacement_mm"] = float(m.group(1))
        except ValueError:
            pass

    return metrics


def scan_out_for_errors(out_path: Path) -> tuple[list[str], list[str]]:
    """Scan ANSYS output file for errors and warnings.

    Returns (errors, warnings) tuple.
    """
    if not out_path.exists():
        return [], []

    errors: list[str] = []
    warnings: list[str] = []

    for line in out_path.read_text(errors="ignore").splitlines():
        if "*** ERROR ***" in line:
            errors.append(line.strip())
        elif "*** WARNING ***" in line or "WARNING" in line:
            warnings.append(line.strip())

    return errors, warnings
