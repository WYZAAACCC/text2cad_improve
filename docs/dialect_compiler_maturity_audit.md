# Dialect 层编译器成熟度深度审计

**审计视角**: C 编译器内核 + SolidWorks/NX 几何内核
**审计日期**: 2026-06-05
**代码基线**: v6.3 (commit 8a1c742)

---

## 一、一句话定级

**当前 dialect 层是一个正确方向上的 L1 编译器（语法驱动、单 pass 后端），但缺少 L2（优化器）、L3（多后端抽象）、L4（增量/并行）三层能力。与工业 CAD 内核的差距不在架构方向上，而在中间表示的语义密度和后端抽象的深度上。**

---

## 二、编译器成熟度模型：当前在哪个位置

我定义一个五级编译器成熟度模型来定位：

| 级别 | 名称 | 特征 | 当前 dialect 层 | 
|------|------|------|----------------|
| L0 | 脚本生成器 | 直接拼接 API 调用字符串，无 IR | ❌ 已超越 |
| **L1** | **语法驱动编译器** | 类型化 IR、多 pass 验证、方言分发 | **✅ 当前位置** |
| L2 | 优化编译器 | 死代码消除、常量折叠、操作融合、依赖分析 | ❌ 完全缺失 |
| L3 | 多后端编译器 | IR → 平台无关优化 → 多后端（OCP/Parasolid/ACIS） | ❌ 缺失 |
| L4 | 增量/并行编译器 | 增量重建、并行 pass、JIT 编译 | ❌ 完全缺失 |

**当前在 L1，且有 4 个关键 L1 子能力尚未完成。**

---

## 三、L1 层未完成的 4 个核心能力

### 3.1 类型系统：有类型名，无类型语义

```python
# ir/values.py — 当前状态
ValueType = Literal["solid", "solid_array", "frame", "plane", "point", 
                     "curve", "profile", "sketch", "face_set", "edge_set", "component_ref"]
```

这是**名义类型系统**（nominal type system）：只要字符串匹配 `"solid"` 就通过类型检查。

编译器的类型系统应该回答这些问题，而当前系统不能：

| 问题 | C 编译器等价 | 当前 dialect | 
|------|------------|-------------|
| 这个 solid 的 topology 是什么？| `sizeof(struct)` | 无法表达 |
| 这个 profile 是开放还是闭合的？| `const` vs `mut` | 无法表达 |
| face_set 引用的是哪个面？| 指针类型 | `face_set` 无名引用 |
| curve 是参考线还是构造线？| `volatile` 语义 | 无区分 |
| solid_array 中每个 solid 是否独立？ | 数组类型 | `solid_array` 不携带元素类型 |

**缺失的类型**:
- `face_ref(target_component, face_name)` — 类型化面引用
- `edge_ref(target_component, edge_set)` — 类型化边引用  
- `bbox_dim(source_component, axis)` — bbox 尺寸符号引用
- `angle(axis_a, axis_b)` — 角度类型
- `distance(point_a, face_b)` — 距离类型
- `closed_profile` vs `open_profile` — profile 子类型

**为什么 `cut_hole_v2` 必须存在**：不是因为 V1 设计错了，而是因为 V1 的 IR 只能用 `position_mm: [x,y]` 表达位置，类型系统无法表达 `face.TOP.center + (u, v)` 这个语义。V2 把语义从字符串提升到了类型层面，但方式是**为每种语义组合新建一个 op**，而不是**增强类型系统**。正确的做法是：

```python
# 不是这样（op 膨胀）:
cut_hole_v2(target_face="top", center_uv=(20,30))
drill_hole_3d(origin=(0,0,0), direction=(0,1,0))
hole_pattern_linear_v2(target_face="front", ...)

# 而是这样（类型系统增强）:
hole_placement = FacePlacement(face=FaceRef("TOP"), origin=FaceOrigin.CENTER, uv=(20,30))
cut_hole(diameter=10, placement=hole_placement, through=ThroughAll())
# 同一种 op，不同类型的 placement 推导出不同的 backend 策略
```

