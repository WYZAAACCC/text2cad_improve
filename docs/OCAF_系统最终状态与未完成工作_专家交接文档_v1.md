# OCAF 原生持久化拓扑命名 — 最终状态与未完成工作

> 编制日期：2026-07-26
> 提交：b7e3fd6 main
> 测试：210 passed, 0 failed, 0 skipped
> 用途：将此文档交给专家，由专家根据文档与代码找到推进方案

---

## 一、系统当前状态

```
OCAF Native Topology Naming — Engineering Beta+
210 tests | 28 source files | 28 test files | 2 worker modules
```

### 结论

Face 级 UNIQUE Solve 在当前 OCP 7.8.1.1 中**可行**。之前标记为"OCP 永久阻塞"是因为 Label 组织和 history 粒度不正确。关键修正：

1. **ResultRoot 子历史**：面级 TNaming 必须放在 Context NamedShape 所在 Label 的**直接子标签**中（兄弟标签不可见）
2. **Semantic Fixture**：必须使用 `BRepPrimAPI_MakeBox.TopFace()` 等稳定构造语义面，不能用 CadQuery `Box.Faces()[i]` 枚举索引
3. **Face 级 Modify**：每面独立 `TNaming_Builder.Modify(old_face, new_face)`

---

## 二、全部已完成工作

### v5.0 实施阶段（7 PR）

| PR | 内容 |
|----|------|
| PR-A | StableLabelIndex v2 fail-closed、safe attribute reader、validate()→exception |
| PR-B | TopologyRunConfig、Pipeline 执行顺序修正、verify_worker、failure injection |
| PR-C | RevisionRecord、Modify-based 跨 Revision T2、lineage metadata、get_current_result_shape |
| PR-D | Policy/Contract 真实读取（解除 OCP Get_s() 误判）、CAE entity kind 检查、Pattern Fuse history 补全 |
| PR-E | explode_entities IsSame 去重、语义验证增强（area_range/normal）、solve_worker |
| PR-F | CAE preflight proof/history gate、Pipeline CAE 接入、solver no-start 验证 |
| PR-G | T3/T5/T6/T7/T8 场景测试 |
| PR-H | 文档同步 + Manifest |

### v6.0 实施阶段（8 PR）

| PR | 内容 |
|----|------|
| PR-1 | **Face UNIQUE 突破**：ResultRoot 子历史 Schema + BRepPrimAPI_MakeBox semantic box T2 + write_role_result |
| PR-2 | Index v3：placeholder 消除、allocate_relation 参数化、revision_number 从 metadata 恢复、Solve read-only lookup |
| PR-3 | Pattern Fuse history 查询方向修正（output face→input face）、Pipeline 自动注入 previous_result |
| PR-4 | Null Shape 检查、explode before semantics 顺序修正、1→N 同一 Builder |
| PR-5 | Immutable Revision Bundle（RevisionStore + HEAD.json + close-before-publish） |
| PR-6 | Solve Worker 增强输出（area/centroid/normal/surface_type per entity） |
| PR-7 | Pipeline CAE Binding 真实数据 + collect_tnaming_labels 范围限定 |
| PR-8 | Corrupted XBF 硬化（5 场景） + 最终 Manifest |

### 系统架构（28 源文件）

```
topology/ocaf/
├── models.py              # Live/Audit 模型, TopologyRunConfig, RevisionRecord, StableObjectKey
├── compat.py              # ext_utf8, read_ascii_string/integer, collect_tnaming_labels
├── schema.py              # 固定 Tag 100 标签树, TagPath, Index v2 常量
├── label_index.py         # StableLabelIndex v2/v3: fail-closed, 6 counters, allocate_relation
├── repository.py          # OcafRepository: create/open/save/publish
├── document.py            # OcafDocumentSession, lineage metadata, get_current_result_shape
├── errors.py              # 20+ 结构化错误类型
├── writer.py              # TopologyNamingWriter: Generated/Modify, write_role_result, 1→N Builder
├── capture_session.py     # CaptureSession 批收集
├── selection_service.py   # PersistentSelectionService: dedup, semantics, policy read
├── cae_preflight.py       # CAE gate: entity kind, proof, history
├── heuristic_candidates.py# HeuristicCandidateFinder (降级)
├── verify_worker.py       # 子进程 XBF 验证 (subprocess crash isolation)
├── solve_worker.py        # 子进程 Selection Solve (enhanced output)
├── revision_store.py      # Immutable Revision Bundle + HEAD.json
├── tracked_ops/
│   ├── boolean.py         # cut/fuse/common (BOPAlgo_BOP + history)
│   ├── extrude.py         # extrude (start_cap/end_cap)
│   ├── revolve.py         # revolve
│   ├── fillet.py          # fillet (persistent EDGE)
│   ├── chamfer.py         # chamfer
│   ├── unify.py           # unify (ShapeUpgrade_UnifySameDomain)
│   ├── mirror.py          # mirror (1:1 face mapping)
│   └── pattern.py         # linear pattern (input-face history query)
├── pipeline/run.py        # Pipeline: correct order, previous_result, CAE preflight
└── runtime/context.py      # RuntimeContext: topology_mode, capture_session
```

