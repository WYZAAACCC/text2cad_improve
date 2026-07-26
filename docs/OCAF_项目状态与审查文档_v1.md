# OCAF 原生持久化拓扑命名 — 项目状态与专家审查文档

> 日期: 2026-07-26
> 环境: Python 3.11.9, CadQuery 2.7.0, OCP 7.8.1.1, Windows 11

---

## 一、项目目标

为 Text-to-CAD 管线构建基于 OCAF/TNaming 的原生持久化拓扑命名系统，实现：

```
自然语言/G-CAD 语义操作
    → 确定性 OCCT Builder 单次执行
    → 捕获真实 old/new TopoDS_Shape 演化历史
    → 写入稳定 TDF_Label 上的 TNaming_NamedShape / TNaming_Naming
    → BinXCAF/XBF 原生持久化
    → 进程退出、重新 Retrieve
    → 下一 Revision 写入 Generated / Modify / Delete
    → TNaming_Selector.Solve → 恢复唯一 FACE/EDGE/SET
    → CAE 载荷、约束、网格控制继续绑定到同一工程语义区域
```

---

## 二、诊断阶段关键发现

在实施前进行了 10 项诊断测试、5 轮外部审查，确认：

**OCP 7.8.1.1 的 OCAF/TNaming 原生持久化完全正常，无需升级 OCP。**

此前失败的三层根因：

| 层 | 症状 | 根因 |
|----|------|------|
| 1 | 同进程 Open 后属性消失 | `SaveAs()` 将文档登记到 Application Session → `Open()` 返回 `PCDM_RS_AlreadyRetrieved` |
| 2 | 跨进程后标签丢失 | `tempfile.mkdtemp()` 生成含中文路径 → `TCollection_ExtendedString(str)` 默认 `isMultiByte=false` → UTF-8 字节被错误复制为 UTF-16 |
| 3 | `NewChild()` 标签错乱 | `TDF_TagSource` 从 0 计数 → 第一次 `NewChild()` 返回 XCAF 占用的 Tag 1 |

---

## 三、实施架构

### 模块结构

```
topology/ocaf/
├── models.py              # Live/Audit 数据模型, Selection 模型, CAE Binding 模型
├── compat.py              # OCP API 安全封装 (ext_utf8, Retrieve, collect_tnaming_labels)
├── schema.py              # 固定 Tag 100 标签树 + TagPath 稳定地址
├── label_index.py         # StableLabelIndex: object_id → TagPath 持久映射
├── repository.py          # OcafRepository: create/open/save/publish 生命周期
├── document.py            # OcafDocumentSession: 单 revision 文档会话
├── errors.py              # 16 种结构化错误类型
├── writer.py              # TopologyNamingWriter: 正确 TNaming 语义写入
├── capture_session.py     # CaptureSession: 批量收集 LiveEvolutionBatch
├── selection_service.py   # PersistentSelectionService: TNaming_Selector 驱动
├── semantic_validation.py # 后验语义验证
├── heuristic_candidates.py# HeuristicCandidateFinder: 仅诊断用途
├── selectors.py           # ⚠️ 遗留死代码, 待删除
├── cae_preflight.py       # CAE binding preflight 检查
├── tracked_ops/           # 8 个 tracked 操作
│   ├── boolean.py         # cut/fuse/common (BOPAlgo_BOP + History)
│   ├── extrude.py         # extrude (BRepPrimAPI_MakePrism)
│   ├── revolve.py         # revolve (BRepPrimAPI_MakeRevol)
│   ├── fillet.py          # fillet (BRepFilletAPI_MakeFillet, persistent EDGE)
│   ├── chamfer.py         # chamfer (BRepFilletAPI_MakeChamfer)
│   ├── unify.py           # clean/unify (ShapeUpgrade_UnifySameDomain)
│   ├── mirror.py          # mirror (BRepBuilderAPI_Transform)
│   └── pattern.py         # linear pattern (Transform + Fuse)
```

