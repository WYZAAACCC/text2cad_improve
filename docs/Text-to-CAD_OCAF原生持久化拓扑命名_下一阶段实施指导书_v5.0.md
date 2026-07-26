# Text-to-CAD OCAF 原生持久化拓扑命名系统
# 当前状态审查与下一阶段实施指导书 v5.0

> 审查日期：2026-07-26  
> 适用仓库：`WYZAAACCC/text2cad_improve`  
> 审查基线：报告声明的最新实现基线 `6e248a0` 及其关联源码  
> 参考文档：`docs/OCAF_完整诊断测试报告_v4.0.md`  
> 执行对象：代码 Agent  
> 文档性质：下一阶段实施基线、代码审查清单与验收规范  
> 目标：从“模块级 OCAF/TNaming Alpha”推进到“可信的跨 Revision 原生拓扑命名 MVP”

---

# 0. 一页结论

当前系统已经证明：

- BinXCAF/XBF 原生持久化可用；
- UTF-8 路径可用；
- 固定 Tag 100 的应用标签树可用；
- `TDataStd_*`、`TNaming_NamedShape`、`TNaming_Naming` 可跨进程恢复；
- Live History 已开始保存真实 `TopoDS_Shape`；
- Writer 已使用 `Generated/Modify/Delete` 的正确 OCCT API；
- Boolean、Extrude、Revolve、Fillet、Chamfer、Mirror、Pattern、Unify 等操作已有不同程度的捕获支持；
- Selection、CAE preflight、Pipeline topology mode、StableLabelIndex 等模块已经出现。

但本次源码审查确认：

> 当前版本仍不能认定为“跨 Revision 原生拓扑命名 MVP”。

更准确的状态是：

> **OCAF/TNaming 模块级 Alpha：基础持久化与单 Revision 组件已具备，但 Stable ID 恢复、Revision/Lineage、真实 Modify 链、Pipeline 事务、Selection 精确解析、CAE fail-closed 尚未形成可信闭环。**

当前最严重的四个问题是：

1. `StableLabelIndex.load_from_ocaf()` 依赖当前 OCP 不存在或不可靠的 `TDataStd_*.Get_s()`，并吞掉读取异常，因此报告声称的“跨进程稳定索引恢复”没有被真实证明；
2. 现有 T2 在新 Revision 中重新写入 `PRIMITIVE`，没有执行 `Modify(old_shape, new_shape)`，而且允许结果为 `AMBIGUOUS`，因此它不是跨 Revision 拓扑演化验收；
3. Pipeline 虽已加入 create/open、事务与 staging，但仍在最终 STEP/Geometry postcheck 之前发布 XBF，且没有真正接入 Selection Solve 与 CAE preflight；
4. Writer 的 Relation Label 仍依赖列表位置，Pattern 只捕获 Transform history、没有捕获最终 Fuse history，却仍宣称 `history_complete=True`。

下一阶段必须按以下顺序执行：

```text
P0：审计基线与测试可信度
→ P1：StableLabelIndex v2 真正持久化
→ P2：Pipeline Artifact Bundle 事务
→ P3：Revision/Lineage 与真实 Modify T2
→ P4：稳定 Relation Identity 与 tracked operation 正确性
→ P5：Selection Service v3 与 Native Crash 隔离
→ P6：CAE Gate 真正接入
→ P7：T3～T12 与完整 E2E
```

在 P1～P3 完成前，禁止继续增加新的 tracked operation。

---

# 1. 审查范围与方法

本次审查不是只读取状态报告，而是将报告声明逐项映射到实际代码，重点检查：

- 报告声称已完成的功能是否在正式运行入口被调用；
- 测试是否真正覆盖报告所声称的语义；
- 代码是否存在 fail-open、异常吞噬或“测试重新创建数据后仍通过”的情况；
- Label、Relation、Selection 是否具备跨 Revision 稳定身份；
- XBF、STEP、metadata 是否属于同一个原子 Revision；
- CAE 是否只能消费已通过原生拓扑解析和语义门禁的实体。

重点源码：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/
├── pipeline/run.py
├── runtime/context.py
└── topology/ocaf/
    ├── compat.py
    ├── schema.py
    ├── models.py
    ├── label_index.py
    ├── document.py
    ├── repository.py
    ├── writer.py
    ├── capture_session.py
    ├── selection_service.py
    ├── cae_preflight.py
    ├── heuristic_candidates.py
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

