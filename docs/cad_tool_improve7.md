
---

# SeekFlow Engineering 工业级闭环修复执行文档

## 0. 修复目标

Claude Code 的目标不是继续堆功能，而是把当前仓库修成一个**可编译、可测试、可验收、fail-closed** 的工业级链路：

```text
Natural Language
→ engineering_validate_cad_ir
→ CAD-IR normalize
→ Capability Router
→ engineering_build_cad_model
→ Build Planner
→ CadQuery / CQ_Gears canonical STEP
→ metadata.json
→ Geometry Inspection
→ Mechanical Validation
→ SolidWorks / NX import STEP and save native
→ EngineeringActionResult
→ demo_full_chain / pytest 回归验收
```

核心原则：

```text
1. LLM 不直接生成 SolidWorks COM / VBS / NXOpen 齿形代码。
2. involute_spur_gear 必须走 deterministic primitive。
3. CadQuery / CQ_Gears / OpenCascade 是 canonical geometry source。
4. SolidWorks / NX 只导入 canonical STEP，不重新生成复杂齿形。
5. metadata、inspection、mechanical validation 缺失时不得 ok=True。
6. demo_full_chain 必须验收统一入口，而不是绕过主链路。
```

当前 capability registry 已经正确声明了 `solidworks2025`、`nx12`、`cadquery` 的 `stable_primitives` 和 `primitive_strategy`；SolidWorks/NX 对 `involute_spur_gear` 使用 `cadquery_step_import`，CadQuery 使用 `native_cadquery_primitive`。这是正确方向。([GitHub][1])

---

# 1. P0：先修源码格式与可执行性

## 1.1 当前风险

多个 raw 文件显示为“极少物理行 + 代码被压成一行”的状态，例如：

```python
"""NX 12.0 SeekFlow tools.""" from __future__ import annotations ...
```

`nx/tools.py`、`cadquery_backend/builder.py`、`ansys/tools.py` 都显示类似情况。([GitHub][2])

如果实际仓库里也是这样，那么 Python 会直接语法错误。比如：

```python
"""docstring.""" from __future__ import annotations
```

不是合法 Python。

## 1.2 Claude Code 必须先执行

```bash
cd integrations/engineering_tools

python -m compileall src demo_full_chain.py
python -m pytest
```

如果 `compileall` 失败，**先修格式，不要修业务逻辑**。

## 1.3 修复方式

如果确实是文件被压成单行，Claude Code 不要尝试“局部修一两个换行”，而应该按模块重新整理这些文件：

```text
src/seekflow_engineering_tools/natural_language/tools.py
src/seekflow_engineering_tools/natural_language/backend_builders.py
src/seekflow_engineering_tools/capabilities/registry.py
src/seekflow_engineering_tools/cadquery_backend/builder.py
src/seekflow_engineering_tools/mechanical_validation/gear_validation.py
src/seekflow_engineering_tools/nx/tools.py
src/seekflow_engineering_tools/nx/nx_bridge_bootstrap.py
src/seekflow_engineering_tools/ansys/tools.py
src/seekflow_engineering_tools/solidworks/tools.py
demo_full_chain.py
pyproject.toml
```

必须保证：

```python
"""Module docstring."""
from __future__ import annotations

import ...
```

而不是：

```python
"""Module docstring.""" from __future__ import annotations import ...
```

## 1.4 验收

```bash
python -m compileall src demo_full_chain.py
```

必须全绿。否则任何架构修复都不算完成。

---

# 2. P0：修复 demo_full_chain.py，不能绕过统一入口

## 2.1 当前问题

当前 `demo_full_chain.py` 已经有 `--case`、`--backend`、`--json-report`、`--allow-step-import`，形式上接近 CI 脚本。但代码里直接调用了：

```python
build_cadquery_from_cad_ir(...)
build_solidworks_from_canonical_step(...)
build_nx_from_canonical_step(...)
choose_backend(...)
CADPartSpec.model_validate(...)
```

而没有真正调用：

```python
engineering_validate_cad_ir(...)
engineering_build_cad_model(...)
```

也就是说，demo 没有验证最终 agent 应该走的统一入口。([GitHub][3])

更严重的是，它多处使用：

```python
validation.get("ok", True)
mv.get("ok", True)
mech_val.get("ok", True)
```

这意味着 validation 或 mechanical_validation 缺失时，demo 会默认认为成功。([GitHub][3])

这违反 fail-closed 原则。

## 2.2 必须修改

### 2.2.1 demo 必须走统一入口

每个 case 都应该走：

```python
from seekflow_engineering_tools.natural_language.tools import (
    engineering_validate_cad_ir,
    engineering_build_cad_model,
)
```

而不是直接调用低层 builder。

推荐结构：

