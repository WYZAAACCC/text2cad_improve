# v5.1 35 Case 测试失败根因分析与修复方案

## 摘要

35 case 全量测试: 27/35 STEP 成功, 25/35 SW 成功。8 个失败分为 5 类根因 + 1 类 SW 限制。

---

## 一、CadQuery helix_sweep 体积严重偏低 (2 cases: tm06_spring, s05_long_spring)

### 根因

`handle_helix_sweep` 使用 `cq.Workplane("XY").parametricCurve(...)` 创建螺旋线路径，然后 `profile.sweep(helix)` 扫掠。OCCT 内部的 `BRepOffsetAPI_MakePipeShell` 对多圈螺旋路径存在已知缺陷：

1. **参数化曲线采样后变成折线逼近** — `parametricCurve` 在内部将曲线采样为 N 个点，生成多段直线 Edge 组成的 Wire。螺旋线的曲率连续变化被离散化为直线段。
2. **MakePipeShell 对折线螺旋路径的扫掠失败** — OCCT 的扫掠算法在折线段连接处无法正确计算 profile 的法向，导致 profile 在转角处"塌陷"。
3. **结果**: 扫掠产生的 solid 只有 profile 自身的局部体积（~2-5%），而非沿整个路径的体积。bbox 的 Z 方向正确（路径确实覆盖了全部高度），但 X/Y 方向只有 profile 本身的尺寸。

### 修复方案

**方案 A (推荐): 使用 OCCT 原生 `Geom_CylindricalSurface` + `BRepOffsetAPI_MakePipe`**

绕过 CadQuery 的 `parametricCurve` + `sweep`，直接用 OCCT C++ 级别的 API：

```python
from OCP.Geom import Geom_CylindricalSurface
from OCP.GeomAPI import GeomAPI_PointsToBSpline
from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Ax1
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
from OCP.TopoDS import TopoDS_Wire

def _build_helix_wire_ocp(radius, total_z, turns, sample_n=720):
    """Build helix TopoDS_Wire using OCP native API (bypasses CadQuery sweep bugs)."""
    pts = []
    for i in range(sample_n + 1):
        t = i / sample_n
        angle = 2.0 * math.pi * turns * t
        z = total_z * t
        pts.append(gp_Pnt(radius * math.cos(angle),
                          radius * math.sin(angle),
                          z))
    # Build BSpline from points
    spline = GeomAPI_PointsToBSpline(pts).Curve()
    edge = BRepBuilderAPI_MakeEdge(spline).Edge()
    wire = BRepBuilderAPI_MakeWire()
    wire.Add(edge)
    return wire.Wire()
```

然后使用 `BRepOffsetAPI_MakePipe(wire, profile_face)` 构建扫掠体。这绕过了 CadQuery 的 Workplane/sweep 层，直接使用 OCCT 的扫掠引擎。

**方案 B (备选): 逐圈扫掠 + 布尔合并**

将多圈螺旋分解为单圈扫掠（每个单圈扫掠体积正确得多），然后用 boolean fuse 合并：

```python
segments = []
for turn_idx in range(int(turns)):
    # Build one turn of helix
    turn_helix = _build_partial_helix(radius, total_z/turns, start_z)
    segment = profile.sweep(turn_helix)
    segments.append(segment)
# Fuse all segments
result = segments[0]
for seg in segments[1:]:
    result = result.union(seg)
```

**方案 C (临时): volume 验证改为 warning + degraded**

如果短期内无法实现 A 或 B，将 volume verification 从 `raise RuntimeError` 改为 `ctx.warnings` + `degraded_ops` 标记。弹簧 case 会标记为 `PASS_DEGRADED` 而非 `FAIL`。

**建议: 优先实施方案 A。** OCP 原生 API 是确定性的，不依赖 CadQuery 的 sweep 实现质量。

---

## 二、shell_housing cross-dialect component (1 case: s10_shelled_box)

### 根因

LLM 将 `shell_body` (dialect=`shell_housing`) 放在 `owner_dialect=sketch_extrude` 的组件中。

运行时 `SketchExtrudeDialect.run_component()` 处理所有属于该组件的节点，但对 `shell_body` 调用 `self.get_op_spec("shell_body", "1.0.0")` 时抛出 KeyError — `shell_body` 不属于 `sketch_extrude` dialect。

```
KeyError: "unknown op/version: 'shell_body'/'1.0.0'"
```

### 修复方案（推荐：运行时按节点 dialect 分派）

修改 `pipeline/run.py` 中的 `_run_components()` 函数。当前逻辑是按 component 的 `owner_dialect` 一次性处理该 component 的全部节点。改为：

```python
def _run_components(canonical, ctx):
    # Group nodes by component, then by dialect within each component
    for component in canonical.components:
        if component.id == "__assembly__":
            continue
        nodes = [n for n in canonical.nodes if n.component == component.id]
        # Group by dialect
        from collections import defaultdict
        by_dialect = defaultdict(list)
        for n in nodes:
            by_dialect[n.dialect].append(n)
        # Run each dialect group separately, wiring outputs between groups
        prev_outputs = {}
        for dialect_id, dialect_nodes in by_dialect.items():
            dialect = require_dialect(dialect_id)
            # Map inputs that reference nodes from other dialects
            for n in dialect_nodes:
                for inp in n.inputs:
                    if inp.producer_node and inp.producer_node in prev_outputs:
                        # Re-wire to use the inter-dialect output
                        ...
            outputs = dialect.run_component(component, dialect_nodes, ctx)
            prev_outputs.update(outputs)
```

