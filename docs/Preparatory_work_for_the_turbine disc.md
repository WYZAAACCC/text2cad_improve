
```text
不实现涡轮盘/叶片的专有几何；
先把当前架构补成“可以可靠接入涡轮盘、叶片、叶盘、压气机盘等复杂 primitive family”的通用基础设施；
不能大改架构；
不能为了涡轮盘写死一条孤立链路；
必须继续复用 CAD-IR → validate → normalize → capability → build → metadata → inspection → mechanical_validation → demo/tests。
```

我先给判断：**当前仓库已经具备 primitive 化的核心骨架，但还需要把 gear-only 的几处实现抽象成 generic primitive infrastructure。** 当前 `PrimitiveFeature` 已经是通用结构，包含 `primitive_name`、`parameters`、`placement`、`operation`；`CADPartSpec` 也已经把 `PrimitiveFeature` 纳入 feature union，这说明不需要重构 CAD-IR 主体。([GitHub][1])

但几个关键位置仍然是“只服务齿轮”的实现：primitive registry 当前只导入 `GEAR_PRIMITIVES`；primitive compiler 只识别 `involute_spur_gear`；metadata sidecar 校验主要检查 gear 字段；mechanical validation dispatcher 只分发 gear validation；capability registry 目前 stable primitives 也只包含 `involute_spur_gear`。([GitHub][2])

---

# SeekFlow Engineering：涡轮盘/叶片 primitive 基础设施补充方案

## 1. 本次补充的目标

本次不做：

```text
axisymmetric_turbine_disk 的真实几何 kernel
turbine_blade 的真实叶型建模
fir-tree slot
叶片气动截面
复杂冷却孔
真实强度/寿命/适航判断
```

本次只做：

```text
通用 primitive family 注册机制
通用 primitive compiler dispatch
通用 primitive metadata schema
通用 primitive mechanical validation dispatch
通用 primitive_validation 字段
通用 demo primitive runner
通用 tests/fail-closed 机制
为 turbine_disk / turbine_blade 预留严格接口
```

完成后，后续新增：

```text
axisymmetric_turbine_disk
parametric_turbine_blade
compressor_blade
blisk
impeller
shaft_disk_assembly
```

都应该走同一套链路，而不是复制齿轮专用代码。

---

# 2. 当前架构允许保留的内容

Claude Code 不得大幅修改下面这些既有架构：

```text
CADPartSpec
PrimitiveFeature
engineering_validate_cad_ir
engineering_build_cad_model
Capability Registry
CadQuery backend
SolidWorks/NX canonical STEP import
demo_full_chain
tests
```

`engineering_validate_cad_ir` 当前已经负责 schema validation、deprecated recipe rewrite、recipe/primitive normalize、backend support 检查；`engineering_build_cad_model` 当前已经负责内部 normalize、选择 backend、禁止非显式 fallback、按 primitive strategy 路由。这个统一入口要继续保留，不能新增独立的 `build_turbine_disk_model` 或 `build_blade_model`。([GitHub][3])

---

# 3. 当前必须补强的 6 个通用扩展点

## 3.1 CAD-IR ValidationSpec 缺少通用 primitive_validation

当前 `ValidationSpec` 里有 bbox/body/hole，以及一组 gear-specific 字段，例如 `expected_tooth_count`、`expected_pitch_diameter_mm`、`expected_kernel`。这说明齿轮已经把一部分 primitive-specific validation 放进了通用 schema。后续如果把涡轮盘/叶片也继续这样塞，会导致 schema 爆炸。([GitHub][4])

必须新增：

```python
primitive_validation: dict[str, dict[str, Any]] = Field(default_factory=dict)
```

用途：

```json
{
  "validation": {
    "expected_bbox_mm": [480, 480, 60],
    "expected_body_count": 1,
    "expected_kernel": "cadquery_opencascade_revolve",
    "primitive_validation": {
      "disk1": {
        "expected_primitive": "axisymmetric_turbine_disk",
        "expected_outer_dia_mm": 480,
        "expected_bore_dia_mm": 80,
        "expected_axial_width_mm": 60
      },
      "blade1": {
        "expected_primitive": "parametric_turbine_blade",
        "expected_span_mm": 85,
        "expected_section_count": 9
      }
    }
  }
}
```

核心原则：

```text
ValidationSpec 保留通用字段；
primitive_validation 承载每个 primitive 自己的 expected 字段；
不再继续无限增加 expected_turbine_xxx / expected_blade_xxx 到 ValidationSpec 顶层。
```

---

## 3.2 Primitive Registry 仍是单 family 注册

当前 registry 已经改成 fail-closed，不再静默吞掉 gear import error，这是好的；但它仍然只导入 `GEAR_PRIMITIVES`，这会导致新增涡轮盘/叶片时继续在 registry 里硬写 family。([GitHub][2])

需要补成：

```text
多 primitive family 注册机制
```

但不能做太复杂。建议采用固定 module-path loader：

```python
PRIMITIVE_FAMILY_MODULES = [
    "seekflow_engineering_tools.geometry_primitives.gears.models:GEAR_PRIMITIVES",
    "seekflow_engineering_tools.geometry_primitives.turbomachinery.models:TURBOMACHINERY_PRIMITIVES",
]
```

其中 `turbomachinery.models` 可以先存在，但导出空列表：

```python
TURBOMACHINERY_PRIMITIVES: list[PrimitiveDefinition] = []
```

等后续实现涡轮盘/叶片时再加入：

```python
from .turbine_disk.models import TURBINE_DISK_PRIMITIVES
from .blade.models import TURBINE_BLADE_PRIMITIVES

TURBOMACHINERY_PRIMITIVES = [
    *TURBINE_DISK_PRIMITIVES,
    *TURBINE_BLADE_PRIMITIVES,
]
```

