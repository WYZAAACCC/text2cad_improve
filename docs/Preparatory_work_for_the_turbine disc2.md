

# SeekFlow Engineering 通用 Primitive 基础设施补充方案

## 目标：充分支撑后续涡轮盘 / 叶片构建

## 一、核心判断

当前系统已经不是“完全不能扩展”，而是处在：

```text
齿轮 primitive 链路已经比较完整；
通用 primitive 平台还没有完全抽象；
涡轮盘 / 叶片不应该现在直接硬塞进去。
```

已有基础：

```text
CAD-IR 已支持 PrimitiveFeature；
engineering_validate_cad_ir / engineering_build_cad_model 已是统一入口；
Capability Registry 已支持 stable_primitives / primitive_strategy；
CadQuery builder 已有 STEP、metadata、inspection、mechanical_validation；
demo_full_chain 已有 finalize 机制；
gear primitive 的测试体系比较完整。
```

不足之处：

```text
ValidationSpec 缺 primitive_validation；
Primitive Registry 只加载 gear family；
Primitive Compiler 只 hardcode gear；
Metadata sidecar 校验偏 gear；
Mechanical validation 只 dispatch gear，未来 unknown primitive 有 fail-open 风险；
demo 缺 generic primitive runner；
tests 缺 generic primitive infrastructure 测试。
```

因此本次要做的不是“实现涡轮盘”，也不是“实现叶片”，而是：

```text
把当前 gear-oriented primitive 架构补成 generic primitive infrastructure。
```

完成后，后续新增：

```text
axisymmetric_turbine_disk
parametric_turbine_blade
compressor_blade
blisk
impeller
```

都只需要新增自己的：

```text
PrimitiveDefinition
parameter validator
deterministic geometry kernel
compiler handler
metadata schema
mechanical validator
demo case
tests
```

而不需要再改主链路。

---

# 二、绝对约束

Claude Code 必须遵守：

```text
1. 不实现涡轮盘专有几何。
2. 不实现叶片专有几何。
3. 不注册 axisymmetric_turbine_disk 为 stable primitive。
4. 不注册 parametric_turbine_blade 为 stable primitive。
5. 不新增 build_turbine_disk_model / build_blade_model 这类独立工具。
6. 不绕过 engineering_validate_cad_ir。
7. 不绕过 engineering_build_cad_model。
8. 不让 SolidWorks / NX 重新生成复杂 primitive；它们后续仍只 import canonical STEP。
9. 不让 metadata 缺失时 ok=True。
10. 不让 mechanical validator 缺失时 ok=True。
11. 不把涡轮盘 / 叶片专有字段硬塞进 ValidationSpec 顶层。
12. 不让 skill 生成 CadQuery / SolidWorks COM / NXOpen / APDL 代码。
```

---

# 三、本次补充后应达到的架构

目标链路：

```text
Natural Language
  ↓
Skill / parser outputs CAD-IR only
  ↓
CADPartSpec
  ↓
engineering_validate_cad_ir
  ↓
Primitive Registry
  ↓
Capability Registry
  ↓
engineering_build_cad_model
  ↓
CadQuery primitive compiler handler registry
  ↓
deterministic primitive kernel
  ↓
STEP + metadata.json
  ↓
inspection
  ↓
mechanical validation handler registry
  ↓
EngineeringActionResult
  ↓
optional SolidWorks / NX canonical STEP import
```

其中：

```text
涡轮盘 / 叶片未来只是 primitive family；
不是独立系统；
不是特殊 build path；
不是 LLM 代码生成。
```

---

# 四、P0 修复 1：ValidationSpec 增加通用 primitive_validation

## 4.1 当前问题

当前 `ValidationSpec` 有通用 bbox/body/hole 字段，也有 gear-specific 字段，例如 expected_tooth_count、expected_pitch_diameter_mm、expected_kernel 等，但没有 `primitive_validation`。如果后续做涡轮盘 / 叶片，继续往顶层塞字段会导致 schema 膨胀。([GitHub][1])

## 4.2 修改文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/ir/cad.py
```

## 4.3 必须新增字段

在 `ValidationSpec` 中新增：

```python
primitive_validation: dict[str, dict[str, Any]] = Field(default_factory=dict)
```

## 4.4 必须新增校验

```python
@model_validator(mode="after")
def validate_primitive_validation(self):
    if self.primitive_validation is None:
        self.primitive_validation = {}

    if not isinstance(self.primitive_validation, dict):
        raise ValueError(
            "primitive_validation must be a dict mapping feature id to expected primitive validation spec"
        )

    for feature_id, expected in self.primitive_validation.items():
        if not isinstance(feature_id, str) or not feature_id.strip():
            raise ValueError("primitive_validation keys must be non-empty feature ids")
        if not isinstance(expected, dict):
            raise ValueError(
                f"primitive_validation['{feature_id}'] must be a dict"
            )

    return self
```

## 4.5 使用方式

未来涡轮盘：

```json
{
  "validation": {
    "expected_bbox_mm": [480.0, 480.0, 60.0],
    "expected_body_count": 1,
    "expected_kernel": "cadquery_opencascade_revolve",
    "primitive_validation": {
      "disk1": {
        "expected_primitive": "axisymmetric_turbine_disk",
        "expected_outer_dia_mm": 480.0,
        "expected_bore_dia_mm": 80.0,
        "expected_axial_width_mm": 60.0,
        "expected_hub_outer_dia_mm": 150.0,
        "expected_web_outer_dia_mm": 380.0,
        "expected_rim_inner_dia_mm": 390.0
      }
    }
  }
}
```

未来叶片：

```json
{
  "validation": {
    "primitive_validation": {
      "blade1": {
        "expected_primitive": "parametric_turbine_blade",
        "expected_span_mm": 85.0,
        "expected_section_count": 9,
        "expected_root_attachment_type": "fir_tree_placeholder"
      }
    }
  }
}
```

## 4.6 禁止

```text
禁止新增 expected_turbine_disk_outer_dia_mm 到 ValidationSpec 顶层。
禁止新增 expected_blade_span_mm 到 ValidationSpec 顶层。
gear 现有字段保持兼容，不删除。
```

---

# 五、P0 修复 2：Primitive Registry 改成多 family loader

## 5.1 当前问题

当前 `geometry_primitives/registry.py` 只导入 `GEAR_PRIMITIVES`，说明它还不是多 primitive family registry。虽然它现在已经不是静默吞错，但仍是 gear-only 结构。([GitHub][2])

## 5.2 修改文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py
```

