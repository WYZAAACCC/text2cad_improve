下面这份可以直接交给 **Claude Code** 执行。我把它写成“修复任务书 + 执行 prompt + 验收标准 + 测试清单”的形式，重点防止 Claude Code 漏改、误改、只做表面修复。

我基于当前 GitHub `main` 的关键源码重新核对后，结论要比上一轮更精确：当前仓库已经补齐了不少 primitive、gear、metadata、SW/NX STEP import、ANSYS fail-closed 和测试文件；但仍然存在几个会让工业级验收失真的漏洞。尤其是 `demo_full_chain.py` 仍然在 case 末尾用 `if build_result.get("ok"): report["overall_ok"] = True` 这种逻辑覆盖前面 stage 失败，属于核心假成功风险。([GitHub][1])

---

# SeekFlow Engineering 修复执行文档

## 0. 修复目标总述

本次修复的目标不是“让测试绿”这么简单，而是把仓库从“已经有工业级架构雏形”修到“可以作为第一阶段工业级 Text-to-CAD 验收基线”。

最终必须达到：

```text
LLM 只输出 CAD-IR；
CAD-IR 支持 recipe + primitive；
spur_gear legacy recipe 自动 rewrite 为 involute_spur_gear primitive；
CadQuery/CQ_Gears/OpenCascade 生成 canonical STEP；
SolidWorks/NX 只 import canonical STEP 并保存 native 文件；
STEP、metadata、inspection、mechanical_validation 缺一不可；
demo_full_chain 是 CI 验收脚本，不是演示脚本；
任何 stage 缺失、validation 缺失、metadata 缺失、fallback 非法、native 文件缺失，都必须 fail-closed；
pytest 必须覆盖所有危险旁路和假成功路径。
```

当前源码中已经有统一入口 `engineering_validate_cad_ir` / `engineering_build_cad_model`，并且 build 入口已经执行 deprecated recipe rewrite、recipe/primitive 参数 normalization、legacy `spur_gear` 拒绝、SW/NX fallback 禁止以及 SW/NX primitive 走 `cadquery_step_import` 路由。([GitHub][2])

当前 capability registry 也已经支持 `stable_primitives`、`primitive_strategy`、`backend_supports_feature`、`get_primitive_strategy`，并且 CadQuery 使用 `native_cadquery_primitive`，SolidWorks/NX 使用 `cadquery_step_import`。([GitHub][3])

但是还必须修复以下问题。

---

# 1. Claude Code 总 Prompt

下面这一段可以直接复制给 Claude Code：

```text
你现在要修复 GitHub 仓库 WYZAAACCC/seekflow-engineering 中的 integrations/engineering_tools 子项目。

你的目标不是做表面优化，而是把 SeekFlow Engineering Tools 的 Text-to-CAD / CAD-to-CAE 工业级验收链路修到 fail-closed 状态。

请严格执行以下原则：

1. 不允许让 demo_full_chain.py 出现假成功。
   - 任意 required stage 缺失或 ok 不是 True，case_report["overall_ok"] 必须是 False。
   - 不允许用 build_result.get("ok") 单独把 overall_ok 设回 True。
   - validation、inspection、mechanical_validation、metadata、kernel_used、reference_dimensions 缺失时必须失败。
   - --case all 中任意 case 失败，最终进程必须 sys.exit(1)。

2. 不允许 primitive registry 静默吞掉 ImportError。
   - geometry_primitives/registry.py 不能 except ImportError: pass。
   - 如果 gear primitive registry 导入失败，必须在 list/get/normalize 时 fail-closed 并给出明确 diagnostic。
   - 不能让 involute_spur_gear 因导入失败而静默从 registry 消失。

3. 齿轮 primitive 必须工业级校验。
   - involute_spur_gear 的 industrial_brep 默认必须使用 cq_gears kernel。
   - cadquery_visual_fallback 只能在明确 quality_grade="visual_fallback" 或 allow_visual_fallback=True 时作为 warning 存在。
   - 对 industrial_brep，fallback 必须 hard fail。
   - metadata 必须包含 kernel、primitive、parameters、reference_dimensions、is_standard_involute。
   - mechanical validation 必须 hard-check pitch/base/outer/root/face_width/bore/tooth_count/kernel，并且与 CAD-IR parameters 一致。

4. SolidWorks/NX 不能重新生成复杂齿形。
   - gear primitive 必须走 CadQuery/CQ_Gears canonical STEP。
   - SolidWorks 只 import STEP 并保存 SLDPRT。
   - NX 只 import STEP 并保存 PRT。
   - legacy gear functions 可以保留，但必须保持 demo-only，不注册、不路由、不参与 engineering_build_cad_model。

5. 测试必须覆盖所有危险路径。
   - 不只测试 happy path。
   - 必须加入/强化假成功测试、metadata missing 测试、mechanical_validation missing 测试、fallback industrial_brep fail 测试、NX result ok 缺失 fail 测试、SW/NX canonical STEP import fail 测试、demo_full_chain stage 缺失 fail 测试。
   - 任何测试不得用宽松断言掩盖问题，例如 “ok False or xxx” 这种不可靠断言必须改掉。

6. 最后必须运行：
   cd integrations/engineering_tools
   python -m compileall src demo_full_chain.py
   python -m pytest

如果本地没有 cadquery/cq-gears/SolidWorks/NX/ANSYS 环境：
- 需要把环境依赖测试用 pytest.importorskip 或 marker 隔离。
- 但是纯逻辑 fail-closed 测试不能跳过。
- mock 测试必须覆盖 SW/NX/ANSYS 的失败路径。

请先阅读以下文件：
- integrations/engineering_tools/demo_full_chain.py
- integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py
- integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py
- integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/backend_builders.py
- integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py
- integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py
- integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
- integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/gears/*
- integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/*
- integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/*
- integrations/engineering_tools/src/seekflow_engineering_tools/nx/*
- integrations/engineering_tools/tests/*

完成后，请输出：
1. 修改了哪些文件；
2. 每个文件修复了什么风险；
3. 新增或强化了哪些测试；
4. compileall / pytest 结果；
5. 是否仍有需要人工环境验证的内容，例如真实 SolidWorks/NX/ANSYS。
```

---

# 2. P0 修复任务：`demo_full_chain.py` 假成功

## 2.1 当前问题

`demo_full_chain.py` 在多个 case 尾部有如下逻辑：

```python
if build_result.get("ok"):
    report["overall_ok"] = True
```

这会导致：

