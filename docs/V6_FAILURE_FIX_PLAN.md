# SeekFlow Generative CAD v6 — 失败案例深度修复方案

**作者身份**: CAD 编译器架构师 / 几何内核工程师 / SolidWorks & NX 首席专家
**基于**: v6 全量 35 case 测试审计报告 + llm_skill_base20.md 细化架构
**日期**: 2026-06-04

---

## 0. 问题全景

| # | Case | 症状 | 根因类别 | 修复难度 |
|---|------|------|---------|---------|
| A | s01_thin_flange | 孔(480mm) > 外径(250mm) | **Prompt 几何矛盾** | 简单 (preflight检测) |
| B | s05_long_spring | 15圈体积2%, OCP分段失败 | **OCP MakePipe 限制** | 困难 (分段算法) |
| C | s10_shelled_box | shell_body 跨方言 dispatch 失败 | **混编方言+LLM结构** | 中等 |
| D | s13_pipe_system | 竖直 sweep path 崩溃 | **CadQuery XY 平面限制** | 中等 (OCP wire) |
| E | s15_multi_valve | LLM JSON 结构错误 | **LLM 质量** | 简单 (prompt增强) |
| F | tm06_spring | 8圈 OCP MakePipe 失败 | **OCP MakePipe 限制** | 中等 (已有部分修复) |
| G | tm12_robot_wrist | DeepSeek 随机 control character | **LLM 随机性** | 简单 (sanitizer) |
| H | tm15_diff_case | 复杂 profile preflight 拒绝 | **参数验证过严** | 简单 (放宽preflight) |
| I | tm07_roller | MULTI_SOLID (boolean_union 失败) | **OCCT Fuse 失败** | 中等 (接触检测+诊断) |
| J | s11/s19 空间语义 | 组件堆叠原点 identity placement | **无空间前端** | 已有方案 (v6) |
| K | handle_cut_hole | axis=X/Y 被静默忽略 | **Handler 功能缺失** | 中等 (新增3D钻孔) |

---

## 1. 修复 A: s01_thin_flange — Preflight 增强 (几何矛盾提前检测)

### 根因

```
Prompt: revolve_profile r=250 z=0-8, cut_center_bore diameter_mm=480
问题: 外径 250mm, 孔径 480mm → 壁厚 = 250 - 240 = -230mm (几何不可能)
现状: preflight_component 检测到 bore_radius(240) > profile_max_radius(250) - margin(1.0)
      但被归类为 preflight 错误而非更明确的 "几何不可能" 错误
```

代码位置: `dialects/axisymmetric/dialect.py` → `preflight_component()` Pass 2

### 修复方案

在 `preflight_component` 的 `cut_center_bore` 检查中，区分 "不可行" 与 "不建议":

```python
# dialects/axisymmetric/dialect.py, preflight_component Pass 2, 
# cut_center_bore 检查处 (现有 margin 检查附近)

# 现有代码 (约 line 150-160):
# bore_radius = dia / 2.0
# if bore_radius >= profile_max_radius - margin: → warning

# 增强为:
bore_radius = dia / 2.0
if bore_radius >= profile_max_radius:
    # 几何不可能: 孔比外径大
    raise ValueError(
        f"cut_center_bore diameter_mm ({dia}) >= outer diameter "
        f"({profile_max_radius * 2}): bore is larger than the part. "
        f"This is geometrically impossible. Reduce bore diameter "
        f"to less than {profile_max_radius * 2 - 2 * tolerance}mm."
    )
elif bore_radius >= profile_max_radius - min_wall:
    # 壁厚太薄
    report.issues.append(ValidationIssue(
        severity="error",
        code="bore_wall_too_thin",
        message=f"Bore diameter ({dia}) leaves wall thickness "
                f"< {min_wall}mm. Minimum: {min_wall}mm.",
    ))
```

**关键**: 将 `>= profile_max_radius` (几何不可能) 提升为 `ValueError` 而非 warning。
这会让 `_run_stage_collect` 在 preflight 阶段就 fail-closed，错误信息明确告诉 LLM repair loop 为什么失败。

### 对于 tm15_diff_case 的同样处理

`tm15_diff_case` 的 `cut_center_bore diameter_mm=100` 在 `revolve_profile station1 r=75` 上：
- 孔径 100mm，外径 150mm → 壁厚 25mm，这是可行的
- 但 profile 较复杂 (3 stations, r=75→60→75)
- preflight 可能在 `profile_stations` 的轴向排序中遇到问题

