

---

# G-CAD IR LLM 幻觉抑制与稳定生成工程实现文档

## 0. 背景与目标

当前 SeekFlow Generative CAD-IR 链路的目标不是把 LLM 变成新的 deterministic primitive 生成器，也不是让 LLM 直接写 CadQuery / SolidWorks / NX / APDL 代码。规划文档明确要求：LLM 只写受控 CAD Grammar，Base / Dialect 解释并执行 Grammar，系统负责结构校验、语义校验、几何预检、STEP 导出和 metadata，最终只在 STEP + metadata 验证通过后并入主链路后半段。

本次改造目标是：

```text
降低 LLM 输出 G-CAD IR 时的 hallucination；
提高 schema / op / params / graph wiring 正确率；
保留 Dialect Compiler 的泛化价值；
避免退化成 primitive；
让失败可分类、可修复、可评测。
```

本工程文档采用以下核心判断：

```text
LLM 负责理解、规划、选择、局部参数推断；
系统负责 schema、固定字段、默认安全约束、graph assembly、validation、repair governance；
Dialect Compiler 负责类型、phase、operation contract、semantic preflight、runtime boundary。
```

---

# 1. 必须采用的稳定策略

本次只实现以下策略：

| 策略                                                             | 工程有效性 | 是否实现               |
| -------------------------------------------------------------- | ----: | ------------------ |
| Strict tool calling / structured output schema                 |     高 | 必须                 |
| 本地 RawGcadDocument + Dialect Validator                         |    极高 | 必须                 |
| 只加载 selected dialect 的上下文                                      |     高 | 必须                 |
| 自动生成 Level-2 Dialect Usage Skill                               |     高 | 必须                 |
| 系统侧生成 envelope / fixed fields / safe defaults                  |     高 | 必须                 |
| Failure taxonomy + metrics                                     |     高 | 必须                 |
| Validator-driven local repair patch                            |     高 | 必须                 |
| Staged generation：route → feature sequence → params → assemble |    中高 | 分阶段实现              |
| 少量高质量 examples + anti-examples                                 |    中高 | 实现                 |
| V4 Pro 替代 Flash 做 Level-2 / repair                             |    中高 | 支持配置               |
| JSON Output fallback                                           |     中 | 只做 fallback，不作为主路径 |

DeepSeek 官方 Tool Calls 文档显示 strict mode 需要 beta endpoint、每个 function 设置 `strict: true`，并且 server 会校验 function JSON Schema；同时 strict mode 支持的 JSON Schema 类型有限，object 的所有 properties 必须 required，且 `additionalProperties` 必须为 false。([DeepSeek API Docs][1]) DeepSeek JSON Output 只保证 valid JSON string，并要求设置 `response_format={"type":"json_object"}`、prompt 中包含 json 示例、合理设置 `max_tokens`，且官方提示偶尔可能返回 empty content。([DeepSeek API Docs][2]) 因此主路径必须使用 strict tool calling + 本地 validator，而不是 JSON Output。

OpenAI Structured Outputs 文档也明确区分 structured outputs 与 JSON mode：JSON mode 只保证 valid JSON，不保证 schema adherence；structured outputs 才保证遵守 schema。([OpenAI Developers][3]) 这进一步支持本次工程方向：**JSON 可解析不是成功，schema + dialect validation 通过才是成功。**

---

# 2. 硬约束

Claude Code 必须严格遵守以下约束。

## 2.1 禁止修改的内容

```text
MUST NOT modify:
- deterministic primitive path semantics
- cadquery_backend/primitive_compiler.py
- geometry_primitives/
- PRIMITIVE_COMPILERS
- CADPartSpec existing semantics
- existing primitive registry behavior
```

规划文档明确要求现有主链路必须保持不变，新链路不能污染 Primitive registry / primitive compiler / geometry_primitives。

## 2.2 LLM 永远不能做的事

```text
LLM MUST NOT:
- write CadQuery code
- write Python runtime code
- call cq.exporters.export
- control file paths
- call subprocess
- write SolidWorks COM
- write NXOpen
- write APDL
- decide validation pass/fail
- disable safety
- invent dialect
- invent operation
- invent op_version
- invent params field
- directly enter dialect runner
```

规划文档里已经明确 LLM 是“受约束 CAD Grammar 作者”，负责理解意图、选择 Base / Dialect、输出 Feature Graph 和局部 repair patch；不负责写完整 CAD 脚本、调用后端、决定验证、关闭 safety 或发明不存在的 Base / op。

## 2.3 Generative CAD 不得退化成 Primitive

```text
MUST NOT add operation names like:
- make_flange
- make_bracket
- make_turbine_disk
- make_mounting_plate
- make_gearbox
- build_standard_part
- generate_part
```

Base / Dialect 必须是 CAD Grammar / Dialect，面向建模范式，不是具体零件；Feature graph 可变，operation 数量可变，默认 trust level 低于 Primitive。

## 2.4 所有 LLM 输出必须 fail-closed

```text
All LLM outputs MUST pass:
1. provider tool schema parse
2. local JSON parse
3. Pydantic model validation
4. Core IR validation
5. Dialect registry validation
6. Operation params validation
7. graph validation
8. type validation
9. phase validation
10. safety validation
11. dialect semantic validation
12. geometry preflight
```

任何失败都必须结构化记录，不允许 silent fallback。

---

# 3. 目标架构

本次实现后的目标链路：

```text
User request
  ↓
Level-1 route tool call
  ↓
RoutePlan
  ↓
System loads selected BasePackage + Dialect Contract
  ↓
Generated Level-2 Usage Skill
  ↓
FeatureSequence tool call
  ↓
NodeParams tool call per node/op
  ↓
System-side RawGcad assembler
  ↓
RawGcadDocument
  ↓
parse / validate / canonicalize
  ↓
CanonicalGcadDocument
  ↓
Dialect Compiler / Runtime
  ↓
STEP + metadata
```

如果要先做低风险 MVP，可以先实现：

```text
User request
  ↓
Level-1 route tool call
  ↓
Selected dialects
  ↓
Generated Level-2 Skill
  ↓
RawGcadDocument strict tool call
  ↓
local validation
  ↓
local repair patch loop
```

但最终推荐 staged generation，因为它能显著减少 LLM 一次性记忆过多字段导致的 hallucination。

---

# 4. 新增模块总览

建议新增或调整以下模块：

