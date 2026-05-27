

# SeekFlow Engineering 修复执行文档

## 0. 总目标

把当前仓库从“primitive / CadQuery 局部可用、商业 CAD 后端接线不完整”的状态，修成下面这个闭环：

```text
Natural Language
→ CAD-IR
→ recipe / primitive normalization
→ deprecated recipe rewrite
→ capability router
→ build planner
→ CadQuery / CQ_Gears canonical STEP
→ metadata sidecar
→ inspection
→ mechanical validation
→ SolidWorks / NX import STEP + save native
→ EngineeringActionResult
→ demo_full_chain / tests 可回归验收
```

绝对不要让 LLM、SolidWorks VBS、NXOpen journal 重新生成复杂机械曲线。复杂机械对象，尤其 `involute_spur_gear`，必须由 deterministic primitive kernel 生成。用户给定的目标文档明确要求：LLM 只负责理解意图、抽取参数、选择 recipe/primitive、输出 CAD-IR 和根据 diagnostics 修正 CAD-IR；不应该直接写 SolidWorks COM/VBS、NXOpen、ANSYS APDL 或现场推导渐开线、螺纹、弹簧、凸轮曲线。

---

# 1. 当前代码的关键问题

## 1.1 Capability 声明与实际执行断开

`capabilities/registry.py` 已经声明了：

```python
solidworks2025:
  stable_primitives: ["involute_spur_gear"]
  primitive_strategy:
    involute_spur_gear: cadquery_step_import

nx12:
  stable_primitives: ["involute_spur_gear"]
  primitive_strategy:
    involute_spur_gear: cadquery_step_import

cadquery:
  primitive_strategy:
    involute_spur_gear: native_cadquery_primitive
```

并且 `BackendChoice`、`backend_supports_feature`、`get_primitive_strategy`、`choose_backend` 已经存在。([GitHub][1])

但是 `natural_language/tools.py` 的 `engineering_build_cad_model` 只按 `choice.backend` 分支：

```python
if choice.backend == "cadquery":
    build_cadquery_from_cad_ir(...)
elif choice.backend == "solidworks2025":
    return _build_solidworks_from_spec(...)
elif choice.backend == "nx12":
    return _build_nx_from_spec(...)
```

没有读取 `get_primitive_strategy`，也没有执行 `cadquery_step_import`。([GitHub][2])

## 1.2 SolidWorks / NX builder 仍是 recipe-only

`_build_solidworks_from_spec` 直接：

```python
recipe_feat = next(f for f in spec.features if f.type == "recipe")
```

然后支持 `box / flanged_hub / spur_gear`，其中 `spur_gear` 又调用 `client.create_spur_gear(...)`。([GitHub][2])

`_build_nx_from_spec` 也直接：

```python
recipe_feat = next(f for f in spec.features if f.type == "recipe")
```

然后只映射 `box / block_with_hole / l_bracket / stepped_block`，没有 primitive，也没有 STEP import action。([GitHub][2])

这意味着：即使 capability 说 SW/NX 支持 `involute_spur_gear`，实际执行时仍不支持。

## 1.3 SolidWorks 仍暴露工程级禁用的齿轮工具

`solidworks/tools.py` 仍注册：

```python
solidworks_create_spur_gear_part
solidworks_create_true_involute_gear_part
```

并加入 `tools.extend([...])`。([GitHub][3])

其中 `solidworks_create_spur_gear_part` 描述为 star-polygon gear body；`solidworks_create_true_involute_gear_part` 描述为用 involute curve equation 创建齿轮。([GitHub][3]) ([GitHub][3])

这违反目标架构：SolidWorks/NX 对复杂 primitive 只应 import STEP，不应重写齿形。用户文档还明确要求不得把 star-polygon / visual gear / triangular teeth approximation 当作工业级齿轮。

## 1.4 SolidWorks COM client 内仍有复杂齿形生成旁路

`solidworks/com_client.py` 中仍有：

```python
create_spur_gear_star
create_spur_gear_involute
create_spur_gear_true_involute
```

其中 `create_spur_gear_involute` 注释说明是“smoothed tooth flanks / approximate involute curve shape”，并用 polygon/interpolated points 近似。`create_spur_gear_true_involute` 声称按 ISO 53 / DIN 867 生成标准 involute spur gear。([GitHub][4]) ([GitHub][4])

这些可以暂时保留为内部 legacy/demo 函数，但不能被默认 tool registry 暴露，不能被 unified build 使用，不能被 capability 标记为工程级成功路径。

## 1.5 `engineering_validate_cad_ir` 只规范化 recipe，没有规范化 primitive

`engineering_validate_cad_ir` 当前会尝试 rewrite deprecated recipe，但异常被吞掉：

```python
try:
    spec = rewrite_deprecated_recipes_to_primitives(spec)
except Exception:
    pass
```

然后只对 `feat.type == "recipe"` 调 `normalize_recipe_parameters`，没有对 primitive 调 `normalize_primitive_parameters`，也没有把 normalized primitive parameters 回写到 spec 或 metrics。([GitHub][2])

而 primitive registry 已经提供了 `normalize_primitive_parameters`，会检查 unknown parameter、类型转换、默认值、min/max 等。([GitHub][5])

