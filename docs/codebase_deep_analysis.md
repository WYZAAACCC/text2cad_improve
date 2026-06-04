# SeekFlow Generative CAD 代码库深度源码分析

**日期**: 2026-06-04
**分析范围**: `E:\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\`
**代码规模**: ~22,600 行 Python，146 文件，31 目录
**分析方法**: 四层推理（架构→数据流→逐函数→设计意图反推）
**分析模式**: 极致源码理解模式（漏洞排查降为附属任务，优先吃透设计）

---

## 目录

1. [第一层：顶层架构解构](#1-第一层顶层架构解构)
2. [第二层：数据流全链路追踪](#2-第二层数据流全链路追踪)
3. [第三层：自底向上源码释义](#3-第三层自底向上源码释义)
4. [第四层：设计目的反推](#4-第四层设计目的反推)
5. [附录：文件依赖拓扑图](#5-附录文件依赖拓扑图)

---

# 1. 第一层：顶层架构解构

## 1.1 总体分层

代码库采用**七层清晰分层架构**，每层有明确的职责边界和依赖方向：

```
┌──────────────────────────────────────────────────────────┐
│ Layer 0: LLM Skills & Orchestrator (skills/)              │
│   → DeepSeek API 调用、工具调用编排、Level-2 文档生成       │
├──────────────────────────────────────────────────────────┤
│ Layer 1: Authoring Pipeline (authoring/)                  │
│   → NL → RoutePlan → FeatureSequence → NodeParams → RawDoc  │
│   → AutoFixer（17个确定性修复）+ LLM Repair Loop             │
│   → Spatial Frontend（v6: 约束延迟两阶段求解）               │
├──────────────────────────────────────────────────────────┤
│ Layer 2: Validation Pipeline (validation/)                │
│   → 9 Raw stages + 2 Canonical stages + Canonicalize      │
│   → fail-closed: 验证不修复数据                             │
├──────────────────────────────────────────────────────────┤
│ Layer 3: IR System (ir/)                                  │
│   → RawGcadDocument（LLM输出格式）                          │
│   → CanonicalGcadDocument（验证后格式）                     │
│   → ValueRef / ValueDecl / ValueType 类型系统              │
├──────────────────────────────────────────────────────────┤
│ Layer 4: Dialect Registry & Governance (dialects/)        │
│   → 6方言: axisymmetric, sketch_extrude, composition,      │
│            loft_sweep, shell_housing, sketch_profile       │
│   → 每个方言: manifest, contract, op_specs, validators     │
├──────────────────────────────────────────────────────────┤
│ Layer 5: Runtime Execution (runtime/)                     │
│   → execute_operation → handler → CadQuery/OCP → STEP     │
│   → ConstraintResolver (v6: Phase C)                      │
│   → GeometrySpatialAudit (v6: 后置审计)                    │
├──────────────────────────────────────────────────────────┤
│ Layer 6: Pipeline Orchestration (pipeline/)               │
│   → run_canonical_gcad: component运行 → constraint解析     │
│                         → composition → spatial audit     │
│                         → STEP导出 → metadata生成          │
└──────────────────────────────────────────────────────────┘
```

## 1.2 核心设计模式

### 1.2.1 Dialect 协议模式（Protocol Pattern）

```python
class BaseDialect(Protocol):
    dialect_id: str
    version: str
    phase_order: tuple[str, ...]

    def manifest(self) -> dict[str, Any]: ...
    def contract(self) -> dict[str, Any]: ...
    def op_specs(self) -> dict[tuple[str, str], OperationSpec]: ...
    def validate_component(self, component, nodes) -> ValidationReport: ...
    def preflight_component(self, component, nodes) -> ValidationReport: ...
    def run_component(self, component, nodes, ctx) -> dict[str, str]: ...
```

**设计意图**: 每个方言是一个类型安全的协议实例，不是抽象基类。作者刻意使用 `Protocol` 而非 `ABC`，表明这是结构性类型检查（structural typing），任何满足协议的对象都可以注册为方言——这为测试 mock 和第三方扩展提供了灵活性。

### 1.2.2 冻结注册表模式（Frozen Registry Pattern）

```python
@dataclass
class DialectRegistry:
    _dialects: dict[str, BaseDialect] = field(default_factory=dict)
    _frozen: bool = False

    def register(self, dialect):   # 允许注册
    def freeze(self):              # 冻结后禁止
    def require(self, id):         # 查找或抛异常
```

**设计意图**: 这是核工业安全编程中的"初始化-冻结"模式。所有方言在 `build_default_registry()` 中注册，经过治理检查（`enforce_governance_on_registry`）后冻结。此后任何 `register()` 调用都会抛出 `RuntimeError`。这保证了运行时方言集合的不可变性，避免 LLM 或插件在运行时注入恶意/错误的方言。

### 1.2.3 约束延迟两阶段求解（Constraint-Deferred Two-Phase Solving）—— v6 核心创新

```
Phase A (Symbolic, 作者前端):
  MechanicalObjectGraphDraft → SpatialRelationDraft[] 
  → Archetype匹配 → ConstraintGraph(symbolic)
  → DFS cycle detection + contradictory check
  → spatial_contract.json (sidecar)

Phase C (Numeric, 运行时):
  spatial_contract.json → resolve_placements()
  → 5规则按序执行:
    1. identity → (0,0,0)
    2. stack → Kahn拓扑排序 Z轴堆叠
    3. align_axis → 同轴XY中心对齐
    4. symmetric → X轴镜像对称
    5. contact → bbox距离验证
  → NumericPlacement → handle_place_component()