### 3.2 控制流：零。不是"不够"，是"没有"

查看整个 IR 系统：没有 `if`、没有 `loop`、没有 `match`、没有 `switch`。

```python
# ir/raw.py — RawNode 的全部控制流语义
required: bool = True                        # 唯一的"控制流"
degradation_policy: Literal["fail", "may_skip_with_warning"] = "fail"  # 唯一的"分支"
```

这意味着：
- **无法表达**"如果孔和外缘重叠，则减少孔直径"
- **无法表达**"对每个法兰面重复相同的螺栓孔模式"
- **无法表达**"根据壁厚选择不同的 shell 策略"

`degradation_policy` 本质是一个单比特的 `Option<T>`：要么执行要么跳过。这不是控制流，这是异常模型的最小实现。

C 编译器的 IR（LLVM IR/GIMPLE）有基本块、分支、phi 节点。CAD 编译器需要的控制流不同但同样重要：
- `for_each_face(name_pattern)` — 面集迭代
- `if_intersects(solid_a, solid_b)` — 几何条件
- `parametric_instance(params_range)` — 参数化实例化
- `select_strategy(fallback_chain)` — 策略选择

### 3.3 符号执行：preflight 是唯一的符号执行，但它是孤立的

```python
# dialects/axisymmetric/dialect.py — preflight_component 中的 envelope tracking
profile_max_radius: float | None = None  # 第一遍收集
for n in nodes:                          # 第二遍验证
    if bore_r >= profile_max_radius - MARGIN:  # 符号比较
        issues.append(...)
```

这是正确的方向——**在不执行几何操作的情况下，通过参数分析判断可行性**。这本质上是编译器的**静态分析 pass**。

但它有严重局限：

1. **每个 dialect 各自实现**：`axisymmetric.preflight_component()` 和 `sketch_extrude.preflight_component()` 是两套完全独立的代码，不可复用
2. **只能分析单个 dialect**：无法跨 dialect 做符号执行（如 sketch_extrude 的基座 + axisymmetric 的轴承座之间的干涉检查）
3. **依赖硬编码的 envelope 变量名**：`profile_max_radius`、`base_width` 等是手动命名的，新增 op 需要手动扩展
4. **没有通用的符号值框架**：

正确的做法是提供一个**符号维度（Symbolic Dimension）**框架：

```python
# 这个框架不存在，但应该有：
@dataclass
class SymbolicDimension:
    """符号维度 — 在运行时之前不需要具体数值"""
    component: str
    axis: AxisName
    edge: Literal["min", "max", "center"]
    
# preflight 不再手动追踪 profile_max_radius
# 而是对所有 op 做符号传播：
# revolve_profile(r=50, ...) → components.c1.radius_max = 50
# cut_center_bore(d=80)      → components.c1.bore_radius = 40
# cut_circular_hole(pcd=160, d=12) → hole_outer_edge = 80 + 6 = 86 > 50 - 1 → CONFLICT
```

### 3.4 变量解析：只能引用直接产物，不能引用派生值

```python
# ir/canonical.py
class CanonicalValueRef(BaseModel):
    producer_node: str | None       # 只能引用完整节点
    producer_component: str | None  # 或完整组件
    output: str                     # 引用节点的输出
    resolved_type: ValueType        # 解析后的类型
```

这只能表达**数据流图**（dataflow graph），不能表达**属性引用**。

在工业 CAD 编译器中，操作需要引用上游几何体的**属性**，而不只是上游几何体本身：

```python
# 当前无法表达的引用：
# "在 revolve_profile 创建的外圆柱面上钻孔"
#  → 需要引用 components.c1.body.faces.cylindrical
# 
# "孔的 PCD 等于法兰外径 - 2*边距"
#  → 需要引用 components.c1.radius_max - 2 * margin
#
# "轴的键槽深度 = 轴径 * 0.15"
#  → 需要引用 components.shaft.radius * 0.15
```