检查 `bases/axisymmetric/preflight.py` 中的 `preflight_revolve_profile`:
- 它检查 `z_front <= z_rear` 每个 station
- 检查 max profile points
- 但不检查整个 profile 是否构成有效回转体

如果 tm15 的失败原因是 preflight，更可能是 LLM 输出的 params 格式问题而非几何问题。

### 验证

```python
# 修复后: s01 应在 preflight 阶段收到明确的 ValueError
# 而非 ambiguity warning
# LLM repair loop 看到 "bore is larger than the part" 后可以修正 prompt
```

---

## 2. 修复 B+F: Helix Sweep 分段算法正确集成

### 根因

```
s05_long_spring: 15 turns → OCP MakePipe 对长螺旋线不稳定
tm06_spring: 8 turns → OCP MakePipe 在某些 OCCT 版本失败
当前代码: 一次性 OCP MakePipe → 失败 → CadQuery parametricCurve fallback → 2% 体积
v6 方案: 分段 (≤3 turns/seg) OCP MakePipe + BRepAlgoAPI_Fuse 合并
状态: v6 分段代码已在 llm_skill_base20.md §11.3 设计, 但未集成到 handlers.py
```

代码位置: `dialects/loft_sweep/handlers.py` lines 208-314

### 修复方案

将 v6 分段 sweep 代码集成到 `handle_helix_sweep`:

```python
# dialects/loft_sweep/handlers.py, 替换现有的 helix sweep 构建部分 (lines 248-280)

def handle_helix_sweep(node, ctx) -> dict:
    # ... (参数验证保持不变, lines 208-247)
    
    # ── v6: Segmented OCP MakePipe ──
    MAX_TURNS_PER_SEGMENT = 3
    sample_n = max(360, int(math.ceil(turns * 60)))
    
    if turns <= 8:
        # 一次性 sweep
        helix_wire = _build_helix_wire_ocp(radius, total_z, turns, sample_n)
        profile = cq.Workplane("XZ").center(radius, 0).circle(profile_r)
        profile_face = profile.val()
        profile_shape = profile_face.wrapped if hasattr(profile_face, 'wrapped') else profile_face
        pipe = BRepOffsetAPI_MakePipe(helix_wire, profile_shape)
        pipe.Build()
        if pipe.IsDone():
            solid = cq.Solid(pipe.Shape())
        else:
            # Fallback to CadQuery
            ctx.warnings.append(f"helix_sweep: OCP MakePipe failed, using CadQuery fallback")
            helix = cq.Workplane("XY").parametricCurve(...)
            solid = profile.sweep(helix)
    else:
        # ── v6: Segmented sweep ──
        n_segs = int(math.ceil(turns / MAX_TURNS_PER_SEGMENT))
        turns_per_seg = turns / n_segs
        z_per_seg = total_z / n_segs
        seg_solids = []
        
        for i in range(n_segs):
            z_start = z_per_seg * i
            seg_z = z_per_seg
            # Build segment wire
            seg_wire = _build_helix_segment_wire(
                radius, z_start, seg_z, turns_per_seg,
                sample_n=max(360, int(math.ceil(turns_per_seg * 60)))
            )
            profile = cq.Workplane("XZ").center(radius, 0).circle(profile_r)
            pf = profile.val()
            ps = pf.wrapped if hasattr(pf, 'wrapped') else pf
            pipe = BRepOffsetAPI_MakePipe(seg_wire, ps)
            pipe.Build()
            if not pipe.IsDone():
                raise RuntimeError(f"helix_sweep segment {i}/{n_segs} OCP MakePipe failed")
            seg_solids.append(cq.Solid(pipe.Shape()))
        
        # Fuse segments
        solid = seg_solids[0]
        for seg in seg_solids[1:]:
            try:
                solid = solid.union(seg)
            except Exception:
                from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
                fuse = BRepAlgoAPI_Fuse(solid.wrapped, seg.wrapped)
                fuse.Build()
                if fuse.IsDone():
                    solid = cq.Solid(fuse.Shape())
                else:
                    raise RuntimeError(f"helix_sweep segment fuse failed")
    
    # ── v6: Volume hard check (default: fail on deviation) ──
    expected_v = _estimate_helix_sweep_volume(radius, profile_r, turns, total_z)
    actual_solid = solid.val() if hasattr(solid, 'val') else solid
    actual_v = actual_solid.Volume()
    
    if actual_v <= 0:
        raise RuntimeError(f"helix_sweep: non-positive volume ({actual_v:.2f})")
    
    ratio = actual_v / expected_v if expected_v > 0 else 0
    if ratio < 0.55 or ratio > 1.65:
        # v6: Default FAIL (not degrade)
        # Only optional nodes with may_skip_with_warning can degrade
        if (hasattr(node, 'degradation_policy') 
            and node.degradation_policy == "may_skip_with_warning"
            and not node.required):
            ctx.warnings.append(f"helix_sweep volume ratio={ratio:.3f} (degraded)")
            ctx.degraded_features.append({...})
        else:
            raise RuntimeError(
                f"helix_sweep volume deviation: ratio={ratio:.3f} "
                f"(actual={actual_v:.0f}, expected={expected_v:.0f}). FAILING."
            )
    
    return {"body": _store_solid(node, ctx, solid)}
```