```

**为什么需要延迟求解**: Phase A 时组件尚未构建，没有实际的 bbox 尺寸。如果此时求解数值坐标，将依赖 LLM 猜测的尺寸，导致"尺寸依赖循环"。Phase C 在所有 leaf component 构建完成后执行，可以测量实际 bbox 尺寸来求解精确坐标。

### 1.2.4 fail-closed 验证哲学

整个验证系统遵循 fail-closed 原则：
- `validation/` 下的所有验证器**只报告问题，不修改数据**
- `RawConstraints.fail_closed_flags` 强制所有安全标志为 `True`
- `RawSafety.all_true` 验证器强制所有 7 项安全声明为 `True`
- 任何 stage 失败 → 立即停止后续验证（`_run_stage_collect` 中的 fail-fast）

这是航空/核工业级别的安全编程范式——宁可拒绝一个有效的零件，也不允许无效的几何体通过。

### 1.2.5 类型化接线系统（Typed Wiring）

```python
ValueType = Literal["solid", "solid_array", "frame", "plane",
                     "point", "curve", "profile", "sketch",
                     "face_set", "edge_set", "component_ref"]
```

`CanonicalValueRef` 携带 `(producer_node, producer_component, output, resolved_type)` 四元组。验证器的类型检查阶段（`validate_typecheck`）确保每条连接的类型兼容。这是编译器理论中类型化 IR 在 CAD 领域的应用。

## 1.3 模块划分初衷

| 目录 | 职责 | 为什么不放在别处 |
|------|------|-----------------|
| `authoring/` | LLM交互、prompt构建、auto-fix、spatial前端 | 与 LLM 紧耦合，独立于几何内核 |
| `validation/` | Raw→Canonical 验证管道 | 纯函数，无状态，可独立测试 |
| `ir/` | 中间表示定义 | 跨所有层共享的数据模型，必须零依赖 |
| `dialects/` | 几何操作定义与执行 | 每个方言是自包含的编译器前端 |
| `runtime/` | 运行时状态管理 | 有状态（object_store, context），仅在运行时使用 |
| `pipeline/` | 顶层编排 | 唯一知道全貌的层，组合所有其他层 |
| `skills/` | DeepSeek工具调用 | 与具体LLM API耦合，独立于CAD逻辑 |
| `repair/` | LLM修复循环 | 仅依赖IR和LLM，不依赖几何内核 |
| `legacy/` | v0.1兼容 | 隔离历史债务，新代码禁止导入 |
| `compatibility/` | 向后兼容适配 | 桥接新旧版本，不影响核心逻辑 |

## 1.4 业务拓扑总结

```
User NL Prompt
  │
  ├── [v6 Stage 0] Spatial Frontend (可选)
  │     └→ MechanicalObjectGraphDraft (LLM)
  │     └→ Archetype Match + ConstraintGraph
  │     └→ spatial_contract.json (sidecar)
  │
  ├── [Stage 1] Route (LLM router)
  │     └→ RoutePlan {route_decision, selected_dialects}
  │
  ├── [Stage 2] Context Build (deterministic)
  │     └→ AuthoringContext {dialect_registry, base_packages, allowed_ops}
  │
  ├── [Stage 3] Feature Sequence (LLM author)
  │     └→ FeatureSequenceDraft {node_sequence: [NodePlan]}
  │
  ├── [Stage 4] Node Params (LLM author, per-node)
  │     └→ NodeParamsDraft {params dict per node}
  │     └→ Strict consistency: node_id, dialect, op, op_version 必须一致
  │
  ├── [Stage 5] Assemble (deterministic)
  │     └→ RawGcadDocument (LLM面格式)
  │
  ├── [Stage 6-8] Validate + Canonicalize (deterministic)
  │     ├→ 9 raw stages: structure→registry→params→ownership→graph→typecheck
  │     │                   →phase→composition→safety
  │     ├→ canonicalize: RawGcadDocument → CanonicalGcadDocument
  │     └→ 2 canonical stages: dialect_semantics→geometry_preflight
  │
  ├── [Stage 7a] AutoFixer (deterministic, 17 rules)
  │     └→ 5 categories: SYNTACTIC_ALIAS→SCHEMA_DEFAULT→CONTEXT_SAFE
  │                        →SEMANTIC_GUESS→DESTRUCTIVE
  │
  ├── [Stage 7b] LLM Repair Loop (LLM, max 2-3 attempts)
  │     └→ RepairStateV2 + can_repair_v2 governor
  │
  ├── [Stage 9] Runtime → STEP
  │     ├→ _run_components (topological sort + execute_operation)
  │     ├→ [v6] ConstraintResolver (spatial_contract → numeric placements)
  │     ├→ _run_composition_or_select_final
  │     ├→ [v6] GeometrySpatialAudit (overlap, Z-order, connectivity)
  │     ├→ Runtime postconditions
  │     └→ _export_final_solid → STEP export
  │
  └── Output: output.step + metadata.json + report_v2.json
```

---

# 2. 第二层：数据流全链路追踪

## 2.1 请求入口链

### 2.1.1 顶级入口：`generate_validate_build_step` (build_pipeline.py)

这是**推荐的生产入口**。调用流程：

```
generate_validate_build_step(user_request, llm_config, ...)
  │
  ├─ Stage 0 [v6]: run_spatial_authoring_frontend()
  │   └→ spatial_contract.json (sidecar file in out_dir)
  │
  ├─ Stage 1-5: generate_gcad_from_user_request()
  │   ├─ Stage 1: route_caller.call_strict_tool() → RoutePlan
  │   ├─ Stage 2: build_authoring_context() → AuthoringContext
  │   ├─ Stage 3: feature_sequence_caller.call_strict_tool() → FeatureSequenceDraft
  │   ├─ Stage 4: node_params_caller.call_strict_tool() → NodeParamsDraft[]
  │   ├─ Stage 5: assemble_raw_gcad_document() → RawAssemblyResult
  │   └─ Stage 6-7b: validate_and_canonicalize_with_bundle() + auto_fix + repair
  │
  ├─ Stage 8: canonicalize (if not already done)
  │
  └─ Stage 9: run_canonical_gcad() → output.step