**这个缺失是整个系统最根本的设计限制**。因为 IR 无法表达属性引用，所以：
- 所有尺寸必须在 LLM 阶段确定（LLM 必须猜出具体数值）
- preflight 只能用硬编码的 envelope 手动追踪
- ConstraintResolver 只能做位置求解，不能做尺寸求解
- 无法实现参数化设计

---

## 四、验证层的结构性问题

### 4.1 13 个 pass 的依赖关系是隐式的

```python
RAW_STAGES = [
    ("structure", ...),       # 依赖：无
    ("root_terminal", ...),   # 依赖：components + nodes 已解析
    ("registry", ...),        # 依赖：dialect 名已知
    ("params", ...),          # 依赖：registry 通过（需要 op_spec）
    ("ownership", ...),       # 依赖：node.component 存在
    ("graph", ...),           # 依赖：node refs 已建立
    ("typecheck", ...),       # 依赖：graph 通过（需要 producer type）
    ("phase", ...),           # 依赖：registry 通过（需要 phase_order）
    ("composition", ...),     # 依赖：components 已解析
    ("hole_semantics", ...),  # 依赖：params 类型已知
    ("safety", ...),          # 依赖：无
]
```

每个 pass 依赖前序 pass 的结果，但这个依赖是**隐式的**（通过执行顺序保证），没有显式声明。如果插入新 pass，容易打乱顺序。

### 4.2 验证是 fail-fast，不是 error-collection

```python
if not report.ok:
    return False, stage_name, reports  # 遇到第一个错误就停止
```

这是一个正确但初级的设计。成熟编译器应该收集所有错误再报告，让 LLM repair 一次看到全部问题。类比 C 编译器：`-Werror -Wall` 收集所有 warning 后才 fail，而不是第一个 warning 就停止。

### 4.3 类型检查是 shallow 的

```python
# typecheck.py line 70: 只检查类型名字符串
elif actual != expected:
    issues.append(...)
```

它检查 `"solid" == "solid"`，但不检查：
- 这个 solid 是否 closed
- 这个 solid 是否 manifold
- 这个 solid 的 bbox 是否合理
- 这个 solid 是否与上游 solid 有几何连续性

这些应该在**语义类型检查**（dependent type check）层面做，而不是简单的 nominal check。

---

## 五、后端代码生成的问题

### 5.1 每个 handler 是独立编译单元，无法共享

当前每个 handler 函数直接调用 `cadquery.Workplane("XY").circle(d).extrude(l)`。这意味着：
- 无法做**公共子表达式消除**（CSE）——两个 handler 各自创建相同的 Workplane
- 无法做**操作融合**——300 个孔的 batch_cut 是手动补丁，不是编译器自动做的
- 无法做**指令调度**——布尔操作的顺序是手动的，没有最优顺序分析

### 5.2 几何验证在 handler 内部，不在编译器层

```python
# executor.py line 73-74
if any(e in ("creates_solid", "modifies_solid") for e in op_spec.effects):
    _validate_geometry(node=node, result=result, ctx=ctx)
```

这个 `_validate_geometry` 调用在每个 handler 之后执行，但它的结果只是 `warnings.append()`。几何错误不阻止后续执行。这是正确的（因为 OCCT 可能在后续布尔中修复问题），但缺少一个**累积的几何健康分数**——如果 5 个连续操作都产生 BRepCheck 错误，应该在某个阈值后 fail。

---

## 六、与工业 CAD 内核的具体差距

| 能力 | Parasolid | ACIS | OCCT (当前后端) | 当前 dialect 层 |
|------|-----------|------|-----------------|----------------|
| 几何内核 | ✅ 自研 | ✅ 自研 | ✅ OCP 绑定 | ⚠️ 通过 cadquery 间接调用 |
| 特征树 | ✅ 完整 | ✅ 完整 | ⚠️ BRepBuilderAPI | ❌ 无（handler 直接产 BRep） |
| 参数化 | ✅ 完整 | ✅ 完整 | ⚠️ 有限 | ❌ 无（所有尺寸必须确定） |
| 约束求解 | ✅ 3D DCM | ✅ 3D DCM | ⚠️ 有限 | ⚠️ ConstraintResolver 仅 5 规则 |
| 拓扑命名 | ✅ 持久化 | ✅ 持久化 | ❌ 无 | ❌ 无 |
| 增量更新 | ✅ | ✅ | ❌ | ❌ OperationCache 仅缓存 |
| 多实体管理 | ✅ Body/Part | ✅ Body/Part | ✅ Compound | ⚠️ 隐式（最后一个 solid） |
| 错误恢复 | ✅ rollback | ✅ rollback | ❌ | ⚠️ degrade or fail |

