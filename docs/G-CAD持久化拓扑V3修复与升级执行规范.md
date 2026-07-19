# G-CAD 持久化拓扑 V3 修复与升级执行规范

**用途**：交给代码 Agent，作为 `WYZAAACCC/text2cad_improve` 仓库持久化拓扑子系统的实施指导文档。  
**审计范围**：`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/topology/`、相关 dialect handlers、runtime/executor、pipeline、CAE bridge、CAD adapters 与 `tests/generative_cad/topology_baseline/`。  
**审计基线**：2026-07-19 获取到的 GitHub `main` 分支内容。当前访问方式未可靠暴露精确 commit SHA；代码 Agent 开工时必须先记录实际基线 SHA。  
**审计性质**：代码级静态审计。文档不把“模块存在”当作“工业环境已验证”，也不把实体数量、字符串稳定或测试绿灯当作拓扑身份正确。

---

## 0. 给代码 Agent 的最高优先级指令

本次升级不是“继续给剩余 handler 加几个语义名字”，而是重建持久化拓扑的可信基础。必须严格遵循以下顺序：

1. **先冻结旧行为并添加失败测试**，再改代码。
2. **先统一身份模型、状态机、绑定验证和事务边界**，再扩展 handler 覆盖。
3. **所有拓扑关键路径默认 fail-closed**。不能解析就返回 `unresolved`/`ambiguous`，绝不猜一个面。
4. **Persistent ID、运行时 locator、几何 fingerprint、证明等级必须分离**，禁止相互冒充。
5. **OCCT history 必须来自实际生成最终几何的同一个 builder**，不能另跑一个“旁路 builder”来制造历史。
6. **Sidecar 恢复后所有实体必须是未绑定状态**；完成严格重绑定前，任何实体都不得返回 `exact`。
7. **CAE、接触、制造、跨 CAD 导入禁止使用模糊自动选择**。
8. **不允许 `except Exception: pass`、静默降级、未知 quality/policy 默认放行**。
9. 每一个阶段都必须独立提交、运行相应测试并更新 `docs/STATUS.md`；不得一次性大改后再补测试。

### 0.1 本次升级的最终定义

升级完成后，“某持久拓扑引用解析成功”必须同时证明：

- 身份描述符合法且与 key 一致；
- 生命周期允许解析；
- lineage 闭包一致；
- owner body 的当前 revision 与绑定记录一致；
- locator 能在当前真实 B-Rep 中找到实体；
- 实体类型、方向、位置和必要几何证据吻合；
- 消费者的类型、基数和证明等级策略全部满足。

只满足“Registry 中有一条 active 记录”不再算解析成功。

---

# 1. 当前持久化拓扑的真实架构

当前实现大致由以下部分组成：

```text
Stable-ID definitions
  topology/ids.py
        ↓
Entity lifecycle / lineage records
  topology/models.py
        ↓
Central registry
  topology/registry.py
        ↓
Runtime binding
  topology/locator.py
  topology/shape_binding.py
        ↓
History / semantic naming
  topology/history_wrappers.py
  topology/semantic_naming.py
        ↓
Operation integration
  dialects/*/handlers.py
  dialects/results.py
  dialects/executor.py
        ↓
Persistence / downstream use
  topology/persistence.py
  topology/cae_bridge.py
  topology/cad_adapters.py
```

设计意图是正确的：将永久身份、谱系、运行时子形状定位、制品 sidecar 和 CAE 引用分离。但当前代码中这些层次仍有交叉和互相代替，导致系统看起来“已经有 PersistentTopoId、Registry、Locator、History、Sidecar”，实际却不能稳定证明同一个工程实体在重建后仍对应正确的 OCCT 子形状。

---

# 2. 必须建立的核心不变量

以下不变量是本次升级的硬性验收标准。

## I-01：身份不依赖瞬时 B-Rep 枚举

Persistent ID 的描述符中禁止出现：

- `face_0`、`edge_12`、`side_face_3`；
- `IndexedMap` position；
- Python `id()`；
- `TopoDS_Shape.HashCode()`；
- 当前遍历次序；
- 随机 UUID；
- 仅由包围盒排序得到的序号。

运行时 index 只能存在于 `RuntimeTopoLocator`，且 locator 只能在特定 owner body revision 内有效。

## I-02：身份、状态、绑定、证明彼此独立

必须拆成四个概念：

1. **Identity**：这个工程实体是谁。
2. **Lifecycle**：它仍 active、已 superseded 还是 deleted。
3. **Binding**：它当前是否绑定到某个真实 B-Rep 子形状。
4. **Proof**：当前绑定由何种证据得到，可信等级是什么。

不得继续用一个 `status` 和一个 `resolution_method` 同时表示以上四层语义。

## I-03：1:1 修改保留逻辑身份

对于 OCCT `Modified(old) -> new` 且能够证明为一对一时：

- PersistentTopoKey 不变；
- entity revision/generation 增加；
- locator、owner revision、fingerprint、proof 更新；
- provenance 记录本次 operation。

不得把 `result_entity_key` 字符串写进一个伪 locator。

## I-04：Split/Merge 不得静默替换

- split：旧实体转为 `superseded`，记录多个终端后代；旧引用只有在消费者允许 set expansion 时才可解析为集合。
- merge：多个旧实体转为 `superseded`，生成一个新实体；不得任意继承其中一个旧 ID。
- deleted：不得有 locator，不得通过 fingerprint“找一个相似面”复活。

## I-05：Sidecar 是身份/谱系证明，不是运行时绑定缓存

Sidecar 可以保存身份、lineage、语义、合同、算法版本和 artifact hash；不得保存或信任跨进程 `IndexedMap` position。读取 Sidecar 后必须进入 `needs_rebind`，不能直接 `exact`。

## I-06：Topology-critical operation 原子提交

一个拓扑关键 operation 只有同时满足以下条件才可提交：

- 几何结果有效；
- TopologyDelta 合法且完整；
- result entity 已获得严格 locator；
- topology contract 满足；
- registry integrity 通过；
- geometry object 和 topology state 能一起提交。

任一失败时，两者都不得留下半提交状态。

## I-07：Exact 只代表可验证的精确证据

以下情况才允许称为 exact：

- 同一 OCCT builder 的 `Generated/Modified/IsDeleted` 历史；
- 可证明的一一 construction semantic，例如拉伸顶面/底面、由稳定 sketch edge 生成的侧面；
- Sidecar 重建后，严格 locator + owner revision + identity evidence 全部校验通过。

“只有一个候选”“Registry 中 active”“指纹距离最小”均不得直接升级为 exact。

## I-08：歧义必须外显

面对完全对称、近对称或证据不足的候选：

- 返回 `ambiguous`；
- 给出候选集合和评分证据；
- 高风险消费者拒绝；
- 不得通过排序或 first-match 自动选择。

## I-09：持久性只能存在于同一文档谱系

“跨重建稳定”必须有前提：新版本继承旧版本的 document lineage 和 stable feature IDs。

两个彼此独立、仅几何相似但没有共同 revision lineage 的文档，不可能无条件证明实体是同一个。此时最多做迁移/匹配，不能声称天然保持身份。

---

# 3. 当前问题、根因与影响总表

严重度定义：

- **P0**：可能把错误面当成正确面，或形成假 exact，必须先修。
- **P1**：破坏稳定性、完整性或端到端闭环。
- **P2**：覆盖、性能、工程化与跨后端增强。