```text
generative_cad/
  llm/
    __init__.py
    provider.py
    deepseek_client.py
    models.py
    tool_calling.py
    errors.py

  authoring/
    __init__.py
    schemas.py
    prompts.py
    route.py
    feature_sequence.py
    node_params.py
    raw_assembler.py
    context_builder.py
    strict_schema.py
    failure_taxonomy.py
    metrics.py

  base_packages/
    __init__.py
    models.py
    registry.py
    generator.py
    axisymmetric/
      package.py
      examples/
      anti_examples/
    sketch_extrude/
      package.py
      examples/
      anti_examples/
    composition/
      package.py
      examples/
      anti_examples/

  skills/
    level2_usage.py
    tool_schema_compiler.py

  repair/
    patch_schema.py
    governor.py
    session.py
    apply_patch.py
    signatures.py

  tests/
    ...
```

---

# 5. LLM Provider 抽象

## 5.1 新增 `generative_cad/llm/models.py`

```python
from enum import Enum
from pydantic import BaseModel, Field


class LlmProvider(str, Enum):
    DEEPSEEK = "deepseek"


class LlmModelRole(str, Enum):
    ROUTER = "router"
    AUTHOR = "author"
    REPAIR = "repair"


class LlmModelConfig(BaseModel):
    provider: LlmProvider = LlmProvider.DEEPSEEK
    model: str
    base_url: str
    use_strict_tools: bool = True
    use_json_output_fallback: bool = False
    timeout_s: int = 90
    max_retries: int = 2
    temperature: float | None = None
    reasoning_enabled: bool = False
    reasoning_effort: str | None = None


class AuthoringLlmConfig(BaseModel):
    router: LlmModelConfig
    author: LlmModelConfig
    repair: LlmModelConfig
```

## 5.2 默认模型策略

```python
DEFAULT_DEEPSEEK_CONFIG = AuthoringLlmConfig(
    router=LlmModelConfig(
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/beta",
        use_strict_tools=True,
    ),
    author=LlmModelConfig(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/beta",
        use_strict_tools=True,
    ),
    repair=LlmModelConfig(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/beta",
        use_strict_tools=True,
    ),
)
```

原则：

```text
Router 可使用 Flash 或 Pro；
Author 必须默认使用 Pro；
Repair 必须默认使用 Pro；
JSON Output 只能 fallback；
strict tools 是主路径。
```

## 5.3 新增 `llm/provider.py`

```python
from typing import Protocol, Any
from pydantic import BaseModel


class ToolCallResult(BaseModel):
    tool_name: str
    arguments: dict
    raw_response_id: str | None = None
    model: str
    provider: str


class LlmToolCaller(Protocol):
    def call_strict_tool(
        self,
        *,
        messages: list[dict],
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        model_config,
    ) -> ToolCallResult:
        ...
```

## 5.4 DeepSeek 实现要求

`deepseek_client.py` 必须：

```text
MUST use beta endpoint when strict_tools=True.
MUST set function.strict = true.
MUST set tool_choice to the required function name.
MUST parse function.arguments as JSON.
MUST fail if no tool_call is returned.
MUST fail if multiple unrelated tool_calls are returned.
MUST not trust provider schema alone.
MUST return parsed dict to local Pydantic validation.
```

示例：

```python
class DeepSeekToolCaller:
    def call_strict_tool(
        self,
        *,
        messages: list[dict],
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        model_config: LlmModelConfig,
    ) -> ToolCallResult:
        client = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=model_config.base_url,
        )

        tools = [{
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_description,
                "strict": True,
                "parameters": tool_schema,
            },
        }]

        response = client.chat.completions.create(
            model=model_config.model,
            messages=messages,
            tools=tools,
            tool_choice={
                "type": "function",
                "function": {"name": tool_name},
            },
            timeout=model_config.timeout_s,
        )

        message = response.choices[0].message
        if not message.tool_calls:
            raise LlmToolCallError("Model returned no tool call")

        if len(message.tool_calls) != 1:
            raise LlmToolCallError("Expected exactly one tool call")

        call = message.tool_calls[0]
        if call.function.name != tool_name:
            raise LlmToolCallError(f"Unexpected tool call: {call.function.name}")

        try:
            args = json.loads(call.function.arguments)
        except Exception as exc:
            raise LlmToolCallError("Tool arguments were not valid JSON") from exc

        return ToolCallResult(
            tool_name=call.function.name,
            arguments=args,
            raw_response_id=getattr(response, "id", None),
            model=model_config.model,
            provider="deepseek",
        )
```

---

# 6. DeepSeek Strict Schema Compiler

## 6.1 目的

不要直接把 Pydantic 原始 schema 丢给 DeepSeek strict mode。DeepSeek strict mode 对 schema 子集有限，object 的所有 properties 必须 required，且 `additionalProperties=false`。([DeepSeek API Docs][1])

新增：

```text
generative_cad/authoring/strict_schema.py
```

## 6.2 API

```python
def to_deepseek_strict_schema(schema: dict) -> dict:
    """
    Convert a Pydantic/OpenAPI-style JSON schema into the subset accepted by
    DeepSeek strict tool calling.

    This function must be deterministic.
    It must not weaken semantic validation silently.
    Constraints unsupported by DeepSeek must be moved to local validator metadata
    or removed with explicit diagnostics.
    """
```

## 6.3 转换规则

```text
MUST:
- set additionalProperties=false on every object
- set required to all property names on every object
- inline or preserve $defs only if provider accepts them; otherwise inline
- preserve enum
- preserve const
- preserve anyOf if all branches are valid
- preserve number minimum / maximum / exclusiveMinimum / exclusiveMaximum
- preserve string pattern / format if supported
- strip unsupported minLength / maxLength for DeepSeek
- strip unsupported minItems / maxItems for DeepSeek
- store stripped constraints in x-local-validation if needed
```

## 6.4 Optional 字段策略

DeepSeek strict mode 要求 object 的所有 properties 都 required。对于 Python optional 字段，转换为 nullable：

```json
{
  "anyOf": [
    {"type": "string"},
    {"type": "null"}
  ]
}
```

不要简单删除 optional 字段，因为那会造成 provider schema 和 local schema 不一致。

## 6.5 禁止

```text
MUST NOT:
- allow additionalProperties=true
- omit required on object
- pass unsupported schema keywords without tests
- rely on provider schema as final validation
- silently drop enum / const
```

## 6.6 测试

