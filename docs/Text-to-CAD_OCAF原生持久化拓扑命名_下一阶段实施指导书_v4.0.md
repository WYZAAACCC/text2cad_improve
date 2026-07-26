# Text-to-CAD OCAF 原生持久化拓扑命名系统  
# 当前状态审查与下一阶段实施指导书 v4.0

> 日期：2026-07-26  
> 适用仓库：`WYZAAACCC/text2cad_improve`，`main` 分支  
> 审查范围：Text-to-CAD / G-CAD Pipeline、`topology/ocaf`、tracked operations、Selection、CAE preflight、现有状态与 DoD 文档  
> 执行对象：代码 Agent  
> 性质：下一阶段唯一实施基线；实施时应以源码和测试结果为准，不得仅依据模块注释或进度表判定完成状态

---

## 0. 执行摘要

当前系统已经跨过“OCCT/OCAF 能否原生持久化”的基础障碍，以下底层能力可以视为已经建立：

1. `BinXCAF/XBF` 原生保存与跨进程 `Retrieve()` 可用；
2. UTF-8 路径通过 `TCollection_ExtendedString(value, True)` 可正确处理；
3. Text-to-CAD 数据已规划在固定 `Tag 100` 下，与 XCAF 保留标签隔离；
4. `LiveEvolutionRelation` 已保存真实 `old_shape/new_shapes`；
5. `TopologyNamingWriter` 已按 `Generated/Modify/Delete` 的原生语义写入；
6. `TNaming_Selector`、Selection Policy、Semantic Contract 和 CAE preflight 的模块骨架已存在；
7. Boolean、Extrude、Revolve、Fillet、Chamfer、Mirror、Pattern、Unify 已有不同程度的 history 捕获实现。

但这仍然不是一个已经完成的“原生持久化拓扑命名系统”。当前源码更准确的状态是：

> **模块级 PoC 基础基本完成，但 Lineage、Revision、稳定 Label 索引、Pipeline 事务、Selection Solve、CAE Gate 尚未形成可信的端到端闭环。**

静态源码审查发现，现有状态文档低估了若干 P0 级问题：

- Pipeline 使用 `OcafDocumentSession()` 空构造，而不是 `create()` 或 `open()`；
- `StableLabelIndex` 仅为内存字典，没有写入 OCAF，也没有在重开时恢复；
- Pipeline 直接覆盖目标 XBF，绕过临时保存、子进程验证和原子发布；
- OCAF 在最终 STEP 与几何后验检查之前写入，可能发布失败 Revision；
- Pipeline 没有调用 `PersistentSelectionService.solve()` 或 `run_cae_preflight()`；
- `topology_mode="enforce"` 不能由公开入口有效配置；
- Writer 的关系标签仍依赖 relation 列表位置，而不是持久业务身份；
- Pattern 只捕获 Transform history，没有捕获最终 Fuse history，却把 `history_complete` 标为 `True`；
- Selection 解析返回的 `resolved_shapes` 仍可能只是一个包含多个面的 Compound；
- CAE preflight 没有真正检查 `allowed_entity_kinds`；
- Delete Solve 会导致 OCP 原生崩溃，目前没有可靠的进程隔离和故障分类。

因此下一阶段禁止继续盲目增加 tracked operation。必须先完成以下主线：

```text
代码一致性与 Pipeline 事务修复
→ StableLabelIndex 真正持久化
→ Revision/Lineage 生命周期
→ 稳定 Relation Identity
→ Selection Solve 正确分类与崩溃隔离
→ 三进程跨 Revision T2
→ EDGE / Unify / Pattern / Delete
→ CAE preflight 真正接入
→ 完整 Text-to-CAD E2E
```

---

# 1. 审查依据

## 1.1 关键文档

本次审查以以下文档为参考，但所有结论均再次与实际源码核对：

- `docs/OCAF_项目状态与审查文档_v1.md`
- `docs/OCAF_DoD_审计报告_v1.md`
- `docs/OCAF_原生拓扑命名_implementation_status.md`
- `docs/OCAF_完整诊断测试报告_v3.0.md`
- `docs/Text-to-CAD_OCAF原生持久化拓扑命名_系统实施指导书_v3.0.md`

注意：状态文档中的“PR 已完成”和“测试通过”只能说明局部单元测试结果，不能代替端到端源码审查。代码 Agent 不得把文档中的百分比作为实现事实。

## 1.2 关键源码

```text
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/
├── pipeline/run.py
├── runtime/context.py
└── topology/ocaf/
    ├── models.py
    ├── compat.py
    ├── schema.py
    ├── label_index.py
    ├── repository.py
    ├── document.py
    ├── writer.py
    ├── capture_session.py
    ├── selection_service.py
    ├── heuristic_candidates.py
    ├── selectors.py
    ├── cae_preflight.py
    └── tracked_ops/
        ├── boolean.py
        ├── extrude.py
        ├── revolve.py
        ├── fillet.py
        ├── chamfer.py
        ├── unify.py
        ├── mirror.py
        └── pattern.py
```

