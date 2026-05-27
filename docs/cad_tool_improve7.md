
---

# SeekFlow Engineering 修复执行文档

## 0. 当前判断

当前仓库已经开始接近目标架构：`engineering_validate_cad_ir` 已经尝试做 recipe/primitive normalization，`engineering_build_cad_model` 也开始根据 primitive strategy 将 SolidWorks/NX primitive 路由到 CadQuery canonical STEP import；`backend_builders.py` 也已经出现 CadQuery → SolidWorks/NX import STEP 的规划函数。([GitHub][1])

但目前仍存在几个不能放过的问题：

1. 多个源码文件 raw 视图显示为极少物理行，`from __future__ import annotations` 被拼在 docstring 同一行，必须先确认是否真实语法损坏。
2. `solidworks_create_spur_gear_part` 和 `solidworks_create_true_involute_gear_part` 仍在源码中作为工具定义存在，虽然当前 tools list 没有加入它们，但仍是危险旁路。([GitHub][2])
3. `CAPABILITIES` 里 SolidWorks 和 CadQuery 仍把 `spur_gear` 放在 `stable_recipes`，这与“工程级齿轮必须 primitive 化”的目标冲突。([GitHub][3])
4. `gear_validation.py` 对 fallback、metadata primitive mismatch、reference_dimensions 缺失仍然主要是 warning，不是 hard error。([GitHub][4])
5. `NXJobQueue` 已允许 `import_step_as_prt`，但 `nx/tools.py` raw 内容几乎为空/不可读，需要确认工具层是否真正注册了 `nx_import_step_as_prt`。([GitHub][5])
6. `demo_full_chain.py` 虽然看起来已经被改成 CI 脚本，但 raw 仍显示只有 3 个物理行，必须先通过 `py_compile` 验证。([GitHub][6])

目标文档中的硬性标准是：SolidWorks/NX 对复杂 primitive 只 import STEP，不重新生成齿形；文件不存在、STEP 为空、metadata 缺失、validation fail、NX/SolidWorks fail 都不得 `ok=True`。

---

# 1. 第一优先级：先修源码格式和可执行性

## 问题

多个 raw 文件显示为异常压缩格式，例如：

```python
"""Natural-language CAD modelling tools — validate IR and build models.""" from __future__ import annotations
```

这在 Python 中通常是语法错误。`tools.py` raw 只有 6 行，`backend_builders.py` raw 只有 16 行，`registry.py` raw 只有 4 行，`demo_full_chain.py` raw 只有 3 行。([GitHub][1])

## Claude Code 必须执行

先不要修业务逻辑，先执行：

```bash
cd integrations/engineering_tools

python -m py_compile demo_full_chain.py
python -m py_compile src/seekflow_engineering_tools/natural_language/tools.py
python -m py_compile src/seekflow_engineering_tools/natural_language/backend_builders.py
python -m py_compile src/seekflow_engineering_tools/capabilities/registry.py
python -m py_compile src/seekflow_engineering_tools/cadquery_backend/builder.py
python -m py_compile src/seekflow_engineering_tools/solidworks/tools.py
python -m py_compile src/seekflow_engineering_tools/solidworks/com_client.py
python -m py_compile src/seekflow_engineering_tools/nx/job_queue.py
python -m py_compile src/seekflow_engineering_tools/mechanical_validation/gear_validation.py
```

如果任何一个失败，必须先恢复正常 Python 换行和格式。不要只靠 formatter；必须保证：

```python
"""docstring."""
from __future__ import annotations
```

而不是：

```python
"""docstring.""" from __future__ import annotations
```

## 验收

```bash
python -m compileall src demo_full_chain.py
```

必须全绿。

---

# 2. 修复 Capability Registry：移除工程级 `spur_gear` recipe

## 问题

当前 `CAPABILITIES` 中：

```python
solidworks2025.stable_recipes = ["box", "flanged_hub", "spur_gear"]
cadquery.stable_recipes = [..., "spur_gear", ...]
```

这会让系统认为 `spur_gear` 仍然是工程级稳定 recipe。([GitHub][3])

目标架构要求：工程级齿轮必须是：

```text
primitive_name = involute_spur_gear
```

而不是：

```text
recipe_name = spur_gear
```

并且 legacy `spur_gear` 应 rewrite 成 primitive。

## 修改文件

```text
src/seekflow_engineering_tools/capabilities/registry.py
src/seekflow_engineering_tools/recipes/mechanical.py
src/seekflow_engineering_tools/recipes/registry.py
src/seekflow_engineering_tools/natural_language/normalizer.py
tests/test_no_legacy_gear_for_engineering.py
```

## 必须修改

### 2.1 `capabilities/registry.py`

从工程级 stable recipes 中删除 `spur_gear`：

```python
"solidworks2025": {
    "stable_recipes": [
        "box",
        "flanged_hub",
    ],
    "stable_primitives": [
        "involute_spur_gear",
    ],
    "primitive_strategy": {
        "involute_spur_gear": "cadquery_step_import",
    },
}
```

CadQuery 中也删除工程级 `spur_gear`：

