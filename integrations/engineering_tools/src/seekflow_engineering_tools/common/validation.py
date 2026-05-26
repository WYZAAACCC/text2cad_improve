"""Input validation utilities for engineering tool parameters."""

from __future__ import annotations


def validate_positive(value: float, name: str) -> float:
    """Ensure *value* > 0, raise with a clear message."""
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


def validate_non_negative(value: float, name: str) -> float:
    """Ensure *value* >= 0."""
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")
    return value


def validate_range(value: float, name: str, low: float, high: float) -> float:
    """Ensure low <= value <= high."""
    if not (low <= value <= high):
        raise ValueError(f"{name} must be between {low} and {high}, got {value}")
    return value


def sanitise_jobname(jobname: str, max_len: int = 64) -> str:
    """Keep only alphanumeric, dash, underscore; truncate to *max_len*."""
    safe = "".join(ch for ch in jobname if ch.isalnum() or ch in ("_", "-"))
    if not safe:
        safe = "unnamed"
    return safe[:max_len]