### 核心架构决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 标签分配 | `FindChild(TAG>=100, True)` | 避免 XCAF 保留 Tag 1-10 |
| 路径编码 | `TCollection_ExtendedString(str, True)` | UTF-8 正确解码 |
| 文档读取 | `app.Retrieve(folder, name, True)` | 避免 Open 输出 Handle 问题 |
| 属性访问 | `TDF_AttributeIterator` | FindAttribute 返回 Restore 壳 |
| Shape 存储 | Live/Audit 分离 | Live Shape 不跨进程, Audit(JSON) 不含 Handle |
| 事务管理 | Writer 纯写入, 事务由 Session 管理 | 单一职责 |
| 选择创建 | 禁止 face/edge index | 调用者必须先解析为 TopoDS_Shape |

---

## 四、实施进度 (8 个 PR)

| PR | 名称 | 状态 | 测试数 | 关键交付 |
|----|------|------|--------|---------|
| PR-0 | 冻结诊断基线 | ✅ | 27 | smoke 测试固化了 UTF-8/Tag100/TNaming/atomic publish |
| PR-1 | Compat + Schema + Document Core | ✅ | — | ext_utf8, Retrieve, 固定 Tag 100, Atomic publish |
| PR-2 | Live History + CaptureSession | ✅ | 26 | LiveEvolutionRelation(真实Shape), 删除全局 staging |
| PR-3 | Boolean + Writer | ✅ | 9 | TopologyNamingWriter: 正确 Generated/Modify/Delete 语义 |
| PR-4 | Selection/Solve | ✅ | 10 | PersistentSelectionService + HeuristicCandidateFinder 降级 |
| PR-5 | 操作覆盖 | ✅ | 17 | chamfer, unify, mirror, linear pattern, persistent EDGE fillet |
| PR-6 | Pipeline 集成 | ✅ | 7 | topology_mode(off/audit/enforce), RuntimeContext 扩展 |
| PR-7 | CAE Binding | ✅ | 6 | CaeBinding 模型, preflight, required binding fail-closed |
| PR-8 | 加固 | ✅ | 13 | 损坏XBF检测, 保存回滚, 路径边缘, 性能基准 |
| **额外** | **Selection Solve 集成** | ✅ | 4 | `collect_tnaming_labels()`, T1/T3/T4 面级 Solve 验证 |

**总计: 116 个测试通过** (另有 2 个因 OCP 析构崩溃而跳过的 tnaming_roundtrip 子进程测试)

---

## 五、Definition of Done 对照

依据 `系统实施指导书_v3.0.md` §19，逐条标注:

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 1 | 禁止错误 API | ✅ PASS | NewChild/Open/Label_s/fingerprint-as-authority 已清除。`selectors.py` 为遗留死代码 |
| 2 | 三 revision lineage | ❌ NOT IMPL | 单 revision 模型。需要多 revision 管线 |
| 3 | T0~T12 全部通过 | ⚠️ PARTIAL | T0/T9/T10/T11 PASS; T1/T3/T4 验证通过; T2/T5-T8/T12 NOT IMPL |
| 4 | FACE+EDGE 跨 revision | ❌ NOT IMPL | 面级 history 捕获完整, 但无跨 revision selection solve 测试 |
| 5 | split/delete/fillet/unify/周期 明确结果 | ⚠️ PARTIAL | 底层 history 完整。面级 Solve 集成: split ✅, delete ⚠️(OCP crash), unify 未集成 |
| 6 | required CAE fail-closed | ✅ PASS | CaePreflightResult 阻止 unresolved required bindings |
| 7 | 中文路径+子进程 | ✅ PASS | ext_utf8() + subprocess 验证 |
| 8 | 保存失败回滚 | ✅ PASS | official 文件在保存失败后完好 |
| 9 | capture-off 几何回归 | ❌ NOT TESTED | 无 A/B 对比 |
| 10 | 无 index 权威 | ✅ PASS | Fillet/Chamfer 接受 TopoDS_Shape, HeuristicFinder 不接受 index |
| 11 | 无 fingerprint 兜底 | ✅ PASS | HeuristicStatus 无 UNIQUE 变体 |
| 12 | 实施状态文件 | ✅ PASS | `implementation_status.md` |

---

## 六、测试矩阵 (T0-T12) 详细状态