```python
"cadquery": {
    "stable_recipes": [
        "box",
        "cylinder",
        "block_with_hole",
        "l_bracket",
        "stepped_block",
        "flanged_hub",
        "shaft_basic",
        "shaft_with_keyway",
    ],
    "stable_primitives": [
        "involute_spur_gear",
    ],
}
```

如果确实需要保留视觉 demo recipe，应改名：

```python
"spur_gear_visual_legacy"
```

并且不放进 `stable_recipes`，最多放进：

```python
"legacy_demo_recipes"
```

### 2.2 `backend_supports_recipe`

不要让 `backend_supports_recipe("cadquery", "spur_gear")` 返回 True。

### 2.3 `choose_backend`

如果 spec 中还有 `recipe_name="spur_gear"`，应该在 normalizer 阶段 rewrite；如果没有 rewrite，`choose_backend` 不应该选择 SolidWorks/CadQuery 直接 recipe。

## 新增测试

```python
def test_spur_gear_not_stable_recipe_any_backend():
    from seekflow_engineering_tools.capabilities.registry import CAPABILITIES

    for backend in ["solidworks2025", "cadquery", "nx12"]:
        assert "spur_gear" not in CAPABILITIES[backend].get("stable_recipes", [])


def test_involute_spur_gear_registered_as_primitive():
    from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

    assert get_primitive_strategy("cadquery", "involute_spur_gear") == "native_cadquery_primitive"
    assert get_primitive_strategy("solidworks2025", "involute_spur_gear") == "cadquery_step_import"
    assert get_primitive_strategy("nx12", "involute_spur_gear") == "cadquery_step_import"
```

---

# 3. 修复 Natural Language 统一入口

## 当前状态

`engineering_validate_cad_ir` 已经做了比较正确的事情：rewrite deprecated recipe、validate schema、normalize recipe/primitive、调用 `backend_supports_feature`。这是正确方向。([GitHub][1])

`engineering_build_cad_model` 也开始区分：

```text
cadquery → build_cadquery_from_cad_ir
solidworks2025/nx12 + primitive → cadquery_step_import
solidworks2025/nx12 + no primitive → direct recipe
```

这也是正确方向。([GitHub][1])

## 仍需修复的问题

### 3.1 `engineering_build_cad_model` 必须先 normalize

当前 build 直接：

```python
cad_spec = CADPartSpec.model_validate(spec)
```

但不保证用户已经调用过 `engineering_validate_cad_ir`。统一入口不能假设调用顺序正确。

## 修改要求

在 `engineering_build_cad_model` 中加入内部 normalization：

```python
spec = rewrite_deprecated_recipes_to_primitives(spec)
cad_spec = CADPartSpec.model_validate(spec)

for feat in cad_spec.features:
    if feat.type == "recipe":
        feat.parameters = normalize_recipe_parameters(feat.recipe_name, feat.parameters)
    elif feat.type == "primitive":
        feat.parameters = normalize_primitive_parameters(feat.primitive_name, feat.parameters)
```

这样即使用户直接调用 build，也不会绕过 primitive 参数校验。

### 3.2 禁止 mixed unsafe routing

如果一个 CAD-IR 同时包含：

```text
primitive involute_spur_gear
recipe spur_gear
```

必须失败。

新增检查：

```python
for feat in cad_spec.features:
    if feat.type == "recipe" and feat.recipe_name == "spur_gear":
        return EngineeringActionResult(
            ok=False,
            error="Recipe 'spur_gear' is deprecated for engineering builds; use primitive 'involute_spur_gear'."
        ).model_dump()
```

### 3.3 backend fallback 不能静默

当前 `choose_backend` 如果 preferred backend 不支持，会 fallback 到 CadQuery，并产生 warning。([GitHub][3])

这对普通 build 可以接受，但对用户明确请求：

```text
backend="solidworks2025"
```

且目的是 native SLDPRT 时，不能悄悄 fallback 到 CadQuery 后返回 STEP 成功。

建议：

```python
if backend in {"solidworks2025", "nx12"} and choice.backend == "cadquery":
    return ok=False, error="Requested native backend does not support this spec; fallback to cadquery is not allowed unless allow_backend_fallback=True."
```

或者给 `engineering_build_cad_model` 增加参数：

```python
allow_backend_fallback: bool = False
```

默认 False。

## 新增测试

```python
def test_build_directly_normalizes_primitive_params(monkeypatch):
    # 输入 primitive 参数 teeth="24"，build 内部应转换为 int 或明确失败


def test_build_rejects_legacy_spur_gear_recipe():
    # recipe_name="spur_gear" 直接 build 应 ok=False


def test_solidworks_request_does_not_silently_fallback_to_cadquery():
    # preferred solidworks 不支持的 feature，不得 silent fallback
```

---

# 4. 修复 Backend Builders：补齐 native 文件 hard check

## 当前状态

`backend_builders.py` 已经有：

```text
build_canonical_step_with_cadquery
build_solidworks_from_canonical_step
build_nx_from_canonical_step
```

并且 SolidWorks/NX primitive 方向已经是 CadQuery → canonical STEP → import native。([GitHub][7])

这是正确方向。

## 仍需修复

### 4.1 CadQuery result 不 ok 时必须停止

当前 `build_solidworks_from_canonical_step` 和 `build_nx_from_canonical_step` 主要检查 `step_path.exists()`，但还应该检查：

