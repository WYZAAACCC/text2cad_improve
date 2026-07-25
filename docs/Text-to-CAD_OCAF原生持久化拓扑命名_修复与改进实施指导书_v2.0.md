# Text-to-CAD / OCAF 原生持久化拓扑命名 - 修复与改进实施指导书 v2.0

供代码 Agent 直接执行的工程实施合同。

| 字段 | 值 |

| --- | --- |

| 目标仓库 | WYZAAACCC/text2cad_improve |

| 固定代码基线 | 0b349da7b24b0f0f234c90b2ec5b6cc2c0129097 |

| 目标环境 | Python 3.11.9 / CadQuery 2.7.0 / OCP 7.8.1.1 / OCCT 7.8.1 |

| 编制日期 | 2026-07-25 |



## 0. 文档控制

| 字段 | 值 | 说明 |

| --- | --- | --- |

| 文档版本 | v2.0 | 在 v1.0 指导书与 v1.1 实施状态报告基础上，按当前源码和上游内核源码重新校正 |

| 实现目标 | 原生 OCAF/TNaming 持久化拓扑命名 | 必须实现 Select -> Save -> 进程重启 -> Open -> Revision Update -> Solve |

| 优先路线 | 不升级优先 | 先修复仓库数据模型、Label 生命周期、History 写入和测试；版本升级仅作为后置兼容项目 |

| 权威拓扑事实 | 原实际 OCCT Builder 的 History | 禁止第二次重放、Face 序号、最近邻、数组顺序作为权威身份 |

| 失败策略 | Fail Closed | 关键选择无法解析、History 不完整或 XBF 自检失败时阻断 Revision/CAE |

| 文档适用者 | 代码 Agent、Reviewer、CAD/CAE 架构负责人 | 代码 Agent 逐项执行；Reviewer 按验收矩阵签收 |



## 目录

- 1. 任务目标、成功定义与非目标

- 2. 固定基线与上游能力结论

- 3. 当前实现的根因诊断

- 4. 目标系统架构与核心不变量

- 5. OCAF 文档树与稳定 Label 方案

- 6. 数据模型重构

- 7. History 捕获与操作覆盖

- 8. TNaming Writer 的正确实现

- 9. Selector 持久化与求解服务

- 10. Revision 生命周期与事务

- 11. CAD-to-CAE 绑定策略

- 12. 错误模型、证据与可观测性

- 13. 文件级实施清单

- 14. 分阶段 PR 计划

- 15. 测试矩阵与验收门禁

- 16. ABI Smoke Test 与诊断脚本

- 17. 迁移、兼容与回滚

- 18. 禁止事项

- 19. 最终交付清单

- 附录 A. 关键代码骨架

- 附录 B. 来源与版本证据

## 1. 任务目标、成功定义与非目标

本任务的目标是将当前 PoC 改造成正确使用 OCAF/TNaming 原生机制的持久化拓扑命名子系统，并为自动有限元提供失败关闭的区域绑定。

```text
自然语言 / Canonical IR
  -> 稳定 document_id / component_id / node_id / selection_id
  -> 原实际 OCCT Builder 单次执行
  -> 同一 Builder 的 Generated / Modified / Deleted History
  -> LiveEvolutionBatch（保留真实 TopoDS_Shape）
  -> 稳定 OCAF Feature Label 写入 TNaming_NamedShape Evolution
  -> 独立 Selection Label 上 TNaming_Selector.Select
  -> Commit + 原子 XBF 保存 + 重开自检
  -> 新进程打开同一 Lineage Document
  -> 在同一稳定 Feature Label 上执行下一 Revision 更新
  -> 写入本次 old -> new Evolution
  -> TNaming_Selector.Solve
  -> EXACT_ONE / SET / DELETED / AMBIGUOUS / UNRESOLVED
  -> CAE Preflight
  -> 允许求解或失败关闭
```

| ID | 目标 | 验收条件 |

| --- | --- | --- |

| S-01 | 最小 Selector 持久化 | Select 后保存 XBF，独立进程重开同一精确 Label Entry，可读回 TNaming_NamedShape 与 TNaming_Naming |

| S-02 | 跨 Revision 求解 | 在同一 OCAF 文档谱系中更新特征后，Selector.Solve() 将旧引用解析到新拓扑 |

| S-03 | 真实 History | 每条 GENERATED/MODIFIED/DELETED 关系包含真实 old_shape 与 new_shape(s)，Writer 不得以 result_shape 代替 |

| S-04 | 稳定 Label | 同一 component_id/node_id/selection_id 在所有 Revision 中使用相同 Label Entry |

| S-05 | 事务一致性 | 几何、命名、选择、CAE 预检与 XBF 自检处于同一 Revision 提交流程，失败时 Abort |

| S-06 | 无静默误绑定 | 一对多、合并、删除、歧义或无法证明时返回结构化状态，不自动选择最近面 |

| S-07 | Clean 可追踪 | 拓扑关键路径上的 UnifySameDomain 必须使用其 History；若目标 OCP 未暴露 History，则该路径不得宣称 EXACT |

| S-08 | CAE 门禁 | 所有必需边界条件在当前 Revision 解析成功并满足语义断言后，才允许网格/求解 |

| S-09 | 版本可重复 | 依赖精确锁定，并记录 Python/CadQuery/OCP/OCCT 版本、平台和 ABI smoke 结果 |



- 本阶段不解决任意无特征身份的两个独立 STEP 文件之间的通用语义匹配。

- 本阶段不以几何指纹、Face 序号、质心最近或数组位置替代原生拓扑命名。

- 本阶段不要求立即升级到 OCCT 7.9+，也不要求重写完整 C++ OCAF 层。

