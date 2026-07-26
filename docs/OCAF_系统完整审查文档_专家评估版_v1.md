# OCAF 原生持久化拓扑命名系统 — 完整审查文档 v1.0

> 编制日期：2026-07-26
> 用途：供专家独立审查——包含已完成、未完成、受限、遇阻的全部内容
> 环境：Python 3.11.9 · CadQuery 2.7.0 · OCP 7.8.1.1 · OCCT 7.8.1 · Windows 11
> 测试：**198 passed, 0 failed** (24 测试文件, 22 源文件)

---

## 一、系统概述

本系统为 Text-to-CAD 管线实现了基于 OCCT OCAF/TNaming 的原生持久化拓扑命名。核心目标：跨设计 Revision 稳定追踪 FACE/EDGE 身份，使 CAE solver 能够通过 `selection_id`（而非 face index 或坐标）可靠绑定载荷/约束面。

系统遵循 v5.0 实施指导书（`Text-to-CAD_OCAF原生持久化拓扑命名_下一阶段实施指导书_v5.0.md`），通过 7 个实施 PR（PR-A ~ PR-G）+ 1 个收尾 PR（PR-H）逐步建成。

---

## 二、已完成 PR 清单

### PR-A：审计基线与 StableLabelIndex v2 ✅ 100%

**完成内容**：
- `compat.py`: `read_ascii_string` / `read_integer` / required 变体——基于 `TDF_AttributeIterator` + `attr.Get()` 实例方法的安全属性读取
- `label_index.py`: Index v2 fail-closed——schema version 校验、10 项加载验证、6 种 counter 分离、`get_existing()` 只读查询、退休策略
- `models.py`: `StableObjectKey._VALID_KINDS` 扩展至 6 种；`validate()` 从 `assert` 改为 `raise InvalidEvolutionRelationError`
- `document.py`: `ensure_component/feature/selection` 附加 `TDataStd_Name`（空标签不持久化 bug 修复）
- `compat.py`: Null label guard——`read_ascii_string`/`read_integer` 增加 `label.IsNull()` 检查防 ACCESS VIOLATION
- `tools/ocaf_status_manifest.py`: CI manifest 生成工具
- `tests/test_stable_label_index_v2.py`: 16 tests (Index-1 到 Index-5 gate 测试 + validate regression)

**关键技术突破**：
- 发现 `attr.Get()` 实例方法在 OCP 7.8.1.1 中可用——解除了之前标记为"OCP 永久限制"的 `TDataStd_*.Get_s()` 不可用问题

---

### PR-B：Artifact Bundle Pipeline ✅ 70%

**完成内容**：
- `models.py`: `TopologyRunConfig(frozen, slots)` + `TopologyMode` Literal 类型
- `pipeline/run.py`: **执行顺序重排**——STEP export → postcheck → 然后 OCAF write（修正了"OCAF 在 postcheck 之前发布"的 bug）
- `topology/ocaf/verify_worker.py`: 子进程 XBF 验证——`verify_xbf()` → `VerifyResult`，native crash 隔离
- `tests/test_failure_injection.py`: 13 tests (writer abort、index failure、commit failure、verify valid/corrupt/missing、mode semantics、back-compat)

**未完成**：
- Immutable Revision Bundle 目录结构（需要 PR-C 的 HEAD.json 基础设施）
- 原子发布 (`os.replace` 替代 `shutil.copy2`)——Windows OCAF 文件句柄问题
- Pipeline 完整 §6.3 步骤 11-13 (Selection Solve + CAE preflight)——需要 PR-E/PR-F 完成后接入

---

### PR-C：Revision Core + True T2 ✅ 60%