重点测试：

```text
test_t2_cross_revision.py
test_pipeline_topology_modes.py
test_ocaf_hardening.py
test_ocaf_operation_coverage.py
test_selection_service.py
```

---

# 2. 对 v4.0 报告结论的评级

## 2.1 可以保留的结论

以下结论与源码方向基本一致：

- OCAF/XBF 原生持久化底层可用；
- UTF-8 路径构造必须统一；
- 固定 Tag 100 能隔离 XCAF 系统标签；
- Live/Audit 分离方向正确；
- Writer 已不再把所有 Evolution 都退化为同一种调用；
- Selection Service 已经能够创建、持久化并尝试 Solve；
- StableObjectKey 已开始支持复合身份；
- Pipeline 已出现 topology off/audit/enforce 的设计；
- Geometry A/B 是必须保留的门禁；
- Delete Solve 存在 native crash 风险；
- 当前仍未完成 T4、T5、T6、T7、T8、T12。

## 2.2 必须降级表述的结论

### “StableLabelIndex 已跨进程恢复”

必须改为：

> StableLabelIndex 已有持久化设计与初步实现，但当前读取实现存在确定性 API 与异常处理问题，现有测试尚未证明真正从 OCAF 恢复索引。

原因：

- 读取路径使用当前 OCP 不存在或不可靠的 `TDataStd_Integer.Get_s()`、`TDataStd_AsciiString.Get_s()`；
- 读取失败时使用 `pass` 或 `continue`；
- open 后测试再次调用 `ensure_*()`，即使索引为空，也会重新分配相同 Tag，从而伪装成恢复成功；
- counter 读取失败时可能从 1000 重新开始，撞击已有标签。

### “T2 跨 Revision MVP 已完成”

必须改为：

> T2 目前验证了多进程保存、Retrieve、再次写入和 Selection 文档往返，但没有验证真实 `Modify(old,new)` 的跨 Revision 拓扑演化。

现有 T2 的关键问题：

- Rev2/Rev3 使用新的 `PRIMITIVE`；
- 没有从上一 Revision 读取 previous current result；
- 没有调用 `Modify(previous_result,new_result)`；
- 允许 `UNIQUE` 或 `AMBIGUOUS`；
- 没有断言精确 FACE、面积、法向、质心；
- 没有断言 Stable TagPath 在三个进程中保持一致；
- 直接 `save_to()`，没有走正式 Pipeline Artifact 事务。

### “Pipeline 已闭环”

必须改为：

> Pipeline 已具有部分 OCAF 接线，但没有形成 Geometry→History→Solve→CAE→Bundle Publish 的最终事务。

### “Pattern 已有 Fuse history”

与源码不符。当前 Pattern：

- 捕获了每个 Transform 的 source→copy；
- 最终使用顺序 Fuse；
- 没有捕获 Fuse 的 Modified/Generated/Deleted；
- Fuse 失败时可能保留前一步结果；
- 最终仍设置 `history_complete=True`。

### “131 项测试全部通过”

必须在报告中明确：

- 哪些测试文件实际存在于所声明 SHA；
- 哪些测试被 ignore/skip；
- fragile tests 是否计入；
- CI 原始命令；
- CI 日志 hash；
- 本地未推送测试不得计入主分支完成度。

---

# 3. 当前成熟度重新评估

| 能力层 | 当前状态 | 成熟度 |
|---|---|---:|
| OCAF/XBF 基础持久化 | 已验证 | 90% |
| UTF-8/Tag 100/安全 Retrieve | 基本完成 | 90% |
| Live History 数据模型 | 主体存在 | 75% |
| 单操作 TNaming Writer | 基本正确 | 70% |
| StableLabelIndex | 写入骨架有，读取不可信 | 35% |
| 单 Revision Selection | 可运行，语义与拆分不足 | 55% |
| Pipeline 集成 | 入口、顺序、事务不完整 | 35% |
| Revision/Lineage | 基本缺失 | 15% |
| 真实跨 Revision Modify | 未验证 | 20% |
| Pattern/Unify/EDGE | 局部 | 25% |
| CAE preflight | 模块存在，未真正接线 | 10% |
| 完整产品 | 模块级 Alpha | 约 40% |

产品状态建议使用：

```text
OCAF Native Topology Naming – Engineering Alpha
```

在真实 T2、P2 Artifact Bundle、P6 CAE Gate 完成前，不应使用：

```text
Cross-Revision MVP Completed
```