```text
test_deepseek_schema_all_objects_additional_properties_false
test_deepseek_schema_all_object_properties_required
test_optional_fields_become_nullable_anyof
test_enum_and_const_preserved
test_unsupported_min_items_removed_with_local_marker
test_unsupported_min_length_removed_with_local_marker
test_schema_compiler_is_deterministic
```

---

# 7. Authoring Schema 设计

为了减少幻觉，不让 LLM 一次性输出完整 RawGcadDocument。先引入中间 authoring schema。

## 7.1 新增 `authoring/schemas.py`

### 7.1.1 RoutePlan

```python
class RouteDecision(str, Enum):
    PRIMITIVE = "primitive"
    GENERATIVE_CAD_IR = "generative_cad_ir"
    UNSUPPORTED = "unsupported"
    NEEDS_CLARIFICATION = "needs_clarification"


class SelectedDialectDraft(BaseModel):
    dialect: str
    version: str
    reason: str


class RoutePlan(BaseModel):
    route_decision: RouteDecision
    part_intent: dict
    selected_dialects: list[SelectedDialectDraft]
    selected_domain_skills: list[str] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
```

Rules:

```text
If route_decision=generative_cad_ir:
  selected_dialects MUST be non-empty.

If route_decision=unsupported:
  unsupported_capabilities MUST be non-empty.

If route_decision=needs_clarification:
  clarification_questions MUST be non-empty.

RoutePlan MUST NOT contain nodes or params.
```

### 7.1.2 FeatureSequenceDraft

```python
class ComponentDraft(BaseModel):
    component_id: str
    owner_dialect: str
    kind_hint: str
    description: str


class NodePlanDraft(BaseModel):
    node_id: str
    component_id: str
    dialect: str
    op: str
    op_version: str
    phase: str
    purpose: str
    expected_input_source: str | None = None
    expected_output_name: str = "body"
    required: bool = True
    degradation_policy: str = "fail"


class FeatureSequenceDraft(BaseModel):
    components: list[ComponentDraft]
    node_sequence: list[NodePlanDraft]
    assumptions: list[str] = Field(default_factory=list)
    unsupported_details: list[str] = Field(default_factory=list)
```

Rules:

```text
FeatureSequenceDraft MUST NOT contain node.params.
FeatureSequenceDraft MUST NOT contain safety or constraints.
FeatureSequenceDraft MUST only use selected dialects.
FeatureSequenceDraft MUST only use operations from loaded contract.
```

### 7.1.3 NodeParamsDraft

```python
class NodeParamsDraft(BaseModel):
    node_id: str
    dialect: str
    op: str
    op_version: str
    params: dict
    assumptions: list[str] = Field(default_factory=list)
```

Rules:

```text
NodeParamsDraft is validated against OperationSpec.params_model immediately.
No extra params allowed.
No missing params allowed.
```

### 7.1.4 RawAssemblyResult

```python
class RawAssemblyResult(BaseModel):
    raw_document: dict
    source_route_plan_hash: str
    source_feature_sequence_hash: str
    source_node_params_hashes: dict[str, str]
    system_filled_fields: list[str]
```

---

# 8. BasePackage 与 Level-2 Skill

规划文档强调 Skill 是 LLM 使用 Base 的指导材料，不是执行器；Skill 不写 CAD 代码，不替代 Base Contract，不包含 runner 源码，也不直接生成 STEP。 二级 Skill 的作用是在 Base / Dialect 选中后，告诉 LLM 当前 Dialect 有哪些 op、phase 顺序、节点组织方式、输入输出示例和常见错误。

## 8.1 新增 `base_packages/models.py`

```python
class BasePackageManifest(BaseModel):
    package_id: str
    dialect_id: str
    dialect_version: str
    title: str
    summary: str
    modeling_paradigm: str
    typical_geometry: list[str]
    typical_parts: list[str]
    main_ops: list[str]
    unsupported_cases: list[str]
    primitive_preferred_when: list[str]
    safety_notes: list[str]
    composition_notes: list[str] = Field(default_factory=list)


class BasePackageExample(BaseModel):
    example_id: str
    title: str
    user_request: str
    route_plan: dict | None = None
    feature_sequence: dict | None = None
    raw_document: dict | None = None
    notes: list[str] = Field(default_factory=list)


class BasePackageAntiExample(BaseModel):
    anti_example_id: str
    title: str
    bad_output: dict | str
    reason: str
    expected_validator_error: str | None = None


class BasePackage(BaseModel):
    manifest: BasePackageManifest
    examples: list[BasePackageExample]
    anti_examples: list[BasePackageAntiExample]
    contract_hash: str
    level2_usage_skill_hash: str | None = None
```

## 8.2 新增 `skills/level2_usage.py`

```python
def generate_level2_usage_skill(
    *,
    package: BasePackage,
    dialect,
    max_examples: int = 3,
    max_anti_examples: int = 3,
) -> str:
    ...
```

必须生成以下结构：

```markdown
# Dialect Usage Skill: <dialect_id>

## 1. Purpose
该 dialect 负责的建模范式。

## 2. When to use
来自 BasePackage manifest。

## 3. When not to use
unsupported cases 和 primitive_preferred_when。

## 4. Core graph pattern
component / node / input / output / root_node 组织规则。

## 5. Phase order
从 dialect contract 或 OperationSpec 提取。

## 6. Available operations
每个 operation 必须包含：
- op
- op_version
- phase
- input types
- output types
- params schema 摘要
- effects
- postconditions
- common mistakes
- param meaning

## 7. Valid examples
少量高质量例子。

## 8. Anti-examples
明确展示 forbidden pattern。

## 9. Repair hints
只允许局部 patch，不允许重写整图。
```

## 8.3 必须避免的错误

```text
MUST NOT hard-code operation descriptions in orchestrator.py.
MUST NOT hand-maintain duplicated params schema in prompts.
MUST NOT include runner source code in Level-2 Skill.
MUST NOT include CadQuery code.
MUST NOT include unselected dialect operations.
```

## 8.4 Skill 生成数据源优先级

```text
1. OperationSpec
2. params_model Field descriptions
3. dialect contract
4. BasePackage manifest
5. examples / anti-examples
6. manual notes
```

`OperationSpec` 和 `params_model` 是 source of truth。二级 Skill 是派生产物，不是事实源。

---

# 9. Context Builder：只加载 selected dialect