```python
def run_case(case: str, backend: str, output_root: Path, allow_step_import: bool) -> dict:
    spec_dict = make_case_spec(case, backend)

    validate_result = engineering_validate_cad_ir(spec_dict)
    stage_validate = validate_result["ok"]

    if not validate_result["ok"]:
        return failed_report(...)

    normalized_spec = validate_result["metrics"]["normalized_spec"]

    build_result = engineering_build_cad_model(
        spec=normalized_spec,
        backend=backend,
        out_step=str(output_root / "models" / f"{case}.step"),
        allow_step_import=allow_step_import,
    )

    extract inspection / mechanical_validation from build_result
```

如果当前 `engineering_build_cad_model` 还没有 `allow_step_import` 参数，Claude Code 应该加上，或在 demo 层用明确条件拒绝 SW/NX gear：

```python
if backend in {"solidworks2025", "nx12"} and case == "involute_spur_gear" and not allow_step_import:
    fail
```

### 2.2.2 缺失 validation 必须失败

禁止：

```python
validation.get("ok", True)
mv.get("ok", True)
```

改成：

```python
def require_stage_ok(container: dict, key: str) -> tuple[bool, str | None]:
    if key not in container:
        return False, f"Missing required stage result: {key}"
    if container[key].get("ok") is not True:
        return False, container[key].get("error") or f"{key} failed"
    return True, None
```

对 gear case：

```python
metrics = build_result.get("metrics", {})

validation = metrics.get("validation")
if not validation:
    _fail(report, "inspect", "Build result missing metrics.validation")
else:
    _stage(report, "inspect", ok=validation.get("ok") is True)

mechanical = metrics.get("mechanical_validation")
if not mechanical:
    _fail(report, "mechanical_validate", "Build result missing metrics.mechanical_validation")
else:
    _stage(report, "mechanical_validate", ok=mechanical.get("ok") is True)
```

对 box/flanged_hub 这种非 primitive case，可以允许：

```json
"mechanical_validate": {
  "ok": true,
  "skipped": true,
  "reason": "No mechanical primitive features."
}
```

但必须显式 skipped，不能默认成功。

### 2.2.3 metadata 读取失败必须失败

当前 demo 对 metadata 读取失败存在静默 `pass` 的逻辑。必须改成：

```python
try:
    sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
except Exception as exc:
    _fail(report, "mechanical_validate", f"Failed to read metadata sidecar: {exc}")
    return report
```

gear report 必须包含：

```json
{
  "metrics": {
    "kernel_used": "cq_gears",
    "reference_dimensions": {
      "pitch_diameter_mm": 48.0,
      "base_diameter_mm": "...",
      "outer_diameter_mm": 52.0,
      "root_diameter_mm": "..."
    }
  }
}
```

任何一个 key 缺失都应该失败。

### 2.2.4 demo report stage 固定

每个 case 必须输出：

```json
{
  "stages": {
    "validate_cad_ir": {"ok": true},
    "normalize_primitives": {"ok": true},
    "choose_backend": {"ok": true},
    "build": {"ok": true},
    "inspect": {"ok": true},
    "mechanical_validate": {"ok": true}
  }
}
```

### 2.2.5 `--case all` 必须 fail-fast 或最终失败退出

保留：

```python
if not full_report["overall_ok"]:
    sys.exit(1)
```

并确保 `--case all` 也写 `--json-report`。

## 2.3 必须新增测试

新增或修改：

```text
tests/test_demo_full_chain_gear.py
```

必须覆盖：

```python
def test_demo_uses_unified_entrypoints(monkeypatch):
    # monkeypatch engineering_validate_cad_ir 和 engineering_build_cad_model
    # 断言 demo 调用了它们，而不是直接调用 build_cadquery_from_cad_ir


def test_demo_missing_validation_fails(monkeypatch, tmp_path):
    # build_result ok=True 但 metrics 缺 validation
    # demo 必须 exit nonzero 或 report overall_ok=False


def test_demo_missing_mechanical_validation_fails_for_gear(monkeypatch, tmp_path):
    # gear build_result ok=True 但缺 mechanical_validation
    # 必须失败


def test_demo_metadata_read_failure_fails(monkeypatch, tmp_path):
    # 写坏 metadata.json，demo 不能 pass


def test_demo_case_all_exits_nonzero_if_any_case_fails(tmp_path):
    # 任一 case fail，--case all 必须 exit 1
```

---

# 3. P0：确认并锁死 NX / UG 链路

## 3.1 当前状态

当前 NX 侧比之前进步明显：

* `nx/tools.py` 已经注册 `nx_import_step_as_prt`；
* 它会检查 input STEP 存在且非空；
* 它会 submit `import_step_as_prt`；
* job result `ok=False` 会失败；
* `.prt` 不存在或为空也会失败。([GitHub][2])

`nx_bridge_bootstrap.py` 当前也已经包含：

```python
def import_step_as_prt(...)
```

并且 `ACTION_HANDLERS` 已经注册：

```python
"import_step_as_prt": import_step_as_prt
```

`process_one_job` 也已经读取：

```python
handler_ok = result_payload.get("ok", True)
```

并根据 `handler_ok` 和 `error_msg` 写 DONE 或 FAILED。([GitHub][4])

所以现在不是“完全没接”，而是要**实测锁死 + 修细节风险**。