```text
build.ok = True
inspect 缺失或 inspect.ok = False
mechanical_validation 缺失或 mechanical_validation.ok = False
metadata 缺失
kernel unknown
reference_dimensions 缺失
```

这些错误已经被 `_stage(..., ok=False)` 标记过，但最后又被 `build_result.get("ok")` 覆盖成 `overall_ok=True`。这是典型 CI 假成功。当前 gear case 中确实可以看到最后读取 metadata / mech validation 后，仍在尾部用 `build_result.get("ok")` 把 `overall_ok` 置回 True。([GitHub][1])

## 2.2 必须修复的文件

```text
integrations/engineering_tools/demo_full_chain.py
```

## 2.3 修复方式

### 2.3.1 新增统一 finalize 函数

在 `demo_full_chain.py` 中新增：

```python
def _finalize_case_report(
    report: dict,
    required_stages: list[str],
    *,
    allow_skipped_stages: set[str] | None = None,
    required_metrics: list[str] | None = None,
) -> dict:
    allow_skipped_stages = allow_skipped_stages or set()
    required_metrics = required_metrics or []

    errors = report.setdefault("errors", [])
    stages = report.setdefault("stages", {})
    metrics = report.setdefault("metrics", {})

    ok = True

    for stage_name in required_stages:
        stage = stages.get(stage_name)
        if stage is None:
            ok = False
            errors.append(f"[{stage_name}] Required stage missing.")
            continue

        if stage.get("skipped") is True and stage_name in allow_skipped_stages:
            continue

        if stage.get("ok") is not True:
            ok = False
            err = stage.get("error") or f"Required stage '{stage_name}' did not pass."
            if f"[{stage_name}]" not in " ".join(errors):
                errors.append(f"[{stage_name}] {err}")

    for key in required_metrics:
        value = metrics
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                ok = False
                errors.append(f"[metrics] Required metric missing: {key}")
                value = None
                break
            value = value[part]
        if value in (None, "", "unknown"):
            ok = False
            errors.append(f"[metrics] Required metric invalid/unknown: {key}")

    report["overall_ok"] = ok
    return report
```

### 2.3.2 `_stage` 必须不再单独决定最终成功

现在 `_stage` 可以继续设置 stage，但不要让它产生“最终成功”。建议改为：

```python
def _stage(report: dict, name: str, ok: bool, **extra):
    report.setdefault("stages", {})[name] = {"ok": ok, **extra}
    if not ok:
        report["overall_ok"] = False
        error = extra.get("error")
        if error:
            report.setdefault("errors", []).append(f"[{name}] {error}")
```

### 2.3.3 删除所有 `if build_result.get("ok"): report["overall_ok"] = True`

必须全文删除：

```python
if build_result.get("ok"):
    report["overall_ok"] = True
```

或者任何等价逻辑。

成功只能由 `_finalize_case_report()` 判断。

### 2.3.4 box / flanged_hub 的 finalize

box / flanged_hub 没有 primitive，所以 mechanical validation 可以 skipped，但 inspect 不可以 skipped。

box case 结尾必须类似：

```python
return _finalize_case_report(
    report,
    required_stages=[
        "validate_cad_ir",
        "normalize_primitives",
        "choose_backend",
        "build",
        "inspect",
        "mechanical_validate",
    ],
    allow_skipped_stages={"normalize_primitives", "mechanical_validate"},
)
```

注意：

```text
normalize_primitives 可以 skipped，因为没有 primitive；
mechanical_validate 可以 skipped，因为没有 primitive；
inspect 不可以 skipped；
build 不可以 skipped；
validate 不可以 skipped。
```

flanged_hub 同理。

### 2.3.5 gear case 的 finalize

gear case 必须更严格：

```python
return _finalize_case_report(
    report,
    required_stages=[
        "validate_cad_ir",
        "normalize_primitives",
        "choose_backend",
        "build",
        "inspect",
        "mechanical_validate",
        "metadata",
    ],
    required_metrics=[
        "kernel_used",
        "reference_dimensions.pitch_diameter_mm",
        "reference_dimensions.base_diameter_mm",
        "reference_dimensions.outer_diameter_mm",
        "reference_dimensions.root_diameter_mm",
    ],
)
```

gear case 不允许 skipped `mechanical_validate`。

### 2.3.6 gear metadata 应作为单独 stage

当前 gear case 只是试图读取 metadata，然后失败时把 failure 塞到 mechanical_validate。建议新增单独 stage：

```python
meta_path = step_path.with_suffix(".metadata.json")
if not meta_path.exists() or meta_path.stat().st_size < 1:
    _stage(report, "metadata", ok=False, error="Gear metadata sidecar missing or empty.")
else:
    try:
        sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
        pm = sidecar.get("primitive_metadata", {}).get("involute_spur_gear")
        if not isinstance(pm, dict):
            _stage(report, "metadata", ok=False, error="primitive_metadata.involute_spur_gear missing.")
        else:
            _stage(report, "metadata", ok=True, path=str(meta_path))
    except (json.JSONDecodeError, OSError) as exc:
        _stage(report, "metadata", ok=False, error=f"Failed to read metadata: {exc}")
```

### 2.3.7 kernel 必须强制为 `cq_gears`

对于 demo 的 `involute_spur_gear` 工业验收 case，`quality_grade` 默认是 `industrial_brep`，所以成功时 `kernel_used` 必须是：

```text
cq_gears
```

不能接受：

```text
cadquery_visual_fallback
unknown
None
```

gear case 中应加入：

```python
if kernel_used != "cq_gears":
    _stage(
        report,
        "mechanical_validate",
        ok=False,
        error=f"Expected gear kernel 'cq_gears', got '{kernel_used}'.",
    )
```

当前 primitive compiler 在没有 `cq_gears` 时会进入 visual fallback 并写 warning；这对 visual demo 可以存在，但工业 `demo_full_chain` 成功路径不能接受 fallback。([GitHub][4])

---

# 3. P0 修复任务：demo gear validation spec 不够硬

## 3.1 当前问题

当前 gear demo 的 validation 只包含：

```text
expected_body_count
expected_bbox_mm
tolerance_mm
expected_kernel
```

但审核目标要求齿轮必须校验：

```text
expected_tooth_count
expected_pitch_diameter_mm
expected_outer_diameter_mm
expected_root_diameter_mm
expected_base_diameter_mm
expected_bore_diameter_mm
expected_face_width_mm
expected_kernel
```

当前 gear validation 已经对 metadata missing、kernel unknown、visual fallback、is_standard_involute、reference_dimensions missing、pitch/base/outer/root mismatch、bbox/face_width 等做了一定 fail-closed 检查。([GitHub][5])