规划文档说明，如果只给 LLM 一个巨大 Skill，会导致上下文过长、Base 一多就混乱、LLM 混用不同 Base 的 op、Base 更新后 Skill 漂移、参数 schema 和 runner 不一致。解决方式是先用一级 Skill 选择 Base，再加载选中 Base 的二级 Skill / Contract。

新增：

```text
authoring/context_builder.py
```

## 9.1 API

```python
class AuthoringContext(BaseModel):
    route_plan: RoutePlan
    selected_dialects: list[str]
    dialect_contracts: dict[str, dict]
    level2_usage_skills: dict[str, str]
    tool_schema_hash: str
    context_hash: str


def build_authoring_context(
    *,
    route_plan: RoutePlan,
    dialect_registry,
    base_package_registry,
) -> AuthoringContext:
    ...
```

## 9.2 规则

```text
MUST load only route_plan.selected_dialects.
MUST fail if selected dialect is not registered.
MUST fail if selected dialect has no BasePackage.
MUST fail if BasePackage.contract_hash != dialect.contract_hash.
MUST generate Level-2 usage skill from current contract.
MUST not include unselected dialect operations.
```

## 9.3 测试

```text
test_context_builder_loads_only_selected_dialects
test_context_builder_rejects_unregistered_dialect
test_context_builder_rejects_missing_base_package
test_context_builder_rejects_contract_hash_mismatch
test_context_builder_does_not_include_unselected_ops
```

---

# 10. Tool Schema Compiler

新增：

```text
skills/tool_schema_compiler.py
```

## 10.1 Route tool schema

`emit_route_plan` schema 只允许输出 RoutePlan。

```python
def compile_route_plan_tool_schema(
    *,
    dialect_manifest_catalog: dict,
    primitive_catalog_summary: dict | None,
) -> dict:
    ...
```

要求：

```text
MUST include dialect enum from registry.
MUST include route_decision enum.
MUST not include operation params.
MUST not include RawGcadDocument fields.
```

## 10.2 Feature sequence tool schema

```python
def compile_feature_sequence_tool_schema(
    *,
    selected_dialects: list[str],
    dialect_registry,
) -> dict:
    ...
```

要求：

```text
MUST restrict dialect to selected_dialects.
MUST restrict op to OperationSpec ops of selected_dialects.
MUST set op_version const/enum from OperationSpec.
MUST restrict phase to OperationSpec.phase.
MUST not include params.
```

## 10.3 Node params tool schema

```python
def compile_node_params_tool_schema(
    *,
    node_plan: NodePlanDraft,
    operation_spec: OperationSpec,
) -> dict:
    ...
```

要求：

```text
MUST expose exactly one op params_model schema.
MUST set dialect/op/op_version const.
MUST not expose other operation params.
MUST apply to_deepseek_strict_schema().
```

## 10.4 Optional raw document tool schema

如果先做 MVP，可以实现：

```python
def compile_raw_gcad_tool_schema(
    *,
    selected_dialects: list[str],
    dialect_registry,
) -> dict:
    ...
```

但长期不应作为唯一主路径。

## 10.5 测试

```text
test_route_tool_schema_contains_no_params
test_feature_sequence_tool_schema_restricts_to_selected_dialects
test_feature_sequence_tool_schema_uses_operation_spec_versions
test_node_params_tool_schema_contains_only_one_op
test_node_params_tool_schema_rejects_extra_params
test_raw_tool_schema_optional_and_not_default_for_staged_pipeline
```

---

# 11. Prompt 设计

Prompt 是辅助，不是安全边界。安全边界是 strict schema + local validator。

## 11.1 Level-1 Routing Prompt

文件：

```text
authoring/prompts.py
```

```python
LEVEL1_ROUTING_SYSTEM_PROMPT = """
You are a constrained CAD route planner for SeekFlow Generative CAD-IR.

You do not write CAD code.
You do not output RawGcadDocument.
You do not invent dialects.
You do not invent operations.
You only choose a route and selected dialects from the provided catalog.

Your job:
1. Understand the user's part intent.
2. Decide whether the request should use deterministic primitive, generative CAD-IR, unsupported, or needs clarification.
3. If generative CAD-IR is appropriate, select the minimal set of dialects.
4. If a deterministic primitive is clearly better for a high-trust known part, choose primitive.
5. If the request asks for certified, airworthy, manufacturing-ready, production-ready, installable, or structurally validated output, do not route to unrestricted generative output.
6. If the geometry requires unsupported capability, return unsupported or needs_clarification.

You must emit exactly one tool call: emit_route_plan.
"""
```

User prompt template:

```python
LEVEL1_ROUTING_USER_TEMPLATE = """
USER_REQUEST:
{user_request}

AVAILABLE_DIALECT_MANIFESTS:
{dialect_manifest_catalog}

PRIMITIVE_CATALOG_SUMMARY:
{primitive_catalog_summary}

DOMAIN_SKILLS:
{domain_skills}

OUTPUT:
Call emit_route_plan only.
"""
```

## 11.2 Level-2 Feature Sequence Prompt

```python
FEATURE_SEQUENCE_SYSTEM_PROMPT = """
You are a constrained G-CAD feature sequence planner.

You are not a CAD programmer.
You must not write Python, CadQuery, SolidWorks, NX, APDL, file paths, or runner code.

You must only use:
- selected dialects listed in SELECTED_DIALECTS
- operations listed in DIALECT_CONTRACTS
- op_version exactly as listed
- phase exactly as listed

You must not output params in this stage.
You must not invent params.
You must not invent operations.
You must not use unselected dialects.

Your task:
1. Create a component plan.
2. Create an ordered node sequence.
3. Each node must reference an existing selected dialect and operation.
4. Do not wire detailed inputs unless necessary; the system will wire simple linear solid chains.
5. If the requested geometry cannot be represented by the selected dialects, report unsupported_details.

You must emit exactly one tool call: emit_feature_sequence.
"""
```

User prompt:

```python
FEATURE_SEQUENCE_USER_TEMPLATE = """
USER_REQUEST:
{user_request}

ROUTE_PLAN:
{route_plan_json}

SELECTED_DIALECTS:
{selected_dialects}

LEVEL_2_USAGE_SKILLS:
{level2_usage_skills}

DIALECT_CONTRACTS:
{dialect_contracts}

OUTPUT:
Call emit_feature_sequence only.
"""
```

## 11.3 Node Params Prompt

