"""Preflight-Guided Repair Hints — actionable parameter adjustments for LLM retry.

.. deprecated:: v0.8 (指导书 Phase 5)
   中心化 hint 生成属 deprecated compatibility path — 目标形态是各
   RepairProvider 自行从 Issue.expected 生成候选方案 (§14 迁移映射)。
   在孔/槽等规则抽入 extensions/ 前保留本模块。

When preflight detects geometric contradictions, it computes feasible parameter
ranges and stores them in ValidationIssue.expected dict. This module extracts
those ranges and formats them as LLM-repairable hints.

Architecture: This does NOT auto-fix parameters. It only computes what ranges
WOULD be valid, so the LLM (or a deterministic solver) can select from them.
"""

from __future__ import annotations


def build_repair_hints_from_validation(report) -> str:
    """Extract actionable repair hints from a ValidationReport.

    v6.1: Detects double-bind situations where both bore-intersection AND
    profile-exceed constraints fire simultaneously (wall too thin for holes).
    Provides coordinated multi-parameter adjustment strategy.
    """
    issues = getattr(report, 'issues', []) or []
    if not issues:
        return ""

    # Group issues by node_id to detect double-bind
    by_node: dict[str, list] = {}
    for issue in issues:
        nid = getattr(issue, 'node_id', None) or '__global__'
        by_node.setdefault(nid, []).append(issue)

    hints: list[str] = []

    for nid, node_issues in by_node.items():
        codes = {getattr(i, 'code', '') for i in node_issues}

        # ── Proactive double-bind detection ──
        # Even if only ONE constraint fires, compute if the OTHER would also
        # be violated. This detects "wall too thin for holes" preemptively.
        bore_issue = next((i for i in node_issues if getattr(i, 'code', '') == "hole_pattern_intersects_center_bore"), None)
        profile_issue = next((i for i in node_issues if getattr(i, 'code', '') == "hole_pattern_outside_profile"), None)

        if bore_issue or profile_issue:
            # Both bounds are now stored in EACH issue's expected dict (v6.1)
            expected = {}
            if bore_issue: expected.update(getattr(bore_issue, 'expected', {}) or {})
            if profile_issue: expected.update(getattr(profile_issue, 'expected', {}) or {})
            min_pcd = expected.get("min_pcd_mm")
            max_pcd = expected.get("max_pcd_mm")
            max_bore = expected.get("max_bore_dia_mm")

            # If we have both bounds (one from each constraint type), check for double-bind
            if min_pcd is not None and max_pcd is not None and min_pcd > max_pcd:
                # Wall thickness insufficient — coordinated fix required
                pcd_gap = min_pcd - max_pcd
                # Calculate hole reduction needed: gap/2 (each mm of hole_dia reduction closes gap by 2mm)
                hole_reduction = pcd_gap / 2.0

                hints.append(
                    f"[CRITICAL] Wall too thin for holes: feasible PCD range [{max_pcd:.0f}, {min_pcd:.0f}]mm "
                    f"is empty (gap={pcd_gap:.0f}mm). "
                    f"COORDINATED FIX (pick ONE):\n"
                    f"  (A) Reduce hole_dia by >= {hole_reduction:.0f}mm (simplest) OR\n"
                    f"  (B) Reduce bore_dia to <= {max_bore:.0f}mm" + (f" AND set PCD to {max_pcd:.0f}mm" if max_pcd else "") + " OR\n"
                    f"  (C) Increase outer radius so wall >= hole_dia + 2mm margin."
                )
                continue  # Skip individual hints — coordinated fix is enough

        # ── Double-bind: both constraints fire simultaneously ──
        if "hole_pattern_intersects_center_bore" in codes and "hole_pattern_outside_profile" in codes:
            bore_issue = next((i for i in node_issues if getattr(i, 'code', '') == "hole_pattern_intersects_center_bore"), None)
            profile_issue = next((i for i in node_issues if getattr(i, 'code', '') == "hole_pattern_outside_profile"), None)

            if bore_issue and profile_issue:
                bore_expected = getattr(bore_issue, 'expected', {}) or {}
                profile_expected = getattr(profile_issue, 'expected', {}) or {}
                min_pcd = bore_expected.get("min_pcd_mm")
                max_pcd = profile_expected.get("max_pcd_mm")
                max_bore = bore_expected.get("max_bore_dia_mm")

                if min_pcd and max_pcd and min_pcd > max_pcd:
                    # Wall thickness insufficient — need MULTI-PARAMETER adjustment
                    pcd_gap = min_pcd - max_pcd
                    hole_dia_hint = ""
                    # Calculate required wall thickness
                    # wall = profile_r - bore_r, need wall >= 2*hole_r + 2*MARGIN
                    if max_bore:
                        hints.append(
                            f"[CRITICAL] Wall too thin for holes: PCD must be between {max_pcd:.0f}-{min_pcd:.0f}mm "
                            f"but {max_pcd:.0f} < {min_pcd:.0f} (gap={pcd_gap:.0f}mm). "
                            f"COORDINATED FIX (pick one):\n"
                            f"  (A) Reduce hole_dia by >= {pcd_gap:.0f}mm OR\n"
                            f"  (B) Reduce bore_dia to <= {max_bore:.0f}mm AND keep PCD in [{max_pcd:.0f}, {min_pcd:.0f}] OR\n"
                            f"  (C) Increase outer radius to accommodate current PCD+bore."
                        )
                        continue  # Skip individual hints for this node

        # ── Individual hints ──
        for issue in node_issues:
            hint = _extract_hint(issue)
            if hint:
                hints.append(hint)

    if not hints:
        return ""

    return (
        "\n\n=== REPAIR HINTS (computed feasible parameter ranges) ===\n"
        + "\n".join(f"- {h}" for h in hints)
        + "\n=== END REPAIR HINTS ===\n"
    )


def _extract_hint(issue) -> str | None:
    """Extract a single repair hint from a ValidationIssue."""
    code = getattr(issue, 'code', '')
    expected = getattr(issue, 'expected', {}) or {}
    actual = getattr(issue, 'actual', {}) or {}

    if code == "hole_pattern_intersects_center_bore":
        min_pcd = expected.get("min_pcd_mm")
        max_bore = expected.get("max_bore_dia_mm")
        if min_pcd and max_bore:
            return (
                f"Adjust PCD to >= {min_pcd:.0f}mm OR reduce bore_dia to <= {max_bore:.0f}mm "
                f"(holes at PCD/2-hole_r = {actual.get('hole_inner_edge_mm','?')}mm "
                f"must not overlap bore)"
            )
        elif min_pcd:
            return f"Increase PCD to >= {min_pcd:.0f}mm to avoid bore overlap"

    elif code == "hole_pattern_outside_profile":
        max_pcd = expected.get("max_pcd_mm")
        min_profile_r = None
        outer_edge = actual.get("outer_edge_mm")
        if max_pcd:
            hint = f"Reduce PCD to <= {max_pcd:.0f}mm to fit within profile"
            if outer_edge:
                hint += f" (holes currently extend to r={outer_edge:.0f}mm)"
            return hint

    elif code == "a002_bore_gt_outer":
        # Bore larger than outer radius — extract max feasible bore from message
        return "Reduce bore diameter to be strictly less than outer diameter"

    elif code == "a002_bore_too_large":
        return "Reduce bore diameter or increase outer radius to leave sufficient wall thickness"

    return None
