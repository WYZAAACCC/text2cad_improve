# Text2CAD Validation / AutoFix 可扩展内核重构指导书

**版本：** 1.0  
**适用仓库：** `WYZAAACCC/text2cad_improve`  
**实施对象：** 代码 Agent / 架构重构开发者  
**核心目标：** 将 Validation 与 AutoFix 从“不断堆叠特殊规则的中心化脚本”重构为“稳定微内核 + 自动加载扩展”的规则系统。

---

## 0. 架构结论

本次重构不得继续在现有 `validation/pipeline.py`、`authoring/auto_fixer.py` 中增加条件分支。

目标架构必须遵循以下主链：

```text
输入文档
  ↓
Extension Activation Resolver
  ↓
Validation Rule Registry
  ↓
Validation Planner
  ↓
Validation Executor
  ↓
统一 Issue / Fact Store
  ↓
Repair Provider Registry
  ↓
Repair Proposal Planner
  ↓
Atomic Patch Transaction
  ↓
增量验证 + 全量回归验证
  ↓
接受修复或回滚
```

系统必须明确分成两层：

```text
Validation / Repair Kernel
├─ 所有 CAD 零件都必须遵守的通用不变量
├─ 规则注册、排序、执行、冲突检测
├─ Issue、Fact、RepairProposal、PatchTransaction 数据模型
├─ 修复策略、风险策略、回归验收
└─ 不认识任何具体零件、孔型、槽型或行业部件

Extensions
├─ Feature Extension：孔、螺纹、圆角、壳、阵列等
├─ Dialect Extension：axisymmetric、sketch_profile 等
├─ Part-family Extension：turbine_disk、gear 等
└─ Domain Extension：制造、航空、CAE 等可选规则
```

**不可妥协原则：**

1. Validator 只检测，不修改文档。
2. AutoFix 只能由具体 Issue 触发，不允许失败后盲目运行全部修复函数。
3. Kernel 不得 import 任何具体 dialect、feature 或 part-family 模块。
4. Extension 只能增加或收紧规则，不能覆盖、屏蔽或降低 Core Error。
5. 每次修复必须是原子事务，失败或回归时完整回滚。
6. 每个修复必须能说明：解决哪个 Issue、修改了什么、风险等级是什么、为什么不改变设计意图。
7. 新增特殊零件时，只新增扩展包，不修改核心 pipeline、核心 stage 列表或中心 AutoFix 文件。

---

## 1. 现有系统的主要问题

### 1.1 Validation Pipeline 是硬编码中心管线

当前 `validation/pipeline.py` 直接维护：

```python
RAW_STAGES = [...]
CANONICAL_STAGES = [...]
```

新增一类特殊校验通常意味着：

- 新建 validator；
- 修改中心 import；
- 修改中心 stage 列表；
- 修改 governor 的 stage rank；
- 修改 repair hints；
- 修改 AutoFix；
- 可能还要修改 dialect 回调。

这会形成明显的 shotgun surgery：一个规则变化扩散到多个模块。

当前 `_run_stage_collect()` 在某一阶段失败后立即返回，导致：

- 同一层级的其他独立问题无法被一次收集；
- AutoFix 得到的是不完整错误集合；
- 修好第一个错误后才暴露第二个错误；
- 修复轮次增多；
- 不利于冲突分析和组合修复。

### 1.2 特殊 Feature 规则已经侵入核心

`validation/hole_semantics.py` 直接识别：

- `cut_hole`
- `cut_hole_v2`
- `cut_hole_pattern_linear`
- `drill_hole_3d`
- `cut_circular_hole_pattern`

这类规则不是“所有 CAD 模型的通用不变量”，应属于 Hole Feature Extension。

该文件在 pipeline 中名为 `hole_semantics`，内部却把 Issue stage 写成 `geometry_preflight`，说明 stage、规则和报告身份已经发生漂移。

### 1.3 Dialect Hook 粒度过粗

当前 `BaseDialect` 只有：

```python
validate_component(...)
preflight_component(...)
```

这只能把一整个 dialect 当作黑盒 validator，缺少：

- 独立 rule_id；
- 规则版本；
- 规则依赖；
- 选择器；
- 规则优先级；
- 运行成本；
- 产生的 facts；
- 可处理的 issue code；
- 对应 repair provider；
- 冲突声明。

随着规则增长，一个 dialect 内部仍会重新变成大型条件分支。

### 1.4 AutoFix 是“盲跑修复链”，不是 Issue-driven Repair

当前 `auto_fix_with_report()` 不接收 ValidationReport，也不接收具体 Issue。验证失败后，它会按固定顺序尝试整个修复链。

这会导致：

- 与当前错误无关的修复也可能运行；
- 修复顺序成为隐藏语义；
- 两个修复对同一字段写入时没有显式冲突；
- 无法准确计算一个修复解决了哪些问题；
- 新规则不断增加后，中心文件会继续膨胀；
- 很难证明修复不改变用户设计意图。

当前审计记录主要记录整个文档修复前后的 hash，`path="/"`，无法完整表达实际改动字段。

### 1.5 安全分类与实际行为不一致

当前有：

```python
SYNTACTIC_ALIAS
SCHEMA_DEFAULT
CONTEXT_SAFE
SEMANTIC_GUESS
DESTRUCTIVE
```

但 `AutoFixEntry.severity` 又使用：

```python
safe_alias
semantic_guess
destructive
```

并且 `safe_alias` 被映射到 `CONTEXT_SAFE`。风险模型没有成为每条规则的严格类型合同。

部分被标为安全的修复实际上会：

- 删除或绕过图节点；
- 重写组件引用；
- 修改 root node；
- 重排节点；
- 镜像槽型；
- 修改截面几何；
- 默认未知 dialect 为 axisymmetric。

这些都不能视为纯语法修复。

### 1.6 两套 Repair 模型并存

当前同时存在：

- `authoring/auto_fixer.py`
- `repair/patch.py`
- `repair/governor.py`