| 编号 | 严重度 | 位置 | 问题 | 根因 | 直接影响 |
|---|---|---|---|---|---|
| T-001 | P0 | `ids.py` | v1/v2 两套 ID 语义并存 | 未定义统一的身份域模型与迁移策略 | adapter、sidecar、registry 互不兼容 |
| T-002 | P0 | `ids.py` | v2 hash 包含 document/node 等易变字段 | 把构建位置描述当作长期逻辑身份 | 节点重命名、文档 clone、特征重排导致 ID 全变 |
| T-003 | P0 | `models.py` | active 可无 locator；exact 可无证据 | 模型缺少跨字段不变量 | 假 exact、CAE 错绑 |
| T-004 | P0 | `registry.resolve()` | 非严格 resolve 对 active 直接返回 exact | 把逻辑状态当成实际几何绑定 | Sidecar 恢复或 locator 丢失后仍被判成功 |
| T-005 | P0 | `registry.resolve()` | 严格路径调用错误的 locator reconstruct，并吞异常 | 接口边界未统一，广义异常捕获 | 预期验证没有实际执行 |
| T-006 | P0 | `shape_binding.py` | IndexedMap position 被当作稳定定位，hash 验证弱 | 未定义 body revision 与 locator 生命周期 | 重建后 locator 可指向另一子形状 |
| T-007 | P0 | handlers / transaction | 几何与拓扑分开提交，拓扑失败 non-fatal | 为兼容旧 handler 使用 side-channel | 几何成功但拓扑损坏仍返回成功 |
| T-008 | P0 | `cae_bridge.py` | CAE gate 不传 ObjectStore/BindingService | 门禁只查 registry 状态 | 载荷/约束可能落到错误面或空引用 |
| T-009 | P0 | `persistence.py` | restore 去除 locator 却保留 active，测试期待 exact | 未区分 persisted identity 与 runtime binding | 持久化后 fail-open |
| T-010 | P0 | `matcher.py` | 所有候选成本为 0，单候选直接 exact | matcher 只是占位框架 | 无几何证据也可能宣称精确 |
| T-011 | P0 | `policies.py` | 未知 policy/quality 可能按低等级处理 | 字符串枚举与默认 rank | 拼写错误可放宽安全要求 |
| T-012 | P1 | `registry.py` | index、generation、shape index 部分未维护 | Registry 缺少单一状态机和索引重建策略 | overwrite/restore 后索引漂移 |
| T-013 | P1 | `registry.apply_delta()` | unknown source/key 只记录事件；`unchanged` 未处理 | Phase 1 lenient 逻辑未升级 | delta 不完整也成功 |
| T-014 | P1 | `semantic_naming.py` | 大量按遍历顺序命名 | 后验观察替代构造语义和 kernel history | 参数改变后身份漂移 |
| T-015 | P1 | `history_wrappers.py` | history wrapper 与真实 handler 构建路径并行 | 未采用统一 topology-aware builder | 历史不一定对应最终 shape |
| T-016 | P1 | boolean integration | 声称 history-aware，实际仍调用后验 `name_boolean_faces` | history 未传入/未消费 | boolean split/merge 谱系不可信 |
| T-017 | P1 | `fingerprint.py` | 几何特征粗糙、坐标依赖、部分公式错误 | 缺少局部坐标与拓扑邻接模型 | fallback 对旋转、平移、裁剪面不稳定 |
| T-018 | P1 | `persistence.py` | sidecar schema/version/contract/hash 不统一 | 每阶段独立补字段，没有正式 artifact schema | 无法可靠复现和验证 |
| T-019 | P1 | `contracts.py` / OperationSpec | 合同存在但多数未连接，缺失仅 warning | topology 被视为可选 side-channel | 不能保证每项 operation 完整报告拓扑 |
| T-020 | P1 | tests | 测试验证数量/字符串，不验证真实子形状连续性 | 缺少跨 revision oracle | 绿灯无法证明拓扑正确 |
| T-021 | P2 | handlers | pocket/rib/fillet/chamfer/shell/loft/sweep/pattern 等未完整接入 | 规划按容易程度扩展，基础尚未加固 | 生产覆盖有限 |
| T-022 | P2 | CAD adapters | v1 parser、模糊名称匹配、关键面非 100% 门禁 | 跨后端 proof 模型不足 | SW/NX 映射可误配 |

---

# 4. 深度问题分析

## 4.1 Persistent ID v1/v2 的根本问题

### 当前行为

`PersistentTopoId` v1 用冒号拼接字段：

```text
gct:v1:<document[:12]>:<component>:<root>:<producer>:<type>:<role>[:branch]
```

问题包括：

- `document_id` 被截断，存在碰撞可能；
- 字段没有转义，role 中的冒号会破坏解析；
- validator 只拒绝纯数字或裸 `face/edge/vertex`，仍允许 `side_face_3`；
- ID 包含 producer node ID，node rename 会改变身份。

v2 改成内容 hash：

```text
gct2_<base64url(sha256(canonical-json))>
```

这解决了截断与分隔符，但没有解决“哪些字段应该决定身份”。它仍 hash `document_id`、`producer_node_id` 等易变字段，所以只是把不稳定描述变成了不可读的不稳定 hash。

另外，v2 文档声称完整 descriptor 会保存在 record/sidecar，但 `TopologyEntityRecord` 没有完整保存这些字段，hash 又不可逆，导致只剩 key 时无法恢复身份描述。

### 修复要求

引入正式的 V3 身份模型：

```python
class TopologyIdentityDescriptorV3(BaseModel):
    scheme: Literal["gcad_topo_v3"]
    document_lineage_id: str
    component_stable_id: str
    feature_stable_id: str
    entity_type: TopologyEntityType
    semantic_path: tuple[str, ...]
    source_entity_keys: tuple[str, ...] = ()
    branch_key: str | None = None
    algorithm_version: str
```

必须区分：

- `document_lineage_id`：同一设计文档的版本谱系；clone 可选择保留或新建。
- `document_revision_id`：某次具体构建版本，不进入 Persistent Key。
- `feature_stable_id`：在 revision 间继承，不能等同于易变 node ID。
- `producer_node_id`：仅作为本次构建 provenance，不决定长期身份。
- `semantic_path`：结构化 tokens，不是任意字符串。
- `branch_key`：只在一源多结果时使用，必须来自稳定分支证据。

Key 计算使用 canonical JSON，并明确排序、Unicode、浮点和空字段规则：

```text
gct3_<base64url(sha256(identity_descriptor_canonical_json))>
```

### 迁移规则

- reader 支持 v1/v2/v3；writer 只写 v3。
- v1 可解析字段，但 document ID 已截断，标记为 `legacy_unverified`。
- v2 key 若 sidecar 中没有完整 descriptor，**不可逆**。不得伪造 descriptor；必须通过旧 artifact + 当前重建做迁移匹配，成功后产生 migration proof，否则保持 unresolved。
- CAD adapter 禁止再用 `PersistentTopoId.from_compact()` 解析任意新 key。

---

## 4.2 `TopologyEntityRecord` 允许非法状态

当前模型把 lifecycle、binding 和 proof 压在以下字段里：

- `status`
- `resolution_method`
- `current_locator: dict | None`
- `confidence`
- `evidence: list[dict]`

这允许：

- `status=active`、locator=None；
- `resolution_method=kernel_generated`、但没有 history evidence；
- deleted/superseded 仍携带相互矛盾的 descendants；
- face record 保存 edge locator；
- confidence 超出 0–1；
- persisted record 假装 runtime-bound。