---

# 4. P0：先修复审计基线与测试可信度

## 4.1 目标

确保报告、源码和测试属于同一个不可变基线，防止本地测试、错误路径或旧文档结果混入完成度。

## 4.2 新增文件

```text
tools/ocaf_status_manifest.py
docs/generated/OCAF_BUILD_MANIFEST.json
```

Manifest 至少包含：

```json
{
  "git_sha": "...",
  "python": "...",
  "ocp": "...",
  "occt": "...",
  "platform": "...",
  "test_files": [],
  "ignored_tests": [],
  "skipped_tests": [],
  "command": "...",
  "passed": 0,
  "failed": 0,
  "duration_seconds": 0,
  "report_sha256": "..."
}
```

## 4.3 要求

1. v4.0 报告声明的每个测试文件必须存在于同一 SHA；
2. 不能把 ignore 的测试计入 passed；
3. 不得使用“131 全过”描述“118 通过 + 2 ignore + 11 局部测试”；
4. 每次更新状态文档必须附 Manifest；
5. CI 必须在 clean checkout 上执行；
6. 禁止依赖未提交的本地脚本。

## 4.4 Gate

```text
git clean checkout
→ 安装锁定依赖
→ 单命令运行
→ 生成相同 manifest
```

未通过不得进入后续 PR。

---

# 5. P1：StableLabelIndex v2

这是下一阶段的第一优先级。

## 5.1 当前问题

### 不安全读取

禁止继续使用：

```python
TDataStd_Integer.Get_s(label)
TDataStd_AsciiString.Get_s(label)
```

并禁止：

```python
except Exception:
    pass
```

### 测试假阳性

现有测试 open 后再调用：

```python
ensure_component(...)
ensure_feature(...)
```

这会在索引加载失败时重新分配 Label，导致“恢复成功”的错觉。

### counter 冲突

若 entries 存在而 counter 加载失败，新的对象可能重新获得 1000、1001 等已有 Tag。

### namespace 不充分

Feature namespace 不应只依赖 component tag；必须使用稳定语义 component ID。

### Relation/Revision 未纳入索引

需要统一管理：

- component；
- feature；
- selection；
- relation；
- revision；
- CAE binding。

## 5.2 安全属性读取适配器

在 `compat.py` 中实现：

```python
def read_ascii_string(label, guid=None) -> str | None:
    for attr in iter_real_attributes(label):
        if is_ascii_string_attr(attr, guid):
            return str(attr.Get())
    return None

def read_integer(label, guid=None) -> int | None:
    for attr in iter_real_attributes(label):
        if is_integer_attr(attr, guid):
            return int(attr.Get())
    return None
```

要求：

- 通过 `TDF_AttributeIterator` 获取真实挂接属性；
- 不使用 `FindAttribute` 壳对象；
- 不使用不存在的 `Get_s`；
- required 字段缺失时抛出结构化错误；
- optional 字段才允许 None。

## 5.3 新复合 Key

```python
@dataclass(frozen=True, slots=True)
class StableObjectKey:
    object_kind: Literal[
        "component",
        "feature",
        "selection",
        "relation",
        "revision",
        "cae_binding",
    ]
    namespace: str
    object_id: str
```

示例：

```text
component | lineage:disk-lineage           | disk
feature   | component:disk                  | extrude-base
feature   | component:shaft                 | extrude-base
selection | lineage:disk-lineage            | bore-surface
relation  | feature:disk/cut-bore           | target-top-modified
revision  | lineage:disk-lineage            | rev-000003
```

## 5.4 OCAF Index Schema

```text
100:7 StableIdIndex
├── 1 Metadata
│   ├── schema_version
│   └── index_revision
├── 2 Counters
│   ├── component_next
│   ├── feature_next
│   ├── selection_next
│   ├── relation_next
│   ├── revision_next
│   └── cae_binding_next
└── 3 Entries
    └── <entry_tag>
        ├── object_kind
        ├── namespace
        ├── object_id
        ├── tag_path
        ├── created_revision
        ├── retired_revision
        └── checksum
```

## 5.5 加载验证

`load_from_ocaf()` 必须：

1. 校验 schema version；
2. 枚举所有 entry；
3. 校验复合 key 唯一；
4. 校验 tag_path 唯一；
5. 校验指向 Label 存在；
6. 校验 counter 大于所有已占用 Tag；
7. 若 counter 缺失，则根据已加载 entries 重建；
8. 若发现冲突，抛出 `CorruptStableIndexError`；
9. 不得自动忽略坏 entry；
10. 不得静默重新分配已有对象。