**完成内容**：
- `models.py`: `RevisionRecord(frozen, slots)` + `RevisionState` Literal + `to_dict()`/`from_dict()`
- `schema.py`: DesignRoot Metadata 子标签常量 (META_TAG_SCHEMA_VERSION 等) + `REVISION_TAG_ENTRY_BASE`
- `writer.py`: `write_feature_result(label, new, previous_result=None)`——`Generated(initial)` / `Modify(subsequent)`
- `writer.py`: `write_batch(previous_result=...)` 透传
- `document.py`: `set_lineage_metadata()` / `get_lineage_metadata()` 读写 Tag 100:1
- `document.py`: `write_revision_record()` 写 Tag 100:6
- `document.py`: `get_current_result_shape()`——从 CurrentResult NamedShape 读取 `TopoDS_Shape`
- `tests/test_true_t2_modify.py`: 4 tests (三 Revision Modify 链、PreviousResult 可检索、Metadata 持久化、RevisionRecord 写入)

**未完成**：
- HEAD.json（需要 immutable revision dir）
- 乐观并发控制（parent conflict 检测）
- Face 级 UNIQUE Solve——**OCP 7.8.1.1 限制**：body 级 `Modify` 后 `TNaming_Selector.Solve()` 返回 Compound(6 faces)，无法单面精确解析

**实施中遇到的问题**：
- 子进程 template 格式化（raw string + `.format()` + f-string 混合）极易出错，SRC 路径 `parents[5]` vs `parents[4]` 计算不直观
- Face 级 UNIQUE Solve 不可行——尝试 6× face Modify 方案触发 ACCESS VIOLATION

---

### PR-D：Relation Identity + 快速修复 + Tracked Ops v2 ✅ 100%

**完成内容**：
- `selection_service.py`: `_read_policy()` / `_read_contract()` **真实实现**——从硬编码 `return None` 改为 `compat.read_ascii_string()` + JSON 反序列化
- `models.py`: `SelectionResolutionStatus` 新增 `INVALID_POLICY` / `INVALID_CONTRACT`
- `cae_preflight.py`: `pass` → 真实 entity kind 检查（`_classify_shape_kind()` 基于 `ShapeType()`）
- `writer.py`: `_relation_tag()` 优先查 Index，默认 position-based 向后兼容
- `label_index.py`: 新增 `allocate_relation()` 方法——Index 基础设施就绪
- `tracked_ops/pattern.py`: Fuse 步骤补全 `Modified` + `IsRemoved` 捕获（不再仅 `Generated`）
- `tests/test_relation_identity.py`: 7 tests (Policy roundtrip、Contract roundtrip、CAE kind mismatch/match、Relation infrastructure)

**未完成**：
- Writer 全面切换到 Index-based Relation Label（tracked ops 需要先提供 `RelationKey`）
- 枚举顺序扰动测试（face/relation 顺序变化 → Tag 不变）

**关键技术突破**：
- Policy/Contract 读取从"OCP 永久阻塞"中解除——`attr.Get()` 可用性验证后修复
- CAE entity kind 检查从空操作变为真实功能

---

### PR-E：Selection Service v3 + Solve Worker ✅ 100%

**完成内容**：
- `selection_service.py`: `explode_entities` 增加 `IsSame()` 两两去重（`HashCode` 在 OCP 7.8.1.1 中可能崩溃）
- `selection_service.py`: `validate_semantics` 增加 `area_range` 检查
- `selection_service.py`: `_get_normal` 实现真实 Plane normal 提取（`BRepAdaptor_Surface.Plane()`）
- `selection_service.py`: `_get_shape_props` 新辅助函数（area + centroid）
- `models.py`: `SemanticContract` 新增 `area_range` 字段
- `topology/ocaf/solve_worker.py`: 子进程 Solve 隔离——`solve_in_subprocess()` → `SolveWorkerResult`
- `tests/test_selection_v3.py`: 6 tests (去重、面积验证、normal 提取、Solve Worker 正常/文件缺失)

**未完成**：
- Delete 前置判定（从 TNaming 历史预判 DELETED → 跳过 Solve 防 crash）——仅 `allow_deleted=True` 路径
- 完整 EDGE curve_type 语义验证（占位未实现）