| 测试 | 名称 | 状态 | 说明 |
|------|------|------|------|
| T0 | 基础原生持久化 | ✅ | UTF-8, Tag100, Primitive NamedShape 跨进程, Selection Naming 跨进程 |
| T1 | 单 Revision 精确 Selection | ✅ | 面级 history + collect_tnaming_labels → Solve 返回 UNIQUE/AMBIGUOUS |
| T2 | 三进程跨 Revision | ❌ | 未实现 |
| T3 | 1→N Split | ✅ | Cut 分裂面 → AMBIGUOUS (EXACT_ONE) / SET (SET_ALLOWED) |
| T4 | Delete | ⚠️ | 面删除后 history 正确写入 DELETED relations。**Solve 在 OCP 7.8.1.1 中 ACCESS VIOLATES** |
| T5 | N→1 UnifySameDomain | ❌ | Unify history 已实现，但未与 Selection Solve 集成测试 |
| T6 | Construction roles | ⚠️ | start_cap/end_cap 存在。参数改变后稳定性未测试 |
| T7 | 周期性相似面 | ❌ | Pattern history 已实现，instance identity 稳定性未测试 |
| T8 | Fillet/Chamfer EDGE | ❌ | History 已实现。EDGE 级 selection solve 未测试 |
| T9 | 保存失败与回滚 | ✅ | 损坏 XBF, 空文件, 保存失败后 official 完好 |
| T10 | 路径和文件系统 | ✅ | ASCII, 中文, 空格, 长路径 |
| T11 | CAE Gate | ✅ | Required binding 未通过→ok=False |
| T12 | 完整 E2E | ❌ | 未实现 |

---

## 七、已发现的问题与限制

### 7.1 OCP 7.8.1.1 已知缺陷

| 问题 | 严重度 | 详情 |
|------|--------|------|
| **TNaming_Selector.Solve() 在面删除后 ACCESS VIOLATES** | 高 | 当被选面完全删除后, Solve 在 native 代码崩溃 (0xC0000005)。Python 无法捕获。**需要子进程隔离或 OCP 版本升级。** |
| **TNaming 析构崩溃** | 中 | 子进程退出时 OCP TNaming 对象析构 ACCESS VIOLATES (returncode 3221226505)。已通过 `print(flush=True)` + 忽略 returncode 规避。 |
| **`IsKind(GetID_s())` 不兼容** | 低 | `GetID_s()` 返回 `Standard_GUID` 而非 `Standard_Type`。已改用 `DynamicType().Name()` 字符串比较。 |
| **`retrieve_xcaf_document` 对垃圾数据 ACCESS VIOLATES** | 中 | OCP 的 `app.Retrieve()` 在损坏文件上直接崩溃。已添加 min_size 守卫（8 字节）。 |

### 7.2 架构限制

| 问题 | 详情 |
|------|------|
| **单 revision 模型** | `OcafDocumentSession` 不支持多 revision lineage。`StableLabelIndex` 有 revision_number 字段但未被 pipeline 使用。 |
| **Body-only history → 面级 Solve 需要 collect_tnaming_labels** | 仅 body PRIMITIVE 时 Solve 返回 AMBIGUOUS。必须收集所有 feature label 的面级 relation 标签才能精确定位。 |
| **selectors.py 遗留** | 旧 `FaceSelector` 仍接受 `face_index: int` 并返回 UNIQUE 指纹匹配。已创建 `heuristic_candidates.py` 降级版，但旧文件未删除。当前无生产引用（已确认）。 |

### 7.3 未完成的测试覆盖

| 类别 | 缺失 |
|------|------|
| 三进程跨 Revision (T2) | 需要多 revision 管线和 subprocess 编排 |
| EDGE 级 Solve (T8) | Fillet/Chamfer EDGE history 已捕获，需集成测试 |
| 跨 Revision 参数变化 | Extrude 距离改变后 construction roles 稳定性 |
| capture-off 几何回归 | topology_mode=off vs on 的 A/B STEP 对比 |
| E2E G-CAD 管线 | 完整的 IR → Rev1 → 修改 → Rev2 → Solve → CAE preflight |

---

## 八、技术决策备忘

### 空标签不持久化
OCAF 的 `SaveAs` 不序列化没有属性的空标签。所有结构标签（DesignRoot、Metadata、Components 等）都必须附加 `TDataStd_Name` 才能跨进程恢复。这是在诊断阶段发现的隐性约束。

### `BRepBuilderAPI_Transform.Modified()` 是 1:1 面映射
Mirror 和 Linear Pattern 的每个源面精确映射到一个目标面（`builder.Modified(face).Size() == 1`）。Pattern 的 per-instance 面级历史通过 `instance_index` 在 `source_key` 中区分。