```python
if not cq_result.get("ok"):
    return ok=False
```

否则可能出现 CadQuery result 已经 validation failed，但 STEP 文件存在，于是继续 import native。

修改：

```python
cq_result = build_canonical_step_with_cadquery(...)

if not cq_result.get("ok", False):
    return EngineeringActionResult(
        ok=False,
        software="solidworks",
        action="build_from_canonical_step",
        error="Canonical CadQuery build failed; refusing to import invalid STEP into SolidWorks.",
        files_created=cq_result.get("files_created", []),
        metrics=cq_result.get("metrics", {}),
        warnings=cq_result.get("warnings", []),
    ).model_dump()
```

NX 同理。

### 4.2 metadata 必须随 native import 传播

SolidWorks/NX 返回的 `files_created` 必须包含：

```text
.step
.metadata.json
.sldprt / .prt
```

如果 `.metadata.json` 不在 `cq_result.files_created` 中，也应该主动检查：

```python
meta_path = step_path.with_suffix(".metadata.json")
if not meta_path.exists() or meta_path.stat().st_size < 1:
    return ok=False
```

### 4.3 native 文件必须自己检查，不只信 client/job result

SolidWorks：

```python
if not sldprt_path.exists() or sldprt_path.stat().st_size < 1:
    return ok=False
```

NX：

```python
if not prt_path.exists() or prt_path.stat().st_size < 1:
    return ok=False
```

当前 NX builder 只是信 `result.get("ok")`，需要增加本地文件检查。([GitHub][7])

## 新增测试

```python
def test_solidworks_import_stops_if_cadquery_result_not_ok(monkeypatch):
    # cq_result ok=False 但 step exists，仍不得调用 SolidWorks import


def test_nx_import_stops_if_cadquery_result_not_ok(monkeypatch):
    # cq_result ok=False 但 step exists，仍不得 submit NX job


def test_solidworks_native_file_must_exist(monkeypatch, tmp_path):
    # import_ok True 但 sldprt 不存在，结果 ok=False


def test_nx_native_file_must_exist(monkeypatch, tmp_path):
    # job result ok True 但 prt 不存在，结果 ok=False
```

---

# 5. 修复 CadQuery Builder：取消 fallback 软成功

## 当前状态

`builder.py` 已经比之前好很多：mechanical validation ImportError 现在是 hard error；primitive metadata sidecar 也有 `_assert_metadata_sidecar`；fallback policy 也初步存在。([GitHub][8])

## 仍需修复

### 5.1 `_assert_metadata_sidecar` 必须检查 `is_standard_involute`

它的 docstring 写了要检查 `is_standard_involute`，但代码只检查：

```python
kernel
reference_dimensions
parameters
```

没有检查 `is_standard_involute`。([GitHub][8])

修改：

```python
if "is_standard_involute" not in gear_meta:
    raise ValueError("Gear metadata missing 'is_standard_involute'")
```

### 5.2 fallback warning 后不能再 `ok=True`

当前末尾仍有：

```python
if has_fallback:
    return EngineeringActionResult(ok=True, ...)
```

这会导致 fallback 最终成功。([GitHub][8])

应该改成：

```python
if has_fallback:
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_from_cad_ir",
        message="STEP file created but fallback gear is not engineering-grade.",
        files_created=files_created,
        metrics=metrics,
        warnings=warnings,
        error="cadquery_visual_fallback is not certified involute geometry.",
    ).model_dump()
```

只有在 spec 显式允许 fallback 时才能成功：

```python
quality_grade == "visual_fallback"
or allow_visual_fallback is True
```

### 5.3 primitive metadata shape 需要兼容但必须严格

当前代码假设：

```python
metadata["primitive_metadata"]["involute_spur_gear"]
```

但如果未来多个 gear instance，需要按 feature id 存储。建议 Claude Code 先兼容当前形态，但增加 TODO 或支持：

```python
metadata["primitive_metadata"][feature.id]
metadata["primitive_metadata"][feature.primitive_name]
```

优先查 feature id，再查 primitive name。

## 新增测试

```python
def test_gear_metadata_requires_is_standard_involute(tmp_path):
    # metadata 缺少 is_standard_involute -> ok=False


def test_fallback_warning_never_ok_for_industrial_brep(monkeypatch):
    # warnings 中含 visual_fallback/not certified -> ok=False


def test_visual_fallback_allowed_only_explicitly(monkeypatch):
    # quality_grade=visual_fallback -> 可以 ok=True，但 warnings 必须存在
```

---

# 6. 修复 Gear Mechanical Validation：warning 改 hard error

## 当前问题

`gear_validation.py` 对以下情况只是 warning：

```text
primitive_mismatch
gear_visual_fallback_used
gear_kernel_unknown
reference_dimension_missing
reference_dimensions_missing
```

这些对工业级齿轮都应该是 error。([GitHub][4])

目标文档明确要求齿轮必须检查 pitch/base/outer/root diameter，fallback 不能静默当成工业级齿轮。

## 修改文件

```text
src/seekflow_engineering_tools/mechanical_validation/gear_validation.py
src/seekflow_engineering_tools/mechanical_validation/common.py
tests/test_gear_validation.py
```

## 修改要求