但是 demo case 自己也必须提供完整期望值，不能只靠内部 metadata 自证。

## 3.2 修复文件

```text
integrations/engineering_tools/demo_full_chain.py
```

## 3.3 修复方式

gear case 中：

```python
ref = spur_gear_reference_dimensions(params)
```

然后 validation 改为：

```python
"validation": {
    "expected_body_count": 1,
    "expected_bbox_mm": [
        ref["outer_diameter_mm"],
        ref["outer_diameter_mm"],
        params["face_width_mm"],
    ],
    "expected_tooth_count": params["teeth"],
    "expected_pitch_diameter_mm": ref["pitch_diameter_mm"],
    "expected_base_diameter_mm": ref["base_diameter_mm"],
    "expected_outer_diameter_mm": ref["outer_diameter_mm"],
    "expected_root_diameter_mm": ref["root_diameter_mm"],
    "expected_bore_diameter_mm": params["bore_dia_mm"],
    "expected_face_width_mm": params["face_width_mm"],
    "expected_kernel": "cq_gears",
    "tolerance_mm": 0.1,
}
```

不要手写 magic number，全部从 `spur_gear_reference_dimensions(params)` 和 `params` 计算。

---

# 4. P0 修复任务：Primitive Registry 不能吞掉 ImportError

## 4.1 当前问题

`geometry_primitives/registry.py` 中存在：

```python
except ImportError:
    pass
```

这会导致齿轮 primitive 模块导入失败时，registry 静默缺失 `involute_spur_gear`。当前源码确实存在这个吞错逻辑。([GitHub][6])

这违反工业级 fail-closed 原则。

## 4.2 修复文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py
```

## 4.3 推荐实现

不要在 `_populate_registry()` 中静默 pass。建议改成保留 diagnostic：

```python
from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.base import PrimitiveDefinition

PRIMITIVE_REGISTRY: dict[str, PrimitiveDefinition] = {}
_REGISTRY_LOAD_ERRORS: list[str] = []


def _populate_registry() -> None:
    PRIMITIVE_REGISTRY.clear()
    _REGISTRY_LOAD_ERRORS.clear()

    try:
        from seekflow_engineering_tools.geometry_primitives.gears.models import GEAR_PRIMITIVES
    except ImportError as exc:
        _REGISTRY_LOAD_ERRORS.append(
            f"Failed to import gear primitives registry: {type(exc).__name__}: {exc}"
        )
        return

    for p in GEAR_PRIMITIVES:
        if p.name in PRIMITIVE_REGISTRY:
            _REGISTRY_LOAD_ERRORS.append(f"Duplicate primitive registered: {p.name}")
            continue
        PRIMITIVE_REGISTRY[p.name] = p


def registry_load_errors() -> list[str]:
    return list(_REGISTRY_LOAD_ERRORS)


def _raise_if_registry_unhealthy() -> None:
    if _REGISTRY_LOAD_ERRORS:
        raise RuntimeError("; ".join(_REGISTRY_LOAD_ERRORS))


def list_primitive_names() -> list[str]:
    _raise_if_registry_unhealthy()
    return sorted(PRIMITIVE_REGISTRY.keys())


def get_primitive(name: str) -> PrimitiveDefinition | None:
    _raise_if_registry_unhealthy()
    return PRIMITIVE_REGISTRY.get(name)
```

如果担心某些轻量环境不安装 gear optional deps，请注意：`gears.models` 不应该依赖 `cq_gears` runtime；它只是 primitive definition。真正 optional 的是 adapter build 阶段。如果 `gears.models` import 都失败，那不是“缺少 cq-gears”，而是 registry 模块坏了，必须 fail。

## 4.4 测试要求

新增或强化：

```text
tests/test_geometry_primitives_registry.py
```

必须覆盖：

```python
def test_registry_does_not_swallow_import_error(monkeypatch):
    # monkeypatch importlib or builtins.__import__ so gears.models import raises ImportError
    # reload registry
    # list_primitive_names 或 get_primitive 必须 raise RuntimeError
```

也可以更简单地测试源码禁止：

```python
def test_registry_has_no_silent_importerror_pass():
    src = Path("src/seekflow_engineering_tools/geometry_primitives/registry.py").read_text()
    assert "except ImportError:\n        pass" not in src
```

但更推荐行为测试。

---

# 5. P0 修复任务：Mechanical Validation 继续加硬

## 5.1 当前状态

当前 `gear_validation.py` 已经做了 metadata hard fail、primitive mismatch、kernel unknown、visual fallback、`is_standard_involute`、reference_dimensions 缺失、pitch/base/outer/root 数值比较、bbox/face_width 检查。([GitHub][5])

这是好的，但还不够完整。

## 5.2 仍需补齐的硬校验

必须新增：

```text
1. expected_kernel vs metadata.kernel
2. expected_tooth_count vs metadata.parameters.teeth
3. expected_bore_diameter_mm vs metadata.parameters.bore_dia_mm
4. expected_face_width_mm vs metadata.parameters.face_width_mm
5. CAD-IR feature.parameters 与 metadata.parameters 的一致性
6. metadata.reference_dimensions 必须包含 face_width_mm 或 validation 必须从 params 校验 face_width
7. inspection body_count / solid_count 必须与 expected_body_count 一致
8. build_warnings 中如出现 fallback / not certified involute geometry，industrial_brep 必须 fail
```

## 5.3 修复文件

```text
src/seekflow_engineering_tools/mechanical_validation/gear_validation.py
src/seekflow_engineering_tools/mechanical_validation/common.py
src/seekflow_engineering_tools/cadquery_backend/builder.py
```

## 5.4 推荐接口调整

`validate_involute_spur_gear_result()` 当前参数是：

```python
validate_involute_spur_gear_result(
    params: dict,
    inspection: dict,
    metadata: dict | None = None,
    tolerance_mm: float = 0.1,
)
```

建议增加：

```python
validation_spec: object | None = None
raw_metadata: dict | None = None
```

或者更简单，把 expected 字段从 `spec.validation` 传入：

```python
def validate_involute_spur_gear_result(
    params: dict,
    inspection: dict,
    metadata: dict | None = None,
    tolerance_mm: float = 0.1,
    expected: dict | None = None,
    raw_metadata: dict | None = None,
) -> dict:
```

在 `mechanical_validation/common.py` 中组装：

```python
expected = {
    "expected_tooth_count": getattr(spec.validation, "expected_tooth_count", None),
    "expected_pitch_diameter_mm": getattr(spec.validation, "expected_pitch_diameter_mm", None),
    "expected_outer_diameter_mm": getattr(spec.validation, "expected_outer_diameter_mm", None),
    "expected_root_diameter_mm": getattr(spec.validation, "expected_root_diameter_mm", None),
    "expected_base_diameter_mm": getattr(spec.validation, "expected_base_diameter_mm", None),
    "expected_bore_diameter_mm": getattr(spec.validation, "expected_bore_diameter_mm", None),
    "expected_face_width_mm": getattr(spec.validation, "expected_face_width_mm", None),
    "expected_kernel": getattr(spec.validation, "expected_kernel", None),
    "expected_body_count": getattr(spec.validation, "expected_body_count", None),
}
```

然后传入 gear validation。

## 5.5 具体校验逻辑

在 `gear_validation.py` 中增加：

```python
meta_params = metadata.get("parameters") or {}