---

### PR-F：CAE Gate 完整化 + Pipeline 接线 ✅ 100%

**完成内容**：
- `models.py`: `CaeBinding` 新增 `require_native_proof` / `require_complete_history`
- `cae_preflight.py`: Proof gate（拒绝 heuristic）+ History complete gate（占位就绪）
- `pipeline/run.py`: `_run_ocaf_write_and_save` 接入 CAE preflight；enforce 模式下 CAE 失败阻塞 Pipeline
- `tests/test_cae_gate.py`: 5 tests (字段存在、valid 通过、kind 不匹配阻塞、optional 不阻塞、solver no-start)

**未完成**：
- History complete gate 的 Pipeline context 激活（需要 capture_session 提供 `history_complete` 信息）
- CAE preflight 证据链的完整 JSON 输出

---

### PR-G：T5-T8 场景测试 + 系统收尾 ✅ 100%

**完成内容**（纯测试，零源码修改）：
- `tests/test_scenario_t3_split.py`: 3 tests (cut face split、source key 稳定性、volume A/B)
- `tests/test_scenario_t5_unify.py`: 3 tests (unify box、history、writer integration)
- `tests/test_scenario_t6_roles.py`: 3 tests (extrude roles 不同高度、different caps、semantic names)
- `tests/test_scenario_t7_pattern.py`: 3 tests (per-instance history、count=1、fuse history)
- `tests/test_scenario_t8_edge.py`: 4 tests (fillet edge shapes、chamfer edge shapes、face history、multi-edge)

---

### PR-H：文档同步 + 最终 Manifest ✅ 100%

**完成内容**：
- `docs/OCAF_完整诊断测试报告_v5.0.md`: 198 tests 完整状态
- `docs/OCAF_实施交接文档_上下文恢复指南.md`: v3.0——最新环境、阻塞项、代码坐标
- `docs/generated/OCAF_BUILD_MANIFEST.json`: 198 passed, 0 failed, SHA256 可复现

---

## 三、未完成项目汇总

### 3.1 被 OCP 7.8.1.1 永久阻塞

| 项目 | 来源 | 阻塞机制 | 建议 |
|------|------|---------|------|
| **T4 Delete Solve** | PR-C | `TNaming_Selector.Solve()` 在被选面完全删除后 ACCESS VIOLATION (0xC0000005) | OCP 升级后重试；当前可通过 TNaming DELETED relation 前置判定跳过 Solve |
| **Face 级 UNIQUE Solve** | PR-C | Body 级 `Modify(old,new)` 后 Solve 返回 Compound(6 faces)→AMBIGUOUS。6× face Modify 触发 ACCESS VIOLATION | 需要 OCCT 7.9+ 的 face 级 TNaming 精确追踪 |
| **子进程 TNaming destructor crash** | PR-A | 子进程退出时 OCP 对象析构 crash (returncode 3221226505) | 使用 `os._exit(0)` 或在写入完成后显式 `del` 所有 OCP 对象 |
| **`app.Retrieve` 在垃圾数据上的 crash** | PR-A | 非 XBF 格式文件 → ACCESS VIOLATION | 子进程隔离 Retrieve；验证 XBF magic bytes；min_size guard 已实现 |
| **`TopoDS_Shape.HashCode` crash** | PR-E | 去重无法使用 HashCode | 当前使用 `IsSame()` 两两比较（O(n²)，对 face 数量 <100 可接受） |
| **Windows OCAF 文件句柄** | PR-B | `os.replace` 在 OCAF-held 文件上失败 (WinError 32) | 当前 `shutil.copy2` + best-effort remove；需要 `app.Close(doc)` 完全释放后重试 |

### 3.2 架构未完成（非 OCP 阻塞）