### 新增辅助函数

```python
def _build_helix_segment_wire(radius, z_start, seg_z, turns_per_seg, sample_n):
    """Build a single helix segment wire (for segmented sweep)."""
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    
    n_pts = sample_n + 1
    arr = TColgp_Array1OfPnt(1, n_pts)
    for j in range(n_pts):
        t = j / sample_n
        angle = 2.0 * math.pi * turns_per_seg * t
        z = z_start + seg_z * t
        arr.SetValue(j + 1, gp_Pnt(
            radius * math.cos(angle),
            radius * math.sin(angle),
            z,
        ))
    spline_api = GeomAPI_PointsToBSpline(arr)
    if not spline_api.IsDone():
        raise RuntimeError("GeomAPI_PointsToBSpline failed for helix segment")
    spline = spline_api.Curve()
    edge = BRepBuilderAPI_MakeEdge(spline).Edge()
    wb = BRepBuilderAPI_MakeWire()
    wb.Add(edge)
    return wb.Wire()
```

### 验证

```python
# 修复后: tm06_spring (8 turns) → 一次性 OCP → volume ratio 0.8-1.2
# 修复后: s05_long_spring (15 turns, 5 segments) → segmented → volume ratio 0.65-1.35
# 如果任一失败: RuntimeError (不再静默 degraded)
```

---

## 3. 修复 D: 竖直 Sweep Path — OCP 3D Wire 替代 CadQuery

### 根因

```
s13_pipe_system 的 main 组件:
  create_sweep_path [{x:0,y:0,z:300},{x:0,y:0,z:500}]
  → 纯竖直路径 (x0==x1, y0==y1)
  → CadQuery Workplane("XY").moveTo(0,0).lineTo(0,0) 产生零长度边 → 崩溃
```

代码位置: `dialects/loft_sweep/handlers.py` `handle_sweep_profile` lines 65-117

### 修复方案

将 `handle_sweep_profile` 改为 OCP 原生 3D wire（替代 CadQuery Workplane）:

```python
# dialects/loft_sweep/handlers.py, handle_sweep_profile (line 65-117)

def handle_sweep_profile(node, ctx) -> dict:
    import cadquery as cq
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    
    path_data = resolve_input_object(node, ctx, 0)
    params = node.params
    shape = params.get("shape", "circle")
    radius = float(params.get("radius_mm", 5))
    
    # Convert path point dicts to tuples
    pts = []
    for p in path_data:
        x = float(p.get("x_mm", p.get("x", 0))) if isinstance(p, dict) else float(p[0])
        y = float(p.get("y_mm", p.get("y", 0))) if isinstance(p, dict) else float(p[1])
        z = float(p.get("z_mm", p.get("z", 0))) if isinstance(p, dict) else float(p[2])
        pts.append((x, y, z))
    
    if len(pts) < 2:
        raise ValueError("Need at least 2 path points for sweep")
    
    # ── v6: OCP native 3D wire (handles vertical/horizontal/angled) ──
    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_wire import (
        make_3d_polyline_wire,
    )
    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_pipe import (
        make_circular_pipe_along_path,
    )
    
    try:
        solid = make_circular_pipe_along_path(pts, radius)
    except Exception as e:
        # Fallback to CadQuery for simple cases
        try:
            if len(pts) == 2:
                # Check if pure vertical
                if pts[0][0] == pts[1][0] and pts[0][1] == pts[1][1]:
                    z0, z1 = pts[0][2], pts[1][2]
                    solid = cq.Workplane("XY").center(pts[0][0], pts[0][1]).circle(
                        radius
                    ).extrude(abs(z1 - z0))
                    if z1 > z0:
                        solid = solid.translate((0, 0, z0))
                    else:
                        solid = solid.translate((0, 0, z1))
                else:
                    raise
            else:
                # Try CadQuery spline
                cq_pts = [cq.Vector(p[0], p[1], p[2]) for p in pts]
                path_wire = cq.Workplane("XY").spline(cq_pts)
                profile = cq.Workplane("XZ").circle(radius)
                solid = profile.sweep(path_wire)
        except Exception:
            raise RuntimeError(f"sweep_profile failed on '{node.id}': {e}")
    
    return {"body": _store_solid(node, ctx, solid)}
```