---

# 2. 当前系统真实状态

## 2.1 分层成熟度判断

以下百分比是本次静态审查的工程判断，不是测试覆盖率：

| 层级 | 当前成熟度 | 审查判断 |
|---|---:|---|
| OCAF/XBF 基础持久化 | 90% | UTF-8、Tag 100、Retrieve、基础 TNaming 已验证 |
| Live History 数据模型 | 80% | 已保存真实 Shape；部分 operation history 仍不完整 |
| TNaming Writer 基础语义 | 75% | Builder 调用正确；Relation Label 身份仍不稳定 |
| 单 Revision Selection PoC | 60% | 可创建、可 Solve；结果拆分和语义分类仍有缺陷 |
| Stable Label / ID 系统 | 25% | 只有内存实现；没有 OCAF 权威存储与重建 |
| Revision / Lineage | 10% | 基本未实现 |
| G-CAD Pipeline 集成 | 20% | 当前生产路径存在确定性构造与事务错误 |
| CAE Gate 集成 | 15% | 模块存在，但 Pipeline 未调用 |
| 完整原生拓扑命名产品 | 约 35% | 尚不能承担跨 Revision 自动 CAE 绑定 |

结论：

> 当前可以称为“原生 OCAF/TNaming 模块级 PoC”，不能称为“完成的持久化拓扑命名系统”。

---

# 3. 已正确实现、应当保留的部分

## 3.1 `models.py` 的 Live/Audit 分离

应保留：

- `LiveEvolutionRelation`
- `LiveEvolutionBatch`
- `EvolutionRelationAudit`
- `ProofClass`
- `TopologyEntityKind`
- `SelectionPolicy`
- `SemanticContract`
- `SelectionResolution`
- `CaeBinding`

原则正确：

```text
Live Shape → 仅在当前几何进程内写入 OCAF
Audit Evidence → JSON 安全，不参与身份判定
```

禁止再次退回“只保存面积、质心和数量，再反向猜 Shape”的旧模式。

需要改进：

- `validate()` 不应使用裸 `assert` 作为生产门禁；
- 改为抛出结构化 `InvalidEvolutionRelationError`；
- `assert` 在 Python 优化模式下可能被移除；
- 增加 `revision_id`、`parent_revision_id`、`source_entity_id`、`relation_key`。

## 3.2 `compat.py`

以下调用约束应保持为唯一合法方式：

```python
ext_utf8(value)
retrieve_xcaf_document(app, path)
TDF_AttributeIterator
TNaming_Selector(label).NamedShape()
collect_tnaming_labels(...)
```

持续禁止：

```python
app.Open(path, doc)
doc.Main().NewChild()
TDF_Tool.Label_s(...)
TCollection_ExtendedString(str(path))  # 缺少 True
FindAttribute(..., shell_attr)         # 当调用方需要真实 Handle 时
```

## 3.3 `schema.py`

固定 Tag 树方向正确：

```text
0:1
└── 100 DesignRoot
    ├── 1 Metadata
    ├── 2 Components
    ├── 3 Selections
    ├── 4 Assembly
    ├── 5 CAEBindings
    ├── 6 Revisions
    └── 7 StableIdIndex
```

应继续坚持：

- `FindChild(tag, create)`
- 动态 Tag 从 1000 起
- NativeNaming Label 独占
- 业务 Metadata 与 TNaming Attribute 分离

## 3.4 `CaptureSession`

当前直接持有 `LiveEvolutionBatch`、删除全局 token staging 的方向正确。

应补充：

- session 状态机；
- staged/committed/aborted/cleared；
- 重复 node/batch 检测；
- transaction 结束后强制 clear；
- 记录 batch 的执行序列号和 operation hash。

## 3.5 `TopologyNamingWriter`

以下映射是正确的：

```text
PRIMITIVE → Generated(new)
GENERATED → Generated(old, new)
MODIFIED  → Modify(old, new)
DELETED   → Delete(old)
```

必须保留“Writer 不自行开启事务”和“异常向上传播”的设计。

---

# 4. P0 级源码问题

## P0-01：Pipeline 创建的是无 Repository 的空 Session

当前 `run_canonical_gcad()` 中存在：

```python
_ocaf_session = OcafDocumentSession()
```

而 `OcafDocumentSession.repository` 在 `_repository is None` 时会直接抛错。

正确调用必须是：

```python
OcafDocumentSession.create(...)
```

或：

```python
OcafDocumentSession.open(existing_xbf)
```

这说明当前 `ocaf_path` 生产入口很可能没有经过真正的 OCAF 集成测试，或测试仅验证了 mock / 局部分支。

### 必须修改

引入明确配置：

```python
@dataclass(frozen=True)
class TopologyRunConfig:
    mode: Literal["off", "audit", "enforce"]
    lineage_id: str
    revision_id: str
    parent_revision_id: str | None
    official_xbf_path: Path
    create_if_missing: bool = True
    required_selection_ids: tuple[str, ...] = ()
```