## 5.3 新增 family 模块路径列表

```python
from importlib import import_module

PRIMITIVE_FAMILY_MODULES = [
    "seekflow_engineering_tools.geometry_primitives.gears.models:GEAR_PRIMITIVES",
    "seekflow_engineering_tools.geometry_primitives.turbomachinery.models:TURBOMACHINERY_PRIMITIVES",
]
```

## 5.4 新增 loader

```python
def _load_definitions_from_module(path: str) -> list[PrimitiveDefinition]:
    if ":" not in path:
        raise ValueError(f"Primitive family path must be 'module:attribute', got {path!r}")

    module_name, attr_name = path.split(":", 1)
    module = import_module(module_name)
    definitions = getattr(module, attr_name)

    if not isinstance(definitions, list):
        raise TypeError(f"{path} must export a list[PrimitiveDefinition]")

    for item in definitions:
        if not isinstance(item, PrimitiveDefinition):
            raise TypeError(
                f"{path} contains non-PrimitiveDefinition item: {item!r}"
            )

    return definitions
```

## 5.5 新增统一注册函数

```python
def _register_all(definitions: list[PrimitiveDefinition], source: str) -> None:
    for p in definitions:
        if p.name in PRIMITIVE_REGISTRY:
            _REGISTRY_LOAD_ERRORS.append(
                f"Duplicate primitive registered: {p.name} from {source}"
            )
            continue
        PRIMITIVE_REGISTRY[p.name] = p
```

## 5.6 修改 `_populate_registry`

```python
def _populate_registry() -> None:
    PRIMITIVE_REGISTRY.clear()
    _REGISTRY_LOAD_ERRORS.clear()

    for module_path in PRIMITIVE_FAMILY_MODULES:
        try:
            definitions = _load_definitions_from_module(module_path)
            _register_all(definitions, source=module_path)
        except Exception as exc:
            _REGISTRY_LOAD_ERRORS.append(
                f"Failed to load primitive family {module_path}: "
                f"{type(exc).__name__}: {exc}"
            )
```

## 5.7 保持 fail-closed

```python
def _raise_if_registry_unhealthy() -> None:
    if _REGISTRY_LOAD_ERRORS:
        raise RuntimeError(
            "Primitive registry load errors: " + "; ".join(_REGISTRY_LOAD_ERRORS)
        )
```

`list_primitive_names()`、`get_primitive()`、`normalize_primitive_parameters()` 必须调用或间接触发 `_raise_if_registry_unhealthy()`。

## 5.8 新增 turbomachinery family 目录

新增：

```text
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/
  __init__.py
  models.py
```

`models.py` 暂时只写：

```python
from __future__ import annotations

from seekflow_engineering_tools.geometry_primitives.base import PrimitiveDefinition

TURBOMACHINERY_PRIMITIVES: list[PrimitiveDefinition] = []
```

## 5.9 禁止

```text
本次不导入 turbine_disk.models。
本次不导入 blade.models。
本次不注册 axisymmetric_turbine_disk。
本次不注册 parametric_turbine_blade。
不允许 except ImportError: pass。
```

---

# 六、P0 修复 3：Primitive Compiler 改成 handler registry

## 6.1 当前问题

当前 `primitive_compiler.py` 只认识 `involute_spur_gear`，并在 unknown primitive 时列出 “Available: involute_spur_gear”。这对后续涡轮盘 / 叶片扩展不够通用。([GitHub][3])

## 6.2 修改文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
```

## 6.3 新增类型和注册表

```python
from collections.abc import Callable
from typing import Any

PrimitiveCompileHandler = Callable[[Any], list[str]]

PRIMITIVE_COMPILERS: dict[str, PrimitiveCompileHandler] = {}
```

## 6.4 新增注册函数

```python
def register_primitive_compiler(
    primitive_name: str,
    handler: PrimitiveCompileHandler,
) -> None:
    if not isinstance(primitive_name, str) or not primitive_name.strip():
        raise ValueError("primitive compiler name must be a non-empty string")
    if primitive_name in PRIMITIVE_COMPILERS:
        raise ValueError(f"Primitive compiler already registered: {primitive_name}")
    PRIMITIVE_COMPILERS[primitive_name] = handler
```

## 6.5 新增列出函数

```python
def list_primitive_compiler_names() -> list[str]:
    return sorted(PRIMITIVE_COMPILERS.keys())
```

## 6.6 修改主 compile 函数

```python
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

## 6.7 保留 gear compiler

现有 `_compile_involute_spur_gear(feature)` 保持逻辑不变。

文件底部注册：

```python
register_primitive_compiler(
    "involute_spur_gear",
    _compile_involute_spur_gear,
)
```

## 6.8 禁止

```text
不要注册 axisymmetric_turbine_disk。
不要注册 parametric_turbine_blade。
不要改 gear 的 cq_gears / fallback 逻辑。
```

---

# 七、P0 修复 4：新增通用 primitive metadata v1 校验模块

## 7.1 当前问题

当前 builder 的 metadata sidecar 校验仍偏 gear，没有统一 primitive metadata schema。builder 已经会检查 metadata sidecar 存在、`primitive_metadata` 和 `build_warnings`，但 primitive-specific 校验主要围绕 `involute_spur_gear` 的字段。([GitHub][4])