# CAD-IR params vs metadata params
for key in [
    "module_mm",
    "teeth",
    "pressure_angle_deg",
    "face_width_mm",
    "bore_dia_mm",
    "addendum_coefficient",
    "clearance_coefficient",
    "profile_shift_coefficient",
    "backlash_mm",
    "root_fillet_radius_mm",
    "quality_grade",
]:
    if key in params:
        expected_value = params[key]
        actual_value = meta_params.get(key)
        if actual_value is None:
            issues.append({
                "code": f"gear_metadata_parameter_missing_{key}",
                "message": f"Metadata parameters missing '{key}'.",
                "severity": "error",
            })
            continue

        if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            if abs(float(actual_value) - float(expected_value)) > tolerance_mm:
                issues.append({
                    "code": f"gear_metadata_parameter_mismatch_{key}",
                    "message": f"Metadata parameter {key}={actual_value} does not match CAD-IR {expected_value}.",
                    "expected": expected_value,
                    "actual": actual_value,
                    "severity": "error",
                })
        else:
            if actual_value != expected_value:
                issues.append({
                    "code": f"gear_metadata_parameter_mismatch_{key}",
                    "message": f"Metadata parameter {key}={actual_value} does not match CAD-IR {expected_value}.",
                    "expected": expected_value,
                    "actual": actual_value,
                    "severity": "error",
                })
```

对于 expected validation：

```python
if expected:
    if expected.get("expected_kernel") and kernel != expected["expected_kernel"]:
        issues.append({
            "code": "gear_expected_kernel_mismatch",
            "message": f"Expected kernel {expected['expected_kernel']}, got {kernel}.",
            "expected": expected["expected_kernel"],
            "actual": kernel,
            "severity": "error",
        })

    if expected.get("expected_tooth_count") is not None:
        actual_teeth = meta_params.get("teeth")
        if int(actual_teeth) != int(expected["expected_tooth_count"]):
            issues.append(...)

    if expected.get("expected_bore_diameter_mm") is not None:
        actual_bore = meta_params.get("bore_dia_mm")
        if abs(float(actual_bore) - float(expected["expected_bore_diameter_mm"])) > tolerance_mm:
            issues.append(...)

    if expected.get("expected_face_width_mm") is not None:
        actual_fw = meta_params.get("face_width_mm")
        if abs(float(actual_fw) - float(expected["expected_face_width_mm"])) > tolerance_mm:
            issues.append(...)
```

对于 body count：

```python
if expected and expected.get("expected_body_count") is not None:
    actual_body_count = (
        inspection.get("solid_count")
        or inspection.get("body_count")
        or inspection.get("body_count_estimate")
    )
    if actual_body_count is None:
        issues.append({
            "code": "gear_body_count_missing",
            "message": "Inspection did not report body/solid count.",
            "severity": "error",
        })
    elif int(actual_body_count) != int(expected["expected_body_count"]):
        issues.append({
            "code": "gear_body_count_mismatch",
            "expected": expected["expected_body_count"],
            "actual": actual_body_count,
            "severity": "error",
        })
```

## 5.6 fallback warning hard fail

`metadata` 内部已有 warnings，`raw_metadata` 顶层也有 `build_warnings`。如果 quality is industrial：

```python
warnings = []
warnings.extend(metadata.get("warnings", []) or [])
if raw_metadata:
    warnings.extend(raw_metadata.get("build_warnings", []) or [])

if params.get("quality_grade", "industrial_brep") == "industrial_brep":
    for w in warnings:
        lw = str(w).lower()
        if "fallback" in lw or "not certified" in lw or "not standard involute" in lw:
            issues.append({
                "code": "gear_industrial_warning_forbidden",
                "message": f"Industrial gear build contains forbidden warning: {w}",
                "severity": "error",
            })
```

---

# 6. P0 修复任务：`test_demo_full_chain_gear.py` 断言太软

## 6.1 当前问题

当前 `test_demo_full_chain_gear.py` 会在 `report["overall_ok"]` 为真时接受：

```python
metrics["kernel_used"] in ("cq_gears", "cadquery_visual_fallback")
```

这对工业验收不够严格。该测试文件确实存在，并且当前断言允许 `cadquery_visual_fallback` 出现在成功结果里。([GitHub][7])

## 6.2 修复文件

```text
tests/test_demo_full_chain_gear.py
```

## 6.3 修复方式

### 6.3.1 成功路径必须只接受 `cq_gears`

改成：

```python
if report["overall_ok"]:
    assert metrics["kernel_used"] == "cq_gears"