Pipeline 初始化：

```python
if config.mode == "off":
    session = None
elif config.official_xbf_path.exists():
    session = OcafDocumentSession.open(config.official_xbf_path)
else:
    session = OcafDocumentSession.create(...)
```

禁止继续以“存在 `ocaf_path` 就自动 audit”作为唯一入口。

---

## P0-02：StableLabelIndex 并没有持久化

`label_index.py` 的注释声明：

> OCAF Tag 100/7 是权威存储，open 时从 OCAF 重建。

但实际代码只有：

```python
_by_id
_by_path
_next_tags
```

没有：

- `save_to_ocaf()`
- `load_from_ocaf()`
- index entry 属性写入
- counter 写入
- open 时重建
- schema/version 校验

`OcafDocumentSession.open()` 反而直接：

```python
session._label_index = StableLabelIndex()
session._revision_number = 1
```

这意味着重开文档后索引为空。系统只能依赖“节点执行顺序碰巧与上一次相同”来重新分配 Tag；一旦添加、删除或重排节点，Stable Label 就会漂移。

### 这是当前跨 Revision 最大的数据层阻塞项。

### 必须实现的 OCAF 索引 Schema

```text
100:7 StableIdIndex
├── 1 Counters
│   ├── 1 component_next
│   ├── 2 feature_next
│   ├── 3 selection_next
│   ├── 4 revision_next
│   └── 5 relation_next
└── 2 Entries
    └── <entry_tag>
        ├── 1 object_kind
        ├── 2 namespace
        ├── 3 object_id
        ├── 4 tag_path
        ├── 5 created_revision
        ├── 6 retired_revision
        └── 7 schema_version
```

可用 `TDataStd_AsciiString` 保存规范 JSON，但必须有 schema 验证。

### 索引 Key 必须改为复合 Key

当前 `_by_id: dict[str, IndexEntry]` 会导致：

- 两个组件都包含 `extrude_1` 时发生错误别名；
- component、feature、selection 的同名 ID 冲突。

改为：

```python
@dataclass(frozen=True)
class StableObjectKey:
    object_kind: str
    namespace: str
    object_id: str
```

示例：

```text
component | lineage             | disk
feature   | component:disk      | extrude_1
feature   | component:shaft     | extrude_1
selection | lineage             | bore_surface
relation  | feature:disk/cut_1  | target.top.modified
```

同一个业务 ID 可以在不同 namespace 中存在。

### 验收

1. Rev1 按顺序 A、B、C 分配；
2. 保存并退出；
3. Rev2 按顺序 C、A、D、B 请求；
4. A/B/C 必须恢复原 TagPath；
5. D 获取新 Tag；
6. 删除 B 后 Tag 永不复用；
7. 同名 feature 在不同 component 下不得冲突。

---

## P0-03：Pipeline 绕过事务、验证和原子发布

当前 `_run_ocaf_write_and_save()`：

```python
for batch in capture_session:
    writer.write_batch(batch)
repository.save_to(ocaf_path)
```

缺少：

- `begin_write()`
- `commit_write()`
- `abort_write()`
- `save_temp()`
- 子进程 Retrieve 验证
- `publish()`
- `close()`

此外 `OcafRepository.publish()` 当前使用：

```python
shutil.copy2(temp, official)
```

这不是严格原子发布。若复制过程中进程退出，official 可能被部分覆盖。

### 必须实现 Artifact Bundle 事务

Pipeline 不应只原子发布 XBF，而应保证：

```text
STEP
XBF
metadata.json
artifact/manifest.json
selection_resolution.json
cae_preflight.json
```

属于同一个 Revision。

推荐流程：

```text
1. 运行几何并 Capture
2. Runtime postconditions
3. 导出 STEP 到 staging
4. Geometry/STEP postcheck
5. begin OCAF transaction
6. 写 History
7. Solve selections
8. CAE preflight
9. commit transaction
10. Save XBF 到 staging
11. 子进程 Retrieve + schema/index/selection 验证
12. 生成 manifest，写入所有文件 hash
13. 关闭 OCAF 文档
14. 将 staging bundle 原子发布到 revision 目录
15. 更新 lineage HEAD 指针
```

任何一步失败：

```text
abort transaction
删除 staging
official HEAD 不变
```

### Windows 原子策略

不要直接 `copy2(temp, official)`。

建议：

```text
official_dir/
├── revisions/
│   ├── rev-000001/
│   └── rev-000002/
└── HEAD.json
```

Revision 目录先以 `.staging-uuid` 构建，验证后：

```python
os.replace(staging_dir, final_revision_dir)
os.replace(head_temp, HEAD.json)
```

若目录 replace 在 Windows 环境受限，至少保证每个正式 Revision 使用新目录，永不原地覆盖旧文件。

---

## P0-04：OCAF 在最终几何门禁之前被写入

当前 Pipeline 的顺序是：