## 5.6 退休策略

- Tag 永不复用；
- 删除对象只写 `retired_revision`；
- 同一 key 不能重新映射到不同路径；
- 如确需复活，必须显式 migration。

## 5.7 决定性测试

### Index-1：真实只读恢复

进程 B 打开后，不调用任何 `ensure_*()`，直接：

```python
entry = index.get_existing(key)
```

断言 TagPath。

### Index-2：乱序恢复

Rev1 请求 A、B、C；Rev2 请求 C、A、D、B：

- A/B/C 原 Tag 不变；
- D 获得新 Tag；
- counter 不冲突。

### Index-3：同名 Feature

两个组件都有 `extrude-base`，必须获得不同路径。

### Index-4：坏索引

手工破坏 counter、重复 key、重复 path，必须 fail-closed。

### Index-5：三进程

Writer、Reader+Append、Final Reader，检查完整索引和 counters。

## 5.8 Gate

只有在 open 后完全不调用 `ensure_*()` 的情况下，仍能恢复全部 Tag，才算通过。

---

# 6. P2：Pipeline Artifact Bundle 事务

## 6.1 当前问题

现有 Pipeline 存在：

- topology mode 不能通过正式公开 API 完整配置；
- XBF 发布发生在最终 STEP/Geometry postcheck 前；
- 没有 Selection Solve；
- 没有 CAE preflight；
- 异常路径未保证 abort/close；
- `publish()` 使用 `copy2`，不是真正原子；
- 没有子进程验证；
- XBF、STEP、metadata 可能属于不同逻辑 Revision。

## 6.2 新公开配置

```python
@dataclass(frozen=True, slots=True)
class TopologyRunConfig:
    mode: Literal["off", "audit", "enforce"]
    lineage_id: str
    revision_id: str
    parent_revision_id: str | None
    output_root: Path
    required_selection_ids: tuple[str, ...] = ()
    required_cae_binding_ids: tuple[str, ...] = ()
    verify_in_subprocess: bool = True
```

`run_canonical_gcad()` 必须显式接受：

```python
topology: TopologyRunConfig | None
```

禁止仅通过存在 `ocaf_path` 自动推导 audit。

## 6.3 正确执行顺序

```text
1. Canonical IR 与 validation
2. 几何操作执行 + Capture
3. Runtime postconditions
4. 导出 STEP 到 staging
5. Geometry postcheck
6. STEP postcheck
7. create/open OCAF Revision Session
8. begin_write()
9. 写 History
10. 持久化 StableLabelIndex
11. Solve required selections
12. Semantic contract validation
13. CAE preflight
14. commit_write()
15. Save XBF 到 staging
16. 独立进程 Retrieve 验证
17. 生成 topology manifest
18. 生成 artifact manifest + hashes
19. 关闭 OCAF 文档
20. 原子发布 Revision Bundle
21. 原子更新 HEAD
```

错误路径：

```text
abort_write()
close()
删除 staging
不修改现有 HEAD
```

## 6.4 Immutable Revision Bundle

```text
lineage/
├── HEAD.json
└── revisions/
    ├── rev-000001/
    │   ├── design.xbf
    │   ├── model.step
    │   ├── metadata.json
    │   ├── topology_manifest.json
    │   ├── selection_resolution.json
    │   └── cae_preflight.json
    └── rev-000002/
```

禁止原地覆盖上一 Revision。

## 6.5 原子发布

推荐：

```python
os.replace(staging_revision_dir, final_revision_dir)
os.replace(head_temp, head_path)
```

若 Windows 目录替换不可靠：

- 使用永不覆盖的新 Revision 目录；
- 只原子替换很小的 `HEAD.json`；
- old Revision 永远保留。

禁止将 `shutil.copy2(temp, official)` 描述为原子发布。

## 6.6 子进程验证

新增：

```text
topology/ocaf/verify_worker.py
```

验证：

- XBF 可 Retrieve；
- DesignRoot 存在；
- schema version；
- StableLabelIndex 完整；
- RevisionRecord；
- required Selection labels；
- TNaming attributes；
- manifest hash。

native crash 必须转为结构化失败。

## 6.7 模式语义

### off

- 不创建 OCAF；
- Geometry 与 STEP 正常。

### audit