- 本阶段不保证所有几何变化都可唯一继承；合法结果可以是集合、歧义、删除或 unresolved。

- 本阶段不把导入型 STEP 的无历史拓扑自动声明为 EXACT；导入模型只能进入明确的 EXTERNAL/HEURISTIC 证明等级。

## 2. 固定基线与上游能力结论

| 项目 | 固定值 | 实施要求 |

| --- | --- | --- |

| 仓库提交 | 0b349da7b24b0f0f234c90b2ec5b6cc2c0129097 | 所有修改先基于该提交建立补丁，不以 main 浮动内容为基线 |

| Python | 3.11.9 | 与状态报告一致 |

| CadQuery | 2.7.0 | 高层 clean() 丢弃 UnifySameDomain History |

| OCP | 7.8.1.1 | 模块配置包含 TDF/TNaming/BinMNaming/BinXCAF/ShapeUpgrade；具体重载必须 smoke test |

| OCCT | 7.8.1 | 原生 TNaming、BinMNaming、OCAF transaction、UnifySameDomain History 均存在 |

| 存储格式 | BinXCAF / XBF | 必须注册 BinXCAFDrivers 并检查 Save/Open 状态 |



| 分支 | smoke 结果 | 动作 |

| --- | --- | --- |

| A | hasattr(unifier, "History") == True | 直接实现 tracked_clean() 并提取 BRepTools_History |

| B | 类存在但 History 不可调用/返回类型异常 | 建立最小复现；优先做 OCP 生成配置的极小补丁或独立小扩展，只暴露 History |

| C | 目标 wheel 确实无 History | 拓扑关键路径暂时禁用 clean/unify，或将其标记为非 EXACT 并阻断需要持久引用的 Revision；禁止用 Fingerprint 宣称修复 |



## 3. 当前实现的根因诊断

| ID | 缺陷 | 当前行为 | 后果 |

| --- | --- | --- | --- |

| RC-01 | EvolutionRelation 丢弃真实形状 | 模型只存 old_shape_evidence/new_shape_count；遍历到的 _gen_shape/_mod_shape 随即丢弃 | Writer 无法调用正确的 Generated(old,new)/Modify(old,new)/Delete(old) |

| RC-02 | Writer 演化写错 | DELETED/MODIFIED/GENERATED/PRIMITIVE 多数都对 batch.result_shape 调用 Generated 或 Delete | OCAF 内不存在真实的子形状演化图 |

| RC-03 | Feature Label 随机分配 | ensure_feature_label() 每次 NewChild() | 同一 Node 跨 Revision 没有稳定持久地址 |

| RC-04 | Component get_or_create 不实现查找 | 循环子 Label 后仍无条件 NewChild() | Component 身份不可持续 |

| RC-05 | 新建/重开 Design Root 不一致 | 新建使用 doc.Main().NewChild()，重开逻辑将根设为 doc.Main() | 恢复时 Label 树偏移一级 |

| RC-06 | 每个 Revision 新建文档 | run_canonical_gcad(ocaf_path) 创建新的 OcafDocumentSession | OCAF 无法沿同一 Data Framework 更新命名 |

| RC-07 | 错误的持久化判据 | 将 IsIdentified() 失败视为 Selector 丢失 | IsIdentified 仅判断是否已有被识别特征，不是 Selector 保存测试 |

| RC-08 | OCAF 失败降级为 warning | Pipeline 保存失败后继续执行 | 产物可能无有效命名证据却被标记成功 |

| RC-09 | OCAF 在最终几何门禁前保存 | XBF 保存发生在 geometry_postcheck 前 | 失败几何可能污染命名谱系 |

| RC-10 | 全局 staging 桥 | tracked_ops 写全局 dict，再由 CaptureSession 拉取 | 内存泄漏、并发冲突、生命周期不清晰 |

| RC-11 | Fillet 使用 Edge Index | 运行时按 0-based Edge 顺序选择 | Edge 顺序不是持久身份，参数变化后可能选错 |

| RC-12 | FaceSelector 被视为替代方案 | 面积/质心/曲面类型用于权威恢复 | 对对称、阵列、分裂、合并、大参数变化不可靠 |



## 4. 目标系统架构与核心不变量

```text
TopologyLineageService
├─ DependencyFingerprint / ABI Probe
├─ OcafLineageDocument
│  ├─ StableLabelIndex
│  ├─ RevisionTransaction
│  ├─ AtomicXbfStore
│  └─ ReopenSelfCheck
├─ TopologyCaptureRuntime
│  ├─ BuilderAdapter[boolean, prism, revolve, fillet, chamfer, clean, ...]
│  ├─ LiveEvolutionBatch
│  └─ AuditProjection
├─ TNamingEvolutionWriter
│  ├─ FeatureResultWriter
│  └─ EvolutionRelationWriter
├─ PersistentSelectionService
│  ├─ Select
│  ├─ Solve
│  ├─ SelectionPolicy
│  └─ SemanticPostcheck
└─ CaeBindingRegistry
   ├─ BoundaryConditionBinding
   ├─ RegionResolution
   └─ PreflightGate
```

| ID | 不变量 | 说明 |

| --- | --- | --- |

| I-01 | 一个模型谱系一个 OCAF Data Framework | Revision 不是独立新文档；它是同一文档谱系的一次事务更新。 |

| I-02 | 稳定业务 ID 对应稳定 Label Entry | document_id/component_id/node_id/selection_id 的 Label 地址不得因重建变化。 |

| I-03 | 一次几何执行对应一次 History | 不得为了拿 History 再执行第二次 Builder。 |

| I-04 | 真实 Shape 只在进程内，审计证据可序列化 | Live 模型保留 TopoDS_Shape；Audit 模型才转换为 JSON。 |

