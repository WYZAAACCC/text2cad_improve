"""AxisymmetricDialect — v0.6: finite checks, envelope tracking, strengthened preflight."""

from __future__ import annotations

import math
from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.contract import AXISYMMETRIC_CONTRACT
from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.handlers import (
    handle_apply_safe_chamfer, handle_cut_annular_groove, handle_cut_center_bore,
    handle_cut_circular_hole_pattern, handle_cut_external_thread,
    handle_cut_internal_thread, handle_cut_rim_slot_pattern, handle_revolve_profile,
)
from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.manifest import AXISYMMETRIC_MANIFEST
from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.params import (
    ApplySafeChamferParams, CutAnnularGrooveParams, CutCenterBoreParams,
    CutCircularHolePatternParams, CutRimSlotPatternParams, RevolveProfileParams,
)
from seekflow_engineering_tools.generative_cad.dialects.axisymmetric.thread_params import (
    CutExternalThreadParams, CutInternalThreadParams,
)
from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalComponent, CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue, ValidationReport


class AxisymmetricDialect:
    dialect_id = "axisymmetric"
    version = "0.2.0"
    phase_order = ("base_solid", "primary_cut", "annular_detail", "pattern_cut", "rim_detail", "edge_treatment", "thread", "cleanup")

    _op_version_map = {k: "1.0.0" for k in [
        "revolve_profile", "cut_center_bore", "cut_annular_groove",
        "cut_circular_hole_pattern", "cut_rim_slot_pattern", "apply_safe_chamfer",
        "cut_internal_thread", "cut_external_thread",
    ]}

    def manifest(self): return dict(AXISYMMETRIC_MANIFEST)
    def contract(self): return dict(AXISYMMETRIC_CONTRACT)

    def op_specs(self) -> dict[tuple[str, str], OperationSpec]:
        return {
            ("revolve_profile", "1.0.0"): OperationSpec(dialect="axisymmetric", op="revolve_profile", op_version="1.0.0", phase="base_solid", input_types=[], output_types=["solid", "frame"], params_model=RevolveProfileParams, effects=["creates_solid", "creates_frame"], postconditions=["valid_solid"], handler=handle_revolve_profile),
            ("cut_center_bore", "1.0.0"): OperationSpec(dialect="axisymmetric", op="cut_center_bore", op_version="1.0.0", phase="primary_cut", input_types=["solid"], output_types=["solid"], params_model=CutCenterBoreParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_center_bore),
            ("cut_annular_groove", "1.0.0"): OperationSpec(dialect="axisymmetric", op="cut_annular_groove", op_version="1.0.0", phase="annular_detail", input_types=["solid"], output_types=["solid"], params_model=CutAnnularGrooveParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_annular_groove),
            ("cut_circular_hole_pattern", "1.0.0"): OperationSpec(dialect="axisymmetric", op="cut_circular_hole_pattern", op_version="1.0.0", phase="pattern_cut", input_types=["solid"], output_types=["solid"], params_model=CutCircularHolePatternParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_circular_hole_pattern),
            ("cut_rim_slot_pattern", "1.0.0"): OperationSpec(dialect="axisymmetric", op="cut_rim_slot_pattern", op_version="1.0.0", phase="rim_detail", input_types=["solid"], output_types=["solid"], params_model=CutRimSlotPatternParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_rim_slot_pattern),
            ("apply_safe_chamfer", "1.0.0"): OperationSpec(dialect="axisymmetric", op="apply_safe_chamfer", op_version="1.0.0", phase="edge_treatment", input_types=["solid"], output_types=["solid"], params_model=ApplySafeChamferParams, effects=["modifies_solid"], postconditions=["valid_solid"], handler=handle_apply_safe_chamfer),
            ("cut_internal_thread", "1.0.0"): OperationSpec(dialect="axisymmetric", op="cut_internal_thread", op_version="1.0.0", phase="thread", input_types=["solid"], output_types=["solid"], params_model=CutInternalThreadParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_internal_thread, summary="Cut an ISO metric internal thread (tapped hole) using helical sweep."),
            ("cut_external_thread", "1.0.0"): OperationSpec(dialect="axisymmetric", op="cut_external_thread", op_version="1.0.0", phase="thread", input_types=["solid"], output_types=["solid"], params_model=CutExternalThreadParams, effects=["cuts_material"], postconditions=["valid_solid"], handler=handle_cut_external_thread, summary="Cut an ISO metric external thread on a cylindrical surface."),
        }

    def default_op_version(self, op): return self._op_version_map[op]
    def get_op_spec(self, op, v=None):
        v = v or self.default_op_version(op)
        key = (op, v); specs = self.op_specs()
        if key not in specs: raise KeyError(f"unknown op/version: {op!r}/{v!r}")
        return specs[key]

    def validate_component(self, component, nodes):
        issues = []
        stage = "dialect_semantics"
        # 1. exactly one base_solid root creation op
        base_solid_nodes = [n for n in nodes if n.phase == "base_solid"]
        if len(base_solid_nodes) != 1:
            issues.append(ValidationIssue(stage=stage, code="axisymmetric_base_solid_count",
                message=f"axisymmetric requires exactly 1 base_solid node, got {len(base_solid_nodes)}",
                severity="error", component_id=component.id))
        # 2. first solid-producing node must be revolve_profile
        solid_creators = [n for n in nodes if n.op == "revolve_profile"]
        for n in solid_creators:
            body_outputs = [o for o in n.outputs if o.name == "body" and o.type == "solid"]
            if not body_outputs:
                issues.append(ValidationIssue(stage=stage, code="revolve_no_body_solid",
                    message=f"revolve_profile node {n.id!r} must output body:solid",
                    severity="error", node_id=n.id, component_id=component.id))
            frame_outputs = [o for o in n.outputs if o.name == "outer_frame" and o.type == "frame"]
            if not frame_outputs:
                issues.append(ValidationIssue(stage=stage, code="revolve_no_outer_frame",
                    message=f"revolve_profile node {n.id!r} must output outer_frame:frame",
                    severity="error", node_id=n.id, component_id=component.id))
        # 3. all cut/modification ops must consume solid and output solid
        for n in nodes:
            if n.phase != "base_solid":
                input_types = [i.resolved_type for i in n.inputs]
                output_types = [o.type for o in n.outputs]
                if "solid" not in input_types and input_types:
                    issues.append(ValidationIssue(stage=stage, code="cut_op_must_consume_solid",
                        message=f"Node {n.id!r} ({n.op}) must consume solid input",
                        severity="error", node_id=n.id, component_id=component.id))
                if not any(t == "solid" for t in output_types):
                    issues.append(ValidationIssue(stage=stage, code="cut_op_must_output_solid",
                        message=f"Node {n.id!r} ({n.op}) must output solid",
                        severity="error", node_id=n.id, component_id=component.id))
        return ValidationReport(ok=not any(i.severity == "error" for i in issues),
                               stage=stage, issues=issues)
    @staticmethod
    def _is_finite_number(x) -> bool:
        return isinstance(x, (int, float)) and math.isfinite(x)

    def preflight_component(self, component, nodes):
        issues = []
        stage = "geometry_preflight"
        MARGIN = 1.0  # mm
        is_finite = AxisymmetricDialect._is_finite_number

        # ── Envelope tracking ──
        profile_max_radius: float | None = None
        profile_min_radius: float | None = None
        center_bore_radius: float | None = None

        # First pass: gather envelope from revolve_profile
        for n in nodes:
            if n.op == "revolve_profile":
                ps = n.typed_params.get("profile_stations") or n.params.get("profile_stations", [])
                if len(ps) < 1:
                    issues.append(ValidationIssue(stage=stage, code="a001_stations_count",
                        message=f"revolve_profile needs >= 1 station, got {len(ps)}",
                        severity="error", node_id=n.id))
                max_r = 0.0
                min_r = float("inf")
                for s in ps:
                    r = s.get("r_mm", 0)
                    if not is_finite(r) or r <= 0:
                        issues.append(ValidationIssue(stage=stage, code="a001_radius_non_positive",
                            message=f"revolve_profile station radius must be > 0 and finite, got {r}",
                            severity="error", node_id=n.id))
                    zf = s.get("z_front_mm", 0); zr = s.get("z_rear_mm", 0)
                    if not is_finite(zf) or not is_finite(zr) or zr <= zf:
                        issues.append(ValidationIssue(stage=stage, code="a001_z_order",
                            message=f"z_rear_mm ({zr}) must be > z_front_mm ({zf}) and finite",
                            severity="error", node_id=n.id))
                    if is_finite(r) and r > 0:
                        max_r = max(max_r, r)
                        min_r = min(min_r, r)
                if max_r > 0 and min_r < float("inf"):
                    profile_max_radius = max_r
                    profile_min_radius = min_r
                    # Single-station cylinder is valid (max_r == min_r OK)
                elif max_r <= 0 or min_r <= 0:
                    issues.append(ValidationIssue(stage=stage, code="a001_radius_range",
                        message=f"max radius ({max_r}) must be > 0, got min radius ({min_r})",
                        severity="error", node_id=n.id))

        # ── A009: revolve_profile 最小半径校验 ──
        # 检测极小半径填充段（0 < r_mm < MIN_PROFILE_RADIUS）。
        # LLM 常输出 r=1.0 的 "hub_lower_fill"/"hub_upper_fill" 段，
        # 这些段产生退化的细针状实体，应移除或增大半径。
        MIN_PROFILE_RADIUS = 0.5  # mm
        for n in nodes:
            if n.op != "revolve_profile":
                continue
            ps = n.typed_params.get("profile_stations") or n.params.get("profile_stations", [])
            for i, s in enumerate(ps):
                r = s.get("r_mm", 0)
                if isinstance(r, dict):
                    continue  # DimExpr, skip — validated at analysis time
                label = s.get("label", "") or ""
                if is_finite(r) and 0 < r < MIN_PROFILE_RADIUS:
                    issues.append(ValidationIssue(
                        stage=stage, code="a009_radius_too_small",
                        message=(
                            f"revolve_profile station {i} (label={label!r}) has radius {r:.3f}mm "
                            f"< minimum {MIN_PROFILE_RADIUS}mm. Sub-millimeter radii produce "
                            f"degenerate needle-like solids. Either increase radius to >= {MIN_PROFILE_RADIUS}mm, "
                            f"or remove this station and let adjacent stations connect directly."
                        ),
                        severity="error", node_id=n.id,
                        expected={"min_r_mm": MIN_PROFILE_RADIUS},
                        actual={"r_mm": r},
                    ))

        # Second pass: validate cuts against envelope
        for n in nodes:
            # A002: center bore
            if n.op == "cut_center_bore":
                dia = n.typed_params.get("diameter_mm") or n.params.get("diameter_mm", 0)
                if not is_finite(dia) or dia <= 0:
                    issues.append(ValidationIssue(stage=stage, code="a002_bore_dia",
                        message=f"center bore diameter must be > 0 and finite, got {dia}",
                        severity="error", node_id=n.id))
                elif profile_max_radius is not None:
                    bore_r = dia / 2.0
                    if bore_r >= profile_max_radius:
                        # v6.1: Geometrically impossible — bore larger than outer radius
                        issues.append(ValidationIssue(stage=stage, code="a002_bore_gt_outer",
                            message=(
                                f"center bore radius ({bore_r:.1f}mm, dia={dia:.1f}) "
                                f">= profile max radius ({profile_max_radius:.1f}mm, outer dia={profile_max_radius*2:.1f}). "
                                f"Bore is larger than the part — geometrically impossible. "
                                f"Reduce bore diameter to < {profile_max_radius*2 - 2*MARGIN:.0f}mm "
                                f"(wall thickness >= {MARGIN:.0f}mm)."
                            ),
                            severity="error", node_id=n.id))
                    elif bore_r >= profile_max_radius - MARGIN:
                        # Very thin wall — might fail boolean ops
                        wall = profile_max_radius - bore_r
                        issues.append(ValidationIssue(stage=stage, code="a002_bore_too_large",
                            message=(
                                f"center bore radius ({bore_r:.1f}mm) leaves wall thickness "
                                f"of only {wall:.1f}mm (margin={MARGIN:.0f}mm). "
                                f"Consider reducing bore or increasing outer radius."
                            ),
                            severity="error", node_id=n.id))
                center_bore_radius = dia / 2 if is_finite(dia) and dia > 0 else None

            # A003: circular hole pattern
            if n.op == "cut_circular_hole_pattern":
                count = n.typed_params.get("count") or n.params.get("count", 0)
                hole_dia = n.typed_params.get("hole_dia_mm") or n.params.get("hole_dia_mm", 0)
                pcd = n.typed_params.get("pcd_mm") or n.params.get("pcd_mm", 0)
                if not is_finite(count) or count < 3:
                    issues.append(ValidationIssue(stage=stage, code="a003_pattern_count",
                        message=f"circular hole pattern count must be >= 3 and finite, got {count}",
                        severity="error", node_id=n.id))
                if not is_finite(hole_dia) or hole_dia <= 0:
                    issues.append(ValidationIssue(stage=stage, code="a003_hole_dia",
                        message=f"hole diameter must be > 0 and finite, got {hole_dia}",
                        severity="error", node_id=n.id))
                if not is_finite(pcd) or pcd <= 0:
                    issues.append(ValidationIssue(stage=stage, code="a003_pcd",
                        message=f"PCD must be > 0 and finite, got {pcd}",
                        severity="error", node_id=n.id))
                # Envelope check: pcd/2 + hole_dia/2 < profile_max_radius - margin
                if profile_max_radius is not None and is_finite(pcd) and pcd > 0 and is_finite(hole_dia) and hole_dia > 0:
                    pcd_radius = pcd / 2
                    hole_radius = hole_dia / 2
                    outer_edge = pcd_radius + hole_radius
                    inner_edge = pcd_radius - hole_radius
                    # v6.1: Preemptively compute BOTH bounds so repair hints can detect double-bind
                    min_pcd = 2 * (center_bore_radius + hole_radius + MARGIN) if center_bore_radius is not None else None
                    max_pcd = 2 * (profile_max_radius - hole_radius - MARGIN)
                    max_bore = 2 * (inner_edge - MARGIN) if center_bore_radius is not None else None
                    # Always include both bounds in expected dict for proactive double-bind detection
                    expected_both = {}
                    if min_pcd is not None: expected_both["min_pcd_mm"] = round(min_pcd, 1)
                    expected_both["max_pcd_mm"] = round(max_pcd, 1)
                    if max_bore is not None: expected_both["max_bore_dia_mm"] = round(max_bore, 1)

                    if outer_edge >= profile_max_radius - MARGIN:
                        issues.append(ValidationIssue(stage=stage, code="hole_pattern_outside_profile",
                            message=(
                                f"Hole pattern exceeds profile: PCD/2+hole_r ({pcd_radius:.0f}+{hole_radius:.0f}"
                                f"={outer_edge:.0f}) >= profile_max_radius ({profile_max_radius:.0f}) - margin ({MARGIN:.0f}). "
                                f"Max PCD for hole_dia={hole_dia:.0f}: {max_pcd:.0f}mm. "
                                f"Or increase profile radius to > {outer_edge + MARGIN:.0f}mm."
                            ),
                            severity="error", node_id=n.id,
                            expected=expected_both,
                            actual={"outer_edge_mm": round(outer_edge, 1)}))
                    if center_bore_radius is not None and inner_edge <= center_bore_radius + MARGIN:
                        issues.append(ValidationIssue(stage=stage, code="hole_pattern_intersects_center_bore",
                            message=(
                                f"Holes overlap with center bore: PCD/2-hole_r ({pcd_radius:.0f}-{hole_radius:.0f}"
                                f"={inner_edge:.0f}) <= bore_r ({center_bore_radius:.0f}) + margin ({MARGIN:.0f}). "
                                f"Min PCD for bore_dia={center_bore_radius*2:.0f}: {min_pcd:.0f}mm. "
                                f"Or max bore_dia for PCD={pcd:.0f}: {max_bore:.0f}mm."
                            ),
                            severity="error", node_id=n.id,
                            expected=expected_both,
                            actual={"hole_inner_edge_mm": round(inner_edge, 1)}))

            # A004: annular groove
            if n.op == "cut_annular_groove":
                inner = n.typed_params.get("inner_dia_mm") or n.params.get("inner_dia_mm", 0)
                outer = n.typed_params.get("outer_dia_mm") or n.params.get("outer_dia_mm", 0)
                if not is_finite(inner) or not is_finite(outer) or inner >= outer:
                    issues.append(ValidationIssue(stage=stage, code="a004_groove_dia",
                        message=f"inner_dia_mm ({inner}) must be < outer_dia_mm ({outer}) and both finite",
                        severity="error", node_id=n.id))
                if profile_max_radius is not None and outer / 2 >= profile_max_radius - MARGIN:
                    issues.append(ValidationIssue(stage=stage, code="a004_groove_outside_profile",
                        message=f"groove outer radius ({outer/2}) >= profile max ({profile_max_radius}) - margin ({MARGIN})",
                        severity="error", node_id=n.id))

        # ── A007: 多 groove Z 区间冲突检测 ──
        # 检测多个 cut_annular_groove 的 Z 区间是否重叠。
        # 仅对指定了 z_position_mm 的 groove 进行检测（无 z_position_mm 时
        # 区间依赖 profile zmin/zmax，冲突检测复杂度高且不常见）。
        groove_intervals: list[tuple[float, float, str]] = []  # (zmin, zmax, node_id)
        for n in nodes:
            if n.op != "cut_annular_groove":
                continue
            z_pos = n.typed_params.get("z_position_mm") or n.params.get("z_position_mm")
            depth = n.typed_params.get("depth_mm") or n.params.get("depth_mm", 0)
            side = n.typed_params.get("side") or n.params.get("side", "")
            if not is_finite(z_pos) or not is_finite(depth):
                continue
            # side="front": 从 z_pos 向 +Z 切削 depth → 区间 [z_pos, z_pos+depth]
            # side="rear":  从 z_pos 向 -Z 切削 depth → 区间 [z_pos-depth, z_pos]
            if side == "front":
                zmin, zmax = z_pos, z_pos + depth
            elif side == "rear":
                zmin, zmax = z_pos - depth, z_pos
            else:
                continue
            groove_intervals.append((zmin, zmax, n.id))

        for i in range(len(groove_intervals)):
            for j in range(i + 1, len(groove_intervals)):
                zf1, zr1, nid1 = groove_intervals[i]
                zf2, zr2, nid2 = groove_intervals[j]
                if zf1 < zr2 and zf2 < zr1:  # Z 区间严格重叠
                    issues.append(ValidationIssue(
                        stage=stage, code="a007_groove_z_overlap",
                        message=(
                            f"cut_annular_groove nodes {nid1!r} (Z={zf1:.1f}→{zr1:.1f}) "
                            f"and {nid2!r} (Z={zf2:.1f}→{zr2:.1f}) have overlapping Z intervals. "
                            f"Multiple grooves cutting the same Z region will destroy each other's geometry. "
                            f"Adjust z_position_mm/depth_mm to avoid overlap."
                        ),
                        severity="error", node_id=nid1,
                    ))

        # ── A005: bore-vs-profile coplanar detection ──
        # 检测 profile 是否有内壁站点（r_mm ~= bore_radius），这种情况下 bore cut 会
        # 产生共面切割，导致 2-Solid 拓扑失败。
        if center_bore_radius is not None and profile_max_radius is not None:
            for n2 in nodes:
                if n2.op != "revolve_profile":
                    continue
                ps2 = n2.typed_params.get("profile_stations") or n2.params.get("profile_stations", [])
                for i, s in enumerate(ps2):
                    r = s.get("r_mm", 0)
                    if is_finite(r) and abs(r - center_bore_radius) < MARGIN:
                        issues.append(ValidationIssue(
                            stage=stage, code="a005_bore_profile_coplanar",
                            message=(
                                f"revolve_profile station {i} radius ({r:.1f}mm) ~= "
                                f"center bore radius ({center_bore_radius:.1f}mm). "
                                f"Bore cut will create coplanar faces → 2-Solid topology failure. "
                                f"Either remove the inner-wall station (let bore cut define the inner wall), "
                                f"or reduce station radius to < {center_bore_radius - MARGIN:.1f}mm."
                            ),
                            severity="error", node_id=n2.id,
                            expected={"station_r_mm": f"< {center_bore_radius - MARGIN:.1f}"},
                            actual={"station_r_mm": r},
                        ))

        # ── A006: revolve_profile Z 重叠检测 ──
        # 检测"区域描述"风格：多个 station 的 Z 区间重叠
        # 这是 LLM 把 bore/hub/web/rim 分区域输出的典型模式，违反 Z 单值约束
        for n in nodes:
            if n.op != "revolve_profile":
                continue
            ps = n.typed_params.get("profile_stations") or n.params.get("profile_stations", [])
            if len(ps) < 2:
                continue
            z_ranges = [(s.get("z_front_mm", 0), s.get("z_rear_mm", 0)) for s in ps]
            overlap_count = 0
            for i, (zf1, zr1) in enumerate(z_ranges):
                for j, (zf2, zr2) in enumerate(z_ranges[i+1:], i+1):
                    if zf1 < zr2 and zf2 < zr1:  # Z 区间严格重叠
                        overlap_count += 1
            if overlap_count > 0:
                issues.append(ValidationIssue(
                    stage=stage, code="a006_profile_z_overlap",
                    message=(
                        f"revolve_profile stations have {overlap_count} overlapping Z ranges. "
                        f"This indicates regional description style (bore/hub/web/rim), "
                        f"which violates the Z single-valued outer contour constraint. "
                        f"Convert to outer contour continuous segments where each Z position "
                        f"has exactly one radius."
                    ),
                    severity="error", node_id=n.id,
                ))

        # ── A010: revolve_profile hub-web-rim thickness pattern ──
        # 涡轮盘剖面应呈现 hub(厚)→web(薄)→rim(厚) 的等强度结构。
        # 均匀厚度剖面（如阶梯圆盘）不满足涡轮盘结构约束。
        for n in nodes:
            if n.op != "revolve_profile":
                continue
            ps = n.typed_params.get("profile_stations") or n.params.get("profile_stations", [])
            if len(ps) < 3:
                continue
            # 按 Z 排序，提取各段 Z 向厚度
            sorted_ps = sorted(ps, key=lambda s: float(s.get("z_front_mm", 0)))
            thicknesses = [float(s.get("z_rear_mm", 0)) - float(s.get("z_front_mm", 0)) for s in sorted_ps]
            max_t = max(thicknesses) if thicknesses else 0
            if max_t <= 0:
                continue
            # 检查是否存在中间薄段：中间某段厚度 < 最大厚度的 70%
            mid_thin = any(t < max_t * 0.7 for t in thicknesses[1:-1]) if len(thicknesses) >= 3 else False
            if not mid_thin:
                issues.append(ValidationIssue(
                    stage=stage, code="a010_hub_web_rim_thickness",
                    message=(
                        f"revolve_profile stations show uniform thickness (max={max_t:.1f}mm). "
                        f"Turbine disks typically have hub(厚)→web(薄)→rim(厚) varying thickness "
                        f"pattern. Verify the profile expresses axial thickness variation."
                    ),
                    severity="warning", node_id=n.id,
                ))

        # ── A011: rim slot neck/lobe width alternation ──
        # 枞树槽应在 width 方向呈现窄→宽→窄→宽的交替。
        # 纯折线宽度单调变化或等宽意味着不是枞树形。
        for n in nodes:
            if n.op != "cut_rim_slot_pattern":
                continue
            sp = n.typed_params.get("slot_profile") or n.params.get("slot_profile", {})
            stations = sp.get("stations", []) if isinstance(sp, dict) else []
            if len(stations) < 4:
                continue
            widths = [float(s.get("half_width_mm", 0)) for s in stations]
            # 统计宽度反向次数：w[i-1] < w[i] and w[i] > w[i+1] (lobe) or w[i-1] > w[i] and w[i] < w[i+1] (neck)
            alternations = 0
            for i in range(1, len(widths) - 1):
                if widths[i-1] < widths[i] and widths[i] > widths[i+1]:
                    alternations += 1
                elif widths[i-1] > widths[i] and widths[i] < widths[i+1]:
                    alternations += 1
            if alternations < 2:
                issues.append(ValidationIssue(
                    stage=stage, code="a011_slot_neck_lobe_alternation",
                    message=(
                        f"cut_rim_slot_pattern slot_profile has only {alternations} width "
                        f"alternation(s) across {len(stations)} stations. A proper fir-tree "
                        f"slot requires at least 2 neck/lobe alternations (narrow→wide→narrow→wide)."
                    ),
                    severity="warning", node_id=n.id,
                    expected={"min_alternations": 2},
                    actual={"alternations_found": alternations},
                ))

        # ── A012: rim slot count range ──
        # 涡轮盘榫槽通常 40-80 个。过少说明槽型过大或盘径不匹配；过多说明槽型过小。
        for n in nodes:
            if n.op != "cut_rim_slot_pattern":
                continue
            count = n.typed_params.get("count") or n.params.get("count", 0)
            count = int(count) if count else 0
            if 0 < count < 20:
                issues.append(ValidationIssue(
                    stage=stage, code="a012_slot_count_range",
                    message=(
                        f"cut_rim_slot_pattern count={count} is unusually low. "
                        f"Turbine disk rim slots typically number 40-80."
                    ),
                    severity="warning", node_id=n.id,
                    expected={"min_count": 20},
                    actual={"count": count},
                ))
            elif count > 150:
                issues.append(ValidationIssue(
                    stage=stage, code="a012_slot_count_range",
                    message=(
                        f"cut_rim_slot_pattern count={count} is unusually high. "
                        f"Turbine disk rim slots typically number 40-80."
                    ),
                    severity="warning", node_id=n.id,
                    expected={"max_count": 150},
                    actual={"count": count},
                ))

        return ValidationReport(ok=not any(i.severity == "error" for i in issues),
                               stage=stage, issues=issues)

    def run_component(self, component: CanonicalComponent, nodes: list[CanonicalNode], ctx: RuntimeContext) -> dict[str, str]:
        phase_rank = {p: i for i, p in enumerate(self.phase_order)}
        node_map = {n.id: n for n in nodes}
        in_degree = {n.id: sum(1 for i in n.inputs if i.producer_node and i.producer_node in node_map) for n in nodes}
        sorted_nodes = []; queue = [n for n in nodes if in_degree[n.id] == 0]
        while queue:
            queue.sort(key=lambda n: (phase_rank.get(n.phase, 999), n.id))
            n = queue.pop(0); sorted_nodes.append(n)
            for other in nodes:
                for inp in other.inputs:
                    if inp.producer_node == n.id:
                        in_degree[other.id] -= 1
                        if in_degree[other.id] == 0 and other not in sorted_nodes and other not in queue:
                            queue.append(other)
        if len(sorted_nodes) != len(nodes):
            unscheduled = [n.id for n in nodes if n not in sorted_nodes]
            raise RuntimeError(f"axisymmetric: unscheduled nodes: {unscheduled}")

        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation

        final_outputs = {}
        for node in sorted_nodes:
            op_spec = self.get_op_spec(node.op, node.op_version)
            try:
                executed = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
            except Exception as exc:
                if not node.required and node.degradation_policy == "may_skip_with_warning":
                    ctx.warnings.append(f"Optional {node.id!r} ({node.op}) skipped: {exc}")
                    ctx.degraded_features.append({"node_id": node.id, "op": node.op, "reason": str(exc)})
                    ctx.operation_metrics.append({"node_id": node.id, "op": node.op, "status": "degraded", "reason": str(exc)})
                    continue
                raise
            for name, hid in executed.outputs.items():
                final_outputs[name] = hid
            ctx.operation_metrics.append({"node_id": node.id, "op": node.op, "status": "ok"})
        root = next((n for n in sorted_nodes if n.id == component.root_node), sorted_nodes[-1] if sorted_nodes else None)
        if root:
            for o in root.outputs:
                try: ctx.bind_component_output(component.id, o.name, ctx.resolve_node_output(root.id, o.name))
                except KeyError: pass  # postconditions.py independently validates root outputs
        return final_outputs


AXISYMMETRIC_DIALECT = AxisymmetricDialect()