- OCAF 失败记录警告；
- 是否允许发布 STEP 必须明确配置；
- 不得把失败 XBF 发布为正式 artifact。

### enforce

- 任意 OCAF、Selection、CAE、verify 失败；
- 整个 Revision Bundle 不发布。

## 6.8 Failure Injection

在以下位置逐一注入失败：

- writer 第 N 条 relation；
- index save；
- selection solve；
- CAE preflight；
- commit；
- SaveAs；
- verify worker；
- manifest；
- HEAD 更新。

每个测试都必须断言上一 HEAD 字节不变。

---

# 7. P3：Revision/Lineage 与真实跨 Revision T2

## 7.1 当前 T2 为什么不成立

真实跨 Revision 必须证明：

```text
Rev1 old shape
→ Rev2 new shape
→ TNaming Modify(old,new)
→ Selector Solve
→ 精确恢复同一语义 FACE/EDGE
```

当前测试只是：

```text
Rev1 Generated(box1)
Rev2 Generated(box2)
Rev3 Generated(box3)
```

这不能证明 topology history 演化。

## 7.2 Revision 数据模型

新增：

```python
@dataclass(frozen=True, slots=True)
class RevisionRecord:
    lineage_id: str
    revision_id: str
    revision_number: int
    parent_revision_id: str | None
    canonical_ir_hash: str
    operation_graph_hash: str
    geometry_hash: str
    xbf_hash: str | None
    state: Literal[
        "staging",
        "validated",
        "published",
        "aborted",
    ]
```

存入：

```text
100:6 Revisions
└── <stable revision label>
```

DesignRoot Metadata：

```text
schema_version
lineage_id
head_revision_id
head_revision_number
```

## 7.3 乐观并发

创建 Rev N 时：

```python
if requested_parent != persisted_head:
    raise RevisionConflictError
```

禁止覆盖分叉历史。

## 7.4 Feature CurrentResult

当前 Writer 总是对 CurrentResult：

```python
Generated(result)
```

必须改为：

```python
if initial_revision:
    builder.Generated(new_result)
else:
    builder.Modify(previous_result, new_result)
```

新增：

```python
write_feature_result(
    feature_label,
    previous_result,
    new_result,
    revision_context,
)
```

要求：

- previous_result 从上一 XBF 的真实 NamedShape 获取；
- 不通过几何指纹猜测；
- feature ID、component ID 与 Label 相同；
- initial/later 分支显式。

## 7.5 真实 T2 Fixture

建议使用非对称实体，避免多个等价面：

```text
Rev1：不对称台阶块，高度 10
选择唯一顶部小平面
Rev2：高度改为 15
Rev3：高度改为 22
```

三个独立进程。

### Rev1

- 创建文档；
- 写 Primitive；
- 创建 Selection；
- 保存、验证、发布。

### Rev2

- Retrieve Rev1；
- 读取 previous CurrentResult；
- 使用同一稳定 Feature ID；
- 执行新的 Builder；
- 写 `Modify(previous_result,new_result)`；
- Solve；
- 保存、验证、发布。

### Rev3

重复 Rev2。

## 7.6 T2 强断言

每个 Revision 都必须断言：

- Selection status == `UNIQUE`；
- `resolved_shapes` 长度 == 1；
- ShapeType == FACE；
- 面积等于预期；
- 质心坐标等于预期；
- 平面法向等于预期；
- Selection Label TagPath 不变；
- Feature Label TagPath 不变；
- Relation Label TagPath 不变；
- 没有调用 heuristic fallback；
- XBF 来自上一 HEAD；
- parent revision 正确；
- Geometry A/B 一致。

禁止接受：

```python
status in (UNIQUE, AMBIGUOUS)
```

## 7.7 Gate

只有该 T2 通过，系统才可以称为：

```text
Cross-Revision Native Topology Naming MVP
```

---

# 8. P4：Relation Identity 与 tracked operations v2

## 8.1 当前问题

Writer 使用：

```text
1001 + relation index
1 + subshape index
```

这是执行顺序，不是业务身份。

tracked operation 的 `source_key` 仍可能是：

```text
face_3
edge_7
inst_2_face_5
```

这些不能跨 Revision。

## 8.2 SourceEntityRef

```python
@dataclass(frozen=True, slots=True)
class SourceEntityRef:
    component_id: str
    feature_id: str
    construction_role_id: str | None
    selection_id: str | None
    entity_kind: TopologyEntityKind
```