```python
NODE_PARAMS_SYSTEM_PROMPT = """
You are a constrained parameter author for one G-CAD operation.

You must only fill params for the single operation provided.
You must not change dialect, op, op_version, phase, node_id, component_id, inputs, outputs, safety, or constraints.
You must not invent parameter names.
You must not omit required parameters.
If a dimension is not specified by the user, choose a conservative reference-geometry default and record it in assumptions.
If the missing value is topology-critical, state the assumption explicitly.

You must emit exactly one tool call: emit_node_params.
"""
```

User prompt:

```python
NODE_PARAMS_USER_TEMPLATE = """
USER_REQUEST:
{user_request}

ROUTE_PLAN:
{route_plan_json}

FEATURE_SEQUENCE:
{feature_sequence_json}

CURRENT_NODE:
{node_plan_json}

OPERATION_SPEC:
{operation_spec_json}

PARAMETER_USAGE_NOTES:
{operation_usage_notes}

OUTPUT:
Call emit_node_params only.
"""
```

---

# 12. System-side RawGcad Assembler

新增：

```text
authoring/raw_assembler.py
```

## 12.1 目的

不要让 LLM 写固定字段。系统负责生成：

```text
schema_version
document_id
units
trust_level
selected_dialects with versions
components.owner_dialect
constraints
safety
node.required
node.degradation_policy
op_version
default output names
linear solid-chain inputs
root_node
```

## 12.2 API

```python
def assemble_raw_gcad_document(
    *,
    user_request: str,
    route_plan: RoutePlan,
    feature_sequence: FeatureSequenceDraft,
    node_params: dict[str, NodeParamsDraft],
    dialect_registry,
    document_id: str | None = None,
    units: str = "mm",
) -> RawAssemblyResult:
    ...
```

## 12.3 Assembly rules

```text
MUST set schema_version to current supported G-CAD schema version.
MUST set trust_level to reference_geometry.
MUST set constraints.require_closed_solid = true.
MUST set constraints.require_step_file = true.
MUST set constraints.require_metadata_sidecar = true.
MUST set safety.not_for_manufacturing = true.
MUST set safety.not_certified = true.
MUST set safety.no_structural_validation = true.
MUST set every selected dialect version from registry, not LLM.
MUST set op_version from OperationSpec, not LLM, or verify exact match.
MUST set outputs from OperationSpec.output_types.
MUST wire simple linear solid chain automatically.
MUST validate that every component.owner_dialect matches selected dialect.
MUST validate node params against OperationSpec.params_model before RawGcadDocument parse.
```

## 12.4 Linear wiring policy

For a component with single solid-producing chain:

```text
First base_solid op:
  inputs = []

Each subsequent solid->solid op:
  input = previous solid output

Root node:
  last solid-producing node
```

Do not auto-wire complex branching or cross-component composition unless clear.

## 12.5 Composition policy

```text
Non-composition dialects MUST NOT directly consume internal outputs from other dialects.
Cross-component operations MUST go through composition dialect.
Composition component id SHOULD be "__assembly__".
```

## 12.6 Tests

```text
test_raw_assembler_fills_safety_flags
test_raw_assembler_fills_constraints
test_raw_assembler_uses_registry_versions
test_raw_assembler_uses_operation_spec_outputs
test_raw_assembler_wires_linear_solid_chain
test_raw_assembler_rejects_unselected_dialect
test_raw_assembler_rejects_param_model_error
test_raw_assembler_sets_reference_geometry_trust_level
```

---

# 13. Failure Taxonomy

新增：

```text
authoring/failure_taxonomy.py
```

## 13.1 Failure codes

```python
class AuthoringFailureCode(str, Enum):
    PROVIDER_NO_TOOL_CALL = "provider_no_tool_call"
    PROVIDER_INVALID_JSON = "provider_invalid_json"
    PROVIDER_SCHEMA_REJECTED = "provider_schema_rejected"
    LOCAL_SCHEMA_ERROR = "local_schema_error"

    UNKNOWN_DIALECT = "unknown_dialect"
    UNKNOWN_OP = "unknown_op"
    WRONG_OP_VERSION = "wrong_op_version"
    PARAMS_MISSING = "params_missing"
    PARAMS_EXTRA = "params_extra"
    PARAMS_TYPE_ERROR = "params_type_error"

    GRAPH_REFERENCE_ERROR = "graph_reference_error"
    GRAPH_CYCLE = "graph_cycle"
    TYPE_MISMATCH = "type_mismatch"
    PHASE_ORDER_ERROR = "phase_order_error"
    OWNERSHIP_ERROR = "ownership_error"
    COMPOSITION_BOUNDARY_ERROR = "composition_boundary_error"

    SAFETY_MISSING = "safety_missing"
    SAFETY_DISABLED = "safety_disabled"
    CONSTRAINT_RELAXED = "constraint_relaxed"

    DIALECT_SEMANTIC_ERROR = "dialect_semantic_error"
    GEOMETRY_PREFLIGHT_ERROR = "geometry_preflight_error"
    RUNTIME_GEOMETRY_ERROR = "runtime_geometry_error"

    METADATA_ERROR = "metadata_error"
    STEP_INSPECTION_ERROR = "step_inspection_error"
```

## 13.2 Error object

```python
class AuthoringFailure(BaseModel):
    code: AuthoringFailureCode
    stage: str
    message: str
    path: str | None = None
    node_id: str | None = None
    dialect: str | None = None
    op: str | None = None
    retryable: bool
    repairable: bool
```

## 13.3 Metrics

新增：

```text
authoring/metrics.py
```

```python
class AuthoringRunMetrics(BaseModel):
    model_router: str
    model_author: str
    model_repair: str | None
    route_success: bool
    feature_sequence_success: bool
    params_success_rate: float
    raw_assembly_success: bool
    parse_success: bool
    canonicalize_success: bool
    validation_success: bool
    runtime_success: bool | None
    repair_attempts: int
    final_failure_code: str | None
```

## 13.4 Tests

```text
test_failure_taxonomy_maps_pydantic_extra_to_params_extra
test_failure_taxonomy_maps_unknown_op
test_failure_taxonomy_marks_safety_disabled_non_repairable_by_llm
test_metrics_serializes_to_json
```

---

# 14. Repair Patch Loop

规划文档要求 Repair loop 只能局部 patch，不能重写整个 graph，不能修改 safety，不能放宽 validation contract，不能发明 base/op，必须记录 graph hash、error signature、repair patch hash，重复 graph / 重复 error / stage 不前进都要停止。