`RepairPatchV2` 禁止修改 dialect、op、op_version，但 `auto_fixer.py` 又会修正 dialect、op_version、qualified op，甚至删除 unknown op。

这意味着系统同时存在两套不同的修复安全合同，必须合并为一个唯一 Repair Kernel。

### 1.7 Repair Governor 与 Validation Stage 漂移

`repair/governor.py` 自己维护 `STAGE_RANK`，但它没有完整覆盖当前 pipeline 的全部 stage。任何新增 stage 都可能忘记同步。

进度判断不应依赖“走到了更靠后的 stage”，而应依赖验证质量是否真实提升。

### 1.8 Web 入口吞掉修复异常

当前 Web 主链大致是：

```python
validate(raw)
if failed:
    try:
        fixed = auto_fix(raw)
        validate(fixed)
    except Exception:
        pass
```

修复系统错误被静默忽略，会造成：

- 无法区分“无修复方案”和“修复框架崩溃”；
- 审计信息缺失；
- 线上问题难以复现；
- 核心安全链失效。

---

## 2. Core 与 Extension 的正式边界

判断一条规则是否属于 Core，只使用下面的标准：

> 该规则是否对所有零件、所有 dialect、所有 part-family 都成立，并且不需要知道具体机械语义？

### 2.1 必须属于 Core 的 Validation

#### A. 输入与结构不变量

- JSON / Pydantic 可解析；
- schema version 合法；
- 未知字段策略；
- ID 存在且唯一；
- component、node、output 引用存在；
- required / degradation policy 合法；
- safety contract 完整；
- 数字有限，禁止 NaN / Inf；
- 单位系统一致。

#### B. 注册表与操作合同

- dialect 已注册；
- operation 和 version 已注册；
- params 满足 `OperationSpec.params_model`；
- 输入、输出类型匹配；
- operation effect、phase、required context 合法；
- operation contract hash 可验证。

#### C. 图不变量

- DAG 无环；
- 依赖可达；
- component ownership 正确；
- root terminal 存在；
- root terminal 输出类型符合组件合同；
- required 节点不会依赖可静默降级节点；
- 跨组件引用符合统一引用规则。

#### D. 通用资源与复杂度限制

- 最大节点数；
- 最大布尔运算数；
- 最大阵列实例数；
- 最大 profile 点数；
- 单次规则执行时间；
- 总验证预算。

这些限制必须来自统一 Policy，不得散落为模块常量。

#### E. 通用几何不变量

- 对象存在；
- 预期 solid 的对象确实是 solid；
- B-Rep 有效；
- solid 闭合；
- 体积为正；
- bounding box 非退化；
- body count 满足合同；
- 输出没有明显退化边、零面积面或空壳；
- runtime operation 的 postcondition 成立。

#### F. 通用 Boolean 校验

- operands 存在且类型正确；
- 坐标系可比较；
- operand 不是空 shape；
- cut / intersect 的包围盒关系可诊断；
- operation 执行后结果不为空；
- 结果仍满足 B-Rep、closed、volume、body-count 合同；
- volume change 与 operation effect 不矛盾；
- union 的连通性符合声明；
- 产生异常碎片、sliver 或多余 body 时报告问题。

#### G. 通用空间校验

- transform 数值有限；
- rotation matrix / quaternion 合法；
- frame 引用存在；
- 显式声明的接触、间隙、包含、对齐关系得到满足；
- 不允许的穿透被检测；
- 所有空间约束必须依据显式 Spatial Contract，而不是猜测机械用途。

#### H. 通用产物校验

- STEP / metadata 必须存在；
- 导出文件可重新导入；
- round-trip 后仍有有效实体；
- graph hash、dialect contract hash、artifact hash 一致；
- metadata 与实际实体数量、bbox、volume 一致。

### 2.2 必须属于 Extension 的规则

以下规则不得进入 Core：

- 孔到边界的特殊距离规则；
- 孔阵列与中心孔、轮缘、轮毂的关系；
- 螺纹等级、标准和内外螺纹语义；
- 枞树槽站点顺序、半轮廓镜像；
- 涡轮盘 hub/web/rim 比例；
- 齿轮模数、压力角、根切；
- 轴承座配合；
- 特定壳体开口规则；
- 特定制造工艺最小壁厚；
- 航空零件的特殊安全约束；
- part-family 专属 CAE 区域。

扩展再分四级：

```text
FeatureExtension
  例：hole、thread、fillet、pattern、shell

DialectExtension
  例：axisymmetric、sketch_profile、composition

PartFamilyExtension
  例：turbine_disk、spur_gear、bearing_housing

DomainExtension
  例：manufacturing、aerospace、CAE
```

规则应放在能表达其最小语义范围的最低层。例如：

- “hole diameter 必须为正”可由 Hole Feature Extension 提供；
- “axisymmetric 孔阵列 PCD 必须处于外轮廓与中心孔之间”由 Axisymmetric Hole Pattern Extension 提供；
- “涡轮盘螺栓孔必须避开 web/rim 过渡区”由 Turbine Disk Part Extension 提供。

---

## 3. 目标目录结构

建议新增：

```text
generative_cad/
├─ validation_kernel/
│  ├─ stages.py
│  ├─ models.py
│  ├─ context.py
│  ├─ facts.py
│  ├─ selectors.py
│  ├─ registry.py
│  ├─ activation.py
│  ├─ planner.py
│  ├─ executor.py
│  ├─ conflict.py
│  ├─ policy.py
│  └─ compatibility.py
│
├─ repair_kernel/
│  ├─ models.py
│  ├─ registry.py
│  ├─ proposer.py
│  ├─ planner.py
│  ├─ transaction.py
│  ├─ authorizer.py
│  ├─ evaluator.py
│  ├─ governor.py
│  └─ policy.py
│
├─ rules/
│  └─ core/
│     ├─ ingest.py
│     ├─ structure.py
│     ├─ registry_contract.py
│     ├─ graph.py
│     ├─ ownership.py
│     ├─ type_system.py
│     ├─ phase_contract.py
│     ├─ resource_budget.py
│     ├─ boolean.py
│     ├─ spatial.py
│     ├─ runtime_geometry.py
│     └─ artifact.py
│
└─ extensions/
   ├─ features/
   │  ├─ hole/
   │  ├─ thread/
   │  ├─ fillet/
   │  └─ pattern/
   ├─ dialects/
   │  ├─ axisymmetric/
   │  ├─ sketch_profile/
   │  └─ composition/
   └─ parts/
      ├─ turbine_disk/
      └─ gear/
```

