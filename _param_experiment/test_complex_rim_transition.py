"""Regression tests for D29-D32 complex rim transition geometry."""

from __future__ import annotations

import math
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from design_families import DESIGN_FAMILIES  # noqa: E402
import param_templates as pt  # noqa: E402


def _disc_points(fid: str) -> list[dict]:
    fam = DESIGN_FAMILIES[fid]
    features = fam.get("features") or {}
    return pt.disc_profile(
        fam["od"], fam["bore"], fam["hub"], fam["rim"], fam["thick"],
        form=fam.get("form", "standard"),
        transition=features.get("transition", "linear"),
        rim_arc_radius_mm=features.get("rim_arc_radius"),
    )["points"]


def test_transition_covers_full_web_rim_span():
    for fid in ("D29", "D30", "D31", "D32"):
        points = _disc_points(fid)
        # Complex rim profiles contain the base outline plus sampled transition points.
        assert len(points) >= 26, (fid, len(points))


def test_transition_has_no_long_diagonal():
    for fid in ("D29", "D30", "D31", "D32"):
        points = _disc_points(fid)
        lower_band = points[3:13]
        gaps = [abs(lower_band[i + 1]["y_mm"] - lower_band[i]["y_mm"]) for i in range(len(lower_band) - 1)]
        # The old bug produced a single ~28-36mm axial jump inside the rim wall.
        assert max(gaps) <= 6.0, (fid, max(gaps))


def test_transition_returns_to_rim_junction():
    for fid in ("D29", "D30", "D31", "D32"):
        points = _disc_points(fid)
        fam = DESIGN_FAMILIES[fid]
        rim_junc = fam["od"] / 2.0 - max(25.0, min(0.17 * fam["od"], 95.0))
        lower_end = next(p for p in points if p["y_mm"] == -fam["rim"] and p["x_mm"] == rim_junc)
        upper_end = next(p for p in points if p["y_mm"] == fam["rim"] and p["x_mm"] == rim_junc)
        assert math.isclose(lower_end["x_mm"], rim_junc, abs_tol=0.01)
        assert math.isclose(upper_end["x_mm"], rim_junc, abs_tol=0.01)