### 6.1 metadata 缺失是 error

```python
if metadata is None:
    issues.append({
        "code": "gear_metadata_missing",
        "message": "Gear metadata sidecar is required for engineering validation.",
        "severity": "error",
    })
```

### 6.2 kernel unknown 是 error

```python
if kernel == "unknown":
    severity = "error"
```

### 6.3 fallback 是 error，除非显式 visual_fallback

```python
if kernel == "cadquery_visual_fallback":
    severity = "error"
```

### 6.4 reference_dimensions 缺失是 error

```python
if "reference_dimensions" not in metadata:
    severity = "error"
```

### 6.5 reference_dimensions 数值必须比较

不仅要检查 key 是否存在，还要比较：

```python
for key in [
    "pitch_diameter_mm",
    "base_diameter_mm",
    "outer_diameter_mm",
    "root_diameter_mm",
]:
    expected = ref[key]
    actual = metadata["reference_dimensions"][key]
    if abs(actual - expected) > tolerance_mm:
        severity = "error"
```

### 6.6 `is_standard_involute` 必须为 True

```python
if metadata.get("is_standard_involute") is not True:
    issues.append({
        "code": "gear_not_standard_involute",
        "severity": "error",
    })
```

## 新增测试

```python
def test_gear_validation_metadata_missing_fails():
    ...


def test_gear_validation_fallback_fails():
    ...


def test_gear_validation_reference_dimension_missing_fails():
    ...


def test_gear_validation_pitch_dimension_mismatch_fails():
    ...


def test_gear_validation_kernel_unknown_fails():
    ...
```

---

# 7. 修复 SolidWorks：清理危险齿轮工具

## 当前问题

`solidworks/tools.py` 中仍有两个 `@tool` 函数：

```text
solidworks_create_spur_gear_part
solidworks_create_true_involute_gear_part
```

虽然当前 `tools.extend([...])` 只加入了 health_check、box、flanged_hub、export_step、import_step_as_part，但这两个函数仍是被装饰的 tool 对象，未来很容易被误加入 registry，且源码中描述了 star-polygon 和 SolidWorks 直接 involute。([GitHub][2])

## 必须修改

### 7.1 删除或改成内部 legacy 函数

把：

```python
@tool(name="solidworks_create_spur_gear_part", ...)
def solidworks_create_spur_gear_part(...):
```

改成：

```python
def _legacy_visual_demo_create_spur_gear_part(...):
    """
    LEGACY DEMO ONLY.
    Not engineering-grade.
    Not registered as SeekFlow tool.
    Do not use for Text-to-CAD production.
    Use involute_spur_gear primitive + CadQuery/CQ_Gears + STEP import.
    """
```

把：

```python
@tool(name="solidworks_create_true_involute_gear_part", ...)
def solidworks_create_true_involute_gear_part(...):
```

改成：

```python
def _legacy_demo_create_true_involute_gear_part(...):
    """
    LEGACY DEMO ONLY.
    Do not expose as tool.
    Do not route from engineering_build_cad_model.
    Canonical engineering path is CadQuery/CQ_Gears STEP import.
    """
```

最好直接删除这两段工具代码。若保留，必须：

```text
无 @tool
不进入 tools.extend
测试证明不会被 build_engineering_tools 注册
docstring 明确 legacy/demo/not engineering-grade
```

### 7.2 `com_client.py` legacy 方法加红线注释

`SolidWorksClient.create_spur_gear_involute` 和 `create_spur_gear_true_involute` 可以暂时保留以兼容旧测试，但必须注释：

```python
# LEGACY / DEMO ONLY.
# Must never be called by engineering_build_cad_model.
# Engineering gear path is CadQuery/CQ_Gears -> STEP -> import_step_as_part.
```

### 7.3 `solidworks_import_step_as_part` 保留并强化

已有 `solidworks_import_step_as_part`，描述方向正确。([GitHub][2])

增强：

```python
ensure_extension(out_path, {".sldprt"})
out_path.parent.mkdir(parents=True, exist_ok=True)

if out_path.exists() and not config.allow_overwrite:
    return ok=False

ok = client.import_step_as_part(...)
_assert_file_created(out_path, "SLDPRT")
```

## 新增测试

```python
def test_solidworks_legacy_gear_tools_not_registered():
    tools = build_solidworks_tools(config)
    names = {t.name for t in tools}

    assert "solidworks_create_spur_gear_part" not in names
    assert "solidworks_create_true_involute_gear_part" not in names
    assert "solidworks_import_step_as_part" in names


def test_solidworks_import_step_checks_output_exists(monkeypatch, tmp_path):
    # client.import_step_as_part 返回 True 但文件不存在 -> ok=False
```

---

# 8. 修复 NX：补完整 `nx_import_step_as_prt` 工具和 bridge 验收

## 当前状态

`NXJobQueue.ALLOWED_ACTIONS` 已经包含：

```python
"import_step_as_prt"
```

这是正确方向。([GitHub][5])

但 `nx/tools.py` raw 内容几乎没有可见实现，上一轮审查也显示工具列表缺少 `nx_import_step_as_prt`。([GitHub][9])

## 必须新增工具

文件：

```text
src/seekflow_engineering_tools/nx/tools.py
```

新增：