## 7.2 新增文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/primitive_metadata.py
```

## 7.3 新增函数

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any


def _issue(code: str, message: str, severity: str = "error", **extra) -> dict:
    item = {"code": code, "message": message, "severity": severity}
    item.update(extra)
    return item


def validate_primitive_metadata_v1(
    *,
    primitive_name: str,
    metadata: dict | None,
) -> dict:
    issues: list[dict] = []

    if metadata is None:
        return {
            "ok": False,
            "issues": [
                _issue(
                    "primitive_metadata_missing",
                    f"Primitive metadata for '{primitive_name}' is missing.",
                )
            ],
            "normalized_metadata": None,
        }

    if not isinstance(metadata, dict):
        return {
            "ok": False,
            "issues": [
                _issue(
                    "primitive_metadata_not_dict",
                    f"Primitive metadata for '{primitive_name}' must be a dict.",
                )
            ],
            "normalized_metadata": None,
        }

    normalized = deepcopy(metadata)

    actual_primitive = normalized.get("primitive")
    if actual_primitive != primitive_name:
        issues.append(
            _issue(
                "primitive_metadata_name_mismatch",
                f"Primitive metadata name mismatch: expected '{primitive_name}', got {actual_primitive!r}.",
                expected=primitive_name,
                actual=actual_primitive,
            )
        )

    version = normalized.get("metadata_version")
    if version is not None and version != "primitive_metadata_v1":
        issues.append(
            _issue(
                "primitive_metadata_version_invalid",
                f"Primitive metadata version must be 'primitive_metadata_v1' when present, got {version!r}.",
                expected="primitive_metadata_v1",
                actual=version,
            )
        )

    kernel = normalized.get("kernel")
    if not isinstance(kernel, str) or not kernel.strip():
        issues.append(
            _issue(
                "primitive_metadata_missing_kernel",
                f"Primitive metadata for '{primitive_name}' missing non-empty string 'kernel'.",
            )
        )

    params = normalized.get("parameters")
    if not isinstance(params, dict):
        issues.append(
            _issue(
                "primitive_metadata_missing_parameters",
                f"Primitive metadata for '{primitive_name}' missing dict 'parameters'.",
            )
        )

    ref = normalized.get("reference_dimensions")
    if not isinstance(ref, dict):
        issues.append(
            _issue(
                "primitive_metadata_missing_reference_dimensions",
                f"Primitive metadata for '{primitive_name}' missing dict 'reference_dimensions'.",
            )
        )

    warnings = normalized.get("warnings", [])
    if warnings is None:
        warnings = []
    if not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings):
        issues.append(
            _issue(
                "primitive_metadata_warnings_invalid",
                f"Primitive metadata for '{primitive_name}' field 'warnings' must be list[str].",
            )
        )
    else:
        normalized["warnings"] = warnings

    return {
        "ok": len([i for i in issues if i.get("severity") == "error"]) == 0,
        "issues": issues,
        "normalized_metadata": normalized if not issues else normalized,
    }
```

## 7.4 通用 metadata 必须字段

每个 primitive metadata 至少必须有：

```json
{
  "primitive": "involute_spur_gear",
  "metadata_version": "primitive_metadata_v1",
  "kernel": "cq_gears",
  "parameters": {},
  "reference_dimensions": {},
  "warnings": []
}
```

`metadata_version` 可以暂时允许缺失，以兼容现有 gear metadata；但如果出现，必须等于 `primitive_metadata_v1`。

---

# 八、P0 修复 5：builder metadata sidecar 改成 generic + gear-specific

## 8.1 修改文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py
```

## 8.2 修改 `_assert_metadata_sidecar`

目标逻辑：

```text
1. metadata 文件必须存在且非空；
2. JSON 必须合法；
3. top-level 必须有 primitive_metadata；
4. top-level 必须有 build_warnings；
5. build_warnings 必须是 list；
6. 每个 PrimitiveFeature 必须在 primitive_metadata 中有 entry；
7. 每个 entry 必须通过 validate_primitive_metadata_v1；
8. gear 继续检查 is_standard_involute；
9. future primitive 暂时只要求 generic metadata；
10. 不能因为 unknown primitive 就跳过 metadata 检查。
```

## 8.3 推荐实现片段

```python
from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
    validate_primitive_metadata_v1,
)
```

新增 helper：

```python
def _assert_primitive_specific_metadata(
    primitive_name: str,
    primitive_meta: dict,
) -> None:
    if primitive_name == "involute_spur_gear":
        if "is_standard_involute" not in primitive_meta:
            raise ValueError("Gear metadata missing 'is_standard_involute'")
        return

    # Future primitive-specific checks should live here or be delegated:
    # axisymmetric_turbine_disk:
    #   is_axisymmetric_base
    #   radial_zones
    #   profile_points
    #   hole_patterns
    #
    # parametric_turbine_blade:
    #   airfoil_sections
    #   span_stations
    #   chord_distribution
    #   twist_distribution
    #
    # For now, unknown/future primitives must still pass generic metadata v1.
    return
```

修改 `_assert_metadata_sidecar` 的 primitive 循环：

```python
pm = metadata.get("primitive_metadata", {})
if not isinstance(pm, dict):
    raise ValueError("Metadata key 'primitive_metadata' must be a dict")

build_warnings = metadata.get("build_warnings")
if not isinstance(build_warnings, list):
    raise ValueError("Metadata key 'build_warnings' must be a list")

for feat in spec.features:
    if getattr(feat, "type", None) != "primitive":
        continue

    primitive_name = feat.primitive_name
    primitive_meta = pm.get(primitive_name)

    if primitive_meta is None:
        raise ValueError(f"Metadata missing primitive entry for '{primitive_name}'")

    generic_result = validate_primitive_metadata_v1(
        primitive_name=primitive_name,
        metadata=primitive_meta,
    )

    if generic_result.get("ok") is not True:
        messages = [
            issue.get("message", issue.get("code", "unknown metadata issue"))
            for issue in generic_result.get("issues", [])
            if issue.get("severity") == "error"
        ]
        raise ValueError(
            f"Primitive metadata validation failed for '{primitive_name}': "
            + "; ".join(messages)
        )

    _assert_primitive_specific_metadata(
        primitive_name,
        generic_result["normalized_metadata"],
    )
```

## 8.4 注意兼容

如果现有 gear metadata 没有 `"primitive": "involute_spur_gear"`，这次会导致旧测试失败。建议同步修改 gear adapter / fallback metadata，让它们输出：

```json
{
  "primitive": "involute_spur_gear",
  "metadata_version": "primitive_metadata_v1",
  "kernel": "cq_gears",
  "parameters": {},
  "reference_dimensions": {},
  "is_standard_involute": true,
  "warnings": []
}
```

需要检查：

```text
geometry_primitives/gears/cq_gears_adapter.py
geometry_primitives/gears/cadquery_fallback.py
geometry_primitives/gears/metadata.py
```

不要为了兼容旧 metadata 放松通用 metadata 规则。

---

# 九、P0 修复 6：mechanical validation 改成 handler registry

## 9.1 当前问题

当前 `validate_mechanical_primitives()` 只处理 `involute_spur_gear`。如果未来 feature 是 `axisymmetric_turbine_disk`，当前函数不会 append result，`overall_ok` 仍可能保持 True，返回空 results。这对复杂 primitive 是严重 fail-open 风险。([GitHub][5])

## 9.2 修改文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/common.py
```