```text
runtime postcondition
→ OCAF write/save
→ STEP export
→ geometry postcheck
→ STEP postcheck
```

这会导致：

- XBF 已保存；
- 后续 STEP 或几何检查失败；
- XBF 与正式几何状态不一致。

必须调整为：

```text
几何执行
→ STEP staging export
→ Geometry/STEP postcheck
→ OCAF transaction/write/solve/preflight
→ XBF staging save/verify
→ bundle publish
```

---

## P0-05：Pipeline 没有 Selection Solve 与 CAE preflight

`selection_service.py` 和 `cae_preflight.py` 已存在，但 `pipeline/run.py` 中没有：

```python
PersistentSelectionService
run_cae_preflight
```

调用。

因此当前所谓“CAE Binding fail-closed”只是模块单元测试，不是 Pipeline 行为。

### 必须新增 Pipeline Stage

```text
topology_history_write
topology_selection_solve
topology_semantic_validation
cae_binding_preflight
artifact_bundle_publish
```

RuntimeReport 必须记录每个 Stage。

在 `enforce` 模式下：

- required selection 非 UNIQUE/允许的 SET；
- semantic contract 失败；
- native worker crash；
- index 恢复失败；
- XBF 验证失败；

均必须阻止 STEP/XBF/metadata 正式发布。

---

## P0-06：Delete Solve 原生崩溃没有隔离

状态文档记录：

> 被选面完全删除后，`TNaming_Selector.Solve()` 发生 `0xC0000005`，Python 无法捕获。

这不能通过“skip test”或“忽略子进程 returncode”作为生产策略。

### 必须采用双层方案

#### 第一层：删除历史前置判定

若 Selection 依赖的 old NamedShape 已有确定 `DELETED` history：

```text
allow_deleted=True  → 直接返回 DELETED
allow_deleted=False → 直接返回 UNRESOLVED/REQUIRED_FAILURE
```

不要进入已知会崩溃的 `Solve()` 路径。

#### 第二层：Solve Worker 子进程隔离

所有跨进程正式 Solve 最终应由独立 worker 执行：

```text
ocaf_solve_worker
输入：
- XBF path
- selection IDs
- valid label scopes
- policy/contract

输出：
- resolution JSON
- 每个 resolved entity 的 BREP 临时文件或稳定 Label reference
- process status
```

若 worker 发生 Access Violation：

```text
status = NATIVE_CRASH
required binding → fail-closed
optional binding → warning
```

新增枚举：

```python
SelectionResolutionStatus.NATIVE_CRASH
SelectionResolutionStatus.INVALID_DOCUMENT
SelectionResolutionStatus.INVALID_POLICY
```

---

# 5. P1 级正确性问题

## P1-01：Relation Label 仍按列表位置分配

Writer 使用：

```python
Tag 1001 + rel_idx
child 1 + sub_idx
```

这不是稳定业务身份。

`relations` 的顺序依赖：

- `shape.Faces()` 枚举顺序；
- Builder history 返回顺序；
- 操作参数；
- OCCT 版本；
- Boolean 结果拓扑。

参数变化后，相同逻辑关系可能从 relation 3 移到 relation 7，导致原 Label 被写入另一个关系。

### 必须增加 Persistent Relation Index

关系 Key 必须来自稳定语义：

```python
@dataclass(frozen=True)
class RelationKey:
    feature_id: str
    source_entity_id: str
    evolution_kind: EvolutionKind
    relation_role: str
```

例如：

```text
feature=cut_bore
source_entity=base_plate.top_face
kind=MODIFIED
role=target
```

禁止把：

```text
target_face_3
edge_7
relation list index
```

作为跨 Revision Key。

### 1→N split 的建议

一个逻辑 old→N relation 应优先写入同一个 relation label：

```python
builder = TNaming_Builder(relation_label)
for new_shape in new_shapes:
    builder.Generated(old_shape, new_shape)
```

这使该 Label 表示一个集合，不把 kernel 返回顺序错误提升成分支身份。

若业务需要区分 split 后的每个分支，必须通过明确的子语义选择创建新 Selection，而不是默认使用 `sub_idx`。

---

## P1-02：`source_key` 仍含 face/edge index

例如：

```text
target_face_0
tool_face_4
face_2_inst_3
edge_1
```

这些字段目前虽然主要用于 relation ID 和审计，但 Writer 的 relation 顺序也受它影响。

必须引入：

```python
@dataclass(frozen=True)
class SourceEntityRef:
    component_id: str
    feature_id: str
    selection_id: str | None
    construction_role: str | None
    entity_kind: TopologyEntityKind
```

tracked operation 的调用方必须把已解析的稳定来源引用传入；tracked operation 不得自行把数组位置伪装成持久身份。

允许 index 的场景仅限：

```text
单次运行内部调试日志
```

不得进入：

```text
StableLabelIndex
relation_id
Selection
CAE binding
cross-revision audit key
```

---

## P1-03：Pattern history 不完整

当前 Pattern：