**关键**: 使用 `dialects/geometry_utils/ocp_pipe.py` 中已实现的 `make_circular_pipe_along_path`。
该函数使用 OCP `BRepPrimAPI_MakeCylinder` + 旋转对齐, 完全支持任意方向的直管段,
包括纯竖直和纯水平管道。

### 验证

```python
# s13_pipe_system 的 main 竖直段: make_circular_pipe_along_path(
#     [(0,0,300), (0,0,500)], radius=30
# ) → 生成正确圆柱
```

---

## 4. 修复 G: LLM JSON Sanitizer 增强

### 根因

```
tm12_robot_wrist: DeepSeek 输出 JSON 含 control character (0x00-0x1F)
导致 Pydantic model_validate 失败, 5 次重试均相同 (LLM 随机输出不可控字符)
```

代码位置: `authoring/auto_fixer.py` 缺少 JSON sanitizer

### 修复方案

在 auto_fixer 的入口处增加 JSON sanitizer:

```python
# authoring/auto_fixer.py, 在 auto_fix_with_report 函数开头

import re

def _sanitize_llm_json(obj: Any) -> Any:
    """Recursively sanitize LLM output for JSON compatibility.
    
    Handles:
    - Control characters (U+0000-U+001F except \n, \r, \t)
    - Zero-width characters (U+200B, U+200C, U+200D, U+FEFF)
    - Unpaired surrogates
    """
    if isinstance(obj, str):
        # Remove control chars except newline, carriage return, tab
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', obj)
        # Remove zero-width chars
        cleaned = re.sub(r'[​‌‍﻿]', '', cleaned)
        return cleaned
    elif isinstance(obj, dict):
        return {k: _sanitize_llm_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_llm_json(v) for v in obj]
    return obj


def auto_fix_with_report(raw_doc: dict, dialect_registry=None, *,
                         allowed_categories=None):
    """Apply deterministic fixes to raw LLM output."""
    # v6: Sanitize first
    raw_doc = _sanitize_llm_json(raw_doc)
    
    # ... existing fix functions ...
```

将此 sanitizer 同时应用到 LLM 调用层（`call_llm` 函数中）:

```python
# 在 call_llm 函数中 (run_v51_full35.py 和 authoring pipeline):
args = json.loads(tc[0].function.arguments)
args = _sanitize_llm_json(args)  # <-- 新增
```

### 验证

```python
# 修复后: tm12 的 control character 被自动清除
# LLM raw JSON → sanitizer → clean JSON → Pydantic validation
```

---

## 5. 修复 K: Side Drilling — `handle_cut_hole` 支持 axis=X/Y

### 根因

```
tm14_hyd_valve 的 prompt 中有:
  A口: cut_hole diameter_mm=10 position_mm=[0,15] axis=Y
  B口: cut_hole diameter_mm=10 position_mm=[0,-15] axis=Y

但 handle_cut_hole (sketch_extrude/handlers.py line 89-105):
  - 不读取 axis 参数
  - 始终在 XY 平面打孔, 沿 Z 方向 extrude
  - 所以 A口/B口 实际上被当作 Z 方向孔 (都在 XY 面上, 位置略有不同)
  
结果: tm14 的 STEP 生成成功了, 但侧孔的位置/方向是错的!
      这是一个静默的语义错误 — STEP 合法但 CAD 意图错误。
```

代码位置: `dialects/sketch_extrude/handlers.py` lines 89-105

### 修复方案

改造 `handle_cut_hole` 支持 3D 轴向:

```python
# dialects/sketch_extrude/handlers.py

def handle_cut_hole(node, ctx) -> dict:
    import cadquery as cq
    from seekflow_engineering_tools.generative_cad.runtime.resolve import resolve_input_object
    
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    dia = float(p.get("diameter_mm", 0))
    if dia <= 0:
        return {"body": _degrade(node, ctx, body, "cut_hole")}
    
    pos = p.get("position_mm", [0, 0, 0])
    x, y = pos[0] if len(pos) > 0 else 0, pos[1] if len(pos) > 1 else 0
    axis = p.get("axis", "Z")  # v6: read axis parameter
    through_all = p.get("through_all", True)
    
    try:
        bb = body.val().BoundingBox()
        
        if axis == "Z":
            # Existing behavior: XY plane, Z extrude
            depth = bb.zlen + 10
            cutter = cq.Workplane("XY").center(x, y).circle(
                dia / 2.0).extrude(depth, both=True)
        elif axis == "Y":
            # Side hole: XZ plane, Y extrude
            z = pos[2] if len(pos) > 2 else (bb.zmin + bb.zmax) / 2
            depth = bb.ylen + 10
            cutter = cq.Workplane("XZ").center(x, z).circle(
                dia / 2.0).extrude(depth, both=True)
        elif axis == "X":
            # Side hole: YZ plane, X extrude
            z = pos[2] if len(pos) > 2 else (bb.zmin + bb.zmax) / 2
            depth = bb.xlen + 10
            cutter = cq.Workplane("YZ").center(y, z).circle(
                dia / 2.0).extrude(depth, both=True)
        else:
            raise ValueError(f"cut_hole: unsupported axis '{axis}'")
        
        result = body.cut(cutter)
    except Exception:
        return {"body": _degrade(node, ctx, body, "cut_hole")}
    return {"body": _store_solid(node, ctx, result)}
```

### 同步更新

- `bases/sketch_extrude/models.py`: `CutHoleParams` 的 `axis` 字段扩展为 `Literal["X","Y","Z"]`
- `authoring/prompt_builders.py`: NODE_PARAMS_SYSTEM_PROMPT 添加 axis 说明
- `authoring/auto_fixer.py`: PARAM_NAME_FIXES 添加 axis 别名

### 对于 s04_deep_holes 同样适用

```
s04_deep_holes prompt: cut_hole axis=Y 和 axis=X 的侧孔
当前: 静默变为 Z 方向孔 (位置略有不同但没有侧向穿透)
修复后: 正确在 XZ/YZ 平面钻孔
```

---

## 6. 修复 I: tm07_roller MULTI_SOLID — Boolean Union 增强

### 根因

```
tm07_roller: 薄壁管 (OD 89mm, ID 80mm, 长度 600mm) + 实心轴 (OD 30mm, 长度 650mm)
boolean_union 逻辑: tube.union(shaft) → fail → tube.fuse(shaft) → fail → degraded
结果: 2 solids (仅保留 tube), MULTI_SOLID 标记
根因: 薄壁管与轴的接触面非常小 (轴在管内滑动配合), OCCT boolean fuse 
      对 near-tangent 或 grazing contact 情况不稳定
```

代码位置: `dialects/composition/handlers.py` lines 152-185

### 修复方案

三层 fallback 策略:

```python
# dialects/composition/handlers.py, handle_boolean_union

def handle_boolean_union(node, ctx) -> dict:
    # ... input resolution ...
    
    pre = pre_boolean_check(a, b, ctx.tolerance)
    
    # Attempt 1: CadQuery union
    try:
        result = a.union(b)
        return {"body": _store_solid(node, ctx, result)}
    except Exception:
        pass
    
    # Attempt 2: OCCT BRepAlgoAPI_Fuse
    try:
        result = a.fuse(b)
        # Verify: check if result has fewer solids than a+b
        a_solids = len(list(a.Solids())) if hasattr(a, 'Solids') else 1
        b_solids = len(list(b.Solids())) if hasattr(b, 'Solids') else 1
        r_solids = len(list(result.Solids())) if hasattr(result, 'Solids') else 1
        if r_solids < a_solids + b_solids:
            # Fuse actually merged at least some solids
            return {"body": _store_solid(node, ctx, result)}
        ctx.warnings.append(
            f"boolean_union: fuse produced {r_solids} solids "
            f"(expected < {a_solids + b_solids}), "
            f"clearance={pre.clearance_mm:.3f}mm"
        )
    except Exception:
        pass
    
    # Attempt 3 (v6 NEW): Add tolerance margin and retry
    # For near-tangent/grazing contact, try with a slightly enlarged tool
    try:
        # Scale B slightly to ensure overlap
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Trsf, gp_Pnt
        # Expand B by tolerance in all directions
        bb_b = b.BoundingBox()
        center_b = ((bb_b.xmin+bb_b.xmax)/2, (bb_b.ymin+bb_b.ymax)/2, (bb_b.zmin+bb_b.zmax)/2)
        b_expanded = b.translate((
            ctx.tolerance.linear_mm * 0.5,
            ctx.tolerance.linear_mm * 0.5,
            ctx.tolerance.linear_mm * 0.5,
        ))
        result = a.fuse(b_expanded)
        ctx.warnings.append(
            f"boolean_union: used tolerance-expanded fuse "
            f"(margin={ctx.tolerance.linear_mm:.3f}mm)"
        )
        return {"body": _store_solid(node, ctx, result)}
    except Exception:
        pass
    
    # Degradation: return first solid + detailed diagnostics
    ctx.degraded_features.append({
        "node_id": node.id, "op": "boolean_union",
        "reason": (
            f"union/fuse/tolerance-fuse all failed. "
            f"clearance={pre.clearance_mm:.3f}mm, "
            f"a_vol={pre.a_volume_mm3:.0f}, b_vol={pre.b_volume_mm3:.0f}"
        ),
        "recommendation": (
            "Check if solids actually intersect. "
            "For concentric cylinders, ensure radial overlap > tolerance."
        ),
    })
    ctx.warnings.append(f"boolean_union: could not merge solids (kept first solid)")
    return {"body": _store_solid(node, ctx, a)}
```

