# llm_skill_base21.md 深度终审报告

**审计日期**: 2026-06-04
**审计方法**: 四层全量交叉验证（文档→代码逐行对齐）
**审计范围**: 文档 1723 行 VS 实际代码 ~22,600 行（146 文件）
**审计模式**: 最高深度推理、全量代码上下文、零容忍工程审计

---

# 1. 一句话终审结论

**方向完全正确，核心诊断精准，但工程落地存在 4 个致命缺陷、7 个中危隐患、6 个低危优化项。需补充 3 个关键实现细节后方可施工。建议先修 P0 再按修订后路线图分批实施，不可照搬原文顺序。**

---

# 2. 顶层方案评审

## 2.1 正确点（保留并强化）

| # | 论断 | 代码验证 | 评价 |
|---|------|---------|------|
| 1 | LLM 不应充当 CAD 编译器 | [raw_assembler.py](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/authoring/raw_assembler.py) 已经承担了接线、output 生成、boolean_union 展开等编译器职责 | ✅ 方向正确，但需注意这已经是部分实现的事实 |
| 2 | 孔语义不足（axis+position_mm 二维歧义） | `CutHoleParams.axis` 允许 X/Y/Z 但 `position_mm` 允许 len=2，handler 中 axis=Y 时 z 默认为 bbox 中面（[handlers.py:117](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/sketch_extrude/handlers.py#L117)）| ✅ 诊断精准 |
| 3 | boolean_union 第三层 `b.translate((margin,margin,margin))` 改变几何 | [composition/handlers.py:219](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/composition/handlers.py#L219) 完全证实 | ✅ 这是真实 bug，不是设计意图 |
| 4 | `handle_place_component` 不消费 `ctx.spatial_placements` | [composition/handlers.py:80](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/composition/handlers.py#L80) 只读 `params.position_mm` | ✅ 确凿 |
| 5 | 成功标准过低（只检查 STEP 存在） | [postconditions.py](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/runtime/postconditions.py) 不检查 volume/solid count/bbox | ✅ 确凿 |
| 6 | cut_hole_pattern_linear 固定在 XY 平面 | [handlers.py:151-159](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/sketch_extrude/handlers.py#L151-L159) 硬编码 `Workplane("XY")` + `z_len` | ✅ 确凿 |
| 7 | loft 只用 CadQuery `.loft()` | [loft_sweep/handlers.py:158](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/loft_sweep/handlers.py#L158) `toPending().loft()` | ✅ 确凿 |

## 2.2 设计缺陷

### 缺陷 D1（致命）：原则A与现有架构冲突

**文档主张**: "LLM 不允许写 concrete node wiring"，"LLM raw 中出现 inputs → schema fail"

**代码现实**: 当前 authoring pipeline 的 Stage 3-4 让 LLM 生成 `FeatureSequenceDraft.node_sequence` 和 `NodeParamsDraft`，这些已经包含了 `node_id`、`dialect`、`op` 等字段。`raw_assembler.py` 的职责是"系统侧确定性地填充 wiring"，但 **LLM 仍然在写 node_id 和 op 选择**。

**矛盾**: 如果Commit 4禁止LLM raw中出现inputs，那么整个 `RawNode.inputs` 字段必须从 LLM 输出中移除。但这意味着：
1. `RawGcadDocument` 的 schema 必须修改
2. `raw_assembler.py` 必须承担所有 wiring 推理（当前只做 typed wiring，不做语义推理）
3. 所有现有 prompt template 和 35+ 测试 case 的 llm_raw.json 全部失效
4. 需要的不是修补，而是整个 Stage 3-5 的**完全重写**

**建议**: 将原则A调整为渐进路线——Phase 1 保持当前 LLM 输出格式但增强 validation；Phase 2 逐步将 wiring 逻辑移到 assembler；Phase 3 最终移除 LLM 的 wiring 能力。

### 缺陷 D2（高危）：`ir/geometry_semantics.py` 放置位置不当

**问题**: 文档建议将 `HolePlacementV2`、`CanonicalFace` 等放在 `ir/geometry_semantics.py`。但 `ir/` 目录当前只包含纯 IR 定义（`raw.py`, `canonical.py`, `values.py`, `parse.py`, `hashing.py`），不包含任何语义解析逻辑。

**后果**: `geometry_semantics.py` 包含 `resolved_face_hole_placement()` 等执行逻辑（放在 `dialects/geometry_utils/hole_placement.py`），但 `HolePlacementV2` 等**纯数据模型**适合 `ir/`。正确的拆分是：
- `ir/geometry_semantics.py` — 只放纯 Pydantic 数据模型（CanonicalFace, Axis3, HolePlacementV2 等）
- `dialects/geometry_utils/hole_placement.py` — 解析/执行逻辑（resolve_face_hole_placement 等）

### 缺陷 D3（中危）：`CanonicalFace` 枚举对圆柱体不适用

**问题**: `CanonicalFace` 枚举 `top/bottom/front/back/left/right` 是为长方体设计的。对于 axisymmetric 零件（圆柱体、锥体），"front" 没有唯一定义——圆柱面是连续曲面。

**代码现实**: `handle_cut_hole` 对 axis=Y 用 `Workplane("XZ")` 在 bbox 中面处钻孔（line 117），这个行为对圆柱体实际可用但语义不精确。

**建议**: 增加 `CanonicalFace.CYLINDRICAL = "cylindrical"` 并在 resolver 中支持圆柱面的参数化（角度+高度）。

### 缺陷 D4（中危）：Commit 顺序逻辑错误

**文档建议顺序**: Postcondition → Hole V2 Models → Hole Handlers → Assembler禁止wiring → Spatial闭环 → Loft+Boolean → Prompt

**问题**: Commit 4（禁止 LLM wiring）应该在 Commit 2-3（新 hole schema）**之前**，因为新的 hole V2 schema 如果仍然由 LLM 自由写 wiring，会立即产生新的错误类型（g14 类引用混乱会从旧 op 迁移到新 op）。

**正确顺序**: Phase 0（安全网）→ Phase 4（Wire 禁止）→ Phase 1（孔重构）→ Phase 2（Spatial闭环）→ Phase 3（内核增强）

---

# 3. 文档代码偏差清单（逐条对应）

## 3.1 数据模型偏差

| # | 文档位置 | 文档内容 | 实际代码 | 偏差类型 |
|---|---------|---------|---------|---------|
| B1 | §3.1 `Axis3` | `class Axis3(str, Enum): POS_X = "+X"` | 系统中 axis 用 `Literal["X","Y","Z"]` | **多实现**——引入新类型但旧代码仍用 Literal，产生两套 axis 表示 |
| B2 | §3.2 `CutHoleV2Params` | `placement: HolePlacementV2` | 旧 `CutHoleParams` 接受 `axis + position_mm` | **兼容缺口**——文档没有提供 V1→V2 的迁移桥接代码 |
| B3 | §3.2 `DrillHole3DParams` | `direction: tuple[float, float, float]` | 系统已有 `translate_solid.vector_mm` 使用同类型 | **少实现**——文档漏了 vector 的 zero 检查只放在 validator 中，handler 里也应防御 |
| B4 | §3.2 `CutCircularHolePatternV2Params` | `pcd_mm: float`, `count: int(ge=1, le=512)` | 旧 `CutCircularHolePatternParams` 在 axisymmetric 方言中 | **不一致**——新 V2 放 sketch_extrude，但 circular hole pattern 传统属于 axisymmetric |
| B5 | §3.1 `FeatureScope` | `target_component: str\|None` | 系统当前没有跨组件 feature scope 概念 | **少实现**——FeatureScope 在单组件场景不需要，但定义没说明何时为 None |

## 3.2 OperationSpec 构造偏差

| # | 文档位置 | 文档内容 | 实际代码 | 偏差类型 |
|---|---------|---------|---------|---------|
| B6 | §3.3 注册代码 | `OperationSpec(op="cut_hole_v2", op_version=1, input_types=["solid"], ...)` | `OperationSpec.__init__` 要求 `dialect, op_version: str, phase, params_model, effects, handler` 等 | **少实现**——文档漏了 `dialect="sketch_extrude"`、`phase`、`effects`、`handler` 四个必需参数 |
| B7 | §3.3 `op_version` | `op_version=1` (int) | [operation.py:37](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/dialects/operation.py#L37): `op_version: str` | **实现相悖**——文档用 int，代码用 str（`"1.0.0"`) |
| B8 | §3.3 `required_default` | `required_default=True` | `OperationSpec` 没有 `required_default` 字段，该属性在 `CanonicalNode.required` 上 | **多实现**——文档虚构了不存在的字段 |

## 3.3 几何内核偏差

| # | 文档位置 | 文档内容 | 实际代码 | 偏差类型 |
|---|---------|---------|---------|---------|
| B9 | §4.1 `fuzzy_fuse_shapes` | `BRepAlgoAPI_Fuse(a_shape, b_shape)` 直接构造 | OCP 7.7+ `BRepAlgoAPI_Fuse` 标准用法是先 `BRepAlgoAPI_Fuse()` 空构造再 `.SetArguments()` + `.SetTools()` + `.Build()` | **实现偏差**——文档的 API 用法在部分 OCP 版本可能不可用 |
| B10 | §4.1 `heal_shape` | `ShapeFix_Shape(shape); fixer.Perform()` | `ShapeFix_Shape` 构造函数不接受 `TopoDS_Shape` 直接参数，需要用 `.Init(shape)` 或 `ShapeFix_Shape().Init(shape)` | **实现偏差**——API 签名错误 |
| B11 | §4.2 `native_loft_sections` | `BRepOffsetAPI_ThruSections(True, ruled, 1e-6)` | 参数正确但缺少关键步骤：需要在 AddWire 之前检查 wire 的 orientation 一致性 | **少实现**——异拓扑截面 wire 方向不一致会导致扭曲 |
| B12 | §4.3 `make_compound` | `BRep_Builder(); builder.MakeCompound(compound)` | API 使用正确但缺少 `TopoDS_Compound` 的正确创建方式——需要 `TopoDS_Compound()` 空构造 | **少实现**——`TopoDS_Compound()` 构造函数调用方式依赖于 SWIG 绑定细节 |

## 3.4 Validation 偏差

| # | 文档位置 | 文档内容 | 实际代码 | 偏差类型 |
|---|---------|---------|---------|---------|
| B13 | §5.1 `validate_root_terminal` | `issues.append({"code": "ROOT_NOT_TERMINAL_SOLID", ...})` | 系统所有 validator 返回 `ValidationIssue` Pydantic 模型，不是裸 dict | **实现相悖**——使用裸 dict 破坏验证系统类型一致性 |
| B14 | §5.2 `validate_hole_semantics` | `issues.append({"code": "LEGACY_SIDE_HOLE_REQUIRES_3D_POSITION", ...})` | 同上——应该用 `ValidationIssue(stage=..., code=..., ...)` | **实现相悖** |
| B15 | §5.3 `GeometryPostcheckResult` | 定义为 `@dataclass` | 系统中类似结构 `ValidationReport` 使用 Pydantic `BaseModel` | **风格不一致**——dataclass 缺乏 Pydantic 的序列化和验证能力 |

## 3.5 Spatial 偏差

| # | 文档位置 | 文档内容 | 实际代码 | 偏差类型 |
|---|---------|---------|---------|---------|
| B16 | §6.1 `handle_place_component` 修改 | `target_component_id = node.params.get("target_component_id")` | 当前 `PlaceComponentParams` 没有 `target_component_id` 字段 | **少实现**——需要同步扩展 params model |
| B17 | §6.2 多组件默认启用 | 无限定条件 | `enable_spatial_frontend=False` 是默认值因为 spatial frontend 需要 LLM caller 参数 | **少实现**——文档没有说明启用需要哪些 LLM caller 配置 |
| B18 | §6.1 `ctx.placed_component_bboxes` | handler 写入此字段 | `RuntimeContext` 没有 `placed_component_bboxes` 字段 | **少实现**——需要在 context.py 中添加 |

## 3.6 Prompt 偏差

| # | 文档位置 | 文档内容 | 实际代码 | 偏差类型 |
|---|---------|---------|---------|---------|
| B19 | §7.1 System Prompt | "Never emit legacy hole parameters" | 当前 tool_schemas.py 的 `build_feature_sequence_tool_schema` 和 `build_node_params_tool_schema` 使用旧 schema | **多实现**——prompt 禁止但 tool schema 仍然暴露旧参数 |
| B20 | §7.3 Feature Sequence Prompt | "Do not emit root_node" | `FeatureSequenceDraft` 当前要求 LLM 提供 `root_node` | **实现相悖**——prompt 说不要但 schema 说必须 |

---

# 4. 分级 BUG 与优化明细

## 4.1 高危致命（P0 — 阻塞施工）

### P0-1: `OperationSpec` 构造代码无法运行

**根因**: 文档 §3.3 的 `OperationSpec(op="cut_hole_v2", op_version=1, ...)` 缺少 `dialect`, `phase`, `effects`, `handler` 四个 `OperationSpec.__init__` 的必需参数。

**风险**: 如果直接复制文档代码，Python 会立即抛出 `TypeError: OperationSpec.__init__() missing required keyword-only arguments`。

**修复代码**:
```python
# 替换文档 §3.3 全部注册代码
specs.update({
    ("cut_hole_v2", "1.0.0"): OperationSpec(
        dialect="sketch_extrude",
        op="cut_hole_v2",
        op_version="1.0.0",
        phase="primary_cut",             # 文档缺失
        input_types=["solid"],            # 文档有
        output_types=["solid"],           # 文档有
        params_model=CutHoleV2Params,     # 文档有但需验证
        effects=["cuts_material"],        # 文档缺失
        handler=handle_cut_hole_v2,       # 文档缺失
    ),
    ("drill_hole_3d", "1.0.0"): OperationSpec(
        dialect="sketch_extrude",
        op="drill_hole_3d",
        op_version="1.0.0",
        phase="primary_cut",
        input_types=["solid"],
        output_types=["solid"],
        params_model=DrillHole3DParams,
        effects=["cuts_material"],
        handler=handle_drill_hole_3d,
    ),
    # ... cut_hole_pattern_linear_v2, cut_circular_hole_pattern_v2 类似
})
```

### P0-2: `handle_place_component` 修改后 `ctx.spatial_placements` 查找不到

**根因**: 文档 §6.1 通过 `target_component_id = node.params.get("target_component_id")` 查找 placement。但 `PlaceComponentParams` 没有此字段，且 `spatial_placements` 的 key 是 `component_id`（来自 `MechanicalObjectGraphDraft`），与 `node.params` 中的任何值没有直接的关联映射。

**风险**: 修改后的 handler 永远走不进 `if target_component_id and getattr(ctx, "spatial_placements", None)` 分支，等价于未修改。

**修复代码**:
```python
def handle_place_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    
    # 优先使用 solver 计算出的 placement
    pos = None
    placements = getattr(ctx, 'spatial_placements', None)
    if placements:
        # node.component 是当前 component_id；
        # 对于 place_component，input[0] 的 producer_component 才是被放置的实体
        target_cid = None
        if node.inputs:
            target_cid = node.inputs[0].producer_component
        if target_cid and target_cid in placements:
            p = placements[target_cid]
            if not p.is_pending:
                pos = tuple(p.translation_mm)
    
    if pos is None:
        pos = node.params.get("position_mm", (0, 0, 0))
    
    # ... rest of handler
```

### P0-3: `ShapeFix_Shape` API 签名错误

**根因**: OCP 的 `ShapeFix_Shape` 默认构造函数不接受 `TopoDS_Shape` 参数。

**风险**: 文档 §4.1 `heal_shape` 函数在运行时会抛出 `TypeError`。

**修复代码**:
```python
from OCP.ShapeFix import ShapeFix_Shape

def heal_shape(shape):
    fixer = ShapeFix_Shape()
    fixer.Init(shape)          # 正确 API
    fixer.Perform()
    return fixer.Shape()
```

### P0-4: Validation 函数返回裸 dict 而非 `ValidationIssue`

**根因**: 文档 §5.1 和 §5.2 的 validator 函数返回 `list[dict]`，但系统所有 validator 返回 `ValidationReport`（其中 `issues` 是 `list[ValidationIssue]`）。

**风险**: 如果插入到 `validation/pipeline.py` 的 stage 列表，类型签名不匹配，`_run_stage_collect` 会调用失败或产生不一致的 issue 结构。

**修复代码** (validate_root_terminal):
```python
from seekflow_engineering_tools.generative_cad.validation.reports import (
    ValidationIssue, ValidationReport
)

def validate_root_terminal(subject) -> ValidationReport:
    issues: list[ValidationIssue] = []
    for comp in subject.components:
        if comp.id == "__assembly__":
            continue
        nodes = [n for n in subject.nodes if n.component == comp.id]
        solid_nodes = [
            n.id for n in nodes
            if any(o.type == "solid" for o in n.outputs)
        ]
        consumed = {
            inp.producer_node
            for n in nodes
            for inp in n.inputs
            if inp.producer_node
        }
        terminal_solids = [nid for nid in solid_nodes if nid not in consumed]
        if comp.root_node not in terminal_solids:
            issues.append(ValidationIssue(
                stage="structure",
                code="ROOT_NOT_TERMINAL_SOLID",
                message=f"Component {comp.id!r} root_node={comp.root_node!r} "
                        f"is not a terminal solid. Candidates: {terminal_solids}",
                severity="error",
                component_id=comp.id,
            ))
    return ValidationReport(
        ok=not any(i.severity == "error" for i in issues),
        stage="structure",
        issues=issues,
    )
```

## 4.2 中危隐患（P1 — 需要关注）

### P1-1: V2 孔 schema 对圆柱面语义缺失

`CanonicalFace` 的 `TOP/BOTTOM/FRONT/BACK/LEFT/RIGHT` 对 axisymmetric 零件（圆柱体）的侧面无法表达。需要在 `CanonicalFace` 中增加 `CYLINDRICAL` 或在 resolver 中支持角度参数。

### P1-2: CutHoleV2Params 的 `placement.through_mode` 访问路径不明确

文档 §3.6 handler 中有歧义：
```python
through_mode = placement.get("through_mode", "through_all") if isinstance(placement, dict) else placement.through_mode
```
当 placement 是 Pydantic 模型时，`placement.through_mode` 是 `ThroughMode` 枚举，`str()` 会得到 `"ThroughMode.THROUGH_ALL"` 而非 `"through_all"`。

### P1-3: `batch_cut` 没有退化策略

如果 300 个孔的 compound cut 失败（一次 OCCT 调用），没有 fallback 到逐孔 cut。密集孔的单次失败概率虽然低，但一旦发生就是 hard fail。

### P1-4: `enable_spatial_frontend=True` 的调用链断裂

文档 §6.2 建议默认启用但没提供 LLM caller 的默认实现。当前 `run_spatial_authoring_frontend()` 需要 5 个 caller 参数，如果 `object_graph_caller is None` 会直接跳过。启用需要：
1. 构造 DeepSeek client
2. 实现 `LlmToolCaller` 协议
3. 构建 object_graph_prompt 和 tool schema

### P1-5: 旧 `cut_hole` 与 `cut_hole_v2` 的 op 注册名冲突风险

两个 op 共存于同一个 dialect 中，但 `sketch_extrude` dialect 的 `validate_component` 中有 phase 相关的断言（exactly 1 base_solid 等），新增 ops 需要同步更新验证逻辑。

### P1-6: `draft_angle_deg` 字段已存在于 `ExtrudeRectangleParams` 中

文档 §3.2 建议修改 `bases/sketch_extrude/models.py` 但没有提及 `draft_angle_deg` 字段已存在于 `ExtrudeRectangleParams` 中（[models.py:19](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/bases/sketch_extrude/models.py#L19)）。如果文档建议重写整个 params 文件，会意外丢失该功能。

### P1-7: `resolve_face_hole_placement` 只支持 `origin_mode=face_center`

文档 §3.4 明确说"第一版只实现 face_center"，但没有在 `HolePlacementV2` 的 docstring 或 `ResolvedHolePlacement` 中标明此限制。调用方需要知道 `origin_mode` 的其他值会导致 `ValueError`。

## 4.3 低危优化（P2 — 可以后修）

### P2-1: `Axis3` 与现有 `Literal["X","Y","Z"]` 的共存

两个类型系统长期共存会增加维护成本。建议在 Phase 1 完成后统一迁移到 `Axis3`。

### P2-2: `make_cylinder_cutter` 长度计算

文档 §3.5 中 `half = length_mm / 2.0` 后 `sx = center - dx*half` 对 through_all 场景是正确的，但对 blind hole，如果 bbox 太大可能导致 cutter 穿出零件背面。

### P2-3: `handle_cut_hole_v2` 的 `required` 检查

文档 §3.6 使用 `getattr(node, "required", True)`，但 `CanonicalNode.required` 默认值是 `True`（[canonical.py:61](integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/ir/canonical.py#L61)），所以 getattr 的默认值一致但不是最佳实践——应该直接读 `node.required`。

### P2-4: 文档 §3.7 的 `strict_geometry_semantics` 上下文来源

```python
strict = getattr(ctx, "strict_geometry_semantics", True)
```
但 `RuntimeContext` 没有此属性。需要在 context.py 中添加。

### P2-5: 批量 boolean cut 缺少性能监控

300 孔 batch_cut 没有超时保护。如果个别 case 导致 OCCT 计算时间过长（>60s），应该 fallback。

### P2-6: `CutCircularHolePatternV2Params` 的方言归属

文档将其放在 sketch_extrude 下，但传统上 circular hole pattern 属于 axisymmetric（与 revolve_profile 的圆柱形基体相关）。在哪个方言中注册会影响 preflight 的 envelope check 能否正确执行。

---

# 5. 缺失内容补全

## 5.1 缺失：V1→V2 迁移兼容层

**问题**: 文档建议将旧 `cut_hole` 标记为 legacy，但没有提供从旧 prompt/旧测试数据自动升级的兼容层。

**补全方案**: 在 `auto_fixer.py` 中增加一个新的 `AutoFixCategory.SAFE_UPGRADE`：
```python
# auto_fixer.py 新增
def _fix_upgrade_legacy_hole(doc: dict) -> dict:
    """将 axis=Z + position_mm len=2 + through_all 的旧 hole 升级为 cut_hole_v2."""
    for node in doc.get("nodes", []):
        if node.get("op") != "cut_hole":
            continue
        params = node.get("params", {})
        axis = params.get("axis", "Z")
        pos = params.get("position_mm", [0,0])
        if axis == "Z" and len(pos) == 2 and params.get("through_all", True):
            node["op"] = "cut_hole_v2"
            node["params"] = {
                "diameter_mm": params["diameter_mm"],
                "placement": {
                    "target_face": "top",
                    "center_uv_mm": pos,
                    "normal_axis": "+Z",
                    "origin_mode": "face_center",
                    "through_mode": "through_all",
                }
            }
    return doc
```

## 5.2 缺失：SPATIAL_PLACEMENT_KEY_MAP

**问题**: `handle_place_component` 需要知道 component_id 如何映射到 `ctx.spatial_placements` 的 key。当前约束图使用的是 `MechanicalObjectGraphDraft.component_id`，但 composition 节点的 `inputs[0].producer_component` 来自 `CanonicalComponent.id`。

**补全方案**: 在 `constraint_resolver.py` 或 pipeline/run.py 的结果中返回映射表：
```python
# constraint_resolver.py 新增到 resolve_placements 返回值
component_id_map: dict[str, str] = {}  # canonical_id → spatial_graph_id
```

## 5.3 缺失：`handle_cut_circular_hole_pattern_v2` 完整实现

文档只定义了 schema 但没有给出 handler 实现。这是圆周孔阵列 V2 最关键的部分。

**补全骨架**:
```python
def handle_cut_circular_hole_pattern_v2(node, ctx) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params
    dia = float(p["hole_dia_mm"])
    placement = p["placement"]
    
    from ...geometry_utils.hole_placement import resolve_face_hole_placement
    from ...geometry_utils.ocp_cylinder import make_cylinder_cutter
    
    bb = body.val().BoundingBox()
    cutters = []
    for k in range(placement.count):
        angle = math.radians(placement.start_angle_deg + k * placement.angular_span_deg / max(placement.count - 1, 1))
        # 在 face UV 坐标系中计算每个孔的中心
        u = placement.center_uv_mm[0] + (placement.pcd_mm / 2.0) * math.cos(angle)
        v = placement.center_uv_mm[1] + (placement.pcd_mm / 2.0) * math.sin(angle)
        # ... 调用 resolve_face_hole_placement 和 make_cylinder_cutter
    
    from ...geometry_utils.boolean_batch import batch_cut
    result = batch_cut(body, cutters)
    return {"body": _store_solid(node, ctx, result)}
```

---

# 6. 最终版标准化投产施工指导书

## 6.1 修订后实施路线

```
Phase 0 (1天): 安全网 — 不改生成能力
  ├─ P0-4: validate_root_terminal + validate_hole_semantics (用 ValidationIssue)
  ├─ P0-3: heal_shape API 修正
  ├─ Geometry postcondition gate (volume>0, n_solids check)
  ├─ required feature hard fail (修改 _degrade 逻辑)
  └─ 回归: g22/g26/g30 验证 fail→hard fail

Phase 1 (2天): 孔系统重构 — 先建模型再写 handler
  ├─ 1a: ir/geometry_semantics.py (纯数据模型: CanonicalFace, Axis3, HolePlacementV2, ...)
  ├─ 1b: 修复文档 P0-1 (OperationSpec 缺失参数)
  ├─ 1c: dialects/geometry_utils/hole_placement.py (解析逻辑)
  ├─ 1d: dialects/geometry_utils/ocp_cylinder.py
  ├─ 1e: dialects/geometry_utils/boolean_batch.py
  ├─ 1f: sketch_extrude dialect 注册新 ops + handler 实现
  ├─ 1g: P2-6: circular pattern 的方言归属决策
  └─ 验收: top/front/right face holes + linear pattern + required hard fail

Phase 2 (1.5天): 空间闭环
  ├─ 2a: 修复 P0-2 (handle_place_component 正确读取 ctx.spatial_placements)
  ├─ 2b: PlaceComponentParams 增加 component_id 字段
  ├─ 2c: RuntimeContext 增加 placed_component_bboxes 字段
  ├─ 2d: 多组件默认启用 spatial frontend
  └─ 验收: 多组件 placement 确定性求解 → audit 通过

Phase 3 (2天): 几何增强
  ├─ 3a: 修复 P0-3 (ShapeFix_Shape API)
  ├─ 3b: fuzzy_fuse 替换 translate-fuse
  ├─ 3c: native loft (OCP ThruSections)
  ├─ 3d: boolean_batch 退化策略 (P1-3)
  └─ 验收: g8/g23 loft + boolean union with fuzzy fuse

Phase 4 (1.5天): Prompt 系统
  ├─ 4a: tool_schemas.py 生成 V2 schema (P1-5 修复)
  ├─ 4b: context_builder.py 隐藏/降权旧 ops
  ├─ 4c: prompts 替换
  └─ 验收: LLM 不输出 legacy hole → schema validation 通过
```

## 6.2 修复后的关键代码补丁

### 补丁 1: `handle_place_component` 完整修复 (替换文档 §6.1)

```python
def handle_place_component(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)

    # v6.3: 优先使用 ConstraintResolver 计算出的 placement
    pos = None
    placements = getattr(ctx, 'spatial_placements', None)
    if placements:
        # 被放置的 component_id 来自第一个 input
        target_cid = node.inputs[0].producer_component if node.inputs else None
        if target_cid and target_cid in placements:
            p = placements[target_cid]
            if not p.is_pending:
                pos = tuple(p.translation_mm)
                if p.rotation_deg_xyz and any(v != 0 for v in p.rotation_deg_xyz):
                    ctx.warnings.append(
                        f"place_component on '{node.id}': rotation from solver ignored "
                        f"(rotation not yet supported in place_component handler)"
                    )

    if pos is None:
        pos = tuple(node.params.get("position_mm", (0, 0, 0)))

    if not isinstance(pos, (list, tuple)) or len(pos) != 3:
        raise ValueError(f"place_component requires 3D position, got {pos}")

    pos_f = tuple(float(v) for v in pos)

    try:
        placed = body.translate(pos_f)
        ctx.bind_node_output(node.id, "body",
            _store_solid(node, ctx, placed))
        return {"body": ctx.resolve_node_output(node.id, "body")}
    except Exception as exc:
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required place_component failed on '{node.id}': {exc}"
            ) from exc
        return {"body": _degraded_store(node, ctx, body, "place_component")}
```

### 补丁 2: `handle_cut_hole_v2` 修复 (替换文档 §3.6)

```python
def handle_cut_hole_v2(node: CanonicalNode, ctx: RuntimeContext) -> dict[str, str]:
    body = resolve_input_object(node, ctx, 0)
    p = node.typed_params if node.typed_params else node.params

    dia = float(p.get("diameter_mm", 0))
    if dia <= 0:
        raise ValueError("cut_hole_v2 requires positive diameter_mm")

    placement_raw = p.get("placement")
    if placement_raw is None:
        raise ValueError("cut_hole_v2 requires placement")

    # 统一为 HolePlacementV2 模型
    from seekflow_engineering_tools.generative_cad.ir.geometry_semantics import (
        HolePlacementV2,
    )
    if isinstance(placement_raw, dict):
        placement = HolePlacementV2.model_validate(placement_raw)
    else:
        placement = placement_raw

    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.hole_placement import (
        resolve_face_hole_placement,
    )
    from seekflow_engineering_tools.generative_cad.dialects.geometry_utils.ocp_cylinder import (
        make_cylinder_cutter,
    )

    bb = body.val().BoundingBox()
    resolved = resolve_face_hole_placement(placement, bb)

    if placement.through_mode == "blind":
        if placement.depth_mm is None:
            raise ValueError("blind hole requires depth_mm")
        length = placement.depth_mm
    else:
        length = max(bb.xlen, bb.ylen, bb.zlen) + 20.0

    cutter = make_cylinder_cutter(
        center_xyz=resolved.center_xyz,
        direction_xyz=resolved.direction_xyz,
        radius_mm=dia / 2.0,
        length_mm=length,
    )

    try:
        result = body.cut(cutter)
    except Exception as exc:
        # 文档原则C: required特征必须hard fail
        if getattr(node, "required", True):
            raise RuntimeError(
                f"required cut_hole_v2 failed on '{node.id}': {exc}"
            ) from exc
        return {"body": _degrade(node, ctx, body, "cut_hole_v2")}

    return {"body": _store_solid(node, ctx, result)}
```

### 补丁 3: `heal_shape` 修复 (替换文档 §4.1)

```python
from OCP.ShapeFix import ShapeFix_Shape

def heal_shape(shape):
    """修复 B-Rep 拓扑错误。不改变几何形状。"""
    fixer = ShapeFix_Shape()
    fixer.Init(shape)  # 正确 API：先 Init 再 Perform
    fixer.Perform()
    return fixer.Shape()
```

### 补丁 4: 新的 `validation/root_terminal.py` (替换文档 §5.1)

```python
"""Root terminal validator — 确保 root_node 指向真正的终端 solid。"""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.validation.reports import (
    ValidationIssue,
    ValidationReport,
)


def validate_root_terminal(subject) -> ValidationReport:
    """检查每个 component 的 root_node 指向不被任何后续操作消费的 terminal solid。
    
    这是防止 g14 类问题的关键验证：
    - root_node 指向 base 但后续有孔/槽/阵列 → 最终输出不包含这些特征
    """
    issues: list[ValidationIssue] = []

    for comp in subject.components:
        cid = comp.id
        if cid == "__assembly__":
            continue

        nodes = [n for n in subject.nodes if n.component == cid]
        if not nodes:
            continue

        solid_producers = [
            n.id for n in nodes
            if any(o.type == "solid" for o in n.outputs)
        ]

        consumed = set()
        for n in nodes:
            for inp in n.inputs:
                if inp.producer_node:
                    consumed.add(inp.producer_node)

        terminal_solids = [nid for nid in solid_producers if nid not in consumed]
        root = comp.root_node

        if root and terminal_solids and root not in terminal_solids:
            issues.append(ValidationIssue(
                stage="structure",
                code="ROOT_NOT_TERMINAL_SOLID",
                message=(
                    f"Component '{cid}' root_node='{root}' is not a terminal solid. "
                    f"It is consumed by downstream operations. "
                    f"Terminal candidates: {terminal_solids}"
                ),
                severity="error",
                component_id=cid,
            ))

    return ValidationReport(
        ok=not any(i.severity == "error" for i in issues),
        stage="structure",
        issues=issues,
    )
```

## 6.3 施工检查清单

实施时每完成一个 commit 必须验证：

- [ ] 所有 Pydantic 模型 `extra="forbid"`
- [ ] 所有 OperationSpec 注册包含 `dialect, phase, effects, handler`
- [ ] 所有新 validator 返回 `ValidationReport`（不是裸 dict）
- [ ] 旧测试（35 case full regression）继续通过
- [ ] 新 hole V2 在 top/front/right 三个面正确钻孔
- [ ] required feature 失败 → hard fail（不是 silent skip）
- [ ] boolean_union 不再使用 translate 后的 fake fuse
- [ ] `handle_place_component` 消费 `ctx.spatial_placements`
- [ ] 多组件装配的 spatial_contract 闭环验证

---

**审计完成时间**: 2026-06-04
**审计结论**: 文档方向正确，核心诊断精准。修正 P0-1 至 P0-4 后可按修订后路线图分批施工。不可照搬原文的 Commit 1→7 顺序。
