# SeekFlow Generative CAD-IR — 审计问题修复清单

**审计日期**: 2026-05-31
**审计标准**: `docs/target.md` 全部 15 条顶级要求

---

## 总览

| 优先级 | 数量 | 预计影响 |
|--------|------|----------|
| P0 CRITICAL | 4 | 数据完整性破坏 / 诊断信息丢失 |
| P1 HIGH | 5 | 静默数据错误 / 代码健康度 |
| P2 MEDIUM | 10 | 架构收口 / 死代码清理 |
| P3 LOW | 6 | 长期优化 / 测试补齐 |

---

## P0 — CRITICAL（数据完整性 / 可诊断性）

### P0-1: `pipeline/run.py:184` — runner 顶层 catch-all 吞噬 traceback

**文件**: `src/seekflow_engineering_tools/generative_cad/pipeline/run.py`
**行号**: 122-191（`run_canonical_gcad` 函数体）

**当前代码**:
```python
try:
    _run_components(canonical, ctx)
    ...  # postconditions, export, metadata, artifact
    return GcadRunResult(ok=True, ...)
except Exception as exc:
    return GcadRunResult(
        ok=False,
        error=str(exc),   # ← traceback 丢失
        ...
    )
```

**问题**: 任何 CadQuery 内核崩溃、几何错误、内存耗尽都被扁平化为 `str(exc)`，生产调试时完全丢失堆栈。

**修复要求**:
- 在 `return` 前添加 `import traceback; ctx.warnings.append(traceback.format_exc())`
- 或使用 `logging.exception("run_canonical_gcad failed")`
- 确保 error 字段包含 traceback 信息而非仅 `str(exc)`

---

### P0-2: `bases/sketch_extrude/runner.py:409` — `_op_apply_safe_fillet` 静默返回原体

**文件**: `src/seekflow_engineering_tools/generative_cad/bases/sketch_extrude/runner.py`
**行号**: ~409

**当前代码**:
```python
def _op_apply_safe_fillet(body, params):
    try:
        return body.fillet(r)
    except Exception:    # ← 捕获一切
        return body      # ← 静默返回原体
```

**问题**: CadQuery fillet 因几何错误失败时，原体被静默返回。无 warning，无 degraded feature 记录。下游 STEP 文件缺失 fillet 且无任何迹象。

**修复要求**:
- 仅捕获 CadQuery 几何特定异常类型
- 记录为 degraded feature：`ctx.degraded_features.append({"node_id": ..., "reason": "fillet failed: ..."})`
- 对其他异常重新 `raise`

---

### P0-3: `bases/sketch_extrude/runner.py:419` — `_op_apply_safe_chamfer` 静默返回原体

**文件**: 同上
**行号**: ~419
**问题**: 与 P0-2 相同模式
**修复要求**: 与 P0-2 相同

---

### P0-4: `bases/axisymmetric/runner.py:506` — `_op_apply_safe_chamfer` 静默返回原体

**文件**: `src/seekflow_engineering_tools/generative_cad/bases/axisymmetric/runner.py`
**行号**: ~504-508
**问题**: 与 P0-2/3 相同模式
**修复要求**: 与 P0-2 相同

---

## P1 — HIGH（静默数据错误 / 代码健康度）

### P1-1: `runtime/cadquery_runtime.py:67` — `_count_solids` 返回虚假值 1

**文件**: `src/seekflow_engineering_tools/generative_cad/runtime/cadquery_runtime.py`
**行号**: ~54-68

**当前代码**:
```python
def _count_solids(solid_obj) -> int:
    try:
        ...
        return 1
    except Exception:
        return 1   # ← 任何错误都返回 1
```

**问题**: 任何错误都被吞没并返回 `1`。这会绕过 `builder.py` 中 `expected_body_count` 的对比检查，以虚假数据通过 validation。

**修复要求**:
- 记录 warning：`warnings.warn(f"_count_solids failed: {exc}")` 后返回 `None`
- 或仅捕获 `AttributeError`/`TypeError`，其他异常重新 `raise`

---

### P1-2: `pipeline/metadata_v3.py:100` — `_compute_step_sha256` 异常 → `"sha256:pending"`