可以让扩展代码物理上留在原 dialect 目录，但必须通过统一 `ExtensionManifest` 注册；Kernel 不得直接 import 这些模块。

---

## 4. 统一 Validation Stage

所有 stage 必须在一个 Enum 中定义，禁止不同模块使用自由字符串。

```python
class ValidationStage(str, Enum):
    INGEST = "ingest"
    RAW_STRUCTURE = "raw_structure"
    RAW_GRAPH = "raw_graph"
    RAW_CONTRACT = "raw_contract"
    CANONICAL_CONTRACT = "canonical_contract"
    SEMANTIC = "semantic"
    GEOMETRY_PREFLIGHT = "geometry_preflight"
    RUNTIME_OPERATION = "runtime_operation"
    RUNTIME_MODEL = "runtime_model"
    ARTIFACT = "artifact"
```

执行原则：

1. Stage 之间有 barrier。
2. 同一 stage 内尽可能收集全部独立 Issue。
3. 只有缺少必要前置数据时才跳过后续规则。
4. 跳过必须产生结构化 `RuleExecutionRecord(status="skipped")`，不能静默消失。
5. Stage 顺序只在 `ValidationStage` / Planner 中定义一次。
6. Repair Governor 不再维护自己的 stage rank。

示例：

- Raw 文档无法解析时，不能执行图规则；
- 图中存在一个缺失引用，不代表同阶段其他独立 component 的引用检查必须停止；
- Canonicalization 失败时，可以终止需要 Canonical IR 的规则；
- Runtime 几何规则只在对应 shape 已生成时执行。

---

## 5. 统一 Rule 规范

### 5.1 RuleManifest

```python
class RuleLayer(str, Enum):
    CORE = "core"
    EXTENSION = "extension"


class RuleManifest(BaseModel):
    rule_id: str                 # 全局唯一，如 core.graph.no_cycle
    version: str
    provider_id: str             # core 或 extension id
    layer: RuleLayer
    stage: ValidationStage

    selector: "RuleSelector"
    before: list[str] = []
    after: list[str] = []

    requires_facts: list[str] = []
    produces_facts: list[str] = []
    emitted_issue_codes: list[str] = []

    deterministic: bool = True
    side_effect_free: bool = True
    estimated_cost: Literal["cheap", "normal", "expensive"] = "cheap"
    timeout_ms: int = 1000
    failure_policy: Literal["fail_closed", "report_provider_error"] = "report_provider_error"
```

要求：

- `rule_id`、issue code 必须带 namespace；
- 同一版本注册表内不得重复；
- `before` / `after` 构成 DAG，启动时检查环；
- `side_effect_free` 必须为真，Validator 禁止修改输入；
- Rule 不能直接调用 RepairProvider；
- Rule 只能返回 Issue 和 Fact。

### 5.2 RuleSelector

```python
class RuleSelector(BaseModel):
    always: bool = False
    dialects: set[str] = set()
    operations: set[str] = set()
    feature_tags: set[str] = set()
    part_families: set[str] = set()
    domain_skills: set[str] = set()
    semantic_roles: set[str] = set()
    artifact_types: set[str] = set()
```

选择器使用“明确元数据”，禁止 Kernel 通过：

- component 名称包含 `cutter`；
- 自然语言模糊匹配；
- 未知 dialect 默认 axisymmetric；
- 零件名称字符串猜测；

来加载规则。

### 5.3 ValidationRule Protocol

```python
class ValidationRule(Protocol):
    manifest: RuleManifest

    def evaluate(
        self,
        ctx: "ValidationContext",
        target: "ValidationTarget",
    ) -> "RuleResult":
        ...
```

### 5.4 ValidationContext

```python
class ValidationContext:
    raw_document: RawGcadDocument | None
    canonical_document: CanonicalGcadDocument | None
    runtime_context: RuntimeContext | None
    artifact_bundle: ArtifactBundle | None

    dialect_registry: DialectRegistry
    operation_index: OperationIndex
    component_index: ComponentIndex
    dependency_graph: DependencyGraph
    facts: FactStore
    policy: ValidationPolicy
    activation: ActivationSnapshot
```

Context 对规则应只读。昂贵的 bbox、volume、profile envelope、shape validity 等数据写入 `FactStore`，避免多个规则重复计算。

### 5.5 ValidationIssue

现有 Issue 模型需要扩展为：

```python
class ValidationIssue(BaseModel):
    issue_id: str                # 稳定 hash
    fingerprint: str             # 用于跨轮次追踪
    code: str                    # 如 feature.hole.pcd_outside_envelope

    rule_id: str
    rule_version: str
    provider_id: str
    layer: RuleLayer
    stage: ValidationStage

    severity: Literal["info", "warning", "error", "fatal"]
    target: TargetLocator
    message: str

    invariant: str | None
    evidence: list[Evidence]
    expected: Any | None
    actual: Any | None

    fixability: Literal[
        "none",
        "normalization",
        "contract_derived",
        "geometry_recovery",
        "domain_semantic",
        "intent_changing",
        "destructive",
    ]

    repair_provider_ids: list[str] = []
    conflict_key: str | None = None
    tags: set[str] = set()
```

`TargetLocator` 至少应支持：

- document；
- component；
- node；
- node param path；
- input/output；
- runtime handle；
- body/face/edge 的稳定语义标识；
- artifact。