| 项目 | 来源 | 说明 | 优先级 |
|------|------|------|--------|
| **Immutable Revision Bundle** | PR-B §6.4 | `lineage/revisions/rev-NNNNNN/design.xbf` 目录结构 | 中 |
| **HEAD.json** | PR-C §7.2-7.3 | `{head_revision_id, head_revision_number}` 指针文件 | 中 |
| **乐观并发控制** | PR-C §7.3 | `parent_revision_id` 冲突检测 | 中 |
| **原子发布** | PR-B §6.5 | `os.replace` 替代 `shutil.copy2` | 低（Windows 阻塞） |
| **RelationKey 全面迁移** | PR-D §8.3 | Writer 默认仍用 position-based Tag；tracked ops 需提供 `RelationKey` | 低 |
| **枚举顺序扰动测试** | PR-D §8.8 | face iteration / relation list / component 执行顺序变化 → Tag 不变 | 低 |
| **History complete gate 激活** | PR-F §10.3 | CAE preflight 的 `require_complete_history` 已占位但未连接 capture_session | 低 |
| **EDGE 完整语义验证** | PR-E §9.5 | `_get_normal` 已实现 FACE；EDGE curve_type/direction 未实现 | 低 |
| **T6 Construction Roles TNaming 验证** | PR-C | Construction Roles (start_cap/end_cap) 当前通过 TNaming_Builder 写入但未做跨 Revision Solve 验证 | 低 |

### 3.3 外部依赖阻塞

| 项目 | 来源 | 依赖 | 说明 |
|------|------|------|------|
| **T12 E2E G-CAD Pipeline** | PR-G | 完整 IR 管线 | 需要自然语言→Canonical IR→几何→多 Revision→Selection→CAE 的完整链路 |

---

## 四、实施中遇到的问题与解决方案

### 4.1 技术问题

| 问题 | 发现阶段 | 解决方案 |
|------|---------|---------|
| `attr.Get()` 实例方法可用性未知 | PR-A Step 0 | 最小可行性实验验证→确认可用 |
| 空标签不持久化（SaveAs 后消失） | PR-A | `ensure_*` 方法附加 `TDataStd_Name` |
| `read_ascii_string` 在 Null label 上 ACCESS VIOLATION | PR-C | 增加 `label.IsNull()` guard |
| 子进程 template 格式化复杂（raw string + f-string + .format） | PR-C | 改为 hybrid 模式（Rev1 子进程 + Rev2/3 进程内） |
| SRC 路径 `parents[5]` vs `parents[4]` 计算不直观 | PR-C | 修正为 `parents[4]`（测试目录结构所致） |
| Face 级 UNIQUE Solve 不可行 | PR-C | 接受 body 级 AMBIGUOUS；标记为 OCP 限制 |
| Writer 改动破坏 Index entry_count 预期 | PR-D | Writer 默认 position-based，Index 分配仅在显式请求时 |
| `SemanticContract` 缺少 `area_range` 字段 | PR-E | 新增字段（向后兼容） |

### 4.2 架构决策

| 决策 | 说明 |
|------|------|
| **Live/Audit 分离** | Live 模型持有 `TopoDS_Shape`（不可跨进程），Audit 模型仅 JSON-safe 标量 |
| **固定 Tag 100 Schema** | 避免与 XCAF 系统标签 1-10 冲突；动态对象从 1000 开始 |
| **Writer 不管理事务** | 事务由 `OcafDocumentSession.begin_write/commit_write/abort_write` 统一管理 |
| **fail-closed 优先** | `load_from_ocaf` 10 项验证 → `CorruptStableIndexError`；`validate()` raise 不用 assert |
| **子进程隔离** | verify_worker + solve_worker——所有正式 XBF 操作在子进程执行，native crash 不传播 |
| **向后兼容** | Writer Relation Label 默认 position-based；旧 `ocaf_path` 参数保留 |

---

## 五、当前系统成熟度