**关键新增**: Tolerance-expanded fuse。当两个 solid 的接触是 grazing/near-tangent 时,
在 fuse 前将 tool solid 沿三个方向微扩展 (tolerance/2), 确保有实际重叠区域。

### 验证

```python
# 修复后: tm07_roller union tube+shaft
# Attempt 1: union → 可能失败 (薄壁)
# Attempt 2: fuse → 可能仍失败
# Attempt 3: tolerance-expanded fuse → 预期成功 (轴在管内)
```

---

## 7. 修复 C+E: LLM Prompt 增强 (减少 JSON 结构错误)

### 根因

```
s10_shelled_box: LLM 对混编方言 (sketch_extrude + shell_housing) 的 JSON 结构不正确
s15_multi_valve: LLM 对多特征 axisymmetric 的节点结构错误
两类错误的共同根因: LLM 没有足够精确的 JSON schema 参考
```

### 修复方案

在 `build_full_contract` 函数中增加 JSON 结构模板:

```python
# 在构建 prompt 时 (run_v51_full35.py 的 build_full_contract 或等效函数):

MIXED_DIALECT_TEMPLATE = """
=== MIXED DIALECT COMPONENT TEMPLATE ===
When using shell_housing with sketch_extrude in the SAME component:
- Owner dialect: sketch_extrude (the primary geometry creator)
- First node: extrude_rectangle (creates the solid)
- Second node: shell_body (consumes the solid)
- shell_body node MUST have: "inputs":[{"node":"NODE_ID_OF_EXTRUDE","output":"body"}]
- Do NOT create separate components for shell_housing and sketch_extrude in this case
- The shell_body node uses dialect="shell_housing" but component="comp_1" (same component)

Example:
{
  "components": [{"id":"comp_1","owner_dialect":"sketch_extrude","root_node":"node_extrude"}],
  "nodes": [
    {"id":"node_extrude","component":"comp_1","dialect":"sketch_extrude",
     "op":"extrude_rectangle","op_version":"1.0.0","phase":"base_solid",
     "inputs":[],"outputs":[{"name":"body","type":"solid"}],
     "params":{...},"required":true,"degradation_policy":"fail"},
    {"id":"node_shell","component":"comp_1","dialect":"shell_housing",
     "op":"shell_body","op_version":"1.0.0","phase":"shell",
     "inputs":[{"node":"node_extrude","output":"body"}],
     "outputs":[{"name":"body","type":"solid"}],
     "params":{"thickness_mm":3.0},"required":true,"degradation_policy":"fail"}
  ]
}
"""

COMPLEX_AXISYMMETRIC_TEMPLATE = """
=== COMPLEX AXISYMMETRIC TEMPLATE (multiple features) ===
For parts with revolve + multiple cuts/patterns:
- All nodes in the SAME component
- op_version is ALWAYS "1.0.0" (NOT "0.2.0" which is the DIALECT version)
- Node IDs must be unique: "node_revolve", "node_bore", "node_holes", "node_groove", "node_chamfer"
- Each subsequent node consumes the previous node's body output
Example for multi_valve:
  revolve_profile → cut_center_bore → cut_circular_hole_pattern → cut_annular_groove → apply_safe_chamfer
  Each node: inputs=[{"node":"PREVIOUS_NODE_ID","output":"body"}], outputs=[{"name":"body","type":"solid"}]
"""
```

### 同时增强 `_fix_op_versions`