```

如果没有安装 `cq-gears`，工业成功路径测试应该：

```python
pytest.importorskip("cq_gears")
```

而不是接受 fallback 成功。

### 6.3.2 增加“fallback 不得成功”测试

新增：

```python
def test_demo_full_chain_gear_fails_when_kernel_unknown_or_fallback(monkeypatch, tmp_path):
    import demo_full_chain

    def fake_build_fn(*args, **kwargs):
        step = Path(kwargs["out_step"])
        step.parent.mkdir(parents=True, exist_ok=True)
        step.write_text("dummy step")
        step.with_suffix(".metadata.json").write_text(json.dumps({
            "primitive_metadata": {
                "involute_spur_gear": {
                    "kernel": "cadquery_visual_fallback",
                    "primitive": "involute_spur_gear",
                    "is_standard_involute": False,
                    "parameters": {
                        "module_mm": 2.0,
                        "teeth": 24,
                        "pressure_angle_deg": 20.0,
                        "face_width_mm": 15.0,
                        "bore_dia_mm": 10.0,
                        "quality_grade": "industrial_brep",
                    },
                    "reference_dimensions": {
                        "pitch_diameter_mm": 48.0,
                        "base_diameter_mm": 45.105,
                        "outer_diameter_mm": 52.0,
                        "root_diameter_mm": 43.0,
                    },
                    "warnings": ["not certified involute geometry"],
                }
            },
            "build_warnings": ["cq_gears is not available; using visual fallback"],
        }))

        return {
            "ok": True,
            "files_created": [str(step), str(step.with_suffix(".metadata.json"))],
            "metrics": {
                "validation": {"ok": True},
                "mechanical_validation": {
                    "ok": False,
                    "results": [{
                        "ok": False,
                        "kernel": "cadquery_visual_fallback",
                        "reference_dimensions": {
                            "pitch_diameter_mm": 48.0,
                            "base_diameter_mm": 45.105,
                            "outer_diameter_mm": 52.0,
                            "root_diameter_mm": 43.0,
                        }
                    }]
                }
            },
            "warnings": ["fallback"],
        }

    def fake_validate_fn(spec):
        return {
            "ok": True,
            "metrics": {
                "normalized_parameters": {
                    "gear1": spec["features"][0]["parameters"]
                }
            }
        }

    monkeypatch.setattr(
        demo_full_chain,
        "_get_unified_tools",
        lambda config: (fake_validate_fn, fake_build_fn),
    )

    report = demo_full_chain.run_case_involute_spur_gear("cadquery", tmp_path)
    assert report["overall_ok"] is False
    assert report["stages"]["mechanical_validate"]["ok"] is False
```

### 6.3.3 增加“inspection 缺失不得成功”测试

```python
def test_demo_full_chain_fails_when_inspection_missing(monkeypatch, tmp_path):
    # fake build returns ok=True but metrics has no validation
    # report overall_ok must be False
```

### 6.3.4 增加“mechanical_validation 缺失不得成功”测试

```python
def test_demo_full_chain_gear_fails_when_mechanical_validation_missing(monkeypatch, tmp_path):
    # fake build returns ok=True and validation ok, but no mechanical_validation
    # report overall_ok must be False
```

### 6.3.5 增加“metadata 缺失不得成功”测试

```python
def test_demo_full_chain_gear_fails_when_metadata_missing(monkeypatch, tmp_path):
    # fake build returns ok=True and metrics validation/mechanical_validation ok,
    # but does not create .metadata.json
    # report overall_ok must be False
    # metadata stage must fail
```

---

# 7. P1 修复任务：`test_cadquery_builder_fail_closed.py` 有宽松断言

## 7.1 当前问题

当前 `test_cadquery_builder_fail_closed.py` 中有一个断言类似：

```python
assert result["ok"] is False or "import" not in str(result).lower()
```

这种断言不够工业级。它允许一些奇怪情况通过。该测试文件确实存在，并且当前断言过软。([GitHub][8])

## 7.2 修复文件

```text
tests/test_cadquery_builder_fail_closed.py
```

## 7.3 修复方式

把测试改成真正模拟 import error。

例如：

```python
def test_mechanical_validation_import_error_fails(monkeypatch):
    import builtins
    from pathlib import Path
    from seekflow_engineering_tools.cadquery_backend.builder import _run_mechanical_validation
    from seekflow_engineering_tools.ir.cad import CADPartSpec
    from seekflow_engineering_tools.ir.primitive import PrimitiveFeature

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "seekflow_engineering_tools.mechanical_validation.common":
            raise ImportError("simulated mechanical validation import failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    spec = CADPartSpec(
        name="test",
        features=[
            PrimitiveFeature(
                id="g1",
                primitive_name="involute_spur_gear",
                parameters={"module_mm": 2.0, "teeth": 24, "face_width_mm": 15.0},
            )
        ],
    )

    result = _run_mechanical_validation(spec, Path("test.step"), {})
    assert result["ok"] is False
    assert any(
        i.get("code") == "mechanical_validation_unavailable"
        for i in result.get("issues", [])
    )
```

不要用 `or` 放松断言。

---

# 8. P1 修复任务：`engineering_validate_cad_ir` 返回 normalized_spec 要更可靠

## 8.1 当前状态

`engineering_validate_cad_ir` 已经执行 rewrite、schema validate、recipe/primitive normalization、backend_supports_feature 检查，并尝试把 `normalized_spec` 放进 metrics。([GitHub][2])

## 8.2 仍需修复的问题

当前 `rewrite_deprecated_recipes_to_primitives(spec)` 会原地修改传入 dict。长期看，这可能导致调用方复用 spec 时出现副作用。

## 8.3 修复文件

```text
src/seekflow_engineering_tools/natural_language/normalizer.py
src/seekflow_engineering_tools/natural_language/tools.py
tests/test_engineering_validate_cad_ir_primitives.py
```

## 8.4 修复方式

### 8.4.1 normalizer 不要原地修改入参

```python
import copy

def rewrite_deprecated_recipes_to_primitives(spec: dict) -> dict:
    spec = copy.deepcopy(spec)
    warnings: list[str] = []
    ...
    spec["rewrite_warnings"] = warnings
    return spec
```

当前 normalizer 已经实现 `spur_gear → involute_spur_gear` 并设置默认 pressure angle、addendum、clearance、profile shift、backlash、root fillet、quality grade 等参数。([GitHub][9])

只需要把它改成不 mutate input。

### 8.4.2 增加测试

```python
def test_rewrite_deprecated_recipe_does_not_mutate_input():
    original = {... spur_gear recipe ...}
    snapshot = copy.deepcopy(original)
    rewritten = rewrite_deprecated_recipes_to_primitives(original)
    assert original == snapshot
    assert rewritten != original
    assert rewritten["features"][0]["type"] == "primitive"
```

---

# 9. P1 修复任务：Capability Registry 增加 `backend_supports_primitive`

## 9.1 当前状态

当前 capability registry 已有：

```text
stable_primitives
primitive_strategy
backend_supports_feature
get_primitive_strategy
choose_backend
```

但没有单独的 `backend_supports_primitive`，而原审核目标里明确要求支持该函数。当前搜索没有找到 `backend_supports_primitive`。([GitHub][3])

## 9.2 修复文件

```text
src/seekflow_engineering_tools/capabilities/registry.py
tests/test_capability_registry_primitives.py
```

## 9.3 修复方式

新增：

```python
def backend_supports_primitive(backend: str, primitive_name: str) -> bool:
    cap = CAPABILITIES.get(backend, {})
    return primitive_name in cap.get("stable_primitives", [])
```

并让 `backend_supports_feature` 内部调用它：

```python
elif feat_type == "primitive":
    return backend_supports_primitive(backend, feature.primitive_name)