## 3.2 仍需修复的风险

### 3.2.1 `handler_ok` 默认 True 不够严格

当前：

```python
handler_ok = result_payload.get("ok", True)
```

如果某个 handler 忘记返回 `ok`，bridge 会默认成功。

建议改成：

```python
if "ok" not in result_payload:
    handler_ok = result_payload.get("error") is None
else:
    handler_ok = bool(result_payload["ok"])
```

或者更严格：

```python
if "ok" not in result_payload:
    handler_ok = False
    error_msg = "NX handler did not return explicit ok field."
```

推荐后者。工业级链路应该要求 handler 显式返回 ok。

### 3.2.2 所有 NX handler 都必须返回显式 `ok`

目前一些 legacy handler 返回：

```python
return {"files_created": ..., "metrics": ...}
```

没有 `ok` 字段。Claude Code 应该统一修改所有 NX action handler：

```python
return {
    "ok": True,
    "message": "...",
    "files_created": files_created,
    "metrics": metrics,
}
```

失败时：

```python
return {
    "ok": False,
    "files_created": files_created,
    "metrics": metrics,
    "error": "...",
}
```

涉及：

```text
create_block_part
create_block_with_hole
create_l_bracket
create_stepped_block
export_step
import_step_as_prt
```

### 3.2.3 `import_step_as_prt` 的 NXOpen API 需要实机验证

当前 bridge 里使用：

```python
dex_mgr = NXOpen.DexManager(session)
importer = dex_mgr.CreateStep214Importer()
importer.InputFile = str(step_path)
importer.OutputFile = str(out_prt)
importer.Commit()
```

这是否完全适配 NX 12.0，需要在 NX 12 内实测。Claude Code 应保留 fallback 或明确失败信息：

```python
try:
    importer = dex_mgr.CreateStep214Importer()
except AttributeError:
    return {
        "ok": False,
        "error": "NX 12.0 STEP importer API CreateStep214Importer not available; verify NXOpen API."
    }
```

### 3.2.4 `.prt` 保存必须基于 import 后的 work part

当前逻辑 import 后又：

```python
work_part.SaveAs(str(out_prt_path))
```

但 import 过程中是否创建了新的 work_part，需要确认。建议在 commit 后重新获取：

```python
work_part = session.Parts.Work
if work_part is None:
    return {"ok": False, "error": "No NX work part after STEP import."}
work_part.SaveAs(str(out_prt_path))
```

## 3.3 必须新增测试

新增或加强：

```text
tests/test_nx_bridge_bootstrap.py
tests/test_nx_step_import_strategy.py
```

测试内容：

```python
def test_nx_action_handlers_include_import_step_as_prt():
    # 静态检查 ACTION_HANDLERS 包含 import_step_as_prt


def test_nx_process_one_job_requires_explicit_ok(tmp_path, monkeypatch):
    # mock handler 返回 {"files_created": []}，没有 ok
    # process_one_job 必须写 FAILED 而不是 DONE


def test_nx_process_one_job_failed_handler_goes_failed(tmp_path, monkeypatch):
    # handler 返回 {"ok": False, "error": "boom"}
    # 必须写 failed result，ok=False


def test_nx_import_step_tool_checks_prt_exists(monkeypatch, tmp_path):
    # queue result ok=True，但 out_prt 不存在
    # nx_import_step_as_prt 必须 ok=False


def test_nx_import_step_submits_correct_action(monkeypatch, tmp_path):
    # 断言 q.submit("import_step_as_prt", ...)
```

---

# 4. P0：修复 backend_builders 的 fail-closed 传播

## 4.1 当前目标

`build_solidworks_from_canonical_step` 和 `build_nx_from_canonical_step` 必须严格保证：

```text
CadQuery build ok
STEP exists and non-empty
metadata exists and non-empty
inspection ok
mechanical_validation ok
native import ok
native file exists and non-empty
```

任何一步失败都不能继续或返回成功。

## 4.2 必须检查的代码点

文件：

```text
src/seekflow_engineering_tools/natural_language/backend_builders.py
```

Claude Code 必须确认：

```python
cq_result = build_canonical_step_with_cadquery(...)
if cq_result.get("ok") is not True:
    return ok=False
```

不能只看 STEP 是否存在。

必须检查：

```python
step_path.exists()
step_path.stat().st_size > 0

meta_path = step_path.with_suffix(".metadata.json")
meta_path.exists()
meta_path.stat().st_size > 0
```

必须从 `cq_result["metrics"]` 中确认：

```python
validation.ok is True
mechanical_validation.ok is True
```

伪代码：

```python
metrics = cq_result.get("metrics", {})
validation = metrics.get("validation")
if not validation or validation.get("ok") is not True:
    return EngineeringActionResult(
        ok=False,
        error="Canonical STEP inspection/validation failed; refusing native import.",
        ...
    ).model_dump()

mechanical = metrics.get("mechanical_validation")
if primitive_spec and (not mechanical or mechanical.get("ok") is not True):
    return EngineeringActionResult(
        ok=False,
        error="Mechanical validation failed; refusing native import.",
        ...
    ).model_dump()
```