## 14.1 新增 `repair/patch_schema.py`

```python
class RepairOperation(str, Enum):
    REPLACE = "replace"
    ADD = "add"
    REMOVE = "remove"


class RepairChange(BaseModel):
    op: RepairOperation
    path: str
    old_value: Any | None = None
    new_value: Any | None = None
    reason: str


class RepairPatch(BaseModel):
    target_node_id: str | None = None
    changes: list[RepairChange]
    reason_summary: str
```

## 14.2 Allowed paths

```python
ALLOWED_REPAIR_PATH_PATTERNS = [
    r"^/nodes/\d+/params(/.*)?$",
    r"^/nodes/\d+/inputs(/.*)?$",
    r"^/nodes/\d+/outputs(/.*)?$",
    r"^/nodes/\d+/phase$",
    r"^/components/\d+/root_node$",
    r"^/constraints/expected_bbox_mm$",
    r"^/constraints/bbox_tolerance_mm$",
]
```

## 14.3 Forbidden paths

```python
FORBIDDEN_REPAIR_PATH_PATTERNS = [
    r"^/schema_version$",
    r"^/trust_level$",
    r"^/selected_dialects",
    r"^/safety",
    r"^/nodes/\d+/dialect$",
    r"^/nodes/\d+/op$",
    r"^/nodes/\d+/op_version$",
    r"^/components/\d+/owner_dialect$",
    r"^/constraints/require_closed_solid$",
    r"^/constraints/require_step_file$",
    r"^/constraints/require_metadata_sidecar$",
]
```

## 14.4 Repair governor

新增：

```text
repair/governor.py
```

```python
class RepairSessionState(BaseModel):
    attempt: int = 0
    max_attempts: int = 3
    seen_graph_hashes: set[str] = Field(default_factory=set)
    seen_error_signatures: set[str] = Field(default_factory=set)
    last_stage_reached: str | None = None
    applied_patch_hashes: list[str] = Field(default_factory=list)
    stopped_reason: str | None = None


def should_stop_repair(
    *,
    state: RepairSessionState,
    current_graph_hash: str,
    current_error_signature: str,
    current_stage_reached: str,
) -> tuple[bool, str | None]:
    ...
```

Stop conditions:

```text
MUST stop if attempts >= max_attempts.
MUST stop if graph hash repeated.
MUST stop if error signature repeated.
MUST stop if validation stage does not advance after patch.
MUST stop if patch tries forbidden path.
MUST stop if patch introduces unknown dialect/op/version.
```

## 14.5 Repair prompt

```python
REPAIR_SYSTEM_PROMPT = """
You are a constrained G-CAD repair patch author.

You do not rewrite the full document.
You do not change schema_version, selected_dialects, safety, trust_level, dialect, op, or op_version.
You do not invent new operations or parameter names.
You only emit a local repair patch.

Allowed changes:
- node params
- node inputs
- node outputs
- node phase
- component root_node
- expected bbox / bbox tolerance only when the validation issue specifically allows it

Forbidden changes:
- safety
- selected_dialects
- dialect
- op
- op_version
- schema_version
- trust_level
- relaxing required constraints

You must emit exactly one tool call: emit_repair_patch.
"""
```

## 14.6 Tests

```text
test_repair_patch_rejects_safety_path
test_repair_patch_rejects_selected_dialects_path
test_repair_patch_rejects_op_change
test_repair_patch_allows_param_replace
test_repair_governor_stops_on_repeated_graph_hash
test_repair_governor_stops_on_repeated_error_signature
test_repair_governor_stops_on_no_stage_progress
test_repair_patch_revalidates_after_apply
```

---

# 15. Examples 与 Anti-examples

## 15.1 设计原则

少量高质量 examples + anti-examples，比大量同类 few-shot 更稳定。每个 BasePackage：

```text
MUST include at least 3 examples.
MUST include at least 3 anti-examples.
MUST cover multiple part intents.
MUST not teach one dialect as one concrete part template.
```

## 15.2 Axisymmetric examples

```text
axisymmetric:
- simple washer
- stepped hub
- flange-like reference ring with bolt circle
```

禁止只放 turbine disk 例子，否则模型会把 axisymmetric 学成 turbine_disk primitive。

## 15.3 Sketch extrude examples

```text
sketch_extrude:
- base plate
- clamp block
- generic ribbed bracket reference
```

## 15.4 Composition examples

```text
composition:
- plate + boss union
- mirrored pair of components
- circular placement of repeated component
```

## 15.5 Anti-examples

每个 package 必须包含：

```text
1. invented op
2. concrete part primitive op
3. direct CadQuery code
4. safety disabled
5. cross-dialect direct internal reference
```

Example anti-example:

```json
{
  "anti_example_id": "axisymmetric_make_flange_bad",
  "title": "Concrete part primitive op is forbidden",
  "bad_output": {
    "nodes": [
      {
        "dialect": "axisymmetric",
        "op": "make_flange",
        "params": {
          "outer_dia_mm": 120
        }
      }
    ]
  },
  "reason": "make_flange is a concrete part primitive. Axisymmetric dialect must use generic grammar operations such as revolve_profile and cut_circular_hole_pattern.",
  "expected_validator_error": "unknown_op"
}
```

---

# 16. Dialect Governance

新增：

```text
dialects/governance.py
```

## 16.1 Forbidden tokens

```python
FORBIDDEN_PART_TOKENS = {
    "bracket",
    "flange",
    "turbine_disk",
    "gearbox",
    "bearing_seat",
    "mounting_plate",
    "shaft_with_keyway",
    "impeller",
    "pump_housing",
}

FORBIDDEN_OP_PREFIXES = {
    "make_",
    "build_part_",
    "generate_part_",
    "create_standard_",
}
```

## 16.2 Validator

```python
def validate_dialect_governance(dialect) -> list[GovernanceIssue]:
    ...
```

Rules:

```text
MUST reject dialect_id containing concrete part token.
MUST reject op names with forbidden concrete-part prefix.
MUST reject op names containing concrete part token unless explicitly allowlisted as generic geometry term.
MUST allow typical_parts in BasePackage manifest.
MUST allow examples to mention part intents.
MUST not allow concrete part naming in Dialect ABI.
```

## 16.3 Tests

```text
test_governance_rejects_part_named_dialect
test_governance_rejects_make_flange_op
test_governance_allows_flange_in_typical_parts
test_governance_allows_revolve_profile
```