### 目标模型

```python
class EntityLifecycle(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"

class BindingState(str, Enum):
    UNBOUND = "unbound"
    BOUND = "bound"
    STALE = "stale"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"

class ProofClass(str, Enum):
    EXACT_GENERATED_HISTORY = "exact_generated_history"
    EXACT_MODIFIED_HISTORY = "exact_modified_history"
    DETERMINISTIC_CONSTRUCTION = "deterministic_construction"
    VERIFIED_REBIND_UNIQUE = "verified_rebind_unique"
    FINGERPRINT_CANDIDATE = "fingerprint_candidate"
    AMBIGUOUS_SET = "ambiguous_set"
    NONE = "none"
```

建议拆分为：

```python
class TopologyIdentityRecord(BaseModel): ...      # 可持久化
class TopologyEntityState(BaseModel): ...         # 可持久化 lifecycle/lineage/revision
class RuntimeTopologyBinding(BaseModel): ...      # 仅运行时
class TopologyProof(BaseModel): ...                # 可持久化证据摘要 + runtime evidence
```

`TopologyEntityRecordV3` 组合以上对象，添加 model validator，至少强制：

- active + bound 才可带 current locator；
- superseded/deleted 不得带 current locator；
- exact history proof 必须含 operation ID、builder 类型、source/result mapping；
- `entity_type == locator.entity_type`；
- locator owner 与 record current owner 一致；
- confidence 严格 `[0,1]`，但安全决策不得只依赖 confidence；
- 所有 list/dict 使用 `default_factory`，不使用可变默认值。

---

## 4.3 Registry 把“记录存在”误判为“真实实体存在”

### 当前失败模式

`resolve()` 在没有 `object_store` 与 `binding_service` 时，只要 record 是 active，就能返回 exact。严格分支中又存在接口调用错误和广义异常吞噬，因此即使调用方提供了 binding service，部分验证也可能被跳过。

这使以下场景均可能假成功：

- Sidecar 恢复后 locator 已被删除；
- owner body 已被新的 handle 或新 shape 替换；
- IndexedMap position 仍存在但指向另一面；
- entity type 不匹配；
- content hash 无法计算，被返回为 `unknown`；
- binding verification 抛异常，被静默忽略。

### 目标解析接口

废弃可选参数式非严格解析，改成显式 context 与 request：

```python
class TopologyResolutionContext(BaseModel):
    object_store: RuntimeObjectStore
    binding_service: ShapeBindingService
    document_revision_id: str
    body_revision_provider: BodyRevisionProvider
    allow_fingerprint_fallback: bool = False

class TopologyResolutionRequest(BaseModel):
    persistent_id: str
    expected_entity_type: TopologyEntityType | None
    cardinality: CardinalityConstraint
    allowed_proof_classes: frozenset[ProofClass]
    allow_set_expansion: bool = False
    consumer: ConsumerKind

class TopologyResolutionV3(BaseModel):
    status: ResolutionStatus
    resolved_entities: list[ResolvedTopologyEntity]
    proof: ResolutionProofReport
```

### 解析顺序

```text
1. 验证 key 与 descriptor
2. 查 record，不存在 → unresolved
3. lifecycle=deleted → deleted
4. lifecycle=superseded → 递归求 terminal descendants
5. 强制 type/cardinality/set policy
6. 检查 binding state=bound
7. 校验 owner handle 和 body revision
8. 重建 IndexedMap，严格 resolve locator
9. 校验 shape 类型、orientation、location、必要 fingerprint
10. 校验证明等级是否满足 consumer policy
11. 返回实际子形状/受控 handle + 完整 proof
```

任何步骤异常都必须转成结构化 failure，不允许 `pass`。

### Lineage 闭包

当前只返回直接 descendants。V3 必须计算递归终端闭包：

- 跳过中间 superseded 节点；
- deleted terminal 不进入可解析集合；
- 发现 cycle 立即 integrity error；
- 多 terminal 只有 request 允许 set expansion 才返回 set；
- terminal 中有 unresolved/ambiguous 时，整体结果不能称 exact。

---

## 4.4 Locator 只是临时地址，当前验证不足

`RuntimeTopoLocator` 基于：

- owner body handle；
- entity type；
- `TopExp.MapShapes` 的 position；
- orientation/location hash；
- owner shape content hash。

IndexedMap position 对同一 shape 实例内定位有用，但不保证跨重建稳定。因此必须明确：

> Locator 是当前 body revision 内的临时地址，PersistentTopoKey 才是逻辑身份。

### 当前问题

- 只完整支持 face/edge，type 声明更宽；
- `_build_indexed_map()` 任何异常都返回空 map；
- owner content hash 基于弱/不稳定 hash，并可能返回 `unknown`；
- `occt_shape_hash` 被写为 0；
- fingerprint verification 尚未真正实现；
- 没有缓存/版本化 BodyTopologyMaps；
- 没有 owner body revision token；
- locator 的 orientation/location 没有形成强校验闭环。

### V3 绑定设计

```python
class RuntimeTopoLocatorV3(BaseModel):
    owner_body_handle_id: str
    owner_body_revision_id: str
    entity_type: TopologyEntityType
    indexed_map_position: int
    orientation: str
    location_digest: str
    local_shape_digest: str | None
    map_algorithm: Literal["occt_indexed_map_v1"]
```

新增：

```python
class BodyTopologyMapsV3:
    owner_body_handle_id
    owner_body_revision_id
    maps_by_type
    artifact_geometry_digest
    runtime_shape_digest
```

### Hash/Revision 原则

不要把 `TopoDS_Shape.HashCode()` 宣称为跨进程 canonical B-Rep hash。建议同时使用两类 token：

1. **Runtime body revision ID**：ObjectStore 每次 put/replace 时生成的单调/内容版本，保证本进程内严格失效。
2. **Artifact geometry digest**：对最终 BREP/STEP 文件字节或明确版本化的几何序列化结果计算 SHA-256，用于 sidecar 与 artifact 绑定。

如采用 BRepTools 序列化计算 shape digest，必须记录 OCCT 版本与 digest algorithm；不得承诺跨 OCCT 版本字节完全稳定。

### 必须删除的行为

- 计算失败返回字符串 `unknown` 并继续；
- 找不到 map 时返回空字典而不报告原因；
- fallback 到 Python `id(shape)`；
- locator verification 抛异常后跳过验证。

---

## 4.5 几何与拓扑事务不是原子的

当前 `TopologyTransaction` 只 clone/commit Registry。handler 通常先产生或存储 geometry，再用 side-channel 注册拓扑；拓扑失败被追加 warning，几何仍成功。

这会产生三种裂脑状态：

1. ObjectStore 有新 body，Registry 仍是旧状态；
2. Registry 已部分登记，最终 body 构建失败；
3. STEP 导出成功，但 topology sidecar 缺失/不完整。

### 目标：`GeometryTopologyTransaction`

```python
with ctx.geometry_topology_transaction(node, op_spec) as tx:
    result_shape, exact_history = builder.build(...)
    provisional_handle = tx.stage_geometry(result_shape)
    delta = topology_adapter.build_delta(
        source_bindings=...,
        result_shape=result_shape,
        history=exact_history,
        provisional_handle=provisional_handle,
    )
    tx.stage_topology(delta)
    tx.build_and_verify_bindings()
    tx.validate_contract(op_spec.topology_contract)
    tx.validate_geometry_health()
    tx.commit()
```

事务提交前必须使用 staged ObjectStore view 做 locator 验证。commit 必须一次性更新：