调用 tracked operation 前，由上游解析并传入。

tracked operation 不得自行把数组下标升级为稳定 identity。

## 8.3 RelationKey

```python
@dataclass(frozen=True, slots=True)
class RelationKey:
    feature_id: str
    source_entity_ref: SourceEntityRef
    evolution_kind: EvolutionKind
    relation_role: str
```

通过 StableLabelIndex 分配 Relation Label。

## 8.4 1→N 关系

默认一个逻辑 relation label：

```python
builder = TNaming_Builder(relation_label)
for new_shape in new_shapes:
    builder.Generated(old_shape, new_shape)
```

禁止默认以 kernel 返回顺序为每个新 shape 生成稳定子 ID。

只有业务语义明确区分分支时，才创建独立 Selection。

## 8.5 Production Validation

`LiveEvolutionRelation.validate()` 禁止使用裸 `assert`。

改为：

```python
raise InvalidEvolutionRelationError(...)
```

因为 `python -O` 会删除 assert。

## 8.6 Pattern 必须重写

当前 Pattern 的 final Fuse history 缺失。

必须使用可返回 history 的 Boolean 算法，并捕获：

```text
source
→ transformed copy
→ intermediate fuse result
→ final pattern result
```

要求：

- 每一步 Fuse `IsDone()`；
- 失败立即抛错；
- 记录 Modified/Generated/Deleted；
- 无 final Fuse history 时 `history_complete=False`；
- enforce 模式下 required Selection 不得依赖不完整 history。

## 8.7 Unify

必须测试真正 N→1：

- 多个 old face；
- 一个 merged face；
- Selection 从 old set 解到 merged face；
- 不允许使用指纹自动绑定。

## 8.8 枚举顺序扰动测试

人为改变：

- input face iteration；
- relation list order；
- component execution order；

Stable Tag 必须不变。

---

# 9. P5：Selection Service v3

## 9.1 当前问题

- Policy/Contract 读取依赖不安全 API，可能直接返回 None；
- 解析异常 fail-open；
- `resolved_shapes` 可能仍是 Compound；
- entity 去重不可靠；
- normal/axis/radius/curve 语义没有完整实现；
- Delete Solve 可能 native crash；
- Solve 仍在主进程调用。

## 9.2 安全元数据读取

使用 P1 compat reader。

required Selection：

- Policy 缺失 → `INVALID_POLICY`；
- Contract 损坏 → `INVALID_CONTRACT`；
- 不得按默认 FACE/EXACT_ONE 继续。

## 9.3 真实实体拆分

```python
def explode_entities(
    shape: TopoDS_Shape,
    entity_kind: TopologyEntityKind,
) -> tuple[TopoDS_Shape, ...]:
    ...
```

去重优先使用：

- `TopTools_IndexedMapOfShape`；
- 或 `IsSame()` 两两判断。

禁止依赖已知不稳定的 `HashCode()`。

## 9.4 完整 Resolution Status

```text
UNIQUE
SET
AMBIGUOUS
DELETED
UNRESOLVED
SEMANTIC_MISMATCH
INVALID_POLICY
INVALID_CONTRACT
VALIDATION_UNAVAILABLE
NATIVE_CRASH
INVALID_DOCUMENT
```

## 9.5 语义验证

至少实现：

### FACE

- surface type；
- planar normal；
- cylinder/cone axis；
- radius range；
- area range；
- centroid zone；
- orientation。

### EDGE

- curve type；
- line direction；
- circle radius/axis；
- length range；
- adjacency role。

无法执行已声明检查时返回：

```text
VALIDATION_UNAVAILABLE
```

不得默认为通过。

## 9.6 Delete 处理

### 前置判定

若 native history 明确显示 Selection 目标被 Delete：

```text
allow_deleted=True  → DELETED
allow_deleted=False → REQUIRED_FAILURE
```

避免进入已知 crash 路径。

### Solve Worker

新增：

```text
topology/ocaf/solve_worker.py
```

所有正式跨 Revision Solve 在子进程执行。

输入：

```json
{
  "xbf_path": "...",
  "selection_ids": [],
  "valid_label_scopes": [],
  "required": true
}
```

输出：

```json
{
  "status": "...",
  "resolutions": [],
  "native_exit_code": 0
}
```

若 Access Violation：

```text
NATIVE_CRASH
```

而不是让主 Pipeline 退出。

## 9.7 T1/T4/T8