SolidWorks native import 后：

```python
if not out_sldprt.exists() or out_sldprt.stat().st_size < 1:
    return ok=False
```

NX native import 后：

```python
if not out_prt.exists() or out_prt.stat().st_size < 1:
    return ok=False
```

## 4.3 files_created 必须包含全部产物

SolidWorks:

```text
.step
.metadata.json
.sldprt
```

NX:

```text
.step
.metadata.json
.prt
```

不能只返回 native 文件。

## 4.4 必须新增测试

```python
def test_solidworks_refuses_import_if_cadquery_build_not_ok(monkeypatch):
    # cq_result ok=False，不能调用 SolidWorksClient.import_step_as_part


def test_nx_refuses_import_if_mechanical_validation_missing(monkeypatch):
    # cq_result ok=True 但缺 mechanical_validation，不能 submit NX job


def test_native_import_requires_metadata_sidecar(monkeypatch, tmp_path):
    # STEP 存在但 metadata 缺失，SW/NX 都必须 ok=False


def test_solidworks_result_files_include_step_metadata_native(monkeypatch):
    # files_created 包含 step、metadata、sldprt


def test_nx_result_files_include_step_metadata_native(monkeypatch):
    # files_created 包含 step、metadata、prt
```

---

# 5. P0：修复 Natural Language build 的 silent fallback

## 5.1 当前问题

`choose_backend` 的规则是：preferred backend 不支持时 fallback 到 CadQuery，并写 warning。([GitHub][1])

这对普通工具选择是合理的，但对用户明确请求：

```text
backend="solidworks2025"
```

并期望生成 native `.sldprt` 时，不能静默 fallback 到 CadQuery 然后只给 STEP。

## 5.2 必须修改

文件：

```text
src/seekflow_engineering_tools/natural_language/tools.py
src/seekflow_engineering_tools/capabilities/registry.py
```

给 `engineering_build_cad_model` 增加参数：

```python
allow_backend_fallback: bool = False
```

逻辑：

```python
choice = choose_backend(cad_spec, preferred=[backend])

if choice.backend == "cadquery" and backend in {"solidworks2025", "nx12"} and choice.fallback_from:
    if not allow_backend_fallback:
        return EngineeringActionResult(
            ok=False,
            software=backend,
            action="build_cad_model",
            error=(
                f"Requested backend '{backend}' does not support this spec. "
                "Fallback to cadquery is disabled by default."
            ),
            warnings=choice.warnings,
        ).model_dump()
```

demo 可以对 gear SW/NX 显式传：

```python
allow_step_import=True
```

但不要等同于 `allow_backend_fallback=True`。
`allow_step_import` 是允许正确策略：

```text
CadQuery STEP → SW/NX import
```

而不是允许“用户请求 SW/NX，系统偷偷改成 CadQuery”。

## 5.3 必须新增测试

```python
def test_requested_solidworks_does_not_silently_fallback_to_cadquery():
    # 构造 SolidWorks 不支持的 feature
    # engineering_build_cad_model(... backend="solidworks2025")
    # 必须 ok=False，除非 allow_backend_fallback=True


def test_allow_backend_fallback_is_explicit(monkeypatch):
    # allow_backend_fallback=True 时可以 fallback，但 warnings 必须包含 fallback_from
```

---

# 6. P0：CadQuery builder 与 gear validation 锁死

## 6.1 当前状态

CadQuery builder 已经有 fail-closed 思路：

* mechanical validation import error 返回 `ok=False`；
* primitive build 要求 metadata sidecar；
* gear metadata 要求 `kernel`、`reference_dimensions`、`parameters`、`is_standard_involute`；
* fallback policy 已经区分 `industrial_brep` 和 `visual_fallback`。([GitHub][5])

Gear validation 也已经把 metadata 缺失、primitive mismatch、unknown kernel、visual fallback、reference dimensions 等作为 error。([GitHub][6])

## 6.2 仍需补强

### 6.2.1 metadata entry 不应只支持 primitive name

当前 builder 使用：

```python
pm.get("involute_spur_gear")
```

如果未来一个 CAD-IR 中有多个 gear instance，会冲突。

兼容修复：

```python
gear_meta = (
    pm.get(feat.id)
    or pm.get(feat.primitive_name)
    or pm.get("involute_spur_gear")
)
```

并推动 compiler 后续写入：

```json
"primitive_metadata": {
  "gear1": {
    "primitive": "involute_spur_gear",
    ...
  }
}
```

### 6.2.2 metadata 中的 parameters 必须与 spec 参数一致

新增校验：

```python
for key in ["module_mm", "teeth", "pressure_angle_deg", "face_width_mm", "bore_dia_mm"]:
    if key in feat.parameters:
        assert metadata["parameters"][key] == feat.parameters[key]
```

浮点用 tolerance。

### 6.2.3 mechanical validation 必须验证 expected_kernel

如果 `spec.validation.expected_kernel == "cq_gears"`，但 metadata kernel 是 fallback，必须 error。

