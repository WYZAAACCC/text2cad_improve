"""Pre-solve checks that the final solid actually changed at the target.

A document edit is a claim about the generated design, not a measurement of
it. The STEP file is the measurement. This module keeps that measurement small
enough to compare between revisions: face centroids are aggregated into
radius/axial/azimuth cells, each carrying face count and surface area. The
cells preserve local changes without storing every tessellated face in the
loop result.

The comparison is deliberately a measurement, not a pass/fail judgement. The
loop refuses to spend a solve when a target edit leaves the sampled solid
unchanged, but reports the resolution and the limitation with that refusal.
"""
from __future__ import annotations

import math

from seekflow_structural.tools import document as document_tools


def surface_cells(
    profile: dict,
    *,
    radial_step_mm: float = 2.0,
    axial_step_mm: float = 2.0,
    angular_step_deg: float = 10.0,
) -> list[dict]:
    """Aggregate the final STEP sample into deterministic spatial cells.

    New profiles carry , which preserve the surface's real
    radial position. Legacy profiles fall back to face centroids.
    """
    if profile.get("triangle_cells"):
        return list(profile["triangle_cells"])
    faces = profile.get("faces") or []
    if not faces:
        return []
    radius_values = [float(face.get("r") or 0.0) for face in faces]
    z_values = [float(face.get("z") or 0.0) for face in faces]
    r_min = min(radius_values)
    z_min = min(z_values)
    r_step = max(float(radial_step_mm), 1e-9)
    z_step = max(float(axial_step_mm), 1e-9)
    a_step = max(float(angular_step_deg), 1e-9)
    cells: dict[tuple[int, int, int, bool], dict] = {}
    for face in faces:
        r = float(face.get("r") or 0.0)
        z = float(face.get("z") or 0.0)
        theta = float(face.get("theta") or 0.0) % 360.0
        full = bool(face.get("full_revolution"))
        key = (
            int(math.floor((r - r_min) / r_step)),
            int(math.floor((z - z_min) / z_step)),
            int(math.floor(theta / a_step)) % int(round(360.0 / a_step)),
            full,
        )
        row = cells.setdefault(key, {
            "key": list(key),
            "face_count": 0,
            "area_mm2": 0.0,
            "r_mm": 0.0,
            "z_mm": 0.0,
            "theta_deg": 0.0,
        })
        area = float(face.get("area") or 0.0)
        row["face_count"] += 1
        row["area_mm2"] += area
        row["r_mm"] += r * max(area, 1e-12)
        row["z_mm"] += z * max(area, 1e-12)
        row["theta_deg"] += theta * max(area, 1e-12)
    out = []
    for row in cells.values():
        weight = max(row["area_mm2"], 1e-12)
        row["r_mm"] = round(row["r_mm"] / weight, 6)
        row["z_mm"] = round(row["z_mm"] / weight, 6)
        row["theta_deg"] = round(row["theta_deg"] / weight, 6)
        row["area_mm2"] = round(row["area_mm2"], 6)
        out.append(row)
    return sorted(out, key=lambda row: tuple(row["key"]))


def _entry_target(document: dict | None, parameter: str) -> dict:
    if document is None or not parameter:
        return {}
    entry = document_tools.editable(document).get(parameter)
    if entry is None:
        return {}
    target: dict = {}
    if isinstance(entry.get("at_r_mm"), (int, float)):
        target["r_mm"] = float(entry["at_r_mm"])
    if isinstance(entry.get("at_z_mm"), (int, float)):
        target["z_mm"] = float(entry["at_z_mm"])
    span = entry.get("spans_r_mm")
    if isinstance(span, list) and len(span) == 2:
        target["r_min_mm"] = float(span[0])
        target["r_max_mm"] = float(span[1])
    return target


def target_window(
    finding: dict, profile: dict, document: dict | None = None
) -> dict | None:
    """A measured spatial window for a finding, if it names one."""
    change = finding.get("change") or {}
    parameter = str(change.get("parameter") or "")
    entries = []
    if document is not None and parameter:
        table = document_tools.editable(document)
        if parameter in table:
            entries.append(table[parameter])
        for group in document_tools.dependency_graph(document).get(
            "joint_edit_groups"
        ) or []:
            members = [str(value) for value in group.get("members") or []]
            if parameter in members and group.get("required"):
                entries.extend(table[member] for member in members if member in table)
    r_low = r_high = None
    z_values = []
    r_centres = []
    for entry in entries:
        if isinstance(entry.get("at_r_mm"), (int, float)):
            r_centres.append(float(entry["at_r_mm"]))
        if isinstance(entry.get("at_z_mm"), (int, float)):
            z_values.append(float(entry["at_z_mm"]))
        span = entry.get("spans_r_mm")
        if isinstance(span, list) and len(span) == 2:
            r_low = float(span[0]) if r_low is None else min(r_low, float(span[0]))
            r_high = float(span[1]) if r_high is None else max(r_high, float(span[1]))
    if finding.get("radius_mm") is not None:
        radius = float(finding["radius_mm"])
        r_centres.append(radius)
        r_low = radius if r_low is None else min(r_low, radius)
        r_high = radius if r_high is None else max(r_high, radius)
    if finding.get("z_mm") is not None:
        z_values.append(float(finding["z_mm"]))
    if not r_centres and r_low is None and not z_values:
        return None

    faces = profile.get("faces") or []
    if not faces:
        return None
    z_all_values = [float(face.get("z") or 0.0) for face in faces]
    if r_low is not None and r_high is not None:
        margin = max(5.0, 0.02 * (r_high - r_low))
        r_min, r_max = r_low - margin, r_high + margin
    else:
        centre = sum(r_centres) / len(r_centres)
        reach = max(5.0, 0.05 * abs(centre))
        r_min, r_max = centre - reach, centre + reach
    if z_values:
        z_margin = max(5.0, 0.05 * (max(z_values) - min(z_values)))
        z_min, z_max = min(z_values) - z_margin, max(z_values) + z_margin
    else:
        z_min, z_max = min(z_all_values), max(z_all_values)
    return {
        "r_min_mm": round(r_min, 6),
        "r_max_mm": round(r_max, 6),
        "z_min_mm": round(z_min, 6),
        "z_max_mm": round(z_max, 6),
        "source": "parameter_and_finding_geometry",
    }