这样 registry 本身保持通用，不会因为新增 primitive family 再改核心代码。

---

## 3.3 Primitive compiler 仍是 hardcoded gear dispatch

当前 `primitive_compiler.py` 只有：

```python
if name == "involute_spur_gear":
    return _compile_involute_spur_gear(feature)

raise PrimitiveCompileError(...)
```

也就是说，它现在还不是通用 primitive compiler，只是 gear compiler。([GitHub][5])

需要补成：

```text
通用 primitive compiler handler registry
```

建议接口：

```python
PrimitiveCompileHandler = Callable[[Any], list[str]]

PRIMITIVE_COMPILERS: dict[str, PrimitiveCompileHandler] = {}

def register_primitive_compiler(name: str, handler: PrimitiveCompileHandler) -> None:
    ...

def list_primitive_compiler_names() -> list[str]:
    ...

def compile_primitive_to_cadquery_script(feature) -> list[str]:
    handler = PRIMITIVE_COMPILERS.get(feature.primitive_name)
    if handler is None:
        raise PrimitiveCompileError(...)
    return handler(feature)
```

gear 自己注册：

```python
register_primitive_compiler("involute_spur_gear", _compile_involute_spur_gear)
```

未来涡轮盘注册：

```python
register_primitive_compiler("axisymmetric_turbine_disk", _compile_axisymmetric_turbine_disk)
```

未来叶片注册：

```python
register_primitive_compiler("parametric_turbine_blade", _compile_parametric_turbine_blade)
```

这不是大重构，只是把 `if name == ...` 改成 map dispatch。

---

## 3.4 Metadata sidecar 校验仍偏 gear

当前 `_assert_metadata_sidecar()` 会检查：

```text
primitive_metadata
build_warnings
involute_spur_gear.kernel
involute_spur_gear.reference_dimensions
involute_spur_gear.parameters
involute_spur_gear.is_standard_involute
```

这说明 sidecar 验证机制已经存在，但字段检查还偏 gear。([GitHub][6])

需要补成两层：

```text
通用 primitive metadata v1 校验
+
primitive-specific metadata 校验
```

通用 metadata v1 每个 primitive 都必须有：

```json
{
  "primitive": "axisymmetric_turbine_disk",
  "metadata_version": "primitive_metadata_v1",
  "kernel": "cadquery_opencascade_revolve",
  "parameters": {},
  "reference_dimensions": {},
  "warnings": []
}
```

齿轮再要求：

```text
is_standard_involute
```

涡轮盘后续再要求：

```text
is_axisymmetric_base
radial_zones
profile_points
hole_patterns
non_flight_reference_only
```

叶片后续再要求：

```text
airfoil_sections
span_stations
chord_distribution
twist_distribution
root_attachment
non_flight_reference_only
```

这样 metadata sidecar 可以支撑复杂 primitive，但不被涡轮盘写死。

---

## 3.5 Mechanical validation dispatcher 仍只处理 gear

当前 `validate_mechanical_primitives()` 只对 `involute_spur_gear` 分发到 `validate_involute_spur_gear_result()`。([GitHub][7])

需要补成：

```text
mechanical validation handler registry
```

建议接口：

```python
PrimitiveValidationHandler = Callable[..., dict]

PRIMITIVE_VALIDATORS: dict[str, PrimitiveValidationHandler] = {}

def register_primitive_validator(name: str, handler: PrimitiveValidationHandler) -> None:
    ...

def validate_one_primitive(feature, spec, step_path, inspection) -> dict:
    handler = PRIMITIVE_VALIDATORS.get(feature.primitive_name)
    if handler is None:
        return fail-closed unsupported primitive validation
```

gear 注册：

```python
register_primitive_validator("involute_spur_gear", _validate_gear_feature)
```

未来涡轮盘注册：

```python
register_primitive_validator("axisymmetric_turbine_disk", _validate_turbine_disk_feature)
```

未来叶片注册：

```python
register_primitive_validator("parametric_turbine_blade", _validate_turbine_blade_feature)
```

注意：**没有 validator 时必须 fail-closed**，不能因为 primitive build 成功就算 mechanical validation 成功。

---

## 3.6 Capability registry 还需要支持 future primitives 的统一声明

当前 capability registry 已经有 `backend_supports_primitive()` 和 `get_primitive_strategy()`，这是好的；但 stable primitives 目前仍只有 gear。([GitHub][8])

本次基础设施可以先不把涡轮盘/叶片加入 stable primitives，因为专有 kernel 还没实现。

但需要约束：

```text
只有 primitive definition + compiler + validator + metadata 校验 + tests 全部存在后，才能加入 stable_primitives。
```

也就是说，Claude Code 不能先把：

```text
axisymmetric_turbine_disk
parametric_turbine_blade
```

加入 stable list，然后没有 kernel/validator 也宣称支持。

---

# 4. 本次补充的最终目标状态

完成后，当前仓库应该具备以下通用能力：

```text
1. CAD-IR 能为任意 primitive feature 指定 primitive_validation。
2. Registry 能加载多个 primitive family。
3. Compiler 能通过 handler map 分发多个 primitive。
4. Metadata sidecar 有通用 primitive metadata v1 校验。
5. Mechanical validation 能通过 handler map 分发多个 primitive。
6. 没有 mechanical validator 的 primitive 必须 fail。
7. Demo 可以复用 generic primitive case runner。
8. Tests 能防止新增 primitive 绕过 metadata / validation / capability。
9. 涡轮盘和叶片后续只需要新增自己的 definition/kernel/validator，而不用改主链路。
```

---

# 5. Claude Code 具体实施任务

## P0-1：修改 `ValidationSpec`，新增 `primitive_validation`