- ObjectStore；
- node outputs；
- TopologyRegistry；
- topology event log；
- body revision map；
- operation result proof。

如果现有 ObjectStore 不支持事务，先实现最小 provisional namespace + commit/rollback，而不是继续依赖调用顺序。

---

## 4.6 Semantic naming 当前大量依赖后验枚举

`semantic_naming.py` 同时承担了三种不同任务：

1. 确定性 primitive construction semantics；
2. OCCT history 的结果命名；
3. 无 history 时的后验几何猜测。

这三者必须拆开。

### 典型问题

- cylinder cap 用全局 `center.z > 0`，对旋转/平移对象不成立；
- extrude cap 按世界轴符号，不按 extrusion vector 投影；
- side face 使用 `side_face_i`；
- revolve/loft/sweep 的 cap 或 lateral 依赖 traversal order；
- boolean face 使用 surface type + index；
- chamfer 用固定面积阈值，受模型尺度影响；
- hole naming 观察 cutter，而不是 boolean result 的真实生成/修改面；
- `build_entity_records_from_delta()` 可能为 source ID 伪造当前 result provenance。

### 重构要求

拆为：

```text
topology/construction_semantics.py
  只实现由建模输入可严格推导的语义

topology/history_adapters/
  按 OCCT builder 读取 Generated/Modified/IsDeleted

topology/rebind_matcher/
  只做受约束 fallback，不创建原始身份
```

生产路径禁止调用通用 `name_boolean_faces()`、`_make_fallback_relation()` 来满足拓扑合同。它们最多保留为 debug/inspection 工具，返回的 proof 必须是低等级且不可进入 CAE/制造。

---

## 4.7 OCCT History Wrapper 没有绑定到实际 builder

History 的价值来自：**它记录了产生最终结果的那个 OCCT builder 的 source→result 映射**。

当前 wrapper 的主要问题：

- wrapper 可能单独执行 builder，而 handler 仍用 CadQuery 高层 API 产生最终几何；
- source key 常为 `edge_i/face_i`；
- 某些 wrapper 只收 generated，忽略 modified/unchanged/deleted；
- 失败时返回 `None`，测试也允许 `None`；
- extrude/revolve 只登记侧面，不完整登记 caps/body/edges；
- 同一 source 生成多个面时可能产生相同 Persistent ID；
- boolean handler 的 history_result 没真正进入 delta 构建。

### 目标架构：Topology-aware builder adapter

每类操作建立 adapter：

```python
class TopologyAwareBuildResult(BaseModel):
    shape: Any
    history: ExactKernelHistory
    diagnostics: BuilderDiagnostics
    source_binding_snapshot: SourceBindingSnapshot
```

```python
class ExtrudeTopologyBuilder:
    def build(profile, direction, source_entities) -> TopologyAwareBuildResult: ...
```

关键要求：

- handler 必须使用 adapter 返回的 `shape` 作为最终 shape；
- adapter 接收 source PersistentTopoKey，而不是运行时 `edge_i`；
- source sketch element 必须有 stable element ID；
- history query 不得二次重建；
- API 不可用时明确返回 `history_unavailable`，不得假装 exact；
- `Generated`、`Modified`、`IsDeleted`、必要 `unchanged` 全部收集；
- 多结果分支必须生成稳定 branch key，无法稳定区分时标 ambiguous。

---

## 4.8 Fingerprint/Matcher 目前只是占位，不可用于安全 fallback

当前 matcher 的所有 cost 为 0；一个候选直接 exact，多个候选通常 ambiguous。Fingerprint 又存在：

- 仅 face，缺 edge；
- area tolerance 量纲不正确；
- plane normal 量化过粗；
- cylinder axis/radius 推导错误或对裁剪面不成立；
- 全局 centroid/bbox 对 placement 敏感；
- adjacency/convexity 未真正计算；
- 没有全局一一匹配；
- `allowed_lineage_relations` 未使用。

### 正确定位

Fingerprint 只能用于：

- Sidecar 后的重绑定候选排序；
- kernel history 缺失时的受约束辅助；
- 发现歧义并拒绝。

不能用于：

- 复活 deleted entity；
- 绕过 lineage；
- 生成第一个版本的 Persistent ID；
- 将低证据结果宣称为 kernel exact。

### V3 Fingerprint

至少包括：

- entity type；
- surface/curve type；
- 局部坐标系中的面积/长度、质心、主轴、包围盒；
- 平面 normal、圆柱/圆锥/球/环面明确参数；
- boundary loop 数量及每个 loop 的长度/曲线类型签名；
- 邻接实体的结构化 signature；
- convex/concave relation；
- source feature/lineage 约束；
- tolerance 和算法版本。

局部坐标系必须来自 component/body construction frame，不得依赖 assembly 世界坐标。

### V3 Matcher

流程：

```text
provenance/lineage hard filter
  ↓
entity type + owner/component hard filter
  ↓
候选图构建
  ↓
多维 normalized cost
  ↓
全局 one-to-one assignment（如 Hungarian）
  ↓
absolute threshold + ambiguity margin
  ↓
verified_unique / ambiguous / unresolved
```

只有评分绝对阈值和第二名间隔同时满足，才能返回 `verified_rebind_unique`；仍不得叫 kernel exact。

---

## 4.9 Sidecar V2 不是完整的 artifact proof

当前 sidecar：

- 写 `gcad_topology_v2`，部分 adapter/validator 仍期待 v1；
- registry hash 只基于 entities list，且可能受插入顺序影响；
- contract hash 留空；
- named sets 由 semantic role 前缀临时分组，不是实际 NamedTopologySet；
- lineage 同时从 ancestor 和 descendant 导出，可能重复；
- reader 尝试读未真正写出的 `node_index/event_count`；
- 没有完整 v2 descriptor；
- 只验证内部 registry hash，不强制验证预期 sidecar SHA、STEP/BREP hash、graph hash、document lineage；
- restore 后不执行真正 rebind。

### Sidecar V3 schema

建议：

```json
{
  "schema": "gcad_topology_v3",
  "writer": {...},
  "document": {
    "document_lineage_id": "...",
    "document_revision_id": "...",
    "canonical_graph_hash": "sha256:..."
  },
  "artifact": {
    "geometry_path_hint": "...",
    "geometry_sha256": "sha256:...",
    "format": "STEP",
    "units": "mm"
  },
  "algorithms": {
    "identity": "3.0.0",
    "history": "...",
    "fingerprint": "...",
    "binding": "...",
    "occt": "...",
    "cadquery": "..."
  },
  "contracts": [...],
  "identities": [...],
  "entity_states": [...],
  "lineage_relations": [...],
  "named_sets": [...],
  "degradations": [...],
  "unresolved": [...],
  "canonical_payload_sha256": "sha256:..."
}
```

要求：

- canonical JSON 序列化；
- identities 按 key 排序；
- relations 使用唯一 relation ID 并排序；
- hash 覆盖除自身 hash 字段外的整个 payload；
- 写入前验证 artifact 文件 SHA；
- 读取时由调用方传入 expected graph/artifact/document lineage 并强制匹配；
- 不持久化 runtime locator；
- restore 后 binding state 全部为 `unbound`；
- rebind 产生独立 `TopologyRebindReport`，不能静默改写历史证明。

---

## 4.10 CAE Bridge 当前没有真正解析到面

`resolve_named_set_to_faces()` 名称暗示返回可用于 CAE 的 face，但实际主要处理 persistent IDs 与逻辑 resolution，并未严格保证得到当前 mesh-ready 子形状。

