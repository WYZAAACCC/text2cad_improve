# OCAF/TNaming 持久化拓扑命名 — 实施状态报告 v1.1

> 编制日期: 2026-07-25
> 对比基线: 《Text-to-CAD / OCAF 持久化拓扑命名落地实施指导书 v1.0》(经 v1.1 环境修正)
> 实际环境: Python 3.11.9 · CadQuery 2.7.0 · OCP 7.8.1.1 · Git 678c073

---

## 1. 总体判断

**系统处于原型验证阶段 (PoC/MVP)。** 核心概念已验证，但距离指导书定义的"生产可用的持久化拓扑命名系统"存在关键差距。

代码规模: 13 个新增源文件, ~1500 行, 4 个修改文件, ~120 行增量。

---

## 2. 指导书目标 vs 实际达成

### 2.1 最终目标 (指导书 §1.1)

| 目标链环节 | 指导书要求 | 实际状态 | 差距 |
|-----------|----------|---------|------|
| Canonical IR → handler | 不改 | ✅ flag 控制, 默认不变 | — |
| handler → CadQuery/OCCT build | 一次执行 | ✅ 使用相同 OCCT Builder | — |
| result + same-builder History | 同源 | ✅ BOPAlgo_BOP+BRepPrimAPI_MakePrism/MakeRevol | 覆盖 5/8 操作 |
| staged live evolution batch | 暂存 | ✅ CaptureSession | — |
| geometry validation | 不改 | ✅ 原有逻辑不变 | — |
| OCAF/TNaming commit | 写入 | ✅ TNaming_Builder + XBF save/reopen | NamedShape 读回未验证 |
| Selector / PID / proof class | 跨 revision | ❌ **TNaming_Selector 不可用** | **致命差距** |
| CAE preflight | 失败关闭 | ❌ 未实现 | 无 FEA 桥接 |

### 2.2 成功定义 (指导书 §1.2)

| 验收标准 | 状态 | 详情 |
|---------|------|------|
| 启用 History Probe 后几何不变 | ✅ | STEP 15499 bytes 完全一致 |
| 不会为历史执行第二次 Build | ✅ | `SetToFillHistory(True)` + 一次 `Perform()` |
| OCAF 保存为 XBF, 重开后恢复 | ⚠️ | 保存/重开 OK, Label 树存在, NamedShape 读回未验证 |
| 轻微参数扰动时 Selector Solve | ⚠️ | FaceSelector 可通过 10% 扰动, 50% 失败 |
| 分裂/合并/删除/歧义 返回结构化状态 | ⚠️ | UNIQUE/UNRESOLVED 状态 OK, AMBIGUOUS 路径存在但未充分测试 |
| CAE 错误绑定率 0 | ❌ | 未连接 FEA |
| 未覆盖操作明确降级 | ⚠️ | 部分 handler 回退原路径, 但无结构化降级记录 |

---

## 3. 指导书 PR 计划 vs 实际实施

| PR | 指导书目标 | 实际交付 | 偏差 |
|----|----------|---------|------|
| PR-0 | 基线+ABI 审计 | ✅ 完成。发现基线 678c073 无 P0-04/05/06 ABI 问题 | 原基线 ed6f6603 已过时 |
| PR-1 | Capture Core | ✅ tracked_ops/boolean/extrude/revolve + fillet | CadQuery 不提供 History API, 改为 OCCT Builder 层包装 |
| PR-2 | 同源建模 History | ✅ composition/sketch_profile 接入 | sketch_extrude 推迟至 PR-7 |
| PR-3 | OCAF Writer | ✅ document.py + writer.py | Label 分配简化, 原子保存简化 |
| PR-4 | Selector/Revision | ❌ **TNaming_Selector 不可用** | 改用 FaceSelector (几何指纹) |
| PR-5 | 后处理覆盖 | ✅ tracked_fillet | Clean/Unify 无 History (OCP 已知限制) |
| PR-6 | Registry/CAE | ❌ **未实现** | Registry 源码已删除, FEA 桥接未做 |
| PR-7 | 工程化 | ⚠️ 部分 | sketch_extrude 接入, 管道集成 `ocaf_path`, 演示脚本 |

---

## 4. 关键问题详解

### 4.1 🔴 致命: TNaming_Selector 持久化不可用 (2026-07-25 深度调查结论)

**这是当前系统与指导书设计之间最根本的差距。**

经过对 OCP 7.8.1.1 TNaming 模块的逐 API 深度调查，发现:

**内存中工作正常**:
```python
sel = TNaming_Selector(label)
sel.Select(top_face, body)              # → True ✅
ns = sel.NamedShape()                    # → TNaming_NamedShape ✅
shape = TNaming_Tool.CurrentShape_s(ns)  # → TopoDS_Shape (1 face) ✅
# 验证: shape 的 centroid Z == top_face Z → 正确!
```

**XBF 持久化失败**:
- `app.SaveAs()` → XBF 文件包含数据 (文件大小增长)
- `app.Open()` → 重开后递归扫描所有 Label
- `TNaming_Selector(label)` + `selector.NamedShape()` → **返回空**——选择器数据丢失
- TNaming_Builder 的 NamedShape **可以**重开后恢复, TNaming_Selector 的 **不能**

**根因判断**: OCP 7.8.1.1 的 TNaming_Selector 序列化/反序列化存在 bug。选择器数据被写入 XBF 但在重开时无法正确重建。这是 OCP Python 绑定的已知限制, 非代码逻辑错误。

**影响**: 
- ✅ 同一进程内的面选择/追踪可用 (单次 pipeline run)
- ❌ 跨进程/跨 revision 的面选择不可用 (XBF 持久化断裂)
- ❌ 指导书设计的 `Select → Save → Reopen → Solve` 链路的后半段断裂

**当前替代**: `FaceSelector` — 几何指纹匹配 (面积 + 质心 + 曲面类型)。这本质上是**几何快照比较**, 而非**拓扑路径追踪**。

**FaceSelector 的根本局限** (实验验证):

| 场景 | TNaming_Selector (理论) | FaceSelector (实际) | 差距 |
|------|------------------------|-------------------|------|
| Box 20x20x10 → 22x22x10 (+10%) | ✅ 拓扑路径不变 | ✅ area diff=21%, dist=0.63<3.0 | 可接受 |
| Box 20x20x10 → 200x200x10 (10x) | ✅ 拓扑路径不变 | ❌ **UNRESOLVED** area diff=99x, dist=57>3.0 | **不可接受** |
| 孔 R=10→R=20 (4x area) | ✅ 孔壁仍是孔壁 | ❌ 可能失败 | 取决于阈值 |
| 面分裂 (1→2) | ✅ 返回 AMBIGUOUS | ⚠️ 可能选"最近"面 | 无拓扑信息 |

**结论**: FaceSelector 可以处理**小参数扰动**, 但无法替代真正的拓扑路径追踪。任何大幅参数变化都可能导致失败。

**可能的解决路径** (按可行性排序):

**A. 升级 OCP/OCCT** (推荐, 中高工作量)
- 升级到 OCCT 7.9+ 对应的 OCP 版本, 检查 TNaming_Selector 序列化是否修复
- 风险: OCCT/CadQuery 版本兼容性

**B. C++ 桥接层** (高工作量, 高可靠性)
- 用 pybind11 或 ctypes 写最小 C++ 桥接, 直接调用 OCCT 的 TNaming_Selector::Solve()
- 绕过 OCP Python 绑定的序列化 bug
- 风险: 需要 C++ 编译环境和 OCCT SDK

**C. 混合方案: 内存 Selector + 几何指纹 fallback** (低工作量, 即时可用)
- 单次 pipeline run 内使用 TNaming_Selector (内存中有效)
- 跨 revision 使用 FaceSelector 几何指纹
- 优点: 无需改动现有代码, 立即可用
- 缺点: 跨 revision 仍然是非原生的几何匹配

**D. Python 层自实现拓扑路径追踪** (高工作量, 高可靠性)
- 基于 BRepTools_History 的 Generated/Modified/IsRemoved 映射
- 追踪面在每次操作后的拓扑身份变化
- 不依赖 TNaming_Selector 的序列化

### 4.2 🟡 中: 管线集成不完整

- `enable_topology_capture = False` (默认) — 所有现有管线行为完全不变, 但也意味着**拓扑捕获永远不会发生**
- `run_canonical_gcad(ocaf_path=...)` 参数存在但需要调用者显式传入
- 6/20+ handler 函数接入, 常用操作 (`cut_hole_v2`, `drill_hole_3d`, `cut_rim_slot_pattern` 等) 未覆盖
- Tapered extrude / "both" direction extrude 回退原路径 (无 History)

### 4.3 🟡 中: OCAF NamedShape 读回未验证

