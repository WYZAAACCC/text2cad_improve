"""Sketch profile postcondition checks — verify geometry after edit operations.

Each check returns a structured report so that callers can decide to
fail-closed, warn, or repair based on operation.required and degradation_policy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PostconditionCheck:
    code: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PostconditionReport:
    checks: list[PostconditionCheck] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[PostconditionCheck]:
        return [c for c in self.checks if not c.passed]


# ── Profile checks ────────────────────────────────────────────────────

def check_wire_count(wires: list, expected: int = 1) -> PostconditionCheck:
    n = len(wires)
    return PostconditionCheck(
        code="PROFILE_HAS_SINGLE_EXPECTED_WIRE",
        passed=n == expected,
        message=f"expected {expected} wire(s), got {n}" if n != expected else "",
        details={"expected": expected, "actual": n},
    )


def check_closed(wire) -> PostconditionCheck:
    try:
        closed = wire.IsClosed()
    except Exception as exc:
        return PostconditionCheck(
            code="PROFILE_IS_CLOSED",
            passed=False,
            message=f"failed to check IsClosed: {exc}",
        )
    return PostconditionCheck(
        code="PROFILE_IS_CLOSED",
        passed=closed,
        message="" if closed else "wire is not closed",
        details={"is_closed": closed},
    )


def check_no_zero_length_edge(vertices: list[tuple[float, float]]) -> PostconditionCheck:
    for i, (p1, p2) in enumerate(zip(vertices, vertices[1:] + vertices[:1])):
        d = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if d < 1e-9:
            return PostconditionCheck(
                code="PROFILE_HAS_NO_ZERO_LENGTH_EDGE",
                passed=False,
                message=f"zero-length edge at index {i}",
                details={"index": i},
            )
    return PostconditionCheck(code="PROFILE_HAS_NO_ZERO_LENGTH_EDGE", passed=True)


def check_no_duplicate_consecutive(points: list[tuple[float, float]]) -> PostconditionCheck:
    for i, (p1, p2) in enumerate(zip(points, points[1:] + points[:1])):
        if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) < 1e-9:
            return PostconditionCheck(
                code="PROFILE_HAS_NO_DUPLICATE_CONSECUTIVE_VERTEX",
                passed=False,
                message=f"duplicate consecutive vertices at index {i}",
                details={"index": i},
            )
    return PostconditionCheck(code="PROFILE_HAS_NO_DUPLICATE_CONSECUTIVE_VERTEX", passed=True)


# ── Fillet checks ──────────────────────────────────────────────────────

def check_fillet_arc_count(
    before_vert_count: int,
    after_vert_count: int,
    expected_arc_count: int,
) -> PostconditionCheck:
    """After filleting, the vertex count should increase by expected_arc_count
    (each fillet replaces 1 sharp corner with 2 tangents + N arc points)."""
    delta = after_vert_count - before_vert_count
    # Each fillet typically adds 1-3 extra vertices (tangent pts + arc pts)
    min_expected = expected_arc_count
    return PostconditionCheck(
        code="FILLET_TARGET_COUNT_MATCHES",
        passed=delta >= min_expected,
        message=(
            "" if delta >= min_expected
            else f"vertex count delta {delta} < expected minimum {min_expected}"
        ),
        details={
            "before_verts": before_vert_count,
            "after_verts": after_vert_count,
            "delta": delta,
            "expected_arc_count": expected_arc_count,
        },
    )


def check_fillet_radius(
    actual_radius_mm: float,
    requested_radius_mm: float,
    tolerance_mm: float = 0.01,
) -> PostconditionCheck:
    ok = abs(actual_radius_mm - requested_radius_mm) <= tolerance_mm
    return PostconditionCheck(
        code="FILLET_RADIUS_MATCHES",
        passed=ok,
        message=(
            "" if ok
            else f"actual radius {actual_radius_mm:.4f} != requested {requested_radius_mm:.4f}"
        ),
        details={"actual": actual_radius_mm, "requested": requested_radius_mm},
    )


# ── Arc checks ────────────────────────────────────────────────────────

def check_arc_center(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    radius_mm: float,
    tolerance_mm: float = 1e-5,
) -> PostconditionCheck:
    r1 = math.hypot(start[0] - center[0], start[1] - center[1])
    r2 = math.hypot(end[0] - center[0], end[1] - center[1])
    ok = abs(r1 - radius_mm) <= tolerance_mm and abs(r2 - radius_mm) <= tolerance_mm
    return PostconditionCheck(
        code="ARC_CENTER_MATCHES",
        passed=ok,
        message=(
            "" if ok
            else f"|start-center|={r1:.6f}, |end-center|={r2:.6f}, expected R={radius_mm}"
        ),
        details={"r_start": r1, "r_end": r2, "requested": radius_mm},
    )