## 9.3 新增注册表

```python
from collections.abc import Callable
from typing import Any

PrimitiveMechanicalValidator = Callable[..., dict]

PRIMITIVE_MECHANICAL_VALIDATORS: dict[str, PrimitiveMechanicalValidator] = {}
```

## 9.4 新增注册函数

```python
def register_primitive_mechanical_validator(
    primitive_name: str,
    handler: PrimitiveMechanicalValidator,
) -> None:
    if not isinstance(primitive_name, str) or not primitive_name.strip():
        raise ValueError("primitive mechanical validator name must be non-empty")
    if primitive_name in PRIMITIVE_MECHANICAL_VALIDATORS:
        raise ValueError(
            f"Primitive mechanical validator already registered: {primitive_name}"
        )
    PRIMITIVE_MECHANICAL_VALIDATORS[primitive_name] = handler
```

## 9.5 新增 list 函数

```python
def list_primitive_mechanical_validator_names() -> list[str]:
    return sorted(PRIMITIVE_MECHANICAL_VALIDATORS.keys())
```

## 9.6 新增 expected helper

```python
def _expected_for_feature(spec, feature) -> dict:
    validation = getattr(spec, "validation", None)
    if validation is None:
        return {}

    pv = getattr(validation, "primitive_validation", {}) or {}
    expected = pv.get(feature.id, {})

    if expected is None:
        return {}

    if not isinstance(expected, dict):
        return {}

    return expected
```

## 9.7 新增 gear adapter handler

```python
def _validate_involute_spur_gear_feature(
    *,
    feature,
    spec,
    step_path: Path,
    inspection: dict,
    raw_metadata: dict | None,
    metadata: dict | None,
    expected: dict,
) -> dict:
    from seekflow_engineering_tools.mechanical_validation.gear_validation import (
        validate_involute_spur_gear_result,
    )

    legacy_expected = {
        "expected_kernel": getattr(spec.validation, "expected_kernel", None),
        "expected_tooth_count": getattr(spec.validation, "expected_tooth_count", None),
        "expected_bore_diameter_mm": getattr(spec.validation, "expected_bore_diameter_mm", None),
        "expected_face_width_mm": getattr(spec.validation, "expected_face_width_mm", None),
        "expected_pitch_diameter_mm": getattr(spec.validation, "expected_pitch_diameter_mm", None),
        "expected_base_diameter_mm": getattr(spec.validation, "expected_base_diameter_mm", None),
        "expected_outer_diameter_mm": getattr(spec.validation, "expected_outer_diameter_mm", None),
        "expected_root_diameter_mm": getattr(spec.validation, "expected_root_diameter_mm", None),
        "expected_body_count": getattr(spec.validation, "expected_body_count", None),
    }

    merged_expected = {
        **{k: v for k, v in legacy_expected.items() if v is not None},
        **(expected or {}),
    }

    return validate_involute_spur_gear_result(
        params=feature.parameters,
        inspection=inspection,
        metadata=metadata,
        tolerance_mm=spec.validation.tolerance_mm,
        expected=merged_expected,
        raw_metadata=raw_metadata,
    )
```

文件底部注册：

```python
register_primitive_mechanical_validator(
    "involute_spur_gear",
    _validate_involute_spur_gear_feature,
)
```

## 9.8 重写 `validate_mechanical_primitives`

```python
def validate_mechanical_primitives(spec, step_path: Path, inspection: dict) -> dict:
    results: list[dict] = []
    overall_ok = True

    metadata_path = Path(str(step_path)).with_suffix(".metadata.json")
    raw_metadata = load_metadata(metadata_path)

    primitive_features = [
        f for f in spec.features if getattr(f, "type", None) == "primitive"
    ]

    if not primitive_features:
        return {"ok": True, "results": []}

    for feature in primitive_features:
        name = feature.primitive_name
        handler = PRIMITIVE_MECHANICAL_VALIDATORS.get(name)

        if handler is None:
            result = {
                "ok": False,
                "primitive": name,
                "issues": [
                    {
                        "code": "primitive_mechanical_validator_missing",
                        "message": (
                            f"No mechanical validator registered for primitive '{name}'. "
                            "Primitive builds must fail closed until a deterministic validator exists."
                        ),
                        "severity": "error",
                    }
                ],
            }
        else:
            metadata = _unwrap_primitive_metadata(raw_metadata, name)
            expected = _expected_for_feature(spec, feature)

            try:
                result = handler(
                    feature=feature,
                    spec=spec,
                    step_path=step_path,
                    inspection=inspection,
                    raw_metadata=raw_metadata,
                    metadata=metadata,
                    expected=expected,
                )
            except Exception as exc:
                result = {
                    "ok": False,
                    "primitive": name,
                    "issues": [
                        {
                            "code": "primitive_mechanical_validator_exception",
                            "message": (
                                f"Mechanical validator for primitive '{name}' raised "
                                f"{type(exc).__name__}: {exc}"
                            ),
                            "severity": "error",
                        }
                    ],
                }

        results.append(result)

        if result.get("ok") is not True:
            overall_ok = False

    return {"ok": overall_ok, "results": results}
```

## 9.9 禁止

```text
unknown primitive 不能 ok=True。
validator exception 不能抛出到 builder 外层造成不清晰错误；应该返回 structured validation failure。
result 缺 ok 时必须视为 fail。
```

---

# 十、P1 修复 7：新增 generic primitive demo runner

## 10.1 当前状态

`demo_full_chain.py` 已有 `_finalize_case_report()`，这是好的；但当前 demo 仍以 recipe runner 和 gear runner 为主，没有通用 primitive runner。([GitHub][6])

## 10.2 修改文件

```text
integrations/engineering_tools/demo_full_chain.py
```

## 10.3 新增常量

```python
PRIMITIVE_REQUIRED_STAGES = [
    "validate_cad_ir",
    "normalize_primitives",
    "choose_backend",
    "build",
    "inspect",
    "mechanical_validate",
    "metadata",
]
```