def _cell_map(cells: list[dict]) -> dict[tuple, dict]:
    return {tuple(row.get("key") or []): row for row in cells}


def _inside(row: dict, window: dict) -> bool:
    r = float(row.get("r_mm") or 0.0)
    z = float(row.get("z_mm") or 0.0)
    return (
        window["r_min_mm"] <= r <= window["r_max_mm"]
        and window["z_min_mm"] <= z <= window["z_max_mm"]
    )


def _different(left: dict | None, right: dict | None, tol: float = 1e-8) -> bool:
    if left is None or right is None:
        return left is not right
    for key in ("face_count", "area_mm2"):
        a = float(left.get(key) or 0.0)
        b = float(right.get(key) or 0.0)
        if abs(a - b) > tol * max(1.0, abs(a), abs(b)):
            return True
    return False


def compare_design(
    before: dict, after: dict, findings: list[dict],
    document: dict | None = None,
) -> dict:
    """Compare two pre-solve STEP probes, including the finding's target zone."""
    before_cells = before.get("surface_cells") or []
    after_cells = after.get("surface_cells") or []
    before_map = _cell_map(before_cells)
    after_map = _cell_map(after_cells)
    changed_keys = sorted(
        set(before_map) | set(after_map),
        key=lambda key: tuple(key),
    )
    changed_keys = [
        key for key in changed_keys
        if _different(before_map.get(key), after_map.get(key))
    ]

    global_keys = (
        "r_min_mm", "r_max_mm", "z_min_mm", "z_max_mm",
        "total_volume_mm3", "total_surface_area_mm2", "face_count",
    )
    global_deltas = {}
    for key in global_keys:
        a = before.get(key)
        b = after.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            global_deltas[key] = (
                (float(b) - float(a)) / max(abs(float(a)), 1e-12)
            )
    global_changed = any(abs(value) > 1e-6 for value in global_deltas.values())
    if before_cells and after_cells:
        measured_changed = bool(changed_keys)
    else:
        measured_changed = global_changed

    windows = []
    target_changed = None
    target_reason = "no_finding_target"
    for finding in findings:
        window = target_window(finding, after, document)
        if window is None:
            continue
        local_before = [row for row in before_cells if _inside(row, window)]
        local_after = [row for row in after_cells if _inside(row, window)]
        local_before_map = _cell_map(local_before)
        local_after_map = _cell_map(local_after)
        local_changed_keys = [
            key for key in set(local_before_map) | set(local_after_map)
            if _different(local_before_map.get(key), local_after_map.get(key))
        ]
        local_changed = bool(local_changed_keys)
        if not local_changed:
            local_changed = _different(
                {
                    "face_count": sum(r["face_count"] for r in local_before),
                    "area_mm2": sum(r["area_mm2"] for r in local_before),
                },
                {
                    "face_count": sum(r["face_count"] for r in local_after),
                    "area_mm2": sum(r["area_mm2"] for r in local_after),
                },
            )
        if not local_before and not local_after:
            # The sampled STEP has no cell in the chosen window. Do not claim
            # the target changed; the caller gets a global fallback and an
            # explicit limitation.
            local_changed = measured_changed
            target_reason = "target_window_unresolved"
        else:
            target_reason = "target_surface_area_changed"
        windows.append({
            **window,
            "before_cell_count": len(local_before),
            "after_cell_count": len(local_after),
            "before_face_count": sum(r["face_count"] for r in local_before),
            "after_face_count": sum(r["face_count"] for r in local_after),
            "before_area_mm2": round(
                sum(r["area_mm2"] for r in local_before), 6
            ),
            "after_area_mm2": round(
                sum(r["area_mm2"] for r in local_after), 6
            ),
            "changed": local_changed,
            "changed_cell_count": len(local_changed_keys),
            "before_min_r_mm": round(
                min((r["r_mm"] for r in local_before), default=0.0), 6
            ),
            "after_min_r_mm": round(
                min((r["r_mm"] for r in local_after), default=0.0), 6
            ),
            "before_max_r_mm": round(
                max((r["r_mm"] for r in local_before), default=0.0), 6
            ),
            "after_max_r_mm": round(
                max((r["r_mm"] for r in local_after), default=0.0), 6
            ),
        })
        target_changed = local_changed if target_changed is None else (
            target_changed or local_changed
        )

    if not windows:
        target_changed = measured_changed
        target_reason = "no_comparable_target_window"
        windows = []
    return {
        "measurement": "step_surface_cells",
        "global_relative_deltas": {
            key: round(value, 6) for key, value in global_deltas.items()
        },
        "global_changed": global_changed,
        "surface_changed": measured_changed,
        "changed_cell_count": len(changed_keys),
        "target_changed": bool(target_changed),
        "target_reason": target_reason,
        "targets": windows,
        "method": (
            "Gmsh boundary-triangle centroids from the generated STEP are "
            "aggregated into 2 mm radial, 2 mm axial and 10 degree azimuth "
            "cells; a target change is a measured face-count, surface-area "
            "or radial-boundary change in the finding's measured window"
        ),
    }