---

## 三、未完成 / 受限 / 阻塞完整清单

### 3.1 OCP 7.8.1.1 永久阻塞（不可绕过）

| 阻塞项 | 机制 | 影响 |
|--------|------|------|
| `TNaming_Selector.Solve()` 在面删除后 ACCESS VIOLATION | C++ 级崩溃，Python 无法捕获 | T4 Delete Solve |
| TNaming destructor crash | 子进程退出时 OCP 对象析构 crash (returncode 3221226505) | 子进程测试 |
| `app.Retrieve()` 在垃圾数据上 ACCESS VIOLATION | 非 XBF 格式→崩溃 | 损坏文件恢复 |
| `TNaming_Selector.Select()` 空文档 ACCESS VIOLATION | 无 TNaming_Builder 前提→崩溃 | 首次创建 Selection |
| `TopoDS_Shape.HashCode` 可能崩溃 | 特定 shape 触发 | 实体去重 |
| Windows OCAF 文件句柄不释放 | `os.replace` 失败 (WinError 32) | 原子发布 |

**备注**：以上 6 项在 v5.0 诊断文档中记录。经过 v6.0 验证，Face 级 UNIQUE 不属于此列——它可以通过正确的 Label 组织解决。

### 3.2 架构未完成（非 OCP 阻塞）

| 项目 | 说明 | 优先级 |
|------|------|--------|
| **C++ fixture** | 在 C++ OCCT 7.8.1 中运行相同 semantic box fixture——验证 OCP binding 是否引入额外问题 | 高 |
| **版本矩阵** | OCP 7.8.1.2 / 7.9.3.1.1 环境下验证 Face UNIQUE fixture | 高 |
| **HistoryGraph/HistoryComposer** | Pattern 顺序 Fuse 产生的多阶段 history（source→transform→fuse1→fuse2→final）需要组合为 input→final output 映射 | 中 |
| **EDGE 完整语义验证** | `validate_semantics` 仅实现了 FACE surface_type/normal/area_range；EDGE curve_type/direction/radius 未实现 | 低 |
| **Feature Namespace semantic ID** | `ensure_feature()` namespace 使用 `component:<Tag>` 而非 `component:<semantic_id>`——需要 API 签名变更 | 低 |
| **RelationKey 全面迁移** | Writer 默认 position-based Tag；tracked ops 需提供 `RelationKey` 才能切换到 Index-based | 低 |
| **T4 Delete Solve** | 通过 TNaming DELETED relation 前置判定跳过 Solve（v6.0 §9.6 方案），未实现 | 中 |
| **T12 E2E G-CAD Pipeline** | 需要完整 IR 管线（自然语言→Canonical IR→几何→多 Revision→Selection→CAE） | 高 |

### 3.3 实施中未达预期的项目

| 项目 | 预期 | 实际 | 原因 |
|------|------|------|------|
| Pipeline CAE binding | 从 OCAF Tag 100:5 读真实 binding | 接受 `TopologyRunConfig.cae_bindings` | Tag 100:5 CAEBindings 未完善 |
| Feature Namespace | 语义 component_id | Tag-based | API 变更影响面太大 |
| Writer Relation Label | 全部 Index-based | 默认 position-based 回退 | tracked ops 未提供 RelationKey |
| History complete gate | 连入 CAE preflight | 占位 | capture_session 未提供 history_complete per batch |

---

## 四、实施中遇到的关键问题

### 4.1 技术问题

| 问题 | 发现阶段 | 解决方案 |
|------|---------|---------|
| `attr.Get()` 实例方法可用性未知 | v5.0 PR-A | 最小可行性实验验证→确认可用 |
| 空标签不持久化（SaveAs 后消失） | v5.0 PR-A | ensure_* 方法附加 TDataStd_Name |
| Null label 上 read_ascii_string ACCESS VIOLATION | v5.0 PR-C | 增加 label.IsNull() guard |
| 子进程 template 格式化出错 | v5.0 PR-C | 改为 hybrid 模式（Rev1 子进程 + Rev2/3 进程内） |
| Body 级 Modify → Solve 返回 Compound(6 faces) | v5.0 PR-C | 根因是 Label 组织错误（不是 OCP 限制） |
| Writer 改动破坏 index entry_count | v5.0 PR-D | Writer 默认 position-based |
| `TNaming_NamedShape.IsNull()` 不存在 | v6.0 PR-4 | 仅 None 检查 |
| Face UNIQUE 被错误归因于 OCP 版本 | v5.0 全阶段 | v6.0 PR-1 推翻——根因是 Label 组织 |

### 4.2 架构决策

