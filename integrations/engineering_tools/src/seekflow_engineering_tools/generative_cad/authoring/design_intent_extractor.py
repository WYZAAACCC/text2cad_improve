"""Deterministic design intent extraction from natural language prompts.

Uses regex patterns to extract explicit dimensions, counts, and feature
expectations from user prompts. This is a pragmatic fallback — a future
version may use LLM-based extraction for richer intent capture.

Reference: lm_skill_base19.md §3.4.2
"""

from __future__ import annotations

import re

from seekflow_engineering_tools.generative_cad.runtime.design_intent import (
    BBoxExpectation,
    CriticalDimensionExpectation,
    DesignIntentMetrics,
    FeatureExpectation,
    RangeMm,
    VolumeExpectation,
)


def extract_design_intent_metrics(
    user_request: str,
    route_plan=None,
) -> DesignIntentMetrics:
    """Extract design intent metrics from a user prompt using regex patterns.

    Detects:
      - Explicit dimension patterns (e.g., "150x150x25", "diameter 100")
      - Feature count patterns ("8 holes", "10 ribs", "12 turns")
      - Critical dimensions with tolerances

    When extraction is ambiguous, returns empty expectations rather than
    guesses — semantic postcheck will pass with low confidence.
    """
    text = user_request.lower() if user_request else ""

    # ── Dimension extraction ──
    bbox = _extract_bbox(text)
    volume = _extract_volume(text)
    critical_dims = _extract_critical_dimensions(text, user_request)
    features = _extract_features(text)
    turns = _extract_turns(text)

    if turns and not critical_dims:
        critical_dims.append(CriticalDimensionExpectation(
            name="helix_turns",
            target_mm=float(turns),
            tolerance_mm=max(1, turns * 0.1),
            measurement="helix_turns",
        ))

    return DesignIntentMetrics(
        bbox=bbox,
        volume=volume,
        critical_dimensions=critical_dims,
        features=features,
        expected_body_count=1,
        allow_degraded_ops=False,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Extraction helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _extract_bbox(text: str) -> BBoxExpectation | None:
    """Extract bounding box from patterns like '150x150x25', '150×150×25'."""
    # Match dimension triples: number × number × number
    m = re.search(r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)', text)
    if m:
        w, h, d = float(m.group(1)), float(m.group(2)), float(m.group(3))
        tolerance = max(w, h, d) * 0.05 + 0.5
        return BBoxExpectation(
            x_mm=RangeMm(min=w - tolerance, max=w + tolerance),
            y_mm=RangeMm(min=h - tolerance, max=h + tolerance),
            z_mm=RangeMm(min=d - tolerance, max=d + tolerance),
        )
    return None


def _extract_volume(text: str) -> VolumeExpectation | None:
    """Extract volume constraints — currently heuristic."""
    # No explicit volume in most prompts; skip
    return None


def _extract_critical_dimensions(text: str, original: str) -> list[CriticalDimensionExpectation]:
    """Extract critical dimensions like diameters, heights, lengths."""
    dims: list[CriticalDimensionExpectation] = []

    # Outer diameter
    m = re.search(r'(?:outer\s*(?:diameter|dia)|od|外径)\s*[:=]?\s*(\d+(?:\.\d+)?)', text)
    if m:
        val = float(m.group(1))
        dims.append(CriticalDimensionExpectation(
            name="outer_diameter", target_mm=val,
            tolerance_mm=max(val * 0.05, 0.5),
            measurement="outer_diameter_xy",
        ))

    # Height / thickness
    m = re.search(r'(?:height|thickness|高|厚)\s*[:=]?\s*(\d+(?:\.\d+)?)', text)
    if m:
        val = float(m.group(1))
        dims.append(CriticalDimensionExpectation(
            name="height", target_mm=val,
            tolerance_mm=max(val * 0.05, 0.5),
            measurement="height_z",
        ))

    # Length
    m = re.search(r'(?:length|长)\s*[:=]?\s*(\d+(?:\.\d+)?)', text)
    if m:
        val = float(m.group(1))
        dims.append(CriticalDimensionExpectation(
            name="length", target_mm=val,
            tolerance_mm=max(val * 0.05, 0.5),
            measurement="bbox_z",
        ))

    return dims


def _extract_features(text: str) -> list[FeatureExpectation]:
    """Extract expected feature counts."""
    features: list[FeatureExpectation] = []

    patterns = [
        (r'(\d+)\s* bolts?\b', "hole"),
        (r'(\d+)\s* holes?\b', "hole"),
        (r'(\d+)\s* ribs?\b', "rib"),
        (r'(\d+)\s* bosses?\b', "boss"),
        (r'(\d+)\s* grooves?\b', "groove"),
        (r'(\d+)\s* threads?\b', "thread"),
    ]
    for pat, kind in patterns:
        m = re.search(pat, text)
        if m:
            count = int(m.group(1))
            features.append(FeatureExpectation(kind=kind, min_count=count, max_count=count))

    return features


def _extract_turns(text: str) -> float | None:
    """Extract helix turns count."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:turns?|圈)', text)
    if m:
        return float(m.group(1))
    return None