### 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/ir/cad.py
```

### 修改内容

在 `ValidationSpec` 中新增：

```python
primitive_validation: dict[str, dict[str, Any]] = Field(default_factory=dict)
```

新增 validator：

```python
@model_validator(mode="after")
def validate_primitive_validation(self):
    if self.primitive_validation is None:
        self.primitive_validation = {}
    if not isinstance(self.primitive_validation, dict):
        raise ValueError("primitive_validation must be a dict mapping feature_id to expected primitive validation spec")
    for feature_id, expected in self.primitive_validation.items():
        if not isinstance(feature_id, str) or not feature_id.strip():
            raise ValueError("primitive_validation keys must be non-empty feature ids")
        if not isinstance(expected, dict):
            raise ValueError(f"primitive_validation['{feature_id}'] must be a dict")
    return self
```

### 不允许

```text
不允许新增大量 turbine/blade 专用字段到 ValidationSpec 顶层。
不允许破坏已有 gear expected_* 字段。
```

### 测试

新增或修改：

```text
tests/test_primitive_validation_schema.py
```

测试：

```python
def test_validation_spec_accepts_primitive_validation_dict():
    ...

def test_validation_spec_rejects_empty_primitive_validation_feature_id():
    ...

def test_validation_spec_rejects_non_dict_primitive_validation_value():
    ...

def test_existing_gear_validation_fields_still_work():
    ...
```

---

## P0-2：把 Primitive Registry 改成多 family loader

### 文件

```text
src/seekflow_engineering_tools/geometry_primitives/registry.py
```

### 当前问题

当前只加载 gear family。([GitHub][2])

### 目标实现

新增：

```python
from importlib import import_module

PRIMITIVE_FAMILY_MODULES = [
    "seekflow_engineering_tools.geometry_primitives.gears.models:GEAR_PRIMITIVES",
    "seekflow_engineering_tools.geometry_primitives.turbomachinery.models:TURBOMACHINERY_PRIMITIVES",
]
```

实现：

```python
def _load_definitions_from_module(path: str) -> list[PrimitiveDefinition]:
    module_name, attr_name = path.split(":", 1)
    module = import_module(module_name)
    definitions = getattr(module, attr_name)
    if not isinstance(definitions, list):
        raise TypeError(f"{path} must export a list of PrimitiveDefinition")
    for item in definitions:
        if not isinstance(item, PrimitiveDefinition):
            raise TypeError(f"{path} contains non-PrimitiveDefinition item: {item!r}")
    return definitions
```

更新 `_populate_registry()`：

```python
def _populate_registry():
    PRIMITIVE_REGISTRY.clear()
    _REGISTRY_LOAD_ERRORS.clear()

    for module_path in PRIMITIVE_FAMILY_MODULES:
        try:
            definitions = _load_definitions_from_module(module_path)
            _register_all(definitions, source=module_path)
        except Exception as exc:
            _REGISTRY_LOAD_ERRORS.append(
                f"Failed to import primitive family {module_path}: "
                f"{type(exc).__name__}: {exc}"
            )
```

注意：这里捕获 `Exception` 是为了把 import/type/schema 错误都转成 registry health error。后续 `list_primitive_names()` / `get_primitive()` 必须抛 RuntimeError。

### 新增目录

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/
```

新增：

```text
__init__.py
models.py
```

`models.py` 内容：

```python
from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.base import PrimitiveDefinition

TURBOMACHINERY_PRIMITIVES: list[PrimitiveDefinition] = []
```

### 不允许

```text
不允许在 registry 里直接 import turbine_disk.models 或 blade.models。
不允许 except ImportError: pass。
不允许 family import 失败后继续返回不完整 registry。
```

### 测试

新增：

```text
tests/test_primitive_family_registry.py
```

测试：

```python
def test_registry_loads_multiple_family_modules():
    names = list_primitive_names()
    assert "involute_spur_gear" in names

def test_turbomachinery_family_exists_but_can_be_empty():
    import seekflow_engineering_tools.geometry_primitives.turbomachinery.models as m
    assert isinstance(m.TURBOMACHINERY_PRIMITIVES, list)

def test_registry_fails_closed_on_family_import_error(monkeypatch):
    ...

def test_registry_rejects_duplicate_primitive_names(monkeypatch):
    ...

def test_registry_rejects_non_primitive_definition_exports(monkeypatch):
    ...
```

---

## P0-3：把 primitive compiler 改成 handler registry

### 文件

```text
src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
```

### 当前问题

当前只识别 `involute_spur_gear`，unknown primitive 报错中也只列出 gear。([GitHub][5])

### 目标实现

新增：

```python
from collections.abc import Callable
from typing import Any

PrimitiveCompileHandler = Callable[[Any], list[str]]

PRIMITIVE_COMPILERS: dict[str, PrimitiveCompileHandler] = {}
```

新增函数：

```python
def register_primitive_compiler(name: str, handler: PrimitiveCompileHandler) -> None:
    if not name or not name.strip():
        raise ValueError("primitive compiler name must be non-empty")
    if name in PRIMITIVE_COMPILERS:
        raise ValueError(f"Primitive compiler already registered: {name}")
    PRIMITIVE_COMPILERS[name] = handler


def list_primitive_compiler_names() -> list[str]:
    return sorted(PRIMITIVE_COMPILERS.keys())


def compile_primitive_to_cadquery_script(feature) -> list[str]:
    name = feature.primitive_name
    handler = PRIMITIVE_COMPILERS.get(name)
    if handler is None:
        raise PrimitiveCompileError(
            f"Unknown primitive '{name}'. "
            f"Available primitive compilers: {list_primitive_compiler_names()}"
        )
    return handler(feature)
```

文件底部注册 gear：

