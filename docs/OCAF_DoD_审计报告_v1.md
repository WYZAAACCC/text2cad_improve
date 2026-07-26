# OCAF 原生持久化拓扑命名 — Definition of Done 审计报告

> 审计日期: 2026-07-26
> 审计依据: `Text-to-CAD_OCAF原生持久化拓扑命名_系统实施指导书_v3.0.md` §19 + §14
> 当前基线: PR-0~PR-8 全部完成，112 个测试通过

---

## 一、Definition of Done（§19）逐条审计

### 1. 正式代码不再使用已确认错误 API/模式

**判定: PASS**（有一个遗留文件需清理）

| 禁用模式 | 生产代码状态 | 备注 |
|---------|-------------|------|
| `NewChild()` | ✅ 已清除 | 全部替换为 `FindChild(TAG, True)` |
| `app.Open(path, doc)` | ✅ 已清除 | 全部替换为 `app.Retrieve(folder, name, True)` |
| `TDF_Tool.Label_s()` | ✅ 已清除 | 零引用 |
| `TCollection_ExtendedString(str)` 无第二个参数 | ✅ 已清除 | 全部使用 `ext_utf8()` |
| `FindAttribute` 用于需真实 Handle 的 API | ✅ 已清除 | 使用 `TDF_AttributeIterator` |
| `Faces()[i]` / `Edges()[i]` 作为持久身份 | ⚠️ `selectors.py` 仍有 | **遗留死代码**，无生产引用 |
| 面积/质心/法向作为权威身份 | ⚠️ `selectors.py` 仍有 | 同上，已降级为 `heuristic_candidates.py` |

**待办**: 删除或重命名 `selectors.py` 以防止未来误用。

---

### 2. 一个 lineage 可连续保存至少三个 revision

**判定: NOT IMPLEMENTED**

当前 OCAF 文档架构是单 revision 模型。`OcafDocumentSession` 创建/打开/保存单次修订，没有跨 revision 的 lineage 演进机制。

基础设施存在（`StableLabelIndex` 支持 revision number、`OcafRepository` 支持 open→modify→save），但未构建多 revision Pipeline 入口。

**差距**: 无法执行 Rev1→Rev2→Rev3 的连续修改+Solve 流程。

---

### 3. T0～T12 全部通过

见第二部分详细审计。**判定: FAIL**

- T0: PASS
- T1: FAIL（Solve 返回 AMBIGUOUS，非单面 UNIQUE）
- T2: NOT IMPLEMENTED
- T3-T8: NOT IMPLEMENTED 或 PARTIAL
- T9: PASS
- T10: PASS
- T11: PASS
- T12: NOT IMPLEMENTED

---

### 4. FACE 和 EDGE 均有跨 revision 用例

**判定: FAIL**

- FACE: 仅有 body 级 PRIMITIVE 的跨 revision 保存/恢复测试（T0 smoke）。
  面级跨 revision selection→modify→solve 未测试。
- EDGE: 无跨 revision 用例。Fillet/Chamfer 的 EDGE 级 history 捕获了真实 Shape，但未与 SelectionService 集成测试。

---

### 5. split、delete、fillet、unify、周期相似面均有明确结果

**判定: PARTIAL**

| 操作 | 底层 history | Selection 集成 | 端到端测试 |
|------|-------------|---------------|-----------|
| split (1→N) | ✅ boolean.py 产生 GENERATED relations | ❌ | ❌ |
| delete | ✅ boolean.py 产生 DELETED relations | ❌ | ❌ |
| fillet | ✅ fillet.py 产生 face 级 history | ❌ | ❌ |
| unify | ✅ unify.py 产生 history (OCP 7.8.1.1) | ❌ | ❌ |
| 周期相似面 (pattern) | ✅ pattern.py 产生 per-instance history | ❌ | ❌ |

底层 history 捕获完整（PR-5），但缺少 "创建 Selection → 执行操作 → Solve Selection → 验证状态" 的端到端测试。

---

### 6. required CAE binding 完全 fail-closed

**判定: PASS**

`CaePreflightResult.ok=False` 当 required binding 的 resolution 非 UNIQUE/SET。CAE solver 启动必须检查此标志。