## 10.4 新增 helper

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
    allow_step_import: bool = False,
    required_metrics: list[str] | None = None,
) -> dict:
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

    required_metrics = required_metrics or [
        "kernel_used",
        "reference_dimensions",
    ]

    report = _make_report_skeleton(case_name, backend)
    config = EngineeringToolsConfig(workspace_root=output_root, allow_overwrite=True)
    validate_fn, build_fn = _get_unified_tools(config)

    spec_dict = {
        "nlcad_version": "0.1",
        "name": case_name,
        "units": "mm",
        "target_backend": [backend],
        "features": [
            {
                "id": feature_id,
                "type": "primitive",
                "primitive_name": primitive_name,
                "operation": "new_body",
                "placement": {
                    "origin_mm": [0.0, 0.0, 0.0],
                    "axis": "Z",
                },
                "parameters": params,
            }
        ],
        "validation": validation,
        "outputs": {
            "native": backend in ("solidworks2025", "nx12"),
            "step": True,
            "stl": False,
            "preview_png": False,
        },
    }

    val_result = validate_fn(spec_dict)
    _stage(
        report,
        "validate_cad_ir",
        ok=val_result.get("ok") is True,
        error=val_result.get("error"),
    )

    normalized = val_result.get("metrics", {}).get("normalized_parameters", {})
    _stage(
        report,
        "normalize_primitives",
        ok=val_result.get("ok") is True and bool(normalized),
        normalized_parameters=normalized,
        error=None if normalized else "Missing normalized primitive parameters.",
    )

    strategy = get_primitive_strategy(backend, primitive_name)
    _stage(
        report,
        "choose_backend",
        ok=strategy is not None,
        backend=backend,
        primitive_strategy=strategy,
        error=None if strategy else f"No primitive strategy for {primitive_name} on {backend}.",
    )

    if val_result.get("ok") is not True or strategy is None:
        return _finalize_case_report(
            report,
            required_stages=PRIMITIVE_REQUIRED_STAGES,
            required_metrics=required_metrics,
        )

    step_path = output_root / "models" / step_filename
    step_path.parent.mkdir(parents=True, exist_ok=True)

    build_result = build_fn(
        spec_dict,
        backend=backend,
        out_step=str(step_path),
        inspect=True,
        allow_backend_fallback=False,
        allow_step_import=allow_step_import,
    )

    _stage(
        report,
        "build",
        ok=build_result.get("ok") is True,
        error=build_result.get("error"),
        message=build_result.get("message"),
    )

    report["files_created"] = build_result.get("files_created", []) or []
    report["warnings"].extend(build_result.get("warnings", []) or [])

    metrics = build_result.get("metrics", {}) or {}

    validation_metrics = metrics.get("validation") or metrics.get("inspection_validation")
    _stage(
        report,
        "inspect",
        ok=isinstance(validation_metrics, dict) and validation_metrics.get("ok") is True,
        error=None if isinstance(validation_metrics, dict) else "Inspection validation missing.",
        validation=validation_metrics,
    )

    mv = metrics.get("mechanical_validation")
    _stage(
        report,
        "mechanical_validate",
        ok=isinstance(mv, dict) and mv.get("ok") is True,
        error=None if isinstance(mv, dict) else "Mechanical validation missing.",
        mechanical_validation=mv,
    )

    meta_path = step_path.with_suffix(".metadata.json")
    if not meta_path.exists() or meta_path.stat().st_size < 1:
        _stage(report, "metadata", ok=False, error="Metadata sidecar missing or empty.")
    else:
        try:
            sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
            pm = sidecar.get("primitive_metadata", {}).get(primitive_name)
            if not isinstance(pm, dict):
                _stage(
                    report,
                    "metadata",
                    ok=False,
                    error=f"primitive_metadata.{primitive_name} missing.",
                )
            else:
                _stage(report, "metadata", ok=True, path=str(meta_path))
                report["metrics"]["kernel_used"] = pm.get("kernel", "unknown")
                report["metrics"]["reference_dimensions"] = pm.get("reference_dimensions", {})
                report["metrics"]["primitive_metadata"] = pm
        except (json.JSONDecodeError, OSError) as exc:
            _stage(report, "metadata", ok=False, error=f"Failed to read metadata: {exc}")

    report["metrics"]["strategy"] = strategy

    return _finalize_case_report(
        report,
        required_stages=PRIMITIVE_REQUIRED_STAGES,
        required_metrics=required_metrics,
    )
```

## 10.5 注意

本次可以先不把 gear demo 改用 generic runner，以降低风险。只要新增 generic runner 和对应 mock tests 即可。

---

# 十一、P1 修复 8：新增 turbomachinery skill contract

## 11.1 新增文件

```text
integrations/engineering_tools/.claude/skills/turbomachinery-cad-ir/SKILL.md
```

如果 `.claude/skills` 在仓库根目录而不是 `integrations/engineering_tools` 下，则按项目已有结构放置。用户原审核说明中曾把 `.claude/skills/` 列为重点目录。

## 11.2 固定内容

```markdown
# Turbomachinery CAD-IR Skill

This skill converts natural-language turbomachinery modeling requests into SeekFlow Engineering CAD-IR.

It must output CAD-IR only.

It must not generate:
- CadQuery code
- SolidWorks COM / VBS
- NXOpen journal code
- ANSYS APDL
- arbitrary backend scripts

## Safety boundary

Aero-engine turbine disks and turbine blades are safety-critical rotating parts.

This skill must not claim that generated geometry is:
- flight-ready
- airworthy
- certified
- manufacturing-ready
- burst-safe
- fatigue-safe
- life-approved

All outputs are reference geometry unless separately verified by deterministic validation, FEA, material review, manufacturing review, life analysis, and certification workflow.

## Reserved primitive names

Reserved future primitive names:

- axisymmetric_turbine_disk
- parametric_turbine_blade

The skill must not emit either primitive name unless all are true:

1. The primitive is registered in Primitive Registry.
2. The requested backend supports it in Capability Registry.
3. A CadQuery compiler handler exists.
4. A mechanical validator exists.
5. The required parameters are present.

## Missing parameters

The skill must not invent required parameters.

If a required parameter is missing, return a missing-parameter diagnostic instead of CAD-IR.

## Output contract

When a primitive is supported, output a CADPartSpec-compatible JSON object:

- nlcad_version = "0.1"
- units = "mm"
- features[].type = "primitive"
- features[].primitive_name = registered primitive name
- features[].parameters contains only allowed primitive parameters
- validation.primitive_validation[feature_id] contains primitive-specific expected fields

## Forbidden behavior

Do not:
- write geometry code
- invent unsupported primitive names
- infer safety-critical dimensions
- mark non-flight reference geometry as certified
- bypass engineering_validate_cad_ir
- bypass engineering_build_cad_model
```

---

# 十二、P1 修复 9：future primitive support contract

## 12.1 新增测试

```text
tests/test_future_primitive_support_contract.py
```

## 12.2 目的

防止未来有人把：

```text
axisymmetric_turbine_disk
parametric_turbine_blade
```

加入 `stable_primitives`，但没有 registry / compiler / validator，造成假支持。

## 12.3 测试代码

```python
RESERVED_FUTURE_PRIMITIVES = {
    "axisymmetric_turbine_disk",
    "parametric_turbine_blade",
}


def test_reserved_future_primitives_not_stable_without_full_implementation():
    from seekflow_engineering_tools.capabilities.registry import CAPABILITIES
    from seekflow_engineering_tools.geometry_primitives.registry import list_primitive_names
    from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
        list_primitive_compiler_names,
    )
    from seekflow_engineering_tools.mechanical_validation.common import (
        list_primitive_mechanical_validator_names,
    )

    registered = set(list_primitive_names())
    compiled = set(list_primitive_compiler_names())
    validated = set(list_primitive_mechanical_validator_names())

    for backend, cap in CAPABILITIES.items():
        stable = set(cap.get("stable_primitives", []))
        for primitive_name in RESERVED_FUTURE_PRIMITIVES:
            if primitive_name in stable:
                assert primitive_name in registered
                assert primitive_name in compiled
                assert primitive_name in validated
```

---

# 十三、必须新增 / 修改的测试清单

## 13.1 `tests/test_primitive_validation_schema.py`

覆盖：

```text
primitive_validation 接受 dict
primitive_validation 默认为 {}
primitive_validation key 为空时报错
primitive_validation value 非 dict 时报错
gear legacy expected_* 字段仍可用
```

## 13.2 `tests/test_primitive_family_registry.py`

覆盖：

```text
registry 能加载 gear family
turbomachinery family 存在且可为空
family import error fail-closed
family export 非 list fail-closed
family export 非 PrimitiveDefinition fail-closed
duplicate primitive name fail-closed
没有 except ImportError: pass
```

## 13.3 `tests/test_primitive_compiler_registry.py`

覆盖：

```text
involute_spur_gear compiler 已注册
unknown primitive compiler fail
错误信息列出 available compilers
重复注册 compiler fail
临时注册 fake primitive compiler 可编译
```

## 13.4 `tests/test_primitive_metadata_v1.py`

覆盖：

```text
valid metadata pass
metadata missing fail
metadata 非 dict fail
primitive mismatch fail
kernel missing fail
kernel 空字符串 fail
parameters missing fail
parameters 非 dict fail
reference_dimensions missing fail
reference_dimensions 非 dict fail
warnings 缺失时 normalize 为 []
warnings 非 list fail
metadata_version 非 primitive_metadata_v1 fail
```

## 13.5 `tests/test_primitive_metadata_sidecar_generic.py`

覆盖：

```text
metadata sidecar 文件缺失 fail
metadata JSON invalid fail
top-level primitive_metadata missing fail
top-level build_warnings missing fail
build_warnings 非 list fail
每个 PrimitiveFeature 必须有 metadata entry
metadata entry 必须过 generic v1
gear 仍要求 is_standard_involute
future fake primitive 有 generic metadata 时可过 sidecar 检查
```

## 13.6 `tests/test_primitive_mechanical_validation_dispatch.py`

覆盖：

```text
gear validator registered
unknown primitive validator missing fail-closed
validator exception 被转为 structured failure
result 缺 ok 时 overall fail
primitive_validation[feature.id] 被传给 handler
gear handler 合并 legacy expected_* 和 primitive_validation expected
```

## 13.7 `tests/test_demo_full_chain_generic_primitive.py`

覆盖：

```text
generic primitive runner 存在
metadata missing => overall_ok False
mechanical_validation missing => overall_ok False
inspection validation missing => overall_ok False
required metric missing => overall_ok False
valid mocked primitive build => overall_ok True
runner 使用 engineering_validate_cad_ir
runner 使用 engineering_build_cad_model
```

## 13.8 `tests/test_turbomachinery_skill_contract.py`

覆盖：

```text
SKILL.md 存在
禁止 CadQuery / SolidWorks COM / NXOpen / APDL 代码生成
声明 reference geometry only
禁止 flight-ready / airworthy / certified / manufacturing-ready 等声称
声明 reserved primitive names
要求 primitive 注册和 backend 支持后才可输出
要求缺参返回 diagnostic
```

## 13.9 `tests/test_future_primitive_support_contract.py`

覆盖：

```text
axisymmetric_turbine_disk 如果进入 stable_primitives，必须：
  registered
  compiler exists
  mechanical validator exists

parametric_turbine_blade 同理
```

---

# 十四、Claude Code 总 Prompt

下面这段可以直接复制给 Claude Code。

```text
你要在 WYZAAACCC/seekflow-engineering 的 integrations/engineering_tools 子项目中补强通用 primitive 基础设施，为后续航空发动机涡轮盘和涡轮叶片 primitive 构建提供支撑。

重要：本次任务不实现涡轮盘专有几何，不实现叶片专有几何，不实现 fir-tree slot，不实现气动叶型，不实现复杂冷却孔，不实现强度/寿命/适航判断。你只做通用基础设施，让未来新增 axisymmetric_turbine_disk、parametric_turbine_blade 等 primitive 时无需再改主链路。

必须保持当前架构：

CAD-IR
→ engineering_validate_cad_ir
→ Primitive Registry / Capability Registry
→ engineering_build_cad_model
→ CadQuery deterministic primitive compiler
→ STEP + metadata
→ inspection
→ mechanical_validation
→ optional SolidWorks/NX canonical STEP import

禁止新增 build_turbine_disk_model 或 build_blade_model 独立工具。
禁止绕过 engineering_validate_cad_ir / engineering_build_cad_model。
禁止让 SolidWorks / NX 重新生成复杂 primitive，未来仍只允许 canonical STEP import。