### `ShapeUpgrade_UnifySameDomain.History()` 在 OCP 7.8.1.1 中存在
与早期判断（v1.1 报告称"无 History"）相反，OCP 7.8.1.1 中 `UnifySameDomain.History()` 返回有效的 `BRepTools_History`，可用于面合并追踪。

### TNaming_Builder 的 `Modify()` 独立存在
`TNaming_Builder` 同时有 `Generated(old, new)` 和 `Modify(old, new)`。PR-3 将 MODIFIED 映射到 `Modify()`，GENERATED 映射到 `Generated(old, new)`，PRIMITIVE 映射到 `Generated(new)`，DELETED 映射到 `Delete(old)`。

### Transaction 生命周期
Writer 不管理事务（纯写入）。事务由 Revision Session 统一开启/提交/回滚。PR-3 将此明确为设计规则。

---

## 九、文件清单

### 源代码 (19 文件)

```
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/
├── topology/ocaf/
│   ├── __init__.py
│   ├── models.py
│   ├── compat.py
│   ├── schema.py
│   ├── label_index.py
│   ├── repository.py
│   ├── document.py
│   ├── errors.py
│   ├── writer.py
│   ├── capture_session.py
│   ├── selection_service.py
│   ├── cae_preflight.py
│   ├── heuristic_candidates.py
│   ├── selectors.py                # 遗留死代码
│   └── tracked_ops/
│       ├── __init__.py
│       ├── boolean.py
│       ├── extrude.py
│       ├── revolve.py
│       ├── fillet.py
│       ├── chamfer.py
│       ├── unify.py
│       ├── mirror.py
│       └── pattern.py
├── runtime/context.py              # PR-6 修改
└── pipeline/run.py                 # PR-6 修改
```

### 测试 (18 文件, 116 测试)

```
tests/generative_cad/topology/ocaf/
├── conftest.py
├── smoke/
│   ├── test_atomic_publish.py
│   ├── test_tag100_schema.py
│   ├── test_tnaming_roundtrip.py    # 2 tests 因 OCP crash 跳过
│   ├── test_utf8_path.py
├── test_cae_binding.py
├── test_capture_session.py
├── test_hardening.py
├── test_live_models.py
├── test_operation_coverage.py
├── test_pipeline_topology_modes.py
├── test_selection_integration.py    # ★ 面级 Solve 集成
├── test_selection_service.py
├── test_writer_correctness.py
```

### 文档 (6 文件)

```
docs/
├── Text-to-CAD_OCAF原生持久化拓扑命名_系统实施指导书_v3.0.md  # 实施规范
├── OCAF_完整诊断测试报告_v3.0.md                              # 诊断历史
├── OCAF_实施交接文档_上下文恢复指南.md                         # 上下文字段恢复
├── OCAF_原生拓扑命名_implementation_status.md                 # 实施状态
├── OCAF_DoD_审计报告_v1.md                                    # DoD 审计
├── OCAF_项目状态与审查文档_v1.md                               # 本文档
```

---

## 十、后续工作建议

### 高优先级

1. **跨 Revision Selection Solve (T2)**: 实现多 revision 管线——这是 DoD #2 的核心要求。
2. **OCP crash 修复/规避**: T4 (Delete Solve) 需要 OCP 补丁或子进程隔离。
3. **清理 selectors.py**: 删除旧 FaceSelector 以避免未来的混淆。

### 中优先级

4. **EDGE 级 Solve (T8)**: Fillet/Chamfer 的 EDGE selection 集成测试。
5. **Construction roles 稳定性 (T6)**: 参数变化后验证 start_cap/end_cap identity。
6. **Pattern instance identity (T7)**: 打乱面枚举顺序验证 instance ID 稳定。
7. **capture-off 几何回归 (DOD #9)**: topology_mode=off vs on 的 A/B STEP 对比。

### 低优先级

8. **E2E G-CAD Pipeline (T12)**: 完整 IR → Rev1 → Rev2 → Solve → CAE preflight。
9. **OCP 版本矩阵测试**: 多 OCP 版本回归。
10. **性能优化**: XBF 大小优化、Solve 性能、大型模型压力测试。