```python
register_primitive_compiler("involute_spur_gear", _compile_involute_spur_gear)
```

### 重要约束

保留 `_compile_involute_spur_gear()` 现有逻辑，不要重写 gear kernel。

### 未来扩展示例，作为注释即可

```python
# Future:
# register_primitive_compiler("axisymmetric_turbine_disk", _compile_axisymmetric_turbine_disk)
# register_primitive_compiler("parametric_turbine_blade", _compile_parametric_turbine_blade)
```

不要现在注册未实现的 primitive。

### 测试

新增：

```text
tests/test_primitive_compiler_registry.py
```

测试：

```python
def test_gear_compiler_registered():
    assert "involute_spur_gear" in list_primitive_compiler_names()

def test_unknown_primitive_compiler_fails_with_available_list():
    ...

def test_duplicate_primitive_compiler_registration_fails():
    ...

def test_register_temp_compiler_and_compile(monkeypatch):
    ...
```

---

## P0-4：新增通用 primitive metadata v1 校验模块

### 新增文件

```text
src/seekflow_engineering_tools/mechanical_validation/primitive_metadata.py
```

或者：

```text
src/seekflow_engineering_tools/cadquery_backend/primitive_metadata.py
```

推荐放在：

```text
src/seekflow_engineering_tools/mechanical_validation/primitive_metadata.py
```

因为 builder 和 mechanical validation 都会用。

### 固定通用 schema

每个 primitive metadata 必须满足：

```python
REQUIRED_PRIMITIVE_METADATA_KEYS = [
    "primitive",
    "kernel",
    "parameters",
    "reference_dimensions",
]
```

`warnings` 允许缺省，但校验时应 normalize 成空 list。

推荐函数：

```python
def validate_primitive_metadata_v1(
    *,
    primitive_name: str,
    metadata: dict | None,
) -> dict:
    """
    Return:
    {
      "ok": bool,
      "issues": list[dict],
      "normalized_metadata": dict | None
    }
    """
```

必须检查：

```text
metadata exists
metadata is dict
metadata["primitive"] == primitive_name
kernel exists and is non-empty str
parameters exists and is dict
reference_dimensions exists and is dict
warnings if present must be list[str]
metadata_version if present must be "primitive_metadata_v1"
```

返回 issue 格式：

```python
{
    "code": "primitive_metadata_missing_kernel",
    "message": "Primitive metadata for axisymmetric_turbine_disk missing kernel.",
    "severity": "error",
}
```

### 示例实现约束

不要使用 Pydantic 强行替换所有 dict；当前项目大量使用 dict result，保持一致即可。

### 测试

新增：

```text
tests/test_primitive_metadata_v1.py
```

测试：

```python
def test_valid_primitive_metadata_v1_passes():
    ...

def test_missing_metadata_fails():
    ...

def test_primitive_name_mismatch_fails():
    ...

def test_missing_kernel_fails():
    ...

def test_missing_parameters_fails():
    ...

def test_missing_reference_dimensions_fails():
    ...

def test_warnings_normalized_to_empty_list():
    ...

def test_bad_warnings_type_fails():
    ...
```

---

## P0-5：把 builder metadata sidecar 检查改成 generic + gear-specific

### 文件

```text
src/seekflow_engineering_tools/cadquery_backend/builder.py
```

### 当前问题

当前 `_assert_metadata_sidecar()` 的 docstring 和实际检查都偏向 gear。([GitHub][6])

### 目标

`_assert_metadata_sidecar()` 应该：

```text
1. 检查 metadata 文件存在且非空；
2. 检查 JSON 合法；
3. 检查 top-level primitive_metadata；
4. 检查 top-level build_warnings；
5. 对每个 PrimitiveFeature：
   - 找到 primitive_metadata[feature.primitive_name]
   - 调 validate_primitive_metadata_v1
   - 调 primitive-specific metadata checker
```

新增函数：

```python
def _assert_primitive_specific_metadata(
    primitive_name: str,
    primitive_meta: dict,
) -> None:
    if primitive_name == "involute_spur_gear":
        ...
    elif primitive_name == "axisymmetric_turbine_disk":
        ...
    elif primitive_name == "parametric_turbine_blade":
        ...
    else:
        # no specific checker yet
        return
```

注意：

```text
当前不要真的实现 turbine disk / blade checker 的硬字段要求；
因为这些 primitive 还没实现。
```

但可以写预留分支注释，不能注册未实现 primitive。

### gear-specific 继续保留

gear 必须继续检查：

```text
is_standard_involute
```

最好也检查：

```text
primitive == "involute_spur_gear"
```

### 不允许

```text
不允许 metadata 缺失但 ok=True。
不允许 primitive_metadata 缺少当前 primitive entry 但 ok=True。
不允许 unknown primitive metadata 直接通过所有检查；至少通用 metadata 必须过。
```

### 测试

新增或扩展：

```text
tests/test_primitive_metadata_sidecar_generic.py
```

测试：

```python
def test_sidecar_requires_primitive_metadata_key():
    ...

def test_sidecar_requires_build_warnings_key():
    ...

def test_sidecar_requires_entry_for_each_primitive_feature():
    ...

def test_sidecar_requires_generic_metadata_keys_for_unknown_test_primitive():
    ...

def test_sidecar_preserves_gear_specific_is_standard_involute_requirement():
    ...

def test_sidecar_allows_future_primitive_with_valid_generic_metadata():
    ...
```

这里的 future primitive 可以用 monkeypatch 构造一个 fake `PrimitiveFeature`，不要加入 capability stable list。

---

## P0-6：把 mechanical validation 改成 handler registry

### 文件

```text
src/seekflow_engineering_tools/mechanical_validation/common.py
```

### 当前问题

当前只分发 gear。([GitHub][7])