| 决策 | 理由 |
|------|------|
| Live/Audit 分离 | Live 持有 TopoDS_Shape（不可跨进程），Audit 仅 JSON-safe 标量 |
| 固定 Tag 100 | 避免与 XCAF 系统标签 1-10 冲突 |
| Writer 不管理事务 | 事务统一由 OcafDocumentSession 管理 |
| fail-closed 优先 | load_from_ocaf 10 项验证；validate() raise 不用 assert |
| 子进程隔离 solve/verify | native crash 不传播到主进程 |
| close-before-publish | 释放 OCAF 文件句柄后再 publish |
| ResultRoot 子历史 | Selector 仅检查 Context Label 的直接子标签 |

---

## 五、下一步建议（供专家）

### 优先路线 A：验证 OCP binding 正确性

1. 在 C++ OCCT 7.8.1 中运行相同的 semantic box fixture（Rev1→Rev2→Rev3 + TopFace UNIQUE）
2. 如果 C++ 成功、Python 失败 → OCP binding 问题
3. 如果 C++ 也失败 → OCCT 版本缺陷
4. 如果都成功 → 当前 Python 路径正确

### 优先路线 B：解决 History 组合

5. 实现 `HistoryGraph` + `HistoryComposer`——将 Pattern 的多阶段 Fuse history 组合为 input→final output 映射
6. 验证 history_complete 可证明

### 优先路线 C：完成 T4 Delete

7. 从 TNaming DELETED relation 前置判定——跳过 Solve，返回 DELETED
8. 子进程隔离验证

### 优先路线 D：T12 E2E

9. IR 管线就绪后，完成自然语言→3 Revision→Selection→CAE 完整链路

---

## 六、关键代码坐标

| 索引 | 文件:行 | 符号 | 说明 |
|------|---------|------|------|
| 1 | compat.py:257 | `read_ascii_string()` | 安全属性读取 (Null guard + attr.Get) |
| 2 | compat.py:186 | `collect_tnaming_labels()` | 收集 TNaming 标签 (支持 restrict_to) |
| 3 | label_index.py:78 | `StableLabelIndex` | v2/v3 fail-closed index |
| 4 | label_index.py:197 | `allocate_relation()` | relation→Index (已消除 placeholder) |
| 5 | writer.py:125 | `write_feature_result()` | Generated/Modify 分支 |
| 6 | writer.py:160 | `write_role_result()` | ResultRoot 子历史 (v6.0) |
| 7 | document.py:263 | `set_lineage_metadata()` | Tag 100:1 |
| 8 | document.py:320 | `get_current_result_shape()` | 读 CurrentResult TopoDS_Shape |
| 9 | selection_service.py:324 | `_read_policy()` | 真实 Policy 读取 (不再 return None) |
| 10 | selection_service.py:217 | `_classify_resolution()` | explode→semantics 正确顺序 |
| 11 | cae_preflight.py:22 | `_classify_shape_kind()` | ShapeType→TopologyEntityKind |
| 12 | verify_worker.py:102 | `verify_xbf()` | 子进程 XBF 验证 |
| 13 | solve_worker.py:19 | `_WORKER_SCRIPT` | 增强输出 (entities array) |
| 14 | revision_store.py:1 | `RevisionStore` | Immutable Revision Bundle |
| 15 | pipeline/run.py:125 | `_run_ocaf_write_and_save()` | 正确顺序 + previous_result + close-before-publish |
| 16 | pipeline/run.py:196 | `run_canonical_gcad(topology=...)` | 正式 Pipeline 入口 |
| 17 | models.py:108 | `LiveEvolutionRelation.validate()` | raise, not assert |
| 18 | models.py:441 | `TopologyRunConfig` | Pipeline 配置 (含 cae_bindings) |
| 19 | models.py:466 | `RevisionRecord` | 跨 Revision 记录 |
| 20 | models.py:373 | `StableObjectKey` | 6 种 kind 复合 key |
| 21 | tracked_ops/pattern.py | `_capture_fuse_face()` | input face history (v6.0) |
| 22 | schema.py | `FEATURE_TAG_RESULT_ROOT` | ResultRoot schema (v6.0) |
| 23 | tests/test_t2_semantic_box.py | `TestSemanticBoxT2` | Face UNIQUE gate 测试 |
| 24 | tests/test_stable_label_index_v2.py | `TestIndex1ReadOnlyRecovery` | Index 恢复 gate |

---

## 七、测试命令

```powershell
cd integrations/engineering_tools
..\..\.conda\python.exe -m pytest tests/generative_cad/topology/ocaf/ `
  --ignore=tests/generative_cad/topology/ocaf/smoke/test_tnaming_roundtrip.py -v
```

预期：**210 passed, 0 failed**

---

## 八、环境

```
Python:     3.11.9 (Anaconda)
CadQuery:   2.7.0
OCP:        7.8.1.1
OCCT:       7.8.1
OS:         Windows 11 Home China 10.0.22631
工作目录:    e:\text_to_cad_improve\auto_detection_process\
虚拟环境:    .\.conda\
Git Remote:  text2cad → https://github.com/WYZAAACCC/text2cad_improve.git
```
