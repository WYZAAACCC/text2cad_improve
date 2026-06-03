# V5 全链路测试审计报告

**测试时间**: 2026-06-03  
**测试结果**: 6/7 通过 (1 例因 auto_fixer bug 失败，已修复)  
**Pipeline**: text → DeepSeek V4 Pro (strict schema) → audited autofix → validate → canonical → CadQuery STEP → SolidWorks SLDPRT

---

## 一、测试 Case 总览

| # | Case ID | Dialect(s) | 结果 | 耗时 | LLM 尝试 | Autofix 修复 | STEP | SW |
|---|---------|-----------|------|------|----------|-------------|------|-----|
| 1 | stepped_shaft | axisymmetric | ❌ 失败 | 44s | 3 | 5 项 | - | - |
| 2 | sensor_mount_plate | sketch_extrude | ✅ 通过 | 60s | 1 | 3 项 | 629KB | 459KB |
| 3 | valve_body | axisymmetric | ✅ 通过 | 26s | 1 | 2 项 | 634KB | 506KB |
| 4 | u_bend_heat_exchanger_tube | loft_sweep | ✅ 通过 | 17s | 1 | 0 项 | 41KB | 213KB |
| 5 | pillow_block | axisymmetric+sketch_extrude+composition | ✅ 通过 | 24s | 1 | 3 项 | 49KB | 108KB |
| 6 | gearbox_cover | sketch_extrude | ✅ 通过 | 69s | 3 | 4 项 | 378KB | 287KB |
| 7 | shaft_sleeve | axisymmetric | ✅ 通过 | 23s | 1 | 2 项 | 957KB | 354KB |

---

## 二、发现的 Pipeline 错误

### 2.1 【严重】auto_fixer 错误修改 thread_class（已修复）

**文件**: `authoring/auto_fixer.py` — `_fix_param_values()`  
**问题**: `CLASS_FIXES` 映射表不区分内螺纹/外螺纹上下文，将外螺纹合法的 `"6g"` 无条件改为 `"6H"`（仅内螺纹合法）。

```python
# 旧代码（错误）
CLASS_FIXES = {"6h": "6H", "6g": "6H", "7h": "7H", "8g": "6g"}
# 对 cut_external_thread 来说 "6g" 是合法的（Literal["6g", "6h", "8g"]）
# 但被错误改为 "6H"（仅 cut_internal_thread 合法: Literal["6H", "6G", "7H"]）
```

**修复**: 按操作类型区分修复表：
```python
INTERNAL_THREAD_CLASS_FIXES = {"6h": "6H", "6g": "6H", "7h": "7H", ...}
EXTERNAL_THREAD_CLASS_FIXES = {"6h": "6h", "6g": "6g", "8g": "8g", "6H": "6g", ...}
```

**影响**: stepped_shaft 的螺纹参数验证失败，导致该 case 无法通过。

### 2.2 【中等】sketch_extrude preflight boss position 过于严格

**文件**: `dialects/sketch_extrude/dialect.py` — `preflight_component()`  
**问题**: sensor_mount_plate 的凸台位置 warning — 凸台中心 y=40, 高度 25, base 半高 50。`40+12.5+1=53.5 > 50` 触发 `se_boss_outside_base` warning。

**分析**: 这是 LLM 真实的几何放置错误（凸台太靠近边缘），但 preflight 正确地将它从 error 降为 warning（在 Phase 7 中已修改），不影响构建。

### 2.3 【轻微】gearbox_cover 首次 pocket depth == base depth

**问题**: LLM 初始输出 `cut_rectangular_pocket depth_mm=15` 而 `extrude_rectangle depth_mm=15`，pocket depth == base depth 触发 `se_pocket_deeper_than_base` error。

**分析**: 这是 LLM 理解偏差（观察窗应贯穿 == depth equal），但 preflight 正确捕获了它。LLM 在第二轮将 pocket depth 改为 15，base 改为 18 后通过。

### 2.4 LLM 常见错误模式统计

从 autofix 记录中提取的 LLM 常见错误：

| 错误类型 | 出现频率 | Autofix 规则 |
|---------|---------|-------------|
| output name: `solid` → `body` | 6/7 案例 | `fix_output_names` |
| input output 引用名不匹配 | 5/7 案例 | `fix_input_output_names` |
| phase 顺序违反 contract | 5/7 案例 | `fix_phase_ordering` |
| op_version 使用 dialect version (0.2.0) | 2/7 案例 | `fix_op_versions` |
| cross-component 使用 node ref 而非 component ref | 1/7 案例 | `fix_cross_component_refs` |
| thread_class 上下文错误 | 1/7 案例 | `fix_param_values` (有 bug) |
| 多余参数 (depth_mm on through_all bore) | 1/7 案例 | `remove_extra_params` |

**核心发现**: LLM 最常犯的错误类别是 output name / input-output 引用名的一致性。这表明我们的 prompt/contract 中对 output type→name 映射的说明不够突出。

---

## 三、零错误案例：U形换热管

### 为什么这个 case 完美？

```json
{
  "nodes": [
    {
      "id": "path_op", "op": "create_sweep_path",
      "outputs": [{"name": "curve", "type": "curve"}],
      "params": {"path_points": [{"x_mm": 0, "y_mm": 0, "z_mm": 0}, ...]}
    },
    {
      "id": "sweep_op", "op": "sweep_profile",
      "inputs": [{"node": "path_op", "output": "curve"}],
      "outputs": [{"name": "body", "type": "solid"}],
      "params": {"shape": "circle", "radius_mm": 8}
    }
  ]
}
```

**成功因素**:
1. 只有 2 个 op，关系简单
2. prompt 明确写明了 `x_mm/y_mm/z_mm`（不是 `x/y/z`）
3. contract 给了 `create_sweep_path` 和 `sweep_profile` 的显式示例
4. 单 dialect (loft_sweep)，无 cross-component 复杂性

---

## 四、生成的 STEP 几何验证

所有 6 个成功 case 均通过 `run_canonical_gcad_from_files` 的运行时后验证（TopAbs_SOLID 检查、BRepCheck、volume>0）。

| Case | STEP 大小 | 分析 |
|------|----------|------|
| sensor_mount_plate | 629KB | 复杂板件，10+ 操作 |
| valve_body | 634KB | 回转体 + 孔阵列 + 环槽 + 倒角 |
| u_bend_heat_exchanger_tube | 41KB | 单 sweep 管，几何简单 |
| pillow_block | 49KB | boolean_union 装配 |
| gearbox_cover | 378KB | 多操作板件 |
| shaft_sleeve | 957KB | 回转体 + 双法兰 + 多孔阵列 |

---

## 五、改进建议

### 5.1 Prompt 优化

1. **output name 一致性**: 在 prompt 中显式说明 "output type=solid → name=body, type=frame → name=outer_frame, type=curve → name=curve"
2. **phase ordering**: 明确写出每个 dialect 的 phase 顺序要求
3. **thread_class**: 区分内螺纹(6H/6G/7H)和外螺纹(6g/6h/8g)

### 5.2 AutoFixer 增强

1. ✅ thread_class 上下文感知（已修复）
2. 考虑添加 auto_fixer 规则: 若 `pocket depth >= base depth` 且 `centered=true`，自动将 `pocket depth` 设为 `base depth - 1`

### 5.3 Contract 增强

1. `loft_sweep` contract 应显式写出 output type→name 映射
2. `axisymmetric` contract 应在 `cut_internal_thread` / `cut_external_thread` 旁列出合法的 `thread_class` 值