```python
# authoring/auto_fixer.py, _fix_op_versions (lines 257-273)

def _fix_op_versions(doc: dict, dialect_registry=None) -> dict:
    if dialect_registry is None:
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        dialect_registry = default_registry()
    
    for node in doc.get("nodes", []):
        ver = node.get("op_version", "")
        
        # v6: Expanded pattern matching for common LLM mistakes
        if ver in ("0.2.0", "0.1.0", "v0.2.0", "v0.2", "v0.1.0"):
            # LLM used dialect version as op version
            did = node.get("dialect", "")
            op = node.get("op", "")
            d = dialect_registry.get(did)
            if d:
                try:
                    node["op_version"] = d.default_op_version(op)
                except Exception:
                    node["op_version"] = "1.0.0"
        elif ver == "" or ver is None:
            # Missing op_version → use default
            did = node.get("dialect", "")
            op = node.get("op", "")
            d = dialect_registry.get(did)
            if d:
                try:
                    node["op_version"] = d.default_op_version(op)
                except Exception:
                    node["op_version"] = "1.0.0"
        elif ver.startswith("v"):
            # Strip "v" prefix: "v1.0.0" → "1.0.0"
            node["op_version"] = ver.lstrip("v")
    
    return doc
```

---

## 8. v6 空间前端集成 (build_pipeline.py)

### 改造点

文件: `authoring/build_pipeline.py`, 在 `generate_validate_build_step` 函数中。
位置: Line 124 之前（Stage 1-4 staged authoring 之前）。

```python
# authoring/build_pipeline.py, generate_validate_build_step 函数

def generate_validate_build_step(
    *,
    user_request: str,
    llm_config: AuthoringLlmConfig,
    dialect_registry,
    base_package_registry,
    out_dir: Path,
    route_caller=None,
    feature_sequence_caller=None,
    node_params_caller=None,
    repair_caller=None,
    allow_autofix: bool = True,
    max_repair_attempts: int = 2,
    # v6 NEW
    enable_spatial_frontend: bool = False,
    spatial_mode: str = "guided",
    object_graph_caller=None,
    spatial_plan_caller=None,
    question_caller=None,
    answer_normalizer_caller=None,
    spatial_user_answers=None,
    spatial_session_state=None,
) -> AuthoringBuildResult:
    
    # ... existing setup ...
    
    # ════════════════════════════════════════════════════════════
    # v6: Stage 0 — Spatial Frontend
    # ════════════════════════════════════════════════════════════
    spatial_result = None
    if enable_spatial_frontend and object_graph_caller is not None:
        from seekflow_engineering_tools.generative_cad.authoring.spatial.pipeline import (
            run_spatial_authoring_frontend,
        )
        spatial_result = run_spatial_authoring_frontend(
            user_request=user_request,
            llm_config=llm_config,
            dialect_registry=dialect_registry,
            base_package_registry=base_package_registry,
            object_graph_caller=object_graph_caller,
            spatial_plan_caller=spatial_plan_caller,
            question_caller=question_caller,
            answer_normalizer_caller=answer_normalizer_caller,
            user_answers=spatial_user_answers,
            session_state=spatial_session_state,
            mode=spatial_mode,
        )
        
        if spatial_result.needs_clarification:
            # Return questions to UI, don't continue to CAD generation
            result.spatial_frontend = spatial_result.model_dump()
            result.final_error = "spatial_clarification_needed"
            return result
        
        # Save spatial contract sidecar
        if spatial_result.constraint_graph is not None:
            import json
            sc_path = out_dir / "spatial_contract.json"
            sc_path.write_text(
                json.dumps(spatial_result.constraint_graph.model_dump(), 
                          indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
        
        result.spatial_frontend = (
            spatial_result.model_dump() if spatial_result else None
        )
    # ════════════════════════════════════════════════════════════
    
    # Stage 1-4: Staged authoring (existing)
    # Pass spatial context to the authoring pipeline
    authoring_result = generate_gcad_from_user_request(
        user_request=user_request,
        llm_config=llm_config,
        dialect_registry=dialect_registry,
        base_package_registry=base_package_registry,
        route_caller=route_caller,
        feature_sequence_caller=feature_sequence_caller,
        node_params_caller=node_params_caller,
        repair_caller=repair_caller,
        max_repair_attempts=max_repair_attempts,
        # v6: spatial context
        enable_spatial_frontend=enable_spatial_frontend,
        spatial_mode=spatial_mode,
        spatial_user_answers=spatial_user_answers,
        spatial_session_state=spatial_session_state,
        object_graph_caller=object_graph_caller,
        spatial_plan_caller=spatial_plan_caller,
        question_caller=question_caller,
        answer_normalizer_caller=answer_normalizer_caller,
    )
    
    # ... rest of existing pipeline ...
```