| I-05 | 一个 TNaming_Builder 只使用一种 Evolution | 遵守 OCCT Builder 合同。 |

| I-06 | Selection Label 独占 | Selector.Select 会清理该 Label 的 Attribute，因此不得与结果或元数据共用。 |

| I-07 | 未证明即非 EXACT | History 缺失、Post-process 未覆盖或导入模型必须降级且触发相应门禁。 |

| I-08 | 歧义是合法结果，误绑定不是 | 不允许启发式挑一个面后继续。 |

| I-09 | 提交前重开自检 | 保存成功不等于可恢复；必须独立打开临时 XBF 并验证关键 Attribute。 |

| I-10 | CAE 只绑定 Selection ID | 不得绑定 face index、STEP entity order 或当前数组位置。 |



## 5. OCAF 文档树与稳定 Label 方案

```text
0:1  Main
└─ 0:1:1  DesignRoot                       [固定 Tag: 1]
   ├─ Metadata                             [固定 Tag: 10]
   │  ├─ SchemaVersion
   │  ├─ document_id
   │  ├─ dependency_fingerprint
   │  └─ current_revision_id
   ├─ Components                           [固定 Tag: 20]
   │  └─ <component stable label>
   │     ├─ Metadata                       [Tag: 1]
   │     ├─ Features                       [Tag: 2]
   │     │  └─ <node stable label>
   │     │     ├─ Result                   [Tag: 1, TNaming_NamedShape]
   │     │     ├─ Evolutions               [Tag: 2]
   │     │     │  └─ <phase/relation labels>
   │     │     └─ Metadata                 [Tag: 3]
   │     └─ Selections                     [Tag: 3]
   │        └─ <selection stable label>
   │           ├─ TNaming_NamedShape(SELECTED)
   │           ├─ TNaming_Naming
   │           └─ Selection metadata
   ├─ Assembly                             [固定 Tag: 30]
   ├─ CAE Bindings                         [固定 Tag: 40]
   └─ Revisions                            [固定 Tag: 50]
      └─ <revision audit labels>
```

- 为固定系统分区使用预定义整数 Tag，例如 DesignRoot=1、Metadata=10、Components=20。

- 业务对象 Label 不直接使用 Python hash()，因为进程间不稳定。

- 推荐使用“持久映射表 + 分配器”：首次出现 ID 时分配新 Tag，同时在 OCAF 中保存 id、kind、label_entry；后续通过映射恢复。

- 映射表必须属于同一 OCAF 文档，不得只存在于旁路 JSON；JSON 可以作为镜像和审计，不是权威。

- 重开时必须从固定 DesignRoot 读取索引，验证每个 Entry 可恢复，且 Label 上的业务 ID 一致。

- 同一 node_id 被删除时 Label 不删除；写入删除 Evolution 并保留身份历史。

```python
class StableLabelIndex:
    def get_or_create(self, *, kind: ObjectKind, object_id: str) -> TDF_Label: ...
    def resolve(self, *, kind: ObjectKind, object_id: str) -> TDF_Label: ...
    def entry_of(self, label: TDF_Label) -> str: ...
    def label_from_entry(self, entry: str, *, create: bool = False) -> TDF_Label: ...
```

## 6. 数据模型重构

```python
@dataclass(frozen=True)
class LiveEvolutionRelation:
    relation_id: str
    kind: EvolutionKind
    old_shape: TopoDS_Shape | None
    new_shapes: tuple[TopoDS_Shape, ...]
    ...

@dataclass(frozen=True)
class EvolutionRelationAudit:
    relation_id: str
    kind: EvolutionKind
    old_shape_evidence: dict
    new_shape_evidence: tuple[dict, ...]
    ...
```

- LiveEvolutionRelation 不得跨进程、不得 JSON 序列化、不得被缓存到数据库。

- Audit Projection 必须在同一进程中由 Live Relation 生成，包含每个 old/new Shape 的面积、质心、类型、方向、局部拓扑统计和可选 BREP hash，仅用于证据。

- 一个 relation 直接保存一对多 new_shapes，不再为同一 old shape 重复创建多条且丢失新形状。

- 实体类型至少支持 face/edge/vertex/solid；第一阶段必须完整支持 face 和 edge。

- HistoryQuality 增加 EXACT_KERNEL、EXACT_CONSTRUCTION、PARTIAL_POSTPROCESS、EXTERNAL_IMPORT、HEURISTIC_CANDIDATE、FAILED。

- 所有 Live relation 在写入前执行 validate_contract()。

## 7. History 捕获与操作覆盖

```python
@dataclass(frozen=True)
class TrackedShapeResult:
    result: Any
    batch: LiveEvolutionBatch
```

| 操作 | Builder | History API | 实施要求 | 优先级 |

| --- | --- | --- | --- | --- |

| Boolean cut/fuse/common | BOPAlgo_BOP | SetToFillHistory(True) + History() | Generated/Modified/IsRemoved，遍历 target 与 tool 的 Face/Edge | P0 |

| Extrude | BRepPrimAPI_MakePrism | Generated/Modified/FirstShape/LastShape | 从 profile Edge/Face 产生侧面与端面；禁止仅记录 evidence | P0 |

| Revolve | BRepPrimAPI_MakeRevol | Generated/Modified/FirstShape/LastShape | 覆盖部分旋转与完整旋转差异 | P0 |

| Fillet | BRepFilletAPI_MakeFillet | Generated(edge), Modified(face), IsDeleted 如可用 | 输入 Edge 必须来自持久 Selection，不得只用 index | P0 |

| Chamfer | BRepFilletAPI_MakeChamfer | Generated/Modified | 与 Fillet 同一策略 | P1 |