**文件**: `src/seekflow_engineering_tools/generative_cad/pipeline/metadata_v3.py`
**行号**: ~97-101

**当前代码**:
```python
def _compute_step_sha256(step_path: Path) -> str:
    try:
        return "sha256:" + hashlib.sha256(step_path.read_bytes()).hexdigest()
    except Exception:
        return "sha256:pending"   # ← 磁盘错误也被标记为 pending
```

**问题**: 真正的磁盘 I/O 错误（权限、损坏）被标注为 `"sha256:pending"` 而非错误。

**修复要求**:
- 仅捕获 `FileNotFoundError` / `PermissionError` / `OSError`
- 其他异常重新 `raise` 或记录为明确的 error sentinel（如 `"sha256:error"`）

---

### P1-3: `pipeline/artifact.py:15` — `_sha256_file` 异常 → 空字符串

**文件**: `src/seekflow_engineering_tools/generative_cad/pipeline/artifact.py`
**行号**: ~12-16

**当前代码**:
```python
def _sha256_file(path: Path) -> str:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return ""   # ← 磁盘错误变为空字符串
```

**问题**: 空字符串使下游无法区分"未计算"和"计算失败"。

**修复要求**:
- 仅捕获 `FileNotFoundError` / `PermissionError` / `OSError`
- 其他异常重新 `raise`

---

### P1-4: `runtime/cadquery_runtime.py:44` — `compute_bbox_mm` 异常 → `None`

**文件**: `src/seekflow_engineering_tools/generative_cad/runtime/cadquery_runtime.py`
**行号**: ~37-45

**问题**: 任何错误（包括 CadQuery 崩溃）都返回 `None`，下游 bbox 校验被静默跳过。

**修复要求**:
- 记录 warning 或仅捕获几何特定异常
- 返回包含错误信息的 dict 而非裸 `None`

---

### P1-5: `runtime/cadquery_runtime.py:50` — `count_bodies` 异常 → `None`

**文件**: 同上，行 ~47-51
**问题**: 与 P1-4 相同模式
**修复要求**: 与 P1-4 相同

---

## P2 — MEDIUM（架构收口 / 死代码清理）

### P2-1: 清理确认死模块（4 个）

以下文件**从未被任何代码导入**，应删除：

| 文件 | 内容 | 建议 |
|------|------|------|
| `errors.py` | 5 个异常类（`GenerativeCadError` 等） | 删除（如需要异常层次则后续在 `runtime/` 中重建） |
| `ir/safety.py` | `safety_all_true()` 函数 | 删除（功能已被 `RawSafety.all_true()` 和 `validation/safety.py` 覆盖） |
| `runtime/cadquery_helpers.py` | 5 个 helper 函数 | 删除（handlers 直接使用 `handles.py` + `resolve.py`） |
| `pipeline/import_gate_models.py` | `ImportGateResult` Pydantic 模型 | 保留文件，但应在 `import_artifact.py` 中使用该模型返回 |

---

### P2-2: 清理 shadow 模块（2 个）

以下 `.py` 文件被同名包目录 shadow，永远不可达：

| 文件 | 状态 | 建议 |
|------|------|------|
| `ir.py` | 被 `ir/` 目录 shadow | 可删除（legacy 访问走 `ir/__init__.py`） |
| `validation.py` | 被 `validation/` 目录 shadow | 可删除（legacy 访问走 `legacy/validation_v01.py`） |

---

### P2-3: 清理 stale 重复文件（2 个）

| 文件 | 问题 | 建议 |
|------|------|------|
| `skills/generic_mechanical_skill.md` | 内容已移至 `skills/domain/` | 删除 |
| `skills/turbomachinery_reference_skill.md` | 同上 | 删除 |

---

### P2-4: 标注"仅测试使用"的 legacy wrappers（4 个）

以下文件无 `SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS` 屏障，但仅被测试导入：

| 文件 | 建议 |
|------|------|
| `artifact.py` | 添加 barrier 或删除 |
| `graph_validation.py` | 添加 barrier 或删除 |
| `metadata.py` | 添加 barrier 或删除 |
| `preflight.py` | 添加 barrier 或删除 |

---

### P2-5: `skills/` 包 — 生产接入或标注