```

## 9.4 测试要求

```python
def test_backend_supports_primitive():
    from seekflow_engineering_tools.capabilities.registry import backend_supports_primitive
    assert backend_supports_primitive("cadquery", "involute_spur_gear") is True
    assert backend_supports_primitive("solidworks2025", "involute_spur_gear") is True
    assert backend_supports_primitive("nx12", "involute_spur_gear") is True
    assert backend_supports_primitive("cadquery", "unknown") is False
```

还要确保：

```python
for backend in ["cadquery", "solidworks2025", "nx12"]:
    assert "spur_gear" not in CAPABILITIES[backend]["stable_recipes"]
```

当前 tests 目录已经存在 `test_capability_registry_primitives.py` 和 `test_no_legacy_gear_for_engineering.py`，但要确认上述断言都覆盖。([GitHub][10])

---

# 10. P1 修复任务：SW/NX canonical STEP import 测试继续加硬

## 10.1 当前状态

`backend_builders.py` 已经明确写了 SolidWorks/NX primitive 流程：

```text
CadQuery/CQ_Gears 生成 canonical STEP + metadata
SolidWorks import STEP → SLDPRT
NX import STEP → PRT
```

并且在导入前检查 canonical build ok、STEP 存在、metadata 存在、inspection validation ok、mechanical validation ok。([GitHub][11])

NX tool 也已经存在 `nx_import_step_as_prt`，会检查 input STEP 存在非空、job result ok、PRT 存在非空。([GitHub][12])

SolidWorks tools 中 legacy gear 函数已经标记为 `LEGACY DEMO ONLY`，不应注册为 tool。([GitHub][13])

## 10.2 仍需强化的测试

### 10.2.1 SolidWorks canonical import tests

文件：

```text
tests/test_solidworks_step_import_strategy.py
```

必须覆盖：

```text
1. build_solidworks_from_canonical_step 调用 build_canonical_step_with_cadquery。
2. cq_result.ok=False 时不得调用 SolidWorksClient.import_step_as_part。
3. metadata missing 时不得调用 import_step_as_part。
4. validation.ok=False 时不得调用 import_step_as_part。
5. mechanical_validation.ok=False 时不得调用 import_step_as_part。
6. import_step_as_part 返回 False 时 result.ok=False。
7. import_step_as_part 返回 True 但 SLDPRT 不存在/为空时 result.ok=False。
8. 成功时 files_created 包含 STEP、metadata、SLDPRT。
9. warnings 包含 native SLDPRT created by importing canonical STEP。
10. legacy gear 函数不在 build_solidworks_tools(config) 返回的 tool names 中。
```

### 10.2.2 NX canonical import tests

文件：

```text
tests/test_nx_step_import_strategy.py
tests/test_nx_bridge_bootstrap.py
```

必须覆盖：

```text
1. build_nx_from_canonical_step 调用 build_canonical_step_with_cadquery。
2. cq_result.ok=False 时不得 submit import_step_as_prt。
3. metadata missing 时不得 submit import_step_as_prt。
4. validation.ok=False 时不得 submit import_step_as_prt。
5. mechanical_validation.ok=False 时不得 submit import_step_as_prt。
6. q.wait 返回 {} 或 {"message": "ok but no ok field"} 时必须 ok=False。
7. q.wait 返回 {"ok": True} 但 PRT 不存在/为空时必须 ok=False。
8. submit action 必须等于 import_step_as_prt。
9. params 必须包含 input_step 和 out_prt。
10. nx_bridge_bootstrap.ACTION_HANDLERS 必须包含 import_step_as_prt。
11. Unknown NX action 必须失败，不能 ok=True。
12. bridge handler 未显式返回 ok=True 必须失败。
```

---

# 11. P1 修复任务：`demo_full_chain.py` 报告结构必须 CI 化

## 11.1 必须输出的 report schema

每个 case 必须包含：

```json
{
  "overall_ok": false,
  "case": "involute_spur_gear",
  "backend": "cadquery",
  "stages": {
    "validate_cad_ir": {"ok": true},
    "normalize_primitives": {"ok": true},
    "choose_backend": {"ok": true},
    "build": {"ok": true},
    "inspect": {"ok": true},
    "mechanical_validate": {"ok": true},
    "metadata": {"ok": true}
  },
  "files_created": [],
  "metrics": {
    "kernel_used": "cq_gears",
    "reference_dimensions": {
      "pitch_diameter_mm": 48.0,
      "base_diameter_mm": 45.105,
      "outer_diameter_mm": 52.0,
      "root_diameter_mm": 43.0
    },
    "metadata_path": "...",
    "strategy": "native_cadquery_primitive"
  },
  "warnings": [],
  "errors": []
}
```

box / flanged_hub 可以没有 metadata stage，但 gear 必须有。

## 11.2 `--case all` 规则

主函数已有 `full_report["overall_ok"]` 聚合，失败时 `sys.exit(1)`。当前主函数这一层方向是对的；关键是每个 case 的 `overall_ok` 不能假成功。([GitHub][1])

增加测试：

```python
def test_case_all_exits_nonzero_if_any_case_fails(monkeypatch, tmp_path):
    # monkeypatch one runner returns overall_ok False
    # run main or subprocess
    # assert returncode != 0
```

---

# 12. P1 修复任务：CadQuery builder metadata 逻辑加硬

## 12.1 当前状态

CadQuery builder 已经包含：

```text
assert_file_created
_run_inspection
_run_mechanical_validation
_assert_metadata_sidecar
fallback policy
```

并且 `_run_mechanical_validation` 的 docstring 明确机械验证模块不可导入时 fail-closed。([GitHub][14])

## 12.2 仍需检查和修复

Claude Code 需要逐项确认：

```text
1. metadata sidecar 文件名必须固定为 step_path.with_suffix(".metadata.json")。
2. primitive build 时 metadata sidecar 缺失必须 ok=False。
3. metadata 缺少 primitive_metadata 必须 ok=False。
4. primitive_metadata 缺少 involute_spur_gear 必须 ok=False。
5. kernel 缺失必须 ok=False。
6. parameters 缺失必须 ok=False。
7. reference_dimensions 缺失必须 ok=False。
8. is_standard_involute 缺失或 False，industrial_brep 必须 ok=False。
9. build_warnings 必须传播到 EngineeringActionResult.warnings。
10. validation fail 不得 ok=True。
11. mechanical_validation fail 不得 ok=True。
12. STEP 文件不存在或为空不得 ok=True。
```

如果当前 builder 中任何地方仍有：

```python
validation.get("ok", True)
mechanical_validation.get("ok", True)
metadata.get("ok", True)
```

必须改成：

```python
validation.get("ok") is True
```

或者：

```python
if validation.get("ok") is not True:
    fail