1. 为每个 Transform 捕获 source→copy；
2. 随后使用顺序 `BRepAlgoAPI_Fuse` 合并所有实例；
3. 没有捕获 Fuse history；
4. `fuser.IsDone()` 为 False 时没有报错；
5. 最终仍标记 `history_complete=True`。

这意味着 Transform 产生的 copy face 不一定与最终 fused result 中的 face 是同一个拓扑对象。

### 必须重写

使用带 History 的 `BOPAlgo_BOP` Fuse，并对每一步组合 history：

```text
source face
→ transformed instance face
→ fuse step 1 result face
→ fuse step 2 result face
→ final pattern face
```

只要任一阶段缺少 history：

```python
history_complete = False
proof = PARTIAL_POSTPROCESS
missing_phases += ["fuse_step_N"]
```

在 enforce 模式下，required Selection 不能依赖 `history_complete=False` 的 feature。

任何 Fuse 失败必须抛错，不允许静默保留前一步结果。

---

## P1-04：Selection 结果没有拆成真实实体集合

当前 `_classify_resolution()` 返回：

```python
resolved_shapes=(current_shape,)
```

即使 `current_shape` 是包含多个 FACE 的 Compound。

后果：

- status 可能是 SET/AMBIGUOUS；
- 但 `len(resolved_shapes)` 仍为 1；
- CAE preflight 得到错误的 entity count；
- 下游无法逐个绑定真实 FACE/EDGE。

### 必须实现

```python
def explode_entities(shape, entity_kind) -> tuple[TopoDS_Shape, ...]:
    ...
```

严格按 `SelectionPolicy.entity_kind` 遍历：

- FACE 只枚举 FACE；
- EDGE 只枚举 EDGE；
- SOLID 只枚举 SOLID。

如果 `current_shape` 自身就是目标类型，返回其自身；若为 Compound，拆分目标子实体并去重。

`SelectionResolution` 应增加：

```python
entity_kind: TopologyEntityKind
proof: ProofClass
resolved_label_entries: tuple[str, ...]
native_worker_status: str
```

---

## P1-05：Selection Policy 和 Semantic Contract 存在 fail-open

当前 `_read_policy()` / `_read_contract()`：

```python
except Exception:
    return None
```

对 required CAE Selection 来说，这是危险的：

- 持久化数据损坏；
- 解析失败；
- 系统反而按“没有 Policy”继续。

必须改为结构化错误：

```text
required selection → INVALID_POLICY，阻止 CAE
optional selection → warning，仍不得自动变为 UNIQUE
```

`expected_normal` 当前实际未实现，`_get_normal()` 永远返回 `None`，Semantic Contract 会静默跳过法向检查。

必须：

- 实现平面法向；
- Cylinder/Cone 轴线；
- 半径范围；
- curve type；
- zone/connectivity role 的可执行验证；
- 对声明但无法验证的 contract 返回 `VALIDATION_UNAVAILABLE`，不能当作通过。

---

## P1-06：CAE preflight 没有检查 allowed entity kinds

`run_cae_preflight()` 的注释声称检查：

```text
allowed_entity_kinds
cardinality
```

实际只检查 status 和 SET policy，没有读取 resolved entity kind。

必须实现：

```python
if resolution.entity_kind not in binding.allowed_entity_kinds:
    report.ok = False
```

还需要：

- 精确 resolved count；
- required/optional 区分；
- semantic contract 状态；
- proof class 必须是原生 history；
- `HEURISTIC_CANDIDATE` 永远不得通过 required gate；
- `history_complete=False` 默认不得通过 required gate。

---

## P1-07：Repository 的“原子发布”和“子进程验证”与源码不一致

`repository.py` 的模块注释声称：

- subprocess verify；
- atomic publish；
- fsync 错误结构化。

实际代码：

- `save_temp()` 后没有调用 verifier；
- `publish()` 使用 `copy2` 原地覆盖；
- `_fsync_path()` 吞掉 `OSError`；
- `close()` 吞掉异常。

下一阶段必须让实现与注释一致。禁止仅修改注释掩盖差距。

---

## P1-08：Construction Role 的 Shape 比较错误

Writer 中：

```python
last_shape is not first_shape
```

这是 Python 包装对象身份比较，不是 OCCT 拓扑等同性。

改为显式：

```python
not last_shape.IsSame(first_shape)
```

或根据需求使用 `IsEqual()`，并写测试说明二者语义差异。

---

# 6. 跨 Revision Lineage 的目标模型

## 6.1 一条 Lineage，一个演化中的 OCAF 文档

继续采用：

```text
one lineage = one logical OCAF history
```

但正式发布采用不可变 Revision Bundle：

```text
design-lineage/
├── HEAD.json
└── revisions/
    ├── 000001/
    │   ├── design.xbf
    │   ├── model.step
    │   ├── metadata.json
    │   ├── topology_manifest.json
    │   └── cae_preflight.json
    ├── 000002/
    └── 000003/
```