`skills/orchestrator.py` 定义了完整的 LLM 编排逻辑（`build_level1_routing_prompt`、`build_level2_authoring_prompt`）但生产代码从不调用。prompts 字符串只被测试文件直接导入。

**建议**：
- 方案A：接入生产 — 在 `tools.py` 中注册 Level-1/Level-2 prompt 构建工具
- 方案B：标注为 WIP — 在文件头部添加 `# WIP: not yet wired into production` 注释

---

### P2-6: `repair/` 包 — 生产接入或标注

`repair/governor.py` 定义了 `can_repair_v2()`、`update_repair_state_v2()` 但生产代码无调用。

**建议**：
- 方案A：接入生产 — 在 builder 或 validator 中集成 repair loop
- 方案B：标注为 WIP — 同 P2-5

---

### P2-7: `compatibility/legacy_spec_adapter.py` — 接入或标注

**当前状态**：仅在 `builder.py` 第 44/64 行的 error message 中被引用为字符串，从未 import 或调用。

**建议**：在 error message 旁添加真实的 `import` + 调用路径，或标注为 external-only API。

---

### P2-8: `dialects/{axisymmetric,sketch_extrude}/dialect.py` — `KeyError: pass` 加注释

**文件**: 
- `dialects/axisymmetric/dialect.py:238`
- `dialects/sketch_extrude/dialect.py:217`

**当前代码**:
```python
try:
    ctx.bind_component_output(component.id, o.name,
        ctx.resolve_node_output(root.id, o.name))
except KeyError:
    pass   # ← 静默跳过
```

**问题**: root node 未产生预期 output 时静默跳过。修复理由是 `postconditions.py` 提供了冗余检查，但无注释说明。

**修复要求**: 添加注释 `# KeyError caught: postconditions.py independently validates root outputs`

---

### P2-9: 可选 node degradation — 防止吞噬 `BaseException`

**文件**: 三个 dialect 的 `run_component()` 方法
**行号**: `axisymmetric/dialect.py:223`, `sketch_extrude/dialect.py:202`, `composition/dialect.py:209`

**当前代码**:
```python
except Exception as exc:
    if not node.required and ...:
        ...   # degrade
        continue
    raise
```

**问题**: `KeyboardInterrupt` / `SystemExit` 会被当作 degradation 处理。

**修复要求**: 添加 `except BaseException: raise` 在 `except Exception` 之前。

---

### P2-10: `ir/legacy.py` 无条件导入 — 影响 production import

**文件**: `ir/__init__.py`
**行号**: ~7

**当前代码**:
```python
from seekflow_engineering_tools.generative_cad.ir.legacy import (
    FeatureGraph, FeatureGraphNode, GenerativeCADSpec, ...
)
```

**问题**: `ir/__init__.py` 被 production 代码 import 时会无条件导入 legacy v0.1 模型。虽然这不会导致 ImportError（legacy/__init__ 无 barrier），但存在命名空间污染。

**建议**: 添加 `SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS` 条件检查，或将这些 re-export 移到独立的 `ir/legacy_compat.py`。

---

## P3 — LOW（长期优化 / 测试补齐）

### P3-1: Mutation tests 缺失

target.md §6.2 要求对以下 16 种破坏输入进行验证。当前部分有行为测试覆盖，部分仅靠源码字符串测试：

| 破坏输入 | 当前测试状态 | 需补充 |
|----------|-------------|--------|
| remove safety | ✅ 行为测试 | — |
| set safety false | ✅ 行为测试 | — |
| remove constraints | ✅ 行为测试 | — |
| unknown dialect | ✅ 行为测试 | — |
| unknown op | ✅ 行为测试 | — |
| wrong op_version | ✅ | — |
| wrong phase | ✅ | — |
| cycle graph | ✅ | — |
| missing input | ✅ | — |
| output type mismatch | ✅ 行为测试 | — |
| handler returns extra output | ✅ 行为测试 | — |
| handler returns missing output | ✅ 行为测试 | — |
| handler returns wrong handle type | ✅ 行为测试 | — |
| metadata missing stage | ✅ 行为测试 | — |
| contract_hash mismatch | ✅ 行为测试 | — |
| step_hash mismatch | ✅ 行为测试 | — |
| repair patch modifies safety | ⚠️ 仅 prompt 字符串检查 | 需行为测试 |
| repair patch modifies op_version | ⚠️ 仅 prompt 字符串检查 | 需行为测试 |