- T1：单 Revision 精确 FACE；
- T4：Delete，不崩溃，分类正确；
- T8：Fillet/Chamfer EDGE 跨 Revision。

---

# 10. P6：CAE Gate 真正接入

## 10.1 当前问题

CAE preflight 目前：

- 没有实际检查 `allowed_entity_kinds`；
- resolution 中 entity kind 可能为空；
- 主要检查 status/cardinality；
- 未集成到正式 Pipeline；
- 测试可能只断言返回 bool，而非必须 True；
- required binding 失败后没有证明 solver 不启动。

## 10.2 Binding Schema

```python
@dataclass(frozen=True, slots=True)
class CaeBinding:
    binding_id: str
    selection_id: str
    required: bool
    allowed_entity_kinds: tuple[TopologyEntityKind, ...]
    cardinality: CardinalityPolicy
    allowed_statuses: tuple[SelectionResolutionStatus, ...]
    require_native_proof: bool = True
    require_complete_history: bool = True
```

## 10.3 Gate 条件

required binding 必须同时满足：

- resolution status 合法；
- entity kind 合法；
- exact count 合法；
- semantic contract 通过；
- proof class 是 native history；
- history_complete；
- 无 heuristic；
- 无 native crash；
- XBF/manifest hash 匹配当前 Revision。

## 10.4 Pipeline 接线

执行顺序：

```text
Selection Solve
→ CAE preflight
→ preflight ok
→ Solver Adapter
```

required 失败时：

```text
solver_start_count == 0
```

必须有测试验证。

## 10.5 resolved shape 交付

不要只传 face index。

可以选择：

- OCAF Label entry；
- 单独导出 resolved BREP；
- 或同进程传真实 Shape Handle。

跨进程 solver 建议使用：

```text
selection_id
label_entry
revision_id
resolved_shape_brep
manifest_hash
```

---

# 11. P7：Revision Artifact 与完整 E2E

## 11.1 T3～T12

| ID | 场景 | 最终要求 |
|---|---|---|
| T0 | XBF 基础 | 保持 |
| T1 | 单 Revision FACE | 唯一、精确语义 |
| T2 | 三进程 Modify | 真正 old→new |
| T3 | 1→N Split | 顺序扰动不影响 relation identity |
| T4 | Delete | 不崩溃、正确分类 |
| T5 | N→1 Unify | 唯一 merged entity |
| T6 | Construction Roles | 参数变化仍稳定 |
| T7 | Pattern 周期相似面 | instance role 稳定 |
| T8 | Fillet/Chamfer EDGE | EDGE 精确恢复 |
| T9 | 原子回滚 | HEAD 不受失败影响 |
| T10 | ASCII/中文路径 | 全链路通过 |
| T11 | CAE Gate | required 失败不启动 solver |
| T12 | Text-to-CAD E2E | IR→3 Rev→Selection→CAE |

## 11.2 T12 必须覆盖

```text
自然语言/Canonical G-CAD
→ 受控几何
→ Rev1 保存
→ 参数修改 Rev2
→ Boolean/Fillet Rev3
→ Selection Solve
→ CAE preflight
→ Solver dry-run
→ artifact bundle
```

## 11.3 Corrupted XBF

所有不可信 XBF 的读取必须在子进程。

仅检查文件小于 8 字节不足以防止 native crash。

验证：

- random garbage；
- truncated file；
- valid header + corrupt payload；
- wrong format；
- old schema；
- duplicate index。

---

# 12. 文件级改造清单

## 必改

```text
topology/ocaf/compat.py
topology/ocaf/label_index.py
topology/ocaf/schema.py
topology/ocaf/models.py
topology/ocaf/document.py
topology/ocaf/repository.py
topology/ocaf/writer.py
topology/ocaf/selection_service.py
topology/ocaf/cae_preflight.py
topology/ocaf/tracked_ops/pattern.py
pipeline/run.py
runtime/context.py
```

## 建议新增

```text
topology/ocaf/revision.py
topology/ocaf/lineage.py
topology/ocaf/manifest.py
topology/ocaf/verify_worker.py
topology/ocaf/solve_worker.py
topology/ocaf/artifact_bundle.py
tests/test_stable_label_index_v2.py
tests/test_true_t2_modify.py
tests/test_pipeline_topology_e2e.py
tests/test_failure_injection.py
tests/test_cae_gate_e2e.py
```

## 建议删除或降级