**更简单的临时修复**: 在 `raw_assembler.py` 中，当一个组件出现 mixed-dialect 节点时，自动将该组件中的跨 dialect 节点分离到独立组件中。`shell_body` 会被放到一个新组件（如 `main_shell__shell`），其 `owner_dialect=shell_housing`。前驱节点（`pocket_cut`）的 solid 输出通过 `__assembly__` scope 传递给新组件。

---

## 三、OCCT sweep 崩溃 (1 case: s13_pipe_system)

### 根因

多管路系统有 3 条 pipe (每条 create_sweep_path + sweep_profile) + 1 条 main pipe，然后用 boolean_union 合并。

崩溃发生在 `main_sweep`: `BRep_API: command not done`。这是 OCCT 内部的扫掠失败。

最可能的原因：前序 `union_ab` (pipe_a ∪ pipe_b) 产生了非流形边界的 solid，然后 `main_sweep` 的输入引用指向这个 union 结果（因为 LLM 将 main_sweep 的 input 连到了 union 后的 solid）。但 `sweep_profile` 期望的输入是 `curve`（路径），不是 `solid`！

检查 LLM 输出：
- pipe_a_path → pipe_a_sweep (OK: sweep consumes curve)
- pipe_b_path → pipe_b_sweep (OK)
- main_path → main_sweep (OK)
- union_ab: boolean_union(pipe_a_sweep, pipe_b_sweep) (OK)
- union_final: boolean_union(union_ab, ???) 

问题在于 `main_sweep` 的 input 被 assembler 自动接线到前一个 solid 输出，但 `sweep_profile` 需要的是 `curve` 输入！在 multi-component 场景中，`main_sweep` 在 component "main" 中，其 `create_sweep_path` 在同一个 component，但 assembler 的 scope 分离可能错误地将 main component 的 sweep_profile 连到了 assembly scope 的 solid。

### 修复方案

**根本修复**: 在 `raw_assembler.py` 的 scope 规则中，leaf component 内的 sweep_profile 只能从本 component scope 消费 curve。当前代码已经做了这个区分（非 composition op 消费本 component scope），但需要验证在 multi-component 场景下是否正确应用。

需要新增保护：`sweep_profile` 必须消费 `curve` 类型。如果本 component scope 中找不到 curve，抛出 `AssemblyError` 而不是尝试接 solid。

---

## 四、tm15 diff_case OCCT ACCESS VIOLATION (1 case)

### 根因

Build 进程以 RC=0xC0000005（ACCESS VIOLATION）崩溃。这发生在 `cut_circular_hole_pattern` 的 `polarArray` + `extrude` + `cut` 操作中。

具体原因：壳体外形是"沙漏形"（两端 r=75，中间 r=60），中心孔 dia=100 (r=50)。PCD=130 的螺栓孔 (r=65) 贯穿两端 r=75 部分，但在中间 r=60 部分，孔的 extrude cylinder 与 shell 的接触面产生退化几何（tangent 或 near-tangent contact）。OCCT 布尔引擎在这种情况下不稳定。

### 修复方案

在 `cut_circular_hole_pattern` handler 中添加防御性检查：

```python
# Before cut: verify the hole cylinders actually intersect the body
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
dist_check = BRepExtrema_DistShapeShape(body, holes)
dist_check.Perform()
if dist_check.Value() > 0.01:
    # Holes don't intersect body — skip with warning
    ctx.warnings.append(f"cut_circular_hole_pattern: holes don't intersect body")
    return {"body": _store_solid(node, ctx, body)}
```

更根本的修复：将 `polarArray` 的 `extrude` 替换为每个孔单独创建 cylinder 并用 try/except 包裹每个 cut 操作。

---

## 五、SW import timeout (2 cases: s17_3d_pipe, tm07_roller)

### 根因

- s17_3d_pipe: 792KB STEP，8 点 3D 样条路径扫掠产生的复杂 NURBS 曲面。SW 的 `LoadFile2` 对复杂 STEP 的解析时间超过 60s。
- tm07_roller: 650mm 长的托辊，STEP 仅 17KB，但 SW 的导入线程可能因大尺寸 + 单位转换卡住。

### 修复方案

1. 增加 SW import 超时时间到 120s
2. 对超大 STEP (>500KB) 使用 `LoadFile4` 异步导入
3. 添加 retry 机制（最多 3 次）

---

## 六、LLM JSON 输出含非法控制字符 (1 case: tm12_robot_wrist)

### 根因

LLM (DeepSeek) 偶尔在 JSON 输出中插入控制字符（换页符、垂直制表符等），导致 `json.loads()` 失败。这是模型输出的随机质量问题，非系统 bug。

### 修复方案

在 `call_llm()` 中添加 JSON 清理：

```python
import re
def _sanitize_llm_json(text: str) -> str:
    # Remove control characters except \n, \r, \t
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
```

---

## 七、修复优先级

| 优先级 | 修复 | 影响 case | 难度 |
|--------|------|----------|------|
| P0 | helix_sweep OCP 原生 API | tm06, s05 (2) | 高 |
| P1 | shell cross-dialect runtime 分派 | s10 (1) | 中 |
| P1 | sweep 输入类型保护 | s13 (1) | 中 |
| P2 | cut_circular_hole_pattern 防御 | tm15 (1) | 中 |
| P2 | LLM JSON 清理 | tm12 (1) | 低 |
| P3 | SW import 超时增加 | s17, tm07 (2) | 低 |

**修复后预期**: 35/35 STEP 成功 (100%), ~33/35 SW 成功 (94%)