Issue 不得仅靠 message 供 AutoFix 解析。

---

## 6. Extension 自动加载规范

### 6.1 ExtensionManifest

```python
class ExtensionManifest(BaseModel):
    extension_id: str
    version: str
    kind: Literal["feature", "dialect", "part_family", "domain"]

    selectors: list[RuleSelector]
    rule_factories: list[str]
    repair_provider_factories: list[str]

    requires_extensions: list[str] = []
    conflicts_with: list[str] = []

    contract_hash: str
    enabled_by_default: bool = True
```

### 6.2 激活来源

激活信息按可信度排序：

1. 用户明确指定；
2. L1 `part_intent` 中的结构化 `part_family`；
3. `selected_domain_skills`；
4. Canonical Graph 中实际使用的 dialect；
5. `OperationSpec.feature_tags`；
6. 运行时产物类型。

建议把当前 `part_intent: dict[str, str]` 改为强类型：

```python
class PartIdentity(BaseModel):
    part_family: str | None
    variant: str | None
    engineering_domain: str | None
    confidence: float
    source: Literal["user", "router", "primitive", "canonical_graph"]
```

### 6.3 激活模式

```text
ENFORCE
  明确 part_family / dialect / operation 命中，规则可产生 error。

ADVISORY
  仅低置信推断命中，规则只产生 warning，不得自动执行语义修复。

DISABLED
  不加载。
```

Kernel 永远加载 Core。Extension 由 `ActivationResolver` 建立本次任务的不可变 `ActivationSnapshot`。

### 6.4 注册方式

可使用 Python entry points：

```toml
[project.entry-points."seekflow.gcad.validation_extensions"]
axisymmetric = "pkg.axisymmetric:build_extension"
turbine_disk = "pkg.turbine_disk:build_extension"
```

仓库内置扩展也必须走同一注册接口，不能由 Kernel 特判。

注册完成后 Registry 应 freeze，并生成 contract hash。现有 frozen dialect registry 的治理方式可以复用。

---

## 7. 规则冲突治理

### 7.1 启动期冲突

Extension Registry 构建时必须检查：

- 重复 `rule_id`；
- 重复 issue code 且未声明共享；
- rule dependency 环；
- extension dependency 缺失；
- extension 显式冲突；
- repair provider 订阅不存在的 issue code；
- provider 请求超出其 patch capability 的路径；
- Core rule 被 Extension 覆盖。

任何启动期合同错误都不得进入运行阶段。

### 7.2 运行期 Issue 合并

Issue 以 fingerprint 去重。Fingerprint 建议由：

```text
rule_id
+ issue code
+ target locator
+ relevant evidence hash
```

组成。

Extension：

- 可以新增更严格的 Issue；
- 不得降低 Core Issue severity；
- 不得 suppress Core Error；
- 如需对 Core 检查提供豁免，必须由 Core Rule 自己读取明确的标准化合同，而不是由 Extension 覆盖 Core Rule。

### 7.3 Repair 冲突

Repair Planner 必须建立写集合：

```text
proposal A writes:
  /nodes/hole_1/params/pcd_mm

proposal B writes:
  /nodes/hole_1/params/pcd_mm
```

若两个 Proposal 写入同一路径且值不同，则进入 conflict group，不允许依赖执行顺序决定结果。

冲突处理顺序：

1. 排除风险超出策略的 Proposal；
2. 优先解决 fatal / core error；
3. 优先不改变设计意图；
4. 优先触碰更少实体；
5. 优先数值变化更小；
6. 仍无法唯一选择时，不自动修复，转为需要用户或 LLM 重新设计。

---

## 8. AutoFix 重构为 Issue-driven Repair

### 8.1 RepairProvider Protocol

```python
class RepairProvider(Protocol):
    manifest: RepairProviderManifest

    def propose(
        self,
        issue: ValidationIssue,
        ctx: ValidationContext,
    ) -> list["RepairProposal"]:
        ...
```

每个 Provider 订阅明确 issue code：

```python
class RepairProviderManifest(BaseModel):
    provider_id: str
    version: str
    handles_issue_codes: set[str]
    selector: RuleSelector
    allowed_patch_capabilities: set[str]
    deterministic: bool
```

### 8.2 RepairProposal

```python
class RepairProposal(BaseModel):
    proposal_id: str
    provider_id: str
    provider_version: str

    resolves_issue_ids: list[str]
    expected_resolved_codes: list[str]

    risk: Literal[
        "normalization",
        "contract_derived",
        "geometry_recovery",
        "domain_semantic",
        "intent_changing",
        "destructive",
    ]

    confidence: float
    intent_preservation: Literal["proven", "assumed", "not_preserved"]

    operations: list[PatchOperation]
    preconditions: list[PatchCondition]
    postconditions: list[PatchCondition]

    touched_targets: list[TargetLocator]
    conflicts_with: list[str]
    exclusive_group: str | None

    estimated_delta: ChangeCost
    requires_user_confirmation: bool = False
```

### 8.3 风险策略

默认自动应用：

```text
normalization
contract_derived
geometry_recovery（仅不改变设计 IR 的内核恢复）
```

条件自动应用：

```text
domain_semantic
```

只有在扩展能够证明：

- 该值不是用户锁定值；
- 可行解唯一；
- 修改不改变声明的设计意图；
- 变化在策略阈值内；
- 修复后完整验证通过；

时才允许自动应用。

默认禁止自动应用：

```text
intent_changing
destructive
```

### 8.4 PatchOperation

不要继续手写大量 path 正则和 if/elif 应用器。采用受控、类型化的 JSON Patch 语义：

```python
class PatchOperation(BaseModel):
    op: Literal["test", "add", "replace", "remove", "move", "rewire"]
    path: str
    value: Any | None
    old_value: Any | None
```

每次修改必须：

