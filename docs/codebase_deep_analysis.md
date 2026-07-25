# SeekFlow Text-to-CAD + Auto-FEA 系统深度架构分析

> **分析日期**: 2026-07-24
> **分析范围**: 完整代码仓库 e:\text_to_cad_improve (355+ Python 文件, ~22,600 行 generative_cad)
> **当前版本**: main @ 678c073 (V3 topology 在 text2cad/v3-phase17-saved @ 81f693d)
> **分析模式**: 极致源码理解 — 先吃透设计，再识别边界

---

## 目录

1. [系统全景](#1-系统全景)
2. [Text-to-CAD 完整管线](#2-text-to-cad-完整管线-10-阶段)
3. [架构层次](#3-架构层次)
4. [IR 中间表示层](#4-ir-中间表示层)
5. [验证内核 (Validation Kernel)](#5-验证内核-validation-kernel)
6. [方言系统 (Dialect System)](#6-方言系统-dialect-system)
7. [运行时与类型化 Handle 系统](#7-运行时与类型化-handle-系统)
8. [V3 持久拓扑命名系统](#8-v3-持久拓扑命名系统)
9. [Auto-FEA 3D 有限元管线](#9-auto-fea-3d-有限元管线)
10. [修复回路 (Repair Loop)](#10-修复回路-repair-loop)
11. [设计哲学](#11-设计哲学)
12. [当前已知问题与架构边界](#12-当前已知问题与架构边界)
13. [关键文件速查表](#13-关键文件速查表)

---

## 1. 系统全景

### 1.1 项目身份

SeekFlow v0.3.7 — "DeepSeek-native zero-trust tool gateway"。核心使命：安全运行 LLM Agent 的生产级工具网关。Text-to-CAD 是其主要子系统，完整实现从自然语言到 ISO 10303-21 STEP 文件的全自动管线。

### 1.2 总体数据流

```
用户自然语言需求
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  Stage 0 (v6 可选): Spatial Frontend                              │
│  ── LLM 提取 MechanicalObjectGraphDraft → 原型匹配 → 约束图     │
│  ── solver 检查一致性 → 多轮问答澄清                            │
│  ── 输出 spatial_contract.json                                   │
├──────────────────────────────────────────────────────────────────┤
│  Stage 1-5: 创作层 (Authoring)                                    │
│  ── Route (LLM): 选 Deterministic / GenerativeCAD / Unsupported  │
│  ── Context Build (规则): 加载方言合约 + BasePackage skills      │
│  ── Feature Sequence (LLM): 规划操作节点 DAG                     │
│  ── Node Params (LLM, 逐节点): 填写操作参数                      │
│  ── Raw Assembly (规则): 组装 RawGcadDocument                    │
├──────────────────────────────────────────────────────────────────┤
│  Stage 6: Validation Kernel (验证内核, 规则)                       │
│  ── 14 stages, barrier 分组, Core + Extension 双层               │
│  ── parse → canonicalize → 完整验证报告                           │
├──────────────────────────────────────────────────────────────────┤
│  Stage 7a-7b: AutoFix + LLM Repair Loop                          │
│  ── 17+ 确定性修复规则 → QualityVector 质量门控                   │
│  ── LLM repair loop (max 3 attempts, governor 策略执行)          │
├──────────────────────────────────────────────────────────────────┤
│  Stage 8: Compiler Middle-End (v6.3)                              │
│  ── Fact Propagation Pass + Planner Pass                          │
│  ── 输出 planning_report, compiler_diagnostics                    │
├──────────────────────────────────────────────────────────────────┤
│  Stage 9: Runtime Execution (方言引擎)                             │
│  ── 拓扑排序 → 逐节点分发 handler                                 │
│  ── 约束求解 (spatial placements)                                 │
│  ── 组合 (boolean + assembly) → STEP 导出                        │
├──────────────────────────────────────────────────────────────────┤
│  Stage 10: Postcondition + Inspection                             │
│  ── geometry_postcheck: closed? valid_solid? volume?              │
│  ── step_postcheck: 文件完整性                                    │
│  ── spatial_audit: 组件干涉检查                                   │
│  ── Metadata v3: 完整审计证明                                    │
└──────────────────────────────────────────────────────────────────┘
    │ .step + .metadata.json
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  FEA 3D 管线 (fea3d/)                                             │
│  Stage 1 (prepare): gmsh 扇区网格 (tet10/SOLID187), 免费 ~2min    │
│  Stage 2 (confirm): 人工确认 .confirmed, 必须                       │
│  Stage 3 (solve): ANSYS 18.1 批处理, 耗算力 ~1-3min              │
│  Stage 4 (post): Python 应力场后处理 + 安全系数                   │
└──────────────────────────────────────────────────────────────────┘
    │ nodal_stress_3d.csv / stress_field_3d.bin
    ▼
  可视化 / 工程决策
```

### 1.3 模块地图

```
auto_detection_process/
├── src/seekflow/                  # SeekFlow Agent 核心运行时 (43 模块)
│   ├── agent/                     # DeepSeekAgent, Crew, Graph, Memory
│   ├── tools/                     # @tool, Registry, Executor, Policy
│   ├── security/                  # safe_join, validate_url, sandbox
│   ├── mcp/                       # MCP gateway
│   └── ...
│
├── integrations/engineering_tools/src/seekflow_engineering_tools/
│   ├── generative_cad/            # ★ Text-to-CAD 引擎 (~22,600 行)
│   │   ├── ir/                    # IR: RawGcadDocument → CanonicalGcadDocument
│   │   ├── validation_kernel/     # ★ 验证内核: Registry + Executor + Models
│   │   ├── validation/            # 旧验证层 (被 kernel 包装)
│   │   ├── dialects/              # ★ 6 个方言: axisymmetric, sketch_extrude,
│   │   │                          #   sketch_profile, composition, loft_sweep, shell_housing
│   │   ├── runtime/               # RuntimeContext, ObjectStore, Handles, Resolve
│   │   ├── compiler/              # 编译器中间端 (v6.3)
│   │   ├── authoring/             # 创作层: LLM 交互 + 空间约束求解
│   │   │   └── spatial/           # 空间约束子系统 (archetypes, solver)
│   │   ├── extensions/            # 扩展系统: Hole Feature Extension
│   │   ├── analysis/              # 语义分析: Facts, Rules, Propagation
│   │   ├── pipeline/              # run.py (核心入口) + metadata_v3 + artifact
│   │   ├── bases/                 # 基础 primitive
│   │   ├── skills/                # LLM skill prompts + orchestrator
│   │   └── topology/              # ★ V3 持久拓扑命名 (仅 __pycache__, 源码在分支)
│   │
│   ├── ansys/                     # ANSYS APDL 集成
│   ├── cadquery_backend/          # CadQuery + OCCT 后端
│   ├── solidworks/                # SolidWorks 集成
│   ├── nx/                        # Siemens NX 集成
│   ├── ir/                        # 全局 IR 类型 (cad, cae, primitive)
│   ├── inspection/                # STEP 几何检查
│   ├── mechanical_validation/     # 力学验证
│   └── geometry_primitives/       # 确定性 primitive
│
├── app/text-to-cad/               # React + Vite 前端
│   └── server/fea3d/              # ★ 3D FEA 管线
│       ├── run3d.py               # 4阶段 CLI
│       ├── mesh_sector.py         # gmsh 网格生成
│       ├── apdl_template_3d.py    # ANSYS APDL 模板
│       └── post3d.py              # 后处理
│
├── tests/                         # 核心测试 (~110 文件)
├── integrations/engineering_tools/tests/  # 工程工具测试 (~187 文件)
│   ├── generative_cad/            # ~95 生成式 CAD 测试
│   ├── topology_v3/               # ★ V3 topology 测试 (仅 __pycache__)
│   └── text_to_cad_real/          # ~10 E2E 真实测试
└── docs/                          # ~256 markdown 文档
```

---

## 2. Text-to-CAD 完整管线 (10 阶段)

### 2.1 核心入口

`builder.py:build_generative_cad_model()` → `pipeline/run.py:run_canonical_gcad()`

### 2.2 Stage 0: Spatial Frontend (v6, 可选)

多组件场景的约束前移。LLM 提取 `MechanicalObjectGraphDraft`（组件 + 空间关系），原型匹配注入默认关系，构建 `SpatialConstraintGraph`。求解器检查矛盾，必要时多轮问答澄清。输出 `spatial_contract.json` sidecar，后续在 Stage 9 用于数值放置。

### 2.3 Stage 1-5: 创作层

**Route (LLM)**: 从 3 个路径中选择: `deterministic_primitive` (模板化 primitive), `generative_cad_ir` (LLM 创作完整 IR), `unsupported` (fail-closed)。安全规则: "manufacturing-ready/certified/airworthy" 关键词强制路由到 `unsupported`。

**Feature Sequence (LLM)**: 规划操作 DAG — `node_sequence: [{node_id, dialect, op, op_version, phase}]`。

**Node Params (LLM, 逐节点)**: 为每个操作填写参数，严格一致性检查（node_id, dialect, op, op_version 必须匹配计划）。支持 `DimExpr` 引用（"hole diameter = bore diameter"）。

### 2.4 Stage 6: Validation Kernel

详见 §5。

### 2.5 Stage 7a-7b: Repair

详见 §10。

### 2.6 Stage 8: Compiler Middle-End

两个 Pass: `FactPropagationPass` (Kahn 拓扑排序, 8 条事实规则, DimExpr 求值) 和 `PlannerPass` (模式计数, 破坏性 op 阈值检查)。输出 diagnostics 和 planning_report，注入 metadata 和 repair prompt。

### 2.7 Stage 9: Runtime Execution

```python
_run_components(canonical, ctx)
    ├── 对每个 Component (非 __assembly__):
    │   ├── 单方言: dialect.run_component()
    │   └── 混合方言: 拓扑排序 → execute_operation() per node
    ├── Constraint Resolution (spatial placements)
    └── _run_composition_or_select_final()
```

### 2.8 Stage 10: Postcondition + Inspection

```python
# 运行时后置条件
validate_runtime_postconditions(canonical, ctx, final_handle_id)
# 几何有效性 (closed, valid_solid, volume)
validate_final_geometry(ctx, final_handle_id, expected_body_count)
# STEP 文件完整性
validate_step_post_export(out_step, min_size_bytes=200)
# 空间审计 (组件干涉/距离)
run_geometry_spatial_audit(final_handle_id, ctx, spatial_graph, placements)
```

---

## 3. 架构层次

系统采用 **7 层架构**:

```
Layer 0: LLM Skills & Orchestrator  ── skills/orchestrator.py, prompts.py
Layer 1: Authoring Pipeline          ── authoring/* (LLM 交互 + 空间求解)
Layer 2: Validation Pipeline         ── validation_kernel/* (Core + Extensions)
Layer 3: IR System                   ── ir/* (RawGcadDocument → CanonicalGcadDocument)
Layer 4: Dialect Registry            ── dialects/* (6 frozen dialects, governance)
Layer 5: Runtime Execution           ── runtime/* (Context, Store, Handles, Resolve)
Layer 6: Pipeline Orchestration      ── pipeline/* (run, metadata_v3, artifact)
```

### 核心设计模式

**Frozen Registry**: 方言注册表和验证规则注册表均在启动时冻结。`freeze()` 后任何 `register()` 调用抛出 `RuntimeError` — 核安全级编程模式，防止 LLM 或插件注入。

**Protocol vs ABC**: 方言使用 `Protocol`（结构化类型）而非 `ABC`（名义类型），支持 mock 替换和第三方扩展。

**Constraint-Deferred Solving (v6)**: 两阶段求解 — Phase A (符号, 创作时) 产生约束图；Phase C (数值, 运行时) 利用真实 bbox 求解精确放置位置。

---

## 4. IR 中间表示层

### 4.1 双层 IR

```
RawGcadDocument (LLM 友好, 宽松, 容错)
    │  parse + validate + canonicalize
    ▼
CanonicalGcadDocument (机器友好, Pydantic strict, 携带哈希)
```

### 4.2 核心 IR 结构

```python
CanonicalGcadDocument
├── schema_version: "g_cad_core_v0.2"
├── canonical_version: "canonical_gcad_v0.2"
├── document_id, part_name, units ("mm"), trust_level
├── selected_dialects: [CanonicalSelectedDialect]  # 方言 + 版本 + 合约哈希
├── components: [CanonicalComponent]               # 每个组件的拥有方言 + 根节点
│   └── id, owner_dialect, kind_hint, root_node, output_aliases
├── nodes: [CanonicalNode]                         # 操作节点 DAG
│   ├── id, component, dialect, op, op_version, phase
│   ├── inputs: [CanonicalValueRef]   # producer_node + producer_component + output
│   ├── outputs: [CanonicalValueDecl] # name + type + value_id
│   ├── params, typed_params          # 原始参数 + 类型化参数
│   ├── required, degradation_policy  # 是否必须成功 + 失败行为
│   ├── operation_effects             # 操作副作用声明
│   ├── postconditions                # 后置条件
│   └── autofix_hints                 # 自动修复提示
├── constraints: RawConstraints       # expected_body_count, expected_bbox_mm
├── safety: RawSafety                 # 7 个安全标志 (全部必须显式 true)
├── canonical_graph_hash: str         # 确定性图哈希
└── raw_graph_hash: str | None        # 原始输入哈希
```

### 4.3 值传递

节点间通过 `CanonicalValueRef` 建立数据依赖:
```python
class CanonicalValueRef:
    producer_node: str | None       # 哪个节点生产
    producer_component: str | None  # 哪个组件 (跨组件引用)
    output: str                     # 输出名 (通常是 "body")
    resolved_type: ValueType        # solid | profile | sketch | frame | ...
```

运行时通过 `resolve_input_object(node, ctx, input_index)` 解析:
```
resolve_input_handle_id:
  1. node.inputs[index].producer_node → ctx.resolve_node_output(pid, output) → handle_id
  2. node.inputs[index].producer_component → ctx.resolve_component_output(cid, output) → handle_id

resolve_input_object:
  handle_id → ctx.object_store.get(hid) → 实际 CadQuery 对象
```

---

## 5. 验证内核 (Validation Kernel)

### 5.1 架构动机

v6.3 之前的验证系统存在以下问题:
- 规则散落在多个文件中, 没有统一注册/发现机制
- 无扩展机制: 新增零件类型验证规则需要修改核心代码
- 规则间依赖不明确, 调试困难

### 5.2 当前架构

```
RuleRegistry (启动时冻结)
├── Core Rules (layer=core, selector.always=True)
│   └── 14 stages: structure → root_terminal → registry → params →
│       ownership → graph → typecheck → phase → composition →
│       hole_semantics → safety → canonicalize →
│       dialect_semantics → geometry_preflight
│
├── Extension Rules (layer=extension, selector 按条件匹配)
│   └── 仅当 ActivationSnapshot 匹配时激活
│
└── 启动期治理: freeze() 时检查依赖/冲突/DAG 环
```

### 5.3 Barrier 语义

```
RAW_BARRIER_GROUPS = (
    (STRUCTURE,),                              # 组1: 结构解析 (独立)
    (ROOT_TERMINAL, REGISTRY, PARAMS,          # 组2: 聚合执行全部规则
     OWNERSHIP, GRAPH, TYPECHECK, PHASE,
     COMPOSITION, HOLE_SEMANTICS, SAFETY),
)
```

组内全部规则运行并聚合 Issue (一次发现全部问题), 组间 barrier — 前组失败则后组全部 `status="skipped"`。

### 5.4 扩展系统

**不可妥协原则**:
1. Kernel 不 import 具体 dialect/feature 模块
2. Kernel 不识别具体操作名 (如 `cut_hole`)
3. Extension 只能新增规则, 不能屏蔽 Core 规则
4. 新增扩展只改 `extensions/` 包, 不改 Kernel

**激活机制**:
```python
ActivationSnapshot 从文档元数据解析:
    dialects     → selected_dialects
    operations   → 所有 node.op
    feature_tags → compiler middle-end 特征识别
    part_families → part_intent/route_plan

RuleSelector.matches(activation):
    always=True → 永远激活 (Core)
    否则 → dialects/operations/feature_tags/part_families 任意交集非空 → 激活
```

**Hole Feature Extension** (首个真实扩展):
```python
MANIFEST = ExtensionManifest(
    extension_id="feature.hole",
    selectors=[RuleSelector(operations={"cut_hole", "cut_hole_v2", ...})],
)
# 仅在文档含孔类操作时激活
```

---

## 6. 方言系统 (Dialect System)

### 6.1 6 个已注册方言

| 方言 ID | 用途 | 操作数 | 关键操作 |
|---------|------|--------|---------|
| `axisymmetric` | 轴对称回转体 | 8 | revolve_profile, cut_rim_slot_pattern, cut_center_bore |
| `sketch_extrude` | 矩形拉伸/切削 | 11 | extrude_rectangle, cut_hole, cut_hole_v2, fillet, chamfer |
| `sketch_profile` | 2D 草图+拉伸/旋转 | 9 | create_2d_sketch, extrude_profile, revolve_profile, fillet_sketch |
| `composition` | 布尔/变换/阵列 | 7 | boolean_union, boolean_cut, translate, circular_pattern, place_component |
| `loft_sweep` | 放样/扫掠 | 4 | loft_solid, sweep_solid |
| `shell_housing` | 壳体 | 2 | shell_housing_builder |

### 6.2 Handler 执行模式

所有 handler 遵循统一模式:

```python
def handle_xxx(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    # 1. 解析输入
    body = resolve_input_object(node, ctx, 0)

    # 2. 参数提取 + 验证
    if invalid:
        if node.required: raise ValueError(...)     # HARD FAIL
        return _degrade(node, ctx, body, "op_name") # 降级

    # 3. 执行操作 (带多层 fallback)
    try: result = primary(body, params)
    except: 
        try: result = fallback(body, params)
        except: return _degrade(node, ctx, body, "op_name")

    # 4. 存储结果 → handle ID
    return {"body": _store_solid(node, ctx, result)}
```

### 6.3 布尔运算 4 层 Fallback

```
Attempt 1: CadQuery a.union(b) → 检查实体数是否减少
Attempt 2: OCCT BRepAlgoAPI_Fuse → a.fuse(b)
Attempt 3: fuzzy fuse at 3 tolerance levels (1x, 5x, 10x)
Attempt 4: shape healing + fuzzy fuse at 10x
全部失败: HARD FAIL (不再静默丢弃 solid B)
```

---

## 7. 运行时与类型化 Handle 系统

### 7.1 RuntimeContext — 状态中枢

```python
@dataclass
class RuntimeContext:
    # 文件路径
    out_step, metadata_path, workspace_root: Path

    # 对象存储 (handle_id → CadQuery 对象)
    object_store: RuntimeObjectStore

    # 输出绑定 (node_id → {output_name: handle_id})
    node_outputs: dict
    component_outputs: dict

    # 组件级可变状态 (workplane, last_point)
    component_state: dict[str, dict[str, object]]

    # 诊断收集
    warnings, degraded_features, operation_metrics: list
    geometry_health_log: dict[str, dict]

    # 空间求解 (v6)
    spatial_placements, placed_component_bboxes: dict

    # 编译器诊断 (v6.3)
    compiler_diagnostics: list[dict]
    planning_report: dict | None
```

### 7.2 Handle 系统

跨方言数据交换完全通过类型化 Handle:

```python
SolidHandle(id="solid:comp1:node5:body", component_id="comp1", producer_node="node5")
EdgeHandle(id="edge:...", parent_solid_id="...", edge_index=3)
FaceHandle(id="face:...", parent_solid_id="...", face_index=0)
ProfileHandle(id="profile:comp1:node2:profile")
FrameHandle, PlaneHandle, PointHandle, CurveHandle, SolidArrayHandle
```

Handle ID 格式: `{type}:{component}:{node_id}:{output_name}` — 全局唯一, 可追溯。

### 7.3 RuntimeObjectStore

双 dict 存储: `_handles[handle_id] → RuntimeHandle`, `_objects[handle_id] → 实际对象`。强制唯一性 (重复插入抛 ValueError), 无弱引用 (管线结束时随 Context GC 回收)。

---

## 8. V3 持久拓扑命名系统

> **重要**: V3 topology 模块的 `.py` 源文件在当前 main 分支 (678c073) 上不存在，仅保留 `__pycache__/*.pyc` 编译字节码。完整源代码在 `text2cad/v3-phase17-saved` 分支 @ `81f693d`。

### 8.1 三层架构

```
Layer 1: 确定性语义命名 (Semantic Naming)
    └── 基于几何参数 + 特征上下文 → V3 descriptor
    └── name_extrude_faces(), name_revolve_faces(), name_boolean_faces()

Layer 2: OCCT 内核历史 (Kernel History)
    └── BRepTools_History: Generated() / Modified() / IsDeleted()
    └── history_aware_extrude(), history_aware_revolve()

Layer 3: 约束指纹匹配 (Constrained Fingerprint)
    └── FaceFingerprint, EdgeFingerprint
    └── ConstrainedTopologyMatcher, MatchWeights
```

### 8.2 核心数据结构 (已从 .pyc 反编译重建)

**TopologyIdentityDescriptorV3** — 规范身份模型:

```python
class TopologyIdentityDescriptorV3(BaseModel):
    scheme: Literal["gcad_topo_v3"]
    document_lineage_id: str      # 稳定 lineage ID (来自 DesignIdentity)
    component_stable_id: str      # 稳定组件 ID
    feature_stable_id: str        # 稳定特征 ID (取代可变 producer_node_id)
    entity_type: Literal["solid","shell","face","wire","edge","vertex"]
    semantic_path: tuple[str, ...] # 多 token 语义路径 ("revolved","lateral","0")
    source_entity_keys: list[str]  # 源实体 key
    branch_key: str | None
    algorithm_version: str = "3.0.0"

    def to_key(self) -> str:
        # → "gct3_<base64url sha256>"  — 内容寻址, 确定性
```

**IdentityTransferPolicy** — 8 维决策引擎:
```
OCCT 观察 (Generated/Modified/Deleted) → 8 维度评估:
    geometric_deviation, topology_change, area_change,
    boundary_similarity, position_in_indexed_map,
    adjacency_preservation, surface_type_match, generation_context
→ IdentityDecision: SAME | MODIFIED | NEW | DELETED | AMBIGUOUS
→ ProofClass: GEOMETRIC | TOPOLOGIC | HEURISTIC | OCCT_HISTORY | FALLBACK
```

**TopologyTransaction** — 原子事务:
```python
class TopologyTransaction:
    staged: TopologyRegistry  # 工作副本 (clone)
    def commit(self):         # 原子提交
        # 完整性检查 → _replace_from(staged) → 失败则 rollback
```

### 8.3 Phase 15-17 状态

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| feature_stable_id 正确率 | 0% | 100% |
| Generation 最大值 | 62 (膨胀) | ≤4 |
| Lineage DAG | 未建立 | 3015 ancestors |
| Extrude locators | 0/52 | 50/52 |
| 回归测试 | — | 189 passed, 9 baseline FAIL |
| 涡轮盘实体 | — | 3079 entities, 4 transactions |

---

## 9. Auto-FEA 3D 有限元管线

### 9.1 4 阶段流水线

```
CAD STEP 模型
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│ Stage 1: prepare — gmsh 网格生成 (免费, ~2min)                     │
│ mesh_sector.py                                                    │
│ ├── 导入整盘 STEP (~15MB, 1-2min)                                 │
│ ├── 扇区切割: 圆柱 Boolean 交 (6° x z_half)                       │
│ ├── 边界面确定性分类: low / high / sym (基于法向+质心)             │
│ ├── 周期配对: setPeriodic (旋转仿射变换, 容差<0.5mm)              │
│ ├── tet10 网格 (gmsh type 11)                                     │
│ ├── 雅可比质量断言: minSICN > 0 (免费阶段拦截坏单元)               │
│ ├── 节点重映射: gmsh tet10 → ANSYS SOLID187 (交换最后两中节点)    │
│ └── 输出: mesh.inp + mesh_report.json                             │
├──────────────────────────────────────────────────────────────────┤
│ Stage 2: confirm — 人工确认 (必须, 算力保护)                        │
│ ├── 审阅 mesh_report.json (节点数, 边界面, 配对距离)               │
│ ├── 确认 几何/载荷/材料 参数                                      │
│ └── 写入 .confirmed (含 config hash, 防误运行)                     │
├──────────────────────────────────────────────────────────────────┤
│ Stage 3: solve — ANSYS 批处理 (耗算力, ~1-3min)                   │
│ apdl_template_3d.py → solve.inp                                    │
│ ├── SOLID187 二阶四面体                                           │
│ ├── GH4169 温度相关材料 (4点 MPTEMP: EX, ALPX vs T)               │
│ ├── 循环对称: CPCYC 自动配对 (容差 0.05mm)                        │
│ ├── z=0 对称面: UZ=0 (消除轴向刚体平动)                            │
│ ├── 孔壁单节点 UY=0 (消除绕轴刚体转动)                             │
│ ├── 径向分带温度场: T(r) = TB+(TR-TB)*((r-RB)/(RO-RB))^TEXP (80带)│
│ ├── 离心载荷: OMEGA 绕 Z 轴                                       │
│ └── 输出: nodal_stress_3d.csv (SX径向,SY环向,SZ轴向,SEQV,S1,S3)   │
├──────────────────────────────────────────────────────────────────┤
│ Stage 4: post — Python 后处理 (免费)                                │
│ post3d.py                                                          │
│ ├── 解析 CSV → 有效节点 (sel=1)                                    │
│ ├── 温度重建 + 屈服强度插值 + 安全系数 (SF = yield/VM)            │
│ ├── 分区指标: bore/hub/web/rim                                     │
│ ├── 量级自查: max VM ∈ [300, 1500] MPa                             │
│ ├── stress_field_3d.bin: 全场应力点云 (8×f32/节点)                 │
│ └── sector_surface.json: 表面三角面 + 每顶点应力                    │
└──────────────────────────────────────────────────────────────────┘
```

### 9.2 人工确认机制 (算力保护)

- `prepare` 免费自动
- `confirm` 必须人工介入
- `.confirmed` 包含 config hash, 配置变更后必须重新确认
- `solve` 消耗算力, 需先通过 confirm gate

### 9.3 与 2D FEA 的对比

现有的 `ansys/apdl_templates.py:turbine_disc_rotational_thermal` 模板是 2D 轴对称 (PLANE183)，已知 8 个缺陷:
1. KEYOPT(3)=0 (plane stress) 当 axisymmetric 用 — 环向应力恒 0
2. OMEGA 旋转轴错误 (Z 而非 Y)
3. BFUNIF 均匀温度 — 无热应力梯度
4. 单模量, 无温度相关材料
5. STEP 路径参数未使用 (几何硬编码)
6. PATH 后处理语法不兼容 ANSYS 18.1
7. n_slots/slot_depth_mm 是死参数
8. Runner 硬编码 -m 512 (三维不够)

---

## 10. 修复回路 (Repair Loop)

### 10.1 双层架构

```
Validation Loop (内层):
    Deterministic AutoFix (17+ 规则) → revalidate
    └── 失败 → LLM repair (max 3 attempts, QualityVector gated)
        └── 成功 → commit → revalidate → exit loop
        └── 失败 → next attempt or give_up

Runtime Loop (外层):
    run_canonical_gcad() → 运行时失败
    └── classify_runtime_failure → repairable?
        ├── params-only repair (numeric budget)
        ├── single accepted patch → full revalidation + rerun
        └── non-repairable → fail
```

### 10.2 提交准则 (QualityVector)

```python
q_before = QualityVector.from_report(current_report)
q_after = QualityVector.from_report(candidate_report)
# 只有严格改进才接受: 错误数减少, 无新错误, 无 regression
if is_strict_improvement(q_before, q_after):
    current_doc = candidate  # COMMIT
else:
    # candidate 丢弃 (ROLLBACK)
```

### 10.3 Governor 停止条件

- Max total attempts / max validation/runtime LLM attempts
- 相同 raw graph hash 重复 (LLM 无进展)
- 相同 error signature 重复 2 次
- 相同 patch hash 重复 (循环检测)
- Stage rank regression (验证回退到更早阶段)
- `give_up: true` from LLM

---

## 11. 设计哲学

### 11.1 核心原则

1. **Fail-Closed > Fail-Open**: 不确定时拒绝而非静默通过。所有安全标志必须显式 `true`，无默认值。

2. **类型安全贯穿**: Raw JSON → Pydantic IR → 类型化 Handle → 类型化 Object 查询。

3. **不可变注册表**: 方言注册表、验证规则注册表均在启动时冻结, 运行时不可变。

4. **确定性**: 图哈希 (canonical_graph_hash)、操作版本 (op_version)、合约哈希 (contract_hash) 确保同一输入产生同一输出。

5. **审计完整性**: Metadata v3 包含完整 validation proof、operation metrics、geometry health log、compiler diagnostics，可逐操作回溯。

6. **Kernel/Extension 分离**: 验证内核只含通用规则，特殊零件规则作为扩展加载，互不污染。

7. **Barrier 语义**: 组内聚合所有问题 (一次发现全部)，组间阻断 (前序失败则后续跳过)。

8. **防御性多层 Fallback**: 几何操作提供多级回退 (CadQuery → OCCT → fuzzy → heal) 而非单一 try/except。

9. **零信任**: "reject a valid part rather than allow an invalid one" — 核安全/航空航天安全哲学。

10. **人工确认机制 (FEA)**: 算力消耗大的操作必须人工确认，用 config hash 防误运行。

### 11.2 架构演进路径

```
v0.1-v0.3: 原型期 — 单文件脚本, 硬编码参数
v0.4-v0.6: 工业化初期 — IR 双层架构, 方言注册表, 类型化 Handle
v0.7-v6.3: 内核重构 — Validation Kernel, Extension 系统, Compiler Middle-End,
            Spatial Solver, 混合方言组件执行
vNext (V3 分支): 持久拓扑命名 — V3 Descriptor, Transaction, IdentityTransferPolicy,
            Lineage DAG, FeatureIdentityReconciler
```

---

## 12. 当前已知问题与架构边界

### 12.1 已识别问题

**1. V3 Topology 源码在主分支缺失**

`topology/` 目录仅含 `__pycache__/*.pyc`，所有 25+ 源文件在 main 分支 (678c073) 上不存在。完整源码在 `text2cad/v3-phase17-saved` 分支。需要合入策略。

**2. 验证系统与几何真实性脱节**

Core validation 验证 IR 合法性，但 `geometry_postcheck` (closed, valid_solid) 只在 builder 最后阶段检查。涡轮盘 test_v11 案例中，所有 core validation 通过但最终几何无效。

**3. 路由器能力边界不强制**

`route_plan` 可列出 `unsupported_capabilities` 但继续选择 `deterministic_primitive`。需要硬规则: 关键能力缺失时强制 `fail_closed`。

**4. Primitive 表达力不足**

- `revolve_profile` 只能 `r(z)` 单值轮廓，不能 `t(r)` 厚度随半径变化
- `cut_rim_slot_pattern` 只能简化折线槽，不能 fir-tree 榫槽

**5. 编译器中间端默认不阻断**

`FAIL_ON_MIDDLE_END_ERROR = False` — 编译器错误仅写 warnings，不阻断管线。

**6. 2D FEA 模板已知错误未修复**

`turbine_disc_rotational_thermal` 有 8 个文档化缺陷，3D 替换方案 (fea3d/) 已就位但可能需要与 CAD 管线更紧密集成。

### 12.2 架构债务

- `validation/` 旧验证层被 `validation_kernel/legacy_adapter.py` 包装，未完全迁移
- `runtime/topology.py` (167 行) 是 v1.0 简单实现，不支持跨操作面追踪
- `dialects/geometry_utils/` 中 OCCT 工具散布各处，缺乏统一几何工具层
- 修复回路的两个 orchestrator (内联 + 独立) 共享逻辑但未统一

---

## 13. 关键文件速查表

### Text-to-CAD 管线

| 文件 | 用途 | 行数 |
|------|------|------|
| `pipeline/run.py` | ★ 核心执行引擎 run_canonical_gcad() | ~660 |
| `builder.py` | 完整构建入口 (验证→执行→检查→元数据) | ~330 |
| `authoring/pipeline.py` | Stage 1-7b 创作层 | ~600+ |
| `authoring/build_pipeline.py` | 最外层指挥 generate_validate_build_step() | ~400+ |
| `authoring/auto_fixer.py` | 17+ 确定性修复规则 | ~200+ |

### 验证系统

| 文件 | 用途 | 行数 |
|------|------|------|
| `validation_kernel/stages.py` | ★ Stage 枚举 + Barrier 分组 (单一事实来源) | ~110 |
| `validation_kernel/registry.py` | RuleRegistry: 注册/选择/冻结/冲突治理 | ~140 |
| `validation_kernel/executor.py` | Barrier 语义验证执行器 | ~230 |
| `validation_kernel/models.py` | RuleManifest, ExtensionManifest, ActivationSnapshot | ~100 |
| `validation_kernel/legacy_adapter.py` | 旧 validator → RegisteredRule 包装 | ~150+ |

### 方言系统

| 文件 | 用途 | 行数 |
|------|------|------|
| `dialects/registry.py` | 方言注册表 (frozen) | ~70 |
| `dialects/base.py` | BaseDialect Protocol | ~80 |
| `dialects/default_registry.py` | 6 方言默认注册 | ~40 |
| `dialects/composition/handlers.py` | 布尔/变换/阵列处理器 | ~390 |
| `dialects/sketch_profile/handlers.py` | 2D 草图+拉伸/旋转处理器 | ~390 |
| `dialects/sketch_extrude/handlers.py` | 矩形拉伸处理器 | ~350 |
| `dialects/axisymmetric/handlers.py` | 轴对称处理器 (含 Z-overlap 检测) | ~550 |
| `dialects/geometry_utils/boolean_safe.py` | 4 层布尔 Fallback | ~150 |

### IR 与运行时

| 文件 | 用途 | 行数 |
|------|------|------|
| `ir/canonical.py` | CanonicalGcadDocument Pydantic 模型 | ~90 |
| `runtime/context.py` | RuntimeContext 状态中枢 | ~85 |
| `runtime/object_store.py` | Handle→对象映射 (双 dict) | ~65 |
| `runtime/handles.py` | 9 种类型化 Handle | ~80 |
| `runtime/resolve.py` | resolve_input_object() 依赖解析 | ~50 |
| `runtime/topology.py` | 基础 face/edge 选择器 (v1.0) | ~165 |

### FEA 3D 管线

| 文件 | 用途 | 行数 |
|------|------|------|
| `app/.../fea3d/run3d.py` | 4 阶段 CLI (prepare→confirm→solve→post) | ~270 |
| `app/.../fea3d/mesh_sector.py` | gmsh 扇区网格 (STEP→tet10) | ~240 |
| `app/.../fea3d/apdl_template_3d.py` | APDL 求解模板 (SOLID187, CPCYC) | ~215 |
| `app/.../fea3d/post3d.py` | 应力场后处理 + 安全系数 + 前端导出 | ~340 |

### V3 Topology (分支保留)

| 模块 | 用途 |
|------|------|
| `topology/ids.py` | V1/V2/V3 PersistentTopoId, 3 代演进 |
| `topology/registry.py` | TopologyRegistry: 实体注册/查询/DAG 血缘 |
| `topology/semantic_naming.py` | 确定性语义命名: 12 种 name_*_faces 函数 |
| `topology/shape_binding.py` | OCCT IndexedMap 子形状定位 + 校验 |
| `topology/design_identity.py` | DesignIdentity, FeatureIdentityReconciler |
| `topology/kernel_identity.py` | IdentityTransferPolicy (8 维), IdentityDecision |
| `topology/transaction.py` | TopologyTransaction: 原子提交/回滚 |
| `topology/operation_adapters.py` | 10 种操作适配器 (Extrude, Revolve, Boolean, ...) |
| `topology/cae_bridge.py` | CAE preflight gate, 命名集→面解析 |