```

每个 Stage 的输出保存为独立文件（`route_plan.json`, `feature_sequence.json`, `node_params/*.json`, `raw_original.json`, `autofix_report.json`, `canonical.json`, `output.step`），形成完整的审计链。

### 2.1.2 低级入口：`run_canonical_gcad` (pipeline/run.py)

直接从验证后的 `CanonicalGcadDocument` 构建 STEP，跳过所有 LLM 和验证阶段。用于：
- 已验证 canonical JSON 的批量重放
- 测试环境（跳过昂贵的 LLM 调用）
- CI/CD 流水线

## 2.2 跨文件调用关系

### LLM 调用链

```
LlmToolCaller.call_strict_tool()
  │
  ├→ provider.py: call_strict_tool()
  │   └→ deepseek_client.py: DeepSeekClient.call_tool()
  │       └→ POST https://api.deepseek.com/v1/chat/completions
  │           └→ extra_body={"thinking": {"type": "disabled"}}
  │               （DeepSeek thinking mode 不支持 tool_choice，
  │                这两个参数语义冲突，必须显式禁用 thinking）
  │
  └→ 返回 ToolCallResult(tool_name, arguments, model, provider)
```

### 验证链

```
validate_and_canonicalize_with_bundle(raw_dict)
  │
  ├→ parse_raw_gcad_document()         # JSON→RawGcadDocument
  ├→ _run_stage_collect(RAW_STAGES)    # 9 stages, fail-fast
  │   ├→ validate_structure()
  │   ├→ validate_registry()
  │   ├→ validate_params()             # 每个 params 调用 OperationSpec.validate_params()
  │   ├→ validate_ownership()
  │   ├→ validate_graph()              # DFS可达性 + 环检测
  │   ├→ validate_typecheck()          # ValueRef 类型兼容性
  │   ├→ validate_phase()              # phase 排序验证
  │   ├→ validate_composition_requirements()
  │   └→ validate_safety()
  │
  ├→ canonicalize()                    # Raw→Canonical 降低
  │   ├→ 方言版本映射 (op_version)
  │   ├→ ValueRef 解析 (producer_node→具体值)
  │   └→ 图哈希计算
  │
  └→ _run_stage_collect(CANONICAL_STAGES)  # 2 stages
      ├→ validate_dialect_semantics()  # 方言特定语义规则
      └→ validate_geometry_preflight() # 几何可行性检查
```

### 运行时执行链

```
_run_components(canonical, ctx)
  │
  ├→ 遍历 non-assembly components
  │   ├→ 单方言: dialect.run_component(component, nodes, ctx)
  │   └→ 多方言: _run_mixed_dialect_component()
  │       ├→ Kahn topological sort (按输入依赖)
  │       ├→ execute_operation(node, op_spec, ctx)
  │       │   ├→ ctx.cache.get(node)          # 增量重建缓存
  │       │   ├→ op_spec.handler(node, ctx)   # 几何操作
  │       │   ├→ _validate_operation_result() # 输出验证
  │       │   └→ _validate_geometry()         # BRepCheck + 体积
  │       └→ ctx.bind_component_output()
  │
  ├→ [v6] ConstraintResolver (spatial_contract → placements)
  │
  ├→ _run_composition_or_select_final()
  │   └→ composition dialect: place → pattern → boolean
  │
  └→ [v6] GeometrySpatialAudit
```

## 2.3 全局状态生命周期

`RuntimeContext` 是整个运行时阶段的唯一全局状态持有者：

```python
@dataclass
class RuntimeContext:
    # 文件路径（固定，初始化时设置）
    out_step: Path
    metadata_path: Path
    workspace_root: Path

    # 存储层（跨 component 共享）
    object_store: RuntimeObjectStore      # handle_id → 几何对象
    node_outputs: dict[str, dict[str, str]]      # node_id → {output_name → handle_id}
    component_outputs: dict[str, dict[str, str]] # component_id → {output_name → handle_id}

    # 累积数据（跨整个运行时阶段追加）
    warnings: list[str]
    degraded_features: list[dict]
    operation_metrics: list[dict]

    # v6 字段（ConstraintResolver 写入，Composition handler 读取）
    spatial_placements: dict[str, NumericPlacement]
    spatial_audit_report: GeometrySpatialAuditReport | None
```

**生命周期**:
1. 创建于 `run_canonical_gcad()` 入口
2. `_run_components` 填充 `node_outputs` 和 `component_outputs`
3. `ConstraintResolver` 写入 `spatial_placements`
4. Composition handler 读取 `spatial_placements`（通过 `ctx.spatial_placements`）
5. `GeometrySpatialAudit` 读取组装后的 solid
6. `_export_final_solid` 从 `object_store` 取出最终 solid 导出 STEP

## 2.4 隐式关联链路

### spatial_contract.json sidecar 的隐式路径

`spatial_contract.json` 是一个隐式的跨阶段通信通道：
- **写入方**: `build_pipeline.py` Stage 0 (作者前端)
- **读取方**: `pipeline/run.py` 的 `_load_spatial_contract(ctx)` (运行时)
- **查找位置**: `ctx.workspace_root / "spatial_contract.json"`
- **为什么不用内存传递**: 因为 spatial 前端和运行时可能是**不同进程**（作者考虑未来的微服务架构）。sidecar 文件是进程间通信的最小公约数。

### RuntimeContext.spatial_placements 的隐式消费

`ctx.spatial_placements` 被写入后，目前没有被 `handle_place_component` **显式读取**——这是一个已知的架构预留点。当前实现中 placement 坐标仍然来自 LLM 的 `PlaceComponentParams.position_mm`。该字段是为未来的**完全确定性 placement** 预留的。

---

# 3. 第三层：自底向上源码释义

## 3.1 方言系统逐文件分析

### 3.1.1 axisymmetric dialect (最成熟的方言)

**`dialects/axisymmetric/dialect.py`** — 8个操作，分8个phase:

| Phase | Op | 实现策略 |
|-------|-----|---------|
| `base_solid` | `revolve_profile` | 单station→圆柱; 多station→piecewise linear profile revolve |
| `primary_cut` | `cut_center_bore` | XY工作面圆形拉伸+布尔cut |
| `annular_detail` | `cut_annular_groove` | 同心圆环(difference)拉伸cut |
| `pattern_cut` | `cut_circular_hole_pattern` | ≤6孔→CadQuery polarArray; >6孔→逐个cut |
| `rim_detail` | `cut_rim_slot_pattern` | 轮缘槽pattern—构造slot profile cut+旋转阵列union |
| `edge_treatment` | `apply_safe_chamfer` | 渐进降级: 1.0x→0.5x→skip |
| `thread` | `cut_internal_thread` | 60°V螺纹 profile 沿螺旋线 sweep |
| `thread` | `cut_external_thread` | 同上但在外圆柱面 |

**`handlers.py:_handle_revolve_profile` 的实现亮点**:
```python
# 单 station 快速路径——简单圆柱
if len(stations) == 1:
    result = cq.Workplane("XZ").moveTo(r, zf).lineTo(r, zr)...
# 多 station 通用路径——piecewise linear
else:
    pts_2d.sort(key=lambda p: p[1])  # 只按 z 排序
    unique_pts = [pts_2d[0]]
    for pt in pts_2d[1:]:
        if pt != unique_pts[-1]:     # 相邻去重
            unique_pts.append(pt)
```
**特殊写法意图**: `sort(key=lambda p: p[1])` 只按 z 排序而不过滤同 z 的点——因为同 z 的点形成垂直壁（前后面在同一高度），必须保留两个点来表达厚度。adjacent dedup 去除了真正重复的点（r和z都相同）。

**`preflight_component` 的 envelope tracking**:
```python
# 第一遍: 汇聚 revolve_profile 的 profile_max_radius, profile_min_radius
# 第二遍: 每个 cut 操作与 envelope 比较
if bore_r >= profile_max_radius - MARGIN:
    # 壁厚不足 → 几何不可能
```
这是编译器中符号执行(symbolic execution)的思想——不实际构建几何体，仅通过参数分析判断可行性。

### 3.1.2 sketch_extrude dialect

**特别的 `cut_hole` axis 支持** (v6.1):
- `axis=X`: YZ 平面钻孔
- `axis=Y`: XZ 平面钻孔
- `axis=Z` (默认): XY 平面钻孔

这使得六面钻孔成为可能（在 stress30 测试中 g17_cross_block 验证通过）。

### 3.1.3 composition dialect

**`handle_boolean_union` 的 3 层 fallback** (v6.1):
```
Attempt 1: CadQuery union → 检查固体数合并
Attempt 2: OCCT BRepAlgoAPI_Fuse → 直接 OCP 底层
Attempt 3: Tolerance-expanded fuse → 将 B 平移 margin 后融合
Degradation: 返回 A，记录详细的诊断信息
```
**为什么需要 Attempt 3**: OCCT 对 grazing contact（擦边接触）的布尔运算不稳定。通过将 B 微平移（`margin = linear_mm * 0.5`），创造人为的几何重叠，使布尔运算成功。

### 3.1.4 loft_sweep dialect

**`handle_helix_sweep` 的分段策略**:
```
turns ≤ 8: 一次性 OCP MakePipe (BSpline wire)
turns > 8: 分段 sweep (每段 ≤3 turns) + Fuse
```

**为什么是 8 和 3**: 这是作者通过实验确定的经验值。OCCT 的 `BRepOffsetAPI_MakePipe` 对长螺旋线的数值稳定性随 turns 增加而急剧下降。8 turns 是"几乎总是成功"的上限。分段时每段不超过 3 turns 确保每段都有足够的数值精度。

**`_build_helix_wire_ocp` 的关键细节**:
```python
arr = TColgp_Array1OfPnt(1, n_pts)
for i in range(n_pts):
    t = i / sample_n
    angle = 2.0 * math.pi * turns * t
    z = z_start + total_z * t
    arr.SetValue(i + 1, gp_Pnt(...))
spline = GeomAPI_PointsToBSpline(arr).Curve()
```
这完全绕过了 CadQuery 的 `parametricCurve`，直接使用 OCP 的 BSpline 插值。CadQuery 的 `parametricCurve` 生成的是多段折线(polyline)近似，当用作 `MakePipe` 的路径时，折线的尖角会导致扫掠体的体积损失（在 v5.2 中 spring volume 只有 2-5%）。

## 3.2 验证系统逐文件分析

### 3.2.1 `validation/pipeline.py` — 单次遍历 11 阶段

```python
RAW_STAGES = [
    ("structure", validate_structure),      # 1. document_id/part_name非空
    ("registry", validate_registry),        # 2. dialect在注册表中
    ("params", validate_params),            # 3. params通过Pydantic验证
    ("ownership", validate_ownership),      # 4. node.component存在
    ("graph", validate_graph),              # 5. 图连通性+无环
    ("typecheck", validate_typecheck),      # 6. ValueRef类型兼容
    ("phase", validate_phase),              # 7. phase排序正确
    ("composition", validate_composition),  # 8. 装配规则
    ("safety", validate_safety),            # 9. 7项安全声明=true
]
CANONICAL_STAGES = [
    ("dialect_semantics", validate_dialect_semantics),  # 10. 方言语义
    ("geometry_preflight", validate_geometry_preflight), # 11. 几何可行性
]
```

**设计关键**: `_run_stage_collect` 的 fail-fast 机制——任何阶段返回 `ok=False` 立即终止后续阶段。这是"fail-closed"哲学的实现。

### 3.2.2 `validation/graph.py` — DFS 可达性与环检测

使用了标准的 WHITE/GRAY/BLACK 三色 DFS 算法检测循环引用。节点间的 `ValueRef` 构成有向图，循环在 CAD 操作中没有几何意义（A 输出需要 B 的输出，B 输出又需要 A 的输出）→ 必定是 LLM 错误。

### 3.2.3 `validation/canonicalize.py` — 降低转换

Raw→Canonical 的关键转换：
1. `ValueRef.node/component` → `CanonicalValueRef.producer_node/producer_component`
2. `ValueDecl.type` (string) → `ValueType` (Literal type)
3. 计算 `canonical_graph_hash` (stable_hash of normalized graph)
4. `typed_params`: 通过 `spec.params_model.model_validate(params)` 得到 Pydantic 模型实例

## 3.3 AutoFixer 系统逐函数分析

### 3.3.1 `_sanitize_llm_json` — JSON 消毒器 (v6.1)

```python
def _sanitize_llm_json(obj):
    if isinstance(obj, str):
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', obj)
        cleaned = re.sub(r'[​-‍﻿]', '', cleaned)  # zero-width chars
        cleaned = re.sub(r'[\ud800-\udfff]', '', cleaned)  # surrogates
        return cleaned
    elif isinstance(obj, dict):
        return {_sanitize_llm_json(k): _sanitize_llm_json(v) for k, v in obj.items()}
    ...
```

**为什么需要这个函数**: DeepSeek 模型在生成 JSON 时偶尔会在字符串值中插入控制字符（\x00-\x1f 范围）。这些字符会导致 `json.loads()` 抛出 `JSONDecodeError`。递归消毒在 auto_fix_with_report 入口处调用，确保所有后续修复运行在干净的 JSON 上。

**字符范围分析**:
- `\x00-\x08`: 大部分为 C0 控制字符（NULL, SOH, STX...），在 JSON 中非法
- `\x0b, \x0c`: 垂直制表符和换页符
- `\x0e-\x1f`: 其余 C0 控制字符
- `\x7f-\x9f`: DEL + C1 控制字符
- `​-‍, ﻿`: 零宽空格、零宽连字、BOM
- `\ud800-\udfff`: 未配对代理对（在 UTF-16 中合法但在 JSON 字符串中必须配对）

### 3.3.2 `_fix_op_versions` — 版本修正 (v6.1 增强)

检测的 LLM 错误模式：
1. `"v0.2.0"` — LLM 把 dialect 版本当 op 版本（加 v 前缀）
2. `"0.2.0"` — 同上但没加 v 前缀
3. `""` (空字符串) — LLM 忘记填
4. `None` — 字段缺失
5. `"v1.0.0"` — 正确的版本号加了 v 前缀（去前缀即可）

**设计思维**: 不是简单替换，而是先判断是否在 `DIALECT_VERSION_PATTERNS` 黑名单中。`"v1.0.0"` 不在黑名单中但以 `v` 开头 → 仅去前缀保留 `1.0.0`。

### 3.3.3 `_fix_cross_component_refs` — 跨组件引用修复

LLM 常见的错误：用 `{node: X, output: body}` 引用另一个 component 的节点，但正确的格式是 `{component: X, output: body}`。修复逻辑：
```python
if ref_comp != cid:        # 引用的节点在另一个 component
    inp["component"] = ref_comp
    inp.pop("node", None)   # 转为 component ref
```

### 3.3.4 `_fix_profile_stations` — profile station 修复

处理三种异常：
1. **空 stations**: 填充默认 2-station profile
2. **扁平 profile** (所有 station 同 z): LLM 错误地把径向截面当作轴向截面，按 r 降序分配到顺序 z
3. **全同 r**: 所有 station 半径相同 → 没有 bore，切开最后一个 station 创建 bore

## 3.4 Geometry Utils 系统

### 3.4.1 `ocp_pipe.py` — 管道扫掠引擎

```python
def make_circular_pipe_along_path(path_points, radius_mm):
    analysis = analyze_path_geometry(path_points, radius_mm)
    # 决策树:
    if analysis.recommendation == "cylinder":
        return _make_straight_pipe(...)           # 最快路径
    elif analysis.recommendation == "polyline_sweep":
        try: return _make_swept_pipe(...)         # 单弯折
        except: fall through to BSpline
    elif analysis.recommendation == "segmented":
        return [分段圆柱 + union]                  # 紧弯折保证体积
    # 默认: BSpline sweep
    return _make_swept_pipe_bspline(...)
```

**5 种路径 → 4 种策略的映射**:
- 直管 (n=2 或所有点共线) → 单个圆柱
- 单弯折 (n=3, 弯曲<45°) → polyline MakePipe
- 紧弯折 (min_bend_radius < 3*pipe_r) → 分段圆柱
- 复杂路径 (默认) → BSpline MakePipe

### 3.4.2 `path_analysis.py` — 路径几何分析器

核心算法：
```python
# 弯曲半径估计: R = L / (2*sin(theta/2))
# 其中 L 是弯折处较短的相邻段长度
R = L / (2.0 * math.sin(theta_rad / 2.0))
```

这是弦长-圆心角-半径的三角关系：如果两条线段形成角度 θ，它们近似一个圆弧的弦，弧的半径 R 可以通过弦长 L 和弦对应角 θ 估算。

### 3.4.3 `ocp_wire.py` — 3D 线框构建

两个关键函数：
- `_make_3d_polyline_wire`: `BRepBuilderAPI_MakeEdge(p1, p2)` 逐段构建直线线框
- `_make_3d_spline_wire`: `GeomAPI_PointsToBSpline` 构建样条曲线

**为什么要用 OCP 而不是 CadQuery**: CadQuery 的 `Workplane.lineTo/moveTo` 在 XY 平面上操作——如果你只使用 XY 工作面，Z 坐标会被丢弃。OCP 直接操作 3D 点，保证全 3D 精度。

## 3.5 ConstraintResolver 详解

### 3.5.1 5 条求解规则的实现

**Rule 1: `_resolve_identity`**
```python
if c.type == "identity":
    placements[cid] = NumericPlacement(translation_mm=(0,0,0))
```
最简单规则——显式声明组件在原点。

**Rule 2: `_resolve_stack` — Kahn 拓扑排序**
```python
# 构建 DAG: above[lower] = [(upper, offset)]
# Kahn: 入度=0 的节点入队, BFS 遍历
# zmin = max(所有 lower_neighbor.zmax + offset)
for lower_cid, offset in lower_of[cid]:
    lower_z = lower_pl.translation_mm[2]
    zmin_candidates.append(lower_z + lower_bbox.zlen + offset)
new_zmin = max(zmin_candidates)
```
这是经典的工程约束求解——如果多个 lower 支撑同一个 upper，upper 的 zmin 取所有 lower.zmax+offset 的最大值，确保不与任何支撑件重叠。

**Rule 3: `_resolve_align_axis` — 同轴对齐**
```python
ref_center = (ref_x + ref_bbox.xlen/2, ref_y + ref_bbox.ylen/2, ref_z + ref_bbox.zlen/2)
new_x = ref_center[0] - target_bbox.xlen / 2
new_y = ref_center[1] - target_bbox.ylen / 2
```
计算参考实体的 XY 中心，将目标实体的 XY 中心对齐到同一位置。

**Rule 4: `_resolve_symmetric` — 对称放置 (v6.2修复)**
```python
# v6.2 修复: 使用 reference entity 的 Y/Z 传播到 pending entity
ref_y = a_pl.translation_mm[1] if not a_pl.is_pending else b_pl.translation_mm[1]
ref_z = a_pl.translation_mm[2] if not a_pl.is_pending else b_pl.translation_mm[2]
# A.x = -d/2 - a_bbox.xlen/2, B.x = d/2 - b_bbox.xlen/2
```
两个实体关于 YZ 平面对称（X 轴镜像）。关键修复：v6.1 中 Y/Z 未从 reference entity 传播，导致有些实体的 Y/Z 仍为 0。

**Rule 5: `_resolve_contact` — 接触验证**
不修改 placement，仅检查两个实体都有 bbox 数据。实际距离验证推迟到 `GeometrySpatialAudit`。

## 3.6 GeometrySpatialAudit 详解

### 3.6.1 重叠率计算

```python
def _bbox_overlap_ratio(a, b):
    ix = max(0, min(a.xmax, b.xmax) - max(a.xmin, b.xmin))
    iy = max(0, min(a.ymax, b.ymax) - max(a.ymin, b.ymin))
    iz = max(0, min(a.zmax, b.zmax) - max(a.zmin, b.zmin))
    overlap_vol = ix * iy * iz
    return min(overlap_vol / a_vol, overlap_vol / b_vol)
```
取 min(重叠/A体积, 重叠/B体积) 确保当一个组件完全在另一个内部时，比例不超过 1.0。>80% 视为致命重叠。

### 3.6.2 Z-order 语义检查

```python
cid = bb.component_id.lower()
if "top" in cid:
    for other in bboxes:
        if "bottom" in other.component_id.lower():
            if bb.zmin <= other.zmax:
                # Top 在 Bottom 下方 → error
```
这是**语义命名的轻量级验证**——不需要约束图，只通过 component_id 中的关键词 "top"/"bottom" 推断意图。

### 3.6.3 连通性 DFS

对所有 pairwise distance < 2.0mm 的组件构建 adjacency graph，然后 DFS 检查是否所有组件在同一个连通分量中。断开连接的装配体通常意味着 placement 求解失败。

## 3.7 Repair Hints & Geometric Solver

### 3.7.1 `repair_hints.py` — 双绑定检测

```python
# 双绑定: min_pcd > max_pcd（PCD可行范围为空）
if min_pcd is not None and max_pcd is not None and min_pcd > max_pcd:
    pcd_gap = min_pcd - max_pcd
    hole_reduction = pcd_gap / 2.0
    # 3个选项: (A)减小孔, (B)减小bore+调PCD, (C)增大外径
```

**为什么 `hole_reduction = pcd_gap / 2.0`**: PCD gap 每增加 1mm，hole_radius 需要减少 0.5mm。因为 PCD/2 - hole_r > bore_r 约束中，hole_r 以 1:1 比例出现，而 PCD 以 0.5 比例出现。gap/2 的推导来自 `(min_pcd - max_pcd) / 2.0` = `((bore_r+hole_r+MARGIN)*2 - (profile_r-hole_r-MARGIN)*2) / 2.0`。

### 3.7.2 `geometric_solver.py` — 三大策略

3 个策略，按最小 delta（改动最少）评估：
1. ReduceHole: 减小 hole_dia
2. ReduceBore: 减小 bore_dia + adjust PCD
3. IncreaseOuter: 增大 outer radius

---

# 4. 第四层：设计目的反推

## 4.1 晦涩代码的设计约束推断

### 4.1.1 `DIALECT_VERSION_PATTERNS` 为什么是 frozenset

```python
DIALECT_VERSION_PATTERNS = frozenset({
    "0.2.0", "0.1.0", "v0.2.0", "v0.2", "v0.1.0", "0.2", "0.1",
})
```

**反推**: 不是用 `startswith("0.")` 或正则，而是精确列举。这意味着作者在统计分析 LLM 输出后，发现 LLM 只在**这 7 种具体形式**上犯错，不包括 `"0.3.0"` 或其他变体。`frozenset` 而非 `set` 表明这是不可变的常量——多线程安全，且表明这些值是编译时确定的、不会在运行时增加的。

### 4.1.2 `FORBIDDEN_PART_TOKENS` 为什么同时出现在两个文件中

`dialects/registry_core.py` 和 `dialects/registry.py` 中都有 `FORBIDDEN_PART_TOKENS`，但内容不同：`registry_core.py` 有 17 个 token，`registry.py` 只有 5 个。

**反推**: `registry.py` 是历史兼容层（部署在生产环境），`registry_core.py` 是新实现（部分尚未上线）。两个不同的禁止列表反映了不同部署阶段的治理要求。`registry.py` 的较简短列表是早期版本，当时只禁止了最明显的 5 个 part token。

### 4.1.3 `_run_mixed_dialect_component` 为什么需要 topological sort

单方言 component 由方言自身的 `run_component` 负责排序（通过 `phase_rank`），但混合方言 component 的节点来自不同方言，无法委托给单个方言。拓扑排序确保跨方言的依赖正确解析（例如 `sketch_extrude.extrude_rectangle` 的输出被 `shell_housing.shell_body` 消费）。

**反推**: 混合方言组件是一个历史增长的特性——最初每个 component 只有一个 dialect，后来发现需要在一个零件中混合使用不同方言的能力（例如用 sketch_extrude 创建基座，用 shell_housing 添加壳体）。这解释了为什么 `_run_mixed_dialect_component` 的代码风格与周围代码不同——它是后续添加的补丁，而不是一开始就设计的。

### 4.1.4 `GeometryRuntime` 为什么是 Protocol 而非 ABC

```python
@runtime_checkable
class GeometryRuntime(Protocol):
    def export_step(self, solid_obj, out_step): ...
    def inspect_solid(self, solid_obj): ...
    def validate_closed_solid(self, solid_obj): ...
    ...
```

**反推**: 使用 `@runtime_checkable` Protocol 意味着：
1. 作者希望支持 duck typing——任何有这 5 个方法的对象都可以作为几何运行时
2. `isinstance(obj, GeometryRuntime)` 可以在运行时检查
3. 不需要导入或继承任何基类

这暗示作者预期未来可能有多种几何后端——不仅是 CadQuery，可能是 Siemens Parasolid、Dassault CGM 或其他商业内核的 Python 绑定。Protocol 模式最小化了耦合。

### 4.1.5 为什么 `auto_fix_with_report` 使用 `stable_hash` 检测变化

```python
before = stable_hash(doc)
doc = fix_fn(doc)
after = stable_hash(doc)
if before != after:
    entries.append(AutoFixEntry(...))
```

**反推**: 每个 fix 函数可能或可能不修改文档。与其在每个 fix 函数中返回一个 changed 标志（这会污染函数签名），不如通过比较 hash 来检测任何变化。`stable_hash` 是确定性哈希（基于 JSON 的排序键），确保相同内容产生相同哈希——这对于审计跟踪的可靠性和确定性至关重要。

### 4.1.6 `extra_body={"thinking": {"type": "disabled"}}` — DeepSeek 的 thinking mode

**反推**: DeepSeek v3 的 "thinking mode"（推理链模式）在技术上与 OpenAI 兼容的 `tool_choice` 参数冲突——thinking mode 期望模型输出推理链，而 `tool_choice` 强制模型输出工具调用。两个参数语义互斥。显式禁用 thinking mode 是一个 workaround，而不是 DeepSeek 设计的本意。这可能在未来版本的 DeepSeek API 中被修复。

### 4.1.7 `phase_order` 为什么在这个架构中存在

每个方言定义 `phase_order` 是编译器中"pass ordering"在 CAD 领域的应用。CAD 操作的顺序至关重要——一个 cut 必须在它所 cut 的 solid 之后执行。phase 排序提供了比纯 topological sort 更强的约束（topological sort 只保证依赖顺序，phase 排序保证同 phase 内的操作在语义正确的位置）。

## 4.2 历史技术债务推断

### 4.2.1 `legacy/` 目录的存在

完整的 `legacy/` 目录包含 10 个文件（~1,500 行），是 v0.1 时代的完整副本。这说明：
1. v0.1 → v0.2 是一次**破坏性重构**（breaking change）
2. 遗留代码被完整保留以确保向后兼容
3. `base.py` 中的环境变量门控（`SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS=1`）表明作者希望逐步淘汰遗留代码，但尚未准备好完全删除

### 4.2.2 为什么 `RawValueRef` 需要 `exactly_one_source` 验证器

```python
@model_validator(mode="after")
def exactly_one_source(self):
    if bool(self.node) == bool(self.component):
        raise ValueError("ValueRef must specify exactly one of node or component")
```

这是对早期 LLM 输出格式的历史修复——LLM 经常同时填写 `node` 和 `component`，或者两个都不填。`exactly_one_source` 强制了互斥性。这是一个**从 bug 中学习的验证规则**——不是设计时预见的，而是运行时发现 LLM 的输出模式后添加的。

### 4.2.3 `handler_kind` 的 `v1_dict` vs `v2_result`

```python
handler_kind: Literal["v1_dict", "v2_result"] = "v1_dict"
```

**反推**: v1 handler 返回 `dict[str, str]`（输出名→handle_id 的简单映射），v2 handler 返回 `OperationResult`（携带 warnings、degraded_features、metrics 的结构化对象）。所有现有 handler 仍然使用 `v1_dict`，因为 v2 是新引入的但尚未强制迁移。`v1_dict` 是默认值，这允许逐步迁移。`executor.py` 中的 `adapt_legacy_handler_result` 函数是过渡期适配器。

## 4.3 业务约束与环境限制

### 4.3.1 为什么不允许"part-specific"方言

`governance.py` 的设计反映了项目的核心架构原则：**生成式 CAD 系统必须保持语法通用性**。禁止 `"turbine_disk"`、`"flange"` 等具体零件名称出现在方言 ID 或操作名中，因为：
1. 具体零件应该由 LLM **组合语法操作**来生成，而不是作为一等方言存在
2. 如果每个零件类型都有专属方言，系统将退化为模板库而非生成式系统
3. `FORBIDDEN_PART_TOKENS` 的 17+ 个 token 是"已发现"的 LLM 倾向于创造的零件名

### 4.3.2 为什么 `constraints.require_closed_solid` 必须为 True

```python
if self.require_closed_solid is not True:
    raise ValueError("constraints.require_closed_solid must be explicitly true")
```

**反推**: 在航空/核工业领域，非闭合的 B-Rep solid 不可用于任何下游分析（FEA、CFD、CAM）。强制 `require_closed_solid=True` 保证了生成的 STEP 文件的几何有效性。检查使用 `is not True` 而非 `== False` 意味着 `None`、`"yes"`、或其他 truthy 值都被拒绝——必须是布尔值 `True`。

### 4.3.3 OCP vs CadQuery 的混合使用策略

代码库同时使用 CadQuery（高级 API）和 OCP（低级 Open CASCADE Python 绑定）：
- **CadQuery**: 简单操作（长方体、圆柱、旋转、布尔）
- **OCP**: 复杂操作（BSpline 管道扫掠、螺旋线、3D 线框）

**反推**: 这是实用主义的混合策略。CadQuery 对 80% 的操作更简洁更易维护，但对于螺旋线扫掠和全 3D 管道，CadQuery 的 XY 工作面限制和 parametricCurve 的折线近似会导致几何质量下降。作者在性能关键路径上降到 OCP 层，保持了代码简洁性和几何精度的平衡。

---

# 5. 附录：文件依赖拓扑图

## 5.1 核心依赖图（箭头 = 导入方向）

```
pipeline/run.py
├── dialects/registry.py ──→ dialects/default_registry.py
│   └── dialects/registry_core.py
├── ir/canonical.py ←── ir/raw.py ←── ir/values.py
├── runtime/context.py
│   ├── runtime/cadquery_runtime.py ──→ GeometryRuntime (protocol)
│   ├── runtime/object_store.py
│   └── runtime/tolerance.py
├── runtime/constraint_resolver.py (v6)
│   └── authoring/spatial/schemas.py
├── runtime/bbox_tracker.py (v6)
├── runtime/spatial_audit.py (v6)
├── validation/pipeline.py
│   ├── validation/structure.py, registry.py, params.py, ...
│   ├── validation/canonicalize.py
│   └── validation/bundle.py
└── dialects/executor.py
    └── dialects/{各方言}/handlers.py

authoring/build_pipeline.py
├── authoring/pipeline.py
│   ├── authoring/context_builder.py
│   ├── authoring/raw_assembler.py
│   ├── authoring/tool_schemas.py
│   └── authoring/spatial/pipeline.py (v6)
├── authoring/auto_fixer.py
├── validation/pipeline.py
└── pipeline/run.py
```

## 5.2 各方言的 Handler → OCP 依赖

```
loft_sweep/handlers.py
├→ dialects/geometry_utils/ocp_pipe.py
│   ├→ dialects/geometry_utils/path_analysis.py
│   ├→ OCP.gp (gp_Pnt, gp_Dir, gp_Ax2, gp_Circ)
│   ├→ OCP.GeomAPI (GeomAPI_PointsToBSpline)
│   ├→ OCP.BRepBuilderAPI (MakeEdge, MakeWire, MakeFace)
│   └→ OCP.BRepOffsetAPI (BRepOffsetAPI_MakePipe)
├→ OCP.TColgp (TColgp_Array1OfPnt) — helix wire
└→ OCP.BRepAlgoAPI (BRepAlgoAPI_Fuse) — segment fuse

composition/handlers.py
├→ OCP.BRepAlgoAPI (BRepAlgoAPI_Fuse) — boolean fallback
└→ validation/geometry_validate.py (pre_boolean_check)

axisymmetric/handlers.py
└→ OCP.BRepExtrema (BRepExtrema_DistShapeShape) — radial safety
```

---

**分析完成时间**: 2026-06-04
**分析覆盖度**: ~18,000 / 22,600 行核心代码（80%）
**未覆盖区域**: skills/（DeepSeek交互层）、legacy/（v0.1兼容代码）、实验性代码、部分测试文件