### 目标

新增：

```python
from collections.abc import Callable
from typing import Any

PrimitiveMechanicalValidator = Callable[..., dict]

PRIMITIVE_MECHANICAL_VALIDATORS: dict[str, PrimitiveMechanicalValidator] = {}
```

推荐接口：

```python
def register_primitive_mechanical_validator(
    primitive_name: str,
    handler: PrimitiveMechanicalValidator,
) -> None:
    ...


def list_primitive_mechanical_validator_names() -> list[str]:
    ...


def _expected_for_feature(spec, feature) -> dict:
    pv = getattr(spec.validation, "primitive_validation", {}) or {}
    return pv.get(feature.id, {})
```

`validate_mechanical_primitives()` 改成：

```python
def validate_mechanical_primitives(spec, step_path: Path, inspection: dict) -> dict:
    results = []
    overall_ok = True

    metadata_path = Path(str(step_path)).with_suffix(".metadata.json")
    raw_metadata = load_metadata(metadata_path)

    for feature in spec.features:
        if getattr(feature, "type", None) != "primitive":
            continue

        name = feature.primitive_name
        handler = PRIMITIVE_MECHANICAL_VALIDATORS.get(name)

        if handler is None:
            result = {
                "ok": False,
                "primitive": name,
                "issues": [
                    {
                        "code": "primitive_mechanical_validator_missing",
                        "message": f"No mechanical validator registered for primitive '{name}'.",
                        "severity": "error",
                    }
                ],
            }
        else:
            metadata = _unwrap_primitive_metadata(raw_metadata, name)
            expected = _expected_for_feature(spec, feature)
            result = handler(
                feature=feature,
                spec=spec,
                step_path=step_path,
                inspection=inspection,
                raw_metadata=raw_metadata,
                metadata=metadata,
                expected=expected,
            )

        results.append(result)
        if result.get("ok") is not True:
            overall_ok = False

    return {"ok": overall_ok, "results": results}
```

### Gear adapter handler

为了不重写 gear validation，可以新增：

```python
def _validate_involute_spur_gear_feature(
    *,
    feature,
    spec,
    step_path,
    inspection,
    raw_metadata,
    metadata,
    expected,
) -> dict:
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    legacy_expected = {
        "expected_kernel": getattr(spec.validation, "expected_kernel", None),
        "expected_tooth_count": getattr(spec.validation, "expected_tooth_count", None),
        ...
    }

    merged_expected = {**legacy_expected, **(expected or {})}

    return validate_involute_spur_gear_result(
        params=feature.parameters,
        inspection=inspection,
        metadata=metadata,
        tolerance_mm=spec.validation.tolerance_mm,
        expected=merged_expected,
        raw_metadata=raw_metadata,
    )
```

文件底部：

```python
register_primitive_mechanical_validator(
    "involute_spur_gear",
    _validate_involute_spur_gear_feature,
)
```

### 不允许

```text
没有 validator 的 primitive 不能 ok=True。
不能因为 results 为空就 ok=True，如果 spec 有 primitive 且无 validator，必须 fail。
```

### 测试

新增：

```text
tests/test_primitive_mechanical_validation_dispatch.py
```

测试：

```python
def test_gear_validator_registered():
    ...

def test_missing_primitive_validator_fails_closed():
    ...

def test_expected_for_feature_reads_primitive_validation():
    ...

def test_validator_result_missing_ok_fails_overall():
    ...

def test_generic_dispatch_passes_metadata_and_expected_to_handler(monkeypatch):
    ...
```

---

## P1-1：新增通用 primitive case runner 给 demo 使用

### 文件

```text
demo_full_chain.py
```

当前 demo 已有 `_finalize_case_report()`，这是好的，说明 demo 已经不再只靠 build ok 判断成功。([GitHub][3])

但 gear case runner 仍是专用 `_run_gear_case()`。为了支撑后续涡轮盘/叶片，不要为每个 primitive 复制一份 200 行 demo。

### 新增函数

```python
def _run_primitive_case(
    *,
    case_name: str,
    backend: str,
    output_root: Path,
    primitive_name: str,
    feature_id: str,
    params: dict,
    validation: dict,
    step_filename: str,
    required_metrics: list[str],
    allow_step_import: bool = False,
    expected_kernel: str | None = None,
) -> dict:
    ...
```

这个函数应执行：

```text
make report skeleton
build spec_dict
validate_fn(spec_dict)
stage validate_cad_ir
stage normalize_primitives
stage choose_backend
get_primitive_strategy
build_fn(spec_dict, ...)
stage build
stage inspect
stage mechanical_validate
stage metadata
collect kernel_used
collect reference_dimensions
finalize required stages + metrics
```

gear case 可以继续保留，也可以改用 generic runner，但不要一次性大改太多。推荐：

```text
先新增 generic primitive runner；
保持 gear case 现有逻辑；
新增测试证明 generic runner 可用于 fake primitive；
后续 turbine disk / blade demo 再使用 generic runner。
```

### 必须 stage

```python
GENERIC_PRIMITIVE_REQUIRED_STAGES = [
    "validate_cad_ir",
    "normalize_primitives",
    "choose_backend",
    "build",
    "inspect",
    "mechanical_validate",
    "metadata",
]
```

### metadata stage 通用读取

不要写死 gear：

```python
pm = sidecar.get("primitive_metadata", {}).get(primitive_name)
```

metrics：

```python
report["metrics"] = {
    "kernel_used": pm.get("kernel", "unknown"),
    "reference_dimensions": pm.get("reference_dimensions", {}),
    "strategy": strategy,
}
```

### 测试

新增：

```text
tests/test_demo_full_chain_generic_primitive.py
```

测试：