1. 带 `base_document_hash`；
2. 带目标 Issue fingerprint；
3. 先执行 `test` / old_value 检查；
4. 由 Provider Capability Authorizer 检查路径；
5. 在文档副本中原子执行；
6. 重新解析 schema；
7. 运行受影响规则；
8. 运行必要的完整 stage barrier；
9. 只有质量向量改善才提交。

### 8.5 修复质量向量

不要再用“到了更后面的 stage”判断进步。

建议比较：

```python
QualityVector(
    core_fatal_count,
    core_error_count,
    extension_error_count,
    unresolved_original_error_count,
    newly_introduced_error_count,
    warning_count,
    intent_risk_score,
    touched_entity_count,
    document_delta_score,
)
```

按字典序最小化。

接受候选修复的最低条件：

- 不新增 Core Error；
- 不降低 Core Error 的可见性；
- 至少解决一个目标 Issue，或显著降低严重度；
- 不引入更高风险问题；
- 完整验证后质量向量严格改善；
- graph hash、patch hash、error fingerprint 不形成循环。

### 8.6 Repair Loop

```python
result = validation_engine.validate(document, session)

for attempt in range(policy.max_repair_attempts):
    if result.ok:
        break

    proposals = repair_engine.propose(result.issues, session)
    plan = repair_planner.select(proposals, result, session.policy)

    if plan.is_empty:
        break

    candidate = patch_transaction.apply_atomic(document, plan)
    candidate_result = validation_engine.validate_incremental(
        candidate,
        invalidated_targets=plan.touched_targets,
        force_full_barriers=True,
    )

    if repair_evaluator.is_strict_improvement(result, candidate_result, plan):
        document = candidate
        result = candidate_result
    else:
        patch_transaction.rollback()
        repair_governor.record_rejection(plan, candidate_result)
```

所有异常必须进入 `RepairExecutionRecord`，禁止 `except Exception: pass`。

---

## 9. Core AutoFix 允许和禁止的边界

### 9.1 Core 可自动执行的修复

#### 输入规范化

- 删除非法控制字符、零宽字符和未配对 surrogate；
- 标准化已声明的 enum 大小写；
- 标准化单位表示；
- 将 registry 明确声明的 alias 转为 canonical name。

Alias 必须由对应 schema / OperationSpec 注册，不能在中心文件维护大字典。

#### 合同派生

- 当 operation 只有一个默认 version 时填入 version；
- 从 OperationSpec 填入唯一确定的 phase；
- 从 Pydantic schema 填入有明确默认值的字段；
- 在唯一匹配时把 output type alias 转成 output name；
- 删除值为 null 且 schema 明确允许省略的可选字段；
- 当且仅当 terminal candidate 唯一时补 root node。

#### 通用空间数值恢复

- 对接近单位长度的方向向量做归一化；
- 对数值误差范围内的 rotation matrix 做正交化；
- 将小于统一 epsilon 的 `-0.0` 归零；
- 仅在 Spatial Contract 明确允许 snap 时处理近重合。

#### 通用几何执行恢复

这类修复优先作用于 runtime execution plan，不修改设计 IR：

- shape clean / heal；
- 有界 fuzzy tolerance 重试；
- associative union 的平衡树或批量 fuse；
- 多刀具体先组合再 cut；
- 大阵列分批执行；
- boolean 失败后的同语义执行策略切换；
- 导出前统一 shape fix。

必须记录：

- 原始执行策略；
- 重试策略；
- tolerance；
- 重试次数；
- 几何后置条件结果。

### 9.2 Core 禁止自动执行的修复

- 未知 dialect 默认成 axisymmetric；
- 通过字符串相似度猜 dialect；
- 删除 unknown operation；
- 删除 component；
- 猜测跨 component 引用；
- 在多个候选中猜 root node；
- 为 profile 填入 10 mm、5 mm 等臆造尺寸；
- 把圆柱自动改成带中心孔零件；
- 镜像半槽型；
- 改孔径、PCD、中心孔或外径；
- 更换用户指定的 thread class；
- 移动零件以消除碰撞；
- 通过重排数组掩盖真实依赖问题；
- 删除 passthrough node；
- 删除 place node；
- 任何以“看起来更像正确机械结构”为依据的修改。

---

## 10. Boolean 与空间修复的专门规范

### 10.1 Boolean Core Validator

Boolean 是跨零件、跨 dialect 的通用能力，应留在 Core，但必须分层：

#### Preflight

- input handle / node 存在；
- 类型为 solid 或允许的 compound；
- bbox 和 frame 可比较；
- 检测明显无交集；
- 检测近重合面；
- 估算 operand volume；
- 根据 effect 判断是否预期有材料变化。

#### Runtime Postcondition

- 输出存在；
- BRepCheck 有效；
- 输出闭合；
- volume > 0；
- cut 后 volume 不应增加；
- intersect 后 volume 不应大于任一输入；
- union 后 volume 不应明显小于最大输入；
- body count 符合 operation contract；
- 检测 sliver、碎片和零面积面。

### 10.2 Boolean Core Repair

Core 只能改变“执行方式”，不能改变“设计参数”：

允许：

- clean / heal；
- bounded fuzzy tolerance；
- boolean operand batching；
- 改变 associative union 的执行树；
- 分批 cut；
- 复制 shape 后重试；
- OCCT 同语义算法 fallback。

禁止：

- 平移刀具体；
- 扩大刀具体；
- 改孔径；
- 改壁厚；
- 改零件位置；
- 删除失败 feature。

需要移动或改变尺寸时，由 Feature / Part Extension 产生语义修复方案。

### 10.3 Spatial Core Repair

允许：

- 坐标表达规范化；
- 方向向量归一化；
- epsilon 范围内 snap；
- 明确等价的 frame 转换。

禁止：

- 为消除碰撞擅自移动 component；
- 默认采用“机械常规位置”；
- 通过名称推断左右、前后、内外；
- 修改用户明确间隙。

---

## 11. 特殊扩展示例：Axisymmetric Hole Pattern