- 旧 heuristic selector 不得进入 required 自动绑定；
- 仅测试模块字段、不调用正式 Pipeline 的“模式测试”应降级为单元测试；
- 删除任何把 `copy2` 称为 atomic publish 的注释；
- 删除吞异常后继续作为正常结果的代码；
- 报告中与源码不符的 Pattern Fuse history 声明。

---

# 13. Schema 版本与迁移

建议升级：

```text
gcad_topo_v4@ocaf_v2
```

旧文档策略：

- v1 只读；
- 不自动猜测 Stable ID；
- 不通过几何指纹迁移拓扑身份；
- 若索引不完整，要求从 Canonical IR 重新生成 lineage；
- migration 必须生成独立新 lineage；
- 原文件不原地修改。

---

# 14. 代码 Agent 的实施顺序

## PR-A：审计与 Index v2

- Manifest；
- safe attribute reader；
- index schema；
- fail-closed load；
- true cross-process index tests。

## PR-B：Artifact Bundle Pipeline

- 正式 `TopologyRunConfig`；
- 正确 stage 顺序；
- immutable revision；
- verify worker；
- failure injection。

## PR-C：Revision Core + True T2

- RevisionRecord；
- HEAD；
- parent conflict；
- CurrentResult Modify；
- 三进程精确 T2。

## PR-D：Relation Identity + Pattern/Unify

- SourceEntityRef；
- RelationKey；
- no positional tags；
- full Fuse history；
- order perturbation tests。

## PR-E：Selection v3

- policy/contract；
- entity explode/dedup；
- semantic validation；
- crash-isolated worker；
- Delete/EDGE tests。

## PR-F：CAE Gate

- allowed kinds；
- proof/history gate；
- solver no-start tests；
- Pipeline integration。

## PR-G：T3～T12 与清理

- 完整 E2E；
- corrupted XBF；
- performance；
- docs/status sync。

每个 PR 未通过 Gate 时，不得继续下一 PR。

---

# 15. 每个 PR 必须提交的交付信息

```text
1. Git SHA
2. 修改文件
3. 删除文件
4. 公开 API 变化
5. OCAF Schema 变化
6. Migration 影响
7. 测试命令
8. Passed / Failed / Skipped / Ignored
9. Failure injection
10. Native crash worker 结果
11. 未解决问题
12. Gate 是否通过
```

禁止只写：

```text
All tests passed
```

---

# 16. 下一阶段 Definition of Done

满足以下全部条件后，才可以把状态升级为：

```text
Cross-Revision Native Topology Naming MVP
```

1. StableLabelIndex 真正从 OCAF 恢复，不重新 ensure；
2. counters 不冲突、Tag 不复用；
3. Pipeline 公开入口可设置 off/audit/enforce；
4. XBF/STEP/metadata 属于一个不可变 Revision Bundle；
5. Geometry/STEP gate 在 OCAF 发布前完成；
6. 失败注入不会改变上一 HEAD；
7. Revision parent/head 冲突可检测；
8. CurrentResult 后续 Revision 使用 Modify；
9. 真实三进程 T2 只接受 UNIQUE；
10. 精确 FACE 的面积、法向、质心正确；
11. Relation Label 不依赖列表顺序；
12. Pattern final Fuse history 完整；
13. Selection policy/contract 跨进程恢复；
14. Delete Solve native crash 被隔离；
15. CAE preflight 在 Pipeline 中实际执行；
16. required binding 失败时 solver 不启动；
17. Geometry A/B off/audit/enforce 一致；
18. v4 状态报告中的测试文件均可在声明 SHA 找到；
19. CI Manifest 可复现；
20. 没有 required 路径的 silent `except: pass`。

---

# 17. 最终审查结论

当前版本的最大进步是：系统已经不再停留在“XBF 能不能保存”的阶段，Live History、Writer、Selection、Index、Pipeline 都开始成形。

但当前最大的风险也发生了变化：

> 风险不再是底层持久化失败，而是上层模块各自通过测试，却没有共享同一个稳定身份、同一个 Revision、同一个事务和同一个 CAE Gate。

因此下一阶段不要继续堆叠更多操作支持。

正确主线是：

```text
真实 Index
→ 原子 Revision
→ 真实 Modify
→ 稳定 Relation
→ 精确 Solve
→ CAE Gate
```

完成这条主线后，Boolean、Fillet、Pattern、Unify 等 operation coverage 才具有真正的系统价值。