```

---

# 13. P1 修复任务：Primitive compiler fallback 策略明确化

## 13.1 当前状态

`primitive_compiler.py` 当前生成脚本逻辑是：

```text
if cq_gears_available():
    build_involute_spur_gear_cq_gears
else:
    BUILD_WARNINGS.append(...)
    build_visual_spur_gear_fallback
```

这说明 fallback 是编译脚本中的运行时分支。([GitHub][4])

## 13.2 风险

这本身可以接受，但必须保证：

```text
quality_grade = industrial_brep 时 fallback build 可以生成 visual STEP，但最终 builder/mechanical_validation 必须 fail；
quality_grade = visual_fallback 时可以 warning 成功；
demo_full_chain industrial gear 不能 fallback 成功。
```

## 13.3 测试要求

文件：

```text
tests/test_involute_spur_gear_cadquery_build.py
tests/test_cadquery_builder_fail_closed.py
tests/test_gear_validation.py
```

必须覆盖：

```text
1. cq_gears unavailable + industrial_brep => build result ok=False
2. cq_gears unavailable + visual_fallback => ok=True but warnings include not certified
3. metadata.kernel == cadquery_visual_fallback
4. metadata.is_standard_involute == False
5. industrial_brep + fallback warning => mechanical_validation.ok=False
```

---

# 14. P1 修复任务：ANSYS fail-closed 回归测试

## 14.1 当前状态

pyproject、tests 目录和源码结构说明 ANSYS 已有 fail-closed 测试文件，例如 `test_ansys_fail_closed.py`、template registry tests、runner mock 等。([GitHub][10])

## 14.2 必须确认覆盖

Claude Code 需要打开并确认：

```text
tests/test_ansys_fail_closed.py
tests/test_ansys_template_validation.py
tests/test_ansys_template_registry.py
tests/test_ansys_runner_mock.py
```

至少覆盖：

```text
1. unknown parameter => ok=False
2. missing required parameter => ok=False
3. type coercion fail => ok=False
4. min/max fail => ok=False
5. geometry constraint fail => ok=False
6. APDL process has_error => ok=False
7. result_summary missing => ok=False
8. required metrics missing => ok=False
9. static parser coverage
10. thermal parser coverage
11. modal parser coverage
12. buckling parser coverage
13. plastic parser coverage
```

如果缺任何一个，补测试。

---

# 15. P2 清理任务：禁止危险字符串回归

新增一个静态 grep 测试文件：

```text
tests/test_no_fail_open_patterns.py
```

内容建议：

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "seekflow_engineering_tools"
DEMO = ROOT / "demo_full_chain.py"

def read_all_python():
    for path in [DEMO, *SRC.rglob("*.py")]:
        yield path, path.read_text(encoding="utf-8")

def test_no_validation_get_ok_true():
    forbidden = [
        'validation.get("ok", True)',
        "validation.get('ok', True)",
        'mechanical_validation.get("ok", True)',
        "mechanical_validation.get('ok', True)",
        'mech_val.get("ok", True)',
        "mech_val.get('ok', True)",
        'result_payload.get("ok", True)',
        "result_payload.get('ok', True)",
    ]
    for path, text in read_all_python():
        for pat in forbidden:
            assert pat not in text, f"{pat} found in {path}"

def test_demo_does_not_promote_build_ok_to_overall_ok():
    text = DEMO.read_text(encoding="utf-8")
    assert 'if build_result.get("ok"):' not in text
    assert 'report["overall_ok"] = True' not in text or "_finalize_case_report" in text

def test_no_tempfile_mktemp():
    for path, text in read_all_python():
        assert "tempfile.mktemp" not in text, f"tempfile.mktemp found in {path}"

def test_no_registry_importerror_pass():
    reg = SRC / "geometry_primitives" / "registry.py"
    text = reg.read_text(encoding="utf-8")
    assert "except ImportError:\n        pass" not in text
```

注意：这类静态测试不是替代行为测试，而是防回归。

---

# 16. P2 文档任务：增加工程验收说明

新增或更新：

```text
integrations/engineering_tools/README.md
```

增加章节：

```text
Industrial Acceptance Criteria
```

写清楚：

```text
1. CadQuery gear success requires cq_gears.
2. visual fallback is not engineering-grade.
3. SolidWorks/NX gear primitive only imports canonical STEP.
4. demo_full_chain is CI acceptance, not demo-only.
5. Required commands:
   python -m compileall src demo_full_chain.py
   python -m pytest
   python demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report reports/gear.json
6. If cq-gears is missing, industrial gear acceptance must fail, not silently pass.
```

---

# 17. 最终验收命令

Claude Code 完成修复后必须运行：

```bash
cd integrations/engineering_tools

python -m compileall src demo_full_chain.py
python -m pytest
```

如果安装了 CadQuery/CQ_Gears：

```bash
python demo_full_chain.py \
  --case involute_spur_gear \
  --backend cadquery \
  --json-report reports/gear_cadquery.json
```

要求：

```text
exit code = 0
overall_ok = true
case overall_ok = true
kernel_used = cq_gears
reference_dimensions.pitch_diameter_mm 存在且数值正确
reference_dimensions.base_diameter_mm 存在且数值正确
reference_dimensions.outer_diameter_mm 存在且数值正确
reference_dimensions.root_diameter_mm 存在且数值正确
metadata stage ok=true
mechanical_validate ok=true
inspect ok=true
```

如果没有 CQ_Gears：

```bash
python demo_full_chain.py \
  --case involute_spur_gear \
  --backend cadquery \
  --json-report reports/gear_cadquery_no_cqgears.json
```

要求：

```text
exit code != 0
overall_ok = false
不得 fallback 成 industrial_brep 成功
warnings 可以说明 visual fallback / cq_gears missing
mechanical_validate 或 metadata/kernel stage 必须 fail
```

SW/NX 环境存在时：

```bash
python demo_full_chain.py \
  --case involute_spur_gear \
  --backend solidworks2025 \
  --allow-step-import \
  --json-report reports/gear_solidworks.json
```

要求：

```text
先生成 canonical STEP + metadata
inspection ok=true
mechanical_validation ok=true
SolidWorks import STEP
SLDPRT 存在且非空
warnings 说明 native SLDPRT created by importing canonical STEP
不得调用 legacy gear create function
```

```bash
python demo_full_chain.py \
  --case involute_spur_gear \
  --backend nx12 \
  --allow-step-import \
  --json-report reports/gear_nx.json
```

要求：