主要问题：

- 调 `registry.resolve(pid)` 时没有 binding context；
- `required_resolution` 未完整落实；
- 空集合可能得到不合理的最佳质量；
- entity type/cardinality/owner revision 未严格检查；
- set expansion 对消费者区别不够；
- 未返回实际子形状或受控 face handles；
- CAE pipeline 尚未把 gate 作为强制前置证明。

### V3 CAE API

```python
class ResolvedNamedTopologySet(BaseModel):
    name: str
    entity_type: Literal["face", "edge", "vertex", "body"]
    entities: list[ResolvedTopologyEntity]
    proof_report_id: str
    cardinality: int
    consumer_policy: str
```

```python
resolve_named_set(
    named_set,
    registry,
    resolution_context,
    cae_request,
) -> ResolvedNamedTopologySet
```

强制：

- 空集合失败；
- 类型不匹配失败；
- exact 与 exact_or_set 按配置执行；
- contact/manufacturing 不能接受 fingerprint-only；
- 每个实体必须返回当前 body revision 的实际 subshape/handle；
- CAE runner 必须接收 preflight proof ID，缺失则拒绝启动 ANSYS。

---

# 5. 目标架构

```text
Canonical IR revision lineage
  ├── document_lineage_id
  ├── document_revision_id
  ├── stable_feature_id
  └── stable sketch element IDs
            ↓
Topology-aware operation builder
  ├── actual result shape
  ├── exact OCCT history from same builder
  └── construction semantics
            ↓
TopologyDeltaV3 + ContractProof
            ↓
GeometryTopologyTransaction
  ├── provisional ObjectStore revision
  ├── typed locators
  ├── Registry staged state
  ├── integrity/contract validation
  └── atomic commit
            ↓
TopologyRegistryV3
  ├── identity table
  ├── lifecycle/state table
  ├── lineage relation graph
  ├── runtime binding table
  └── named sets
            ↓
Strict resolver
  ├── lifecycle closure
  ├── current B-Rep verification
  ├── constrained fallback matching
  └── consumer policy
            ↓
Sidecar V3 / CAE / SW-NX / inspection
```

---

# 6. V3 数据模型规范

## 6.1 稳定 Feature ID

Canonical node 必须新增或明确继承：

```python
stable_feature_id: str
revision_node_id: str  # 当前图中的 node.id，可变化
```

规则：

- 编辑已有 feature 时 stable ID 保留；
- 在前面插入新 feature 不改变后续 feature stable ID；
- LLM 每次从零生成且无 previous document 时，只能创建新 lineage；
- revision merge/clone 必须显式选择是否继承 lineage。

Sketch element 同样需要 stable ID，例如：

```text
profile/main/edge/left
profile/main/arc/fillet_top_left
```

禁止在 handler 内通过 `enumerate(edges)` 临时创造长期 element ID。

## 6.2 Identity descriptor

必须完整持久化，key 仅是 descriptor 的索引，不是唯一可读信息。

建议字段：

- scheme/algorithm version；
- document lineage；
- component stable ID；
- feature stable ID；
- entity type；
- semantic path；
- stable source entity keys；
- branch key；
- optional design intent label。

## 6.3 Entity lifecycle/state

```python
class TopologyEntityStateV3(BaseModel):
    persistent_id: str
    lifecycle: EntityLifecycle
    entity_revision: int
    current_owner_body_logical_id: str | None
    last_producer_node_id: str
    last_document_revision_id: str
    ancestor_ids: tuple[str, ...]
    descendant_ids: tuple[str, ...]
```

`owner_body_handle_id` 属于 runtime binding，不应作为持久 identity state 的唯一 owner。

## 6.4 Relation

```python
class TopologyRelationV3(BaseModel):
    relation_id: str
    operation_stable_id: str
    operation_revision_node_id: str
    kind: RelationKind
    source_ids: tuple[str, ...]
    result_ids: tuple[str, ...]
    proof: TopologyProof
```

强制 cardinality：

| kind | source | result |
|---|---:|---:|
| primitive | 0 | >=1 |
| generated | >=0/按 operation 定义 | >=1 |
| modified | 1 | 1 |
| unchanged | 1 | 1（通常同一 ID） |
| deleted | >=1 | 0 |
| split | 1 | >=2 |
| merged | >=2 | 1 |
| selected | >=1 | 0，且不改变 lifecycle |

## 6.5 Delta

`TopologyDeltaV3` 必须包含：

- operation stable/revision ID；
- source body revisions；
- result provisional body revisions；
- relations；
- complete/partial 标记；
- operation contract hash；
- history provider 类型与版本；
- unresolved items 及 severity；
- builder diagnostics；
- transaction ID。

对于 `topology_mode=required` 的 operation，`partial` 或 unresolved 必须阻断 commit。

## 6.6 NamedTopologySet

新增：

- stable set ID；
- explicit members；
- expected type；
- min/max/exact cardinality；
- set expansion policy；
- required proof classes；
- owner component/body scope；
- consumer purpose；
- revision/migration policy。

禁止 sidecar 通过 role prefix 自动编造集合。

---

# 7. 各类 CAD 操作的持久命名规则

## 7.1 Primitive box/cylinder

### Box

在 body-local frame 中定义：

- `face/x_min`、`face/x_max`；
- `face/y_min`、`face/y_max`；
- `face/z_min`、`face/z_max`；
- edges 由相交面语义组合，例如 `edge/x_min/y_max`。

变换后仍使用 local semantics，不按世界坐标重新命名。

### Cylinder

- `face/cap/start`、`face/cap/end` 基于 axis parameter；
- `face/lateral`；
- `edge/rim/start`、`edge/rim/end`。

不得用 `center.z > 0` 判定 cap。

## 7.2 Extrude

- source profile face/edges 必须有 stable IDs；
- side face identity 绑定到 source sketch edge；
- cap start/end 绑定 extrusion parameter 0/1；
- extrusion vector 允许任意方向；
- 多 wire/inner loop 必须区分外环与内环 stable element；
- taper/draft 造成 split 时必须用 history 产生 split relation。

## 7.3 Revolve

- lateral faces由 stable profile edge 生成；
- full 360° 与 partial revolve 的 seam/caps 明确区分；
- axis intersection、零长度或退化 edge 必须形成诊断；
- 同一 source edge 生成多个面时，用稳定几何/历史分支 token，无法区分则 ambiguous。

## 7.4 Boolean union/cut/intersect

必须使用真实 BRepAlgo history：

- 对每个输入 persistent face/edge 查询 Modified/Generated/IsDeleted；
- 1→1 为 modified；
- 1→N 为 split；
- N→1 为 merge；
- 删除明确记录；
- 新的交界面 identity 由 operation stable ID + 排序后的 source identities + relation semantics 构造；
- 不能按最终 result face 遍历顺序命名。

## 7.5 Hole/pocket/boss/rib

将其视为带工程语义的 boolean feature：

- tool geometry 有自己的临时 construction identities；
- 产品中的 hole wall/rim/bottom 必须绑定到 boolean result 的 generated/modified entities；
- tool-only face 不应直接登记为最终产品 active face；
- through/blind/counterbore/countersink 使用结构化 semantic path；
- entry/exit 基于 feature direction 与 source support face，不按世界坐标。

## 7.6 Fillet/Chamfer