```python
@tool(
    name="nx_import_step_as_prt",
    description=(
        "Import a canonical STEP file into Siemens NX 12.0 and save as native PRT. "
        "This is the required path for engineering primitives generated by CadQuery/CQ_Gears."
    ),
    cache=False,
    sanitize=True,
    trusted=False,
)
def nx_import_step_as_prt(input_step: str, out_prt: str) -> dict:
    ...
```

逻辑：

```python
in_path = ensure_inside_workspace(config.workspace_root, input_step)
out_path = ensure_inside_workspace(config.workspace_root, out_prt)
ensure_extension(in_path, {".step", ".stp"})
ensure_extension(out_path, {".prt"})

if not in_path.exists() or in_path.stat().st_size < 1:
    return ok=False

job_id = q.submit("import_step_as_prt", {
    "input_step": str(in_path),
    "out_prt": str(out_path),
})

result = q.wait(job_id, timeout_s=config.nx_default_timeout_s)

if not result.get("ok"):
    return ok=False

if not out_path.exists() or out_path.stat().st_size < 1:
    return ok=False

return ok=True
```

返回 warnings：

```text
Native PRT created by importing canonical STEP; NX feature tree is not regenerated.
```

## Bridge 端必须实现

找到 NX bridge/journal 文件，通常可能是：

```text
nx_bridge_bootstrap.py
nx/actions.py
nx/bridge_handlers.py
```

确保存在 handler：

```python
def handle_import_step_as_prt(params):
    input_step = params["input_step"]
    out_prt = params["out_prt"]

    # NXOpen STEP importer
    # import STEP
    # save as PRT
    # return ok only if out_prt exists and non-empty
```

如果没有 bridge handler，`NXJobQueue` 允许该 action 也没用。

## 新增测试

```python
def test_nx_tools_register_import_step_as_prt():
    tools = build_nx_tools(config)
    names = {t.name for t in tools}
    assert "nx_import_step_as_prt" in names


def test_nx_import_step_action_submitted(monkeypatch):
    # monkeypatch NXJobQueue.submit
    # assert action == "import_step_as_prt"


def test_nx_import_step_requires_prt_file(monkeypatch, tmp_path):
    # result ok=True 但 .prt 不存在 -> ok=False
```

---

# 9. 修复 Demo：必须成为真正 CI 验收脚本

## 当前状态

`demo_full_chain.py` 已经看起来包含 case runner、`--case`、`--backend`、`--json-report`、`--allow-step-import`，方向正确。([GitHub][6])

但必须先解决：

```text
源码物理行/语法问题
box/flanged_hub 不应只支持 cadquery
gear 的 SW/NX stage 不应把 inspect/mechanical_validate 简化为 result.ok
```

目标文档要求 demo 是端到端验收脚本，而不是演示打印，gear report 必须包含 validate、normalize、choose_backend、build、inspect、mechanical_validate 等 stages，并且失败时 `sys.exit(1)`。

## 必须修改

### 9.1 所有 case 统一走 `engineering_validate_cad_ir` 和 `engineering_build_cad_model`

不要在 demo 里直接：

```python
build_cadquery_from_cad_ir(...)
```

应该走统一入口：

```python
tools = build_natural_language_tools(config)
engineering_validate_cad_ir(...)
engineering_build_cad_model(...)
```

或者直接 import underlying function，但语义上必须验证 unified route。

### 9.2 stage 定义固定

每个 case report 必须有：

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

对于 box/flanged_hub 没有 primitive，也必须填：

```json
"mechanical_validate": {
  "ok": true,
  "skipped": true,
  "reason": "No mechanical primitive features."
}
```

### 9.3 gear 的 SW/NX report 要从 CadQuery result 中取 validation

SolidWorks/NX import 后的 result metrics 中应包含：

```python
metrics["inspection"]
metrics["validation"]
metrics["mechanical_validation"]
```

demo 不能简单：

```python
_stage(report, "inspect", ok=result.get("ok", False))
_stage(report, "mechanical_validate", ok=result.get("ok", False))
```

应改成：

```python
validation = result["metrics"].get("validation", {})
mechanical = result["metrics"].get("mechanical_validation", {})

_stage(report, "inspect", ok=validation.get("ok") is True)
_stage(report, "mechanical_validate", ok=mechanical.get("ok") is True)
```

### 9.4 `--case all` 必须写完整报告并失败退出

当前看起来有 `overall_ok` 和 `sys.exit(1)`，保留并加强。([GitHub][6])

## 新增测试

```python
def test_demo_gear_cadquery_report_schema(tmp_path):
    # subprocess run demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report
    # assert report has required stages and metrics


def test_demo_all_fails_if_one_case_fails(monkeypatch):
    # mock one runner fail，assert exit code != 0


def test_demo_solidworks_gear_requires_allow_step_import():
    # no --allow-step-import -> exit nonzero
```

---

# 10. 修复 ANSYS：结果缺失不能软成功

## 当前目标

ANSYS 18.1 应使用 APDL batch，不依赖 PyMAPDL gRPC；模板参数必须强校验；parser 覆盖 static、thermal、modal、buckling、plastic。

## Claude Code 需要检查并修复

文件：

