"""Generative CAD-IR path — LLM-authored feature graph → fixed runner → STEP artifact.

This package is deliberately isolated from the deterministic primitive path.
It produces lower-trust reference geometry only, validated through a strict
pipeline of schema/registry/graph/semantic/geometry preflight checks.
"""

from __future__ import annotations