## 1.6 CadQuery builder 仍有假成功风险

`cadquery_backend/builder.py` 的 `_run_mechanical_validation` 在 import mechanical validation 失败时返回：

```python
{"ok": True, "results": []}
```

这是明确的假成功。([GitHub][6])

另外，primitive build 时如果 metadata sidecar 不存在，当前只是没有加入 `files_created`，但没有 hard fail。目标要求 primitive build 输出 STEP + metadata，metadata 必须包含 kernel、primitive、parameters、reference_dimensions。

## 1.7 Fallback gear 仍可 `ok=True`

当前 builder 检测 fallback warning 后返回 `ok=True`，只是 message 写 “with fallback warnings”。([GitHub][6])

这不够。对于 `quality_grade="industrial_brep"`，fallback visual gear 不应等同成功；至少要 `ok=False`，或返回 `ok=True` 但 `engineering_grade=False` 并让 demo/CI 判失败。建议直接 hard fail，除非 CAD-IR 明确允许 `quality_grade="visual_fallback"` 或 `allow_visual_fallback=True`。

## 1.8 NX 没有 STEP import action

我检索了 `nx/job_queue.py` 和 NX 目录，没有找到 `import_step` 相关动作。([GitHub][7]) ([GitHub][8])

因此 `nx12` 的 `primitive_strategy: cadquery_step_import` 当前只是配置声明，没有可执行 handler。

## 1.9 demo_full_chain 不是严格 CI 验收脚本

用户目标要求 demo 支持：

```bash
python demo_full_chain.py --case box --backend cadquery
python demo_full_chain.py --case flanged_hub --backend cadquery
python demo_full_chain.py --case involute_spur_gear --backend cadquery
python demo_full_chain.py --case involute_spur_gear --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case all --backend cadquery --json-report reports/full_chain.json
```

并要求 gear report 包含 `stages.validate_cad_ir / normalize_primitives / choose_backend / build / inspect / mechanical_validate`，失败时 `sys.exit(1)`。

当前 demo 的 CLI 和执行逻辑需要重构为真正 case runner，而不是演示式串行打印。

---

# 2. Claude Code 必须执行的 P0 修复任务

## P0-1：新增 Build Planner，真正消费 `primitive_strategy`

### 目标

让 `engineering_build_cad_model` 不再只按 backend 粗暴分支，而是按 feature 类型 + capability strategy 规划执行。

### 文件

重点修改：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py
integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/backend_builders.py  # 新增
integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py
```

### 实现要求

新增 `backend_builders.py`，把现在 `tools.py` 里的 `_build_solidworks_from_spec`、`_build_nx_from_spec` 迁移进去，并新增：

```python
def spec_has_primitives(spec: CADPartSpec) -> bool: ...

def get_single_primitive_name(spec: CADPartSpec) -> str | None: ...

def build_canonical_step_with_cadquery(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    inspect: bool = True,
) -> dict: ...

def build_solidworks_from_canonical_step(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    out_native: str | Path | None = None,
    inspect: bool = True,
) -> dict: ...

def build_nx_from_canonical_step(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    out_native: str | Path | None = None,
    inspect: bool = True,
) -> dict: ...
```

`engineering_build_cad_model` 逻辑应变成：

```python
cad_spec = CADPartSpec.model_validate(spec)
choice = choose_backend(cad_spec, preferred=[backend])

if choice.backend == "cadquery":
    return build_cadquery_from_cad_ir(...)

if choice.backend in {"solidworks2025", "nx12"}:
    primitive_features = [f for f in cad_spec.features if f.type == "primitive"]

    if primitive_features:
        for f in primitive_features:
            strategy = get_primitive_strategy(choice.backend, f.primitive_name)
            if strategy != "cadquery_step_import":
                return EngineeringActionResult(ok=False, ...)

        if choice.backend == "solidworks2025":
            return build_solidworks_from_canonical_step(...)
        if choice.backend == "nx12":
            return build_nx_from_canonical_step(...)

    # no primitive: old recipe-only path allowed
    if choice.backend == "solidworks2025":
        return build_solidworks_direct_recipe(...)
    if choice.backend == "nx12":
        return build_nx_direct_recipe(...)
```

### 关键验收

对下面 CAD-IR：

```json
{
  "part_name": "gear",
  "target_backend": ["solidworks2025"],
  "features": [
    {
      "id": "gear1",
      "type": "primitive",
      "primitive_name": "involute_spur_gear",
      "parameters": {
        "module_mm": 2,
        "teeth": 24,
        "face_width_mm": 10,
        "bore_dia_mm": 10
      },
      "operation": "new_body"
    }
  ]
}
```

`engineering_build_cad_model(... backend="solidworks2025")` 必须执行：

```text
CadQuery/CQ_Gears build STEP
→ assert STEP exists
→ assert metadata exists
→ inspection
→ mechanical validation
→ SolidWorks import STEP
→ assert SLDPRT exists
```

不能调用：

```python
client.create_spur_gear(...)
client.create_spur_gear_involute(...)
client.create_spur_gear_true_involute(...)
```

---

## P0-2：修复 `engineering_validate_cad_ir` 的 primitive normalization

### 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py
integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/normalizer.py
```