---

# 17. End-to-End Authoring Pipeline

新增：

```text
authoring/pipeline.py
```

## 17.1 API

```python
class AuthoringPipelineResult(BaseModel):
    route_plan: RoutePlan
    feature_sequence: FeatureSequenceDraft | None
    node_params: dict[str, NodeParamsDraft]
    raw_assembly: RawAssemblyResult | None
    canonical_document: Any | None
    validation_bundle: Any | None
    metrics: AuthoringRunMetrics
    failures: list[AuthoringFailure]


def generate_gcad_from_user_request(
    *,
    user_request: str,
    llm_config: AuthoringLlmConfig,
    dialect_registry,
    base_package_registry,
    primitive_catalog_summary: dict | None = None,
    max_repair_attempts: int = 3,
) -> AuthoringPipelineResult:
    ...
```

## 17.2 Pipeline steps

```text
1. Build route prompt.
2. Compile route tool schema.
3. Call strict tool emit_route_plan.
4. Validate RoutePlan locally.
5. If primitive / unsupported / needs_clarification, stop cleanly.
6. Build authoring context for selected dialects only.
7. Compile feature sequence tool schema.
8. Call strict tool emit_feature_sequence.
9. Validate FeatureSequenceDraft locally.
10. For each node:
    a. compile op-specific params schema
    b. call strict tool emit_node_params
    c. validate params with OperationSpec.params_model
11. Assemble RawGcadDocument system-side.
12. Parse RawGcadDocument.
13. validate_and_canonicalize.
14. If validation fails and repairable:
    a. build repair prompt
    b. call emit_repair_patch
    c. apply patch
    d. revalidate
15. Return result with metrics.
```

## 17.3 Fallback policy

```text
If strict tool calling fails due provider schema rejection:
  log provider_schema_rejected
  do not silently switch to JSON Output unless config explicitly allows fallback.

If JSON Output fallback is enabled:
  still run local JSON parse and validator.
  mark metrics.used_json_output_fallback = true.
```

---

# 18. Metadata Additions

Generative metadata must include authoring provenance.

Add:

```json
{
  "authoring": {
    "route_model": "deepseek-v4-flash",
    "author_model": "deepseek-v4-pro",
    "repair_model": "deepseek-v4-pro",
    "strict_tools": true,
    "json_output_fallback_used": false,
    "selected_base_packages": [
      {
        "package_id": "axisymmetric",
        "dialect_id": "axisymmetric",
        "contract_hash": "...",
        "level2_usage_skill_hash": "..."
      }
    ],
    "tool_schema_hashes": {
      "route": "...",
      "feature_sequence": "...",
      "node_params:n_body": "..."
    },
    "context_hash": "...",
    "assumptions": [],
    "repair_attempts": 0,
    "failure_taxonomy": []
  }
}
```

Tests:

```text
test_metadata_contains_authoring_models
test_metadata_contains_base_package_hashes
test_metadata_contains_tool_schema_hashes
test_metadata_contains_repair_attempts
```

---

# 19. Evaluation Harness

新增：

```text
tests/fixtures/generative_cad/authoring/
```

## 19.1 Fixture format

```json
{
  "fixture_id": "axisymmetric_washer_001",
  "user_request": "Create a simple reference washer with outer diameter 80 mm, bore diameter 30 mm, thickness 8 mm.",
  "expected_route": "generative_cad_ir",
  "expected_dialects": ["axisymmetric"],
  "expected_ops": [
    "revolve_profile",
    "cut_center_bore"
  ],
  "must_not_include_ops": [
    "make_washer",
    "make_flange"
  ],
  "expected_validation": {
    "parse_success": true,
    "canonicalize_success": true
  }
}
```

## 19.2 Metrics

Track:

```text
route_accuracy
selected_dialect_accuracy
unknown_op_rate
params_extra_rate
params_missing_rate
phase_error_rate
graph_reference_error_rate
canonicalize_success_rate
repair_success_rate
runtime_success_rate
```

## 19.3 Tests

```text
test_authoring_fixtures_route_correctly
test_authoring_fixtures_do_not_generate_forbidden_ops
test_authoring_fixtures_validate_after_assembly
test_authoring_failure_metrics_are_recorded
```

Do not require live DeepSeek API in normal CI. Use mocked LLM responses.

Add optional integration tests:

```text
RUN_DEEPSEEK_AUTHORING_INTEGRATION=1
```

---

# 20. Claude Code 实施顺序

请按以下顺序执行，不要一次性大爆炸重构。

## Commit 1：LLM Provider 与模型配置

Files:

```text
generative_cad/llm/models.py
generative_cad/llm/provider.py
generative_cad/llm/deepseek_client.py
generative_cad/llm/errors.py
```

Tests:

```text
test_deepseek_tool_client_requires_one_tool_call
test_deepseek_tool_client_rejects_invalid_json_arguments
```

## Commit 2：DeepSeek Strict Schema Compiler

Files:

```text
generative_cad/authoring/strict_schema.py
```

Tests:

```text
test_deepseek_schema_all_objects_additional_properties_false
test_deepseek_schema_all_object_properties_required
test_optional_fields_become_nullable_anyof
```

## Commit 3：Authoring schemas

Files:

```text
generative_cad/authoring/schemas.py
```

Tests:

```text
test_route_plan_requires_selected_dialects_for_generative
test_feature_sequence_contains_no_params
test_node_params_validates_basic_shape
```

## Commit 4：BasePackage registry 与 Level-2 Skill generator

Files:

```text
generative_cad/base_packages/models.py
generative_cad/base_packages/registry.py
generative_cad/skills/level2_usage.py
```

Tests:

```text
test_base_package_registry
test_level2_usage_generated_from_operation_specs
test_level2_usage_contains_no_runner_source
```

## Commit 5：Tool schema compiler

Files:

```text
generative_cad/skills/tool_schema_compiler.py
```

Tests:

```text
test_route_tool_schema_contains_no_params
test_feature_sequence_schema_restricts_ops
test_node_params_schema_single_op_only
```

## Commit 6：Context builder

Files:

```text
generative_cad/authoring/context_builder.py
```

Tests:

```text
test_context_builder_only_selected_dialects
test_context_builder_rejects_contract_hash_mismatch
```

## Commit 7：Raw assembler

Files:

```text
generative_cad/authoring/raw_assembler.py
```