## 6.3 必须新增测试

```python
def test_metadata_can_be_indexed_by_feature_id():
    # primitive_metadata["gear1"] 可被识别


def test_gear_metadata_parameters_must_match_spec():
    # metadata teeth != spec teeth -> fail


def test_expected_kernel_cq_gears_rejects_visual_fallback():
    # expected_kernel=cq_gears + kernel=cadquery_visual_fallback -> fail
```

---

# 7. P1：SolidWorks legacy gear 代码隔离

## 7.1 当前状态

SolidWorks 工具注册主路径已经比较正确：`solidworks_import_step_as_part` 存在，并且其描述明确这是 CadQuery/CQ_Gears primitive 的 canonical path。([GitHub][7])

但 legacy gear 代码仍存在于 SolidWorks COM/client 层。它们可以保留做历史兼容或 demo，但必须锁死：

```text
不注册
不路由
不用于 engineering_build_cad_model
不返回工程级成功
```

## 7.2 必须修改

文件：

```text
src/seekflow_engineering_tools/solidworks/tools.py
src/seekflow_engineering_tools/solidworks/com_client.py
tests/test_solidworks_step_import_strategy.py
tests/test_no_legacy_gear_for_engineering.py
```

要求：

1. `_legacy_visual_demo_create_spur_gear_part` 保持无 `@tool`。
2. `_legacy_demo_create_true_involute_gear_part` 保持无 `@tool`。
3. `build_solidworks_tools()` 的 tools list 中不得出现：

   * `solidworks_create_spur_gear_part`
   * `solidworks_create_true_involute_gear_part`
4. `engineering_build_cad_model` 不得调用：

   * `create_spur_gear`
   * `create_spur_gear_involute`
   * `create_spur_gear_true_involute`
5. 所有 legacy 函数 docstring 必须写：

```text
LEGACY DEMO ONLY.
Not engineering-grade.
Do not route from engineering_build_cad_model.
Use involute_spur_gear primitive + CadQuery/CQ_Gears + STEP import.
```

## 7.3 必须新增测试

```python
def test_solidworks_legacy_gear_tools_not_registered():
    tools = build_solidworks_tools(config)
    names = {t.name for t in tools}
    assert "solidworks_create_spur_gear_part" not in names
    assert "solidworks_create_true_involute_gear_part" not in names
    assert "solidworks_import_step_as_part" in names


def test_engineering_build_model_never_calls_solidworks_gear_generation(monkeypatch):
    # monkeypatch SolidWorksClient.create_spur_gear* 抛异常
    # build involute_spur_gear with solidworks2025
    # 不应触发这些函数
```

---

# 8. P1：ANSYS 继续保持 fail-closed，并补测试

## 8.1 当前状态

ANSYS 工具现在已经比较稳：使用 ANSYS 18.1 APDL batch；模板参数验证失败会 `ok=False`；APDL process error 会失败；有 expected metrics 的模板如果缺 `result_summary.txt` 或缺 required metrics，也会失败。([GitHub][8])

这部分不用大改，但要补测试锁死。

## 8.2 必须新增或确认测试

```text
tests/test_ansys_fail_closed.py
tests/test_ansys_template_validation.py
tests/test_ansys_template_registry.py
tests/test_ansys_runner_mock.py
```

必须覆盖：

```python
def test_ansys_unknown_parameter_fails():
    ...


def test_ansys_missing_required_parameter_fails():
    ...


def test_ansys_process_error_fails():
    ...


def test_ansys_summary_missing_fails_for_template_with_metrics():
    ...


def test_ansys_required_metric_missing_fails():
    ...


def test_ansys_does_not_import_pymapdl():
    # 静态检查 ansys 目录中没有 PyMAPDL gRPC 强依赖
```

---

# 9. P1：pyproject.toml 只需验证，不再作为缺口

当前 `pyproject.toml` 已经包含：

```toml
cadquery = ["cadquery>=2.5"]
gears = [
  "numpy>=1.24",
  "cq-gears @ git+https://github.com/meadiode/cq_gears.git@main",
]
build123d = ["build123d>=0.10"]
industrial = [
  "cadquery>=2.5",
  "numpy>=1.24",
  "cq-gears @ git+https://github.com/meadiode/cq_gears.git@main",
]
```

这符合目标方向。([GitHub][9])

Claude Code 只需要做两个验证：

1. `cq-gears` 没有进入主 `dependencies`；
2. pytest markers 中的 `requires_cq_gears` / `not_requires_cq_gears` 被实际测试使用。

新增测试或静态检查：

```python
def test_cq_gears_is_optional_dependency_only():
    # 解析 pyproject.toml
    # assert "cq-gears" not in project.dependencies
    # assert "cq-gears" in optional-dependencies["gears"]
    # assert "cq-gears" in optional-dependencies["industrial"]
```

---

# 10. P1：Capability Registry 需要补“禁止 legacy recipe”的测试

当前 capability registry 中已经删除了 `spur_gear` stable recipe，并保留了 `involute_spur_gear` primitive strategy。([GitHub][1])

