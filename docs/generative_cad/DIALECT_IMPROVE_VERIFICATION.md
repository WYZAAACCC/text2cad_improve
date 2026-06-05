# dialect_improve.md 逐条代码核实报告

**核实日期**: 2026-06-05
**核实方法**: 对 `docs/dialect_improve.md` 每项主张，交叉引用真实代码位置
**判定标记**:
- ✅ **Verified** — 主张与代码一致
- ⚠️ **Partial** — 主张方向正确，但细节有偏差或遗漏
- ❌ **Invalid** — 主张与代码矛盾
- ❓ **Needs Clarification** — 代码无法直接回答，需人工判断

---

# §2. 当前架构核实结论 — 逐条验证

## 2.1 Raw IR 是正确资产

> RawGcadDocument 有 schema_version, document_id, part_name, units, trust_level, selected_dialects, components, nodes, constraints, safety, llm_validation_hints

✅ **Verified** — [ir/raw.py:111-141](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py#L111)

> RawNode 有 id, component, dialect, op, op_version, phase, inputs, outputs, params, required, degradation_policy

✅ **Verified** — [ir/raw.py:47-65](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/raw.py#L47)

> 所有新语义表达都必须先放进 node.params，由各 op 的 params_model 解析

⚠️ **Partial** — 这是可行的方向，但 `typed_params` 已经以 `dict[str, Any]` 形式存在于 CanonicalNode 中（[canonical.py:58](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/canonical.py#L58)），且 typed_params 不参与 canonical_graph_hash（[canonicalize.py:141-149](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/canonicalize.py#L141) 的 hash 输入只包含 `params` 不含 `typed_params`）。**DimExpr 放在 typed_params 中不会破坏 hash**，这是重要的设计事实，文档没有明确提到。

## 2.2 Canonical IR 是可扩展资产

> CanonicalNode 当前已有 inputs, outputs, params, typed_params, required, degradation_policy, operation_effects, postconditions

✅ **Verified** — [ir/canonical.py:44-65](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/canonical.py#L44)

> CanonicalValueRef 只能表达 producer_node/producer_component, output, resolved_type，不能表达属性路径

✅ **Verified** — [ir/canonical.py:29-34](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/canonical.py#L29)

> 不要直接替换 CanonicalValueRef。新增 sidecar RefPath / DimExpr / PlacementExpr。

✅ **Verified (方向兼容)** — `CanonicalValueRef` 被 `canonicalize.py:_resolve_input_type()` 和 `typecheck.py:_resolve_producer_type()` 两处消费。新增 sidecar 不影响这两条路径。

> 只允许新表达式出现在 typed_params 中

✅ **Verified (可行)** — `typed_params` 在 canonicalize 阶段由 `op_spec.validate_params(node.params)` 生成（[canonicalize.py:99-101](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/canonicalize.py#L99)）。DimExpr 可以作为 params 中的 dict 值传入，在 canonicalize 后通过 typed_params 暴露。

⚠️ **问题**: `typed_params` 是 `op_spec.params_model.model_validate(node.params)` 的结果。如果 params 中包含 DimExpr dict（而不是 float），Pydantic model 会 reject（因为 params_model 定义字段为 `float`，不接受 dict）。  
**解决方案需明确**: 要么 (A) params_model 的字段类型改为 `float | DimExpr`，要么 (B) DimExpr 走单独的通道（如 `node.params["_dim_exprs"]` 然后在 canonicalize 后注入 typed_params）。方案 A 影响大（需要改所有 params_model），方案 B 更安全但不优雅。文档 §8 暗示了方案 A 但未明确。

## 2.3 ValueType 是名义类型

> 当前 ValueType 包含 solid, solid_array, frame, plane, point, curve, profile, sketch, face_set, edge_set, component_ref

✅ **Verified** — [ir/values.py:7-19](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/values.py#L7)

> 只能做浅层类型检查

✅ **Verified** — typecheck.py 只比较字符串 `actual != expected`（[typecheck.py:70](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/typecheck.py#L70)）

> 不要直接替换 ValueType。新增 SemanticType sidecar。

✅ **Verified (方向兼容)** — ValueType 被 50+ 处引用（所有 dialect spec 的 input_types/output_types、typecheck.py、handles.py 等）。替换代价极高。sidecar 方案正确。

## 2.4 OperationSpec 是核心 ABI

> 当前 OperationSpec 已有 dialect, op, op_version, phase, input_types, output_types, params_model, effects, required_context, postconditions, handler, handler_kind, summary/usage_notes 等

✅ **Verified** — [dialects/operation.py:32-65](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py#L32)

> 不要修改 OperationSpec 构造参数。新增 OperationSemanticSpec registry 旁路关联。

✅ **Verified (方向兼容)** — OperationSpec 字段变更会影响所有 6 个 dialect 的 op_specs() 方法（每个 dialect 构造 ~50+ OperationSpec）。旁路 registry 正确。

⚠️ **问题**: `OperationSpec` 有 `model_config = ConfigDict(extra="forbid")`（[operation.py:33](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py#L33)）。如果第二阶段要把 semantic 字段并回 OperationSpec，需要改为 `extra="ignore"` 或显式新增字段。文档说"第二阶段再考虑"但没有标记这个 extra=forbid 约束。

## 2.5 Executor 是正确的执行入口

> execute_operation 已经统一处理 handler 调用、legacy dict 适配、输出名校验、输出类型校验、handle 存在性校验、handle value_type 校验、warnings/degraded_features/metrics 传播、solid geometry validation

✅ **Verified** — [dialects/executor.py:27-90](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/executor.py#L27)

> geometry error 现在主要 append 到 ctx.warnings

✅ **Verified** — `_validate_geometry()` 将 BRepCheck 结果 append 到 `ctx.warnings`（[executor.py:137-164](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/executor.py#L137)）。**确实没有累积 GeometryHealth。**

> 没有事务 rollback

✅ **Verified** — handler 失败后没有回滚机制。部分 handler catch exception 后返回原 body。

> handler 内部仍存在 warn + return original body 的模式

✅ **Verified (严重)** — 以下 handler 存在此模式：
- `handle_cut_center_bore` [handlers.py:124-125](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L124) — **不检查 required**
- `handle_cut_circular_hole_pattern` [handlers.py:141-142](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L141) (params invalid) 和 [handlers.py:184-185](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L184) (exception) — **不检查 required**
- `handle_cut_annular_groove` [handlers.py:198-199](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L198) (params) 和 [handlers.py:210-211](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L210) (exception) — **不检查 required**
- `handle_cut_rim_slot_pattern` [handlers.py:224-228](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L224) 和 [handlers.py:249-250](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L249) — **不检查 required**
- `handle_cut_internal_thread` [handlers.py:321-322](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L321) 和 [handlers.py:342-343](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L342) — **不检查 required**
- `handle_cut_external_thread` [handlers.py:359-360](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L359) 和 [handlers.py:377-379](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/handlers.py#L377) — **不检查 required**

**但注意**: 外层 `dialect.run_component` 的 except 块（[dialect.py:278-282](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py#L278)）会检查 `not node.required and degradation_policy == "may_skip_with_warning"`，在 handler **向上抛出** exception 时兜底。但 handler 内部 try/except 吞掉 exception 返回原 body 时，外层不会触发。**文档 §14 正确识别了这个问题。**

## 2.6 geometry_preflight 方向正确

> validate_geometry_preflight 做 max_nodes, max_boolean_ops, max_profile_points, per-dialect preflight_component

✅ **Verified** — [geometry_preflight.py:25-89](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/geometry_preflight.py#L25)

> axisymmetric.preflight_component 已经做了 envelope tracking

✅ **Verified** — [dialect.py:102-250](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py#L102): profile_max_radius, profile_min_radius, center_bore_radius 等。

> envelope 只在 axisymmetric 内部可见，变量名硬编码，不能跨 dialect

✅ **Verified** — preflight_component 返回 `ValidationReport`（只包含 issues），不包含 envelope 数据。ShapeFacts 作为独立 pass 的必要性得到确认。

> 新增 ShapeFacts pass。第一阶段不要删除任何 dialect.preflight_component。

✅ **Verified (兼容)** — `CANONICAL_STAGES` 当前只有 2 个 stage（[pipeline.py:42-45](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/pipeline.py#L42)）。新增第 3 个 stage 不影响前两个。

## 2.7 RuntimeContext 有 sidecar 插槽

> RuntimeContext 已经有 spatial_placements, spatial_audit_report, spatial_contract_hash, placed_component_bboxes, strict_geometry_semantics 等 sidecar 字段

✅ **Verified** — [context.py:37-42](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/context.py#L37)

> 扩展 RuntimeContext 是合理的。新增字段必须有 default_factory 或默认值。

✅ **Verified (可行)** — RuntimeContext 是 `@dataclass` 且所有现有非必填字段都用 `field(default=...)` 或 `field(default_factory=...)`。新增 `compiler_facts: dict = field(default_factory=dict)` 等完全兼容。

⚠️ **注意**: RuntimeContext 不是 Pydantic model — 无 `extra=forbid` 限制。但构造函数 `__init__` 不接受未声明字段。文档建议的新字段需要显式声明。

---

# §3. 升级价值判断 — 逐条验证

## 3.1 SemanticType

✅ **Verified (兼容)** — 作为 sidecar 完全安全。`ir/semantic.py` 是新文件，不触及 `ir/values.py`。

## 3.2 DimExpr / PlacementExpr / RefPath

✅ **Verified (方向正确)** — 这是解决 "LLM 必须猜死坐标" 的唯一合理路径。

⚠️ **Partial (关键实现细节未解决)**:
- DimExpr 放入 `params` 时，Pydantic params_model（如 `CutCenterBoreParams`）当前声明 `diameter_mm: float = Field(gt=0)`，不接受 dict。需要在 canonicalize 阶段处理。
- 文档 §8 的 `evaluate_dim_expr` 返回 `float | None` — 这是 runtime 求值，但 typed_params 是在 canonicalize 阶段生成的。需要明确 DimExpr 求值发生在哪个阶段。
- 建议: Phase 1 先定义 DimExpr schema，不求值。Phase 2 在 runtime 中求值并替换 typed_params 的 DimExpr 为实际 float。这避免了 canonicalize 阶段的类型问题。

## 3.3 ShapeFacts

✅ **Verified (高优先级)** — axisymmetric preflight 的手写 envelope tracking 已经证明了可行性。通用化是自然下一步。

## 3.4 Feature IR / CAD SSA

✅ **Verified (方向判断正确)** — Phase 1 做 FeatureTrace 而非 FeatureIR executor，避免重写所有 handler。

## 3.5 Topology Naming

✅ **Verified (方向判断正确)** — Phase 1 做弱版本（TopologySelector based on bbox extreme/normal/area rank），不承诺永久稳定。

## 3.6 Planner / Optimizer

✅ **Verified (方向判断正确)** — Phase 1 只输出 PlanningReport，不做 graph rewrite。

## 3.7 Structured Recovery

✅ **Verified (必须做)** — handler 私自降级的问题已在上文 §2.5 验证。

## 3.8 GeometryHealth

✅ **Verified (高价值低破坏)** — geometry_runtime 已有 inspect_solid/validate_closed_solid/compute_bbox_mm/count_bodies 四个方法（[geometry_runtime.py:12-35](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/geometry_runtime.py#L12)），可直接复用。

## 3.9 Backend Lowering

✅ **Verified (Phase 4 延后判断正确)**

---

# §4. 目标架构 — 验证

> 升级后: Raw → validate_and_canonicalize_with_bundle → Canonical → build_compiler_module → semantic_analysis → fact_propagation → geometry_feasibility → planning_analysis → run_canonical_gcad ...

⚠️ **Partial** — 这个流程图将 compiler module 放在 `run_canonical_gcad` **之前**。但当前架构中 `run_canonical_gcad` 是直接接收 CanonicalGcadDocument 的（[run.py:94](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py#L94)）。有两个插入选项:

**Option A (文档建议)**: 在 `run_canonical_gcad` 外部运行 compiler module，然后传入 ctx
**Option B (更安全)**: 在 `run_canonical_gcad` 内部（`_run_components` 之前）运行 compiler module

当前 `run_canonical_gcad` 签名是:
```python
def run_canonical_gcad(canonical, out_step, metadata_path, validation_seed, ...)
```
没有 `compiler_module` 参数。Option A 不需要改签名（compiler module 结果通过 validation dict 传入）。Option B 在函数内部创建 compiler module。

**文档 §11 选择了 Option B**（在 `run_canonical_gcad` 内部调用 `analyze_canonical_with_middle_end`），这是正确的选择。

> 若 middle-end disabled，旧系统必须完全按原路径工作

✅ **Verified (可通过环境变量实现)**

---

# §5. 新增模块清单 — 验证

> 新增目录: compiler/, ir/expr.py, ir/semantic.py, analysis/, planning/, runtime/health.py

✅ **代码已证实不存在这些文件** — 可以安全创建。

> 尽量不要修改: ir/raw.py, ir/values.py, dialects/base.py, existing params.py, existing handler signatures

✅ **已确认这些文件不应修改**。

> 允许小幅修改: ir/canonical.py, runtime/context.py, dialects/executor.py, validation/pipeline.py, pipeline/run.py, pipeline/metadata_v3.py

⚠️ **Partial** — 明细:
- `ir/canonical.py` — **不需要修改**（CompilerModule 读 CanonicalGcadDocument 但不写入）
- `runtime/context.py` — ✅ 需要添加 compiler_facts 等字段
- `dialects/executor.py` — ✅ 需要在 `_validate_geometry` 处记录 health
- `validation/pipeline.py` — **不需要修改**（compiler 在 canonicalize 之后运行，不作为 validation pass 加入 RAW_STAGES 或 CANONICAL_STAGES）。但文档 §11 把 compiler 放在 validation pipeline 之外，所以不需要修改。
- `pipeline/run.py` — ✅ 需要插入 middle-end 调用
- `pipeline/metadata_v3.py` — ✅ 需要将 compiler diagnostics 写入 metadata

---

# §6. 数据模型规格 — 逐字段验证

## 6.1 ir/expr.py — DimExpr / RefPath

> RefPath.root_kind: Literal["node", "component"]; root_id: str; output: str; path: list[str]

✅ **与现有 IR 一致** — CanonicalValueRef 也有 producer_node 和 producer_component 字段。RefPath 扩展了 path。

> DimExpr.op 白名单: const, ref, add, sub, mul, div, min, max, abs, clamp

✅ **安全的操作符集合**。没有 `pow`, `sin`, `cos` 等需要数学库的操作。适合 Phase 1。

> 禁止 eval，禁止 Python expression string

✅ **强制性约束**

> 除法分母接近 0 时 fail-closed

✅ **正确**

> 递归深度默认最大 16

✅ **合理**

## 6.2 ir/semantic.py — SemanticType

> SemanticType.kind 包含 face, edge, datum, dimension

✅ **这些类型在 ValueType 中不存在**，是补充而非替换。

> FaceSelector.role 包含 top, bottom, front, back, left, right, outer_cylindrical, inner_cylindrical 等

✅ **与 CanonicalFace enum** ([geometry_semantics.py:35-52](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/geometry_semantics.py#L35)) 一致。

## 6.3 analysis/facts.py — ShapeFacts / FactStore

> ShapeFacts 字段: value_id, value_type, component_id, producer_node, bbox, radius_min_mm, radius_max_mm, length_z_mm, volume_mm3, traits, faces, derived_from, notes

✅ **设计合理**。value_id 格式与 CanonicalValueDecl.value_id 一致（`f"{decl.type}:{node.component}:{node.id}:{decl.name}"` — [canonicalize.py:125-126](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/canonicalize.py#L125)）。

> 建议增加 extra: dict[str, Any]

✅ **已在 §8.2 的修正说明中补充**

> FactStore 的 bind/get_node_output 接口

✅ **干净的设计** — 通过 `node_id.output_name` key 映射到 fact。

---

# §7. CompilerModule 与 PassManager — 验证

> CompilerModule 的 add_issue() 方法

⚠️ **Partial** — issue dict 字段（stage, code, message, severity, node_id, component_id, details）与 ValidationIssue（[reports.py:12-22](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/reports.py#L12)）字段不完全一致。ValidationIssue 有 `path`, `expected`, `actual` 字段。建议 compiler diagnostic 格式与 ValidationIssue 对齐，方便 repair prompt 统一处理。

> CompilerPass Protocol

✅ **简单且足够** — `run(module) -> module` 是不可变式 pattern。Phase 1 不需要复杂依赖图。

---

# §8. Fact Propagation 第一阶段规则 — 逐 op 验证

## 8.1 axisymmetric.revolve_profile — 输入参数

> profile_stations: list[{r_mm, z_front_mm, z_rear_mm}]

✅ **Verified** — RevolveProfileParams 的 profile_stations 字段确实是 `list[ProfileStation]`，ProfileStation 有 `r_mm, z_front_mm, z_rear_mm`（[bases/axisymmetric/models.py:10-22](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/bases/axisymmetric/models.py#L10)）。

> 输出 facts: radius_max_mm = max(r_mm)

✅ **逻辑正确** — 对于单 station（圆柱体），radius_max == radius_min。对于多 station 阶梯轴，max 等于最大外径。

## 8.2 axisymmetric.cut_center_bore — 校验规则

> diameter_mm / 2 < input.radius_max_mm - min_wall_margin_mm

✅ **与现有 preflight 一致** — 现有 axisymmetric preflight 检查 `bore_r >= profile_max_radius - MARGIN`（[dialect.py:168](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py#L168)）。MARGIN = 1.0mm。

> 输出 facts: faces.inner_cylindrical = cylinder radius diameter/2

⚠️ **Partial** — 当前 `handle_cut_center_bore` 不追踪 faces。从 OCP 检测 inner_cylindrical face 是可行的（通过 normal 方向和半径），但 Phase 1 从 typed_params 推导更简单。

## 8.3 axisymmetric.cut_circular_hole_pattern — 校验规则

> pcd_mm / 2 + hole_dia_mm / 2 < radius_max_mm - margin

✅ **与现有 preflight 一致** — [dialect.py:213-215](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py#L213)

> if center_bore exists: pcd_mm / 2 - hole_dia_mm / 2 > center_bore_radius_mm + margin

✅ **与现有 preflight 一致** — [dialect.py:224-226](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/axisymmetric/dialect.py#L224)

## 8.4 composition.translate_solid — 保守传播

> bbox min/max shifted by x/y/z if exact numeric facts exist

✅ **逻辑正确**

## 8.5 composition.boolean_cut — 保守传播

> 如果 cutter bbox 与 target bbox 明确不相交 → warning boolean_cut_may_be_noop

✅ **逻辑正确** — 这是静态分析中非常有价值的信息

> 如果 cutter bbox 完全 swallows target bbox → error boolean_cut_may_remove_entire_body

✅ **逻辑正确** — 这会阻止全切错误

---

# §9. Expression Evaluator — 验证

> evaluate_dim_expr(expr, module) -> float | None

⚠️ **Partial**:
- `module: CompilerModule` 参数包含了 canonical graph 引用。RefPath 解析 `component.<id>.body.radius_max_mm` 需要查询 ShapeFacts（在 FactStore 中）。
- **Phase 1 限制**: ShapeFacts 和 DimExpr 求值器都在 Phase 1 中实现，但 RefPath 解析需要 FactStore 先填充。这是一个鸡生蛋问题 — 应该在 FactStore 填充后、handler 执行前求值 DimExpr。

> 不要支持 arbitrary object path, method call, CadQuery object inspection, runtime object_store lookup

✅ **正确的安全约束**

---

# §10. Semantic Analysis 第一阶段 — 验证

> OperationSemanticSpec 的 fact_rule / feasibility_rule 签名

⚠️ **Partial** — `Callable[..., Any]` 类型不明确。建议明确签名:
```python
fact_rule: Callable[[CanonicalNode, FactStore, CompilerModule], ShapeFacts] | None
feasibility_rule: Callable[[CanonicalNode, ShapeFacts, CompilerModule], list[dict]] | None
```

---

# §11. 新增 Validation Stage 的接入方式 — 验证

> 新增函数 analyze_canonical_with_middle_end(canonical) -> CompilerModule

✅ **插入点清晰** — 在 `run_canonical_gcad` 内部 `_run_components` 之前。

> 环境变量 SEEKFLOW_GCAD_ENABLE_MIDDLE_END 默认 "1"

✅ **环境变量控制可行**

⚠️ **关键缺失**: 文档说在 `run_canonical_gcad` 内部运行，但没有明确 middle-end 产物如何传递给 `_run_components`。建议方案:
```python
ctx.compiler_facts = module.facts.model_dump()
```
因为 `ctx` 在 `_run_components` 之前已创建。handler 可以通过 `ctx` 访问 facts。

---

# §12. PlanningReport 第一阶段 — 验证

> Planner rules: hole_pattern_should_batch, edge_treatment_too_early, many_destructive_ops, large_pattern_risk

✅ **与现有 geometry_preflight 策略一致**:
- 现有 hole count 上限在 axisymmetric params: `count: int = Field(ge=2, le=240)`（[models.py:58](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/bases/axisymmetric/models.py#L58)）
- 现有 pattern count 上限在 composition preflight: `max_instances = 360`（[composition/dialect.py:134](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/composition/dialect.py#L134)）
- 现有 edge_treatment phase 在大部分 dialect 中是倒数阶段

# §13. GeometryHealth — 验证

> 使用现有 geometry_runtime 的 inspect_solid, validate_closed_solid, compute_bbox_mm, count_bodies

✅ **所有方法已存在** — [geometry_runtime.py:12-35](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/geometry_runtime.py#L12)

> 修改 execute_operation._validate_geometry：保留原 warnings 行为，新增 ctx.geometry_health

⚠️ **Partial** — `geometry_health` 以什么 key 存储？建议 `f"{node.id}.{output.name}"`，与 ObjectStore handle id 格式对齐。

> OCP 不可用时 health.status = unknown，不 fail

✅ **已在 geometry_runtime 的返回类型中体现** — `compute_bbox_mm` 返回 `list[float] | None`，`count_bodies` 返回 `int | None`。

---

# §14. Handler 降级规则收紧 — 验证

> 发现现状中一些 handler 仍会: except Exception → warn + return original body

✅ **Verified (严重)** — 已在 §2.5 详细列出。

> 新增 helper 函数 handle_feature_failure

✅ **正确的统一方式**

> 第一阶段只改 axisymmetric handlers 中最明显的 destructive ops

✅ **范围合理** — 7 个 axisymmetric destructive handler 需要修复。composition handlers 已经有 `_degraded_store` 且检查了 `required`（[composition/handlers.py:32-47](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/composition/handlers.py#L32)），sketch_extrude handlers 需要检查（未逐行读）。

⚠️ **需要确认**: sketch_extrude handlers 中的 `handle_cut_hole`, `handle_cut_rectangular_pocket` 等的 degradation 行为是否也需修复。文档 §14 说只改 axisymmetric，但 sketch_extrude 的 handlers 可能有同样问题。

---

# §15. Metadata 集成 — 验证

> 当前 metadata_v3 已保存 validation, runtime proof, artifact hash 等

✅ **Verified** — [metadata_v3.py:54-84](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata_v3.py#L54) + [metadata_v3.py:86-92](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata_v3.py#L86)

> 新增字段不要破坏 MetadataProofV3 的 extra=forbid

✅ **Verified (关键发现)**: 
- `MetadataProofV3` 有 `extra="forbid"`（[metadata_v3.py:88](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata_v3.py#L88)），但它的 `validation: dict` 字段是 bare dict — **新增 validation section 不会触发 extra=forbid 错误**！
- `normalize_validation_proof()` 在 [metadata.py:63-66](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata.py#L63) 明确保留 extra diagnostic sections:
  ```python
  # Preserve any extra non-required diagnostic sections
  for key, value in validation.items():
      if key not in normalized:
          normalized[key] = value
  ```
- `REQUIRED_VALIDATION_STAGES` = `["core_validation", "dialect_semantics", "geometry_preflight", "runtime_postconditions", "inspection_validation"]`（[metadata.py:9-15](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/metadata.py#L9)）
- 新增 `compiler_middle_end`, `planning_report`, `geometry_health_summary` 会通过 `normalize_validation_proof` 自动保留

✅ **文档 §15 的 "因为现有 normalize_validation_proof 会保留 extra diagnostic sections" 主张 — 完全正确。**

> 在 validation dict 中添加额外 section: compiler_middle_end, planning_report, geometry_health_summary

✅ **代码已证实可以安全添加**

---

# §16. STEP 生成能力保持 — 验证

> STEP export 当前: obj = ctx.object_store.get(handle_id) → ctx.geometry_runtime.export_step(obj, ctx.out_step)

✅ **Verified** — [run.py:470-472](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py#L470)

> 新增 pre_export_health_gate：runtime_postconditions 之后，_export_final_solid 之前

✅ **插入点清晰** — 当前运行顺序在 [run.py:226-238](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py#L226):
```
runtime_postconditions → _export_final_solid → geometry_postcheck → step_postcheck
```
pre_export_health_gate 应在 runtime_postconditions 之后、`_export_final_solid` 之前。

⚠️ **设计问题**: 当前 `geometry_postcheck` 也在 `_export_final_solid` 之后运行（[run.py:247-251](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/pipeline/run.py#L247)）。pre_export_health_gate 建议合并进 geometry_postcheck 的前半部分（export 前检查 volume/bbox/closed），而不是新增一个独立 gate。

---

# §17. 测试计划 — 验证

> 新增测试目录 tests/generative_cad/test_*.py

✅ **现有测试目录结构**: `integrations/engineering_tools/tests/generative_cad/` 已有 25+ 个测试文件。新增测试文件可以放入同一目录。

> SEEKFLOW_GCAD_ENABLE_MIDDLE_END=0 时旧路径 ok，=1 时新路径 ok

✅ **正确**

> canonical_graph_hash 不因 middle-end 改变

✅ **正确的验收标准** — 这是 middle-end 不修改 CanonicalGcadDocument 的直接验证。

---

# §18. 分阶段实施计划 — 验证

> Phase 0: 安全保护与开关

✅ **Phase 0 的最小实现**: compiler/module.py, compiler/pass_manager.py, compiler/config.py, 以及 run.py 中的 if-check。不运行任何实际 pass。

> Phase 1: Expression + ShapeFacts for axisymmetric

✅ **文件清单与 §5 一致**

> Phase 2: GeometryHealth + required degradation 收紧

✅ **文件清单正确** — runtime/health.py + dialects/executor.py + axisymmetric/handlers.py

> Phase 3: PlanningReport

✅ **文件清单正确**

> Phase 4: Opt-in Planner Rewrite

✅ **延后正确** — 这是最危险的阶段，应等前三个 phase 稳定

> Phase 5: Backend Lowering 准备

✅ **延后正确**

---

# §19-20. Claude Code 实施约束 — 验证

> 每个 commit 必须保持测试可运行

✅

> 不得修改 Raw schema_version

✅ — 当前值是 `Literal["g_cad_core_v0.2"]`

> 不得修改 canonical_graph_hash 计算逻辑

✅ — 当前在 [canonicalize.py:141-149](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/validation/canonicalize.py#L141)，hash 输入是 id, component, dialect, op, op_version, phase, inputs, outputs, params（不含 typed_params）

> 不得在 params 中使用 eval

✅

> 不得引入非标准 heavyweight dependency

✅

> 不得要求 OCP 在所有测试环境可用

✅

---

# 汇总：关键发现

## 代码已证实兼容的

1. ✅ RuntimeContext dataclass 支持新字段（§2.7）
2. ✅ metadata validation dict 保留 extra diagnostic sections（§15）
3. ✅ `typed_params` 不参与 canonical_graph_hash（§2.1）
4. ✅ OpenSpec 有 extra=forbid 但文档的旁路 registry 方案回避了此问题（§2.4）
5. ✅ 现有 geometry_runtime 有所有需要的 inspection 方法（§13）
6. ✅ shape_facts value_id 格式与 canonicalize 一致（§6.3）

## 需要明确/修正的

1. ⚠️ **DimExpr 类型兼容**: Pydantic params_model 当前拒绝 dict 类型的字段值。Phase 1 是只定义 schema 不求值，还是需要改 params_model？
2. ⚠️ **handle_cut_center_bore etc. 的 required 检查**: 需要统一到 `_degrade` 函数
3. ⚠️ **Phase 1 compiler module 放置位置**: 确认在 `run_canonical_gcad` 内部 `_run_components` 之前（doc §11 Option B）
4. ⚠️ **sketch_extrude handlers 的 degradation**: 文档 §14 说只改 axisymmetric。需要确认 sketch_extrude 是否也需要。

## 与现有代码冲突的

没有发现任何冲突。所有方案都是增量添加，不改动现有 ABI。

## 最终判断

**dialect_improve.md 的架构方案整体与代码一致，可以进入 Phase 0 实施。**

Phase 0 的最小实现只需要：
1. 创建 `compiler/module.py`（CompilerModule dataclass）
2. 创建 `compiler/config.py`（环境变量检测）
3. 在 `pipeline/run.py` 的 `run_canonical_gcad` 中加入一个 if-check（不运行任何实际 pass）
4. 验证所有现有测试通过

这是零风险的起步方式。