请完成以下任务：

1. 修改 src/seekflow_engineering_tools/ir/cad.py

在 ValidationSpec 中新增：
primitive_validation: dict[str, dict[str, Any]] = Field(default_factory=dict)

新增 validator：
- primitive_validation 必须是 dict
- key 必须是非空 feature id
- value 必须是 dict

不要把涡轮盘 / 叶片专用 expected 字段加到 ValidationSpec 顶层。
保留现有 gear expected_* 字段兼容性。

2. 修改 src/seekflow_engineering_tools/geometry_primitives/registry.py

把当前只加载 GEAR_PRIMITIVES 的逻辑改成多 primitive family loader。

新增：
PRIMITIVE_FAMILY_MODULES = [
  "seekflow_engineering_tools.geometry_primitives.gears.models:GEAR_PRIMITIVES",
  "seekflow_engineering_tools.geometry_primitives.turbomachinery.models:TURBOMACHINERY_PRIMITIVES",
]

实现 _load_definitions_from_module(path)：
- path 格式为 module:attribute
- import module
- 获取 attribute
- 必须是 list[PrimitiveDefinition]
- 非法则 raise

实现 _register_all(definitions, source)。

_populate_registry 遍历 PRIMITIVE_FAMILY_MODULES。
任何 family import/type/schema 错误都记录到 _REGISTRY_LOAD_ERRORS。
list_primitive_names/get_primitive/normalize_primitive_parameters 在 registry unhealthy 时必须 fail-closed raise RuntimeError。
禁止 except ImportError: pass。

3. 新增目录 src/seekflow_engineering_tools/geometry_primitives/turbomachinery/

新增：
__init__.py
models.py

models.py 内容：
from __future__ import annotations
from seekflow_engineering_tools.geometry_primitives.base import PrimitiveDefinition
TURBOMACHINERY_PRIMITIVES: list[PrimitiveDefinition] = []

本次不要注册 axisymmetric_turbine_disk 或 parametric_turbine_blade。

4. 修改 src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py

把当前 hardcoded if name == "involute_spur_gear" 改为 handler registry。

新增：
PrimitiveCompileHandler
PRIMITIVE_COMPILERS
register_primitive_compiler
list_primitive_compiler_names

compile_primitive_to_cadquery_script(feature) 从 PRIMITIVE_COMPILERS 里查 handler。
未注册 primitive 必须 raise PrimitiveCompileError，并列出 available primitive compilers。

保留 _compile_involute_spur_gear 原逻辑。
文件底部注册：
register_primitive_compiler("involute_spur_gear", _compile_involute_spur_gear)

不要注册未实现的涡轮盘/叶片 compiler。

5. 新增 src/seekflow_engineering_tools/mechanical_validation/primitive_metadata.py

实现：
validate_primitive_metadata_v1(
    *,
    primitive_name: str,
    metadata: dict | None,
) -> dict

必须检查：
- metadata exists
- metadata is dict
- metadata["primitive"] == primitive_name
- metadata_version 如果存在，必须是 "primitive_metadata_v1"
- kernel exists and is non-empty str
- parameters exists and is dict
- reference_dimensions exists and is dict
- warnings if present must be list[str]
- warnings missing 时 normalize 为 []

返回：
{
  "ok": bool,
  "issues": list[dict],
  "normalized_metadata": dict | None
}

issue 必须包含 code/message/severity。

6. 修改 gear metadata 输出

检查并修改：
src/seekflow_engineering_tools/geometry_primitives/gears/cq_gears_adapter.py
src/seekflow_engineering_tools/geometry_primitives/gears/cadquery_fallback.py
src/seekflow_engineering_tools/geometry_primitives/gears/metadata.py

确保 gear primitive metadata 至少包含：
primitive = "involute_spur_gear"
metadata_version = "primitive_metadata_v1"
kernel
parameters
reference_dimensions
warnings
is_standard_involute

不要放松 metadata v1 规则来兼容旧字段；应该修正 metadata 生成端。

7. 修改 src/seekflow_engineering_tools/cadquery_backend/builder.py

重构 _assert_metadata_sidecar：
- metadata file 必须存在且非空
- JSON 必须合法
- top-level primitive_metadata 必须存在且是 dict
- top-level build_warnings 必须存在且是 list
- 对 spec.features 中每个 primitive feature：
  - primitive_metadata[feature.primitive_name] 必须存在
  - 调 validate_primitive_metadata_v1
  - generic metadata 不通过必须 raise ValueError
  - 调 _assert_primitive_specific_metadata
- _assert_primitive_specific_metadata 对 involute_spur_gear 继续要求 is_standard_involute
- 未实现的 future primitive 暂时只需要通过 generic metadata v1
- metadata 缺失 / primitive entry 缺失 / kernel 缺失 / parameters 缺失 / reference_dimensions 缺失都必须 fail

8. 修改 src/seekflow_engineering_tools/mechanical_validation/common.py

把 validate_mechanical_primitives 改成 handler registry。

新增：
PrimitiveMechanicalValidator
PRIMITIVE_MECHANICAL_VALIDATORS
register_primitive_mechanical_validator
list_primitive_mechanical_validator_names
_expected_for_feature

没有 registered mechanical validator 的 primitive 必须 fail-closed：
{
  "ok": False,
  "primitive": name,
  "issues": [
    {
      "code": "primitive_mechanical_validator_missing",
      "message": "...",
      "severity": "error"
    }
  ]
}

为 involute_spur_gear 注册 adapter handler：
register_primitive_mechanical_validator(
  "involute_spur_gear",
  _validate_involute_spur_gear_feature
)

gear adapter handler 内部继续调用 validate_involute_spur_gear_result。
它必须合并：
- spec.validation 顶层 gear expected_* 字段
- spec.validation.primitive_validation[feature.id]

validator 抛异常时必须转为 structured failure。
result.get("ok") is not True 时 overall_ok=False。
不要注册未实现的 turbine_disk/blade validator。

9. 修改 demo_full_chain.py

新增通用 _run_primitive_case(...) helper。

它必须：
- 走 engineering_validate_cad_ir
- 走 engineering_build_cad_model
- 构造 primitive CAD-IR
- 包含 stages：
  validate_cad_ir
  normalize_primitives
  choose_backend
  build
  inspect
  mechanical_validate
  metadata