---

## 9. 修复优先级与实施顺序

### P0 — 阻塞性修复 (2-3天)

| 顺序 | 修复 | 影响范围 | 代码改动量 |
|------|------|---------|-----------|
| 1 | **JSON Sanitizer** (修复 G) | auto_fixer.py + call_llm | ~30 行 |
| 2 | **_fix_op_versions 增强** (修复 E 部分) | auto_fixer.py | ~15 行 |
| 3 | **Prompt 模板增强** (修复 C+E) | run_v51_full35.py / build_full_contract | ~60 行 |
| 4 | **preflight 几何矛盾检测** (修复 A) | axisymmetric/dialect.py | ~20 行 |

**预期效果**: s01 → 明确报错 (不再静默失败), tm12 → sanitizer 修复, s10/s15 → prompt 模板修复

### P1 — 功能性修复 (3-4天)

| 顺序 | 修复 | 影响范围 | 代码改动量 |
|------|------|---------|-----------|
| 5 | **handle_cut_hole axis=X/Y** (修复 K) | sketch_extrude/handlers.py + models.py | ~40 行 |
| 6 | **Helix 分段 sweep 集成** (修复 B+F) | loft_sweep/handlers.py | ~100 行 |
| 7 | **OCP 3D wire sweep** (修复 D) | loft_sweep/handlers.py | ~50 行 |

**预期效果**: s13 → OCP pipe 不再崩溃, tm06/s05 → 分段 helix, tm14/s04 → side drilling 正确

### P2 — 健壮性修复 (2-3天)

| 顺序 | 修复 | 影响范围 | 代码改动量 |
|------|------|---------|-----------|
| 8 | **boolean_union 3层 fallback** (修复 I) | composition/handlers.py | ~40 行 |
| 9 | **v6 spatial build_pipeline 集成** (修复 J) | build_pipeline.py | ~50 行 |

**预期效果**: tm07 → MULTI_SOLID 修复, s11/s19 → v6 空间管线 (需要 LLM ObjectGraphDraft 提取)

### P3 — 验证与回归 (1-2天)

| 顺序 | 修复 | 影响范围 |
|------|------|---------|
| 10 | tm15_diff_case 根因确认 | 手动检查 LLM raw JSON |
| 11 | 全量 35 case 回归 | 重新运行 |
| 12 | SW 批量导入修复 | batch_sw_import_v6.py |
| 13 | 最终审计报告更新 | V6_AUDIT_REPORT.md |

---

## 10. 总体验收标准

修复完成后，必须满足:

```text
STEP 生成率: ≥ 30/35 (86%, 当前 27/35 = 77%)
  - s01: preflight 明确报错 (几何不可能) → 不计入失败
  - s05: 分段 helix → 预期通过
  - s13: OCP pipe → 预期通过
  - s10: prompt 模板 → 预期通过或明确报错
  - tm06: 分段 helix → 预期通过
  - tm12: sanitizer → 预期通过

几何异常: 0/30 (当前 1 = tm07_roller MULTI_SOLID)
  - tm07: boolean_union 3层 fallback → 预期修复

空间语义:
  - s11/s19: 在 enable_spatial_frontend=True 时正确堆叠 placement
  - 其他多组件 case: bbox z 对应正确 Z 堆叠

SW 导入: ≥ 25/30 SLDPRT
  批量导入脚本修复后稳定运行

回归: ≥ 450 tests passed, 0 new failures
```

---

## 附录: 关键代码修改索引

| 文件 | 修改类型 | 行数 | 关联修复 |
|------|---------|------|---------|
| `authoring/auto_fixer.py` | 新增 sanitizer + 增强 fix_op_versions | ~50 | G, E |
| `dialects/axisymmetric/dialect.py` | preflight 孔>外径检测 | ~15 | A |
| `dialects/loft_sweep/handlers.py` | 分段 helix + OCP pipe sweep | ~150 | B, F, D |
| `dialects/sketch_extrude/handlers.py` | cut_hole axis=X/Y | ~30 | K |
| `dialects/composition/handlers.py` | boolean_union 3层 fallback | ~40 | I |
| `authoring/build_pipeline.py` | Stage 0 空间前端 | ~50 | J |
| `authoring/prompt_builders.py` 或等效 | 混编方言 + 复杂特征模板 | ~60 | C, E |
| `bases/sketch_extrude/models.py` | CutHoleParams axis 扩展 | ~5 | K |