```text
src/seekflow_engineering_tools/ansys/
tests/test_ansys_*.py
```

必须确认：

```text
unknown parameter -> ok=False
required parameter missing -> ok=False
type conversion fail -> ok=False
min/max fail -> ok=False
geometry constraint fail -> ok=False
APDL process nonzero -> ok=False
expected result_summary.txt missing -> ok=False 或至少 template-specific error
parser expected metrics missing -> ok=False
```

如果当前 `ansys_run_apdl_template` 对 summary 缺失只是 warning，应改成：

```python
if template.requires_summary and not summary_path.exists():
    return EngineeringActionResult(ok=False, error="ANSYS result summary missing")
```

## 新增测试

```python
def test_ansys_summary_missing_fails_for_templates_that_require_summary():
    ...


def test_ansys_parser_missing_required_metric_fails():
    ...


def test_ansys_unknown_parameter_fails():
    ...
```

---

# 11. 补 pyproject optional dependencies

目标文档要求 CQ_Gears 是齿轮主 kernel，并作为 optional dependency，不破坏最小安装。

修改：

```text
integrations/engineering_tools/pyproject.toml
```

加入：

```toml
[project.optional-dependencies]
cadquery = [
  "cadquery>=2.5",
]

gears = [
  "numpy>=1.24",
  "cq-gears @ git+https://github.com/meadiode/cq_gears.git@main",
]

build123d = [
  "build123d>=0.10",
]

industrial = [
  "cadquery>=2.5",
  "numpy>=1.24",
  "cq-gears @ git+https://github.com/meadiode/cq_gears.git@main",
]
```

注意：不要把 `cq-gears` 放到主 dependencies。

---

# 12. 补测试清单

Claude Code 必须新增或确认以下测试存在并通过：

```text
tests/test_capability_registry_primitives.py
tests/test_no_legacy_gear_for_engineering.py
tests/test_engineering_validate_cad_ir_primitives.py
tests/test_engineering_build_cad_model_primitive_routing.py
tests/test_cadquery_builder_fail_closed.py
tests/test_gear_metadata_sidecar.py
tests/test_gear_validation.py
tests/test_solidworks_step_import_strategy.py
tests/test_nx_step_import_strategy.py
tests/test_demo_full_chain_gear.py
tests/test_ansys_fail_closed.py
```

核心断言：

```python
def test_no_solidworks_gear_tools_registered():
    names = {t.name for t in build_solidworks_tools(config)}
    assert "solidworks_create_spur_gear_part" not in names
    assert "solidworks_create_true_involute_gear_part" not in names
    assert "solidworks_import_step_as_part" in names
```

```python
def test_solidworks_gear_primitive_uses_cadquery_step_import(monkeypatch):
    # assert build_canonical_step_with_cadquery called
    # assert SolidWorksClient.import_step_as_part called
    # assert create_spur_gear / create_spur_gear_true_involute never called
```

```python
def test_nx_gear_primitive_submits_import_step_as_prt(monkeypatch):
    # assert NXJobQueue.submit("import_step_as_prt", ...)
```

```python
def test_fallback_gear_industrial_brep_fails(monkeypatch):
    # metadata kernel=cadquery_visual_fallback, quality_grade default industrial_brep -> ok False
```

```python
def test_gear_validation_reference_dimensions_missing_fails():
    # metadata missing pitch/base/outer/root -> ok False
```

```python
def test_demo_full_chain_gear_report_has_required_stages(tmp_path):
    # report contains validate_cad_ir, normalize_primitives, choose_backend, build, inspect, mechanical_validate
```

---

# 13. 必须运行的验收命令

Claude Code 完成后必须运行：

```bash
cd integrations/engineering_tools

python -m compileall src demo_full_chain.py
python -m pytest
```

再运行：

```bash
python demo_full_chain.py \
  --case involute_spur_gear \
  --backend cadquery \
  --json-report reports/gear.json
```

如果机器没有 SolidWorks/NX，可以只跑 mock 测试；如果有实机环境，再跑：

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

再跑 grep：

```bash
grep -R "solidworks_create_spur_gear_part" src/seekflow_engineering_tools || true
grep -R "solidworks_create_true_involute_gear_part" src/seekflow_engineering_tools || true
grep -R "create_spur_gear_true_involute\|create_spur_gear_involute\|create_spur_gear_star" src/seekflow_engineering_tools || true
grep -R "star-polygon\|visual gear\|triangular teeth" src/seekflow_engineering_tools || true
grep -R "return {\"ok\": True, \"results\": \[\]}" src/seekflow_engineering_tools || true
grep -R "best-effort" src/seekflow_engineering_tools || true
grep -R "tempfile.mktemp" src/seekflow_engineering_tools || true
```

grep 命中 legacy gear 代码可以接受，但必须满足：

```text
1. 不注册为 SeekFlow tool。
2. 不被 engineering_build_cad_model 调用。
3. docstring 明确 legacy/demo/not engineering-grade。
4. 有测试证明不会被路由。
```

---

# 14. 给 Claude Code 的完整执行 Prompt

下面这段可以直接复制给 Claude Code：