```
OCAF Native Topology Naming — Engineering Beta
198 tests | 22 source files | 10/12 scenarios (T4/T12 blocked)
```

| 能力层 | 成熟度 |
|--------|--------|
| OCAF/XBF 基础持久化 | 95% |
| UTF-8/Tag 100/安全 Retrieve | 95% |
| StableLabelIndex v2 | 95% |
| 单 Revision Live History + TNaming Writer | 85% |
| 跨 Revision Modify 演化 | 70% |
| Selection Create/Solve | 65% |
| CAE Gate | 60% |
| Pipeline 集成 | 55% |
| Immutable Revision Artifact | 20% |

---

## 六、下一步工作建议（供专家参考）

### 优先级 1：解除 OCP 阻塞

1. **OCP 升级**（7.8.1.1 → 7.9+）后重试：
   - T4 Delete Solve（`TNaming_Selector.Solve` on deleted face）
   - Face 级 UNIQUE Solve（逐面 `Modify(old_face, new_face)`）
   - `TopoDS_Shape.HashCode` 去重
   - Windows 文件句柄释放 → `os.replace` 原子发布

### 优先级 2：架构补完

2. **Immutable Revision Bundle**：`lineage/revisions/rev-NNNNNN/` 目录结构 + `HEAD.json`
3. **乐观并发**：`parent_revision_id` 冲突检测
4. **RelationKey 全面迁移**：tracked ops 提供 `RelationKey`，Writer 全面切换 Index-based

### 优先级 3：完整 E2E

5. **T12 E2E G-CAD Pipeline**（需要 IR 管线就绪）
6. **CAE Solver 真实接入**：从 `solver_start_count=0` 到实际 ANSYS/CalculiX 调用

### 优先级 4：质量提升

7. **枚举顺序扰动测试**：证明 Tag 不依赖迭代顺序
8. **EDGE 完整语义验证**：curve_type, line direction, circle radius/axis
9. **Performance baseline**：1000+ relation 写入性能

---

## 七、关键代码坐标速查

| 文件 | 关键符号 |
|------|---------|
| `compat.py:257` | `read_ascii_string()` — 安全属性读取（Null guard + attr.Get()） |
| `compat.py:186` | `collect_tnaming_labels()` — 递归收集 TNaming 标签 |
| `label_index.py:78` | `StableLabelIndex` — v2 fail-closed index |
| `label_index.py:163` | `save_to_ocaf()` — v2 schema 写入 |
| `label_index.py:255` | `load_from_ocaf()` — 10 项验证加载 |
| `writer.py:117` | `write_feature_result()` — Generated/Modify 分支 |
| `writer.py:77` | `write_batch(previous_result=...)` — 透传 previous |
| `document.py:263` | `set_lineage_metadata()` — Tag 100:1 写入 |
| `document.py:320` | `get_current_result_shape()` — 读 CurrentResult |
| `selection_service.py:324` | `_read_policy()` — 真实 Policy 读取 |
| `selection_service.py:492` | `explode_entities()` — IsSame 去重 |
| `selection_service.py:390` | `validate_semantics()` — area_range + normal |
| `cae_preflight.py:22` | `_classify_shape_kind()` — ShapeType 分类 |
| `cae_preflight.py:99` | Proof gate — 拒绝 heuristic |
| `verify_worker.py:102` | `verify_xbf()` — 子进程 XBF 验证 |
| `solve_worker.py:96` | `solve_in_subprocess()` — 子进程 Solve |
| `pipeline/run.py:125` | `_run_ocaf_write_and_save()` — 正确顺序 + CAE |
| `pipeline/run.py:196` | `run_canonical_gcad(topology=...)` — 正式入口 |
| `models.py:108` | `LiveEvolutionRelation.validate()` — raise, not assert |
| `models.py:441` | `TopologyRunConfig` — Pipeline 配置 |
| `models.py:466` | `RevisionRecord` — 跨 Revision 记录 |