### 当前问题

现在 validate 只 normalize recipe，不 normalize primitive；rewrite 异常被吞掉。([GitHub][2])

### 实现要求

在 `engineering_validate_cad_ir` 中：

1. 调用 `rewrite_deprecated_recipes_to_primitives`，如果失败，返回 `ok=False`，不要 `pass`。
2. `CADPartSpec.model_validate(spec)` 后遍历所有 feature：

   * recipe：`normalize_recipe_parameters`
   * primitive：`normalize_primitive_parameters`
3. 对 primitive 的 normalized params 必须：

   * 写入 `metrics["normalized_parameters"][feature.id]`
   * 最好回写到 `normalized.features[i].parameters`
   * `EngineeringActionResult.metrics["normalized_spec"]` 中返回完整规范化 CAD-IR
4. backend support 检查必须用 `backend_supports_feature`，不能只用 `backend_supports_recipe`。
5. 如果 primitive unknown parameter、teeth < 6、bore 过大等，必须 `ok=False`。

### 伪代码

```python
from seekflow_engineering_tools.geometry_primitives.registry import normalize_primitive_parameters
from seekflow_engineering_tools.capabilities.registry import backend_supports_feature

try:
    spec = rewrite_deprecated_recipes_to_primitives(spec)
except Exception as exc:
    return EngineeringActionResult(
        ok=False,
        software="generic",
        action="validate_cad_ir",
        error=f"Deprecated recipe rewrite failed: {exc}",
    ).model_dump()

normalized = CADPartSpec.model_validate(spec)

normalized_params = {}
for idx, feat in enumerate(normalized.features):
    try:
        if feat.type == "recipe":
            n = normalize_recipe_parameters(feat.recipe_name, feat.parameters)
            feat.parameters = n
        elif feat.type == "primitive":
            n = normalize_primitive_parameters(feat.primitive_name, feat.parameters)
            feat.parameters = n
        else:
            continue
        normalized_params[feat.id] = n
    except ValueError as exc:
        errors.append(f"Feature '{feat.id}': {exc}")

for backend in normalized.target_backend:
    for feat in normalized.features:
        if not backend_supports_feature(backend, feat):
            errors.append(...)
```

### 测试

新增：

```text
tests/test_validate_cad_ir_primitives.py
```

必须覆盖：

```python
def test_validate_primitive_fills_defaults():
    # pressure_angle_deg, clearance, backlash 等默认值出现在 normalized_parameters

def test_validate_primitive_rejects_unknown_parameter():
    # foo=123 => ok False

def test_validate_primitive_rejects_teeth_lt_6():
    # teeth=5 => ok False

def test_validate_rewrites_spur_gear_recipe_to_primitive():
    # recipe spur_gear => primitive involute_spur_gear

def test_validate_does_not_swallow_rewrite_failure(monkeypatch):
    # monkeypatch rewrite 抛异常，结果 ok False
```

---

## P0-3：CadQuery builder 必须 fail-closed

### 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py
```

### 当前问题

`_run_mechanical_validation` ImportError 时返回 ok true。([GitHub][6])

### 修复要求

改成：

```python
except ImportError as exc:
    return {
        "ok": False,
        "results": [],
        "issues": [
            {
                "code": "mechanical_validation_unavailable",
                "message": f"Mechanical validation module could not be imported: {exc}",
                "severity": "error",
            }
        ],
    }
```

同时：

1. `has_primitive=True` 时，`meta_path` 必须存在且非空。
2. `meta_path` 不存在时，直接返回 `ok=False`。
3. metadata JSON 解析失败时返回 `ok=False`。
4. metadata 缺少 `primitive_metadata` / `build_warnings` 时返回 `ok=False`。
5. 对 gear primitive，metadata 中必须包含：

   * `primitive`
   * `kernel`
   * `parameters`
   * `reference_dimensions`
   * `is_standard_involute`
6. fallback warning 对 `quality_grade="industrial_brep"` 必须 hard fail。

### 建议新增 helper

```python
def _assert_metadata_sidecar(step_path: Path, spec: CADPartSpec) -> dict:
    meta_path = step_path.with_suffix(".metadata.json")
    assert_file_created(meta_path, "metadata")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))

    if "primitive_metadata" not in metadata:
        raise ValueError("metadata missing primitive_metadata")
    if "build_warnings" not in metadata:
        raise ValueError("metadata missing build_warnings")

    for feat in spec.features:
        if feat.type == "primitive" and feat.primitive_name == "involute_spur_gear":
            # find metadata for this primitive
            # assert kernel, reference_dimensions, parameters
            ...
    return metadata
```

### Fallback policy

如果 metadata 或 warnings 表明：

```text
kernel = cadquery_visual_fallback
is_standard_involute = false
not certified involute geometry
```

则：

```python
if feat.parameters.get("quality_grade", "industrial_brep") in {"industrial_brep", "validated"}:
    return EngineeringActionResult(
        ok=False,
        message="STEP created but fallback gear is not engineering-grade.",
        warnings=warnings,
        error="Visual fallback is not certified involute geometry.",
        ...
    )