最关键的差距是**特征树**和**拓扑命名**。当前 dialect 层没有特征树——每个 handler 的输出是一个裸 `TopoDS_Shape`。如果后续操作失败，无法回滚到前一个特征，因为特征已经丢失了。

---

## 七、最应该补充的 5 个功能

### 7.1 符号尺寸框架（Symbolic Dimension Framework）

解决 IR 无法表达属性引用的问题。新增：
- `ir/symbolic.py`: `SymbolicDimension`, `DimensionExpr`, `FaceRef`, `EdgeRef`
- 让 `revolve_profile` 自动注册 `component.radius_max`, `component.z_extent`
- 让后续 op 的 params 可以引用这些符号值
- Solver 在运行时用实际 bbox 测量值替换符号值

### 7.2 中间优化 Pass（Mid-Level Optimizer）

在 canonicalize 之后、execute 之前插入优化 pass：
- `DeadNodeElimination`: 移除不产生被消费的 solid 的可选节点
- `HolePatternFusion`: 相邻的同参数孔 → batch cut
- `BooleanOrderOptimizer`: 分析 boolean 操作的最优顺序
- `ConstantPropagation`: 已知参数的代数简化

### 7.3 结构化的错误恢复（Structured Error Recovery）

替换当前的 try/except/degrade 为：
- `RecoveryStrategy` 枚举（retry_with_reduced_params, skip_and_warn, fail_immediate, try_alternate_op）
- 每个 OperationSpec 声明 `recovery_strategies: list[RecoveryStrategy]`
- 编译器自动尝试恢复策略链

### 7.4 类型化的面/边引用系统

```python
# 新增类型
FaceRef = Annotated[str, "face_ref"]  # 格式: "component_id.face_name"
EdgeRef = Annotated[str, "edge_ref"]

# 面选择器
class FaceSelector(BaseModel):
    component: str
    face: Literal["top", "bottom", "front", "back", "left", "right", "cylindrical"]
    origin: Literal["center", "corner", "datum"]
```

这样 `cut_hole` 的 placement 就可以是类型化的 `FaceSelector` 而不是原始坐标。

### 7.5 增量重建（Incremental Rebuild）

当前 `OperationCache` 只做最简单的节点级缓存。需要：
- 在 canonicalize 之后计算节点依赖图的哈希
- 变更检测：比较新旧 IR 的差异子树
- 只重建受影响的节点（及其下游）
- 这对 LLM repair loop 特别有用（repair 通常只改 1-2 个节点）

---

## 八、结论

**当前 dialect 层不是"不成熟"——它是"第一阶段完成，第二阶段空白"。**

它的架构方向（类型化 IR + 多 pass 验证 + 方言分发 + 治理约束）是正确的。它已经是一个能工作的 L1 编译器，成功地将 LLM 输出从"不可验证的自然语言"降维到"可验证的结构化 IR"。

但它缺少编译器理论中最重要的中间层——**优化器和符号分析器**。这导致：
1. IR 只能表达"做什么"（what），不能表达"为什么"（why）和"依赖什么"（depends on what）
2. LLM 承担了本应由编译器承担的尺寸推导和冲突检测
3. 每个优化（batch_cut, repair_hints）都需要手动实现，而非编译器自动推导
4. 新增 geometry 能力（如 fillet）需要同时修改 5 个文件，没有统一的扩展点

**最关键的一句话：当前 dialect 是一个将 LLM 输出翻译为 CadQuery API 调用的 translator，而不是一个理解几何语义的 compiler。升级为真正的 CAD compiler 需要的是 IR 的语义深度，而不是更多的 op。**