```python
def test_generic_primitive_case_fails_when_metadata_missing():
    ...

def test_generic_primitive_case_fails_when_mechanical_validation_missing():
    ...

def test_generic_primitive_case_fails_when_required_metric_missing():
    ...

def test_generic_primitive_case_passes_with_valid_mocked_build():
    ...
```

---

## P1-2：新增 turbomachinery skill contract，但不实现涡轮盘/叶片特有输出

### 新增目录

```text
.claude/skills/turbomachinery-cad-ir/
```

新增文件：

```text
SKILL.md
```

### 目标

这个 skill 不是几何内核。它只定义未来涡轮盘/叶片自然语言转 CAD-IR 的边界。

### 固定内容

```markdown
# Turbomachinery CAD-IR Skill

This skill converts natural-language turbomachinery modeling requests into SeekFlow Engineering CAD-IR.

It must not generate CadQuery, SolidWorks COM, NXOpen, APDL, or any direct CAD backend code.

It must output CAD-IR only.

## Supported phase

This skill only prepares structured CAD-IR for registered primitives.

If the requested primitive is not registered in Primitive Registry and not supported by Capability Registry, return an unsupported primitive diagnostic.

## Safety boundary

Aero-engine turbine disks and blades are safety-critical rotating parts.

The output is reference geometry only unless the project later adds verified engineering validation, FEA, life analysis, manufacturing review, and certification workflow.

The skill must not claim:
- flight-ready
- airworthy
- certified
- manufacturing-ready
- burst-safe
- fatigue-safe
- life-approved

## Current reserved primitive names

Reserved but not necessarily implemented:
- axisymmetric_turbine_disk
- parametric_turbine_blade

The skill must not emit these primitive names unless they are registered in the current Primitive Registry and supported by the requested backend.

## Missing parameters

The skill must not invent required parameters.

If a required parameter is missing, return a missing-parameter diagnostic instead of CAD-IR.

## Output contract

When a primitive is supported, output a CADPartSpec-compatible JSON object:
- nlcad_version = "0.1"
- units = "mm"
- features[].type = "primitive"
- features[].primitive_name = registered primitive name
- validation.primitive_validation[feature_id] contains primitive-specific expected fields
```

### 测试

新增：

```text
tests/test_turbomachinery_skill_contract.py
```

测试：

```python
def test_skill_forbids_direct_cad_code_generation():
    ...

def test_skill_mentions_reference_geometry_only():
    ...

def test_skill_forbids_airworthy_certified_manufacturing_ready_claims():
    ...

def test_skill_requires_registered_primitive_before_emitting_reserved_names():
    ...

def test_skill_requires_missing_parameter_diagnostic():
    ...
```

---

## P1-3：新增 future primitive reserved name 检查，不允许未实现就宣称支持

### 文件

```text
tests/test_future_primitive_support_contract.py
```

目的：防止 Claude Code 把 `axisymmetric_turbine_disk` 或 `parametric_turbine_blade` 加到 stable_primitives，但没有 kernel/validator。

测试逻辑：

```python
RESERVED_FUTURE_PRIMITIVES = [
    "axisymmetric_turbine_disk",
    "parametric_turbine_blade",
]

def test_reserved_future_primitives_not_stable_without_full_implementation():
    from seekflow_engineering_tools.capabilities.registry import CAPABILITIES
    from seekflow_engineering_tools.geometry_primitives.registry import list_primitive_names
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import list_primitive_compiler_names
    from seekflow_engineering_tools.mechanical_validation.common import list_primitive_mechanical_validator_names

    names = set(list_primitive_names())
    compilers = set(list_primitive_compiler_names())
    validators = set(list_primitive_mechanical_validator_names())

    for backend, cap in CAPABILITIES.items():
        stable = set(cap.get("stable_primitives", []))
        for prim in RESERVED_FUTURE_PRIMITIVES:
            if prim in stable:
                assert prim in names
                assert prim in compilers
                assert prim in validators
```

这个测试非常关键：它允许后续实现涡轮盘/叶片，但不允许“假支持”。

---

# 6. 完成后推荐的目录结构

完成本次基础设施补充后，目录应该类似：

```text
integrations/engineering_tools/
  src/seekflow_engineering_tools/
    ir/
      cad.py
      primitive.py

    geometry_primitives/
      base.py
      registry.py
      gears/
        models.py
        ...
      turbomachinery/
        __init__.py
        models.py

    cadquery_backend/
      compiler.py
      primitive_compiler.py
      builder.py

    mechanical_validation/
      common.py
      primitive_metadata.py
      gear_validation.py

    capabilities/
      registry.py

  .claude/skills/
    turbomachinery-cad-ir/
      SKILL.md

  tests/
    test_primitive_validation_schema.py
    test_primitive_family_registry.py
    test_primitive_compiler_registry.py
    test_primitive_metadata_v1.py
    test_primitive_metadata_sidecar_generic.py
    test_primitive_mechanical_validation_dispatch.py
    test_demo_full_chain_generic_primitive.py
    test_turbomachinery_skill_contract.py
    test_future_primitive_support_contract.py
```

---

# 7. 严格禁止事项

Claude Code 必须遵守：

```text
1. 不得实现真实涡轮盘几何。
2. 不得实现真实叶片几何。
3. 不得把 axisymmetric_turbine_disk 加入 stable_primitives，除非同时实现 definition/compiler/kernel/validator/metadata/mechanical_validation/tests。
4. 不得把 parametric_turbine_blade 加入 stable_primitives，除非同时实现完整链路。
5. 不得新增独立 build_turbine_disk 或 build_turbine_blade tool。
6. 不得绕过 engineering_validate_cad_ir / engineering_build_cad_model。
7. 不得让 metadata 缺失时 ok=True。
8. 不得让 mechanical validator 缺失时 ok=True。
9. 不得继续在 registry 里写 except ImportError: pass。
10. 不得把 primitive-specific 字段无限塞到 ValidationSpec 顶层。
11. 不得让 SolidWorks/NX 重新生成复杂 primitive；它们仍然只能 canonical STEP import。
12. 不得让 skill 生成 CadQuery/SolidWorks/NXOpen/APDL 代码。
```