Tests:

```text
test_raw_assembler_fills_safety
test_raw_assembler_wires_linear_chain
test_raw_assembler_uses_operation_spec_versions
```

## Commit 8：Failure taxonomy + metrics

Files:

```text
generative_cad/authoring/failure_taxonomy.py
generative_cad/authoring/metrics.py
```

Tests:

```text
test_failure_taxonomy_basic_mapping
test_metrics_serialization
```

## Commit 9：Repair loop

Files:

```text
generative_cad/repair/patch_schema.py
generative_cad/repair/governor.py
generative_cad/repair/apply_patch.py
generative_cad/repair/signatures.py
```

Tests:

```text
test_repair_forbidden_paths
test_repair_allowed_param_patch
test_repair_stop_conditions
```

## Commit 10：End-to-end authoring pipeline

Files:

```text
generative_cad/authoring/pipeline.py
```

Tests:

```text
test_pipeline_with_mock_llm_success
test_pipeline_with_mock_llm_validation_failure_repair_success
test_pipeline_with_mock_llm_unknown_op_fails_closed
```

## Commit 11：Metadata provenance

Files:

```text
pipeline/metadata.py 或 existing metadata module
builder integration if needed
```

Tests:

```text
test_metadata_authoring_provenance
```

## Commit 12：Evaluation fixtures

Files:

```text
tests/fixtures/generative_cad/authoring/*.json
tests/generative_cad/test_authoring_fixtures.py
```

---

# 21. 给 Claude Code 的总提示词

下面这段可以直接作为 Claude Code 的主提示词。

```text
You are modifying SeekFlow generative_cad to reduce LLM hallucination during G-CAD IR generation.

The goal is NOT to create a new primitive system. The deterministic primitive path already exists and must not be modified.

Core principles:
1. LLM is a constrained CAD Grammar author, not a CAD programmer.
2. Dialect Compiler remains the source of truth for operation contracts, params, types, phases, and semantics.
3. BasePackage is LLM-facing guidance, not a runtime executor.
4. Level-2 Skill must be generated from Dialect Contract / OperationSpec / params_model, not hand-maintained as duplicated schema text.
5. The system must load only selected dialects for Level-2 authoring.
6. The system must fill fixed RawGcadDocument fields such as schema_version, trust_level, safety, constraints, dialect versions, op_versions, outputs, and simple linear graph wiring.
7. LLM should output smaller staged objects: RoutePlan, FeatureSequenceDraft, NodeParamsDraft. RawGcadDocument should be assembled by system code.
8. All LLM outputs must go through strict tool schema and local validation. Provider schema enforcement is not trusted as the final boundary.
9. JSON Output is only a fallback and must still pass local validation.
10. Repair must be local patch only. Never regenerate the whole graph during repair.
11. Repair must not modify safety, selected_dialects, schema_version, trust_level, dialect, op, or op_version.
12. Unknown dialect/op/version must fail closed. No fuzzy matching. No silent fallback.
13. Generative output trust_level must not exceed reference_geometry.
14. Output remains canonical STEP + generative metadata, not primitive.

Do not modify:
- cadquery_backend/primitive_compiler.py
- geometry_primitives/
- primitive registries
- CADPartSpec semantics

Implement in small commits:
1. LLM provider abstraction and DeepSeek strict tool client.
2. DeepSeek-compatible strict schema compiler.
3. Authoring schemas: RoutePlan, FeatureSequenceDraft, NodeParamsDraft.
4. BasePackage registry and generated Level-2 Usage Skill.
5. Tool schema compiler for route, feature sequence, and node params.
6. Context builder that loads only selected dialects.
7. System-side RawGcadDocument assembler.
8. Failure taxonomy and metrics.
9. Local repair patch loop with forbidden path governance.
10. End-to-end authoring pipeline with mocked tests.
11. Metadata provenance.
12. Evaluation fixtures.

Prioritize tests. Every fail-closed behavior must have a test.
```

---

# 22. 验收清单

最终必须满足：

```text
[ ] Primitive path tests unchanged.
[ ] LLM provider returns exactly one strict tool call.
[ ] DeepSeek strict schemas set additionalProperties=false on all objects.
[ ] DeepSeek strict schemas mark all object properties required.
[ ] RoutePlan never contains params.
[ ] FeatureSequenceDraft never contains params.
[ ] NodeParamsDraft validates against exactly one OperationSpec.params_model.
[ ] Level-2 context includes only selected dialects.
[ ] Level-2 Skill generated from contract / OperationSpec.
[ ] No hand-coded OP_DESCRIPTIONS remain in orchestrator.
[ ] Raw assembler fills safety and constraints.
[ ] Raw assembler sets trust_level=reference_geometry.
[ ] Raw assembler uses registry dialect versions and OperationSpec op_versions.
[ ] Unknown dialect fails closed.
[ ] Unknown op fails closed.
[ ] Extra params fail closed.
[ ] Missing params fail closed.
[ ] Phase errors fail closed.
[ ] Type mismatch fails closed.
[ ] Cross-dialect internal reference fails closed.
[ ] Repair cannot modify safety.
[ ] Repair cannot modify selected_dialects.
[ ] Repair cannot modify op/op_version.
[ ] Repair stops on repeated graph hash.
[ ] Repair stops on repeated error signature.
[ ] Metadata records model, tool schema hash, Level-2 skill hash, BasePackage hash.
[ ] Evaluation fixtures record route accuracy, unknown_op_rate, validation success.
```

---

# 23. 最终实施判断

最稳定的实现路线不是：

```text
换 V4 Pro，然后写一个更长 prompt。
```

而是：

```text
DeepSeek V4 Pro for authoring / repair
  + strict tool calling
  + DeepSeek-compatible schema compiler
  + selected dialect context
  + generated Level-2 Skill
  + system-side RawGcad assembly
  + local Dialect Compiler validation
  + local patch repair
  + failure taxonomy and fixtures
```

这样才能保留 Dialect Compiler 的泛化优势，同时把 LLM 幻觉限制在可检测、可修复、可度量的范围内。

[1]: https://api-docs.deepseek.com/guides/tool_calls "Tool Calls | DeepSeek API Docs"
[2]: https://api-docs.deepseek.com/guides/json_mode "JSON Output | DeepSeek API Docs"
[3]: https://developers.openai.com/api/docs/guides/structured-outputs "Structured model outputs | OpenAI API"