---

### 7. 中文路径和独立进程验证通过

**判定: PASS**

27 个 smoke 测试覆盖：`ext_utf8()` 构造、中文路径 Save→Retrieve（子进程）、ASCII 路径。

---

### 8. save/publish 失败不破坏上一 revision

**判定: PASS**

Hardening 测试覆盖：保存失败后 official XBF 大小不变、publish 缺失 temp 抛 `AtomicPublishError`、空文件被 min_size 守卫拦截。

---

### 9. capture-off 几何回归无变化

**判定: NOT TESTED**

未执行 `topology_mode=off` vs `topology_mode=audit/enforce` 的 A/B 几何对比（STEP 体积、面数、有效性）。PR-6 确保 `off` 模式下走原始 CadQuery 路径，但无回归测试。

---

### 10. 没有 face/edge index 权威身份

**判定: PASS**（遗留文件除外）

新代码中：
- `HeuristicCandidateFinder` 接受 `TopoDS_Shape` 而非 index
- `tracked_fillet`/`tracked_chamfer` 接受 `edge_shapes: list[TopoDS_Shape]` 而非 `list[int]`
- `PersistentSelectionService.create()` 不接受 index

遗留: `selectors.py` 的 `FaceSelector` 仍接受 `face_index: int`——但无生产引用。

---

### 11. 没有自动 fingerprint 身份兜底

**判定: PASS**

`HeuristicCandidateFinder` 不返回 UNIQUE（`HeuristicStatus` 枚举无 `UNIQUE` 变体）。指纹结果必须标记 `ProofClass.HEURISTIC_CANDIDATE`。

---

### 12. 实施状态文件附完整测试证据

**判定: PASS**

`docs/OCAF_原生拓扑命名_implementation_status.md` 持续更新，记录每个 PR 的修改文件、验收项、测试命令和结果。

---

## 二、T0～T12 测试矩阵逐条审计

### T0: 基础原生持久化 → PASS ✅

| 测试项 | 覆盖 | 文件 |
|--------|------|------|
| Primitive NamedShape 跨进程 | ✅ | `test_tnaming_roundtrip.py` |
| Selection Naming 跨进程 | ✅ | 同上 |
| UTF-8 路径 | ✅ | `test_utf8_path.py` |
| Tag 100 | ✅ | `test_tag100_schema.py` |

### T1: 单 Revision 精确 Selection → FAIL ❌

**需求**: 不对称几何 → 选唯一顶面 → Save → 进程退出 → Retrieve → Solve → 断言 `ShapeType == FACE`

**现状**: `test_solve_unique_same_revision` 调用 Solve 但得到 AMBIGUOUS（整个 body 的 6 个面），而非单一顶面。根因：feature label 上只有 body 级 PRIMITIVE history，没有面级 GENERATED/MODIFIED 关系。TNaming_Selector 无法区分具体面。

**需要**: 写入面级 history（如 Boolean cut 的 GENERATED 关系）后再 Solve。

### T2: 三进程跨 Revision → NOT IMPLEMENTED ❌

Process A: Rev1 create + select + save
Process B: Retrieve Rev1 + rebuild Rev2 + Modify + Solve + save
Process C: Retrieve Rev2 + verify exact selection

**需要**: 多 revision 管线支持 + 面级 selection solve。

### T3: 1→N Split → NOT IMPLEMENTED ❌

**需要**: Boolean cut 后旧面分裂为多个面。Solve 后应返回 AMBIGUOUS（EXACT_ONE policy）或 SET（SET_ALLOWED policy）。

### T4: Delete → NOT IMPLEMENTED ❌

**需要**: Boolean cut 后面完全删除。Solve 应返回 DELETED（allow_deleted=True）或 pipeline failure（allow_deleted=False）。

### T5: N→1 / UnifySameDomain → NOT IMPLEMENTED ❌

**需要**: Unify 合并多个面后 Solve。已验证 Unify 有 History，但未与 Selection Solve 集成测试。

### T6: Extrude/Revolve construction roles → PARTIAL ⚠️