还需要补测试锁死，防止后续回归。

新增：

```text
tests/test_capability_registry_primitives.py
tests/test_no_legacy_gear_for_engineering.py
```

测试：

```python
def test_spur_gear_not_in_stable_recipes():
    for backend in ["cadquery", "solidworks2025", "nx12"]:
        assert "spur_gear" not in list_backend_recipes(backend)


def test_involute_spur_gear_primitive_strategy():
    assert get_primitive_strategy("cadquery", "involute_spur_gear") == "native_cadquery_primitive"
    assert get_primitive_strategy("solidworks2025", "involute_spur_gear") == "cadquery_step_import"
    assert get_primitive_strategy("nx12", "involute_spur_gear") == "cadquery_step_import"
```

---

# 11. 完整测试清单

Claude Code 应确认这些测试存在并通过；没有就补：

```text
tests/test_compileall.py
tests/test_capability_registry_primitives.py
tests/test_no_legacy_gear_for_engineering.py
tests/test_engineering_validate_cad_ir_primitives.py
tests/test_engineering_build_cad_model_primitive_routing.py
tests/test_cadquery_builder_fail_closed.py
tests/test_gear_metadata_sidecar.py
tests/test_gear_validation.py
tests/test_solidworks_step_import_strategy.py
tests/test_nx_step_import_strategy.py
tests/test_nx_bridge_bootstrap.py
tests/test_demo_full_chain_gear.py
tests/test_ansys_fail_closed.py
tests/test_pyproject_optional_dependencies.py
```

特别要补的测试：

```python
def test_compileall_project():
    # subprocess python -m compileall src demo_full_chain.py


def test_demo_missing_validation_fails():
    ...


def test_demo_does_not_default_missing_mechanical_validation_to_ok():
    ...


def test_nx_handler_without_explicit_ok_fails():
    ...


def test_backend_builders_refuse_native_import_when_cq_validation_missing():
    ...


def test_solidworks_legacy_gear_not_registered_or_routed():
    ...
```

---

# 12. 必须运行的验收命令

Claude Code 完成后必须运行：

```bash
cd integrations/engineering_tools

python -m compileall src demo_full_chain.py
python -m pytest
```

然后运行 CadQuery demo：

```bash
python demo_full_chain.py \
  --case involute_spur_gear \
  --backend cadquery \
  --json-report reports/gear.json
```

检查报告：

```bash
python - <<'PY'
import json
from pathlib import Path

p = Path("reports/gear.json")
r = json.loads(p.read_text(encoding="utf-8"))
assert r["overall_ok"] is True, r

case = r["cases"][0] if "cases" in r else r
for s in [
    "validate_cad_ir",
    "normalize_primitives",
    "choose_backend",
    "build",
    "inspect",
    "mechanical_validate",
]:
    assert case["stages"][s]["ok"] is True, (s, case["stages"].get(s))

ref = case["metrics"]["reference_dimensions"]
for k in [
    "pitch_diameter_mm",
    "base_diameter_mm",
    "outer_diameter_mm",
    "root_diameter_mm",
]:
    assert ref[k] is not None, k

assert case["metrics"]["kernel_used"] in {"cq_gears", "cadquery_visual_fallback"}
if case["metrics"]["kernel_used"] == "cadquery_visual_fallback":
    raise AssertionError("Industrial demo must not pass with visual fallback.")
PY
```

如果有 SolidWorks/NX 实机环境，再运行：

```bash
python demo_full_chain.py \
  --case involute_spur_gear \
  --backend solidworks2025 \
  --allow-step-import \
  --json-report reports/gear_solidworks.json

python demo_full_chain.py \
  --case involute_spur_gear \
  --backend nx12 \
  --allow-step-import \
  --json-report reports/gear_nx.json
```

再运行静态 grep：

```bash
grep -R "solidworks_create_spur_gear_part" src/seekflow_engineering_tools || true
grep -R "solidworks_create_true_involute_gear_part" src/seekflow_engineering_tools || true
grep -R "create_spur_gear_true_involute\|create_spur_gear_involute\|create_spur_gear_star" src/seekflow_engineering_tools || true
grep -R "validation.get(\"ok\", True)" demo_full_chain.py src/seekflow_engineering_tools || true
grep -R "mechanical.*get(\"ok\", True)" demo_full_chain.py src/seekflow_engineering_tools || true
grep -R "result_payload.get(\"ok\", True)" src/seekflow_engineering_tools/nx || true
grep -R "best-effort" src/seekflow_engineering_tools || true
grep -R "tempfile.mktemp" src/seekflow_engineering_tools || true
```

要求：

```text
1. demo 中不得再有 validation.get("ok", True)。
2. NX bridge 中不得再有 result_payload.get("ok", True)。
3. SolidWorks legacy gear 可以命中，但必须不注册、不路由、有 legacy docstring、有测试锁死。
4. 不得有 tempfile.mktemp。
5. best-effort 不得作为 ok=True 依据。
```

---

