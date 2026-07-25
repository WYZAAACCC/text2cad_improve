---
title: "Text-to-CAD / OCAF 持久化拓扑命名落地实施指导书"
document_version: "v1.0"
source_format: "DOCX"
source_file: "Text-to-CAD_OCAF持久化拓扑命名_代码Agent实施指导书_v1.0.docx"
target_reader: "代码 Agent"
---

# Text-to-CAD / OCAF 持久化拓扑命名落地实施指导书

> 供代码 Agent 直接执行的工程实施规范

| 字段 | 值 |
| --- | --- |
| 目标仓库 | WYZAAACCC/text2cad_improve |
| 审阅分支 | main |
| 原审阅基线 | ed6f6603e77d903dccd09966f792d7ddc2986501 (已过时) |
| **实际基线** | **678c073b6380caefa6a8be7484ec0e294dd2f405** (V3 回退后干净基线) |
| **基线状态** | V3 topology 模块源文件**已完全删除**，仅 `__pycache__/*.pyc` 残留 |
| 文档版本 | v1.1 (基于实际环境修正) |
| 编制日期 | 2026-07-24 |
| 修正日期 | 2026-07-24 |
| **实际环境** | Python 3.11.9 · CadQuery 2.7.0 · OCP 7.8.1.1 · OCAF/TNaming 全可用 |
| 实施目标 | 原 CadQuery/OCCT 运行路径单次建模 + 同 builder History + OCAF/TNaming + CAE 失败关闭 |

状态：可执行设计基线。所有 OCP Python 重载名称必须在目标环境先做 smoke test，禁止凭文档版本猜测。

## 文档控制与使用方式

> 给代码 Agent 的总指令：本文件是实施合同。先完成 P0 基线冻结与 ABI 审计，再按 PR-1 至 PR-7 顺序推进。不得直接从 OCAF Writer 开始，不得用第二次 OCCT 重放冒充原 builder 历史，不得以 Face 序号、几何最近邻或数组顺序进行权威绑定。

本指导书继承此前交接文档的核心决策：OCAF/TNaming 作为几何演化事实与选择求解内核；权威历史来自原 Text-to-CAD 运行路径中的实际 builder；采集必须只读、失败隔离；允许 unresolved，禁止静默误绑定。

本文件进一步修正了一个容易被忽略的边界：同一次 revision 内，原 builder History 可以形成 EXACT_KERNEL_HISTORY；跨 revision 若每次都是全新 CadQuery 重建，还需要稳定 feature identity、同一 OCAF 文档更新和 revision bridge。不能把“每次都采集了 builder history”自动等同于“跨 revision 已经获得精确连续身份”。

### 执行优先级

| 优先级 | 含义 | 处理规则 |
| --- | --- | --- |
| P0 | 当前主分支的编译、ABI、版本和真实调用链基线 | 未通过不得接 OCAF |
| P1 | 单次真实建模与真实 History 同源 | 先覆盖 extrude/revolve/boolean |
| P2 | OCAF 写入、保存、重开 | 必须失败隔离与原子保存 |
| P3 | Selector 与跨 revision | 必须通过扰动和临界测试 |
| P4 | Registry/CAE 桥接 | 关键 CAE 错误绑定率为 0 |

## 目录

- 1. 目标、范围与验收定义
- 2. 当前仓库现状与阻断性缺陷
- 3. 技术原理与不可变规则
- 4. 目标架构与信任边界
- 5. P0 基线冻结与代码审计
- 6. 目标模块、文件与接口合同
- 7. Live History 数据模型
- 8. CadQuery/OCCT 原路径接入
- 9. 各类几何操作的实施策略
- 10. OCAF/XCAF 文档、Label 与 TNaming 写入
- 11. Selector、PID 与跨 revision 更新
- 12. 现有 TopologyRegistry 的迁移与双写
- 13. 缓存、并发、进程和故障隔离
- 14. 失败语义、证明等级与 CAE 门禁
- 15. 测试矩阵与验收标准
- 16. 分阶段 PR 实施计划
- 17. 代码 Agent 最终执行清单
- 附录 A. 建议代码骨架
- 附录 B. 操作覆盖矩阵
- 附录 C. 交付物与验收勾选表
- 附录 D. 源码与官方文档依据

## 1. 目标、范围与验收定义

### 1.1 最终目标

在不改变现有 G-CAD 编译、方言调度和几何结果的前提下，将每个拓扑改变节点实际调用的 CadQuery/OCCT builder 历史，在 builder 仍存活时提取并写入 OCAF/TNaming，形成可持久化、可重开、可重算、可审计的拓扑选择基础，为后续 NamedTopologySet、载荷、约束、接触与网格区域提供失败关闭的绑定能力。

**目标主链**

```text
Canonical IR node
    -> original handler
    -> one and only one CadQuery/OCCT build
    -> result TopoDS_Shape + same-builder History
    -> staged live evolution batch
    -> geometry validation
    -> OCAF/TNaming commit
    -> Selector / PID / proof class
    -> CAE preflight
```

### 1.2 成功的定义

- 启用 History Probe 后，原 CAD 几何、STEP、异常类型、操作顺序和 builder 调用次数不发生变化。
- 权威演化关系可追溯到实际生成交付几何的同一个 builder，且不会再为历史执行第二次 Build/Perform。
- OCAF 文档可保存为 XBF，关闭进程并重新打开后，Label、NamedShape、PID 映射和 Selector 均可恢复。
- 轻微参数扰动时，关键选择能正确 Solve；分裂、合并、删除或歧义时返回结构化状态，不静默选“最近面”。
- 自动有限元只消费满足证明等级、类型、上下文、基数与语义不变量的 NamedTopologySet。
- 关键 CAE 测试中的错误绑定率为 0；允许自动解析失败。

### 1.3 非目标

- 不重写 OCCT 的 B-Rep、布尔求交、曲面或容差算法。
- 不把 OCAF 变成第二条独立建模主流程。
- 不在第一阶段删除现有 TopologyRegistry、sidecar、semantic naming 或 CAE bridge。
- 不承诺所有算法都具有完整内核历史；未覆盖操作必须明确降级。
- 不把外部 STEP、Face 序号、几何指纹或 LLM 猜测升级为 EXACT_KERNEL_HISTORY。

## 2. 当前仓库现状与阻断性缺陷

审阅基线 main 最新可见提交为 ed6f6603e77d903dccd09966f792d7ddc2986501。**⚠️ 基线已变更**: 本文档原基于 ed6f6603（含 V3 topology 部分集成代码），但当前 main 已被 force-push 到 678c073。V3 topology 模块的全部源文件（25+ .py 文件）已被删除，仅 `__pycache__/*.pyc` 残留。代码 Agent 必须基于 678c073 工作——这是一个**比原基线更干净**的起点，不需要修复原 P0-01 至 P0-06。

### 2.1 当前几何与拓扑链路

```text
CanonicalNode
  -> dialects/executor.py
  -> dialect handler
  -> CadQuery Workplane / Shape API
  -> OCP bindings
  -> OCCT builder
  -> RuntimeObjectStore
  -> current TopologyDelta / TopologyRegistry
  -> STEP / metadata
```

当前系统已经存在 TopologyEntityRecord、TopologyRelation、TopologyDelta、ProofClass、NamedTopologySet、TopologyRegistry 事务和 CAE 失败关闭等基础，但这些主要是自研语义与运行时投影，并非 OCAF/TNaming。

### 2.2 已确认的基线状态 (v1.1 修正, 基于 678c073)