- ✅ start_cap/end_cap 存在
- ❌ "参数改变后 role identity 稳定" 未测试
- ❌ profile edge lateral face 关系未测试

### T7: 周期性相似面 → NOT IMPLEMENTED ❌

Pattern 操作已有 per-instance history，但未测试 instance identity 稳定性（打乱面枚举顺序）。

### T8: Fillet/Chamfer EDGE → NOT IMPLEMENTED ❌

- ✅ fillet/chamfer 产生面级 history
- ❌ "selection 精确恢复 EDGE" 未测试
- ❌ "半径变化仍可 Solve" 未测试

### T9: 保存失败与回滚 → PASS ✅

Hardening 测试覆盖：空/损坏文件、invalid path、official survives failure。

### T10: 路径和文件系统 → PASS ✅

覆盖：ASCII、中文、空格、长路径（~180 chars）。

### T11: CAE Gate → PASS ✅

`test_cae_binding.py` + `test_hardening.py` 覆盖：required 未通过→ok=False、非 required→ok=True+warnings。

### T12: 完整 Text-to-CAD E2E → NOT IMPLEMENTED ❌

无端到端管线测试（G-CAD IR → Rev1 几何 → 原生 selection → XBF → Rev2 参数变更 → history → solve → CAE preflight → manifest）。

---

## 三、总结: 当前状态真实评估

### 我们做到了什么

| 层级 | 完成度 | 说明 |
|------|--------|------|
| **OCAF 文档基础** | ✅ 100% | 固定 Schema、ext_utf8、Retrieve、Atomic publish |
| **Live History 捕获** | ✅ 100% | Boolean/Extrude/Revolve/Fillet/Chamfer/Mirror/Pattern/Unify 全部面级 History |
| **TNaming Writer** | ✅ 100% | PRIMITIVE→Generated(new), GENERATED→Generated(old,new), MODIFIED→Modify(old,new), DELETED→Delete(old) |
| **Selection 创建** | ✅ 100% | TNaming_Selector.Select() 创建原生 Selection |
| **CAE Binding + Preflight** | ✅ 100% | CaeBinding 模型、preflight 检查、fail-closed |
| **Pipeline 集成** | ✅ 80% | topology_mode (off/audit/enforce)、RuntimeContext 扩展 |
| **加固** | ✅ 90% | 损坏 XBF 检测、保存回滚、路径边缘情况、性能基准 |
| **跨 Revision Selection Solve** | ❌ 0% | **这是最大的差距** |

### 核心差距: Selection Solve 未打通

我们有所有的基础设施——真实 Shape 的 history、正确的 TNaming 写入、Selection 创建——但从未把它们串联成 "选择面 → 修改几何 → Solve → 找回同一面" 的流程。

**当前**: Solve 返回 AMBIGUOUS（整个 body），因为我们只写了 body 级 PRIMITIVE history，没有在 Solve 的 valid_labels 中包含面级 history。

**需要**: 将 Boolean cut 的面级 GENERATED/MODIFIED/DELETED relations 写入 OCAF，然后在 valid_labels 中包含这些 relation labels，再 Solve。

### 通过测试 ≠ 实现拓扑持久化命名

当前 112 个测试验证了各模块独立工作，但缺少将模块串联的集成测试（T1-T8, T12）。系统目前处于 "各组件就绪，但未集成验证" 的阶段。

---

## 四、达到 DoD 需要的工作

### 优先级 P0: Selection Solve 端到端（T1-T5）

1. 在单个 OCAF 文档中: PRIMITIVE body → 创建 Selection → 执行 Boolean cut（产生面级 history）→ write relations → Solve Selection → 验证 UNIQUE/DELETED/AMBIGUOUS
2. 三进程跨 Revision（T2）: 需要多 revision OCAF 管线

### 优先级 P1: 操作验证（T6-T8）

3. Construction roles 稳定性测试
4. Fillet/Chamfer EDGE selection + Solve
5. Pattern instance identity 稳定性

### 优先级 P2: 回归与 E2E（T12）

6. capture-off 几何 A/B 回归
7. 完整 Text-to-CAD E2E 管线测试

### 额外: 代码清理

8. 删除/重命名 `selectors.py`（死代码，含禁止模式）