| Clean/Unify | ShapeUpgrade_UnifySameDomain | History()，若绑定可用 | 捕获合并面/边的 Modified/Removed；无绑定时阻断 EXACT | P0 门禁 |

| Offset/Shell | BRepOffset / BRepOffsetAPI | 按实际 Builder API smoke | 缺 History 时明确降级，不得假定 1:1 | P1 |

| Pattern | 多次变换+Boolean | 每个实例稳定 suboperation_id + 每步 History | 实例身份必须由 pattern index 和稳定源 Feature 建立 | P1 |

| STEP Import | STEPControl/XCAF | 无原建模 History | 只能建立外部初始 PRIMITIVE/IMPORT proof，不支持自动跨修订 EXACT | P2 |



```python
def export_bop_history(...):
    generated = tuple(history.Generated(old))
    modified = tuple(history.Modified(old))
    removed = bool(history.IsRemoved(old))
    # Preserve the real old and new TopoDS_Shape handles.
```

```python
def tracked_clean(shape, *, scope):
    unifier = ShapeUpgrade_UnifySameDomain(shape.wrapped, True, True, True)
    unifier.Build()
    if not hasattr(unifier, "History"):
        raise TopologyCapabilityError(...)
    return result, export_history_for_shape_upgrade(unifier.History(), ...)
```

## 8. TNaming Writer 的正确实现

```python
def write_relation(label, relation):
    if relation.kind is PRIMITIVE:
        builder.Generated(new_shape)
    elif relation.kind is GENERATED:
        builder.Generated(old_shape, new_shape)
    elif relation.kind is MODIFIED:
        builder.Modify(old_shape, new_shape)
    elif relation.kind is DELETED:
        builder.Delete(old_shape)
```

- 禁止任何 b.Generated(batch.result_shape) 作为 GENERATED/MODIFIED 的替代。

- 禁止 b.Delete(batch.result_shape) 代替被删除的 old subshape。

- Feature Result Label 保存该 Feature 当前结果；Evolution Relation Label 保存 old/new 演化，两者职责分离。

- 如果 result_shape 是 Compound，必须用已验证的 TNaming 写法；不得 catch Exception 后静默跳过。

- 写入每条 relation 后，立即读取 TNaming_NamedShape Evolution、OldShape/NewShape 数量并做内存自检。

- 写入 Batch 前验证 node_id 对应稳定 Feature Label；若 Label 映射冲突，Abort。

## 9. Selector 持久化与求解服务

| 状态 | 定义 | 处理 |

| --- | --- | --- |

| UNIQUE | 解析为一个满足类型和语义断言的 Shape | 可按 EXACT_ONE 策略继续 |

| SET | 解析为多个合法后继 Shape | 仅 ALL_DESCENDANTS/SET_ALLOWED 策略可继续 |

| DELETED | 旧选择被明确删除且无后继 | 相关 CAE 绑定失败关闭 |

| AMBIGUOUS | 存在多个候选但策略不允许自动继承 | 要求人工决策或修改模型语义 |

| UNRESOLVED | Solve 失败、Naming 缺失或结果为空 | 失败关闭 |

| INVALID_SEMANTICS | 拓扑可解析但不再满足圆柱面/平面/外法向等业务语义 | 失败关闭 |



```python
selector = TNaming_Selector(selection_label)
assert selector.Select(selected_shape, context_shape, False, keep_orientation)
# Verify TNaming_NamedShape and TNaming_Naming on the exact same label.
# Do not use IsIdentified() as the persistence test.
```

| 策略 | 规则 | 典型用途 |

| --- | --- | --- |

| EXACT_ONE | 必须恰好一个 Shape | 孔壁载荷、单个接触面、唯一基准面 |

| ALL_DESCENDANTS | 允许旧面分裂后传播到全部后继 | 面压力、温度边界可覆盖所有后继时 |

| SET_ALLOWED | 选择本身定义为 Named Topology Set | 一组冷却孔壁、一组周期面 |

| MANUAL_ON_AMBIGUITY | 多解时人工确认 | 高风险接触、载荷方向敏感区域 |

| DELETE_ALLOWED | 删除是合法模型状态但使绑定失效 | 可选特征的监控选择 |



## 10. Revision 生命周期与事务

```text
open existing lineage XBF or create lineage
  -> verify dependency fingerprint and schema
  -> resolve DesignRoot and StableLabelIndex
  -> NewCommand()
  -> execute canonical nodes in deterministic topological order
  -> for each node:
       run one real builder
       capture live history
       write evolution to the stable feature label subtree
       update current result label
       update valid-label set
  -> resolve all required persistent selections
  -> run geometry postconditions
  -> run semantic selection postconditions
  -> run CAE binding preflight
  -> CommitCommand()
  -> SaveAs(temp.xbf)
  -> open temp.xbf in a fresh document instance
  -> verify schema, label entries, NamedShape/Naming attributes and critical selections
  -> atomically replace official revision XBF
  -> emit revision manifest and proof
```

```python
with lineage.begin_revision(revision_id) as tx:
    ...
    tx.commit()
lineage.save_checkpoint(target)
```

- 检查 app.SaveAs 返回的 PCDM_StoreStatus 枚举，不使用“status != 0”之外未经验证的假设；在 compat smoke 中记录实际 OK 值。

- Open 时必须创建正确类型的新 TDocStd_Document，检查 PCDM_ReaderStatus。

- 新建和重开都必须通过固定 Tag 恢复同一个 DesignRoot，禁止重开后将 doc.Main() 当 DesignRoot。

- 临时 XBF 的重开自检必须在 fresh document instance 中执行；最好在独立子进程执行关键 T0/T2 测试。

- 原子替换前写入 revision manifest；Windows 下使用同卷临时文件和 os.replace。