---

# 8. Claude Code 总 Prompt

下面这段可以直接复制给 Claude Code：

```text
你要在 WYZAAACCC/seekflow-engineering 的 integrations/engineering_tools 子项目中补强通用 primitive 基础设施，为后续航空发动机涡轮盘和叶片 primitive 构建提供支撑。

重要：本次任务不实现涡轮盘或叶片的专有几何 kernel，不实现真实叶型，不实现 fir-tree slot，不实现冷却孔，不实现强度/寿命/适航逻辑。你只做通用基础设施，让未来新增 axisymmetric_turbine_disk、parametric_turbine_blade 等 primitive 时无需再改主链路。

必须保持当前架构：
CAD-IR → engineering_validate_cad_ir → primitive registry/capability registry → engineering_build_cad_model → CadQuery deterministic primitive compiler → STEP + metadata → inspection → mechanical_validation → optional SolidWorks/NX canonical STEP import。

不得新增 build_turbine_disk_model 或 build_blade_model 这种独立工具。

请严格完成以下任务：

1. 修改 src/seekflow_engineering_tools/ir/cad.py
   - 在 ValidationSpec 中新增：
     primitive_validation: dict[str, dict[str, Any]] = Field(default_factory=dict)
   - 增加 validator：
     primitive_validation key 必须是非空 feature id；
     value 必须是 dict。
   - 不要把涡轮盘/叶片专用 expected 字段加到 ValidationSpec 顶层。
   - 保留现有 gear expected_* 字段兼容性。

2. 修改 src/seekflow_engineering_tools/geometry_primitives/registry.py
   - 把当前只加载 gear 的逻辑改为多 primitive family loader。
   - 使用：
     PRIMITIVE_FAMILY_MODULES = [
       "seekflow_engineering_tools.geometry_primitives.gears.models:GEAR_PRIMITIVES",
       "seekflow_engineering_tools.geometry_primitives.turbomachinery.models:TURBOMACHINERY_PRIMITIVES",
     ]
   - 实现 _load_definitions_from_module(path)。
   - family import/type/schema 出错必须记录 _REGISTRY_LOAD_ERRORS。
   - list_primitive_names/get_primitive 必须在 registry unhealthy 时 raise RuntimeError。
   - 禁止 except ImportError: pass。
   - 保持 normalize_primitive_parameters 现有 gear validator 行为。

3. 新增 src/seekflow_engineering_tools/geometry_primitives/turbomachinery/
   - __init__.py
   - models.py
   - models.py 中只导出：
     TURBOMACHINERY_PRIMITIVES: list[PrimitiveDefinition] = []
   - 不要注册 axisymmetric_turbine_disk 或 parametric_turbine_blade，除非你同时完成完整实现；本任务不要求实现它们。

4. 修改 src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
   - 把 if primitive_name == "involute_spur_gear" 改成 handler registry。
   - 新增：
     PrimitiveCompileHandler
     PRIMITIVE_COMPILERS
     register_primitive_compiler
     list_primitive_compiler_names
   - compile_primitive_to_cadquery_script(feature) 从 PRIMITIVE_COMPILERS 里查 handler。
   - 未注册 primitive 必须 raise PrimitiveCompileError，并列出 available primitive compilers。
   - 保留 _compile_involute_spur_gear 原逻辑。
   - 文件底部注册：
     register_primitive_compiler("involute_spur_gear", _compile_involute_spur_gear)
   - 不要注册未实现的涡轮盘/叶片 primitive。

5. 新增 src/seekflow_engineering_tools/mechanical_validation/primitive_metadata.py
   - 实现 validate_primitive_metadata_v1(primitive_name: str, metadata: dict | None) -> dict
   - 必须检查：
     metadata exists
     metadata is dict
     metadata["primitive"] == primitive_name
     kernel exists and is non-empty str
     parameters exists and is dict
     reference_dimensions exists and is dict
     warnings if present must be list
     metadata_version if present must be "primitive_metadata_v1"
   - 返回：
     {"ok": bool, "issues": list[dict], "normalized_metadata": dict | None}
   - warnings 缺失时 normalize 为 []。
   - issue 格式必须包含 code/message/severity。

6. 修改 src/seekflow_engineering_tools/cadquery_backend/builder.py
   - 把 _assert_metadata_sidecar 改成 generic primitive metadata 检查。
   - 对每个 PrimitiveFeature：
     找 primitive_metadata[feature.primitive_name]
     调 validate_primitive_metadata_v1
     通用 metadata 不通过则 raise ValueError。
   - 保留 gear-specific 检查：
     involute_spur_gear 必须有 is_standard_involute。
   - 不要为未实现的 turbine_disk/blade 写硬检查。
   - metadata 缺失、primitive entry 缺失、kernel 缺失、parameters 缺失、reference_dimensions 缺失都必须 fail。

7. 修改 src/seekflow_engineering_tools/mechanical_validation/common.py
   - 把 validate_mechanical_primitives 改成 handler registry。
   - 新增：
     PRIMITIVE_MECHANICAL_VALIDATORS
     register_primitive_mechanical_validator
     list_primitive_mechanical_validator_names
   - 没有 registered mechanical validator 的 primitive 必须 fail-closed，返回 ok=False issue code primitive_mechanical_validator_missing。
   - 为 involute_spur_gear 注册 adapter handler，内部继续调用 validate_involute_spur_gear_result。
   - adapter handler 要合并：
     旧的 spec.validation 顶层 gear expected_* 字段
     和 spec.validation.primitive_validation[feature.id]
   - validator result.get("ok") is not True 时 overall_ok=False。
   - 不要注册未实现的 turbine_disk/blade validator。

8. 修改 demo_full_chain.py
   - 新增通用 _run_primitive_case(...) helper。
   - 它必须走 engineering_validate_cad_ir 和 engineering_build_cad_model。
   - 它必须包含 stages：
     validate_cad_ir
     normalize_primitives
     choose_backend
     build
     inspect
     mechanical_validate
     metadata
   - metadata stage 必须按 primitive_name 从 sidecar 中读取。
   - required metric 缺失必须 fail。
   - 不要把 build_result.get("ok") 单独作为 overall_ok。
   - 可以暂时不新增 turbine_disk/blade demo case，因为专有 primitive 还没实现。
   - 保持现有 gear demo 通过。

9. 新增 .claude/skills/turbomachinery-cad-ir/SKILL.md
   - 说明该 skill 只输出 CAD-IR。
   - 禁止生成 CadQuery/SolidWorks/NXOpen/APDL 代码。
   - 说明涡轮盘/叶片是 safety-critical rotating parts。
   - 禁止声称 flight-ready/airworthy/certified/manufacturing-ready/burst-safe/fatigue-safe/life-approved。
   - 说明 reserved primitive names:
     axisymmetric_turbine_disk
     parametric_turbine_blade
   - 但必须写明：只有当 primitive 已在 Primitive Registry 注册并被 Capability Registry 支持时，skill 才能输出这些 primitive name。
   - 必填参数缺失时必须输出 missing-parameter diagnostic，不得猜参数。

10. 新增测试：
   tests/test_primitive_validation_schema.py
   tests/test_primitive_family_registry.py
   tests/test_primitive_compiler_registry.py
   tests/test_primitive_metadata_v1.py
   tests/test_primitive_metadata_sidecar_generic.py
   tests/test_primitive_mechanical_validation_dispatch.py
   tests/test_demo_full_chain_generic_primitive.py
   tests/test_turbomachinery_skill_contract.py
   tests/test_future_primitive_support_contract.py

测试必须覆盖：
- primitive_validation 接受 dict
- primitive_validation 拒绝空 feature id
- primitive_validation 拒绝非 dict value
- registry 能加载 gear + empty turbomachinery family
- registry family import error fail-closed
- registry duplicate primitive fail
- primitive compiler registry 中 gear 已注册
- unknown primitive compiler fail
- duplicate compiler registration fail
- primitive metadata v1 valid pass
- missing metadata fail
- primitive mismatch fail
- missing kernel fail
- missing parameters fail
- missing reference_dimensions fail
- warnings normalize
- builder sidecar requires top-level primitive_metadata and build_warnings
- builder sidecar requires primitive entry for each PrimitiveFeature
- builder sidecar requires generic metadata keys
- gear still requires is_standard_involute
- mechanical validator missing fails closed
- gear mechanical validator still registered
- primitive_validation expected dict is passed to handler
- demo generic primitive runner metadata missing fails
- demo generic primitive runner mechanical_validation missing fails
- skill forbids CAD code generation and unsafe claims
- reserved future primitives cannot be stable unless registered, compiled, and mechanically validated

11. 运行：
cd integrations/engineering_tools
python -m compileall src demo_full_chain.py
python -m pytest

12. 成功标准：
- compileall 通过
- pytest 通过
- 现有 gear demo 不被破坏
- involute_spur_gear 仍然可 build/validate
- 没有未实现的 turbine disk/blade primitive 被加入 stable_primitives
- 没有 metadata/mechanical_validation 缺失仍 ok=True 的情况
- 未来新增 axisymmetric_turbine_disk / parametric_turbine_blade 时，只需新增 family definition、compiler handler、kernel、metadata、mechanical validator 和 tests，不需要再改主链路
```