建议把当前 `hole_semantics.py`、`geometric_solver.py` 和 hole repair hints 拆为扩展：

```text
extensions/features/hole/
├─ manifest.py
├─ common_rules.py
├─ common_repairs.py
└─ tests/

extensions/dialects/axisymmetric/
├─ hole_pattern_rules.py
├─ hole_pattern_repairs.py
└─ tests/
```

Manifest 示例：

```yaml
extension_id: feature.axisymmetric_hole_pattern
version: 1.0.0
kind: feature

selectors:
  - dialects: [axisymmetric]
    operations: [cut_circular_hole_pattern]

rules:
  - feature.axisymmetric_hole_pattern.valid_dimensions
  - feature.axisymmetric_hole_pattern.inside_profile
  - feature.axisymmetric_hole_pattern.clear_of_center_bore

repair_providers:
  - feature.axisymmetric_hole_pattern.repair_pcd
  - feature.axisymmetric_hole_pattern.repair_dimensions
```

规则可以从 FactStore 读取：

```text
outer_profile_envelope
center_bore_radius
hole_radius
requested_pcd
minimum_margin
user_locked_parameters
```

计算可行区间：

```text
pcd_min = 2 × (bore_radius + hole_radius + inner_margin)
pcd_max = 2 × (outer_radius - hole_radius - outer_margin)
```

然后生成多个 RepairProposal，而不是直接选一个：

1. Clamp PCD 到可行区间；
2. 减小孔径；
3. 减小中心孔；
4. 增大外轮廓。

风险分类：

- PCD 未锁定、可行区间唯一、变化很小：`domain_semantic`，可按策略自动；
- 修改孔径：`intent_changing`；
- 修改中心孔：`intent_changing`；
- 增大外径：`intent_changing`。

不得像当前 solver 一样直接以“原始毫米变化最小”比较不同参数，因为 1 mm 孔径变化和 1 mm 外径变化并不具有相同设计成本。应由扩展提供归一化 `ChangeCost`。

---

## 12. 特殊扩展示例：Turbine Disk

激活条件必须是：

```text
part_family == "turbine_disk"
```

或明确选中：

```text
selected_domain_skills contains "part.turbine_disk"
```

不得依赖：

```python
"disk" in component_name
"cutter" in component_name
```

扩展可提供：

- hub/web/rim 拓扑关系；
- bore 与 bolt-circle 关系；
- slot 深度与 rim 厚度关系；
- 枞树槽 station 单调性；
- slot profile 对称性；
- 轮缘剩余壁厚；
- part-specific semantic regions；
- 对应 RepairProvider。

“半槽型镜像”只有在扩展确认用户请求的是对称枞树槽、对称轴明确、轮廓端点满足镜像前提时，才能作为 Proposal；否则必须要求重新设计。

---

## 13. OperationSpec 的扩展

当前 `OperationSpec` 已有：

- effect；
- phase；
- input/output types；
- params model；
- postconditions。

建议增加：

```python
class OperationSpec(BaseModel):
    ...
    feature_tags: set[str] = set()
    semantic_roles: set[str] = set()

    canonical_aliases: OperationAliases = OperationAliases()
    validation_extension_ids: list[str] = []
    repair_extension_ids: list[str] = []

    execution_fallbacks: list[ExecutionFallbackSpec] = []
```

示例：

```python
OperationSpec(
    dialect="axisymmetric",
    op="cut_circular_hole_pattern",
    feature_tags={"hole", "pattern", "boolean_cut"},
    semantic_roles={"circular_hole_pattern"},
    validation_extension_ids=[
        "feature.hole",
        "feature.axisymmetric_hole_pattern",
    ],
)
```

这样新增 operation 时，不再修改中心 `PARAM_NAME_FIXES`、`TARGET_VALUE_FIXES` 或中心 AutoFix 顺序。

---

## 14. 现有代码迁移映射

| 当前模块/逻辑 | 迁移目标 | 处理 |
|---|---|---|
| `validation/structure.py` | `rules/core/structure.py` | 保留并适配 Rule Protocol |
| `root_terminal.py` | Core graph/terminal rules | 拆成独立规则 |
| `registry.py` | Core registry contract | 保留 |
| `params.py` | Core operation contract | 保留 |
| `ownership.py` | Core graph ownership | 保留 |
| `graph.py` | Core graph | 保留 |
| `typecheck.py` | Core type system | 保留 |
| `phase.py` | Core contract-derived phase | 保留，但 phase 数据来自 OperationSpec |
| `safety.py` | Core safety | 保留 |
| `composition.py` | Core 引用规则 + Composition Extension | 拆分 |
| `hole_semantics.py` | Hole Feature Extension | 移出 Core |
| `dialect_semantics.py` | Kernel dispatcher / compatibility adapter | 不再承载实际规则 |
| `geometry_preflight.py` | Core policy + Extension Rules | 拆分全局规则和 dialect 规则 |
| `geometric_solver.py` | Axisymmetric Hole / Part Extension | 移出 Core |
| `repair_hints.py` | 各 RepairProvider 自己生成 | 删除中心特殊规则 |
| `authoring/auto_fixer.py` | Repair Providers | 分解后废弃 |
| `repair/patch.py` | `repair_kernel/transaction.py` | 升级为通用原子补丁 |
| `repair/governor.py` | `repair_kernel/governor.py` | 改用 QualityVector |
| `runtime/postconditions.py` | Core Runtime Rules | 统一 Issue 模型 |
| `validation/geometry_validate.py` | Core Runtime Geometry Rules | 统一 Fact / Issue |

具体 AutoFix 迁移：