```

允许 fallback 成功的唯一情况：

```json
{
  "quality_grade": "visual_fallback"
}
```

或另加显式参数：

```json
{
  "allow_visual_fallback": true
}
```

但默认必须 fail-closed。

### 测试

新增：

```text
tests/test_cadquery_builder_fail_closed.py
```

覆盖：

```python
def test_mechanical_validation_import_error_fails(monkeypatch):
    ...

def test_primitive_requires_metadata_sidecar(tmp_path, monkeypatch):
    ...

def test_industrial_gear_visual_fallback_fails(monkeypatch):
    ...

def test_visual_fallback_can_pass_only_when_explicitly_allowed(monkeypatch):
    ...
```

---

## P0-4：SolidWorks 只允许 STEP import 处理 gear primitive

### 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/com_client.py
integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/tools.py
integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/backend_builders.py
```

### 必须新增

在 `SolidWorksClient` 中新增：

```python
def import_step_as_part(self, step_path: str | Path, out_sldprt: str | Path) -> bool:
    """
    Open canonical STEP in SolidWorks and save as SLDPRT.
    Must return True only if out_sldprt exists and size > 0.
    """
```

实现要求：

1. `step_path` 必须存在且非空。
2. `out_sldprt` parent 创建。
3. 使用 SolidWorks API 打开 STEP：

   * 可用 `OpenDoc6(str(step_path), swDocPART, ...)`
   * 或 SolidWorks 支持的 import data API
4. 保存 `.sldprt`。
5. 保存后必须 `exists + size > 0`。
6. 失败时返回 False 或抛异常，不能 best-effort 成功。

### 新增 tool

在 `solidworks/tools.py` 新增：

```python
@tool(name="solidworks_import_step_as_part", ...)
def solidworks_import_step_as_part(input_step: str, out_sldprt: str) -> dict:
    ...
```

返回：

```python
EngineeringActionResult(
    ok=True,
    software="solidworks",
    action="import_step_as_part",
    files_created=[str(out_sldprt_path)],
    warnings=["Native SLDPRT created by importing canonical STEP; feature tree is not regenerated."],
    metrics={
        "source_step": str(step_path),
        "native_path": str(out_sldprt_path),
        "strategy": "cadquery_step_import",
    },
)
```

### 必须移除默认注册

在 `tools.extend([...])` 中删除：

```python
solidworks_create_spur_gear_part
solidworks_create_true_involute_gear_part
```

当前它们被注册在 tools list 中。([GitHub][3])

保留方式：

1. 函数可以保留，但重命名为：

   * `_legacy_solidworks_create_spur_gear_visual_demo`
   * `_legacy_solidworks_create_true_involute_gear_demo`
2. 不加 `@tool`。
3. 不进入 `tools.extend`。
4. docstring 必须写：

   * not engineering-grade
   * not used by unified build
   * use `involute_spur_gear` primitive + STEP import instead

### 禁止

不要让 `_build_solidworks_from_spec` 对 `recipe_name == "spur_gear"` 调 `client.create_spur_gear(...)`。当前有这个调用，必须删除或改成 hard fail。([GitHub][2])

新的 recipe direct builder 只允许：

```text
box
flanged_hub
```

如果收到 `spur_gear` recipe，必须返回：

```text
ok=False
error="Recipe 'spur_gear' is deprecated for engineering builds; use primitive 'involute_spur_gear'."
```

---

## P0-5：NX 增加 STEP import → PRT 保存

### 文件