---

# 9. Claude Code 完成后的自检报告模板

要求 Claude Code 完成后输出：

```text
## Primitive Infrastructure 补充完成报告

### 修改文件
- path
  - 修改内容
  - 对应风险

### 新增文件
- path
  - 用途

### 新增测试
- test_xxx.py
  - 覆盖场景

### 架构保持情况
- 是否仍走 engineering_validate_cad_ir:
- 是否仍走 engineering_build_cad_model:
- 是否没有新增 turbine-specific build tool:
- 是否 SW/NX 仍只支持 canonical STEP import:

### 命令结果
- python -m compileall src demo_full_chain.py:
- python -m pytest:

### 未实现但已预留
- axisymmetric_turbine_disk:
- parametric_turbine_blade:
- turbine_disk kernel:
- turbine_blade kernel:
```

---

# 10. 最终判断标准

这次补充不是为了“马上画出涡轮盘/叶片”，而是为了让后续涡轮盘/叶片开发不会污染主架构。

完成后应达到：

```text
当前架构 = 通用 primitive 平台
齿轮 = 其中一个 primitive family
涡轮盘 = 后续一个 primitive family
叶片 = 后续一个 primitive family
```

而不是：

```text
当前架构 = 齿轮专用架构
涡轮盘 = 又写一条特殊链路
叶片 = 再写一条特殊链路
```

我的建议是：**先让 Claude Code 完成本方案，再开始实现 `axisymmetric_turbine_disk`；等涡轮盘 primitive 跑通后，再实现 `parametric_turbine_blade`。** 这样最稳，也最符合你“保持通用性、不能大改架构、不能让 Claude Code 自己幻想参数和接口”的要求。

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/ir/primitive.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/demo_full_chain.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/ir/cad.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/common.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py "raw.githubusercontent.com"