```text
先生成 canonical STEP + metadata
inspection ok=true
mechanical_validation ok=true
NX job action = import_step_as_prt
PRT 存在且非空
warnings 说明 native PRT created by importing canonical STEP
NXOpen 不重新生成 involute curves
```

---

# 18. Claude Code 完成后必须输出的报告模板

让 Claude Code 最后输出：

```text
## 修复完成报告

### 1. 修改文件
- path/to/file.py
  - 修复点：
  - 风险关闭方式：
  - 对应测试：

### 2. 新增/修改测试
- tests/test_xxx.py
  - 覆盖场景：
  - 是否 mock：
  - 是否需要外部软件：

### 3. 执行结果
- python -m compileall src demo_full_chain.py
  - 结果：
- python -m pytest
  - 结果：
- demo_full_chain cadquery gear
  - 结果：
  - kernel_used：
  - metadata：
  - mechanical_validation：

### 4. 未能在本机验证的环境项
- SolidWorks 2025：
- NX 12：
- ANSYS 18.1：
- CadQuery：
- CQ_Gears：

### 5. 仍需人工注意的事项
- ...
```

---

# 19. 最终修复优先级表

| 优先级 | 修复项                                 | 是否必须 | 失败后果                   |
| --- | ----------------------------------- | ---: | ---------------------- |
| P0  | demo_full_chain overall_ok 聚合修复     |   必须 | CI 假成功                 |
| P0  | gear demo 完整 ValidationSpec         |   必须 | 齿轮自证成功                 |
| P0  | metadata stage 独立化                  |   必须 | metadata 缺失仍可能混入成功     |
| P0  | kernel_used 必须为 cq_gears            |   必须 | visual fallback 冒充工业齿轮 |
| P0  | registry 不吞 ImportError             |   必须 | primitive 静默消失         |
| P0  | test_demo_full_chain_gear 加硬        |   必须 | 假成功无法回归捕获              |
| P1  | gear_validation 增加 expected_* 校验    |   必须 | CAD-IR 与 metadata 不一致  |
| P1  | SW/NX canonical STEP import mock 测试 |   必须 | 商业 CAD 旁路无法发现          |
| P1  | no fail-open patterns 静态测试          | 建议必须 | 未来回归                   |
| P1  | normalizer 不 mutate input           | 建议必须 | 调用副作用                  |
| P2  | README 工业验收说明                       |   建议 | 使用者误解 fallback 成功      |

---

# 20. 给 Claude Code 的短版执行指令

如果你只想给 Claude Code 一段更短的指令，用这一段：

```text
请修复 integrations/engineering_tools，使其达到工业级 Text-to-CAD fail-closed 验收。

重点修复：
1. demo_full_chain.py：删除所有 if build_result.get("ok"): report["overall_ok"] = True。新增 _finalize_case_report，所有 required stages 聚合决定 overall_ok。gear case 必须要求 validate、normalize、choose_backend、build、inspect、mechanical_validate、metadata 全部 ok，kernel_used 必须 cq_gears，reference_dimensions 四项必须存在。stage/metrics 缺失必须 overall_ok=False。--case all 任一失败必须 exit 1。
2. demo gear validation：补 expected_tooth_count、expected_pitch/base/outer/root/bore/face_width、expected_kernel。
3. geometry_primitives/registry.py：禁止 except ImportError: pass。gear primitive registry 导入失败必须 fail-closed，有 diagnostic。
4. mechanical_validation/gear_validation.py：增加 expected_kernel、expected_tooth_count、expected_bore_diameter、expected_face_width、body_count、metadata.parameters 与 CAD-IR params 一致性校验。industrial_brep 下 fallback warning 必须 error。
5. tests：强化 test_demo_full_chain_gear.py，不允许 overall_ok=True 时 kernel_used=cadquery_visual_fallback。新增 inspection missing、mechanical_validation missing、metadata missing、kernel unknown/fallback 的假成功测试。修复 test_cadquery_builder_fail_closed.py 里的宽松断言。新增 no_fail_open_patterns 静态测试，禁止 validation.get("ok", True)、mechanical_validation.get("ok", True)、result_payload.get("ok", True)、tempfile.mktemp、except ImportError: pass。
6. capability registry：如无 backend_supports_primitive，补上并测试。
7. normalizer：rewrite_deprecated_recipes_to_primitives 不要原地修改入参。

最后运行：
cd integrations/engineering_tools
python -m compileall src demo_full_chain.py
python -m pytest

如果有 cadquery/cq-gears，运行：
python demo_full_chain.py --case involute_spur_gear --backend cadquery --json-report reports/gear_cadquery.json

成功时 kernel_used 必须 cq_gears；没有 cq-gears 时 industrial_brep gear demo 必须失败，不能 fallback 成功。
```

---

# 21. 最终判断标准

Claude Code 修完后，只有同时满足下面条件，才算真正修复完成：

```text
1. demo_full_chain 不再通过 build.ok 覆盖前面 stage 失败。
2. stage 缺失必 fail。
3. validation 缺失必 fail。
4. inspection 缺失必 fail。
5. mechanical_validation 缺失必 fail。
6. gear metadata 缺失必 fail。
7. kernel unknown 必 fail。
8. industrial_brep + visual fallback 必 fail。
9. gear success kernel 必须 cq_gears。
10. gear validation 比对 CAD-IR params、metadata params、reference dimensions、expected validation fields。
11. registry 不吞 ImportError。
12. tests 捕获所有假成功路径。
13. compileall 通过。
14. pytest 通过。
15. demo cadquery gear 在 cq-gears 环境下通过，在无 cq-gears 环境下不能假成功。
```

这份修复完成后，仓库才能接近你原始审核说明里定义的“第一阶段工业级目标”。当前 tests 目录已经存在大量相关测试文件，包括 compileall、capability primitives、demo_full_chain gear、primitive validation、gear metadata、gear validation、CadQuery fail-closed、SW/NX step import、pyproject optional deps 等，所以这次不是从零补测试，而是要把已有测试从“覆盖存在性”提升为“能抓住假成功和危险旁路”。([GitHub][10])

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/demo_full_chain.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/gear_validation.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/tests/test_demo_full_chain_gear.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/tests/test_cadquery_builder_fail_closed.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/normalizer.py "raw.githubusercontent.com"
[10]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/tests "seekflow-engineering/integrations/engineering_tools/tests at main · WYZAAACCC/seekflow-engineering · GitHub"
[11]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/backend_builders.py "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx/tools.py "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/tools.py "raw.githubusercontent.com"
[14]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py "raw.githubusercontent.com"