# 13. 给 Claude Code 的完整执行 Prompt

下面这段可以直接复制给 Claude Code：

```text
你正在修复 WYZAAACCC/seekflow-engineering 仓库中的 integrations/engineering_tools 子项目。

目标：
把 SolidWorks / NX / ANSYS / CadQuery 集成修成 fail-closed 的工业级 Text-to-CAD / CAD-to-CAE 闭环。

核心管线：
Natural Language
→ engineering_validate_cad_ir
→ CAD-IR normalize
→ Capability Router
→ engineering_build_cad_model
→ Build Planner
→ CadQuery / CQ_Gears canonical STEP
→ metadata.json
→ Geometry Inspection
→ Mechanical Validation
→ SolidWorks / NX import STEP and save native
→ EngineeringActionResult
→ demo_full_chain / pytest 回归验收

绝对原则：
1. LLM 不直接生成 SolidWorks COM/VBS、NXOpen 齿形代码。
2. involute_spur_gear 必须走 deterministic primitive。
3. CadQuery / CQ_Gears / OpenCascade 是 canonical geometry source。
4. SolidWorks / NX 对复杂 primitive 只 import STEP，不重新生成齿形。
5. 文件不存在、STEP 为空、metadata 缺失、validation 缺失、mechanical_validation 缺失、fallback 静默使用，都不得 ok=True。
6. demo_full_chain 必须验收统一入口 engineering_validate_cad_ir + engineering_build_cad_model。

请按顺序执行：

任务 1：先确认源码可执行性。
- 运行：
  cd integrations/engineering_tools
  python -m compileall src demo_full_chain.py
- 如果失败，先修源码格式。多个 raw 文件看起来被压成一行，必须恢复正常 Python 换行。
- 确保所有模块以合法结构开始：
  """docstring."""
  from __future__ import annotations
  import ...

任务 2：修 demo_full_chain.py。
- demo 不得直接调用 build_cadquery_from_cad_ir / build_solidworks_from_canonical_step / build_nx_from_canonical_step 作为主路径。
- demo 必须调用 engineering_validate_cad_ir 和 engineering_build_cad_model。
- 去掉 validation.get("ok", True)、mv.get("ok", True)、mech_val.get("ok", True)。
- validation 或 mechanical_validation 缺失时必须失败。
- gear metadata 读取失败必须失败，不得 pass。
- 每个 case 必须输出 stages:
  validate_cad_ir
  normalize_primitives
  choose_backend
  build
  inspect
  mechanical_validate
- gear metrics 必须包含:
  kernel_used
  reference_dimensions.pitch_diameter_mm
  reference_dimensions.base_diameter_mm
  reference_dimensions.outer_diameter_mm
  reference_dimensions.root_diameter_mm
- --case all 任一 case 失败必须 sys.exit(1)。

任务 3：修 NX bridge fail-closed。
- nx_bridge_bootstrap.py 中 process_one_job 不得使用 result_payload.get("ok", True)。
- 所有 NX action handler 必须显式返回 ok=True 或 ok=False。
- handler 没有 ok 字段时必须视为失败。
- import_step_as_prt 必须保留在 ACTION_HANDLERS。
- import_step_as_prt 必须检查 input STEP 存在且非空、import 后 work_part 存在、out_prt 存在且非空。
- 失败写 FAILED，不得写 DONE。
- 不得在 NXOpen 里重新生成 involute 齿形。

任务 4：修 backend_builders fail-closed。
- build_solidworks_from_canonical_step / build_nx_from_canonical_step 必须先检查 cq_result["ok"] is True。
- 如果 CadQuery build ok=False，即使 STEP 存在，也不得 import native。
- 必须检查 STEP 和 metadata.json 存在且非空。
- 必须检查 cq_result.metrics.validation.ok is True。
- 对 primitive 必须检查 cq_result.metrics.mechanical_validation.ok is True。
- SolidWorks import 后检查 .sldprt 存在且非空。
- NX import 后检查 .prt 存在且非空。
- files_created 必须包含 STEP、metadata、native 文件。
- warnings 必须说明 native file created by STEP import; feature tree is not regenerated.

任务 5：修 engineering_build_cad_model 的 backend fallback。
- 增加 allow_backend_fallback=False。
- 用户明确请求 solidworks2025/nx12 时，不得静默 fallback 到 cadquery。
- 只有 allow_backend_fallback=True 才允许 fallback，并且 warnings 必须保留。

任务 6：补强 CadQuery builder / gear validation。
- primitive_metadata 支持用 feature.id 查找，兼容 primitive name。
- metadata.parameters 必须与 CAD-IR spec 参数一致。
- expected_kernel=cq_gears 时，cadquery_visual_fallback 必须失败。
- metadata 缺 primitive/kernel/parameters/reference_dimensions/is_standard_involute 必须失败。
- cadquery_visual_fallback 默认不得 industrial_brep 成功。

任务 7：SolidWorks legacy gear 隔离。
- solidworks_create_spur_gear_part 不得注册为 tool。
- solidworks_create_true_involute_gear_part 不得注册为 tool。
- legacy 函数必须无 @tool，不进 tools.extend。
- docstring 必须写 LEGACY DEMO ONLY / not engineering-grade / use primitive + STEP import。
- engineering_build_cad_model 不得调用 SolidWorks create_spur_gear*。
- solidworks_import_step_as_part 必须保留，并检查 STEP 和 SLDPRT 文件。

任务 8：ANSYS fail-closed 测试锁死。
- ANSYS 18.1 继续 APDL batch。
- unknown parameter / missing required / type error / min-max / process error / summary missing / required metrics missing 均必须 ok=False。
- 不要引入 PyMAPDL gRPC 强依赖。

任务 9：pyproject 只做验证。
- 确认 cq-gears 只在 optional-dependencies.gears / industrial 中，不在主 dependencies。
- 保留 build123d optional dependency。
- pytest markers requires_cq_gears / not_requires_cq_gears 应存在并被测试使用。

任务 10：补测试。
至少新增或修正：
- tests/test_compileall.py
- tests/test_capability_registry_primitives.py
- tests/test_no_legacy_gear_for_engineering.py
- tests/test_engineering_validate_cad_ir_primitives.py
- tests/test_engineering_build_cad_model_primitive_routing.py
- tests/test_cadquery_builder_fail_closed.py
- tests/test_gear_metadata_sidecar.py
- tests/test_gear_validation.py
- tests/test_solidworks_step_import_strategy.py
- tests/test_nx_step_import_strategy.py
- tests/test_nx_bridge_bootstrap.py
- tests/test_demo_full_chain_gear.py
- tests/test_ansys_fail_closed.py
- tests/test_pyproject_optional_dependencies.py

关键测试必须覆盖：
- compileall 通过。
- demo 使用 unified entrypoints。
- demo validation/mechanical_validation 缺失时失败。
- NX handler 无 explicit ok 时失败。
- NX import_step_as_prt 工具注册并提交正确 action。
- backend_builders 不在 CadQuery validation fail 后继续 native import。
- SolidWorks legacy gear 不注册、不路由。
- fallback industrial_brep fails。
- metadata missing fails。
- expected_kernel=cq_gears rejects fallback。
- pyproject cq-gears is optional only。

最后运行：
cd integrations/engineering_tools
python -m compileall src demo_full_chain.py
python -m pytest
python demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report reports/gear.json

再运行 grep：
grep -R "validation.get(\"ok\", True)" demo_full_chain.py src/seekflow_engineering_tools || true
grep -R "mechanical.*get(\"ok\", True)" demo_full_chain.py src/seekflow_engineering_tools || true
grep -R "result_payload.get(\"ok\", True)" src/seekflow_engineering_tools/nx || true
grep -R "solidworks_create_spur_gear_part" src/seekflow_engineering_tools || true
grep -R "solidworks_create_true_involute_gear_part" src/seekflow_engineering_tools || true
grep -R "create_spur_gear_true_involute\|create_spur_gear_involute\|create_spur_gear_star" src/seekflow_engineering_tools || true
grep -R "best-effort" src/seekflow_engineering_tools || true
grep -R "tempfile.mktemp" src/seekflow_engineering_tools || true

如果 grep 命中 legacy gear，必须确认：
1. 不注册为 tool。
2. 不被 engineering_build_cad_model 调用。
3. docstring 明确 legacy/demo/not engineering-grade。
4. 有测试覆盖不注册、不路由。
```