```text
你正在修复 WYZAAACCC/seekflow-engineering 仓库的 integrations/engineering_tools 子项目。

总体目标：
把当前 SolidWorks / NX / ANSYS / CadQuery 集成修成 fail-closed 的工业级 Text-to-CAD / CAD-to-CAE 第一阶段闭环：

Natural Language
→ CAD-IR
→ recipe / primitive normalization
→ capability routing
→ build planner
→ CadQuery / CQ_Gears canonical STEP
→ metadata.json
→ inspection
→ mechanical validation
→ SolidWorks / NX import STEP and save native
→ EngineeringActionResult
→ demo_full_chain / tests 回归验收

绝对原则：
1. LLM 不直接生成 SolidWorks COM/VBS、NXOpen journal 或复杂 APDL。
2. LLM 不现场推导 involute gear、thread、spring、cam 曲线。
3. involute_spur_gear 必须是 deterministic primitive。
4. CadQuery/CQ_Gears/OpenCascade 是 canonical geometry source。
5. SolidWorks/NX 对 gear primitive 只 import STEP，不重新生成齿形。
6. 文件不存在、STEP 为空、metadata 缺失、validation fail、mechanical validation 不可用时，绝不能 ok=True。
7. cadquery_visual_fallback 默认不能作为 industrial_brep 成功。

请按下面顺序执行。

任务 1：先修源码可执行性。
- 运行 python -m compileall src demo_full_chain.py。
- 如果 raw 文件被压成一行导致 from __future__ import annotations 语法错误，先恢复正常换行。
- 所有 Python 文件必须 py_compile 通过。

任务 2：修 capability registry。
- 从 solidworks2025 和 cadquery stable_recipes 删除 spur_gear。
- 保留 involute_spur_gear 为 stable_primitives。
- cadquery primitive_strategy[involute_spur_gear] = native_cadquery_primitive。
- solidworks2025/nx12 primitive_strategy[involute_spur_gear] = cadquery_step_import。
- 如果保留 visual gear，命名为 spur_gear_visual_legacy，不得进入 stable_recipes。

任务 3：修 engineering_validate_cad_ir 和 engineering_build_cad_model。
- validate 必须 rewrite deprecated spur_gear recipe 成 involute_spur_gear primitive。
- validate 必须 normalize recipe 和 primitive。
- build 即使用户没先调用 validate，也必须内部 normalize。
- build 遇到 recipe_name=spur_gear 必须失败或 rewrite，不得直接工程构建。
- backend support 检查必须用 backend_supports_feature。
- 明确请求 solidworks2025/nx12 时，不得静默 fallback 到 cadquery，除非显式 allow_backend_fallback=True。

任务 4：修 backend_builders。
- build_solidworks_from_canonical_step 和 build_nx_from_canonical_step 必须先检查 cq_result["ok"]。
- 如果 CadQuery build ok=False，即使 STEP 文件存在，也不得 import 到 SolidWorks/NX。
- 必须检查 STEP 和 metadata.json 存在且非空。
- SolidWorks import 后必须检查 .sldprt 存在且非空。
- NX import 后必须检查 .prt 存在且非空。
- files_created 必须包含 STEP、metadata、native 文件。
- warnings 必须说明 native file created by STEP import; feature tree is not regenerated.

任务 5：修 CadQuery builder fail-closed。
- _assert_metadata_sidecar 必须检查 is_standard_involute。
- primitive metadata 缺失必须 ok=False。
- gear metadata 缺 kernel/parameters/reference_dimensions/is_standard_involute 必须 ok=False。
- mechanical_validation import error 必须 ok=False。
- cadquery_visual_fallback 对 industrial_brep/validated 必须 ok=False。
- 只有 quality_grade=visual_fallback 或 allow_visual_fallback=True 才允许 fallback 成功，并且必须 warnings 明确 not certified involute geometry。

任务 6：修 mechanical_validation/gear_validation.py。
- metadata missing 是 error。
- primitive mismatch 是 error。
- kernel unknown 是 error。
- kernel cadquery_visual_fallback 是 error，除非明确 visual_fallback。
- reference_dimensions missing 是 error。
- pitch/base/outer/root diameter 必须与标准公式比较，超 tolerance 是 error。
- is_standard_involute != True 是 error。
- bbox/face_width mismatch 继续是 error。

任务 7：清理 SolidWorks 危险旁路。
- solidworks_create_spur_gear_part 不得注册为 tool。
- solidworks_create_true_involute_gear_part 不得注册为 tool。
- 最好删除这两个 @tool 函数；如保留，改成 _legacy_* 内部函数，无 @tool，不进 tools.extend。
- docstring 必须写 LEGACY DEMO ONLY / not engineering-grade / use involute_spur_gear primitive + STEP import instead。
- SolidWorksClient.create_spur_gear_involute / create_spur_gear_true_involute 必须注释为 legacy only，不得被 unified build 调用。
- solidworks_import_step_as_part 必须保留并检查 input STEP 和 output SLDPRT。

任务 8：补 NX STEP import 工具和 bridge。
- NXJobQueue 已允许 import_step_as_prt，但 nx/tools.py 必须注册 nx_import_step_as_prt。
- nx_import_step_as_prt(input_step, out_prt) 必须检查 input STEP 存在且非空。
- submit action 必须是 import_step_as_prt。
- job result ok=True 后仍必须检查 out_prt 存在且非空。
- bridge/journal handler 必须真正实现 STEP import 和 SaveAs PRT。
- NXOpen 中不得重新生成 involute 曲线。

任务 9：修 demo_full_chain.py。
- 必须 py_compile 通过。
- 必须支持：
  python demo_full_chain.py --case box --backend cadquery
  python demo_full_chain.py --case flanged_hub --backend cadquery
  python demo_full_chain.py --case involute_spur_gear --backend cadquery
  python demo_full_chain.py --case involute_spur_gear --backend solidworks2025 --allow-step-import
  python demo_full_chain.py --case involute_spur_gear --backend nx12 --allow-step-import
  python demo_full_chain.py --case all --backend cadquery --json-report reports/full_chain.json
- 每个 case report 必须包含 stages:
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
- 失败必须 sys.exit(1)，包括 --case all。
- demo 尽量走 engineering_validate_cad_ir 和 engineering_build_cad_model 统一入口，不要绕过主链路。

任务 10：修 ANSYS fail-closed。
- ANSYS 18.1 继续走 APDL batch，不用 PyMAPDL gRPC。
- unknown parameter、missing required、type error、min/max、geometry constraint 必须 ok=False。
- APDL process 非零退出必须 ok=False。
- 对需要 result_summary 的模板，summary 缺失必须 ok=False。
- parser 缺 required metric 必须 ok=False。

任务 11：补 pyproject optional deps。
- 加 cadquery/gears/build123d/industrial optional dependencies。
- cq-gears 放在 gears/industrial optional，不要放主 dependencies。

任务 12：补测试。
至少新增或修正：
- test_capability_registry_primitives.py
- test_no_legacy_gear_for_engineering.py
- test_engineering_validate_cad_ir_primitives.py
- test_engineering_build_cad_model_primitive_routing.py
- test_cadquery_builder_fail_closed.py
- test_gear_metadata_sidecar.py
- test_gear_validation.py
- test_solidworks_step_import_strategy.py
- test_nx_step_import_strategy.py
- test_demo_full_chain_gear.py
- test_ansys_fail_closed.py

关键测试必须覆盖：
- spur_gear 不在 stable_recipes。
- spur_gear recipe rewrite 成 involute_spur_gear primitive。
- SolidWorks/NX gear primitive 先 build CadQuery STEP，再 import native。
- SolidWorks legacy gear tools 不注册。
- NX import_step_as_prt tool 注册并提交正确 action。
- metadata missing fails。
- mechanical validation import error fails。
- fallback industrial_brep fails。
- demo gear report schema 正确。
- native file 不存在时 ok=False。

最后运行：
cd integrations/engineering_tools
python -m compileall src demo_full_chain.py
python -m pytest
python demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report reports/gear.json

然后运行 grep：
grep -R "solidworks_create_spur_gear_part" src/seekflow_engineering_tools || true
grep -R "solidworks_create_true_involute_gear_part" src/seekflow_engineering_tools || true
grep -R "create_spur_gear_true_involute\|create_spur_gear_involute\|create_spur_gear_star" src/seekflow_engineering_tools || true
grep -R "star-polygon\|visual gear\|triangular teeth" src/seekflow_engineering_tools || true
grep -R "return {\"ok\": True, \"results\": \[\]}" src/seekflow_engineering_tools || true
grep -R "best-effort" src/seekflow_engineering_tools || true
grep -R "tempfile.mktemp" src/seekflow_engineering_tools || true

如果 grep 命中 legacy gear，必须确认：
1. 不注册为 tool。
2. 不被 engineering_build_cad_model 调用。
3. docstring 明确 legacy/demo/not engineering-grade。
4. 有测试覆盖不注册、不路由。
```