- 保存失败、重开失败或 Attribute 缺失时不覆盖上一有效 Revision。

## 11. CAD-to-CAE 绑定策略

```text
BoundaryConditionBinding
- binding_id
- selection_id
- selection_policy
- expected_entity_type
- semantic_contract
- load_or_constraint_type
- propagation_policy
- required: bool
- last_resolved_revision
- proof_class
```

| 绑定 | 策略 | 语义合同 | 期望结果 |

| --- | --- | --- | --- |

| bore_temperature | SET_ALLOWED | Cylinder faces, radius range, axis near Z, inside radial zone | 全部匹配孔壁/内圆柱面 |

| rim_temperature | SET_ALLOWED | outer radial zone, outward normal, connected rim region | 外轮缘面集合 |

| symmetry_z0 | SET_ALLOWED | planar, normal parallel Z, centroid Z≈0 | 半模型对称面 |

| cyclic_low/high | EXACT_ONE 或 SET_ALLOWED | planar radial cuts, angular separation equals sector angle, pairable topology | 周期面配对 |

| fixed_support | EXACT_ONE | 指定基准面/孔面，方向与位置满足合同 | 唯一约束区域 |



- 所有 required binding 必须状态为 UNIQUE 或策略允许的 SET。

- 每个 Shape 必须存在于当前最终 Context Shape 中。

- 语义合同必须通过；仅 TNaming Solve 成功不等于业务绑定正确。

- 不得在失败后使用几何最近邻自动补齐。

- CAE 输入文件和结果 Metadata 必须记录 selection_id、Label Entry、Revision ID、resolution proof。

## 12. 错误模型、证据与可观测性

| 错误码 | 含义 | 处理 |

| --- | --- | --- |

| CAPABILITY_MISSING | OCP 未暴露所需 API，例如 Unify History | 阻断相应 EXACT 路径；给出 smoke 证据 |

| HISTORY_INCOMPLETE | Builder/后处理阶段没有完整 History | Revision 若存在 required persistent selection 则失败 |

| LABEL_ID_CONFLICT | 业务 ID 映射到错误/重复 Label | Abort Revision |

| EVOLUTION_CONTRACT_INVALID | old/new Shape 与 Evolution 不匹配 | Abort；这是代码缺陷 |

| OCAF_WRITE_FAILED | TNaming_Builder 写入或内存自检失败 | Abort |

| XBF_SAVE_FAILED | SaveAs 非成功状态或文件不完整 | 保留上一有效文件 |

| XBF_REOPEN_FAILED | 临时文件无法在 fresh document 打开 | 不替换正式文件 |

| SELECTOR_ATTRIBUTE_MISSING | 精确 Selection Label 缺 NamedShape 或 Naming | 失败；记录 Label Entry |

| SELECTOR_SOLVE_FAILED | Solve 返回 False | UNRESOLVED，required 时失败 |

| SELECTION_AMBIGUOUS | 结果集合不满足 Policy | 失败或人工确认 |

| SELECTION_SEMANTICS_INVALID | 拓扑解析成功但语义合同失败 | 失败 |

| CAE_PREFLIGHT_FAILED | 任一 required binding 无有效解析 | 禁止网格/求解 |



| 证明等级 | 定义 |

| --- | --- |

| EXACT_KERNEL_HISTORY | 同一生产 Builder 提供 old/new History，并成功写入 OCAF |

| EXACT_CONSTRUCTION | 构造语义能精确证明，例如原始 primitive 结果 |

| PERSISTED_SELECTOR | Selection Label 的 NamedShape/Naming 跨进程恢复且 Solve 通过 |

| PARTIAL_POSTPROCESS | 主操作有 History，但某后处理阶段缺失 |

| EXTERNAL_IMPORT | 从外部 BREP/STEP 导入，无建模演化史 |

| HEURISTIC_CANDIDATE | 指纹仅生成候选，不能自动用于 required CAE |



## 13. 文件级实施清单

| 文件 | 动作 | 具体要求 |

| --- | --- | --- |

| topology/ocaf/models.py | 重写 | 新增 LiveEvolutionRelation/Batch、Audit Projection、SelectionRecord/Resolution、ProofClass；删除“关系不存 live shape”的设计 |

| topology/ocaf/capture_session.py | 重写 | 移除 global staging token；直接持有 Batch；支持 ordered batches、close、泄漏检查 |

| topology/ocaf/tracked_ops/boolean.py | 重写核心 | 保存真实 old/new Shape；Face+Edge；一对多 tuple；删除判定规则；无全局 dict |

| topology/ocaf/tracked_ops/extrude.py | 修改 | 保存 profile entity -> generated shape；端面/侧面；多输入 element 的稳定 suboperation_id |

| topology/ocaf/tracked_ops/revolve.py | 修改 | 同上；处理 360° 与部分角度；轴退化测试 |

| topology/ocaf/tracked_ops/fillet.py | 重写输入选择 | 不再以 Edge index 为权威输入；使用已解析 Edge Selection；保存 Generated/Modified |

| topology/ocaf/tracked_ops/chamfer.py | 新增 | 按实际 Builder History 实现 |

| topology/ocaf/tracked_ops/clean.py | 新增 | 直接调用 ShapeUpgrade_UnifySameDomain；ABI gate；History 捕获 |

| topology/ocaf/compat.py | 扩展 | 集中所有 OCP 7.8.1.1 API 重载、枚举状态、FindAttribute、TDF Entry/Label、History 能力探测 |

| topology/ocaf/label_index.py | 新增 | 稳定 ID↔Label Entry 索引；固定 Tag；冲突检测 |

| topology/ocaf/document.py | 重写 | Lineage Document；稳定 DesignRoot；open/create；Revision transaction；原子保存和 fresh reopen self-check |