---

### P3-2: Golden corpus 缺失

target.md §6.3 要求建立 6 个 golden fixture：

| Golden fixture | 当前状态 | 需补充 |
|---------------|----------|--------|
| `golden_axisymmetric_minimal` | ✅ fixtures 中有 `axisymmetric_minimal.json` | — |
| `golden_axisymmetric_with_holes` | ❌ 缺失 | 需创建 |
| `golden_sketch_extrude_plate` | ✅ fixtures 中有 `sketch_extrude_minimal.json` | — |
| `golden_composition_two_components` | ✅ fixtures 中有 `composed_disk_with_lugs.json` | — |
| `golden_repair_success` | ❌ 缺失 | 需创建 |
| `golden_repair_give_up` | ❌ 缺失 | 需创建 |

---

### P3-3: Contract evolution tests 缺失

target.md §6.4 要求验证"新增 op 参数不改核心编译器"：

| 测试 | 状态 |
|------|------|
| 新增 op 参数 → 只改 ParamsModel + Handler | ❌ 缺失 |
| Core IR 不变 | ❌ 缺失 |
| Core Validator 不变 | ❌ 缺失 |
| metadata 记录新 op_version | ❌ 缺失 |
| 旧 op_version 仍能 validate | ❌ 缺失 |
| 未知 op_version fail | ❌ 缺失 |

---

### P3-4: Prompt 版本化

target.md §5 要求 prompt 必须版本化。当前 prompt 字符串无 `prompt_version` 字段。

**建议**：在 `skills/prompts.py` 中添加：
```python
PROMPT_VERSION_LEVEL1 = "level1_routing_v2"
PROMPT_VERSION_LEVEL2 = "level2_authoring_v2"
PROMPT_VERSION_REPAIR = "repair_patch_v3"
```

---

### P3-5: GeometryRuntime 错误类型缺失

target.md §7.2 要求异常必须结构化。当前 CadQueryRuntime 没有专用异常类型。

**建议**：在 `runtime/` 下新增 `runtime/runtime_errors.py`，定义：
```python
class GeometryRuntimeError(Exception): ...
class StepExportError(GeometryRuntimeError): ...
class SolidInspectionError(GeometryRuntimeError): ...
```

---

### P3-6: 新增能力扩展不改核心编译器的测试缺失

target.md §2.2 要求验证"新增 dialect 只注册 + 不改核心编译器"。当前无此测试。

**建议**：新增 `test_contract_evolution.py`，验证注册新 dialect 后 `ir/raw.py`、`validation/graph.py`、`pipeline/run.py` 的 hash 不变。

---

## 修复优先级时间线建议

```
Week 1 (P0 全部):
  Day 1: P0-1 (run.py traceback)
  Day 2: P0-2 + P0-3 (sketch_extrude safe_fillet/chamfer)
  Day 3: P0-4 (axisymmetric safe_chamfer)
  Day 4: 回归测试 + review

Week 2 (P1 全部):
  Day 1-2: P1-1 ~ P1-5 (cadquery_runtime + hash 函数)
  Day 3: 回归测试 + review

Week 3 (P2 选择):
  Day 1: P2-1 ~ P2-3 (死代码清理)
  Day 2: P2-4 ~ P2-7 (legacy 标注)
  Day 3: P2-8 ~ P2-10 (小修复)

Week 4+ (P3 按需):
  P3-1: Mutation tests（按 target.md §6.2 清单）
  P3-2: Golden corpus
  P3-3: Contract evolution tests
  P3-4: Prompt 版本化
```

---

## 验证命令

全部修复完成后运行：

```bash
# 全部 generative_cad 测试
pytest tests/generative_cad/ -q

# 全部测试（含 legacy + primitive）
pytest tests/ -q

# 静态编译检查
python -m compileall integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad

# 确认无 production legacy imports
pytest tests/generative_cad/test_no_production_legacy_imports.py -q
pytest tests/generative_cad/test_vnext_legacy_import_barrier.py -q
```