| 当前 Fix | 新归属 |
|---|---|
| sanitize JSON | Core ingest normalization |
| missing IDs | Core，仅可生成确定性 ID |
| selected dialect alias | Registry alias；禁止未知值默认 axisymmetric |
| operation version | Core contract-derived |
| output names | Core contract-derived |
| phase name | Core contract-derived |
| phase ordering | 不再通过排序修复；Planner 使用依赖图 |
| param names | OperationSpec alias / Feature Extension |
| target values | 对应 operation / feature extension |
| thread class mapping | Thread Feature Extension |
| path points x→x_mm | Sweep Feature Extension 或 schema alias |
| root node | Core，仅唯一 terminal candidate 时 |
| cross-component refs | 默认不自动；仅唯一可证明时 Proposal |
| strip passthrough nodes | Graph optimizer，不属于 AutoFix |
| remove place before pattern | Composition Extension |
| profile stations | Axisymmetric Extension，禁止臆造默认尺寸 |
| slot station order | Slot / Turbine Disk Extension |
| slot half profile | Turbine Disk Extension，默认需确认 |
| unknown op deletion | 禁止自动 |
| remove extra params | schema normalization，但必须确认字段确实无语义 |

---

## 15. Validation 执行器规范

### 15.1 规划

`ValidationPlanner`：

1. 加载全部 Core Rules；
2. 根据 ActivationSnapshot 加载 Extensions；
3. 应用 selectors；
4. 构建 rule dependency DAG；
5. 检查冲突；
6. 按 stage 建立 execution plan；
7. 对同 stage 无依赖规则允许并行。

### 15.2 执行记录

每条规则必须产生：

```python
class RuleExecutionRecord(BaseModel):
    rule_id: str
    rule_version: str
    provider_id: str
    status: Literal["passed", "failed", "skipped", "timed_out", "provider_error"]
    duration_ms: float
    target_count: int
    issue_ids: list[str]
    produced_fact_keys: list[str]
    skip_reason: str | None
```

### 15.3 异常策略

规则抛异常时：

- 不得让整个 Python 进程崩溃；
- 生成 `kernel.rule_provider_error`；
- Core Rule 异常默认 fatal；
- Extension Rule 异常是否阻断由 policy 决定，但必须可见；
- 不得静默 pass。

### 15.4 增量验证

Patch 应声明 touched targets。Kernel 维护依赖：

```text
param change
→ node contract rules
→ downstream graph rules
→ component semantic rules
→ geometry preflight
→ runtime geometry
```

增量验证用于效率，但提交修复前仍要运行强制全量 barrier：

- Core graph；
- Core contract；
- Core runtime model；
- artifact gate。

---

## 16. Policy 配置

所有阈值从代码常量迁移到统一配置：

```yaml
validation:
  max_nodes: 64
  max_boolean_ops: 256
  max_profile_points: 128
  max_pattern_instances: 360
  rule_timeout_ms: 1500
  total_budget_ms: 20000

geometry:
  fuzzy_zero_mm: 1.0e-6
  min_boolean_clearance_mm: 0.2
  max_fuzzy_retry_mm: 0.05
  min_edge_length_mm: 0.25

repair:
  max_attempts: 3
  auto_apply_risks:
    - normalization
    - contract_derived
    - geometry_recovery
  allow_domain_semantic: false
  allow_intent_changing: false
  allow_destructive: false
  max_touched_nodes: 8
  require_full_core_regression: true
```

Extension 可以声明自己的默认阈值，但必须命名空间化：

```yaml
extensions:
  feature.axisymmetric_hole_pattern:
    min_inner_margin_mm: 1.0
    min_outer_margin_mm: 1.0
```

---

## 17. 分阶段实施计划

### Phase 0：建立行为基线

在改代码前：

1. 收集当前成功/失败样例；
2. 保存 raw、canonical、validation report、autofix report、STEP metadata；
3. 建立 golden corpus；
4. 为所有现有 validator 和 fix 建立行为测试；
5. 标记当前不安全修复，不要求新系统保持这些错误行为。

交付：

```text
tests/golden_validation/
tests/golden_repair/
```

### Phase 1：引入统一模型与 Registry，不改行为

新增：

- ValidationStage；
- RuleManifest；
- ValidationContext；
- ValidationIssue v2；
- RuleRegistry；
- ExtensionManifest；
- ActivationSnapshot。

把现有 validator 包装为 LegacyRuleAdapter。

目标：旧 pipeline 的结果可以通过新 Executor 复现。

### Phase 2：重构 Validation Pipeline

1. 用 Registry 替换硬编码 `RAW_STAGES` / `CANONICAL_STAGES`；
2. 同 stage 聚合全部问题；
3. 增加 prerequisite / skipped 机制；
4. 统一 runtime postcondition 和 geometry issue；
5. 删除各模块自由 stage 字符串；
6. governor 不再维护 stage rank。

### Phase 3：建立 Repair Kernel

1. 创建 RepairProposal 和 PatchTransaction；
2. 让每个修复订阅明确 Issue；
3. 引入风险策略；
4. 引入 conflict graph；
5. 引入 QualityVector；
6. Web 改为 validate → propose → plan → transaction → revalidate；
7. 删除 `except Exception: pass`。

此阶段保留 `auto_fixer.py` 作为兼容入口，但内部必须调用新 Repair Engine。

### Phase 4：抽取 Extension

按顺序抽取：

1. Hole Feature；
2. Axisymmetric；
3. Sketch Profile / Profile Station；
4. Slot / Pattern；
5. Thread；
6. Composition；
7. Turbine Disk。

每抽取一类：

- Core 文件中删除对应 op 名判断；
- 增加 extension activation 测试；
- 验证该 extension 未激活时规则绝不运行。

### Phase 5：删除双轨制

删除或正式 deprecated：

- 中心化 `authoring/auto_fixer.py` 规则实现；
- 特殊 `repair_hints.py`；
- 特殊 `geometric_solver.py` 在 validation 核心中的入口；
- dialect 黑盒 validator 的生产依赖；
- `STAGE_RANK`；
- 手写 patch path 分发。

### Phase 6：性能与治理

- FactStore 缓存；
- 独立规则并行；
- 增量验证；
- Extension contract hash；
- 启动期治理检查；
- 插件超时和隔离；
- metadata 中保存 activated extensions 和 rule versions。