- 选择输入必须是 persistent edges；
- 新 fillet/chamfer face 从 selected edge history 得到；
- 相邻 faces 通常为 modified，并保留原 ID；
- selected edge 可能 deleted/superseded，按 history 处理；
- 不允许用面积阈值或遍历序号识别新面。

## 7.7 Shell/Hollow

- removed face：deleted；
- offset counterpart：由 source face generated/modified；
- thickness side faces：由 source boundary edges generated；
- inner/outer orientation 必须基于 offset direction 和 body-local frame；
- shell builder 失败不得 `pass`。

## 7.8 Loft/Sweep/Helix sweep

- section/profile/path elements必须有 stable IDs；
- cap 与 section endpoints 绑定；
- side surfaces 绑定相应 section edge/path span；
- topology 改变造成多个结果时显式 split；
- 若 OCCT 无法提供稳定 history，标记部分支持，禁止为 CAE 关键路径提供 exact。

## 7.9 Pattern

每个实例使用稳定 lattice key：

- linear：`instance/(i,j,k)`；
- circular：`instance/angular_index`，同时持久化 pattern origin/direction semantics；
- count 增减时，保留仍存在坐标实例的 identity；
- 不按结果 compound 遍历顺序编号。

## 7.10 Transform / Assembly placement

纯刚体 transform：

- persistent identity 不变；
- binding owner revision/location digest 更新；
- fingerprint 使用 body-local 坐标，避免 transform 后全变；
- assembly occurrence identity 与 part definition identity 分层，不得混为一个 key。

---

# 8. 文件级实施清单

## 8.1 `topology/ids.py`

- 新增 V3 descriptor/key/canonical serializer。
- 增加结构化 semantic path validator。
- 增加禁止 runtime-index token 的严格规则和测试。
- 添加 v1/v2 migration reader；v1/v2 writer deprecated。
- 不再在 CAD adapter 中解析 hash key。

## 8.2 `topology/models.py`

- 拆 lifecycle、binding、proof。
- typed locator/fingerprint/evidence，移除裸 `dict`。
- 添加 relation cardinality model validators。
- 添加 Delta completeness/contract fields。
- 添加 NamedTopologySet cardinality/proof policy。

## 8.3 `runtime/object_store.py` 或相应实现

- 每个 object handle 增加 revision ID。
- replace/put 后 revision 必须变化。
- 提供 provisional/staged object view。
- 提供 shape unwrap 的统一接口。

## 8.4 `topology/locator.py`、`shape_binding.py`

- 实现 V3 locator。
- 支持需要的 face/edge/vertex/solid 类型。
- 构建失败返回 typed error，不返回空 map 冒充正常。
- 使用 owner revision 严格失效。
- 验证 orientation/location/local digest。
- 缓存 key 包含 owner handle + revision + entity type。

## 8.5 `topology/registry.py`

- 重写为显式状态机。
- 删除非严格 `resolve()`；或保留仅名为 `inspect_record()`，不得返回 exact。
- 新增 strict `resolve(request, context)`。
- 实现 terminal lineage closure、cycle detection。
- 所有 unknown source/result 变成 delta validation error。
- 实现 `unchanged`。
- 统一更新所有 indices；提供 `rebuild_indices()` 与双向完整性检查。
- overwrite 前清理旧索引，禁止重复项。
- clone/replace/export/restore 覆盖全部必要状态。
- 增加 lock 或明确单线程事务约束；并发修改使用 registry revision/optimistic check。

## 8.6 `topology/transaction.py`

- 升级为 geometry+topology 联合事务。
- commit 前运行 contract、integrity、binding、geometry health。
- 禁止拓扑 required operation 的 warning-only 失败。

## 8.7 `topology/contracts.py`、`dialects/operation.py`

`OperationSpec` 新增强类型字段：

```python
topology_mode: Literal["forbidden", "optional", "required"]
topology_contract: TopologyContractV3 | None
```

合同包含：

- expected relation types；
- expected semantic outputs；
- cardinality；
- history requirement；
- completeness；
- allowed degradation；
- contract hash。

所有 geometry-producing operation 必须显式声明 mode；不能靠 `None` 猜测。

## 8.8 `topology/history_wrappers.py`

- 改造成 topology-aware builder adapters。
- source 参数使用 persistent IDs 与实际 source subshapes 的映射。
- 返回完整 typed history，不返回 `None`。
- builder 不可用时返回明确 error/unsupported。
- 删除任何与最终 handler shape 不同源的旁路构建。

## 8.9 `topology/semantic_naming.py`

- 拆分 construction semantics 与 debug heuristics。
- 删除生产路径中的 index-based role。
- 修正 local frame/axis semantics。
- 禁止通过 role 文本猜 entity type。
- `build_entity_records_from_delta()` 不得伪造 source record。

## 8.10 `topology/fingerprint.py`、`matcher.py`

- 修复 Pydantic 可变默认值。
- 完整实现 face/edge fingerprints。
- 引入 local frame、boundary、adjacency。
- 实现 normalized cost 与全局 assignment。
- 加 absolute threshold、ambiguity margin。
- matcher 结果 proof 固定为 rebind/fallback，不冒充 kernel history。

## 8.11 `topology/policies.py`

- 使用 Enum 与 exhaustive match。
- unknown consumer/quality 一律 deny。
- proof quality 从 proof object 推导，不由调用者自由填写。
- 分别定义 inspection、CAE load、CAE contact、manufacturing 等策略。

## 8.12 `topology/persistence.py`

- writer 只写 V3 canonical sidecar。
- hash 覆盖完整 payload。
- 写真实 contracts/named sets/relations。
- 与 STEP/BREP SHA、graph hash、document lineage 绑定。
- restore 后全部 unbound。
- `rebind_after_restore()` 必须真正执行 matcher/binding 或删除此伪接口，改为明确 orchestration service。

## 8.13 `topology/cae_bridge.py`

- 要求 strict resolution context。
- 返回实际 resolved subshapes/handles。
- 强制 type/cardinality/proof。
- empty set 拒绝。
- 输出不可伪造的 preflight proof ID。

## 8.14 `topology/cad_adapters.py`

- 去除 v1-only parser。
- per-entity proof，而非 80% aggregate 即通过。
- critical named sets 要求 100% 映射。
- fuzzy matching 只能用于交互提示，不自动提交 CAE/制造映射。
- adapter 结果区分 exact/verified/ambiguous/unresolved。

## 8.15 `pipeline/run.py` / metadata / artifact

- geometry 与 sidecar 都成功后才返回最终 artifact success。
- 自动写 sidecar V3。
- metadata 写入 sidecar SHA、geometry SHA、algorithm versions、topology validation report。
- topology required 且 sidecar 失败时，整个 build fail。

## 8.16 各 dialect handlers

按第 7 节规则分批升级。禁止先广泛接入弱 heuristic，再回头修基础。

---

# 9. 分阶段实施计划

## Phase 0：基线冻结与失败用例

### 任务

- 记录 git SHA、Python/CadQuery/OCP 版本。
- 运行全部现有 topology tests 与 E2E，保存报告。
- 为下列错误行为添加 characterization tests，并先确保它们能暴露当前问题：
  - active 无 locator 不得 exact；
  - sidecar restore 后不得 exact；
  - matcher 单候选且无成本不得 exact；
  - v2 ID 进入 SW adapter 不得被静默丢弃；
  - unknown delta source 必须失败；
  - `unchanged` 必须被处理；
  - boolean history 必须来自最终 builder；
  - topology failure 对 required operation 必须阻断 geometry commit。

### 验收