每个 Rev 的 XBF 是上一 Rev 打开、修改、保存后的快照。这样既保持 OCAF lineage，也保证可回滚和可审计。

## 6.2 Revision Metadata

在 `Tag 100/6 Revisions` 下记录：

```python
@dataclass(frozen=True)
class RevisionRecord:
    lineage_id: str
    revision_id: str
    revision_number: int
    parent_revision_id: str | None
    canonical_ir_hash: str
    operation_graph_hash: str
    geometry_hash: str
    xbf_hash: str
    created_at: str
    status: Literal["staging", "validated", "published", "aborted"]
```

DesignRoot Metadata 保存：

```text
schema_version
lineage_id
head_revision_id
head_revision_number
```

打开 Revision 时必须验证：

```text
request.parent_revision_id == current HEAD
```

不满足时抛出 `RevisionConflictError`，禁止覆盖。

## 6.3 Revision Session 状态机

```text
NEW
→ OPENED
→ TXN_STARTED
→ GEOMETRY_CAPTURED
→ HISTORY_WRITTEN
→ SELECTIONS_SOLVED
→ PREFLIGHT_PASSED
→ COMMITTED
→ SAVED_TEMP
→ VERIFIED
→ PUBLISHED
→ CLOSED
```

失败路径：

```text
任何阶段
→ ABORTED
→ STAGING_CLEANED
→ CLOSED
```

每个方法必须检查当前状态，禁止重复 commit、abort 后 save、publish 未验证文件等非法操作。

---

# 7. 跨 Revision History 的实施原则

这是下一阶段最难的核心。

当前 tracked operations 捕获的是：

```text
同一次 Builder 执行内部：
input old shape → operation result new shape
```

跨 Revision 需要的是：

```text
Rev1 的稳定语义实体 → Rev2 的同一语义实体
```

两者不是自动等价的。

## 7.1 禁止使用几何指纹自动建立 Rev1→Rev2 身份

面积、质心、法向只可验证和诊断，不可建立权威映射。

## 7.2 通过稳定 Feature Graph 和稳定 Source Entity 建立桥梁

每个 node 必须具有稳定：

```text
component_id
feature_id / node_id
operation type
input source refs
construction role IDs
selection IDs
```

Rev2 执行相同 feature 时：

1. 从 Rev1 OCAF 稳定 Label 读取前一 CurrentResult 与 ConstructionRoles；
2. 从 Rev2 上游 feature 的 native resolved source 获取当前 input；
3. 执行 Builder；
4. 捕获 Builder 当前操作 history；
5. 将同一稳定 relation key 写回相同 relation label；
6. 对 feature CurrentResult 写入明确的 revision bridge。

## 7.3 CurrentResult 的更新语义

初次 Revision：

```python
Generated(new_result)
```

后续 Revision：

```python
Modify(previous_current_result, new_current_result)
```

但只有在 `previous_current_result` 和 `new_current_result` 的逻辑 feature 身份相同时才允许。

不能每个 Revision 都无条件：

```python
Generated(new_result)
```

覆盖同一 CurrentResult Label。

需要新增：

```python
writer.write_feature_result(
    feature_label,
    previous_result,
    new_result,
    is_initial_revision,
)
```

并完成 OCP 行为测试，验证同一 Label 跨 transaction 更新后 Selection 能 Solve。

## 7.4 第一阶段只做受控 T2

不要直接在完整 G-CAD 上调试跨 Revision。

先构建最小受控 Fixture：

```text
Rev1：不对称实体 + 稳定顶面 Selection
Rev2：仅修改高度，保留 feature/node/source IDs
Rev3：再次修改高度
```

要求：

- 三个独立进程；
- 每次从上一正式 XBF Retrieve；
- StableLabelIndex 真正恢复；
- CurrentResult/roles/relation labels 不变；
- Selection 每次返回唯一 FACE；
- 不使用指纹兜底。

该 T2 通过后，才接入完整 G-CAD Pipeline。

---

# 8. 下一阶段 PR 规划

## PR-9A：源码一致性与 Pipeline 正确接线

### 修改文件

- `pipeline/run.py`
- `runtime/context.py`
- `topology/ocaf/document.py`
- `topology/ocaf/repository.py`
- `topology/ocaf/errors.py`

### 任务

1. 新增 `TopologyRunConfig`；
2. 使用 `OcafDocumentSession.create/open`；
3. 支持明确 `off/audit/enforce`；
4. 增加事务；
5. OCAF 写入移到几何/STEP 门禁之后；
6. 使用 staging + verify + bundle publish；
7. 所有路径 finally close；
8. Pipeline RuntimeReport 增加 topology stages；
9. 删除直接 `save_to(official_path)` 的生产调用；
10. 为现有错误构造路径写集成测试。

### 门禁

- 真实 `run_canonical_gcad(..., topology config)` 不再因空 Session 失败；
- audit 模式 OCAF 失败不发布 XBF，但 STEP 可按策略输出；
- enforce 模式任何 OCAF 失败不发布整个 bundle；
- official Revision 在注入失败后字节不变。