需要 Claude Code 先审阅 NX 当前结构，再落地到对应文件：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/nx/job_queue.py
integrations/engineering_tools/src/seekflow_engineering_tools/nx/bridge.py
integrations/engineering_tools/src/seekflow_engineering_tools/nx/tools.py
integrations/engineering_tools/src/seekflow_engineering_tools/nx/*.py
```

当前 `nx/job_queue.py` 没有 `import_step` 相关动作。([GitHub][7])

### 必须实现的 action

```text
action: import_step_as_prt
params:
  input_step: str
  out_prt: str
  out_step: optional str
```

### 预期行为

```text
canonical STEP exists + non-empty
→ submit NX job import_step_as_prt
→ NX bridge / journal imports STEP into part
→ saves native .prt
→ optional exports/copies STEP
→ result ok only if .prt exists + non-empty
```

### bridge/journal 伪代码

具体 API 让 Claude Code 根据仓库现有 NX bridge 风格实现，目标行为必须类似：

```python
def handle_import_step_as_prt(params):
    input_step = Path(params["input_step"])
    out_prt = Path(params["out_prt"])

    assert input_step.exists() and input_step.stat().st_size > 0

    # NXOpen pseudo:
    # importer = session.DexManager.CreateStep214Importer()
    # importer.InputFile = str(input_step)
    # importer.OutputFile = str(out_prt) or import into current part then SaveAs(out_prt)
    # importer.Commit()
    # importer.Destroy()
    # work_part.SaveAs(str(out_prt))

    assert out_prt.exists() and out_prt.stat().st_size > 0

    return {
        "ok": True,
        "message": "NX PRT created by importing canonical STEP.",
        "files_created": [str(out_prt)],
        "metrics": {
            "strategy": "cadquery_step_import",
            "source_step": str(input_step),
            "native_path": str(out_prt),
        },
        "warnings": [
            "Native PRT created by importing canonical STEP; NX feature tree is not regenerated."
        ],
    }
```

### 禁止

不要在 NXOpen 中重新写 involute 曲线、齿形 polyline、gear tooth sketch。NX 只 import STEP。

### 测试

新增：

```text
tests/test_nx_step_import_strategy.py
```

覆盖：

```python
def test_nx_primitive_build_submits_import_step_job(monkeypatch):
    # monkeypatch CadQuery build returns ok + step + metadata
    # monkeypatch NXJobQueue.submit/wait
    # assert action == "import_step_as_prt"

def test_nx_import_step_requires_native_file(monkeypatch):
    # wait result ok True 但 files missing => unified builder 必须 ok False
```

---

## P0-6：修复 `demo_full_chain.py` 为 CI 级验收脚本

### 文件

```text
integrations/engineering_tools/demo_full_chain.py
```

### 必须重构

不要再写“演示式”大串流程。改成明确的 case runner：

```python
def build_case_spec(case: str, backend: str) -> dict: ...

def run_case(case: str, backend: str, output_root: Path, allow_step_import: bool) -> dict:
    report = {
        "overall_ok": False,
        "case": case,
        "backend": backend,
        "stages": {},
        "files_created": [],
        "metrics": {},
        "warnings": [],
        "errors": [],
    }

    # stage 1 validate_cad_ir
    # stage 2 normalize_primitives
    # stage 3 choose_backend
    # stage 4 build
    # stage 5 inspect
    # stage 6 mechanical_validate

    return report
```

### CLI 必须支持

```bash
python demo_full_chain.py --case box --backend cadquery
python demo_full_chain.py --case flanged_hub --backend cadquery
python demo_full_chain.py --case involute_spur_gear --backend cadquery
python demo_full_chain.py --case involute_spur_gear --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case involute_spur_gear --backend nx12 --allow-step-import
python demo_full_chain.py --case all --backend cadquery --json-report reports/full_chain.json
```

### Gear case 输出要求

```text
models/involute_spur_gear.step
models/involute_spur_gear.metadata.json
reports/gear.json
```

### Gear report 必须包含

```json
{
  "overall_ok": true,
  "case": "involute_spur_gear",
  "backend": "cadquery",
  "stages": {
    "validate_cad_ir": {"ok": true},
    "normalize_primitives": {"ok": true},
    "choose_backend": {"ok": true},
    "build": {"ok": true},
    "inspect": {"ok": true},
    "mechanical_validate": {"ok": true}
  },
  "files_created": [
    "models/involute_spur_gear.step",
    "models/involute_spur_gear.metadata.json"
  ],
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

### 退出码

```python
if not overall_ok:
    sys.exit(1)
sys.exit(0)
```

必须保证 `--case all --json-report reports/full_chain.json` 也写报告，也按失败退出非 0。

### 测试

新增：

```text
tests/test_demo_full_chain_gear.py
```

覆盖：

```python
def test_demo_full_chain_gear_cadquery_json_report(tmp_path):
    # 可 monkeypatch build 或用真实 CadQuery，视 CI 环境决定
    # 必须验证 report schema

def test_demo_full_chain_failure_exits_nonzero(tmp_path):
    # 故意传 invalid case/backend 或 monkeypatch failure
```

---

# 3. P1 修复任务

## P1-1：移除工程级 `spur_gear` recipe

### 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/recipes/mechanical.py
integrations/engineering_tools/src/seekflow_engineering_tools/recipes/registry.py
integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py
integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/recipes.py
```

### 当前问题

`cadquery` capability 仍把 `spur_gear` 放在 stable_recipes，SolidWorks 也有 `spur_gear` direct recipe。([GitHub][1])

### 要求

1. 工程级 `stable_recipes` 删除 `spur_gear`。
2. 如需 demo，改名为：

   * `spur_gear_visual_legacy`
   * 或 `visual_spur_gear_demo`
3. `recipe_name == "spur_gear"` 必须 rewrite 成 primitive。
4. 如果 explicit visual legacy，必须 metadata / warnings 明确：

   * not engineering-grade
   * not certified involute geometry
   * do not use for manufacturing / CAE

### 测试

```text
tests/test_no_legacy_gear_for_engineering.py
```

覆盖：

```python
def test_spur_gear_not_in_stable_engineering_recipes():
    ...

def test_spur_gear_recipe_rewrites_to_involute_primitive():
    ...

def test_visual_gear_requires_explicit_legacy_name():
    ...
```

---

## P1-2：增强 gear mechanical validation

### 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/gear_validation.py
integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/common.py
```

### 必须检查

对 `involute_spur_gear`：

```text
metadata sidecar exists
metadata primitive == involute_spur_gear
kernel in {"cq_gears"} for industrial_brep
is_standard_involute == true
parameters.module_mm matches spec
parameters.teeth matches spec
parameters.face_width_mm matches spec
reference_dimensions.pitch/base/outer/root present
pitch/base/outer/root formulas within tolerance
face_width within tolerance
expected_body_count
expected_kernel
fallback warning impossible for industrial_brep
```

### 错误级别

以下必须是 error：

```text
metadata missing
primitive_metadata missing
kernel missing
kernel cadquery_visual_fallback with industrial_brep
is_standard_involute false with industrial_brep
reference_dimensions missing
pitch diameter mismatch
outer diameter mismatch
root diameter mismatch
base diameter mismatch
face width mismatch
body count mismatch
```

warning 只用于非关键提醒，不能替代 error。

---

## P1-3：补 `.claude/skills`

### 目录

```text
.claude/skills/
```

### 必须存在

```text
industrial-text-to-cad/SKILL.md
geometry-primitives/SKILL.md
involute-gears/SKILL.md
cadquery-cq-gears/SKILL.md
solidworks-step-import/SKILL.md
nx-step-import/SKILL.md
```

### 每个 skill 必须包含红线

```text
- 不得从自然语言直接生成 SolidWorks COM/VBS 或 NXOpen 复杂几何。
- 复杂机械对象必须走 CAD-IR primitive。
- 齿轮必须使用 involute_spur_gear primitive。
- CQ_Gears 是首选齿轮 kernel。
- CadQuery/CQ_Gears 输出 canonical STEP。
- SolidWorks/NX 只 import STEP 并保存 native。
- fallback visual gear 不能作为工业级成功。
- 文件不存在、metadata 不存在、validation fail 不得 ok=True。
```

---

## P1-4：pyproject optional dependencies

### 文件

```text
integrations/engineering_tools/pyproject.toml
```

### 要求

确保存在：

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

不要把 `cq-gears` 放进最小安装依赖，避免破坏基础安装。

---

# 4. 必须新增 / 修改的测试清单

Claude Code 必须补齐以下测试。不要只写 happy path，要写 fail-closed 测试。

```text
tests/test_geometry_primitives_registry.py
tests/test_involute_spur_gear_parameters.py
tests/test_involute_spur_gear_dimensions.py
tests/test_involute_spur_gear_cadquery_build.py
tests/test_gear_metadata_sidecar.py
tests/test_gear_validation.py
tests/test_demo_full_chain_gear.py
tests/test_no_legacy_gear_for_engineering.py
tests/test_primitive_feature_schema.py
tests/test_capability_registry_primitives.py
tests/test_engineering_validate_cad_ir_primitives.py
tests/test_engineering_build_cad_model_primitive_routing.py
tests/test_solidworks_step_import_strategy.py
tests/test_nx_step_import_strategy.py
tests/test_cadquery_builder_fail_closed.py
```

核心断言：

```python
def test_capability_registry_has_primitive_strategies():
    assert get_primitive_strategy("cadquery", "involute_spur_gear") == "native_cadquery_primitive"
    assert get_primitive_strategy("solidworks2025", "involute_spur_gear") == "cadquery_step_import"
    assert get_primitive_strategy("nx12", "involute_spur_gear") == "cadquery_step_import"

def test_build_model_solidworks_primitive_uses_cadquery_step_import(monkeypatch):
    # assert build_cadquery_from_cad_ir called
    # assert solidworks_import_step_as_part called
    # assert client.create_spur_gear not called

def test_build_model_nx_primitive_uses_import_step_job(monkeypatch):
    # assert NXJobQueue.submit action == "import_step_as_prt"

def test_solidworks_legacy_gear_tools_not_registered():
    names = {t.name for t in build_solidworks_tools(config)}
    assert "solidworks_create_spur_gear_part" not in names
    assert "solidworks_create_true_involute_gear_part" not in names
    assert "solidworks_import_step_as_part" in names

def test_metadata_missing_fails_primitive_build(monkeypatch):
    ...

def test_mechanical_validation_unavailable_fails(monkeypatch):
    ...

def test_demo_full_chain_report_schema():
    ...
```

---

# 5. 必须运行的验收命令

Claude Code 完成后必须运行：

```bash
cd integrations/engineering_tools
python -m pytest
```

再运行静态检查：

```bash
grep -R "solidworks_create_spur_gear_part" src/seekflow_engineering_tools || true
grep -R "solidworks_create_true_involute_gear_part" src/seekflow_engineering_tools || true
grep -R "create_spur_gear_true_involute\|create_spur_gear_involute\|create_spur_gear_star" src/seekflow_engineering_tools || true
grep -R "star-polygon\|visual gear\|triangular teeth" src/seekflow_engineering_tools || true
grep -R "return {\"ok\": True, \"results\": \[\]}" src/seekflow_engineering_tools || true
grep -R "tempfile.mktemp" src/seekflow_engineering_tools || true
grep -R "best-effort" src/seekflow_engineering_tools || true
```

注意：这些 grep 不是都必须零结果。例如 legacy 函数可以保留，但如果 grep 命中，必须确认：

```text
1. 不在 tool registry。
2. 不在 engineering_build_cad_model 路径。
3. docstring 明确 legacy/demo/not engineering-grade。
4. 测试覆盖“不注册、不路由、不成功”。
```

必须运行 demo：

```bash
python demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report reports/gear.json
```

如果本机没有 SolidWorks/NX，可以通过 mock 测试验证 routing；如果有实机环境，再运行：

```bash
python demo_full_chain.py --case involute_spur_gear --backend solidworks2025 --allow-step-import --json-report reports/gear_solidworks.json
python demo_full_chain.py --case involute_spur_gear --backend nx12 --allow-step-import --json-report reports/gear_nx.json
```

---

# 6. 给 Claude Code 的完整执行 Prompt

下面这段可以直接复制给 Claude Code：

```text
你正在修复 WYZAAACCC/seekflow-engineering 仓库中的 integrations/engineering_tools 子项目。请严格按以下目标执行，不要只做表面改名。

最终目标：
实现工业级 Text-to-CAD 第一阶段闭环：
Natural Language → CAD-IR → recipe/primitive normalization → capability routing → build planner → CadQuery/CQ_Gears canonical STEP → metadata.json → inspection → mechanical validation → SolidWorks/NX import STEP + save native → EngineeringActionResult → demo_full_chain/tests 验收。

绝对原则：
1. LLM 不直接生成 SolidWorks COM/VBS、NXOpen journal、ANSYS APDL 复杂模板。
2. LLM 不现场推导 involute gear、thread、spring、cam 曲线。
3. involute_spur_gear 必须是 deterministic primitive。
4. CadQuery/CQ_Gears 是 canonical BREP/STEP 生成路径。
5. SolidWorks/NX 对 gear primitive 只 import STEP 并保存 native，不重新生成齿形。
6. 文件不存在、STEP 为空、metadata 缺失、validation fail、mechanical validation 不可用时，绝不能 ok=True。
7. cadquery_visual_fallback 不能作为 industrial_brep 成功，除非 CAD-IR 显式请求 visual_fallback。

请先阅读这些文件：
- integrations/engineering_tools/src/seekflow_engineering_tools/ir/cad.py
- integrations/engineering_tools/src/seekflow_engineering_tools/ir/primitive.py
- integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/
- integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/gears/
- integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py
- integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py
- integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py
- integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/compiler.py
- integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/
- integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/tools.py
- integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/com_client.py
- integrations/engineering_tools/src/seekflow_engineering_tools/nx/
- integrations/engineering_tools/demo_full_chain.py
- integrations/engineering_tools/tests/

任务 1：实现真正的 build planner。
- 新增 natural_language/backend_builders.py。
- 迁移 recipe direct builders。
- 新增 build_canonical_step_with_cadquery。
- 新增 build_solidworks_from_canonical_step。
- 新增 build_nx_from_canonical_step。
- engineering_build_cad_model 必须读取 get_primitive_strategy。
- solidworks2025/nx12 的 involute_spur_gear 必须走 cadquery_step_import。
- 不得调用 SolidWorks/NX 齿形生成函数。

任务 2：修 engineering_validate_cad_ir。
- rewrite_deprecated_recipes_to_primitives 失败必须 ok=False。
- recipe 调 normalize_recipe_parameters。
- primitive 调 normalize_primitive_parameters。
- backend support 检查用 backend_supports_feature。
- normalized spec / normalized parameters 放入 metrics。
- primitive unknown param、teeth<6、bore 过大必须 ok=False。

任务 3：修 CadQuery builder fail-closed。
- mechanical_validation import 失败必须 ok=False。
- primitive build 必须要求 metadata sidecar 存在且非空。
- metadata 必须包含 primitive_metadata、build_warnings。
- gear metadata 必须包含 primitive/kernel/parameters/reference_dimensions/is_standard_involute。
- cadquery_visual_fallback 对 industrial_brep 必须失败。
- STEP、metadata、script 都必须在 workspace 内。

任务 4：SolidWorks STEP import。
- SolidWorksClient 新增 import_step_as_part(input_step, out_sldprt)。
- 新增 tool solidworks_import_step_as_part。
- 返回 warnings: Native SLDPRT created by importing canonical STEP; feature tree is not regenerated.
- 输出 SLDPRT 必须 exists + size > 0 才 ok=True。
- 从 tool registry 删除 solidworks_create_spur_gear_part 和 solidworks_create_true_involute_gear_part。
- 如保留旧函数，改成 legacy/demo/internal，不加 @tool，不进 tools.extend，docstring 明确 not engineering-grade。
- _build_solidworks_direct_recipe 不再支持 spur_gear；收到 spur_gear 必须报错让用户用 primitive。

任务 5：NX STEP import。
- 新增 NX job action import_step_as_prt。
- 参数 input_step/out_prt/out_step optional。
- NX bridge/journal 只 import canonical STEP 并 save PRT。
- 输出 PRT 必须 exists + size > 0 才 ok=True。
- warnings: Native PRT created by importing canonical STEP; feature tree is not regenerated.
- 不要在 NXOpen 中生成 involute 齿形。

任务 6：重构 demo_full_chain.py。
- 实现真正 --case / --backend 控制。
- 支持：
  python demo_full_chain.py --case box --backend cadquery
  python demo_full_chain.py --case flanged_hub --backend cadquery
  python demo_full_chain.py --case involute_spur_gear --backend cadquery
  python demo_full_chain.py --case involute_spur_gear --backend solidworks2025 --allow-step-import
  python demo_full_chain.py --case involute_spur_gear --backend nx12 --allow-step-import
  python demo_full_chain.py --case all --backend cadquery --json-report reports/full_chain.json
- gear report 必须包含：
  overall_ok
  case
  backend
  stages.validate_cad_ir
  stages.normalize_primitives
  stages.choose_backend
  stages.build
  stages.inspect
  stages.mechanical_validate
  files_created
  metrics.kernel_used
  metrics.reference_dimensions.pitch_diameter_mm
  metrics.reference_dimensions.base_diameter_mm
  metrics.reference_dimensions.outer_diameter_mm
  metrics.reference_dimensions.root_diameter_mm
- 失败必须 sys.exit(1)，包括 --case all。

任务 7：补测试。
至少新增/修改：
- test_engineering_validate_cad_ir_primitives.py
- test_engineering_build_cad_model_primitive_routing.py
- test_solidworks_step_import_strategy.py
- test_nx_step_import_strategy.py
- test_cadquery_builder_fail_closed.py
- test_no_legacy_gear_for_engineering.py
- test_demo_full_chain_gear.py
- test_gear_metadata_sidecar.py
- test_gear_validation.py
- test_capability_registry_primitives.py

必须测试：
- solidworks/nx primitive 会先 build cadquery STEP，再 import native。
- legacy SolidWorks gear tools 不再注册。
- spur_gear recipe rewrite 成 involute_spur_gear primitive。
- primitive 参数默认值、unknown 参数、teeth<6、bore 过大。
- mechanical_validation import error fails。
- metadata missing fails。
- visual fallback industrial_brep fails。
- demo report schema 和 exit code。

任务 8：补 .claude/skills。
新增或更新：
.claude/skills/industrial-text-to-cad/SKILL.md
.claude/skills/geometry-primitives/SKILL.md
.claude/skills/involute-gears/SKILL.md
.claude/skills/cadquery-cq-gears/SKILL.md
.claude/skills/solidworks-step-import/SKILL.md
.claude/skills/nx-step-import/SKILL.md
规则必须写清：
- 不得从自然语言直接生成后端 CAD API。
- 复杂机械对象必须是 primitive。
- 齿轮必须使用 involute_spur_gear primitive。
- CQ_Gears 是首选齿轮 kernel。
- fallback 必须 warning 且不能 industrial_brep 成功。
- SolidWorks/NX 只 import STEP，不重新生成齿形。

任务 9：运行验收。
运行：
cd integrations/engineering_tools
python -m pytest
python demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report reports/gear.json

再运行 grep：
grep -R "solidworks_create_spur_gear_part" src/seekflow_engineering_tools || true
grep -R "solidworks_create_true_involute_gear_part" src/seekflow_engineering_tools || true
grep -R "create_spur_gear_true_involute\|create_spur_gear_involute\|create_spur_gear_star" src/seekflow_engineering_tools || true
grep -R "star-polygon\|visual gear\|triangular teeth" src/seekflow_engineering_tools || true
grep -R "return {\"ok\": True, \"results\": \[\]}" src/seekflow_engineering_tools || true
grep -R "best-effort" src/seekflow_engineering_tools || true

如果 grep 仍命中 legacy gear 代码，必须确认它们：
- 不注册为 tool
- 不被 engineering_build_cad_model 调用
- 有 not engineering-grade / legacy only docstring
- 有测试覆盖

完成后给出：
1. 修改文件清单
2. 每个 P0/P1 任务完成情况
3. 测试结果
4. demo 结果
5. 剩余风险
```

---

# 7. 最终验收标准

修完后，下面每条都必须为真：

```text
1. engineering_validate_cad_ir 同时 normalize recipe 和 primitive。
2. recipe spur_gear 会 rewrite 成 primitive involute_spur_gear。
3. choose_backend 能识别 primitive。
4. engineering_build_cad_model 对 cadquery primitive 直接生成 STEP + metadata。
5. engineering_build_cad_model 对 SolidWorks/NX primitive 先生成 canonical STEP，再 import native。
6. SolidWorks/NX 不再注册工程级齿轮生成工具。
7. SolidWorks/NX 不再在工程路径生成 involute 曲线。
8. STEP 不存在、metadata 不存在、validation 失败、mechanical validation 不可用时，ok=False。
9. cadquery_visual_fallback 默认不能让 industrial_brep 成功。
10. metadata 包含 primitive、kernel、parameters、reference_dimensions、is_standard_involute。
11. demo_full_chain gear case 可跑通，并输出严格 JSON report。
12. pytest 覆盖 primitive registry、gear dimensions、gear build、metadata、legacy rewrite、SW/NX step import routing、demo。
```

当前最关键的落点不是继续补齿轮数学，而是把“配置里已经声明的 primitive strategy”真正接到统一构建入口，并堵住 SolidWorks/NX 直接生成齿形和各种假成功路径。

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py "raw.githubusercontent.com"
[2]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[3]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/tools.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/tools.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[4]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/com_client.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/com_client.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[5]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[6]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[7]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx/job_queue.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/nx/job_queue.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[8]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/nx at main · WYZAAACCC/seekflow-engineering · GitHub"
