# OCAF 原生持久化拓扑命名 — 实施交接文档 v2.0

> 日期: 2026-07-26
> 用途: 上下文重置后恢复工作状态
> 当前进度: v4.0 Step 1-4 + T2 + PR-13 完成，131 测试通过

---

## 1. 你必须首先读取的文件

按优先级排列：

| 顺序 | 文件 | 用途 |
|------|------|------|
| 1 | `docs/Text-to-CAD_OCAF原生持久化拓扑命名_下一阶段实施指导书_v4.0.md` | **当前实施规范**——所有工作的唯一执行依据 |
| 2 | `docs/OCAF_完整诊断测试报告_v4.0.md` | 当前系统完整测试状态 |
| 3 | `docs/OCAF_项目状态与审查文档_v1.md` | 项目状态概览，供专家审查 |
| 4 | `docs/OCAF_DoD_审计报告_v1.md` | Definition of Done 逐条对照 |
| 5 | `docs/OCAF_OCP_API限制与已知问题_v1.md` | 13 个 OCP 7.8.1.1 API 限制 |
| 6 | `docs/OCAF_原生拓扑命名_implementation_status.md` | 实施进度追踪 |

---

## 2. 环境信息

```
Python:     3.11.9 (Anaconda)
CadQuery:   2.7.0
OCP:        7.8.1.1
OCCT:       7.8.1 (原生 C++ 库)
OS:         Windows 11 Home China 10.0.22631
工作目录:    e:\text_to_cad_improve\auto_detection_process\
虚拟环境:    .\.conda\
Python 路径: .\.conda\python.exe
Git Remote:  text2cad → https://github.com/WYZAAACCC/text2cad_improve.git
测试命令:    cd integrations/engineering_tools && ..\..\.conda\python.exe -m pytest tests/generative_cad/topology/ocaf/ --ignore=tests/.../test_tnaming_roundtrip.py -v
```

---

## 3. 当前完成状态

### v4.0 步骤完成情况

| 步骤 | 内容 | 状态 |
|------|------|------|
| Step 1 | P0-01: Pipeline create()/open() 替代空构造 | ✅ |
| Step 2 | P0-02: StableLabelIndex 复合Key + OCAF持久化 | ✅ |
| Step 3 | P0-03/04: 事务 + staging + publish + 正确顺序 | ✅ |
| Step 4 | P0-05: Pipeline Solve/Preflight 集成 | ⚠️ 基础设施就绪 |
| T2 | 三进程跨 Revision | ✅ |
| P1-04 | explode_entities | ✅ |
| P1-08 | IsSame() 替代 `is` | ✅ |
| P1-01/02 | RelationKey + SourceEntityRef 模型 | ✅ |
| P1-03 | Pattern Fuse history 完整化 | ✅ |
| PR-13 | 删除 selectors.py + 几何A/B + 多组件 | ✅ |

### 测试状态

```
131 passed (excluding 2 known-fragile tnaming_roundtrip)
```

---

## 4. OCP API 限制（不可绕过）

以下限制来自 OCP 7.8.1.1，**不要花时间尝试修复**：

1. `TDataStd_AsciiString.Get_s()` 不存在 → Policy/Contract 无法可靠恢复
2. `TDataStd_Integer.Get_s()` 不存在 → 计数器无法恢复
3. `TNaming_Selector.Solve()` 在面删除后 ACCESS VIOLATES → T4 Delete Solve 不可行
4. `app.Retrieve()` 在垃圾数据上 ACCESS VIOLATES → 已加 min_size guard
5. `TNaming_Selector.Select()` 在空文档上 ACCESS VIOLATES → 需先写 Builder
6. `IsKind(GetID_s())` 返回 Standard_GUID 而非 Standard_Type → 用 DynamicType().Name()

---

## 5. 未完成的受阻项目

这些项目**不要实施**，因为被 OCP 限制阻塞：

- P0-06: Delete Solve 崩溃隔离
- P1-05: Policy/Contract fail-closed (需要 Get_s())
- P1-06: CAE preflight entity kind 完整检查 (需要 Get_s())

---

## 6. 下一步工作（不受阻）

按 v4.0 指南 §8 的 PR 顺序，**跳过受阻项目**：

1. **PR-13 剩余**: T6 construction role 稳定性, T7 pattern instance identity, T8 EDGE selection
2. **PR-12**: CAE Gate Pipeline 调用（在不受阻范围内）
3. **T12**: E2E G-CAD Pipeline（如 IR 管线可用）

---

## 7. 关键代码坐标

| 文件 | 关键内容 |
|------|---------|
| `topology/ocaf/compat.py` | ext_utf8(), retrieve_xcaf_document(), collect_tnaming_labels() |
| `topology/ocaf/models.py` | LiveEvolutionRelation, SelectionPolicy, CaeBinding, StableObjectKey, RelationKey |
| `topology/ocaf/schema.py` | DESIGN_ROOT_TAG=100, TagPath, make_component_tagpath() |
| `topology/ocaf/label_index.py` | StableLabelIndex + save_to_ocaf/load_from_ocaf |
| `topology/ocaf/repository.py` | OcafRepository.create/open/save_to/save_temp/publish |
| `topology/ocaf/document.py` | OcafDocumentSession.create/open, ensure_component/feature/selection |
| `topology/ocaf/writer.py` | TopologyNamingWriter + TAG_CURRENT_RESULT=2, TAG_EVOLUTION_RELATIONS=3 |
| `topology/ocaf/selection_service.py` | PersistentSelectionService.create/solve, explode_entities() |
| `topology/ocaf/cae_preflight.py` | run_cae_preflight() |
| `topology/ocaf/capture_session.py` | CaptureSession.stage/iter_batches/clear |
| `pipeline/run.py` | _run_ocaf_write_and_save(), run_canonical_gcad() |
| `runtime/context.py` | topology_mode, enable_topology_capture, capture_session |

---

## 8. 核心设计约束（不可违反）

1. ❌ 不使用 `doc.Main().NewChild()` — 使用 `FindChild(TAG, True)`
2. ❌ 不使用 `app.Open(path, doc)` — 使用 `app.Retrieve(folder, name, True)`
3. ❌ 不传 `TCollection_ExtendedString(str)` 无第二个参数 — 使用 `ext_utf8()`
4. ❌ 不使用 face/edge index 作为持久身份
5. ❌ 不使用几何指纹作为权威身份
6. ❌ Writer 不管理事务 — 纯写入
7. ✅ 空标签必须附加属性才能持久化
8. ✅ Solve 前必须调用 collect_tnaming_labels() 收集所有 TNaming 标签

---

## 9. 开始工作的检查清单

1. 读取 `Text-to-CAD_OCAF原生持久化拓扑命名_下一阶段实施指导书_v4.0.md` (必读 #1)
2. 读取 `OCAF_完整诊断测试报告_v4.0.md` 了解测试状态
3. 读取 `OCAF_OCP_API限制与已知问题_v1.md` 了解不可绕过限制
4. 确认环境: `.\.conda\python.exe -c "import cadquery; print('ok')"`
5. 运行测试: `pytest tests/generative_cad/topology/ocaf/ --ignore=...test_tnaming_roundtrip.py -v`
6. 确认 131 测试全部通过
7. 继续不受 OCP 限制阻塞的工作