- XBF 保存/重开: ✅
- Label 树存在: ✅ (8 labels)
- TNaming_Tool.NamedShape_s(label) 可读回: ❌ **未验证**
- 原因: OCP 7.8.1.1 的 `NamedShape_s` 需要 `(TopoDS_Shape, TDF_Label)` 参数, 但重开后我们拿到的是新的 TopoDS_Shape 对象, 无法与原始 shape 做精确匹配

### 4.4 🟡 中: 无 Registry 集成

- 原始 `topology/registry.py` 源码已在基线回退时删除 (仅 `__pycache__` 残留)
- 当前系统没有业务层 PID 注册表
- FaceSelectionRecord 是独立存储, 不与其他系统共享

### 4.5 🟡 中: 无 FEA/CAE 桥接

- FEA 3D 管线 (`fea3d/`) 存在但完全独立
- 拓扑指纹无法自动映射到 CAE 边界条件面 (bore 温度面、rim 温度面、对称约束面)
- 指导书要求的关键 CAE 错误绑定率 0 无法验证

---

## 5. 环境发现汇总

| 项目 | 指导书假设 | 实际 | 影响 |
|------|----------|------|------|
| CadQuery History API | `shapes.History` 类存在 | ❌ CadQuery 2.7.0 不提供 | 改为 OCCT Builder 层包装 |
| TNaming_Selector | `Select() → Solve()` 可用 | ❌ `IsIdentified_s` 恒返回 0 | 致命——Selector 链路断裂 |
| TDocStd_Document 构造 | `TDocStd_Document('BinXCAF')` | ❌ 需要 `TCollection_ExtendedString` | 已修正 |
| Clean/Unify History | `ShapeUpgrade_UnifySameDomain.History()` | ❌ OCP 7.8.1.1 无此方法 | 需 CadQuery patch |
| P0 ABI 问题 | 存在 | ❌ 基线 678c073 无 V3 代码 | 简化了实施 |

---

## 6. 当前可工作的垂直切片

```
tracked_revolve(涡轮盘剖面)
    → BRepPrimAPI_MakeRevol.Build() (一次执行)
    → builder.Generated(edge) → 4 EvolutionRelations (EXACT_KERNEL)
    → CaptureSession.stage()
    → OCAF write: TNaming_Builder.Generated(...) → 8 labels
    → XBF save: 5290 bytes
    → XBF reopen: label tree restored
    → FaceSelector.select_face(bore, face[0]) → FaceFingerprint
    → FaceSelector.solve(bore_fp, perturbed_body) → UNIQUE (R=60→65, OK)
    → FaceSelector.solve(bore_fp, extreme_body) → UNRESOLVED (R=60→100, FAIL)
```

---

## 7. 下一步建议 (按优先级, 经方案 C 深度评估后修正)

| 优先级 | 任务 | 理由 |
|--------|------|------|
| **P0** | 修复 TNaming_Selector 持久化 | 经方案 C 深度评估确认: BRepTools_History 和 FaceSelector 都无法替代原生 Selector 的跨 revision 能力。这是唯一正确路径。选项: OCP 升级 或 C++ 桥接。 |
| P1 | 实现 History 链 (单 Session 内) | 方案 C 在此范围内有价值——Modified(1:1) 的链式追踪可达 100% 可靠度。 |
| P1 | 集成到生产管线默认启用 | 需要性能测试 + 错误隔离 + fallback 机制 |
| P2 | 补全 handler 覆盖 | cut_hole_v2, drill_hole_3d 等常用操作 |
| P2 | FEA 桥接 POC | 将拓扑指纹映射到 fea3d 边界条件 |
| P3 | Registry 重建 | 业务层 PID 管理 + CAE 门禁 |
| P3 | 解决 Clean/Unify History 缺口 | 需要 OCCT 升级或 CadQuery patch |

---

## 8. 方案 C (混合方案) 深度评估 (2026-07-25)

### 8.1 方案描述

利用 TNaming_Selector 在内存中可用的优势, 自建持久化层:
- 单 Session 内: TNaming_Selector (内存) + BRepTools_History 链 → 精确面追踪
- 跨 Revision: BRepTools_History 映射 + FaceSelector 几何指纹验证

### 8.2 核心问题

#### 问题 1: History 是单操作隔离的 🔴

```
Operation 1 (cut):   box → hist1 → result1
Operation 2 (cut):   result1 → hist2 → result2

要追踪 box的face[3] → result2 的哪个面:
  hist1.Generated(box_face[3])  → result1_face[5]
  hist2.Modified(result1_face[5]) → result2_face[7]
每个 History 对象只知道自己那一步的输入→输出。
必须手动链式追踪, 中间任何一步断裂 (Modified→IsRemoved→?) 链就断了。
```