---

# 15. 最终验收标准

修完后必须满足：

```text
1. python -m compileall src demo_full_chain.py 全部通过。
2. spur_gear 不再是工程级 stable recipe。
3. deprecated spur_gear 会 rewrite 成 involute_spur_gear primitive。
4. engineering_validate_cad_ir normalize recipe 和 primitive。
5. engineering_build_cad_model 是唯一推荐统一入口。
6. CadQuery primitive 输出 STEP + metadata.json。
7. metadata 包含 kernel、primitive、parameters、reference_dimensions、is_standard_involute。
8. mechanical validation hard-check pitch/base/outer/root/face_width/kernel/fallback。
9. cadquery_visual_fallback 默认不能 industrial_brep 成功。
10. SolidWorks/NX gear primitive 只走 CadQuery/CQ_Gears STEP import。
11. SolidWorks legacy gear tool 不注册。
12. NX 注册 nx_import_step_as_prt，并检查 .prt 存在且非空。
13. ANSYS 模板和 parser fail-closed。
14. demo_full_chain.py 可作为 CI 验收脚本。
15. pytest 覆盖 primitive、gear、metadata、legacy rewrite、SW/NX import、demo。
```

一句话：**现在不是继续补 CAD 曲线数学，而是要清理危险旁路、强制 canonical STEP 管线、把所有 validation 改成 fail-closed，并用 demo/tests 锁死回归。**

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/tools.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/gear_validation.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx/job_queue.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/demo_full_chain.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/backend_builders.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx/tools.py "raw.githubusercontent.com"