| topology/ocaf/writer.py | 重写 | 正确 TNaming evolution；结果/演化分区；内存自检；禁止吞异常 |

| topology/ocaf/selection_service.py | 新增 | 原生 Select/Solve；Attribute 验证；Policy；语义后检查 |

| topology/ocaf/selectors.py | 降级 | FaceSelector 改名 HeuristicFaceCandidateFinder；不得作为权威路径 |

| topology/ocaf/cae_bindings.py | 新增 | Selection ID 到 CAE Region 的绑定和 preflight |

| pipeline/run.py | 重构集成 | 打开同一 Lineage；整个 Revision 单事务；geometry/selection/CAE gate 后提交；OCAF 失败变 hard failure |

| runtime/context.py | 修改 | 加入 lineage、revision transaction、stable label index、proof log |

| pyproject.toml / lock | 修改 | 精确锁定 CadQuery/OCP/Python 支持矩阵；添加版本自检命令 |

| tests/topology/ocaf/* | 新增 | T0-T12 全部测试；独立进程测试 |

| scripts/ocaf_smoke/* | 新增 | ABI probe、最小 selector persistence、XBF inspector、label dump |



## 14. 分阶段 PR 计划

| PR | 主题 | 交付 | 合并门禁 |

| --- | --- | --- | --- |

| PR-0 | 版本冻结与 ABI 证伪 | 锁版本；生成 dependency fingerprint；T0 最小程序；确认 Save/Open 状态、FindAttribute、Selector 属性、Unify History 暴露 | 未通过不得改生产 Pipeline |

| PR-1 | Live History 数据模型 | 重构 models/capture；Boolean 保存真实 Shape；单操作内存测试 | 真实 old/new 关系可验证 |

| PR-2 | 稳定 Label 与 Lineage Document | label_index、固定 DesignRoot、open/create、事务、原子保存 | 同一 ID 跨重开 Entry 不变 |

| PR-3 | 正确 TNaming Writer | Generated/Modify/Delete；内存自检；XBF 重开验证 | T0/T1 通过 |

| PR-4 | Persistent Selection Service | Select/Solve、Policy、语义检查、跨进程测试 | T2/T3/T4 通过 |

| PR-5 | 操作覆盖与 tracked_clean | Extrude/Revolve/Fillet/Chamfer/Clean；Edge 选择改造 | 操作级覆盖门槛达到 |

| PR-6 | 生产 Pipeline 集成 | 整个 Revision 单事务；OCAF hard gate；Metadata proof | E2E 不改变关闭状态下几何；启用时强一致 |

| PR-7 | CAE Binding | Selection Registry、FEA preflight、边界条件区域输出 | 关键绑定误绑定率 0 |

| PR-8 | 兼容性与升级矩阵 | 在独立分支测试更新 OCP/OCCT；不与核心修复混合 | 可选，不阻塞 v2.0 |



## 15. 测试矩阵与验收门禁

| ID | 测试 | 场景 | 通过条件 |

| --- | --- | --- | --- |

| T0 | 纯 Selector XBF 持久化 | Box + 非对称 Face；Select；保存；新进程精确 Entry 恢复 | NamedShape 与 Naming 都存在，当前 Shape 非空 |

| T1 | Primitive + Modify | 同一文档 Box 尺寸改变，写入 old top face -> new top face Modify | Solve 后唯一解析到新顶面 |

| T2 | 跨进程三阶段 | 进程 A Rev1；进程 B Open+Rev2；进程 C Open+Solve | Entry 稳定，Solve 通过 |

| T3 | Generated 1→N | Boolean 明确分裂一个面 | 返回 SET/AMBIGUOUS，按 Policy 处理；不自动选最近 |

| T4 | Delete | 删除被选择特征 | 返回 DELETED，required CAE 阻断 |

| T5 | Merge N→1 | Unify 或 Boolean 合并多个面 | Named set/Policy 正确，证据完整 |

| T6 | Clean History | UnifySameDomain 前后 | History 链完整；若 API 缺失，capability test 明确失败 |

| T7 | 对称阵列 | 多个面积/质心/类型相同孔面 | 原生 Selection 可保持语义；Fingerprint 不参与权威判定 |

| T8 | Fillet 参数变化 | 持久 Edge Selection + 半径变化 | 选中边或后继集合正确；禁止 Edge index 漂移 |

| T9 | 事务回滚 | 中间 Feature 故意失败 | XBF 和选择保持上一 Revision 状态 |

| T10 | XBF 损坏/保存失败 | 模拟权限/截断/打开错误 | 不覆盖正式文件；结构化错误 |

| T11 | CAE 门禁 | 一个 required 绑定 unresolved | ANSYS/Gmsh 不启动 |

| T12 | 完整 Text-to-CAD E2E | 参数修改、重启服务、再分析 | CAD、OCAF、CAE proof 一致 |



- 所有测试默认在 Windows 目标环境执行；T0/T2/T10 必须使用独立子进程。

- 每次 PR 都必须运行原有 CAD 几何回归，证明未开启 topology capture 时结果不变。

- 开启 topology capture 后，STEP 几何体积、实体数和关键 BBox 与原路径一致。

- 测试不得依赖 Face() 或 Edge() 的数组顺序来判断身份；仅可用几何属性做断言，不能用作解析算法。

- 测试输出必须保存 dependency fingerprint、Label tree dump、Attribute dump、History relation dump。

- 任何 flaky test 不得通过放宽指纹阈值解决。

## 16. ABI Smoke Test 与诊断脚本

```python
from __future__ import annotations
import json, platform, sys
from pathlib import Path
import cadquery as cq
import OCP
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TNaming import TNaming_Selector, TNaming_Builder, TNaming_NamedShape, TNaming_Naming
from OCP.TDF import TDF_LabelMap, TDF_Tool

result = {
    "python": sys.version,
    "platform": platform.platform(),
    "cadquery": getattr(cq, "__version__", "unknown"),
    "ocp": getattr(OCP, "__version__", "unknown"),
}

box = cq.Workplane("XY").box(20, 30, 10).val()
unifier = ShapeUpgrade_UnifySameDomain(box.wrapped, True, True, True)
result["unify_has_history"] = hasattr(unifier, "History")
result["selector_methods"] = {
    name: hasattr(TNaming_Selector, name)
    for name in ("Select", "Solve", "NamedShape", "IsIdentified_s")
}
result["builder_methods"] = {
    name: hasattr(TNaming_Builder, name)
    for name in ("Generated", "Modify", "Delete", "Select")
}
result["attribute_ids"] = {
    "named_shape": str(TNaming_NamedShape.GetID_s()),
    "naming": str(TNaming_Naming.GetID_s()),
}
print(json.dumps(result, indent=2, ensure_ascii=False))
```

- 创建时 DesignRoot Entry、Result Label Entry、Selection Label Entry。

- Select 返回值。

- 保存前 Selection Label 上 NamedShape/Naming Attribute 存在性。

- SaveAs 状态名称和整数值。

- 新进程 Open 状态名称和整数值。

- 重开后按精确 Entry 找到 Label 的结果。

- 重开后两个 Attribute 存在性。

- NamedShape Evolution 是否为 SELECTED。

- TNaming_Tool.CurrentShape 返回的 Shape 类型、是否为空、几何断言。

## 17. 迁移、兼容与回滚

- 新增 schema_version，例如 `gcad_ocaf_lineage_v2`，拒绝把旧 `gcad_topo_v3@ocaf_v1` 文件直接作为可更新谱系。

- 提供只读 inspector，可导出旧 XBF Label tree 和 NamedShape，但不宣称可恢复旧 PID。

- 首次启用 v2 时从当前 Canonical IR 重建一个新的 Lineage Baseline Revision；用户/系统重新创建 required selections。

- Fingerprint 只用于给人工重建 Selection 提供候选，不自动提交。

- 保留 feature flag：`topology_lineage_mode = off | audit | enforce`。audit 模式写证据但不驱动 CAE；enforce 模式严格失败关闭。

- 每次正式 Revision 保留上一有效 XBF 和 manifest，支持原子回滚。

| 变更 | 要求 | 限制 |

| --- | --- | --- |

| OCP/OCCT 升级 | 独立兼容分支运行 T0-T12 | 不得与核心架构修复同一个 PR |

| CadQuery 升级 | 比较 shapes.py 建模路径和 clean 实现 | tracked op 必须重新对齐生产 Builder |

| Python 升级 | 重新构建/验证 wheel ABI | 不得只因纯 Python 测试通过就放行 |

| 旧 XBF | 只读，不自动迁移 PID | 需要人工或新的 baseline selection |



## 18. 禁止事项

- 禁止用 `batch.result_shape` 代替 relation.old_shape 或 relation.new_shapes。

- 禁止把 MODIFIED 写成 Generated(result_shape)。

- 禁止把 DELETED 写成 Delete(result_shape)。

- 禁止每次 Revision 新建无关联的 OCAF 文档并声称支持跨 Revision。

- 禁止用 NewChild() 的自然顺序作为 component/node/selection 的持久身份。

- 禁止在 Selection Label 上附加其他业务 Attribute 后再调用 Select()，因为 Select 会清理该 Label。

- 禁止把 IsIdentified() 作为 Selector 持久化验收。

- 禁止递归扫描 Label 树后挑一个 NamedShape 作为 Selector 恢复。

- 禁止 catch Exception 后继续标记 OCAF 成功。

- 禁止在 geometry_postcheck 和 CAE preflight 之前覆盖正式 XBF。

- 禁止把 FaceSelector/几何指纹结果直接用于 required CAE 绑定。

- 禁止用 Face/Edge 数组索引作为持久输入，特别是 Fillet/Chamfer。

- 禁止为了取得 History 第二次执行几何 Builder。

- 禁止在缺少 Unify History 时把 clean 后结果标记为 EXACT_KERNEL_HISTORY。

- 禁止在同一 PR 中同时重构 OCAF 架构并升级 OCCT/CadQuery。

## 19. 最终交付清单

| ID | 交付物 |

| --- | --- |

| D-01 | 精确依赖锁与 dependency fingerprint |

| D-02 | ABI smoke JSON 和最小 T0 复现脚本 |

| D-03 | Live/Audit 分离的数据模型 |

| D-04 | 无全局 registry 的 CaptureSession |

| D-05 | Boolean/Extrude/Revolve/Fillet/Clean 真实 History |

| D-06 | StableLabelIndex 和固定 OCAF 文档树 |

| D-07 | Lineage Document + RevisionTransaction + 原子保存重开自检 |

| D-08 | 正确的 TNamingEvolutionWriter |

| D-09 | PersistentSelectionService 和 Policy |

| D-10 | CAE Binding Registry 与 Preflight Gate |

| D-11 | T0-T12 自动化测试与日志证据 |

| D-12 | 开发者文档、schema、迁移说明和故障排查手册 |



## 附录 A. 关键代码骨架

```python
def find_attribute(label, attr_cls):
    """Return a typed OCAF attribute or None.

    OCP 7.8.1.1 customizes TDF_Label.FindAttribute; verify the exact calling
    convention in PR-0 and keep it isolated here.
    """
    attr = attr_cls()
    ok = label.FindAttribute(attr_cls.GetID_s(), attr)
    return attr if ok else None


def assert_selector_attributes(label):
    named = find_attribute(label, TNaming_NamedShape)
    naming = find_attribute(label, TNaming_Naming)
    if named is None or naming is None:
        raise SelectorAttributeMissing(
            label_entry=entry_of(label),
            has_named_shape=named is not None,
            has_naming=naming is not None,
        )
    return named, naming
```

```python
def entry_of(label) -> str:
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TDF import TDF_Tool
    entry = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, entry)  # exact generated name must be smoke-tested
    return entry.ToCString()


def label_from_entry(doc, entry: str, *, create: bool = False):
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TDF import TDF_Label, TDF_Tool
    label = TDF_Label()
    ok = TDF_Tool.Label_s(
        doc.GetData(),
        TCollection_AsciiString(entry),
        label,
        create,
    )
    if not ok or label.IsNull():
        raise LabelNotFound(entry)
    return label
```

```python
def reopen_self_check(path: Path, manifest: RevisionManifest) -> XbfReopenProof:
    reopened = OcafLineageDocument.open(path, expected_document_id=manifest.document_id)
    assert reopened.schema_version == manifest.schema_version
    for item in manifest.critical_labels:
        label = reopened.labels.label_from_entry(item.entry, create=False)
        assert reopened.labels.object_id(label) == item.object_id
    for selection in manifest.required_selections:
        label = reopened.labels.label_from_entry(selection.label_entry, create=False)
        named, naming = assert_selector_attributes(label)
        current = TNaming_Tool.CurrentShape_s(named)
        if current.IsNull():
            raise XbfSelfCheckFailed(selection.selection_id, "empty current shape")
    return XbfReopenProof(ok=True, ...)
```

## 附录 B. 来源与版本证据

| 编号 | 来源 | 用途 |

| --- | --- | --- |

| R1 | 当前实施状态报告 v1.1 | 仓库 docs/OCAF_实施状态报告_v1.1.md，提交 0b349da... |

| R2 | 此前代码 Agent 指导书 v1.0 | 仓库 docs/Text-to-CAD_OCAF持久化拓扑命名_代码Agent实施指导书_v1.0.md，提交 0b349da... |

| R3 | 当前 document.py | 仓库 generative_cad/topology/ocaf/document.py，提交 0b349da... |

| R4 | 当前 writer.py | 仓库 generative_cad/topology/ocaf/writer.py，提交 0b349da... |

| R5 | 当前 models.py | 仓库 generative_cad/topology/ocaf/models.py，提交 0b349da... |

| R6 | 当前 tracked boolean | 仓库 topology/ocaf/tracked_ops/boolean.py，提交 0b349da... |

| R7 | 当前 pipeline integration | 仓库 generative_cad/pipeline/run.py，提交 0b349da... |

| U1 | OCCT 7.8.1 TNaming_Selector | Open-Cascade-SAS/OCCT tag V7_8_1, src/TNaming/TNaming_Selector.cxx/.hxx |

| U2 | OCCT 7.8.1 TNaming_Builder | Open-Cascade-SAS/OCCT tag V7_8_1, src/TNaming/TNaming_Builder.hxx |

| U3 | OCCT 7.8.1 NamedShape binary driver | src/BinMNaming/BinMNaming_NamedShapeDriver.cxx |

| U4 | OCCT 7.8.1 Naming binary driver | src/BinMNaming/BinMNaming_NamingDriver.cxx |

| U5 | OCCT 7.8.1 UnifySameDomain | ShapeUpgrade_UnifySameDomain.hxx；实现见同目录 .cxx |

| U6 | OCCT OCAF User Guide | Label persistent address、TNaming evolution、Selector、transaction、persistence |

| U7 | OCP 7.8.1.1 binding config | CadQuery/OCP tag 7.8.1.1, ocp.toml |

| U8 | CadQuery 2.7.0 shapes.py | CadQuery/cadquery tag v2.7.0，clean/extrude/revolve/fillet 实现 |



- R1: https://raw.githubusercontent.com/WYZAAACCC/text2cad_improve/0b349da7b24b0f0f234c90b2ec5b6cc2c0129097/docs/OCAF_%E5%AE%9E%E6%96%BD%E7%8A%B6%E6%80%81%E6%8A%A5%E5%91%8A_v1.1.md

- R2: https://raw.githubusercontent.com/WYZAAACCC/text2cad_improve/0b349da7b24b0f0f234c90b2ec5b6cc2c0129097/docs/Text-to-CAD_OCAF%E6%8C%81%E4%B9%85%E5%8C%96%E6%8B%93%E6%89%91%E5%91%BD%E5%90%8D_%E4%BB%A3%E7%A0%81Agent%E5%AE%9E%E6%96%BD%E6%8C%87%E5%AF%BC%E4%B9%A6_v1.0.md

- U1: https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/TNaming/TNaming_Selector.cxx

- U2: https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/TNaming/TNaming_Builder.hxx

- U3: https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/BinMNaming/BinMNaming_NamedShapeDriver.cxx

- U4: https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/BinMNaming/BinMNaming_NamingDriver.cxx

- U5: https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/ShapeUpgrade/ShapeUpgrade_UnifySameDomain.hxx

- U6: https://dev.opencascade.org/doc/overview/html/occt_user_guides__ocaf.html

- U7: https://github.com/CadQuery/OCP/blob/7.8.1.1/ocp.toml

- U8: https://github.com/CadQuery/cadquery/blob/v2.7.0/cadquery/occ_impl/shapes.py

> 给代码 Agent 的最后指令：先用 T0 最小程序证明正确的 Attribute/Label/Save/Open 链，再修改生产 Pipeline。不要用启发式让测试“变绿”。