---

## 18. 代码 Agent 的具体任务清单

### 新建文件

```text
validation_kernel/stages.py
validation_kernel/models.py
validation_kernel/context.py
validation_kernel/facts.py
validation_kernel/selectors.py
validation_kernel/registry.py
validation_kernel/activation.py
validation_kernel/planner.py
validation_kernel/executor.py
validation_kernel/conflict.py
validation_kernel/policy.py

repair_kernel/models.py
repair_kernel/registry.py
repair_kernel/planner.py
repair_kernel/transaction.py
repair_kernel/authorizer.py
repair_kernel/evaluator.py
repair_kernel/governor.py
repair_kernel/policy.py
```

### 修改文件

```text
dialects/operation.py
  增加 feature_tags、semantic_roles、aliases、extension ids。

skills/schemas.py
  将 part_intent 强类型化，保留向后兼容解析。

validation/pipeline.py
  改为新 Engine 的兼容 wrapper。

runtime/postconditions.py
validation/geometry_validate.py
  改为统一 RuleResult / ValidationIssue。

app/text-to-cad/server/main.py
  接入 issue-driven repair loop，不再调用盲目 auto_fix。
```

### 初期兼容

保留以下外部 API：

```python
validate_and_canonicalize(...)
validate_and_canonicalize_with_bundle(...)
auto_fix(...)
auto_fix_with_report(...)
```

但内部实现委托新系统，并在报告中标记 deprecated compatibility path。

---

## 19. 测试要求

### 19.1 Rule Contract Test

每个规则必须通过：

- rule_id 唯一；
- issue code 已声明；
- 无输入修改；
- 相同输入结果确定；
- 不读取未声明 Fact；
- 超时受控；
- provider exception 可报告。

### 19.2 Repair Contract Test

每个 RepairProvider 必须验证：

- 只响应声明的 Issue；
- Proposal 包含目标 Issue fingerprint；
- patch 路径在 capability 内；
- 前置条件失败时不修改文档；
- 重复执行幂等；
- 修复后目标 Issue 消失；
- 不新增 Core Error；
- 风险等级准确；
- 用户锁定参数不会被自动修改。

### 19.3 Extension Activation Test

至少验证：

1. 未命中 selector 时 extension 不加载；
2. 命中 dialect/op 时 feature extension 加载；
3. 明确 part_family 时 part extension 加载；
4. 低置信推断只进入 advisory；
5. extension 缺失依赖时启动失败；
6. extension 冲突时启动失败；
7. extension 异常不会静默。

### 19.4 Property-based / Fuzz Test

- 随机缺失 ID；
- 随机断引用；
- 随机环；
- NaN / Inf；
- 随机错误 alias；
- 极大阵列；
- 近重合 boolean；
- 空 shape；
- 重复 repair；
- 冲突 proposal；
- patch old_value 不匹配。

### 19.5 回归测试

对现有 golden corpus 比较：

- Issue fingerprint；
- activated rules；
- applied proposals；
- accepted / rejected patch；
- canonical hash；
- geometry metadata；
- STEP round-trip。

---

## 20. 验收标准

只有全部满足时，重构才算完成：

1. 新增一个特殊零件扩展，不修改 Kernel 和 Core Rule 文件。
2. Core 代码中不出现 `turbine_disk`、`cut_circular_hole_pattern`、`fir_tree` 等特殊名称。
3. Kernel 不 import 任一具体 dialect / part extension。
4. 所有修复都能追溯到一个或多个 ValidationIssue。
5. 不再存在“验证失败后运行全部 fix”的路径。
6. 不再存在两个不同 Repair 安全合同。
7. Extension 不能覆盖或降低 Core Error。
8. 修复采用原子事务，失败和回归能够回滚。
9. 每次 accepted repair 都通过完整 Core 回归验证。
10. 所有 rule、extension、repair provider 均版本化并进入 metadata。
11. 相同输入、相同 registry、相同 policy 得到相同 rule plan、Issue 顺序和 repair plan。
12. 新增 stage 不需要修改 governor。
13. 线上入口不再吞掉 Validation / Repair 异常。
14. 自动修复默认不会删除节点、删除组件、猜 dialect、猜设计尺寸或移动零件。
15. Hole、slot、thread、turbine disk 等规则可以按 selector 自动加载，并在非目标零件上完全不运行。

---

## 21. 禁止代码 Agent 采取的捷径

- 不允许只把 `auto_fixer.py` 拆成多个文件，但仍由中心函数固定顺序调用。
- 不允许 Extension 通过修改全局 list 注册。
- 不允许使用 import side effect 构建可变 Registry。
- 不允许 Validator 直接修改文档。
- 不允许 RepairProvider 重新运行 LLM 来决定安全补丁。
- 不允许用 priority 掩盖写冲突。
- 不允许通过 component 名称猜 part-family。
- 不允许对异常使用空 `except`。
- 不允许把所有特殊规则继续塞进 dialect 的单个 `validate_component()`。
- 不允许为了通过验证而降低 required、删除失败节点或静默退化。
- 不允许把“能成功生成 STEP”当成“设计语义正确”。

---

## 22. 最终目标状态

重构完成后，Validation 与 AutoFix 应成为一个稳定的工程规则平台：

```text
Kernel
  只负责框架、通用不变量、冲突治理和安全事务，
  长期保持小而稳定。

Extensions
  负责特殊 Feature、Dialect、Part 和 Domain 语义，
  可以独立添加、版本化、测试、启用和禁用。

Validation
  输出结构化、可追踪、可组合的 Issue 与 Fact。

Repair
  根据 Issue 提出候选方案，
  经过策略、冲突分析和回归验证后才允许提交。

新增零件
  不再增加核心复杂度，
  只增加一个遵守统一合同的扩展包。
```

这应成为后续所有 CAD 特殊结构、制造约束、CAE 语义区域和行业规则扩展的统一基础。