---

## PR-9B：StableLabelIndex 真正持久化

### 修改文件

- `label_index.py`
- `schema.py`
- `document.py`
- `repository.py`

### 任务

1. 复合 Key；
2. OCAF index schema；
3. counters 持久化；
4. open 时重建；
5. retire 不复用；
6. 全量一致性验证；
7. index migration/version；
8. component/feature/selection/relation/revision 全部进入 index。

### 门禁

完成前禁止开始多 Revision。

---

## PR-9C：Relation Identity 与 Writer v2

### 修改文件

- `models.py`
- `writer.py`
- 全部 `tracked_ops/*`

### 任务

1. 新增 `SourceEntityRef` 与 `RelationKey`；
2. 删除 relation list index 作为持久 Tag；
3. 1→N 使用逻辑 relation label；
4. CurrentResult 支持 initial/generated 与 later/modify；
5. relation metadata 写入 OCAF；
6. `history_complete` enforce gate；
7. Pattern Fuse history 完整化；
8. Boolean/Fillet/Chamfer/Unify 失败全部 fail-closed。

### 门禁

改变 `Faces()` 枚举顺序后 Stable Tag 不变。

---

## PR-10：Revision/Lineage Core

### 新增建议文件

```text
topology/ocaf/revision.py
topology/ocaf/lineage.py
topology/ocaf/manifest.py
topology/ocaf/verify_worker.py
```

### 任务

1. RevisionRecord；
2. HEAD 与 parent conflict；
3. 状态机；
4. immutable revision bundle；
5. snapshot/open/modify/save；
6. revision audit；
7. T2a 手工 kernel bridge；
8. T2b 最小 Pipeline。

### 门禁

三进程 Rev1→Rev2→Rev3 全通过。

---

## PR-11：Selection Service v2 与原生崩溃隔离

### 修改文件

- `selection_service.py`
- `models.py`
- `compat.py`
- `errors.py`
- 新增 `solve_worker.py`

### 任务

1. 按 entity kind 拆分 resolved shapes；
2. 正确 UNIQUE/SET/AMBIGUOUS；
3. policy/contract 解析 fail-closed；
4. 完成 normal/axis/radius 验证；
5. 删除前置分类；
6. subprocess Solve；
7. native crash 结构化；
8. valid label scope manifest；
9. proof class 和 history completeness gate。

### 门禁

T1、T3、T4、T5、T8。

---

## PR-12：CAE Gate 真正接入

### 修改文件

- `cae_preflight.py`
- `pipeline/run.py`
- CAE 调用层

### 任务

1. entity kind 检查；
2. cardinality 检查；
3. proof/history gate；
4. required/optional；
5. Pipeline 调用；
6. resolved shape export contract；
7. manifest 写入；
8. ANSYS/其他求解器只能接收已验证 Selection Binding。

### 门禁

required binding 任意失败，求解器启动次数必须为 0。

---

## PR-13：完整测试与清理

### 任务

1. 删除 `selectors.py`；
2. capture off/on A/B 几何；
3. Pattern instance identity；
4. Construction role 参数稳定性；
5. EDGE selection；
6. 多组件同名 feature；
7. 大模型压力；
8. OCP 版本矩阵；
9. T12 完整 Text-to-CAD E2E；
10. 文档与代码同步。

---

# 9. T0～T12 修订后的验收矩阵

| ID | 测试 | 当前 | 下一阶段验收 |
|---|---|---|---|
| T0 | 基础 XBF/TNaming | 基本通过 | 保持 |
| T1 | 单 Revision 精确 Selection | 部分 | resolved_shapes 必须为真实 FACE/EDGE |
| T2 | 三进程跨 Revision | 未完成 | Rev1→Rev2→Rev3 唯一恢复 |
| T3 | 1→N Split | 局部通过 | 关系 Label 不依赖返回顺序 |
| T4 | Delete | 原生崩溃 | 前置删除分类 + worker 隔离 |
| T5 | N→1 Unify | 未集成 | Solve 返回唯一合并实体 |
| T6 | Construction Roles | 部分 | 参数变化后 role identity 稳定 |
| T7 | 周期相似面 | 未完成 | instance ID 不依赖 face 枚举 |
| T8 | Fillet/Chamfer EDGE | 未完成 | EDGE 跨 revision 精确恢复 |
| T9 | 保存失败回滚 | 局部 | Revision Bundle 真正原子 |
| T10 | 路径 | 通过 | 保持 |
| T11 | CAE Gate | 仅模块 | Pipeline/solver 启动门禁 |
| T12 | 完整 E2E | 未完成 | IR→3 Rev→Solve→CAE→Manifest |

---

# 10. 必须新增的测试

## 10.1 Pipeline 真实入口测试

禁止只测 helper。

```python
run_canonical_gcad(
    ...,
    topology_config=TopologyRunConfig(...),
)
```