- 形成 `docs/topology_v3_baseline.md`。
- 新测试在旧代码上按预期失败，而不是被 skip/return 吃掉。

## Phase 1：V3 身份与数据模型

### 任务

- 实现 descriptor/key、stable feature ID contract、typed state/proof/models。
- 添加 v1/v2 reader 与 migration status。
- 更新所有 model tests。

### 验收

- 相同 descriptor 输出 byte-identical key；
- node revision ID 变化不影响 key；
- feature stable ID 变化会改变 key；
- runtime index token 被拒绝；
- 所有非法状态无法构造。

## Phase 2：Registry 状态机与严格解析

### 任务

- 实现 relation cardinality、delta validation、lineage closure。
- 修复全部 indices、clone/replace/restore。
- strict resolver 上线；旧非严格 resolver 禁止进入生产。

### 验收

- deleted/superseded/ambiguous/unbound 状态严格返回；
- cycle、dangling、重复 index、错误双向 lineage 被检测；
- unknown source/result 使事务失败；
- restore 后全是 unbound。

## Phase 3：运行时 binding 与联合事务

### 任务

- ObjectStore revisions；
- locator V3；
- ShapeBindingService strict verification；
- GeometryTopologyTransaction。

### 验收

- 替换 owner body 后旧 locator 必然 stale；
- locator position 指向错误类型时拒绝；
- 人为交换两个 locator 时 mutation test 失败；
- topology commit 失败后 ObjectStore 无新结果。

## Phase 4：核心 exact-history builders

优先顺序：

1. primitives；
2. extrude；
3. revolve；
4. boolean union/cut/intersect。

### 验收

- 使用同一 builder 产生 geometry/history；
- caps、sides、modified/deleted/split/merge 完整；
- 不含 index-based identity；
- parameter perturbation 与 feature insertion 测试通过。

## Phase 5：工程特征覆盖

依次升级：

- hole/pocket/boss/rib；
- fillet/chamfer；
- shell；
- loft/sweep/helix；
- pattern/transform。

每个 operation 必须先定义 contract，再实现 builder 与测试。

## Phase 6：Fingerprint 与重绑定

### 任务

- 实现局部 fingerprint、候选图、global assignment；
- sidecar + rebuild 的 rebind orchestrator；
- ambiguity/unresolved 输出。

### 验收

- 对称模型不会自动选第一个；
- rigid transform 不影响 local fingerprint；
- 参数小扰动可在有充分证据时 verified rebind；
- 超过阈值或歧义时拒绝。

## Phase 7：Sidecar V3 与标准 pipeline

### 任务

- canonical sidecar；
- geometry/artifact binding；
- metadata integration；
- migration report。

### 验收

- 同一输入/环境重复构建 sidecar byte-identical；
- 修改一个 sidecar 字段必然 hash mismatch；
- 用 A 模型 sidecar 配 B 模型 STEP 必然拒绝；
- restore 前后不会出现假 exact。

## Phase 8：CAE 与跨 CAD 消费者

### 任务

- CAE strict gate；
- proof ID 贯穿 solve；
- SW/NX per-entity mapping proof；
- critical sets 100% gate。

### 验收

- 任一关键 face unresolved/ambiguous，ANSYS 不启动；
- contact pair 类型/基数错误时拒绝；
- SW/NX fuzzy result 不可自动升级为制造可用。

## Phase 9：硬化、性能、文档

### 任务

- benchmark map building、history capture、sidecar size；
- cache 按 body revision；
- property-based/randomized tests；
- CI matrix；
- 移除 deprecated paths；
- 更新架构文档、STATUS、migration guide。

---

# 10. 必须新增的测试体系

## 10.1 不再以“实体数量正确”为核心 oracle

3083 个 entity 只能说明登记了很多记录，不能证明它们是正确的同一工程实体。新的 oracle 必须比较：

- construction source identity；
- OCCT history relation；
- 实际 current subshape；
- local geometric/topological invariants；
- consumer policy result。

## 10.2 Revision perturbation matrix

每个受支持 operation 至少覆盖：

1. 尺寸参数变化；
2. 上游插入无关 feature；
3. revision node rename；
4. document clone（继承/不继承 lineage 两种）；
5. boolean split/merge；
6. fillet/chamfer 前后；
7. rigid transform/assembly placement；
8. sidecar persist→新进程 rebuild→rebind；
9. 对称/近对称歧义；
10. feature 删除与恢复；
11. pattern count 增减；
12. 多 body/多 component。

## 10.3 Mutation tests

主动篡改：

- locator position；
- owner body revision；
- entity type；
- orientation/location digest；
- descriptor 与 key；
- lineage source/result；
- sidecar graph hash；
- geometry artifact hash；
- contract hash；
- proof class。

所有篡改都必须 fail-closed。

## 10.4 测试纪律

禁止：

```python
try:
    ...
except Exception:
    return
```

只有环境确实缺 OCP/SW/NX 时才可 `pytest.skip()`，并写明原因。核心 OCP 能力存在但代码失败时必须 fail。

## 10.5 建议测试文件

```text
tests/generative_cad/topology_v3/
  test_identity_v3.py
  test_model_invariants.py
  test_registry_state_machine.py
  test_strict_resolution.py
  test_geometry_topology_transaction.py
  test_shape_binding_revision.py
  test_history_extrude.py
  test_history_revolve.py
  test_history_boolean.py
  test_secondary_features.py
  test_fingerprint_local_frame.py
  test_global_matcher.py
  test_sidecar_v3.py
  test_sidecar_migration.py
  test_cae_preflight_strict.py
  test_cross_backend_proof.py
  test_revision_perturbations.py
  test_topology_mutations.py
```

旧 `topology_baseline` 测试可暂保留用于兼容观察，但不再作为 V3 correctness 的主要证明。

---

# 11. 必须修改或删除的错误测试预期

现有测试中以下思想必须纠正：

- active record 无 locator 仍 `exact`；
- sidecar round-trip 后无 locator 仍 `exact`；
- matcher 只有一个候选就 `exact`；
- history wrapper 返回 `None` 也算通过；
- loft/sweep 异常后直接 return；
- CAE gate 使用没有真实 locator 的 active records 仍通过；
- 只用 v1 ID 验证 SW/NX adapter；
- 只比较 role 字符串/实体数，不比较实际子形状。

这些不是“兼容行为”，而是应被移除的错误安全语义。

---

# 12. 规划中未完成内容及正确重排

仓库 `docs/STATUS.md` 已明确列出以下未完成项：

- sketch_extrude 的 pocket/rib/fillet/chamfer；
- axisymmetric bore/groove/slot；
- shell；
- loft/sweep；
- composition pattern/transform；
- OperationSpec 与 TopologyContract 连接；
- standard pipeline 自动生成 sidecar；
- CAE bridge 接入 FEA pipeline；
- OCP history-aware handlers；
- SW/NX 真实测试；
- fingerprint fallback matching。

原计划把“集成更多 naming helper”列为短期低风险，但从本次审计看，这个顺序不应继续采用。正确顺序是：

```text
身份模型与 fail-closed
  → 严格 binding/transaction
  → 同一 builder 的 exact history
  → 核心操作
  → 剩余 handler
  → fallback matcher
  → sidecar/CAE/SW-NX
```

原因是：在身份、绑定和事务语义错误时继续扩展 handler，会把不可靠记录扩散到更多操作，未来迁移成本更高。

---

# 13. 禁止项清单

代码 Agent 在实施中不得：