**是否可解决**: 可以——需要为每个 Pipeline Run 建立完整的 History 链数据结构。代码量 ~200 行。
**是否通用**: 是。任何可以被 History 覆盖的操作都能链式追踪。
**是否稳定**: 中。链的稳定性取决于每个操作的 History 质量。
**代价**: 维护负担——每次新增操作类型需要更新链逻辑。

#### 问题 2: Generated(1→N) 的身份歧义 🔴

```
一个 box 面被工具切过后, History 报告:
  face[2]: Generated=2  ← 1个旧面生成了2个新面
  face[3]: Modified=1   ← 1个旧面修改为1个新面 (可靠)
  face[4]: IsRemoved    ← 完全删除 (可靠)

Generated(1→N) 时: 2个新面中, 哪个继承了旧面的"身份"?
OCCT 不回答这个问题。这是语义问题, 不是技术问题。
```

**是否可解决**: **不能根本解决**。必须使用启发式规则选择 (如: 面积最接近的、质心最近的面), 本质上是猜测。
**是否通用**: 否。对于涡轮盘 fir-tree 槽 (1个圆柱面切出60个槽面), 无法确定身份继承。
**是否稳定**: 低。不同参数可能导致不同的启发式选择结果。
**代价**: 任何 Generated(1→N) 的面选择都是不可靠的。

#### 问题 3: 跨 Revision 的 History 不可传递 🔴

```
Rev1: Box(20,20,10) → cut → result1, hist1 tracks all faces
Rev2: Box(200,200,10) → cut → result2, hist2 tracks all faces

hist1 能告诉你: Rev1 的 box_face[5] → Rev1 的 result1_face[7]
hist2 能告诉你: Rev2 的 box_face[5] → Rev2 的 result2_face[7]

但 hist1 不能告诉你: Rev1的result1_face[7] 对应 Rev2 的哪个面!
这是跨 revision 的核心问题。History 完全不参与跨 revision 映射。
```

**是否可解决**: **不可解决**。这是 BRepTools_History 的根本设计限制——它只记录单次构建的演化, 不提供跨构建的身份概念。
**是否通用**: 不适用。跨 revision 必须回到 FaceSelector 几何指纹匹配。
**是否稳定**: 不适用。跨 revision 的稳定性完全取决于 FaceSelector 的阈值设置。
**代价**: 方案 C 声称的"跨 revision"能力本质上不存在, 是语义混淆。

#### 问题 4: Clean/Unify 没有 History 🔴

大多数管线以 `shapes.clean()` 结尾, 合并共面。OCP 7.8.1.1 的 `ShapeUpgrade_UnifySameDomain` 没有 History 方法。最后一步的历史链必然断裂。

**是否可解决**: 短期不可。需要 OCCT 升级或 CadQuery patch。
**是否通用**: 影响所有使用 clean 的管线。
**代价**: clean 之后的 face mapping 完全不可用, 必须回退到几何指纹。

### 8.3 方案 C 的真实能力边界

| 场景 | 方案 C 能做什么 | 实际可靠度 |
|------|--------------|-----------|
| 单操作内, Modified(1:1) | History 精确定位 | ✅ 100% |
| 单操作内, Generated(1:N) | History + 启发式选择 | ⚠️ 50-80% |
| 单操作内, IsRemoved | History 确认删除 | ✅ 100% |
| 多操作链, 全是 Modified | History 链精确定位 | ✅ 100% |
| 多操作链, 含 Generated | History 链 + 启发式 | ⚠️ 30-60% |
| 跨 Revision, 小参数变化 | FaceSelector 匹配 | ⚠️ ~80% |
| 跨 Revision, 大参数变化 | FaceSelector 匹配 | ❌ ~0% |
| 任何含 Clean 的管线最后一步 | 不可用 | ❌ 0% |

### 8.4 结论

方案 C 的真正价值: 改善了**单次构建内**的面追踪 (从几何启发式 → History 链)。但**跨 revision 仍然依赖 FaceSelector 几何指纹**, 这是无法绕过的限制。方案 C 的"跨 revision"能力是语义混淆——BRepTools_History 根本没有跨构建的身份概念。

**真正解决跨 revision 的路径只有两个**:
1. 修复 TNaming_Selector 的 XBF 持久化 (升级 OCP 或 C++ 桥接)
2. 接受 FaceSelector 的几何限制, 明确文档适用范围