---

# 14. 最终验收标准

修复完成后，必须满足：

```text
1. python -m compileall src demo_full_chain.py 全绿。
2. pytest 全绿。
3. demo_full_chain 走 engineering_validate_cad_ir + engineering_build_cad_model。
4. demo 不再把缺失 validation / mechanical_validation 默认当成功。
5. NX import_step_as_prt 从 tool → queue → bridge → PRT 文件检查完整闭环。
6. NX handler 没有 explicit ok 时失败。
7. SolidWorks legacy gear 不注册、不路由。
8. SolidWorks/NX gear primitive 只走 CadQuery/CQ_Gears canonical STEP import。
9. backend_builders 不在 CadQuery validation fail 后继续 native import。
10. metadata 缺失、fallback、expected_kernel mismatch 都会失败。
11. ANSYS APDL template fail-closed。
12. cq-gears 作为 optional dependency，不污染最小安装。
13. reports/gear.json 中 gear stages 和 reference dimensions 完整。
```

当前最关键的不是“再增加新模块”，而是把**已经出现的模块接严、接死、接到统一入口上**。尤其是这三件事必须优先完成：

```text
1. compileall：先证明代码真的能跑。
2. demo_full_chain：改成验收统一入口，不能绕路。
3. fail-closed：任何缺 validation、缺 metadata、缺 native 文件、缺 explicit ok 都必须失败。
```

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx/tools.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/demo_full_chain.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx/nx_bridge_bootstrap.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/gear_validation.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/tools.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/ansys/tools.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/pyproject.toml "raw.githubusercontent.com"