1. 用 `face_i/edge_i` 作为 Persistent ID descriptor 的一部分。
2. 用全局坐标正负判断任意朝向零件的工程语义。
3. 用 `id(shape)` 或 `HashCode()` 作为跨重建身份。
4. 把 `IndexedMap` position 持久化后直接复用。
5. 让 active+无 locator 返回 exact。
6. 让 fingerprint 单候选直接 exact。
7. 捕获 topology 异常后 `pass` 或只 warning（required path）。
8. 由 role 字符串猜 entity type。
9. 为 source entity 伪造 result body 的 provenance。
10. 在不是最终几何 builder 的对象上采集 history。
11. 用 role 前缀自动构造 CAE named set。
12. 用 fuzzy common-word match 自动映射 CAE/制造关键面。
13. 对未知 policy/quality 使用宽松默认值。
14. 用实体数量或测试绿灯宣称持久拓扑已正确。
15. 在没有 previous lineage 的独立文档之间声称 identity 天然保持。

---

# 14. 代码 Agent 的执行方式

每个 Phase 使用以下循环：

```text
1. 写出本阶段假设和不变量
2. 添加失败测试
3. 做最小必要实现
4. 运行本阶段单测
5. 运行全部 topology tests
6. 运行相关 CAD E2E
7. 输出变更文件、风险、未覆盖项
8. 更新 STATUS/架构文档
9. 独立 commit
```

每次提交信息建议：

```text
topology-v3(p0): add identity descriptor and invariant tests
topology-v3(p1): enforce strict registry resolution
topology-v3(p2): add geometry-topology atomic transaction
...
```

不要一次跨多个 Phase。若发现现有高层 CadQuery API 无法提供实际 builder history，必须停在该 operation，改成 OCP builder adapter；不得用后验枚举临时填充 exact contract。

---

# 15. Definition of Done

只有全部满足以下项目，才能宣称持久化拓扑 V3 完成。

## 身份

- [ ] writer 只生成 v3 key；reader 有明确 v1/v2 migration。
- [ ] Persistent descriptor 不含 runtime index、node revision ID、随机值。
- [ ] stable feature/sketch element IDs 能跨 revision 继承。
- [ ] descriptor 与 key 可验证一致。

## 状态与 Registry

- [ ] lifecycle、binding、proof 分离。
- [ ] 非法状态无法构造。
- [ ] split/merge/deleted/unchanged 的状态机完整。
- [ ] recursive lineage closure、cycle detection、index consistency 完整。
- [ ] 不存在生产用 non-strict exact resolve。

## Binding

- [ ] locator 带 owner body revision。
- [ ] owner 替换会使 locator 明确 stale。
- [ ] strict resolve 返回实际 current subshape/handle。
- [ ] 所有异常转为结构化 failure，无静默跳过。

## History 与 handlers

- [ ] 核心操作使用生成最终 shape 的同一个 topology-aware builder。
- [ ] primitive/extrude/revolve/boolean 完整通过 perturbation tests。
- [ ] topology-critical handlers 有合同并强制完整 delta。
- [ ] 不存在 production index-based semantic naming。

## Transaction

- [ ] geometry 与 topology 原子提交。
- [ ] 拓扑失败不会留下 geometry-only success。
- [ ] standard pipeline 的 sidecar/metadata/artifact 一致提交。

## Fallback

- [ ] fingerprint 使用 local frame、boundary、adjacency。
- [ ] matcher 实现 hard constraints、global assignment、阈值和歧义。
- [ ] 对称场景不会自动选取。
- [ ] fallback proof 不冒充 kernel history。

## Persistence

- [ ] Sidecar V3 canonical、deterministic、完整 hash。
- [ ] 与 graph 和 geometry artifact 绑定。
- [ ] restore 后全部 unbound，重绑定前不能 exact。
- [ ] migration 不可逆时明确 unresolved，不伪造身份。

## Downstream

- [ ] CAE gate 使用 strict binding context。
- [ ] 空集合、类型、基数、proof 不满足均拒绝。
- [ ] ANSYS solve 必须携带有效 topology preflight proof。
- [ ] SW/NX critical mapping 要求逐实体通过。

## 测试

- [ ] revision perturbation matrix 完整。
- [ ] mutation tests 完整。
- [ ] 无 catch-and-return 假测试。
- [ ] 同环境重复构建 sidecar byte-identical。
- [ ] 核心确定性/history-covered 情况 identity 保持率为 100%；不能保持时必须显式 ambiguous/unresolved，禁止错误匹配。

---

# 16. 最终架构判断

当前持久化拓扑的价值不在于已有多少个 entity 或 naming helper，而在于它已经具备 Registry、lineage、history、binding、sidecar、CAE bridge 等正确的模块雏形。真正的问题是：

- 这些模块的**可信边界尚未收紧**；
- identity 与 locator 尚未彻底分离；
- exact 与 heuristic 尚未严格分级；
- geometry 与 topology 尚未原子化；
- persistence 与 runtime binding 尚未分离；
- 测试尚未证明“同一个工程实体仍绑定到正确 B-Rep 子形状”。

因此，本次升级的核心不是增加更多规则，而是建立一条可以被证明的链：

```text
稳定设计身份
  + 同一 builder 的准确演化历史
  + 当前 body revision 的严格子形状绑定
  + 显式谱系与歧义
  + 原子事务
  + 与几何制品绑定的 Sidecar 证明
  + 消费者特定的 fail-closed 门禁
```

当这条链完整后，Text2CAD 后续的自动有限元、参数迭代、CAD 重新生成、SolidWorks/NX 导入才有可靠基础。否则任何“自动载荷落面”“自动接触”“自动网格控制”都可能建立在一个看似稳定、实际漂移的面引用之上。

---

# 附录 A：首批必须加入的失败测试名称

```text
test_active_unbound_entity_never_resolves_exact
test_sidecar_restore_requires_rebind
test_single_fingerprint_candidate_is_not_kernel_exact
test_unknown_delta_source_is_fatal
test_unchanged_relation_is_applied
test_registry_reindex_after_superseded_overwrite
test_strict_resolve_rejects_stale_owner_revision
test_strict_resolve_rejects_wrong_entity_type
test_locator_swap_is_detected
test_required_topology_failure_rolls_back_geometry
test_v2_legacy_key_requires_descriptor_for_migration
test_boolean_history_comes_from_final_builder
test_split_resolves_only_when_consumer_allows_set
test_recursive_terminal_lineage_closure
test_symmetric_candidates_remain_ambiguous
test_sidecar_geometry_hash_mismatch_is_fatal
test_empty_cae_named_set_is_fatal
test_cae_preflight_requires_real_bound_faces
test_unknown_consumer_policy_is_denied
test_runtime_index_token_rejected_in_identity_descriptor
```

# 附录 B：首批代码搜索与清理规则

建议在 CI 中加入定向静态检查：

```text
拓扑生产代码中禁止：
  except Exception: pass
  semantic_role=f"...{i}..."
  face_{index}
  edge_{index}
  id(shape)
  status == "active" → direct exact
  _QUALITY_RANK.get(..., 0)
```

注意：测试 fixture、debug 输出或运行时 locator 日志可能合法包含 index，规则需要限定目录与 AST 上下文，不能简单全仓误杀。

# 附录 C：建议新增文档

```text
docs/topology_v3_architecture.md
docs/topology_v3_migration.md
docs/topology_v3_consumer_policies.md
docs/topology_v3_test_matrix.md
docs/topology_v3_baseline.md
```