| 编号 | 检查项 | 实际状态 |
| --- | --- | --- |
| B-01 | topology/ 源文件 | ❌ **全部缺失** — 25+ .py 文件被删除, 仅 __pycache__/*.pyc 残留 |
| B-02 | OperationResult ABI | ✅ **正常** — executor.py 不读取 topology_delta (V3 代码已回退) |
| B-03 | OperationSpec ABI | ✅ **正常** — executor.py 不读取 topology_mode (V3 代码已回退) |
| B-04 | OperationCache ABI | ✅ **正常** — executor.py 用 get(node)/put(node,result), 签名匹配 |
| B-05 | Boolean 二次 Build | ✅ **不存在** — history_aware_boolean_* 函数已随 V3 回退删除 |
| B-06 | PID 数组顺序猜测 | ✅ **不存在** — mod_i%len/pop(0) 等逻辑已随 V3 回退删除 |
| B-07 | History 异常被吞掉 | ✅ **不存在** — KernelHistoryAdapter 等已随 V3 回退删除 |
| B-08 | CadQuery History API | ❌ **CadQuery 2.7.0 不提供** — shapes.History 类不存在, free functions 不接受 history= 参数 |
| B-09 | OCCT Builder History | ✅ **完全可用** — 见 §8bis |
| B-10 | OCAF/TNaming 绑定 | ✅ **完全可用** — 见 §10 smoke test 结果 |
| B-11 | CadQuery clean History | ❌ **不可用** — ShapeUpgrade_UnifySameDomain 无 History() (OCP 7.8.1.1) |

> **v1.1 结论**: 当前基线是 V3 回退后的干净状态。不需要修复旧的 ABI 问题——它们从未存在于此基线。唯一真正的阻断项是 CadQuery 2.7.0 不提供 History API，但 OCCT Builder 层 History 完全可用，可通过包装层解决。

> **v1.1 阻断规则修正**: 原 v1.0 的 P0-04/05/06 阻断条件在当前基线 678c073 **不适用**（V3 topology 代码已回退）。当前唯一的阻断项是: **确认 TrackedOperation 产生的几何与 CadQuery 原路径完全一致**（A/B 测试）。在 A/B 验证通过前，不得将任何 TrackedOperation 接入 dialect handler。

## 3. 技术原理与不可变规则

### 3.1 两种 Builder 必须严格区分

| 对象 | 职责 | 是否执行几何 | 核心输出 |
| --- | --- | --- | --- |
| OCCT 建模 builder | Prism、Revolve、Boolean、Fillet、Unify 等算法 | 是 | result Shape + Generated/Modified/Deleted |
| OCAF TNaming_Builder | 把已知 old/new Shape 演化写到 Label | 否 | TNaming_NamedShape |

OCAF 不会读取一段操作日志后自动执行建模。应用必须在实际 builder 完成后提供真实 TopoDS_Shape old/new 对。操作名称、参数和自然语言只属于审计元数据。

### 3.2 History 的权威数据

- 真实输入 TopoDS_Shape，含目标、工具、profile、path、selected edge/face。
- 真实结果 TopoDS_Shape 和当前 Context Shape。
- Generated(old)、Modified(old)、IsDeleted/IsRemoved(old) 的结果。
- Prism/Revolve 的 FirstShape、LastShape，以及多 builder 的 phase/suboperation 顺序。
- builder 类型、有效容差、fuzzy/glue/non-destructive 等真实算法选项。
- History 完整性、缺失阶段、警告与版本 manifest。

### 3.3 十二条不可变规则

| 规则 | 要求 |
| --- | --- |
| R-01 | 主几何只执行一次。 |
| R-02 | History Probe 不得修改输入 Shape、选择、参数、容差、调用顺序、返回值或异常传播。 |
| R-03 | 不得为了采集历史再次 Build/Perform。 |
| R-04 | 必须在 builder 和输入/输出 Shape 仍存活时提取 live history。 |
| R-05 | live TopoDS_Shape 不得 JSON 化、不得跨进程传输、不得以 Python id 持久化。 |
| R-06 | Face/Edge 枚举序号不得作为跨 rebuild PID。 |
| R-07 | 无关系、接口不可用和采集失败必须是不同状态。 |
| R-08 | OCAF 写入、保存或 Selector 失败不得改变原 CAD 几何；CAE 必须关闭。 |
| R-09 | 一个 TNaming_Builder 只写一种 evolution；不同 evolution 使用不同 Label。 |
| R-10 | clean/fix/unify/sewing/MakeSolid 等改变拓扑的后处理必须独立成 phase。 |
| R-11 | 跨 revision 必须保留 stable node_id/feature identity；歧义时不复用旧 Label。 |
| R-12 | 对关键 CAE，错误绑定率优先于解析率；unresolved 是合法安全结果。 |

## 4. 目标架构与信任边界

**目标架构**

```text
G-CAD compiler / Canonical IR
        |
        v
Unified operation executor
  - creates TopologyCaptureScope
  - disables incompatible cache
        |
        v
Tracked CadQuery adapter
  - executes original operation once
  - receives original result
  - extracts same-builder history
        |
        +------> RuntimeObjectStore / geometry validation
        |
        v
Live TopologyEvolutionBatch (in-process only)
        |
        v
OCAF document transaction
  - stable labels
  - TNaming_NamedShape
  - TNaming_Selector
  - atomic XBF save
        |
        v
SemanticTopologyBridge
  - PID
  - semantic role
  - lineage policy
  - proof class
        |
        v
NamedTopologySet / CAE preflight
```

### 4.1 权威边界

| 层 | 权威职责 | 禁止事项 |
| --- | --- | --- |
| G-CAD 编译器 | 节点依赖、参数、执行顺序、feature identity | 不从 OCAF 反向决定几何参数 |
| CadQuery/OCCT | 真实 B-Rep 构建和本次运行内核历史 | 不承担业务语义和 CAE 策略 |
| Capture Adapter | 只读提取 live history 并标准化 | 不得重建或猜测关系 |
| OCAF/TNaming | 保存演化事实、命名结构、Selector 求解、文档持久化 | 不自动理解 fixed_face/hole_wall |
| TopologyRegistry | PID、语义、split/merge、proof、CAE policy | 不再自行伪造内核 history |
| CAE Bridge | 解析集合、检查证明与门禁 | 不得 fallback 到最近面 |

### 4.2 事务边界

几何 builder 必须先完成，History 必须立即提取到 node staging buffer；几何健康检查通过后，才开启 OCAF command 写入。OCAF 提交成功后再更新业务 Registry。任一阶段失败时，各层按下列顺序回滚：

1. 几何失败：沿用现有 required/optional 语义；不得生成 OCAF 事件。
1. History 提取失败：CAD 可成功；topology_capture=failed/partial；required_for_cae 时 cae_ready=false。
1. OCAF 写入失败：AbortCommand；保留 CAD 输出；不提交 Registry。
1. Registry 投影失败：回滚 Registry 事务；OCAF 本轮可 Abort 或标记 orphaned，不能形成双写分裂。
1. XBF 保存失败：内存状态不能宣称持久化成功；保留上一版 XBF；输出 topology_status。

## 5. P0 基线冻结与代码审计

### 5.1 代码 Agent 第一轮只允许做审计

**基线命令**

```bash
git checkout main
git pull --ff-only
git rev-parse HEAD
git status --porcelain
python -VV
python -m pip freeze > artifacts/baseline/pip-freeze.txt
python -m compileall integrations/engineering_tools/src
python -m pytest integrations/engineering_tools/tests -q

# 记录真实模块位置和 API
python - <<'PY'
import cadquery, OCP, inspect
from cadquery.occ_impl import shapes
print('cadquery=', getattr(cadquery, '__version__', 'unknown'))
print('OCP=', getattr(OCP, '__version__', 'unknown'))
print('shapes.py=', inspect.getsourcefile(shapes))
print('History=', hasattr(shapes, 'History'))
print('cut=', inspect.signature(shapes.cut))
print('extrude=', inspect.signature(shapes.extrude))
print('revolve=', inspect.signature(shapes.revolve))
print('clean=', inspect.signature(shapes.clean))
PY
```

### 5.2 必须生成的审计产物

- baseline_manifest.json：repo SHA、Python、CadQuery、OCP、OCCT、OS、架构、定制 wheel SHA。
- operation_call_graph.md：每个方言 op 到 Workplane/Shape/free function/OCP builder 的真实链。
- history_coverage.csv：操作、路径、builder、History API、后处理、完整度、测试状态。
- abi_findings.md：OperationResult、OperationSpec、OperationCache、TopologyTransaction 的签名一致性。
- ocaf_binding_smoke.json：OCP 是否暴露 TDF/TDocStd/TNaming/XCAF/BinXCAF 以及重载结果。

### 5.3 OCAF/OCP smoke test 必测接口

| 模块 | 接口 | 验收 |
| --- | --- | --- |
| XCAFApp | GetApplication / GetApplication_s | 能取得应用实例 |
| BinXCAFDrivers | DefineFormat / DefineFormat_s | 注册 BinXCAF |
| TDocStd_Document | 构造、Main、NewCommand、CommitCommand、AbortCommand | 事务可用 |
| TDF_Label | NewChild/FindChild 或 TagSource 分配 | 可稳定创建层级 |
| TNaming_Builder | Generated(new)、Generated(old,new)、Modify、Delete | 重载可调用 |
| TNaming_Selector | Select(selection,context)、Solve | 选择可建立与更新 |
| TNaming_Tool | GetShape | 可读取当前结果 |
| TDocStd_Application | SaveAs、Open、Close | XBF 可保存重开 |

> 版本规则：OCP 的静态方法可能带 _s 后缀，容器模板类型的 Python 名称也可能变化。不得把本文示例中的具体拼写视为无需验证的事实；必须通过 ocaf_compat.py 统一适配。

## 6. 目标模块、文件与接口合同

### 6.1 新增目录

```text
generative_cad/topology/ocaf/
├── __init__.py
├── compat.py                 # OCP version/API compatibility
├── context.py                # contextvars node/phase scope
├── models.py                 # live batch + status models
├── capture_session.py        # node staging / commit / abort
├── cadquery_adapter.py       # History/Op export
├── occt_adapter.py           # direct builder/BRepTools_History export
├── document.py               # XCAF application/document/session
├── labels.py                 # stable label allocation and indexes
├── writer.py                 # TNaming_Builder writes
├── selectors.py              # Select/Solve/GetShape
├── revision_bridge.py        # previous feature result -> current feature result
├── semantic_bridge.py        # OCAF -> existing Registry/PID
├── coverage.py               # operation coverage registry
├── diagnostics.py            # structured failures and reports
└── tests/
    ├── test_ocaf_smoke.py
    ├── test_capture_no_effect.py
    ├── test_extrude_history.py
    ├── test_boolean_history.py
    ├── test_ocaf_persistence.py
    ├── test_selector_rebuild.py
    └── test_cae_fail_closed.py
```

### 6.2 必须修改的现有文件

| 文件 | 修改要求 |
| --- | --- |
| dialects/results.py | 为 OperationResult 增加 topology_capture_token 或 topology_delta；建议 live Shape 不进入 Pydantic。 |
| dialects/operation.py | 正式增加 topology_capture_policy、history_completeness、topology_phases。 |
| dialects/executor.py | 创建 scope、控制 cache、commit/abort capture、OCAF/Registry 双事务。 |
| runtime/context.py | 增加 revision_id、capture mode、OcafDocumentSession、CaptureSession、status。 |
| runtime/cache.py | 先修 ABI；required capture 时绕过；以后升级 artifact bundle。 |
| composition/handlers.py | 删除第二次 Boolean 和数组猜测 PID；使用 tracked adapter。 |
| topology/history_wrappers.py | 冻结为 legacy/audit；不得再作为权威主路径。 |
| topology/models.py | 扩展 proof class、OCAF label/selector 映射字段。 |
| builder/runtime entry | 创建/打开 XBF、传 revision、保存 topology manifest。 |
| CAE bridge | PID 先通过 OCAF Selector 解析，再执行 proof/type/cardinality policy。 |

### 6.3 接口总览

```python
class TopologyCaptureSession:
    def begin_node(self, scope) -> None: ...
    def stage(self, batch) -> str: ...
    def commit_node(self, node_id) -> CaptureCommitReceipt: ...
    def abort_node(self, node_id, reason) -> None: ...

class TrackedCadQueryAdapter:
    def cut(self, target, tool, *, options, event_name) -> TrackedShapeResult: ...
    def fuse(self, left, right, *, options, event_name) -> TrackedShapeResult: ...
    def extrude(self, profile, vector, *, options, event_name) -> TrackedShapeResult: ...
    def revolve(self, profile, axis, *, options, event_name) -> TrackedShapeResult: ...

class OcafDocumentSession:
    def begin_node(self, node_id) -> None: ...
    def write_batch(self, batch) -> OcafCommitReceipt: ...
    def commit_node(self) -> None: ...
    def abort_node(self) -> None: ...
    def save_atomic(self, path) -> None: ...

class SelectorManager:
    def create(self, pid, selection, context, invariants) -> SelectionRecord: ...
    def solve(self, pid, valid_scope=None) -> SelectionResolution: ...

class SemanticTopologyBridge:
    def project(self, receipt, registry_transaction) -> None: ...
```

## 7. Live History 数据模型

必须区分“进程内 live 数据”和“可持久化审计数据”。真实 TopoDS_Shape handle 只能在同一几何 worker 内短期存活；JSON sidecar 只保存 Label、PID、版本、数量、证明等级和诊断。

### 7.1 TopologyCaptureScope

```python
@dataclass(frozen=True)
class TopologyCaptureScope:
    schema_version: str
    document_id: str
    revision_id: str
    component_id: str
    node_id: str
    dialect: str
    operation: str
    operation_version: str
    sequence_index: int
    phase: str
    suboperation_index: int
    attempt_index: int = 0
```

### 7.2 EvolutionRelation 与 Batch

```python
class EvolutionKind(str, Enum):
    PRIMITIVE = 'primitive'
    GENERATED = 'generated'
    MODIFIED = 'modified'
    DELETED = 'deleted'

class HistoryQuality(str, Enum):
    EXACT_KERNEL = 'exact_kernel'
    PARTIAL_KERNEL = 'partial_kernel'
    SEMANTIC = 'semantic'
    UNAVAILABLE = 'unavailable'
    FAILED = 'failed'

@dataclass(frozen=True)
class EvolutionRelation:
    relation_id: str
    kind: EvolutionKind
    old_shape: TopoDS_Shape | None
    new_shapes: tuple[TopoDS_Shape, ...]
    source_role: str
    source_pid: str | None
    entity_type: str
    quality: HistoryQuality
    evidence: dict[str, Any]

@dataclass
class TopologyEvolutionBatch:
    scope: TopologyCaptureScope
    builder_kind: str
    builder_options: dict[str, Any]
    input_shapes: tuple[TopoDS_Shape, ...]
    result_shape: TopoDS_Shape
    context_shape: TopoDS_Shape
    relations: list[EvolutionRelation]
    first_shape: TopoDS_Shape | None
    last_shape: TopoDS_Shape | None
    history_complete: bool
    missing_phases: list[str]
    warnings: list[TopologyDiagnostic]
```

### 7.3 禁止使用的数据作为 PID

| 数据 | 可用范围 | 禁止用途 |
| --- | --- | --- |
| Face/Edge 枚举索引 | 单次快照调试 | 跨 rebuild PID |
| Python id() | 同一进程临时日志 | 持久身份、cache key |
| TopoDS_Shape.HashCode | 同进程 map 辅助；需理解 Location/Orientation | 内容哈希、跨进程身份 |
| 面积/质心/法向指纹 | 低证明候选与人工检查 | EXACT history |
| 操作名+参数 | 审计和 feature identity | old/new subshape 因果关系 |

### 7.4 状态模型

```text
TopologyBuildStatus {
  cad_build_status,
  capture_status,
  history_quality,
  ocaf_write_status,
  ocaf_save_status,
  selector_status,
  coverage_ratio,
  exact_relation_count,
  partial_relation_count,
  unresolved_count,
  ambiguous_count,
  cae_ready
}
```

## 8. CadQuery/OCCT 原路径接入 (v1.1 大幅修正)

### 8.0 关键发现: CadQuery 2.7.0 不提供 History API

验证结果（`python -c "from cadquery.occ_impl.shapes import History"` → `False`）:

- `cadquery.occ_impl.shapes.History` 类**不存在**
- `shapes.cut(s1, s2, tol, glue)` **不接受** `history=` 参数
- `shapes.extrude(s, d)` **不接受** `history=` 参数
- `shapes.revolve(s, p, d, a)` **不接受** `history=` 参数
- `shapes._update_history` 函数**不存在**

**结论**: 指导书 v1.0 中"MVP 优先调用 CadQuery free-function API 的 History 能力"的策略在当前 CadQuery 版本中**不可行**。

### 8.1 实际可用的 History 捕获路径

OCCT Builder 层 History 能力已通过 OCP 7.8.1.1 验证:

| Builder 类 | CadQuery 内部对应 | History 提取方式 | 已验证 |
|-----------|-----------------|-----------------|--------|
| `BOPAlgo_BOP` (CUT/FUSE/COMMON) | `shapes.cut/fuse` | `builder.SetToFillHistory(True)` → `builder.Perform()` → `builder.History()` | ✅ |
| `BRepAlgoAPI_Cut` | (备选, 更现代) | `builder.SetToFillHistory(True)` → `builder.Build()` → `builder.History()` | ✅ |
| `BRepPrimAPI_MakePrism` | `shapes.extrude` | `builder.Generated(face)` / `builder.Modified(face)` / `builder.FirstShape()` / `builder.LastShape()` | ✅ |
| `BRepPrimAPI_MakeRevol` | `shapes.revolve` | `builder.Generated(face)` / `builder.Modified(face)` / `builder.FirstShape()` / `builder.LastShape()` | ✅ |
| `BRepFilletAPI_MakeFillet` | `shapes.fillet` | 待验证 | ⬜ |
| `ShapeUpgrade_UnifySameDomain` | `shapes.clean` | **无 History 支持** (OCP 7.8.1.1) | ❌ |

### 8.2 修正后的接入策略: OCCT Builder 包装层

**核心思路**: 创建 `TrackedOperations` 模块，在 OCCT Builder 层面（而非 CadQuery 层面）包装，使用与 CadQuery 内部相同的 Builder 类，一次 Build 同时产出几何和 History。

```
不修改 CadQuery
    ↓
TrackedOperation 包装层 (新增)
    ├── 使用与 CadQuery 内部相同的 OCCT Builder
    ├── 启用 History 捕获
    ├── 执行一次 Build/Perform
    ├── 提取 History 数据
    └── 返回 (CadQuery Shape, History batch)  ← 与 CadQuery 几何完全一致
```

### 8.3 TrackedShapeResult

```python
@dataclass(frozen=True)
class TrackedShapeResult:
    result: cadquery.Shape          # 与 CadQuery 输出完全一致的几何
    capture_token: str              # 引用的 staged live batch
    diagnostics: tuple[TopologyDiagnostic, ...]
```

### 8.4 各操作实现策略

#### 8.4.1 Boolean (cut/fuse/common) — BOPAlgo_BOP 路径

CadQuery 的 `shapes.cut()` 内部使用 `BOPAlgo_BOP` + `SetOperation(BOPAlgo_CUT)`。我们的包装层使用**完全相同的 Builder**，增加 `SetToFillHistory(True)`:

```python
from OCP.BOPAlgo import BOPAlgo_BOP, BOPAlgo_CUT
from OCP.BRepTools import BRepTools_History

def tracked_cut(target_shape, tool_shape, tol=0.0, glue=None, scope=None) -> TrackedShapeResult:
    """与 shapes.cut() 几何完全一致, 同时捕获 History."""
    builder = BOPAlgo_BOP()
    builder.SetOperation(BOPAlgo_CUT)
    builder.SetToFillHistory(True)          # ★ 唯一区别: 启用 History
    _set_glue(builder, glue)                 # 复用 CadQuery 内部逻辑
    _set_builder_options(builder, tol)       # 复用 CadQuery 内部逻辑
    builder.AddArgument(target_shape.wrapped)
    builder.AddTool(tool_shape.wrapped)
    builder.Perform()                        # ★ 只执行一次
    result_shape = _compound_or_shape(builder.Shape())
    history = builder.History()              # ★ BRepTools_History 对象
    batch = export_boolean_history(history, target_shape, tool_shape, result_shape, scope)
    return TrackedShapeResult(
        result=cadquery.Shape.cast(result_shape),
        capture_token=stage_batch(batch),
        diagnostics=()
    )
```

**关键验证**: BOPAlgo_BOP 与 BRepAlgoAPI_Cut 产生相同体积 (box 20×20×10 cut box 10×10×12 → 均输出 volume=3000.00mm³)。

#### 8.4.2 Extrude — BRepPrimAPI_MakePrism 路径

CadQuery 的 `shapes.extrude()` 内部使用 `BRepPrimAPI_MakePrism`。我们的包装层使用**完全相同的 Builder**:

```python
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.gp import gp_Vec

def tracked_extrude(profile_shape, vector, scope=None) -> TrackedShapeResult:
    """与 shapes.extrude() 几何完全一致, 同时捕获 History."""
    results = []
    batches = []
    for el in _get(profile_shape, ("Vertex", "Edge", "Wire", "Face")):
        builder = BRepPrimAPI_MakePrism(el.wrapped, gp_Vec(*vector))
        builder.Build()                      # ★ 只执行一次
        results.append(builder.Shape())
        # ★ 从 builder 直接提取 (无 History() 方法, 用 Generated/Modified)
        batch = _export_prism_history(
            builder, el,
            first_shape=builder.FirstShape(),
            last_shape=builder.LastShape(),
            result_shape=builder.Shape(),
            scope=scope
        )
        batches.append(batch)
    result_shape = _compound_or_shape(results)
    return TrackedShapeResult(
        result=cadquery.Shape.cast(result_shape),
        capture_token=stage_batches(batches),
        diagnostics=()
    )
```

**BRepPrimAPI_MakePrism History 能力** (已验证):
- `builder.Generated(face)` → TopTools_ListOfShape (从 profile face 生成的结果面)
- `builder.Modified(face)` → TopTools_ListOfShape (被修改的面)
- `builder.FirstShape()` → TopoDS_Shape (起始截面形状)
- `builder.LastShape()` → TopoDS_Shape (终止截面形状)
- **注意**: 没有 `builder.HasHistory()` 和 `builder.History()` 方法 (与 BOPAlgo_BOP 不同)

#### 8.4.3 Revolve — BRepPrimAPI_MakeRevol 路径

与 Extrude 完全相同的模式，使用 `BRepPrimAPI_MakeRevol`:

```python
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
from OCP.gp import gp_Ax1, gp_Pnt, gp_Dir

def tracked_revolve(profile_shape, axis_origin, axis_dir, angle_deg, scope=None) -> TrackedShapeResult:
    builder = BRepPrimAPI_MakeRevol(
        profile_shape.wrapped,
        gp_Ax1(gp_Pnt(*axis_origin), gp_Dir(*axis_dir)),
        math.radians(angle_deg)
    )
    builder.Build()
    # ... 同 extrude 的 History 提取模式
```

**已验证**: `builder.Generated()`, `builder.Modified()`, `builder.FirstShape()`, `builder.LastShape()` 均可用。

#### 8.4.4 Clean / UnifySameDomain — 当前为 History 缺口 (v1.1 确认)

OCP 7.8.1.1 中 `ShapeUpgrade_UnifySameDomain` **没有 History() 方法**。这证实了指导书 v1.0 对 clean 的担忧。

**短期方案**: Boolean 后的 clean 步骤标记 `history_quality=PARTIAL_KERNEL`，在 OCAF 中记录 `missing_phases=["clean_unify"]`。

**长期方案**: 维护 CadQuery patch，为 `shapes.clean()` 内部创建 `ShapeUpgrade_UnifySameDomain` builder 后调用 `builder.History()`（如果 OCCT 版本升级后支持），或使用 BRepAlgoAPI_Fuse 的 fuzzy 模式替代 clean。

### 8.5 关于 CadQuery Workplane 路径

当前 dialect handler 调用链为:
```
handler → Workplane.extrude() → shapes.extrude() → BRepPrimAPI_MakePrism
```

**TrackedOperation 不改变 Workplane 层**。handler 将 Workplane 转换为 Shape 后调用 TrackedOperation，结果再包装回 Workplane 保持后续兼容性。对于简单的操作（rectangle extrude），可直接跳过 Workplane，使用 TrackedOperation:

```python
# 当前 handler:
solid = cq.Workplane(plane).rect(w, h).extrude(d)

# 改为:
profile = cq.Workplane(plane).rect(w, h)  # 生成 wire profile
tracked = tracked_extrude(profile.val(), (0, 0, d), scope=...)
solid = cq.Workplane(plane).newObject([tracked.result])
```

### 8.6 executor 接线 (修正)

不需要 OperationCache ABI 修改（当前缓存签名已匹配），不需要 OperationSpec 增加 topology_mode（extra=forbid 不受影响）。只需在 executor 中增加 capture scope 和 OCAF 事务:

```python
def execute_operation(node, op_spec, ctx):
    # Check cache only when capture is not required
    cache_allowed = not ctx.capture_session.requires_capture(node)
    if cache_allowed:
        cached = ctx.cache.get(node)
        if cached is not None:
            # ... existing cache logic
    
    # Execute handler (handler internally calls TrackedOperation)
    raw_result = op_spec.handler(node, ctx)
    
    # If handler returned TrackedShapeResult, stage the history
    if isinstance(raw_result, TrackedShapeResult):
        ctx.capture_session.stage(raw_result.history_batch)
    
    # ... existing validation and binding logic
```

## 9. 各类几何操作的实施策略 (v1.1 修正 — 基于实际 OCCT Builder History 能力)

### 9.0 两种 History API 模式

经过 OCP 7.8.1.1 实际验证，OCCT Builder 提供两种不同的 History 访问模式:

**模式 A: BRepTools_History 对象** (Boolean 操作 — BOPAlgo_BOP, BRepAlgoAPI_Cut/Fuse)

```python
builder.SetToFillHistory(True)   # 必须在 Build/Perform 之前调用
builder.Perform()                 # 或 builder.Build()
history = builder.History()       # 返回 BRepTools_History 对象
# history.Generated(shape) → TopTools_ListOfShape
# history.Modified(shape) → TopTools_ListOfShape
# history.IsRemoved(shape) → bool
```

**模式 B: Builder 直接方法** (Prism/Revolve — BRepPrimAPI_MakePrism/MakeRevol)

```python
builder.Build()                   # 必须先 Build
# builder.Generated(face) → TopTools_ListOfShape  (从输入面生成的结果)
# builder.Modified(face) → TopTools_ListOfShape   (被修改的面)
# builder.FirstShape() → TopoDS_Shape              (起始截面)
# builder.LastShape()  → TopoDS_Shape              (终止截面)
# 注意: 没有 builder.HasHistory() 或 builder.History() 方法!
```

### 9.1 Primitive

Box、Cylinder 等 primitive 可以在结果 Label 上使用 Generated(newShape)。若要长期引用顶面、底面、圆柱侧面，优先从原 primitive builder 的专用接口或确定性构造语义建立子 Label；禁止仅依据 Faces() 顺序。第一阶段可将 primitive 子面标为 DETERMINISTIC_CONSTRUCTION，待专用 builder 覆盖后提升证明。

### 9.2 Extrude / Revolve (v1.1 修正)

实际使用 `BRepPrimAPI_MakePrism` / `BRepPrimAPI_MakeRevol` (模式 B — Builder 直接方法)。

**CadQuery 内部调用链**: `shapes.extrude(s, d)` → `BRepPrimAPI_MakePrism(el.wrapped, vec).Build()` → `builder.Shape()`

**我们的包装层使用完全相同的 Builder**，在 `Build()` 后提取 Generated/Modified/FirstShape/LastShape:

| 源对象 | 提取方法 | 可派生语义锚点 |
| --- | --- | --- |
| profile edge | `builder.Generated(edge)` → lateral face | lateral_from_profile_edge |
| profile face | `builder.Generated(face)` → solid/shell | feature result |
| FirstShape | `builder.FirstShape()` | start_cap |
| LastShape | `builder.LastShape()` | end_cap |

**示例 — 从 profile face 提取生成的面**:
```python
builder = BRepPrimAPI_MakePrism(profile_face.wrapped, gp_Vec(0, 0, depth))
builder.Build()
result = builder.Shape()
# 提取 history
gen_faces = builder.Generated(profile_face.wrapped)  # TopTools_ListOfShape
# 遍历 gen_faces 创建 EvolutionRelation(kind=GENERATED, old_shape=profile_face, new_shapes=[...])
```

### 9.3 Boolean Cut/Fuse/Common (v1.1 修正)

实际使用 `BOPAlgo_BOP` + `SetToFillHistory(True)` + `History()` (模式 A — BRepTools_History)。

**CadQuery 内部调用链**: `shapes.cut(s1, s2, tol)` → `BOPAlgo_BOP()` → `SetOperation(BOPAlgo_CUT)` → `Perform()` → `builder.Shape()`

**我们的包装层使用完全相同的 Builder**, 增加 `SetToFillHistory(True)`:

```python
builder = BOPAlgo_BOP()
builder.SetOperation(BOPAlgo_CUT)
builder.SetToFillHistory(True)      # ★ 唯一新增
builder.AddArgument(target.wrapped)
builder.AddTool(tool.wrapped)
builder.Perform()                    # ★ 只执行一次
result = builder.Shape()
history = builder.History()          # BRepTools_History
# 遍历 source shapes, 查询:
#   history.Generated(source) → list of generated shapes
#   history.Modified(source) → list of modified shapes
#   history.IsRemoved(source) → bool
```

**已验证**: 与 BRepAlgoAPI_Cut 产生相同几何 (体积一致)。BOPAlgo_BOP 是 CadQuery 实际使用的路径，选择 BOPAlgo_BOP 而非 BRepAlgoAPI_Cut 可以最小化几何差异风险。

### 9.4 Fillet / Chamfer

记录 selected edge、输入 body 和相邻 face。新圆角/倒角面通常由 edge 生成，相邻 face 可能 Modified，原 edge 可能 Deleted。半径变化可能导致 contour 重组，必须允许 ambiguous/deleted。

### 9.5 Clean / UnifySameDomain (v1.1 确认: History 缺口)

**OCP 7.8.1.1 中 `ShapeUpgrade_UnifySameDomain` 没有 `History()` 方法**。这是当前版本的明确限制。

短期方案:
- Boolean 后的 clean 步骤标记 `history_quality=PARTIAL_KERNEL`
- 在 OCAF 中记录 `missing_phases=["clean_unify"]`
- 证明等级降级: Boolean output → Clean output 的关系无法从内核提取

中期方案:
- 若 OCCT 升级到支持 `ShapeUpgrade_UnifySameDomain.History()` 的版本，立即接入
- 或：用 fuzzy fuse (BOPAlgo_BOP + SetFuzzyValue) 替代 CadQuery clean，保持 History 完整链

> 证明降级：在 clean history 未接通前，Boolean 后的最终几何只能标记 PARTIAL_KERNEL_HISTORY。

### 9.6 Hollow / Shell / Sweep / Loft

这类操作往往包含多 builder、MakeSolid、sewing、fix、orientation 和 History remap。第一阶段不得宣称 complete。每个子阶段单独记录；未覆盖阶段写入 missing_phases。

### 9.7 Transform / Pattern / Assembly

纯 Location 变换通常不产生新的拓扑，但实例身份必须包含 prototype PID + occurrence_id + TopLoc_Location。Pattern 不能把相同原型多个实例的面混为一个。若 pattern 通过复制后 Boolean 合并，应分别记录 occurrence 生成和后续 Boolean。

### 9.8 外部 STEP

没有本系统 builder history 的外部 STEP 只能注册为 IMPORTED_SNAPSHOT。允许建立人工选择或低证明 fingerprint candidate，但禁止用于关键 CAE 的自动精确绑定。

## 10. OCAF/XCAF 文档、Label 与 TNaming 写入

### 10.1 选择 XCAF/BinXCAF

建议使用 XCAFApp_Application + BinXCAFDrivers + TDocStd_Document("BinXCAF")。虽然最小 BinOcaf 也能保存 TNaming，但系统后续存在组件、实例、材料和 CAE 需求，XCAF 更适合作为文档容器。

```python
# 已验证正确的构造方式 (OCP 7.8.1.1)
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFApp import XCAFApp_Application
from OCP.BinXCAFDrivers import BinXCAFDrivers
from OCP.TDocStd import TDocStd_Document

app = XCAFApp_Application.GetApplication_s()
BinXCAFDrivers.DefineFormat_s(app)
fmt = TCollection_ExtendedString('BinXCAF')  # ★ 必须用 TCollection_ExtendedString
doc = TDocStd_Document(fmt)                  # ★ 不接受 plain str
app.InitDocument(doc)
root = doc.Main()
doc.NewCommand()   # 开始事务
# ... TNaming 写入 ...
doc.CommitCommand()  # 提交事务
```

### 10.2 推荐 Label 树

```text
0:1  Main
└── DesignRoot
    ├── Metadata
    ├── Components
    │   └── <component label>
    │       ├── Prototype
    │       ├── Instances
    │       ├── Features
    │       │   └── <stable node label>
    │       │       ├── Result
    │       │       ├── RevisionBridge
    │       │       ├── Phases
    │       │       │   └── <phase/suboperation label>
    │       │       │       ├── Primitive
    │       │       │       ├── Generated
    │       │       │       ├── Modified
    │       │       │       └── Deleted
    │       │       └── Diagnostics
    │       └── Selections
    │           └── <persistent-id label>
    │               ├── Selector
    │               ├── SemanticRole
    │               ├── ProofClass
    │               └── ExpectedInvariants
    ├── NodeIndex
    ├── PersistentIdIndex
    ├── Revisions
    └── CAENamedSets
```

### 10.3 稳定 Label 分配

- 第一次遇到 node_id 时由 TagSource/NewChild 分配内部 Label，并保存 node_id 属性。
- NodeIndex 保存 node_id -> Label 引用；重开文档后先恢复索引。
- 同一 node_id 的参数修改必须更新原 Label，不得新建无关联 Label。
- PID 不等于 Label entry；外部 API 使用 PID，内部保存 PID -> Label。
- feature identity 歧义时创建新 Label，并将旧节点标记 tombstone/superseded。

### 10.4 TNaming 写入

```python
def write_relation(parent_label, relation):
    relation_label = labels.new_relation_label(
        parent_label,
        evolution=relation.kind,
        relation_id=relation.relation_id,
    )
    b = TNaming_Builder(relation_label)

    if relation.kind == PRIMITIVE:
        assert relation.old_shape is None
        for new in relation.new_shapes:
            b.Generated(new)
    elif relation.kind == GENERATED:
        for new in relation.new_shapes:
            b.Generated(relation.old_shape, new)
    elif relation.kind == MODIFIED:
        for new in relation.new_shapes:
            b.Modify(relation.old_shape, new)
    elif relation.kind == DELETED:
        b.Delete(relation.old_shape)
    else:
        raise UnsupportedEvolution(...)
```

一个 TNaming_Builder 只能写一种 evolution；同一种 evolution 可写多组 old/new 对。不要在同一个 Label 混用 Generated、Modify、Delete。

### 10.5 原子保存

```python
def save_atomic(app, doc, target: Path):
    tmp = target.with_suffix(target.suffix + '.tmp')
    status = compat.save_as(app, doc, tmp)
    ensure_store_status_ok(status)
    fsync_file(tmp)
    os.replace(tmp, target)
    fsync_directory(target.parent)
```

每次 revision 保留上一版 XBF 或内容哈希备份。SaveAs 失败时不得覆盖上一版文件，也不得把内存文档状态声明为持久化成功。

## 11. Selector、PID 与跨 revision 更新

### 11.1 Selector 建立

```python
selector = TNaming_Selector(selection_label)
ok = compat.selector_select(
    selector,
    selection=current_subshape,
    context=current_body_shape,
    geometry=False,
    keep_orientation=False,
)
if not ok:
    raise SelectorCreationError(...)

# Persist semantic metadata separately:
# pid, entity_type, component_id, occurrence_id,
# semantic_role, expected_invariants, proof_class
```

### 11.2 Solve 后仍需二次校验

- 结果是否非空、唯一或符合 set policy。
- 实体类型是否仍是预期 Face/Edge/Vertex。
- 是否属于正确 body、component 和 occurrence。
- 是否仍满足 semantic invariants：法向方向、圆柱轴、邻接 feature、面积范围等。
- 是否出现 split/merge，消费者是否允许集合。
- proof class 是否达到 load/constraint/contact 的策略阈值。

### 11.3 跨 revision 的关键修正

> 关键事实：新 revision 的 CadQuery builder History 只证明“本次重建内部”的输入到输出关系。它不能天然证明上一 revision 的某个旧面与本 revision 的新 profile edge 是同一设计身份。跨 revision 必须依赖稳定 feature identity、同一 OCAF 文档更新和 Selector/RevisionBridge 共同验证。

### 11.4 推荐跨 revision 流程

1. 打开上一 revision 的 XBF，同时加载上一版 Canonical IR/feature identity manifest。
1. 对当前 Canonical IR 运行 FeatureIdentityReconciler，产生 unchanged/modified/inserted/deleted/ambiguous。
1. 按依赖顺序重建节点。每个节点使用当前运行的真实 builder History 写入稳定 feature Label。
1. 对同一 stable node 的 feature result，读取上一版 Result Shape，建立 previous-result -> current-result 的 RevisionBridge。
1. RevisionBridge 的证明来源是稳定 feature identity 与操作合同，不得标记为内核 Generated/Modified 的同等强度。
1. 全部上游命名结构更新后，对现有 Selector 调用 Solve。
1. 执行类型、上下文、基数、语义不变量和 lineage 检查。
1. 成功则写 VERIFIED_REBIND_UNIQUE / EXACT_SELECTOR_SOLVED；失败则 unresolved/ambiguous。
1. OCAF command 与 Registry 事务全部成功后保存新 XBF，上一版保持可恢复。

### 11.5 FeatureIdentityReconciler 最低规则

| 变化 | node_id 处理 | OCAF Label 处理 |
| --- | --- | --- |
| 仅参数变化 | 保持 node_id | 更新原 feature label |
| 执行顺序变化但语义节点相同 | 保持 node_id | 按新依赖顺序更新原 label |
| 新增特征 | 分配新 node_id | 创建新 label |
| 删除特征 | 保留 tombstone | 旧 label 标记 deleted/superseded |
| Repair 修改参数/连接 | 优先 patch 原节点 | 不得删除再新建同义节点 |
| LLM 全量重生且匹配歧义 | 不自动复用 | 新建 label；相关旧 Selector unresolved |

### 11.6 ProofClass 建议

| 证明等级 | 含义 | 关键 CAE |
| --- | --- | --- |
| EXACT_KERNEL_HISTORY | 同 revision、同 builder、完整 Generated/Modified/Deleted | 允许 |
| EXACT_SELECTOR_SOLVED | 跨 revision Selector 唯一 Solve 且不变量通过 | 允许 |
| VERIFIED_REBIND_UNIQUE | feature bridge + 唯一重绑定 + 验证 | 按策略允许 |
| PARTIAL_KERNEL_HISTORY | 存在未覆盖后处理或算法历史不完整 | 默认禁止 |
| DETERMINISTIC_CONSTRUCTION | primitive/operation 语义确定 | 按操作白名单 |
| FINGERPRINT_CANDIDATE | 几何候选 | 禁止自动关键 CAE |
| AMBIGUOUS / UNRESOLVED | 多候选或无法解析 | 禁止 |

## 12. 现有 TopologyRegistry 的迁移与双写

### 12.1 保留 Registry，但改变职责

第一阶段不删除现有 Registry。OCAF 成为几何演化事实和 Selector 求解权威；Registry 成为面向业务和 CAE 的稳定 API、语义与风险治理层。

| 能力 | OCAF/TNaming | Registry |
| --- | --- | --- |
| old/new Shape 演化 | 权威 | 引用 OCAF 证据，不再猜测 |
| 选择重算 | 权威 | 消费结果并执行策略 |
| 文档持久化 | XBF | JSON 索引/manifest |
| PID | 保存属性和 Label 映射 | 对外稳定 API |
| semantic_role | 可存字符串 | 权威定义 |
| split/merge policy | 保存几何关系 | 决定继承、集合、阻断 |
| proof class | 提供底层证据 | 汇总消费者策略 |
| CAE Named Set | 解析实际 Shape | 定义集合语义与门禁 |

### 12.2 Registry 记录扩展

```python
class TopologyEntityRecord:
    persistent_id: str
    entity_type: str
    component_id: str
    occurrence_id: str | None
    producer_node_id: str
    semantic_role: str

    ocaf_document_id: str
    ocaf_feature_label_entry: str
    ocaf_selector_label_entry: str | None

    lifecycle: EntityLifecycle
    binding_state: BindingState
    proof_class: ProofClass
    resolution_status: str

    ancestor_ids: list[str]
    descendant_ids: list[str]
    expected_invariants: dict
    evidence: list[dict]
```

### 12.3 双写迁移阶段

1. Shadow：OCAF 写入但 Registry 仍使用旧逻辑；比较结果，不用于 CAE。
1. Dual-read：Registry 同时读取旧定位和 OCAF Selector；不一致时阻断并报告。
1. OCAF-authoritative：Registry 只消费 OCAF 几何事实，semantic naming 仅用于低等级角色。
1. Legacy freeze：禁止新增 history_wrappers 旁路重建；旧路径只用于回归对照。

## 13. 缓存、并发、进程和故障隔离

### 13.1 缓存策略

required topology capture 初期必须禁用普通 OperationCache。缓存命中不会产生本次运行的 builder，也不能恢复 live Shape history。

```python
cache_allowed = not (
    capture_required
    and op_spec.topology_capture_policy == 'required'
)
```

后期可引入 GeometryArtifactBundle 缓存，最小内容必须包括 geometry artifact、OCAF checkpoint、PID/Label 映射、Selector 状态、版本 manifest 和依赖哈希。仅缓存 OperationResult/TopologyDelta 不足以恢复 OCAF 事实。

### 13.2 并发模型

- 一个 component/revision 的几何节点按依赖顺序执行并串行提交同一 OCAF 文档。
- 独立组件可以在独立 worker 和独立文档中并行，装配层再建立 occurrence。
- ContextVar 只传递只读 scope；OCAF document 和 CaptureSession 不共享给无关线程。
- 不要在多个线程同时修改一个 TDocStd_Document。

### 13.3 进程隔离

若高风险 OCP 几何操作放入子进程，则原 builder、History 提取和 OCAF 写入必须在同一 worker 内完成。TopoDS_Shape handle 不得跨进程。主进程只接收 STEP/BREP、XBF、metadata 和 topology_status。

### 13.4 broad catch 规则

禁止在 History 适配层使用 except Exception: return []/None。只能捕获明确的 ImportError、版本兼容错误或已分类 OCCT 异常，并形成结构化诊断。未知异常在 audit 模式可隔离，在 required 模式必须使 topology 失败。

## 14. 失败语义、证明等级与 CAE 门禁

### 14.1 结构化错误码

```text
HISTORY_NO_RELATION
HISTORY_API_UNAVAILABLE
HISTORY_BUILDER_NOT_DONE
HISTORY_SOURCE_NOT_TRACKED
HISTORY_BINDING_ERROR
HISTORY_EXTRACTION_FAILED
POSTPROCESS_HISTORY_UNCOVERED
OCAF_TRANSACTION_FAILED
OCAF_WRITE_FAILED
OCAF_SAVE_FAILED
SELECTOR_CREATE_FAILED
SELECTOR_UNRESOLVED
SELECTOR_AMBIGUOUS
FEATURE_IDENTITY_AMBIGUOUS
CAE_PROOF_INSUFFICIENT
```

### 14.2 构建状态分离

```json
{
  "cad_build": "success",
  "kernel_history": "partial",
  "ocaf_write": "success",
  "ocaf_save": "success",
  "selector_resolution": "ambiguous",
  "cae_ready": false
}
```

### 14.3 CAE preflight 必查

- NamedTopologySet 中每个 PID 都可解析到当前 Shape。
- 实体类型正确；集合非空；基数满足 exact/exact_or_set。
- 组件、实例和 body revision 正确。
- 不存在 ambiguous、deleted、stale 或 unresolved。
- proof class 达到该消费者的最低等级。
- semantic invariants 通过。
- 关键 constraint/load/contact 中任何一项失败则禁止求解。

## 15. 测试矩阵与验收标准

### 15.1 A/B 无影响性测试

| 比较项 | 要求 |
| --- | --- |
| builder 调用次数 | capture on/off 完全相同；不得多 Build/Perform |
| 异常语义 | 异常类型、节点、阶段、required/optional 行为相同 |
| 几何拓扑 | solid/face/edge/vertex 数量一致 |
| 几何量 | 体积、面积、质心、包围盒在容差内一致 |
| 有效性 | BRepCheck、closed、positive volume 一致 |
| 制品 | STEP 规范化结构和 metadata 主字段一致 |
| 性能 | 记录额外开销；超阈值可关闭 capture，但不得改变几何 |

### 15.2 最小垂直切片

```text
Revision 1:
  rectangle profile
  -> extrude plate
  -> cylinder tool
  -> boolean cut
  -> clean/unify
  selectors: fixed_face, load_face, hole_wall_set

Revision 2:
  change length/thickness/hole diameter
  expected: all selectors solve uniquely

Revision 3:
  move hole until it intersects boundary
  expected: hole wall split/deleted/ambiguous,
            CAE blocked, never nearest-face fallback
```

### 15.3 单操作 History 测试

| 测试名 | 核心断言 |
| --- | --- |
| test_extrude_edge_generates_lateral_face | profile edge -> generated face |
| test_extrude_first_last_caps | FirstShape/LastShape 可恢复 |
| test_boolean_target_face_modified | 旧目标面 -> modified face(s) |
| test_boolean_tool_face_generates_hole_wall | 工具面 -> result face(s) |
| test_boolean_split_one_to_many | one-to-many 不被压缩 |
| test_fillet_edge_generates_face | selected edge -> fillet face |
| test_unify_merges_coplanar_faces | Unify History 被记录 |
| test_failed_fallback_history_discarded | 失败 attempt 不提交 |

### 15.4 跨 revision 测试

- 轻微尺寸变化；面不分裂时保持选择连续。
- 孔相交、圆角消失、面分裂、面合并。
- 特征插入、删除、重新排序。
- 对称和重复阵列。
- 保存、关闭进程、重新打开 XBF、重建并 Solve。
- FeatureIdentityReconciler 歧义时必须拒绝复用。

### 15.5 故障注入

| 注入点 | 预期 |
| --- | --- |
| History export 抛异常 | CAD 成功；topology failed/partial；CAE false |
| TNaming_Builder 抛异常 | AbortCommand；Registry 不提交 |
| Selector.Select 失败 | 选择 unresolved；不生成假 PID |
| Selector.Solve 多候选 | ambiguous；CAE 阻断 |
| SaveAs 失败 | 上一版 XBF 保留；不宣称 persisted |
| Registry 投影失败 | 双写回滚；报告 split-brain prevented |

### 15.6 发布验收门槛

- 所有生产使用的拓扑改变调用均登记；未知调用产生阻断或明确告警。
- 所有 exact 事件可追溯到实际 builder 和固定版本。
- XBF 可跨进程恢复。
- 最小垂直切片全部通过。
- 关键 CAE 错误绑定率为 0。
- 每个 partial/unresolved/ambiguous 都有 node、phase、builder 和原因。

## 16. 分阶段 PR 实施计划 (v1.1 修正 — 基于实际基线)

| PR | 目标 | 主要交付 | 退出条件 |
| --- | --- | --- | --- |
| PR-0 | 基线确认 + smoke test | 锁版本；OCAF/OCP smoke test；compile/tests 全绿 | 未改几何行为 |
| PR-1 | Tracked Operations | `tracked_ops/boolean.py`, `tracked_ops/extrude.py`, `tracked_ops/revolve.py` | A/B 几何一致 |
| PR-2 | Handler 接入 | 修改 dialect handlers 使用 TrackedOperation | 现有 tests 全绿 + A/B 通过 |
| PR-3 | OCAF Writer | XCAF doc、Label allocator、TNaming writer、事务、原子 XBF | 保存重开通过 |
| PR-4 | Selector/Revision | PID Selector、FeatureIdentity、RevisionBridge、Solve | 扰动 POC 通过 |
| PR-5 | 后处理覆盖 | fillet/chamfer；clean 标 partial；hollow/sweep/loft 标 partial | 覆盖矩阵更新 |
| PR-6 | Registry/CAE | OCAF authoritative projection、NamedTopologySet、CAE gate | 零误绑定测试 |
| PR-7 | 工程化 | 缓存 bundle、worker 隔离、性能、监控、升级矩阵 | 生产候选 |

### 16.1 PR-0 详细任务 (v1.1 修正)

**不需要修复 ABI**。当前基线 OperationResult/OperationSpec/OperationCache 签名一致。

- 确认基线 commit (678c073)、Python 3.11.9、CadQuery 2.7.0、OCP 7.8.1.1。
- 运行 `python -m compileall integrations/engineering_tools/src` — 确认编译通过。
- 运行 `pytest integrations/engineering_tools/tests/ -q` — 确认 baseline tests 全绿。
- 运行 OCAF/OCP smoke test — 确认 XCAFApp/TNaming/BinXCAF 全部可用。
- 验证 OCCT Builder History (BOPAlgo_BOP, BRepPrimAPI_MakePrism/MakeRevol)。
- 生成 `baseline_manifest.json`、`ocaf_binding_smoke.json`。

### 16.2 PR-1 详细任务 (v1.1 修正 — OCCT Builder 包装层)

**核心**: 创建 `topology/ocaf/tracked_ops/` 模块。

- 实现 `tracked_ops/boolean.py`: tracked_cut/fuse/common — 包装 BOPAlgo_BOP + SetToFillHistory
- 实现 `tracked_ops/extrude.py`: tracked_extrude — 包装 BRepPrimAPI_MakePrism + Generated/Modified
- 实现 `tracked_ops/revolve.py`: tracked_revolve — 包装 BRepPrimAPI_MakeRevol + Generated/Modified
- 实现 `topology/ocaf/models.py`: TrackedShapeResult, EvolutionRelation, TopologyEvolutionBatch 等
- **不与任何 dialect handler 连接** — 仅独立测试

### 16.3 PR-2 详细任务 (v1.1 修正)

- 修改 `dialects/composition/handlers.py`: boolean_union/boolean_cut 使用 tracked_cut/fuse
- 修改 `dialects/sketch_profile/handlers.py`: extrude_profile/revolve_profile 使用 tracked_extrude/revolve
- 增加 capture scope 管理到 `dialects/executor.py`
- 在 `runtime/context.py` 增加 `capture_session` 和 `ocaf_session` 字段（可选，初始 None）
- **A/B 测试强制**: capture on/off 产生相同 STEP (体积/面积/面数/有效性)

### 16.3 每个 PR 的 Agent 输出格式

```text
1. Changed files
2. Architecture decisions
3. Exact API/version assumptions
4. Tests added
5. Commands executed and results
6. Remaining unsupported operations
7. Risks / rollback plan
8. Git diff summary
9. No-geometry-change evidence
```

## 17. 代码 Agent 最终执行清单

> 禁止一次性大改：代码 Agent 不得在一个 PR 中同时重写 CadQuery handler、接 OCAF、改 Registry 和接 CAE。每个阶段必须可独立回滚，并以测试和制品证明退出。

- [ ] 已固定 repo commit 与依赖版本。
- [ ] 已证明 current main 的 ABI 问题已闭合。
- [ ] 已生成全部拓扑改变调用覆盖矩阵。
- [ ] 没有任何权威 History 来自第二次 builder。
- [ ] 没有 Face/Edge 索引、Python id、modulo 或 nearest-face 用作 exact PID。
- [ ] live Shape 没有跨进程或 JSON 持久化。
- [ ] OCAF 写入发生在几何校验后，且可 Abort。
- [ ] XBF 使用临时文件原子替换。
- [ ] 稳定 node_id 与 feature identity 已定义。
- [ ] 跨 revision 只在 Selector 和不变量验证后提升证明。
- [ ] 关键 CAE 只消费通过 preflight 的 NamedTopologySet。
- [ ] A/B、扰动、临界、故障注入和跨进程测试全部通过。

### 17.1 可直接交给代码 Agent 的任务提示

```text
你正在 WYZAAACCC/text2cad_improve 中实现 OCAF/TNaming 持久化拓扑命名。

严格按《Text-to-CAD / OCAF 持久化拓扑命名落地实施指导书 v1.1》执行。
注意: v1.1 基于实际环境 (Python 3.11.9, CadQuery 2.7.0, OCP 7.8.1.1, commit 678c073)
对 v1.0 做了重大修正。关键差异: CadQuery 不提供 History API,
必须通过 OCCT Builder 层面包装 (BOPAlgo_BOP + SetToFillHistory)。

第一阶段只完成 PR-0 (修正版):
1. 确认基线: git rev-parse HEAD → 678c073; python -VV; CadQuery/OCP 版本。
2. 运行 compileall + pytest (baseline tests 全绿)。
3. 运行 OCAF/OCP smoke test: XCAFApp, BinXCAF, TNaming_Builder/Selector/Tool 全部验证。
4. 验证 OCCT Builder History: BOPAlgo_BOP.SetToFillHistory, BRepPrimAPI_MakePrism.Generated 等。
5. 生成 baseline_manifest.json, ocaf_binding_smoke.json。
6. **不需要修复 ABI** — 当前基线 OperationResult/OperationSpec/OperationCache 签名一致。
7. 不得修改几何算法, 不得接入 OCAF Writer。

退出条件: 所有 smoke test 通过, baseline tests 全绿, OCCT Builder History 路径确认。
未达到退出条件不得进入 PR-1。
```

## 附录 A. 建议代码骨架

### A.1 context.py

```python
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_CURRENT_SCOPE: ContextVar[TopologyCaptureScope | None] = ContextVar(
    'topology_capture_scope', default=None
)

@contextmanager
def topology_capture_scope(scope):
    token = _CURRENT_SCOPE.set(scope)
    try:
        yield scope
    finally:
        _CURRENT_SCOPE.reset(token)

def require_scope():
    scope = _CURRENT_SCOPE.get()
    if scope is None:
        raise TopologyCaptureProtocolError('operation outside capture scope')
    return scope
```

### A.2 capture_session.py

```python
class TopologyCaptureSession:
    def __init__(self):
        self._nodes = {}

    def begin_node(self, scope):
        if scope.node_id in self._nodes:
            raise CaptureAlreadyOpen(scope.node_id)
        self._nodes[scope.node_id] = NodeStaging(scope=scope)

    def stage(self, batch):
        validate_live_batch(batch)
        token = new_capture_token(batch)
        self._nodes[batch.scope.node_id].batches[token] = batch
        return token

    def accept_attempt(self, node_id, attempt_index): ...
    def reject_attempt(self, node_id, attempt_index, error): ...
    def consume_for_commit(self, node_id, tokens): ...
    def abort_node(self, node_id, reason): ...
```

### A.3 compat.py (v1.1 修正 — 基于实际 OCP 7.8.1.1 API)

```python
"""OCP version/API compatibility adapter.

OCP 7.8.1.1 verified:
- Static methods use _s suffix: GetApplication_s, DefineFormat_s
- TDocStd_Document needs TCollection_ExtendedString, not plain str
- TopTools_ListOfShape for SetArguments/SetTools
"""

from OCP.TCollection import TCollection_ExtendedString
from OCP.TopTools import TopTools_ListOfShape

def get_xcaf_application():
    """Get XCAF application instance. OCP 7.8 uses GetApplication_s."""
    from OCP.XCAFApp import XCAFApp_Application
    return XCAFApp_Application.GetApplication_s()

def define_binxcaf_format(app):
    """Register BinXCAF format. OCP 7.8 uses DefineFormat_s."""
    from OCP.BinXCAFDrivers import BinXCAFDrivers
    return BinXCAFDrivers.DefineFormat_s(app)

def new_document(app, storage_format='BinXCAF'):
    """Create a new TDocStd_Document. ★ Must use TCollection_ExtendedString."""
    from OCP.TDocStd import TDocStd_Document
    fmt = TCollection_ExtendedString(storage_format)
    doc = TDocStd_Document(fmt)
    app.InitDocument(doc)
    return doc

def make_list_of_shape(shapes):
    """Convert Python list to TopTools_ListOfShape for OCP 7.8."""
    lst = TopTools_ListOfShape()
    for s in shapes:
        lst.Append(s)
    return lst
```

### A.4 SemanticTopologyBridge

```python
class SemanticTopologyBridge:
    def project(self, receipt, tx):
        for binding in receipt.bindings:
            rec = TopologyEntityRecord(
                persistent_id=binding.pid,
                entity_type=binding.entity_type,
                component_id=binding.component_id,
                occurrence_id=binding.occurrence_id,
                producer_node_id=binding.node_id,
                semantic_role=binding.semantic_role,
                ocaf_document_id=receipt.document_id,
                ocaf_feature_label_entry=binding.feature_label,
                ocaf_selector_label_entry=binding.selector_label,
                lifecycle=binding.lifecycle,
                binding_state=binding.binding_state,
                proof_class=binding.proof_class,
                expected_invariants=binding.invariants,
                evidence=binding.evidence,
            )
            tx.upsert_from_ocaf(rec)

        # No modulo, list-order, nearest-face or silent fallback is permitted.
```

## 附录 B. 操作覆盖矩阵

| 操作 | 实际 Builder (OCP 7.8.1.1) | History 方式 | 初始等级 | 主要风险 |
| --- | --- | --- | --- | --- |
| **Extrude** | `BRepPrimAPI_MakePrism` | `builder.Generated()/.Modified()/.FirstShape()/.LastShape()` (已验证) | Exact 候选 | 多 builder/up-to-face |
| **Revolve** | `BRepPrimAPI_MakeRevol` | `builder.Generated()/.Modified()/.FirstShape()/.LastShape()` (已验证) | Exact 候选 | 360°接缝/轴上边 |
| **Boolean** | `BOPAlgo_BOP` (CadQuery 原路径) | `SetToFillHistory(True)` → `builder.History()` (已验证) | Exact 候选 | split/merge/fuzzy |
| **Fillet** | `BRepFilletAPI_MakeFillet` | `builder.Generated()/.Modified()` (待验证) | Exact 候选 | contour 重组 |
| **Chamfer** | `BRepFilletAPI_MakeChamfer` | 待验证 | Exact 候选 | 相邻面映射 |
| **Clean/Unify** | `ShapeUpgrade_UnifySameDomain` | ❌ **无 History** (OCP 7.8.1.1) | **当前 Partial** | 必须 patch 或用 fuzzy fuse 替代 |
| Primitive box/cylinder | BRepPrimAPI | 需专用适配 | Deterministic | 子面语义 |
| Hollow/Shell | MakeThickSolid + 后处理 | 部分 | Partial | MakeSolid/fix |
| Sweep/Loft | 多个 builder + sewing | 部分 | Partial | history remap |
| Pattern | occurrence + Boolean | 语义为主 | 按阶段 | 重复实例 |
| Transform | Location | 可实现 | 特殊 | prototype/occurrence |
| External STEP | 无 builder history | 无 | Imported snapshot | 只允许低证明 |

## 附录 C. 交付物与验收勾选表

| 交付物 | 验收目标 | 完成 |
| --- | --- | --- |
| baseline_manifest.json | 版本和环境可重复 | ☐ |
| operation_call_graph.md | 所有生产几何路径可追踪 | ☐ |
| history_coverage.csv | 操作完整/部分/无历史明确 | ☐ |
| ocaf_binding_smoke.json | OCP 重载和持久化可用 | ☐ |
| model.xbf | 可保存、关闭、重开 | ☐ |
| topology_manifest.json | PID/Label/proof/status 可审计 | ☐ |
| A/B evidence | capture 不改变几何 | ☐ |
| revision perturbation report | Selector 行为可解释 | ☐ |
| CAE fail-closed report | 关键错误绑定率 0 | ☐ |

## 附录 D. 源码与官方文档依据

以下是代码 Agent 在实现时必须核对的原始来源。版本敏感接口以目标环境实际源码和 smoke test 为最终依据。

| 编号 | 来源 |
| --- | --- |
| S-01 | 目标仓库 main，基线提交 ed6f6603e77d903dccd09966f792d7ddc2986501。 |
| S-02 | 仓库：generative_cad/dialects/composition/handlers.py。 |
| S-03 | 仓库：generative_cad/topology/history_wrappers.py。 |
| S-04 | 仓库：generative_cad/dialects/executor.py、operation.py、results.py。 |
| S-05 | 仓库：generative_cad/runtime/context.py、cache.py、cadquery_runtime.py。 |
| S-06 | 仓库：generative_cad/topology/models.py。 |
| S-07 | CadQuery stable/latest：cadquery.occ_impl.shapes 源码，History、Op、_update_history、cut/extrude/revolve/fillet/chamfer/sweep/loft/hollow/clean。 |
| S-08 | CadQuery Free Function API：History 命名操作使用说明。 |
| S-09 | OCCT Reference Manual：BRepTools_History。 |
| S-10 | OCCT Reference Manual：TNaming、TNaming_Builder、TNaming_Selector、TNaming_Tool。 |
| S-11 | OCCT OCAF User Guide：Loading history、Selection/re-computation、NamedShape evolution。 |
| S-12 | OCCT Reference Manual：TDocStd_Document、TDocStd_Application、XCAFApp_Application、BinXCAFDrivers。 |
| S-13 | OCCT OCAF Usage Tutorial：TNaming_Sample。 |

## 最终实施结论 (v1.1)

> **v1.1 结论**: 可落地的核心是”让原 CadQuery/OCCT 操作只执行一次，在 OCCT Builder 层面（非 CadQuery 层面）捕获真实 History”。CadQuery 2.7.0 不提供 History API，但底层 OCCT Builder 的 History 能力完全可用。通过在 Builder 层面创建 TrackedOperation 包装层，使用与 CadQuery 内部相同的 Builder 类，一次 Build 同时产出几何和 History。

**v1.1 垂直切片**: 实现 TrackedOperation (extrude/cut) → A/B 几何一致性验证 → Handler 接入 → OCAF Writer (XBF) → Selector → 参数扰动 → CAE preflight。只有此链全通过，才扩展到 fillet/chamfer/sweep/loft。

**v1.0 → v1.1 关键修正**:
1. CadQuery 不提供 `history=` 参数 → 改为 OCCT Builder 层面包装
2. P0-04/05/06 ABI 问题在当前基线不存在 → 删除相关修复任务
3. Clean/UnifySameDomain 确认无 History → 标为 PARTIAL_KERNEL
4. BRepPrimAPI_MakePrism/MakeRevol 用 Generated/Modified (非 History()) → 区分两种 API 模式
5. TDocStd_Document 需要 TCollection_ExtendedString → 修正构造方式