必须真实产生：

- STEP
- XBF
- Metadata
- Manifest

## 10.2 Index 重开测试

```text
进程 A：分配并保存
进程 B：不同顺序恢复并新增
进程 C：验证原路径、退休状态和 counters
```

## 10.3 Failure Injection

在以下点注入异常：

- Writer 第 N 条关系；
- Selection Solve；
- XBF Save；
- Verify worker；
- Manifest 写入；
- HEAD 更新。

每次都必须证明上一正式 Revision 未损坏。

## 10.4 Geometry A/B

同一 IR：

```text
topology_mode=off
topology_mode=audit
topology_mode=enforce
```

比较：

- volume；
- area；
- face/edge/solid count；
- bounding box；
- validity；
- STEP hash（允许非语义序列差异时使用几何规范 hash）。

---

# 11. 代码 Agent 禁止事项

1. 不得继续增加新 tracked operation，直到 PR-9A/9B 完成；
2. 不得用 face/edge index 生成持久 ID；
3. 不得使用 geometry fingerprint 自动重绑；
4. 不得在 required CAE 路径吞异常；
5. 不得忽略 native worker 非零退出码；
6. 不得把 `copy2` 描述为原子发布；
7. 不得把单元测试通过描述成 E2E 完成；
8. 不得在同一 relation label 混用不同 EvolutionKind；
9. 不得在 NativeNaming Label 写业务属性；
10. 不得让 Audit JSON 反向驱动 TNaming；
11. 不得在官方 Revision 文件上原地修改；
12. 不得在 `except Exception` 后返回 None 作为 required policy 的正常状态；
13. 不得用裸 `assert` 承担生产数据校验；
14. 不得在未验证 `history_complete` 时发布 enforce Revision；
15. 不得更新状态文档而不附真实测试命令与输出摘要。

---

# 12. 每个 PR 的交付格式

代码 Agent 每个 PR 必须输出：

```text
1. 修改文件
2. 删除文件
3. 新增/变化的公开 API
4. 数据 Schema 变化
5. OCAF Label Schema 变化
6. 兼容性影响
7. 测试命令
8. 测试数量与结果
9. 失败注入结果
10. 未解决问题
11. 是否满足本 PR Gate
```

如果 Gate 未通过，不得自动进入下一 PR。

---

# 13. 下一步的最小可执行任务

代码 Agent 收到本文档后，应从以下任务开始，而不是直接实现 T12：

## Step 1

修复 `pipeline/run.py`：

```python
_ocaf_session = OcafDocumentSession()
```

改为显式 create/open，并增加真实 Pipeline 集成测试。

## Step 2

实现 `StableLabelIndex.save_to_ocaf()` 与 `load_from_ocaf()`，修复复合 namespace。

## Step 3

把 OCAF 写入移到 Geometry/STEP postcheck 之后，增加事务、staging、verify、publish。

## Step 4

让 `run_canonical_gcad()` 真正调用 Selection Solve 与 CAE preflight。

完成以上四步后，再进入多 Revision。

---

# 14. 下一阶段 Definition of Done

下一阶段不是要求全部 T0～T12 一次完成，而是要求达到“可可信开展跨 Revision”的门槛：

1. Pipeline OCAF 真实入口可运行；
2. topology mode 可由公开 API 配置；
3. StableLabelIndex 可跨进程恢复；
4. Revision parent/head 冲突可检测；
5. official artifacts 不被部分覆盖；
6. OCAF 写入发生在几何后验门禁之后；
7. Selection 结果拆成真实实体；
8. required Policy/Contract 解析 fail-closed；
9. Delete Solve 原生崩溃被进程隔离；
10. CAE preflight 在 Pipeline 中被实际调用；
11. T2 最小三进程用例通过；
12. capture off/on 几何 A/B 不变。

达到以上条件后，系统状态可以从：

```text
模块级 PoC
```

升级为：

```text
跨 Revision 原生拓扑命名 MVP
```

在 T5～T8、T12 完成前，仍不得称为生产级 CAD-to-CAE 持久拓扑命名系统。

---

# 15. 最终审查结论

当前实现方向是正确的，尤其是：

- 底层 OCAF/XBF 不再被错误怀疑；
- Live/Audit 分离；
- 正确 TNaming Builder 语义；
- 原生 Selector；
- heuristic 降级；
- CAE fail-closed 的设计意图。

但系统目前存在明显的“模块完成度高、主链完成度低”现象。

真正的下一阶段核心不是继续证明：

```text
XBF 能不能保存 TNaming
```

而是完成：

```text
稳定业务 ID
→ 稳定 OCAF Label
→ 多 Revision 事务
→ 正确 History 更新
→ Native Solve
→ Crash Isolation
→ CAE Gate
→ Bundle 原子发布
```

代码 Agent 应优先修复 Pipeline 和 StableLabelIndex。若这两项没有完成，后续任何跨 Revision Selection 测试即使偶然通过，也不能证明系统具有稳定拓扑身份。