- metadata stage 必须按 primitive_name 从 sidecar 中读取
- required metric 缺失必须 fail
- 不能用 build_result.get("ok") 单独决定 overall_ok
- 可以暂时不新增 turbine_disk/blade demo case
- 保持现有 gear demo 通过

10. 新增 .claude/skills/turbomachinery-cad-ir/SKILL.md

内容必须说明：
- skill 只输出 CAD-IR
- 禁止生成 CadQuery/SolidWorks COM/NXOpen/APDL 代码
- 涡轮盘和叶片是 safety-critical rotating parts
- 输出只是 reference geometry，不能声明 flight-ready/airworthy/certified/manufacturing-ready/burst-safe/fatigue-safe/life-approved
- reserved primitive names:
  axisymmetric_turbine_disk
  parametric_turbine_blade
- 只有 primitive 已注册、backend 支持、compiler 存在、mechanical validator 存在、必填参数齐全时，skill 才能输出这些 primitive name
- 必填参数缺失时必须返回 missing-parameter diagnostic，不能猜参数

11. 新增测试

必须新增以下测试文件：

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

primitive_validation：
- accepts dict
- default {}
- rejects empty feature id
- rejects non-dict value
- existing gear expected fields still work

registry：
- loads gear family
- loads empty turbomachinery family
- family import error fail-closed
- non-list export fail-closed
- non-PrimitiveDefinition item fail-closed
- duplicate primitive fail-closed
- no "except ImportError: pass"

compiler registry：
- involute_spur_gear compiler registered
- unknown primitive compiler fails
- duplicate registration fails
- temporary fake compiler can be registered and called

primitive metadata v1：
- valid pass
- missing metadata fail
- non-dict metadata fail
- primitive mismatch fail
- missing/empty kernel fail
- missing/non-dict parameters fail
- missing/non-dict reference_dimensions fail
- warnings missing normalized to []
- bad warnings type fail
- bad metadata_version fail

builder sidecar：
- missing file fail
- invalid JSON fail
- primitive_metadata missing fail
- build_warnings missing fail
- build_warnings non-list fail
- missing primitive entry fail
- generic metadata keys required
- gear still requires is_standard_involute
- future fake primitive with valid generic metadata passes sidecar check

mechanical validation:
- gear validator registered
- missing validator fails closed
- validator exception becomes structured failure
- result missing ok fails overall
- primitive_validation[feature.id] passed to handler
- gear handler merges legacy expected and primitive_validation expected

demo generic primitive:
- metadata missing => overall_ok false
- mechanical_validation missing => overall_ok false
- inspection missing => overall_ok false
- required metric missing => overall_ok false
- valid mocked primitive build => overall_ok true
- runner uses engineering_validate_cad_ir and engineering_build_cad_model

skill contract:
- forbids direct CAD code generation
- mentions reference geometry only
- forbids unsafe claims
- requires registered primitive before emitting reserved names
- requires missing-parameter diagnostic

future primitive support:
- if axisymmetric_turbine_disk or parametric_turbine_blade appears in any backend stable_primitives, assert it is registered, compiled, and mechanically validated

12. 运行：

cd integrations/engineering_tools
python -m compileall src demo_full_chain.py
python -m pytest

13. 成功标准：

- compileall 通过
- pytest 通过
- 现有 gear demo 不被破坏
- involute_spur_gear 仍可 build/validate
- 未实现的 axisymmetric_turbine_disk / parametric_turbine_blade 不得进入 stable_primitives
- 未注册 compiler 的 primitive build 必须 fail
- 未注册 mechanical validator 的 primitive mechanical_validation 必须 fail
- metadata 缺失不得 ok=True
- mechanical_validation 缺失不得 ok=True
- 未来新增涡轮盘/叶片时，只需新增 family definition、kernel、compiler handler、metadata、validator、tests，不需要再改主链路
```

---

# 十五、Claude Code 完成后必须输出的报告模板

要求 Claude Code 最后输出：

```text
## 通用 Primitive 基础设施补充完成报告

### 1. 修改文件
- path/to/file.py
  - 修改内容：
  - 关闭的风险：
  - 对应测试：

### 2. 新增文件
- path/to/new_file.py
  - 用途：
  - 对应测试：

### 3. 架构约束确认
- 是否仍走 engineering_validate_cad_ir：
- 是否仍走 engineering_build_cad_model：
- 是否没有新增 turbine/blade 独立 build tool：
- 是否没有注册未实现的 turbine/blade primitive：
- 是否 SolidWorks/NX 仍只允许 canonical STEP import：

### 4. 测试结果
- python -m compileall src demo_full_chain.py：
- python -m pytest：

### 5. 未实现但已预留
- axisymmetric_turbine_disk：
- parametric_turbine_blade：
- turbine disk deterministic kernel：
- turbine blade deterministic kernel：

### 6. 仍需人工后续实现
- 涡轮盘参数表：
- 涡轮盘 validator：
- 涡轮盘 CadQuery kernel：
- 涡轮盘 mechanical validation：
- 叶片参数表：
- 叶片 airfoil section kernel：
- 叶片 mechanical validation：
```

---

# 十六、最终验收判断

Claude Code 完成这份补充后，项目才可以说：

```text
当前架构已经足够支撑涡轮盘 / 叶片 primitive 的构建工作。
```

但注意，这里的“支撑”指的是基础架构支撑，不是已经能生成涡轮盘 / 叶片。完成后应达到：

```text
可以安全新增 axisymmetric_turbine_disk；
可以安全新增 parametric_turbine_blade；
不会污染主链路；
不会复制 gear-only 逻辑；
不会让未验证 primitive 假成功；
不会让 metadata / mechanical_validation 缺失还 ok=True。
```

我的建议是分两步走：

```text
第一步：让 Claude Code 完成本方案，补通用 primitive infrastructure。
第二步：再让 Claude Code 实现 axisymmetric_turbine_disk v0.1。
第三步：等涡轮盘跑通后，再实现 parametric_turbine_blade v0.1。
```

这样最稳，也最符合你当前的目标：**保持架构通用，不为涡轮盘/叶片硬写孤立系统。**

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/ir/cad.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/common.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/demo_full_chain.py "raw.githubusercontent.com"
