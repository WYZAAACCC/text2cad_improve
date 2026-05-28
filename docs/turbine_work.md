

# SeekFlow Engineering：`axisymmetric_turbine_disk v0.1` 高质量落地实施文档

## 1. 实施目标

本次任务的目标不是“画一个像涡轮盘的 STEP”，而是将仓库从当前的“齿轮 primitive 已跑通、turbomachinery 仅保留 reserved name”的状态，升级为：

```text
CAD-IR primitive feature
→ primitive registry
→ parameter normalization
→ primitive-specific validator
→ capability registry
→ backend strategy
→ CadQuery compiler handler
→ deterministic turbine disk kernel
→ STEP
→ primitive metadata sidecar
→ generic metadata validation
→ turbine-specific metadata validation
→ mechanical validation
→ demo_full_chain case
→ tests
```

最终要新增并跑通：

```text
primitive_name = "axisymmetric_turbine_disk"
kernel = "cadquery_axisymmetric_revolve_v0"
quality scope = non-flight reference geometry only
```

当前 CAD-IR 已经支持 `PrimitiveFeature`，`ValidationSpec` 也已经支持 `primitive_validation`，因此无需重写 CAD-IR 大架构；应沿着现有 `PrimitiveFeature`、`PrimitiveDefinition`、`primitive_compiler`、`mechanical_validation.common` 的扩展点实现。([GitHub][2]) ([GitHub][3])

---

## 2. 当前代码真实状态

### 2.1 已经具备的基础

当前 `PrimitiveDefinition` / `PrimitiveParameter` 已经能描述 primitive 名称、分类、参数、backend、kernel、validation defaults，适合直接承载涡轮盘 primitive 参数表。([GitHub][4])

`geometry_primitives.registry` 已经采用 family module loader，当前加载：

```text
seekflow_engineering_tools.geometry_primitives.gears.models:GEAR_PRIMITIVES
seekflow_engineering_tools.geometry_primitives.turbomachinery.models:TURBOMACHINERY_PRIMITIVES
```

这说明新增涡轮盘时不应改成单文件大 registry，而应在 `geometry_primitives/turbomachinery/models.py` 中注册。([GitHub][5])

`primitive_compiler.py` 已经是 handler registry：未知 primitive 会抛 `PrimitiveCompileError`，目前只注册了 `involute_spur_gear`。这正好适合新增 `axisymmetric_turbine_disk` handler。([GitHub][6])

`builder.py` 对 primitive build 已经强制要求 metadata sidecar，并且会先跑 generic metadata validation，再跑 primitive-specific metadata check，再跑 mechanical validation；mechanical validation 失败会让 build 失败。这个闭环要复用，不要绕开。([GitHub][7])

`mechanical_validation.common` 已经有 `PRIMITIVE_MECHANICAL_VALIDATORS` 注册表，未注册 primitive validator 会返回 `primitive_mechanical_validator_missing` 并使 overall 失败。这是正确的 fail-closed 机制。([GitHub][8])

`natural_language.tools` 在 validate 与 build 阶段都会重新 normalize recipe/primitive 参数，所以涡轮盘的参数合法性应放进 `normalize_primitive_parameters()` 的 primitive-specific validator 分支，而不是只在 demo 里检查。([GitHub][9])

SolidWorks / NX primitive 当前走 canonical STEP import 路线：先由 CadQuery 生成 canonical STEP + metadata，再由 SolidWorks / NX import STEP，并且在导入前检查 CadQuery build、metadata、inspection validation、mechanical validation 是否通过。涡轮盘也必须沿用这个策略。([GitHub][10])

### 2.2 当前明确缺口

`turbomachinery/models.py` 目前只保留 reserved primitive names，`TURBOMACHINERY_PRIMITIVES` 是空列表。也就是说，`axisymmetric_turbine_disk` 尚未注册、未实现。([GitHub][11])

`capabilities.registry` 当前 `cadquery`、`solidworks2025`、`nx12` 的 `stable_primitives` 都只有 `involute_spur_gear`，没有涡轮盘。这是当前正确状态；只有完成 kernel、compiler、metadata、mechanical validator 和 tests 后，才能把 `axisymmetric_turbine_disk` 加进去。([GitHub][12])

`validate_primitive_metadata_v1()` 的 docstring 声明 `warnings if present must be list[str]`，但实际代码中，`warnings` 不是 list 时只给 severity=`warning`，最终 `ok` 仍可能为 True。涡轮盘这种安全敏感 reference geometry 不应允许 malformed metadata 通过。([GitHub][13])

`normalize_primitive_parameters()` 当前对 bool 使用 `bool(value)`，这会导致 `"False"` 被解析成 `True`，而涡轮盘会引入 `non_flight_reference_only`，必须先修。([GitHub][5])

`demo_full_chain.py` 当前没有真正的 generic `_run_primitive_case()`，只有齿轮 case。齿轮 case 中 strategy 缺失时会 fallback 到 `"native_cadquery_primitive"`，且 reference dimensions 只保留齿轮字段。涡轮盘实现前必须重构这块，否则 demo 会给出假阳性。([GitHub][1]) ([GitHub][1])

---

## 3. 不可违背的工程边界

本项目记忆文档已经明确：primitive 是“工程语义化的、确定性参数化 CAD 几何单元”，不是简单 CAD feature，也不是 LLM 生成代码；涡轮盘和叶片属于 safety-critical rotating parts，LLM / skill 只负责自然语言理解、缺参诊断和输出 CAD-IR，真实几何必须由 deterministic primitive kernel 生成。

本次必须遵守：

```text
1. 不允许让 LLM 直接生成复杂 CadQuery 脚本。
2. 不允许生成 SolidWorks COM/VBS/NXOpen/APDL 几何代码。
3. 不允许 Claude Code 自行发明涡轮盘参数名。
4. 不允许声称模型 flight-ready / airworthy / certified / manufacturing-ready / production-ready / installable。
5. 不允许实现真实航空发动机涡轮盘设计。
6. 不允许做真实 fir-tree 榫槽。
7. 不允许做真实叶片连接。
8. 不允许做真实复杂冷却流道。
9. 不允许做材料、寿命、转速、强度、适航判断。
10. SolidWorks / NX 只能 import canonical STEP，不能重建涡轮盘几何。
```

本次只做：

```text
axisymmetric_turbine_disk v0.1

范围：
- 轴对称 hub-web-rim 盘体
- 中心孔
- 螺栓孔环
- 减重孔环
- 简化冷却孔环
- CadQuery deterministic revolve kernel
- STEP
- metadata sidecar
- inspection
- mechanical_validation
- demo_full_chain case
- tests
```

---

# 4. 实施阶段划分

Claude Code 必须按下面顺序做，不能跳步。

## Phase 0：先保护现有行为

### 目标

在任何修改前，先确认当前测试可运行，记录当前失败情况。不要因为涡轮盘实现破坏齿轮、recipe、SolidWorks/NX canonical STEP import 已有行为。

### 执行

在仓库根目录执行：

```bash
cd integrations/engineering_tools
python -m pytest tests -q
```

如果当前仓库已有失败，先记录，不要擅自大改无关模块。后续新增测试只针对本任务。

---

# 5. Phase 1：修复 primitive infrastructure 的 P0 问题

## 5.1 修复 bool 参数解析

### 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py
```

### 问题

当前：

```python
normalized[pname] = bool(value)
```

这会导致：

```python
bool("False") is True
```

### 必须修改为严格解析

新增 helper：

```python
def _parse_bool(value: object, pname: str) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y"}:
            return True
        if v in {"false", "0", "no", "n"}:
            return False

    raise ValueError(
        f"Parameter '{pname}' must be bool or strict bool string "
        f"(true/false/1/0/yes/no), got {type(value).__name__}: {value!r}"
    )
```

替换 bool 分支为：

```python
elif expected_type == "bool":
    normalized[pname] = _parse_bool(value, pname)
```

### 验收

必须新增测试：

```text
tests/test_primitive_bool_normalization.py
```

测试内容：

```python
import pytest

from seekflow_engineering_tools.geometry_primitives.registry import _parse_bool


def test_parse_bool_false_string_is_false():
    assert _parse_bool("False", "non_flight_reference_only") is False
    assert _parse_bool("false", "non_flight_reference_only") is False
    assert _parse_bool("0", "non_flight_reference_only") is False
    assert _parse_bool("no", "non_flight_reference_only") is False


def test_parse_bool_true_string_is_true():
    assert _parse_bool("True", "non_flight_reference_only") is True
    assert _parse_bool("true", "non_flight_reference_only") is True
    assert _parse_bool("1", "non_flight_reference_only") is True
    assert _parse_bool("yes", "non_flight_reference_only") is True


def test_parse_bool_rejects_ambiguous_string():
    with pytest.raises(ValueError):
        _parse_bool("maybe", "non_flight_reference_only")
```

如果不想暴露 `_parse_bool`，可以通过一个临时测试 primitive 或涡轮盘 primitive 的 normalization 间接测试。但无论如何，必须证明 `"False"` 不会变成 `True`。

---

## 5.2 修复 generic primitive metadata warnings 规则

### 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/primitive_metadata.py
```

### 当前问题

函数说明写的是：

```text
warnings if present must be list[str]
```

但非 list 只给 warning，导致 `ok=True` 的可能性存在。([GitHub][13])

### 必须改成 error

替换：

```python
if bw is not None:
    if not isinstance(bw, list):
        issues.append({
            "code": "primitive_warnings_not_list",
            "message": "Metadata 'warnings' must be a list.",
            "severity": "warning",
        })
        normalized["warnings"] = []
else:
    normalized["warnings"] = []
```

为：

```python
if bw is None:
    normalized["warnings"] = []
elif not isinstance(bw, list):
    issues.append({
        "code": "primitive_warnings_not_list",
        "message": "Metadata 'warnings' must be a list[str].",
        "severity": "error",
    })
elif not all(isinstance(item, str) for item in bw):
    issues.append({
        "code": "primitive_warnings_item_not_str",
        "message": "Metadata 'warnings' must contain only strings.",
        "severity": "error",
    })
else:
    normalized["warnings"] = bw
```

### 验收

新增或更新：

```text
tests/test_primitive_metadata_v1.py
```

必须包含：

```python
from seekflow_engineering_tools.mechanical_validation.primitive_metadata import (
    validate_primitive_metadata_v1,
)


def _base_metadata():
    return {
        "primitive": "axisymmetric_turbine_disk",
        "metadata_version": "primitive_metadata_v1",
        "kernel": "cadquery_axisymmetric_revolve_v0",
        "parameters": {},
        "reference_dimensions": {},
        "warnings": [],
    }


def test_warnings_not_list_is_error():
    md = _base_metadata()
    md["warnings"] = "not-a-list"

    result = validate_primitive_metadata_v1(
        primitive_name="axisymmetric_turbine_disk",
        metadata=md,
    )

    assert result["ok"] is False
    assert any(i["code"] == "primitive_warnings_not_list" for i in result["issues"])


def test_warnings_item_not_str_is_error():
    md = _base_metadata()
    md["warnings"] = ["ok", 123]

    result = validate_primitive_metadata_v1(
        primitive_name="axisymmetric_turbine_disk",
        metadata=md,
    )

    assert result["ok"] is False
    assert any(i["code"] == "primitive_warnings_item_not_str" for i in result["issues"])
```

---

## 5.3 重构 `demo_full_chain.py`：新增真正 generic primitive runner

### 文件

```text
integrations/engineering_tools/demo_full_chain.py
```

### 当前问题

当前 demo 只有齿轮 primitive case，strategy 缺失时会 fallback 到 `"native_cadquery_primitive"`，并且 metrics 只保留齿轮 reference dimensions。([GitHub][1]) ([GitHub][1])

### 必须做的重构

新增真正通用函数：

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


def _metric_get(metrics: dict, dotted_key: str):
    value = metrics
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _finalize_case_report(
    report: dict,
    required_stages: list[str],
    *,
    allow_skipped_stages: set[str] | None = None,
    required_metrics: list[str] | None = None,
) -> dict:
    allow_skipped_stages = allow_skipped_stages or set()
    required_metrics = required_metrics or []

    ok = True
    errors = report.setdefault("errors", [])
    stages = report.setdefault("stages", {})
    metrics = report.setdefault("metrics", {})

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
            errors.append(f"[{stage_name}] {err}")

    for key in required_metrics:
        value = _metric_get(metrics, key)
        if value in (None, "", "unknown"):
            ok = False
            errors.append(f"[metrics] Required metric missing or invalid: {key}")

    report["overall_ok"] = ok
    return report
```

新增：

```python
def _run_primitive_case(
    case_name: str,
    backend: str,
    output_root: Path,
    primitive_name: str,
    params: dict,
    step_filename: str,
    *,
    extra_validation: dict | None = None,
    required_metrics: list[str] | None = None,
    allow_step_import: bool = False,
) -> dict:
    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.capabilities.registry import get_primitive_strategy

    report = _make_report_skeleton(case_name, backend)
    config = EngineeringToolsConfig(workspace_root=output_root, allow_overwrite=True)
    validate_fn, build_fn = _get_unified_tools(config)

    spec_dict = {
        "name": f"{case_name}_demo",
        "units": "mm",
        "target_backend": [backend],
        "features": [
            {
                "id": "primitive1",
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
        "validation": {
            "expected_body_count": 1,
            "tolerance_mm": 0.5,
            **(extra_validation or {}),
        },
    }

    val_result = validate_fn(spec_dict)
    _stage(
        report,
        "validate_cad_ir",
        ok=val_result.get("ok", False),
        error=val_result.get("error"),
    )

    norm_params = val_result.get("metrics", {}).get("normalized_parameters", {})
    _stage(
        report,
        "normalize_primitives",
        ok=val_result.get("ok", False),
        normalized_params=norm_params.get("primitive1"),
    )

    if not val_result.get("ok"):
        return _finalize_case_report(
            report,
            PRIMITIVE_REQUIRED_STAGES,
            required_metrics=required_metrics,
        )

    if backend in ("solidworks2025", "nx12") and not allow_step_import:
        _fail(
            report,
            "choose_backend",
            (
                f"Backend '{backend}' requires --allow-step-import for primitive "
                f"'{primitive_name}'. Use --backend cadquery or add --allow-step-import."
            ),
        )
        return _finalize_case_report(
            report,
            PRIMITIVE_REQUIRED_STAGES,
            required_metrics=required_metrics,
        )

    strategy = get_primitive_strategy(backend, primitive_name)
    if strategy is None:
        _fail(
            report,
            "choose_backend",
            (
                f"No primitive strategy registered for primitive '{primitive_name}' "
                f"on backend '{backend}'."
            ),
        )
        return _finalize_case_report(
            report,
            PRIMITIVE_REQUIRED_STAGES,
            required_metrics=required_metrics,
        )

    _stage(report, "choose_backend", ok=True, backend=backend, strategy=strategy)

    step_path = output_root / "models" / step_filename
    step_path.parent.mkdir(parents=True, exist_ok=True)

    build_result = build_fn(
        spec_dict,
        backend=backend,
        out_step=str(step_path),
        inspect=True,
        allow_backend_fallback=False,
    )

    _stage(
        report,
        "build",
        ok=build_result.get("ok", False),
        error=build_result.get("error") if not build_result.get("ok", False) else None,
    )

    report["files_created"] = build_result.get("files_created", [])
    report["warnings"] = build_result.get("warnings", [])

    metrics = build_result.get("metrics", {})
    validation_result = metrics.get("validation")
    mech_val_result = metrics.get("mechanical_validation")

    if validation_result is None:
        _stage(report, "inspect", ok=False, error="Validation result missing from build metrics.")
    else:
        _stage(report, "inspect", ok=validation_result.get("ok") is True)

    if mech_val_result is None:
        _stage(
            report,
            "mechanical_validate",
            ok=False,
            error="Mechanical validation result missing from build metrics.",
        )
    else:
        _stage(report, "mechanical_validate", ok=mech_val_result.get("ok") is True)

    kernel_used = "unknown"
    ref_dims = {}

    meta_path = step_path.with_suffix(".metadata.json")
    if meta_path.exists() and meta_path.stat().st_size > 0:
        try:
            sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
            pm = sidecar.get("primitive_metadata", {}).get(primitive_name, {})
            if pm.get("kernel"):
                kernel_used = pm["kernel"]
            if pm.get("reference_dimensions"):
                ref_dims = pm["reference_dimensions"]
            _stage(report, "metadata", ok=True, metadata_path=str(meta_path))
        except (json.JSONDecodeError, OSError) as exc:
            _stage(
                report,
                "metadata",
                ok=False,
                error=f"Failed to read primitive metadata sidecar: {exc}",
            )
    else:
        _stage(report, "metadata", ok=False, error="Primitive metadata sidecar missing or empty.")

    if kernel_used == "unknown" and mech_val_result:
        for r in mech_val_result.get("results", []):
            if r.get("primitive") == primitive_name:
                if r.get("kernel"):
                    kernel_used = r["kernel"]
                if r.get("reference_dimensions"):
                    ref_dims = r["reference_dimensions"]

    report["metrics"] = {
        **metrics,
        "kernel_used": kernel_used,
        "reference_dimensions": ref_dims,
    }

    return _finalize_case_report(
        report,
        PRIMITIVE_REQUIRED_STAGES,
        required_metrics=required_metrics,
    )
```

### 重要约束

不得再写：

```python
strategy = get_primitive_strategy(...) or "native_cadquery_primitive"
```

不得在 generic primitive runner 中写：

```python
"reference_dimensions": {
    "pitch_diameter_mm": ...,
    "base_diameter_mm": ...,
}
```

齿轮需要什么 metrics，由 `GEAR_REQUIRED_METRICS` 指定；涡轮盘需要什么 metrics，由 `TURBINE_DISK_REQUIRED_METRICS` 指定。

---

# 6. Phase 2：实现 `axisymmetric_turbine_disk` primitive definition

## 6.1 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py
```

## 6.2 替换空 registry

当前：

```python
TURBOMACHINERY_PRIMITIVES: list[PrimitiveDefinition] = []
```

改为注册 `axisymmetric_turbine_disk`。

## 6.3 参数固定

不得新增、删减、改名。参数表固定为：

```text
outer_dia_mm
bore_dia_mm
axial_width_mm

hub_outer_dia_mm
web_outer_dia_mm
rim_inner_dia_mm

hub_width_mm
web_width_mm
rim_width_mm

hub_fillet_radius_mm
web_fillet_radius_mm
rim_fillet_radius_mm
edge_chamfer_mm

bolt_hole_count
bolt_pcd_mm
bolt_hole_dia_mm
bolt_hole_axis

lightening_hole_count
lightening_hole_pcd_mm
lightening_hole_dia_mm
lightening_hole_axis

cooling_hole_count
cooling_hole_pcd_mm
cooling_hole_dia_mm
cooling_hole_axis

quality_grade
non_flight_reference_only
```

## 6.4 建议实现

```python
from seekflow_engineering_tools.geometry_primitives.base import (
    PrimitiveDefinition,
    PrimitiveParameter,
)

AXISYMMETRIC_TURBINE_DISK = PrimitiveDefinition(
    name="axisymmetric_turbine_disk",
    category="turbomachinery",
    description=(
        "Axisymmetric turbine disk non-flight reference geometry: "
        "hub-web-rim body, center bore, and optional bolt/lightening/cooling "
        "hole rings. This primitive is not airworthy, not certified, and not "
        "for manufacturing."
    ),
    parameters=[
        PrimitiveParameter(name="outer_dia_mm", type="float", unit="mm", required=True, min_value=1.0),
        PrimitiveParameter(name="bore_dia_mm", type="float", unit="mm", required=True, min_value=0.0),
        PrimitiveParameter(name="axial_width_mm", type="float", unit="mm", required=True, min_value=0.1),

        PrimitiveParameter(name="hub_outer_dia_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="web_outer_dia_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="rim_inner_dia_mm", type="float", unit="mm", required=True, min_value=0.1),

        PrimitiveParameter(name="hub_width_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="web_width_mm", type="float", unit="mm", required=True, min_value=0.1),
        PrimitiveParameter(name="rim_width_mm", type="float", unit="mm", required=True, min_value=0.1),

        PrimitiveParameter(name="hub_fillet_radius_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="web_fillet_radius_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="rim_fillet_radius_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="edge_chamfer_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),

        PrimitiveParameter(name="bolt_hole_count", type="int", required=False, default=0, min_value=0),
        PrimitiveParameter(name="bolt_pcd_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="bolt_hole_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="bolt_hole_axis", type="str", required=False, default="Z"),

        PrimitiveParameter(name="lightening_hole_count", type="int", required=False, default=0, min_value=0),
        PrimitiveParameter(name="lightening_hole_pcd_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="lightening_hole_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="lightening_hole_axis", type="str", required=False, default="Z"),

        PrimitiveParameter(name="cooling_hole_count", type="int", required=False, default=0, min_value=0),
        PrimitiveParameter(name="cooling_hole_pcd_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="cooling_hole_dia_mm", type="float", unit="mm", required=False, default=0.0, min_value=0.0),
        PrimitiveParameter(name="cooling_hole_axis", type="str", required=False, default="Z"),

        PrimitiveParameter(name="quality_grade", type="str", required=False, default="concept_geometry"),
        PrimitiveParameter(name="non_flight_reference_only", type="bool", required=False, default=True),
    ],
    supported_kernels=["cadquery_axisymmetric_revolve_v0"],
    supported_backends=["cadquery", "solidworks2025", "nx12"],
    standards=[],
    validation_defaults={
        "expected_body_count": 1,
        "tolerance_mm": 0.5,
        "non_flight_reference_only": True,
    },
)

TURBOMACHINERY_PRIMITIVES: list[PrimitiveDefinition] = [
    AXISYMMETRIC_TURBINE_DISK,
]
```

---

# 7. Phase 3：实现参数 validator

## 7.1 新增文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/validator.py
```

## 7.2 validator 目标

validator 不做真实航空强度判断，只做：

```text
1. 参数存在性和类型已由 PrimitiveParameter/normalizer 做基础处理；
2. validator 做 geometry consistency；
3. validator 做 fail-closed safety scope；
4. validator 防止明显无效、重叠、不可建模的孔环；
5. validator 禁止非 reference quality。
```

## 7.3 必须实现

```python
from __future__ import annotations

import math


ALLOWED_QUALITY_GRADES = {"concept_geometry", "engineering_reference"}
FORBIDDEN_QUALITY_GRADES = {
    "flight_ready",
    "airworthy",
    "certified",
    "manufacturing_ready",
    "production_ready",
    "installable",
}


def _f(params: dict, key: str) -> float:
    return float(params.get(key, 0.0))


def _i(params: dict, key: str) -> int:
    return int(params.get(key, 0))


def _validate_hole_ring(
    errors: list[str],
    *,
    name: str,
    count: int,
    pcd_mm: float,
    hole_dia_mm: float,
    axis: str,
    min_radius_mm: float,
    max_radius_mm: float,
    radial_margin_mm: float,
) -> None:
    if count == 0:
        if pcd_mm != 0:
            errors.append(f"{name}_pcd_mm must be 0 when {name}_hole_count is 0")
        if hole_dia_mm != 0:
            errors.append(f"{name}_hole_dia_mm must be 0 when {name}_hole_count is 0")
        return

    if count < 2:
        errors.append(f"{name}_hole_count must be 0 or >= 2")
        return

    if axis != "Z":
        errors.append(f"{name}_hole_axis must be 'Z' in v0.1")

    if pcd_mm <= 0:
        errors.append(f"{name}_pcd_mm must be > 0 when {name}_hole_count > 0")
        return

    if hole_dia_mm <= 0:
        errors.append(f"{name}_hole_dia_mm must be > 0 when {name}_hole_count > 0")
        return

    ring_radius = pcd_mm / 2.0
    hole_radius = hole_dia_mm / 2.0

    if ring_radius - hole_radius - radial_margin_mm <= min_radius_mm:
        errors.append(
            f"{name} hole ring intrudes inward: "
            f"ring_radius({ring_radius}) - hole_radius({hole_radius}) - margin({radial_margin_mm}) "
            f"must be > min_radius({min_radius_mm})"
        )

    if ring_radius + hole_radius + radial_margin_mm >= max_radius_mm:
        errors.append(
            f"{name} hole ring intrudes outward: "
            f"ring_radius({ring_radius}) + hole_radius({hole_radius}) + margin({radial_margin_mm}) "
            f"must be < max_radius({max_radius_mm})"
        )

    chord_spacing = 2.0 * ring_radius * math.sin(math.pi / count)
    if chord_spacing <= hole_dia_mm * 1.25:
        errors.append(
            f"{name} holes are too close: chord spacing {chord_spacing:.3f} mm "
            f"must be > 1.25 * hole_dia_mm ({hole_dia_mm * 1.25:.3f} mm)"
        )


def validate_axisymmetric_turbine_disk_parameters(params: dict) -> list[str]:
    errors: list[str] = []

    outer_d = _f(params, "outer_dia_mm")
    bore_d = _f(params, "bore_dia_mm")
    axial_w = _f(params, "axial_width_mm")

    hub_d = _f(params, "hub_outer_dia_mm")
    web_d = _f(params, "web_outer_dia_mm")
    rim_inner_d = _f(params, "rim_inner_dia_mm")

    hub_w = _f(params, "hub_width_mm")
    web_w = _f(params, "web_width_mm")
    rim_w = _f(params, "rim_width_mm")

    quality = str(params.get("quality_grade", "concept_geometry"))
    non_flight = params.get("non_flight_reference_only")

    if quality not in ALLOWED_QUALITY_GRADES:
        errors.append(
            f"quality_grade must be one of {sorted(ALLOWED_QUALITY_GRADES)}, got {quality!r}"
        )

    if quality in FORBIDDEN_QUALITY_GRADES:
        errors.append(
            f"quality_grade={quality!r} is forbidden for axisymmetric_turbine_disk"
        )

    if non_flight is not True:
        errors.append(
            "axisymmetric_turbine_disk requires non_flight_reference_only=True; "
            "this primitive is reference geometry only"
        )

    if outer_d <= 0:
        errors.append("outer_dia_mm must be > 0")
    if bore_d < 0:
        errors.append("bore_dia_mm must be >= 0")
    if axial_w <= 0:
        errors.append("axial_width_mm must be > 0")

    if not (bore_d < hub_d < web_d <= rim_inner_d < outer_d):
        errors.append(
            "Diameter ordering must satisfy: "
            "bore_dia_mm < hub_outer_dia_mm < web_outer_dia_mm "
            "<= rim_inner_dia_mm < outer_dia_mm"
        )

    if bore_d > 0 and bore_d >= 0.75 * hub_d:
        errors.append(
            "bore_dia_mm must be < 0.75 * hub_outer_dia_mm for stable reference geometry"
        )

    for key, value in [
        ("hub_width_mm", hub_w),
        ("web_width_mm", web_w),
        ("rim_width_mm", rim_w),
    ]:
        if value <= 0:
            errors.append(f"{key} must be > 0")
        if axial_w > 0 and value > axial_w:
            errors.append(f"{key} must be <= axial_width_mm")

    if web_w > hub_w:
        errors.append("web_width_mm must be <= hub_width_mm")
    if web_w > rim_w:
        errors.append("web_width_mm must be <= rim_width_mm")

    for key in [
        "hub_fillet_radius_mm",
        "web_fillet_radius_mm",
        "rim_fillet_radius_mm",
        "edge_chamfer_mm",
    ]:
        value = _f(params, key)
        if value < 0:
            errors.append(f"{key} must be >= 0")
        if axial_w > 0 and value > axial_w * 0.2:
            errors.append(f"{key} must be <= 0.2 * axial_width_mm in v0.1")

    r_bore = bore_d / 2.0
    r_hub = hub_d / 2.0
    r_web = web_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    r_outer = outer_d / 2.0
    radial_margin = max(1.0, outer_d * 0.005)

    _validate_hole_ring(
        errors,
        name="bolt",
        count=_i(params, "bolt_hole_count"),
        pcd_mm=_f(params, "bolt_pcd_mm"),
        hole_dia_mm=_f(params, "bolt_hole_dia_mm"),
        axis=str(params.get("bolt_hole_axis", "Z")),
        min_radius_mm=r_bore,
        max_radius_mm=r_hub,
        radial_margin_mm=radial_margin,
    )

    _validate_hole_ring(
        errors,
        name="lightening",
        count=_i(params, "lightening_hole_count"),
        pcd_mm=_f(params, "lightening_hole_pcd_mm"),
        hole_dia_mm=_f(params, "lightening_hole_dia_mm"),
        axis=str(params.get("lightening_hole_axis", "Z")),
        min_radius_mm=r_hub,
        max_radius_mm=r_rim_inner,
        radial_margin_mm=radial_margin,
    )

    _validate_hole_ring(
        errors,
        name="cooling",
        count=_i(params, "cooling_hole_count"),
        pcd_mm=_f(params, "cooling_hole_pcd_mm"),
        hole_dia_mm=_f(params, "cooling_hole_dia_mm"),
        axis=str(params.get("cooling_hole_axis", "Z")),
        min_radius_mm=r_web,
        max_radius_mm=r_outer,
        radial_margin_mm=radial_margin,
    )

    return errors
```

## 7.4 接入 registry

在 `normalize_primitive_parameters()` 末尾增加：

```python
elif primitive_name == "axisymmetric_turbine_disk":
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.validator import (
        validate_axisymmetric_turbine_disk_parameters,
    )

    disk_errors = validate_axisymmetric_turbine_disk_parameters(normalized)
    if disk_errors:
        raise ValueError(
            "Turbine disk validation failed: " + "; ".join(disk_errors)
        )
```

---

# 8. Phase 4：实现 deterministic CadQuery kernel

## 8.1 新增文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py
```

## 8.2 kernel 约束

```text
1. 只能 deterministic。
2. 不允许随机扰动。
3. 不允许读取外部 CAD 模板。
4. 不允许调用 LLM。
5. 不允许在 kernel 内做 safety / life / stress claim。
6. 输出必须是 CadQuery object + metadata dict。
```

## 8.3 几何坐标约定

```text
Z 轴：旋转轴 / 轴向；
XY 平面：径向平面；
原点：盘体中心；
总外径：outer_dia_mm；
总轴向宽度：axial_width_mm；
中心孔：bore_dia_mm；
```

## 8.4 profile 点定义

建议用 XZ 半剖面，X 是半径，Z 是轴向坐标：

```python
r_bore = bore_dia_mm / 2
r_hub = hub_outer_dia_mm / 2
r_web = web_outer_dia_mm / 2
r_rim_inner = rim_inner_dia_mm / 2
r_outer = outer_dia_mm / 2

t_hub = hub_width_mm / 2
t_web = web_width_mm / 2
t_rim = rim_width_mm / 2
```

profile：

```python
profile_points = [
    (r_bore, -t_hub),
    (r_hub, -t_hub),
    (r_hub, -t_web),
    (r_web, -t_web),
    (r_rim_inner, -t_rim),
    (r_outer, -t_rim),
    (r_outer, t_rim),
    (r_rim_inner, t_rim),
    (r_web, t_web),
    (r_hub, t_web),
    (r_hub, t_hub),
    (r_bore, t_hub),
]
```

## 8.5 推荐代码骨架

```python
from __future__ import annotations

import math
from typing import Any


KERNEL_NAME = "cadquery_axisymmetric_revolve_v0"
PRIMITIVE_NAME = "axisymmetric_turbine_disk"


def _hole_pattern_metadata(name: str, count: int, pcd_mm: float, dia_mm: float, axis: str) -> dict[str, Any]:
    return {
        "name": name,
        "count": int(count),
        "pcd_mm": float(pcd_mm),
        "hole_dia_mm": float(dia_mm),
        "axis": axis,
    }


def _cut_hole_ring(result, *, count: int, pcd_mm: float, hole_dia_mm: float, axis: str):
    if count == 0:
        return result

    if axis != "Z":
        raise ValueError(f"Only Z-axis through holes are supported in v0.1, got {axis!r}")

    radius = pcd_mm / 2.0

    return (
        result.faces(">Z")
        .workplane(centerOption="CenterOfBoundBox")
        .polarArray(radius, 0, 360, count)
        .hole(hole_dia_mm)
    )


def _reference_dimensions(params: dict) -> dict[str, Any]:
    return {
        "outer_dia_mm": float(params["outer_dia_mm"]),
        "bore_dia_mm": float(params["bore_dia_mm"]),
        "axial_width_mm": float(params["axial_width_mm"]),
        "hub_outer_dia_mm": float(params["hub_outer_dia_mm"]),
        "web_outer_dia_mm": float(params["web_outer_dia_mm"]),
        "rim_inner_dia_mm": float(params["rim_inner_dia_mm"]),
        "hub_width_mm": float(params["hub_width_mm"]),
        "web_width_mm": float(params["web_width_mm"]),
        "rim_width_mm": float(params["rim_width_mm"]),
        "bolt_hole_count": int(params["bolt_hole_count"]),
        "lightening_hole_count": int(params["lightening_hole_count"]),
        "cooling_hole_count": int(params["cooling_hole_count"]),
        "expected_through_hole_count": (
            1
            + int(params["bolt_hole_count"])
            + int(params["lightening_hole_count"])
            + int(params["cooling_hole_count"])
        ),
    }


def build_axisymmetric_turbine_disk_cadquery(params: dict):
    import cadquery as cq

    outer_d = float(params["outer_dia_mm"])
    bore_d = float(params["bore_dia_mm"])
    hub_d = float(params["hub_outer_dia_mm"])
    web_d = float(params["web_outer_dia_mm"])
    rim_inner_d = float(params["rim_inner_dia_mm"])

    hub_w = float(params["hub_width_mm"])
    web_w = float(params["web_width_mm"])
    rim_w = float(params["rim_width_mm"])

    r_bore = bore_d / 2.0
    r_hub = hub_d / 2.0
    r_web = web_d / 2.0
    r_rim_inner = rim_inner_d / 2.0
    r_outer = outer_d / 2.0

    t_hub = hub_w / 2.0
    t_web = web_w / 2.0
    t_rim = rim_w / 2.0

    profile_points = [
        (r_bore, -t_hub),
        (r_hub, -t_hub),
        (r_hub, -t_web),
        (r_web, -t_web),
        (r_rim_inner, -t_rim),
        (r_outer, -t_rim),
        (r_outer, t_rim),
        (r_rim_inner, t_rim),
        (r_web, t_web),
        (r_hub, t_web),
        (r_hub, t_hub),
        (r_bore, t_hub),
    ]

    result = (
        cq.Workplane("XZ")
        .polyline(profile_points)
        .close()
        .revolve(360, (0, 0, 0), (0, 0, 1))
    )

    result = _cut_hole_ring(
        result,
        count=int(params["bolt_hole_count"]),
        pcd_mm=float(params["bolt_pcd_mm"]),
        hole_dia_mm=float(params["bolt_hole_dia_mm"]),
        axis=str(params["bolt_hole_axis"]),
    )

    result = _cut_hole_ring(
        result,
        count=int(params["lightening_hole_count"]),
        pcd_mm=float(params["lightening_hole_pcd_mm"]),
        hole_dia_mm=float(params["lightening_hole_dia_mm"]),
        axis=str(params["lightening_hole_axis"]),
    )

    result = _cut_hole_ring(
        result,
        count=int(params["cooling_hole_count"]),
        pcd_mm=float(params["cooling_hole_pcd_mm"]),
        hole_dia_mm=float(params["cooling_hole_dia_mm"]),
        axis=str(params["cooling_hole_axis"]),
    )

    warnings: list[str] = [
        "axisymmetric_turbine_disk is non-flight reference geometry only.",
        "Not airworthy, not certified, not manufacturing-ready.",
        "No real fir-tree slots, blade attachment, material, stress, life, or cooling-flow validation is performed.",
    ]

    ref_dims = _reference_dimensions(params)

    metadata = {
        "primitive": PRIMITIVE_NAME,
        "metadata_version": "primitive_metadata_v1",
        "kernel": KERNEL_NAME,
        "parameters": dict(params),
        "reference_dimensions": ref_dims,
        "warnings": warnings,
        "radial_zones": {
            "bore_radius_mm": r_bore,
            "hub_outer_radius_mm": r_hub,
            "web_outer_radius_mm": r_web,
            "rim_inner_radius_mm": r_rim_inner,
            "outer_radius_mm": r_outer,
        },
        "profile_points": [[float(r), float(z)] for r, z in profile_points],
        "hole_patterns": [
            _hole_pattern_metadata(
                "bolt",
                int(params["bolt_hole_count"]),
                float(params["bolt_pcd_mm"]),
                float(params["bolt_hole_dia_mm"]),
                str(params["bolt_hole_axis"]),
            ),
            _hole_pattern_metadata(
                "lightening",
                int(params["lightening_hole_count"]),
                float(params["lightening_hole_pcd_mm"]),
                float(params["lightening_hole_dia_mm"]),
                str(params["lightening_hole_axis"]),
            ),
            _hole_pattern_metadata(
                "cooling",
                int(params["cooling_hole_count"]),
                float(params["cooling_hole_pcd_mm"]),
                float(params["cooling_hole_dia_mm"]),
                str(params["cooling_hole_axis"]),
            ),
        ],
        "safety": {
            "non_flight_reference_only": True,
            "not_for_manufacturing": True,
            "not_airworthy": True,
            "not_certified": True,
        },
    }

    return result, metadata
```

## 8.6 注意 CadQuery revolve 坐标风险

如果 `cq.Workplane("XZ").polyline(...).revolve(...)` 在本地测试中轴向 bbox 不符合预期，Claude Code 不得用“调 tolerance”掩盖。必须修正坐标建模方式，直到：

```text
bbox X ≈ outer_dia_mm
bbox Y ≈ outer_dia_mm
bbox Z ≈ axial_width_mm
```

可选替代方式：

```python
result = (
    cq.Workplane("XZ")
    .polyline(profile_points)
    .close()
    .revolve(angleDegrees=360)
)
```

或根据 CadQuery 实际 API 调整 revolve axis，但最终验收以 inspection bbox 为准。

---

# 9. Phase 5：实现 turbine-specific metadata validation

## 9.1 当前 builder 位置

`builder._assert_metadata_sidecar()` 已经调用：

```python
validate_primitive_metadata_v1(...)
_assert_primitive_specific_metadata(pname, primitive_entry)
```

目前 `_assert_primitive_specific_metadata()` 只检查齿轮的 `is_standard_involute`。([GitHub][7])

## 9.2 修改文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py
```

## 9.3 新增 turbine metadata check

不要把复杂逻辑全部塞进 builder，建议新增：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/metadata.py
```

实现：

```python
from __future__ import annotations


REQUIRED_TURBINE_METADATA_KEYS = [
    "radial_zones",
    "profile_points",
    "hole_patterns",
    "safety",
]


def validate_axisymmetric_turbine_disk_metadata(metadata: dict) -> list[str]:
    errors: list[str] = []

    for key in REQUIRED_TURBINE_METADATA_KEYS:
        if key not in metadata:
            errors.append(f"axisymmetric_turbine_disk metadata missing '{key}'")

    radial_zones = metadata.get("radial_zones")
    if not isinstance(radial_zones, dict):
        errors.append("axisymmetric_turbine_disk metadata 'radial_zones' must be a dict")
    else:
        required_zones = [
            "bore_radius_mm",
            "hub_outer_radius_mm",
            "web_outer_radius_mm",
            "rim_inner_radius_mm",
            "outer_radius_mm",
        ]
        for key in required_zones:
            if key not in radial_zones:
                errors.append(f"radial_zones missing '{key}'")

    profile_points = metadata.get("profile_points")
    if not isinstance(profile_points, list) or len(profile_points) < 4:
        errors.append("axisymmetric_turbine_disk metadata 'profile_points' must be a non-empty list")

    hole_patterns = metadata.get("hole_patterns")
    if not isinstance(hole_patterns, list):
        errors.append("axisymmetric_turbine_disk metadata 'hole_patterns' must be a list")
    else:
        names = {p.get("name") for p in hole_patterns if isinstance(p, dict)}
        for expected in {"bolt", "lightening", "cooling"}:
            if expected not in names:
                errors.append(f"hole_patterns missing '{expected}' pattern")

    safety = metadata.get("safety")
    if not isinstance(safety, dict):
        errors.append("axisymmetric_turbine_disk metadata 'safety' must be a dict")
    else:
        if safety.get("non_flight_reference_only") is not True:
            errors.append("safety.non_flight_reference_only must be True")
        if safety.get("not_airworthy") is not True:
            errors.append("safety.not_airworthy must be True")
        if safety.get("not_certified") is not True:
            errors.append("safety.not_certified must be True")
        if safety.get("not_for_manufacturing") is not True:
            errors.append("safety.not_for_manufacturing must be True")

    return errors
```

然后在 builder 中扩展：

```python
def _assert_primitive_specific_metadata(pname: str, primitive_entry: dict) -> None:
    if pname == "involute_spur_gear":
        if "is_standard_involute" not in primitive_entry:
            raise ValueError("Gear metadata missing 'is_standard_involute'")

    elif pname == "axisymmetric_turbine_disk":
        from seekflow_engineering_tools.geometry_primitives.turbomachinery.metadata import (
            validate_axisymmetric_turbine_disk_metadata,
        )

        errors = validate_axisymmetric_turbine_disk_metadata(primitive_entry)
        if errors:
            raise ValueError(
                "Turbine disk metadata validation failed: " + "; ".join(errors)
            )
```

---

# 10. Phase 6：实现 CadQuery primitive compiler handler

## 10.1 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
```

## 10.2 添加 handler

```python
def _compile_axisymmetric_turbine_disk(feature) -> list[str]:
    params = feature.parameters
    param_lines = []

    for k, v in params.items():
        if isinstance(v, str):
            param_lines.append(f'    "{k": {v!r},')
        else:
            param_lines.append(f'    "{k": {v!r},')

    code = f"""
# [Primitive: axisymmetric_turbine_disk]
from seekflow_engineering_tools.geometry_primitives.turbomachinery.axisymmetric_turbine_disk import (
    build_axisymmetric_turbine_disk_cadquery,
)

_params = {{
{chr(10).join(param_lines)}
}}

result, PRIMITIVE_METADATA["axisymmetric_turbine_disk"] = (
    build_axisymmetric_turbine_disk_cadquery(_params)
)

BUILD_WARNINGS.extend(
    PRIMITIVE_METADATA["axisymmetric_turbine_disk"].get("warnings", [])
)
"""
    return code.strip().split("\n")
```

注册：

```python
register_primitive_compiler(
    "axisymmetric_turbine_disk",
    _compile_axisymmetric_turbine_disk,
)
```

## 10.3 约束

不要把涡轮盘代码 inline 到 compiler 里。compiler 只负责把 CAD-IR feature 编译为 deterministic kernel 调用。

---

# 11. Phase 7：实现 mechanical validation

## 11.1 新增文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/turbomachinery_validation.py
```

## 11.2 目标

mechanical validation 必须 fail-closed。不能因为 STEP 已生成就通过。

必须检查：

```text
1. metadata 存在；
2. metadata["primitive"] == "axisymmetric_turbine_disk"；
3. metadata["kernel"] == "cadquery_axisymmetric_revolve_v0"；
4. metadata["parameters"] 与 CAD-IR params 一致；
5. metadata["reference_dimensions"] 与 CAD-IR params 一致；
6. bbox X/Y/Z 与 outer_dia_mm / axial_width_mm 一致；
7. body count 为 1；
8. expected_through_hole_count 一致；
9. non_flight_reference_only 是 True；
10. safety flags 全是 True；
11. quality_grade 只能是 concept_geometry 或 engineering_reference。
```

## 11.3 推荐实现

```python
from __future__ import annotations

from typing import Any


PRIMITIVE_NAME = "axisymmetric_turbine_disk"
KERNEL_NAME = "cadquery_axisymmetric_revolve_v0"
ALLOWED_QUALITY_GRADES = {"concept_geometry", "engineering_reference"}


def _issue(code: str, message: str, *, expected=None, actual=None, severity: str = "error") -> dict:
    item = {
        "code": code,
        "message": message,
        "severity": severity,
    }
    if expected is not None:
        item["expected"] = expected
    if actual is not None:
        item["actual"] = actual
    return item


def _float_equal(a: Any, b: Any, tol: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _expected_reference_dimensions(params: dict) -> dict[str, Any]:
    return {
        "outer_dia_mm": float(params["outer_dia_mm"]),
        "bore_dia_mm": float(params["bore_dia_mm"]),
        "axial_width_mm": float(params["axial_width_mm"]),
        "hub_outer_dia_mm": float(params["hub_outer_dia_mm"]),
        "web_outer_dia_mm": float(params["web_outer_dia_mm"]),
        "rim_inner_dia_mm": float(params["rim_inner_dia_mm"]),
        "hub_width_mm": float(params["hub_width_mm"]),
        "web_width_mm": float(params["web_width_mm"]),
        "rim_width_mm": float(params["rim_width_mm"]),
        "bolt_hole_count": int(params["bolt_hole_count"]),
        "lightening_hole_count": int(params["lightening_hole_count"]),
        "cooling_hole_count": int(params["cooling_hole_count"]),
        "expected_through_hole_count": (
            1
            + int(params["bolt_hole_count"])
            + int(params["lightening_hole_count"])
            + int(params["cooling_hole_count"])
        ),
    }


def validate_axisymmetric_turbine_disk_result(
    params: dict,
    inspection: dict,
    metadata: dict | None = None,
    tolerance_mm: float = 0.5,
    expected: dict | None = None,
    raw_metadata: dict | None = None,
) -> dict:
    expected = expected or {}
    issues: list[dict] = []

    ref = _expected_reference_dimensions(params)

    if metadata is None:
        issues.append(
            _issue(
                "turbine_disk_metadata_missing",
                "Turbine disk metadata sidecar is required for mechanical validation.",
            )
        )
        return {
            "ok": False,
            "primitive": PRIMITIVE_NAME,
            "issues": issues,
            "reference_dimensions": ref,
            "kernel": "unknown",
        }

    kernel = metadata.get("kernel", "unknown")

    if metadata.get("primitive") != PRIMITIVE_NAME:
        issues.append(
            _issue(
                "primitive_mismatch",
                f"Metadata primitive field is {metadata.get('primitive')!r}, expected {PRIMITIVE_NAME!r}.",
                expected=PRIMITIVE_NAME,
                actual=metadata.get("primitive"),
            )
        )

    if kernel != KERNEL_NAME:
        issues.append(
            _issue(
                "turbine_disk_kernel_mismatch",
                f"Expected kernel {KERNEL_NAME!r}, got {kernel!r}.",
                expected=KERNEL_NAME,
                actual=kernel,
            )
        )

    quality = params.get("quality_grade", "concept_geometry")
    if quality not in ALLOWED_QUALITY_GRADES:
        issues.append(
            _issue(
                "turbine_disk_quality_grade_invalid",
                f"quality_grade must be one of {sorted(ALLOWED_QUALITY_GRADES)}, got {quality!r}.",
                expected=sorted(ALLOWED_QUALITY_GRADES),
                actual=quality,
            )
        )

    if params.get("non_flight_reference_only") is not True:
        issues.append(
            _issue(
                "turbine_disk_non_flight_flag_missing",
                "CAD-IR parameter non_flight_reference_only must be True.",
                expected=True,
                actual=params.get("non_flight_reference_only"),
            )
        )

    safety = metadata.get("safety") or {}
    for key in [
        "non_flight_reference_only",
        "not_for_manufacturing",
        "not_airworthy",
        "not_certified",
    ]:
        if safety.get(key) is not True:
            issues.append(
                _issue(
                    f"turbine_disk_safety_{key}_missing",
                    f"Metadata safety.{key} must be True.",
                    expected=True,
                    actual=safety.get(key),
                )
            )

    meta_params = metadata.get("parameters") or {}
    for key, expected_value in params.items():
        actual_value = meta_params.get(key)
        if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            if not _float_equal(actual_value, expected_value, tolerance_mm):
                issues.append(
                    _issue(
                        f"turbine_disk_parameter_mismatch_{key}",
                        f"Metadata parameter {key} does not match CAD-IR parameter.",
                        expected=expected_value,
                        actual=actual_value,
                    )
                )
        else:
            if actual_value != expected_value:
                issues.append(
                    _issue(
                        f"turbine_disk_parameter_mismatch_{key}",
                        f"Metadata parameter {key} does not match CAD-IR parameter.",
                        expected=expected_value,
                        actual=actual_value,
                    )
                )

    ref_meta = metadata.get("reference_dimensions") or {}
    for key, expected_value in ref.items():
        actual_value = ref_meta.get(key)
        if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            if not _float_equal(actual_value, expected_value, tolerance_mm):
                issues.append(
                    _issue(
                        f"turbine_disk_reference_dimension_mismatch_{key}",
                        f"Reference dimension {key} mismatch.",
                        expected=expected_value,
                        actual=actual_value,
                    )
                )
        else:
            if actual_value != expected_value:
                issues.append(
                    _issue(
                        f"turbine_disk_reference_dimension_mismatch_{key}",
                        f"Reference dimension {key} mismatch.",
                        expected=expected_value,
                        actual=actual_value,
                    )
                )

    bbox = inspection.get("bbox_mm")
    if bbox and len(bbox) >= 3:
        if abs(float(bbox[0]) - ref["outer_dia_mm"]) > tolerance_mm:
            issues.append(
                _issue(
                    "turbine_disk_bbox_x_mismatch",
                    "BBox X does not match outer_dia_mm.",
                    expected=ref["outer_dia_mm"],
                    actual=bbox[0],
                )
            )
        if abs(float(bbox[1]) - ref["outer_dia_mm"]) > tolerance_mm:
            issues.append(
                _issue(
                    "turbine_disk_bbox_y_mismatch",
                    "BBox Y does not match outer_dia_mm.",
                    expected=ref["outer_dia_mm"],
                    actual=bbox[1],
                )
            )
        if abs(float(bbox[2]) - ref["axial_width_mm"]) > tolerance_mm:
            issues.append(
                _issue(
                    "turbine_disk_bbox_z_mismatch",
                    "BBox Z does not match axial_width_mm.",
                    expected=ref["axial_width_mm"],
                    actual=bbox[2],
                )
            )
    else:
        issues.append(
            _issue(
                "turbine_disk_bbox_missing",
                "Inspection did not provide bbox_mm.",
            )
        )

    actual_body = inspection.get("solid_count") or inspection.get("body_count")
    if actual_body is None:
        issues.append(
            _issue(
                "turbine_disk_body_count_missing",
                "Inspection did not report body/solid count.",
            )
        )
    elif int(actual_body) != 1:
        issues.append(
            _issue(
                "turbine_disk_body_count_mismatch",
                "Turbine disk primitive must produce exactly one solid body.",
                expected=1,
                actual=actual_body,
            )
        )

    if expected:
        expected_kernel = expected.get("expected_kernel")
        if expected_kernel and kernel != expected_kernel:
            issues.append(
                _issue(
                    "turbine_disk_expected_kernel_mismatch",
                    "Expected kernel mismatch.",
                    expected=expected_kernel,
                    actual=kernel,
                )
            )

        expected_holes = expected.get("expected_through_hole_count")
        if expected_holes is not None and int(expected_holes) != int(ref["expected_through_hole_count"]):
            issues.append(
                _issue(
                    "turbine_disk_expected_hole_count_mismatch",
                    "Expected through hole count mismatch.",
                    expected=expected_holes,
                    actual=ref["expected_through_hole_count"],
                )
            )

    ok = not any(i["severity"] == "error" for i in issues)

    return {
        "ok": ok,
        "primitive": PRIMITIVE_NAME,
        "issues": issues,
        "reference_dimensions": ref,
        "kernel": kernel,
    }
```

## 11.4 注册 validator

修改：

```text
integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/common.py
```

加入：

```python
def _validate_axisymmetric_turbine_disk_feature(
    params: dict,
    inspection: dict,
    metadata: dict | None,
    tolerance_mm: float,
    expected: dict | None = None,
    raw_metadata: dict | None = None,
) -> dict:
    from seekflow_engineering_tools.mechanical_validation.turbomachinery_validation import (
        validate_axisymmetric_turbine_disk_result,
    )

    return validate_axisymmetric_turbine_disk_result(
        params=params,
        inspection=inspection,
        metadata=metadata,
        tolerance_mm=tolerance_mm,
        expected=expected or {},
        raw_metadata=raw_metadata,
    )


register_primitive_mechanical_validator(
    "axisymmetric_turbine_disk",
    _validate_axisymmetric_turbine_disk_feature,
)
```

---

# 12. Phase 8：capability registry 接入

## 文件

```text
integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py
```

## 修改原则

只有在以下全部完成后，才能把 `axisymmetric_turbine_disk` 加入 capability registry：

```text
1. PrimitiveDefinition 已注册；
2. parameter validator 已接入 normalize_primitive_parameters；
3. CadQuery compiler handler 已注册；
4. deterministic kernel 已实现；
5. metadata sidecar 可生成；
6. generic metadata validation 可通过；
7. turbine-specific metadata validation 可通过；
8. mechanical validator 已注册；
9. tests 已覆盖 happy path 与 fail-closed；
10. demo_full_chain cadquery case 可通过。
```

## 修改内容

`cadquery`：

```python
"stable_primitives": [
    "involute_spur_gear",
    "axisymmetric_turbine_disk",
],
"primitive_strategy": {
    "involute_spur_gear": "native_cadquery_primitive",
    "axisymmetric_turbine_disk": "native_cadquery_primitive",
},
```

`solidworks2025`：

```python
"stable_primitives": [
    "involute_spur_gear",
    "axisymmetric_turbine_disk",
],
"primitive_strategy": {
    "involute_spur_gear": "cadquery_step_import",
    "axisymmetric_turbine_disk": "cadquery_step_import",
},
```

`nx12`：

```python
"stable_primitives": [
    "involute_spur_gear",
    "axisymmetric_turbine_disk",
],
"primitive_strategy": {
    "involute_spur_gear": "cadquery_step_import",
    "axisymmetric_turbine_disk": "cadquery_step_import",
},
```

同时 caveats 增加：

```text
"Turbomachinery primitives are non-flight reference geometry only."
"Turbine disk primitives are imported via canonical STEP; native feature trees are not regenerated."
```

---

# 13. Phase 9：新增 demo case

## 文件

```text
integrations/engineering_tools/demo_full_chain.py
```

## 新增 metrics

```python
TURBINE_DISK_REQUIRED_METRICS = [
    "kernel_used",
    "reference_dimensions.outer_dia_mm",
    "reference_dimensions.bore_dia_mm",
    "reference_dimensions.axial_width_mm",
    "reference_dimensions.hub_outer_dia_mm",
    "reference_dimensions.web_outer_dia_mm",
    "reference_dimensions.rim_inner_dia_mm",
    "reference_dimensions.expected_through_hole_count",
]
```

## 新增 case

```python
def run_case_axisymmetric_turbine_disk(
    backend: str,
    output_root: Path,
    allow_step_import: bool = False,
) -> dict:
    params = {
        "outer_dia_mm": 480.0,
        "bore_dia_mm": 80.0,
        "axial_width_mm": 60.0,

        "hub_outer_dia_mm": 200.0,
        "web_outer_dia_mm": 340.0,
        "rim_inner_dia_mm": 400.0,

        "hub_width_mm": 60.0,
        "web_width_mm": 32.0,
        "rim_width_mm": 56.0,

        "hub_fillet_radius_mm": 0.0,
        "web_fillet_radius_mm": 0.0,
        "rim_fillet_radius_mm": 0.0,
        "edge_chamfer_mm": 0.0,

        "bolt_hole_count": 12,
        "bolt_pcd_mm": 140.0,
        "bolt_hole_dia_mm": 10.0,
        "bolt_hole_axis": "Z",

        "lightening_hole_count": 8,
        "lightening_hole_pcd_mm": 280.0,
        "lightening_hole_dia_mm": 24.0,
        "lightening_hole_axis": "Z",

        "cooling_hole_count": 24,
        "cooling_hole_pcd_mm": 430.0,
        "cooling_hole_dia_mm": 5.0,
        "cooling_hole_axis": "Z",

        "quality_grade": "concept_geometry",
        "non_flight_reference_only": True,
    }

    expected_through_hole_count = 1 + 12 + 8 + 24

    return _run_primitive_case(
        "axisymmetric_turbine_disk",
        backend,
        output_root,
        "axisymmetric_turbine_disk",
        params,
        "axisymmetric_turbine_disk.step",
        extra_validation={
            "expected_bbox_mm": [480.0, 480.0, 60.0],
            "expected_body_count": 1,
            "expected_through_hole_count": expected_through_hole_count,
            "tolerance_mm": 0.75,
            "primitive_validation": {
                "primitive1": {
                    "expected_kernel": "cadquery_axisymmetric_revolve_v0",
                    "expected_through_hole_count": expected_through_hole_count,
                }
            },
        },
        required_metrics=TURBINE_DISK_REQUIRED_METRICS,
        allow_step_import=allow_step_import,
    )
```

## 更新 case registry

```python
CASE_RUNNERS = {
    "box": run_case_box,
    "flanged_hub": run_case_flanged_hub,
    "involute_spur_gear": run_case_involute_spur_gear,
    "axisymmetric_turbine_disk": run_case_axisymmetric_turbine_disk,
}
```

## 更新 argparse choices

```python
choices=[
    "all",
    "box",
    "flanged_hub",
    "involute_spur_gear",
    "axisymmetric_turbine_disk",
]
```

## 验收命令

```bash
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery
python demo_full_chain.py --case axisymmetric_turbine_disk --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case axisymmetric_turbine_disk --backend nx12 --allow-step-import
```

如果 CI 环境没有 SolidWorks/NX，不要求真实通过 native import；但必须保证 cadquery 路径通过，SW/NX 在缺环境时不得伪造成功。

---

# 14. Phase 10：新增 skill contract

## 新增文件

```text
integrations/engineering_tools/.claude/skills/turbomachinery-cad-ir/SKILL.md
```

## 内容必须包括

````markdown
# Turbomachinery CAD-IR Skill

This skill only emits CAD-IR.

It must never generate:
- CadQuery scripts
- SolidWorks COM/VBS code
- NXOpen journals
- APDL code
- manufacturing instructions
- airworthiness/certification claims

Turbine disks and turbine blades are safety-critical rotating parts.

All turbomachinery primitives generated by this skill are non-flight reference geometry only.

Forbidden claims:
- flight-ready
- airworthy
- certified
- manufacturing-ready
- production-ready
- installable
- safe for operation

Reserved primitive names:
- axisymmetric_turbine_disk
- parametric_turbine_blade

The skill may emit `axisymmetric_turbine_disk` only when:
1. the primitive is registered;
2. the target backend supports the primitive;
3. a compiler handler exists;
4. a deterministic geometry kernel exists;
5. a mechanical validator exists;
6. all required parameters are present;
7. `quality_grade` is `concept_geometry` or `engineering_reference`;
8. `non_flight_reference_only` is true.

If required parameters are missing, return a missing-parameter diagnostic. Do not guess dimensions.

The skill must output CAD-IR using this shape:

```json
{
  "name": "axisymmetric_turbine_disk_demo",
  "units": "mm",
  "target_backend": ["cadquery"],
  "features": [
    {
      "id": "disk1",
      "type": "primitive",
      "primitive_name": "axisymmetric_turbine_disk",
      "operation": "new_body",
      "placement": {
        "origin_mm": [0.0, 0.0, 0.0],
        "axis": "Z"
      },
      "parameters": {
        "outer_dia_mm": 480.0,
        "bore_dia_mm": 80.0,
        "axial_width_mm": 60.0,
        "hub_outer_dia_mm": 200.0,
        "web_outer_dia_mm": 340.0,
        "rim_inner_dia_mm": 400.0,
        "hub_width_mm": 60.0,
        "web_width_mm": 32.0,
        "rim_width_mm": 56.0,
        "hub_fillet_radius_mm": 0.0,
        "web_fillet_radius_mm": 0.0,
        "rim_fillet_radius_mm": 0.0,
        "edge_chamfer_mm": 0.0,
        "bolt_hole_count": 12,
        "bolt_pcd_mm": 140.0,
        "bolt_hole_dia_mm": 10.0,
        "bolt_hole_axis": "Z",
        "lightening_hole_count": 8,
        "lightening_hole_pcd_mm": 280.0,
        "lightening_hole_dia_mm": 24.0,
        "lightening_hole_axis": "Z",
        "cooling_hole_count": 24,
        "cooling_hole_pcd_mm": 430.0,
        "cooling_hole_dia_mm": 5.0,
        "cooling_hole_axis": "Z",
        "quality_grade": "concept_geometry",
        "non_flight_reference_only": true
      }
    }
  ],
  "validation": {
    "expected_body_count": 1,
    "expected_bbox_mm": [480.0, 480.0, 60.0],
    "expected_through_hole_count": 45,
    "tolerance_mm": 0.75,
    "primitive_validation": {
      "disk1": {
        "expected_kernel": "cadquery_axisymmetric_revolve_v0",
        "expected_through_hole_count": 45
      }
    }
  }
}
````

````

---

# 15. Phase 11：测试矩阵

必须新增以下测试。不要只靠 demo。

## 15.1 Registry 测试

```text
tests/test_axisymmetric_turbine_disk_registry.py
````

必须覆盖：

```python
from seekflow_engineering_tools.geometry_primitives.registry import (
    get_primitive,
    list_primitive_names,
    backend_supports_primitive,
)


def test_axisymmetric_turbine_disk_registered():
    assert "axisymmetric_turbine_disk" in list_primitive_names()

    pd = get_primitive("axisymmetric_turbine_disk")
    assert pd is not None
    assert pd.category == "turbomachinery"
    assert "cadquery_axisymmetric_revolve_v0" in pd.supported_kernels


def test_axisymmetric_turbine_disk_backend_support():
    assert backend_supports_primitive("cadquery", "axisymmetric_turbine_disk")
    assert backend_supports_primitive("solidworks2025", "axisymmetric_turbine_disk")
    assert backend_supports_primitive("nx12", "axisymmetric_turbine_disk")
```

## 15.2 参数测试

```text
tests/test_axisymmetric_turbine_disk_parameters.py
```

覆盖：

```text
1. happy path normalize 成功；
2. 缺 required parameter 失败；
3. bore >= hub 失败；
4. hub >= web 失败；
5. rim_inner >= outer 失败；
6. non_flight_reference_only=False 失败；
7. quality_grade=flight_ready 失败；
8. bolt count > 0 但 pcd=0 失败；
9. count=0 但 pcd/dia 非 0 失败；
10. axis != Z 失败；
11. "False" 正确解析为 False 并被 validator 拒绝。
```

## 15.3 Compiler 测试

```text
tests/test_axisymmetric_turbine_disk_compiler.py
```

覆盖：

```python
from seekflow_engineering_tools.cadquery_backend.primitive_compiler import (
    list_primitive_compiler_names,
    compile_primitive_to_cadquery_script,
)
from seekflow_engineering_tools.ir.primitive import PrimitiveFeature


def test_axisymmetric_turbine_disk_compiler_registered():
    assert "axisymmetric_turbine_disk" in list_primitive_compiler_names()


def test_axisymmetric_turbine_disk_compiler_uses_kernel():
    feature = PrimitiveFeature(
        id="disk1",
        type="primitive",
        primitive_name="axisymmetric_turbine_disk",
        parameters={
            # use valid params fixture
        },
    )

    lines = compile_primitive_to_cadquery_script(feature)
    script = "\n".join(lines)

    assert "build_axisymmetric_turbine_disk_cadquery" in script
    assert 'PRIMITIVE_METADATA["axisymmetric_turbine_disk"]' in script
```

## 15.4 Metadata 测试

```text
tests/test_axisymmetric_turbine_disk_metadata.py
```

覆盖：

```text
1. generic metadata v1 happy path；
2. warnings 非 list 失败；
3. warnings item 非 str 失败；
4. turbine metadata 缺 radial_zones 失败；
5. turbine metadata 缺 safety 失败；
6. safety.not_airworthy 非 True 失败。
```

## 15.5 Mechanical validation 测试

```text
tests/test_axisymmetric_turbine_disk_mechanical_validation.py
```

覆盖：

```text
1. happy path ok；
2. metadata missing fail；
3. primitive mismatch fail；
4. kernel mismatch fail；
5. CAD-IR params 与 metadata params mismatch fail；
6. bbox mismatch fail；
7. body_count mismatch fail；
8. non_flight_reference_only False fail；
9. quality_grade invalid fail；
10. expected kernel mismatch fail。
```

## 15.6 Demo 测试

```text
tests/test_demo_full_chain_turbine_disk.py
```

覆盖：

```text
1. cadquery demo case 能返回 overall_ok=True；
2. metrics.kernel_used == cadquery_axisymmetric_revolve_v0；
3. metrics.reference_dimensions.outer_dia_mm 存在；
4. metrics.reference_dimensions.expected_through_hole_count 存在；
5. metadata stage 存在并 ok；
6. strategy None 时 choose_backend fail；
7. generic runner 不裁剪 reference_dimensions。
```

## 15.7 Skill contract 测试

```text
tests/test_turbomachinery_skill_contract.py
```

覆盖：

```python
from pathlib import Path


def test_turbomachinery_skill_exists():
    path = Path(".claude/skills/turbomachinery-cad-ir/SKILL.md")
    assert path.exists()


def test_turbomachinery_skill_contract_terms():
    text = Path(".claude/skills/turbomachinery-cad-ir/SKILL.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "only emits cad-ir" in text or "only output cad-ir" in text
    assert "never generate" in text
    assert "cadquery" in text
    assert "solidworks" in text
    assert "nxopen" in text
    assert "non-flight reference geometry" in text
    assert "axisymmetric_turbine_disk" in text
    assert "parametric_turbine_blade" in text
    assert "missing-parameter" in text
    assert "do not guess" in text
```

---

# 16. 验收命令

Claude Code 完成后必须执行：

```bash
cd integrations/engineering_tools
python -m pytest tests -q
```

重点单测：

```bash
python -m pytest tests/test_primitive_bool_normalization.py -q
python -m pytest tests/test_primitive_metadata_v1.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_registry.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_parameters.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_compiler.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_metadata.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_mechanical_validation.py -q
python -m pytest tests/test_demo_full_chain_turbine_disk.py -q
python -m pytest tests/test_turbomachinery_skill_contract.py -q
```

demo：

```bash
python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery
```

可选：

```bash
python demo_full_chain.py --case axisymmetric_turbine_disk --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case axisymmetric_turbine_disk --backend nx12 --allow-step-import
```

---

# 17. Definition of Done

本任务只有在满足以下全部条件时才算完成：

```text
1. list_primitive_names() 包含 axisymmetric_turbine_disk。
2. get_primitive("axisymmetric_turbine_disk") 返回 category=turbomachinery。
3. cadquery capability registry 支持 axisymmetric_turbine_disk。
4. solidworks2025/nx12 capability registry 仅通过 cadquery_step_import 支持 axisymmetric_turbine_disk。
5. normalize_primitive_parameters 能 normalize happy path 参数。
6. normalize_primitive_parameters 会拒绝 invalid geometry。
7. "False" 不会被 bool(value) 错解析为 True。
8. primitive compiler registry 包含 axisymmetric_turbine_disk。
9. compiler handler 只调用 deterministic kernel，不 inline 复杂几何。
10. deterministic kernel 能生成 STEP。
11. metadata sidecar 包含 primitive_metadata.axisymmetric_turbine_disk。
12. metadata 包含 primitive、metadata_version、kernel、parameters、reference_dimensions、warnings。
13. metadata 包含 radial_zones、profile_points、hole_patterns、safety。
14. malformed warnings 导致 metadata validation fail。
15. turbine-specific metadata 缺字段会 fail。
16. mechanical validator 已注册。
17. 未注册 mechanical validator 的 primitive 仍 fail-closed。
18. mechanical validation 检查 bbox、body count、params、reference_dimensions、kernel、safety flags。
19. demo_full_chain axisymmetric_turbine_disk cadquery case overall_ok=True。
20. demo metrics.reference_dimensions 保留完整字段，不裁剪为齿轮字段。
21. strategy None 时 choose_backend fail，不得 fallback。
22. 现有 involute_spur_gear case 不被破坏。
23. 现有 recipe cases 不被破坏。
24. skill contract 文件存在。
25. skill contract 明确禁止直接 CAD code 和 aviation/manufacturing claims。
```

---

# 18. 可直接交给 Claude Code 的最终 Prompt

下面是可以直接复制给 Claude Code 的完整任务指令。

```text
你现在在 GitHub 仓库 seekflow-engineering 中工作，重点目录是：

integrations/engineering_tools/

目标：
实现第一个 turbomachinery primitive：

primitive_name = "axisymmetric_turbine_disk"
kernel = "cadquery_axisymmetric_revolve_v0"

注意：这不是让你写一个孤立 CadQuery 脚本，而是要把它完整接入当前 SeekFlow Engineering primitive 体系：

CAD-IR
→ primitive registry
→ parameter normalization
→ primitive-specific validator
→ capability registry
→ backend strategy
→ CadQuery primitive compiler handler
→ deterministic kernel
→ STEP
→ metadata sidecar
→ generic metadata validation
→ turbine-specific metadata validation
→ mechanical validation
→ demo_full_chain
→ tests

最高优先级约束：
1. 不允许让 LLM 直接生成复杂 CadQuery 脚本。
2. 不允许生成 SolidWorks COM/VBS/NXOpen/APDL 几何代码。
3. 不允许实现真实航空发动机涡轮盘设计。
4. 不允许声称 flight-ready / airworthy / certified / manufacturing-ready / production-ready / installable。
5. 不允许做真实 fir-tree 榫槽。
6. 不允许做真实叶片连接。
7. 不允许做真实复杂冷却流道。
8. 不允许做材料、寿命、转速、强度、适航判断。
9. SolidWorks / NX 只能 import canonical STEP，不能重建涡轮盘几何。
10. 所有异常路径必须 fail-closed，不能 silent fallback。
11. 不要破坏现有 involute_spur_gear 行为。
12. 不要破坏现有 recipe 行为。
13. 不要大面积无关重构。
14. 不要重命名已有 public API，除非测试证明必须。

当前代码真实状态：
- CAD-IR 已支持 PrimitiveFeature。
- ValidationSpec 已支持 primitive_validation。
- geometry_primitives.registry 已支持 family module loader。
- turbomachinery.models 当前只是 reserved names，占位，TURBOMACHINERY_PRIMITIVES 为空。
- primitive_compiler 是 handler registry，目前只注册 involute_spur_gear。
- builder 已要求 primitive metadata sidecar。
- mechanical_validation.common 已有 primitive validator registry；未注册 validator 应 fail-closed。
- capabilities.registry 当前 stable_primitives 只有 involute_spur_gear。
- demo_full_chain 当前没有真正 generic _run_primitive_case，只有 gear case。
- demo_full_chain gear case 中有错误 fallback：get_primitive_strategy(...) or "native_cadquery_primitive"。
- demo_full_chain gear case 中 reference_dimensions 被裁剪为齿轮字段。
- primitive_metadata.validate_primitive_metadata_v1 中 warnings 非 list 只是 warning，应改为 error。
- registry.normalize_primitive_parameters 中 bool(value) 会把 "False" 错解析为 True，必须修。

请严格按以下阶段实施。

====================
Phase 0：基线保护
====================

进入目录：

cd integrations/engineering_tools

先运行：

python -m pytest tests -q

如果当前有已有失败，记录失败，不要擅自大改无关模块。

====================
Phase 1：修复 primitive infrastructure P0
====================

1. 修改：
src/seekflow_engineering_tools/geometry_primitives/registry.py

新增严格 bool parser：

def _parse_bool(value: object, pname: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y"}:
            return True
        if v in {"false", "0", "no", "n"}:
            return False
    raise ValueError(...)

将 bool normalization 从 bool(value) 改为 _parse_bool(value, pname)。

新增测试：
tests/test_primitive_bool_normalization.py

必须证明：
- "False" -> False
- "false" -> False
- "0" -> False
- "no" -> False
- "True" -> True
- "true" -> True
- "1" -> True
- "yes" -> True
- "maybe" raise ValueError

2. 修改：
src/seekflow_engineering_tools/mechanical_validation/primitive_metadata.py

将 warnings validation 改为：
- missing warnings -> normalized []
- warnings 非 list -> severity="error"
- warnings 中 item 非 str -> severity="error"
- 只有 list[str] 才通过

新增或更新测试：
tests/test_primitive_metadata_v1.py

必须证明 malformed warnings 会 result["ok"] is False。

3. 重构：
demo_full_chain.py

新增真正 generic primitive runner：

_run_primitive_case(...)

要求：
- 通过 engineering_validate_cad_ir 和 engineering_build_cad_model。
- strategy = get_primitive_strategy(backend, primitive_name)
- 如果 strategy is None，choose_backend stage fail，不能 fallback。
- 对 solidworks2025/nx12，如果没有 --allow-step-import，choose_backend fail。
- metadata sidecar 必须存在。
- metrics.reference_dimensions 必须保留完整 ref_dims，不得裁剪为齿轮字段。
- required_metrics 由具体 primitive case 传入。
- 现有 gear case 可改用 generic runner，但不得破坏齿轮测试。
- 如果不改 gear case，也必须让 axisymmetric_turbine_disk 使用 generic runner，并新增测试证明 strategy None fail 和 ref_dims 不被裁剪。

绝对禁止再写：
get_primitive_strategy(...) or "native_cadquery_primitive"

====================
Phase 2：注册 axisymmetric_turbine_disk primitive
====================

修改：
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py

注册 PrimitiveDefinition：

name="axisymmetric_turbine_disk"
category="turbomachinery"
supported_kernels=["cadquery_axisymmetric_revolve_v0"]
supported_backends=["cadquery", "solidworks2025", "nx12"]

参数固定为以下 30 个，不能新增、删减、改名：

outer_dia_mm
bore_dia_mm
axial_width_mm
hub_outer_dia_mm
web_outer_dia_mm
rim_inner_dia_mm
hub_width_mm
web_width_mm
rim_width_mm
hub_fillet_radius_mm
web_fillet_radius_mm
rim_fillet_radius_mm
edge_chamfer_mm
bolt_hole_count
bolt_pcd_mm
bolt_hole_dia_mm
bolt_hole_axis
lightening_hole_count
lightening_hole_pcd_mm
lightening_hole_dia_mm
lightening_hole_axis
cooling_hole_count
cooling_hole_pcd_mm
cooling_hole_dia_mm
cooling_hole_axis
quality_grade
non_flight_reference_only

默认：
quality_grade="concept_geometry"
non_flight_reference_only=True
所有 fillet/chamfer 默认 0.0
所有 hole_count 默认 0
所有 pcd/dia 默认 0.0
所有 hole_axis 默认 "Z"

quality_grade 只允许：
concept_geometry
engineering_reference

禁止：
flight_ready
airworthy
certified
manufacturing_ready
production_ready
installable

====================
Phase 3：实现参数 validator
====================

新增：
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/validator.py

实现：
validate_axisymmetric_turbine_disk_parameters(params: dict) -> list[str]

必须检查：
- quality_grade in {"concept_geometry", "engineering_reference"}
- non_flight_reference_only is True
- outer_dia_mm > 0
- bore_dia_mm >= 0
- axial_width_mm > 0
- bore_dia_mm < hub_outer_dia_mm < web_outer_dia_mm <= rim_inner_dia_mm < outer_dia_mm
- bore_dia_mm < 0.75 * hub_outer_dia_mm
- hub_width_mm > 0
- web_width_mm > 0
- rim_width_mm > 0
- hub_width_mm <= axial_width_mm
- web_width_mm <= axial_width_mm
- rim_width_mm <= axial_width_mm
- web_width_mm <= hub_width_mm
- web_width_mm <= rim_width_mm
- fillet/chamfer >= 0
- fillet/chamfer <= 0.2 * axial_width_mm

孔环规则：
对 bolt / lightening / cooling 三组都检查：
- count == 0 时 pcd_mm == 0 且 hole_dia_mm == 0
- count > 0 时 count >= 2
- count > 0 时 pcd_mm > 0
- count > 0 时 hole_dia_mm > 0
- axis 必须为 "Z"
- 孔不得侵入 inner zone
- 孔不得超出 outer zone
- chord spacing > 1.25 * hole_dia_mm

建议区域：
bolt: bore radius 到 hub outer radius
lightening: hub outer radius 到 rim inner radius
cooling: web outer radius 到 outer radius

接入：
src/seekflow_engineering_tools/geometry_primitives/registry.py

在 normalize_primitive_parameters() 中新增分支：

elif primitive_name == "axisymmetric_turbine_disk":
    from ...turbomachinery.validator import validate_axisymmetric_turbine_disk_parameters
    disk_errors = validate_axisymmetric_turbine_disk_parameters(normalized)
    if disk_errors:
        raise ValueError("Turbine disk validation failed: " + "; ".join(disk_errors))

====================
Phase 4：实现 deterministic CadQuery kernel
====================

新增：
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/axisymmetric_turbine_disk.py

实现：
build_axisymmetric_turbine_disk_cadquery(params: dict) -> tuple[object, dict]

约束：
- import cadquery 只能在函数内部。
- 不允许调用 LLM。
- 不允许随机。
- 不允许读外部 CAD 模板。
- 不允许真实安全/寿命/转速/适航判断。
- 返回 result, metadata。

几何：
- Z 为旋转轴。
- 原点为盘中心。
- 使用 XZ 半剖面 revolve。
- 中心孔由 profile 从 bore radius 开始自然形成。
- profile 点：
  (r_bore, -t_hub)
  (r_hub, -t_hub)
  (r_hub, -t_web)
  (r_web, -t_web)
  (r_rim_inner, -t_rim)
  (r_outer, -t_rim)
  (r_outer, t_rim)
  (r_rim_inner, t_rim)
  (r_web, t_web)
  (r_hub, t_web)
  (r_hub, t_hub)
  (r_bore, t_hub)

孔环：
- 使用 result.faces(">Z").workplane(centerOption="CenterOfBoundBox").polarArray(...).hole(...)
- bolt/lightening/cooling count=0 不生成孔
- count>0 生成 Z-axis through holes
- axis != "Z" raise ValueError

metadata 必须包含：
primitive="axisymmetric_turbine_disk"
metadata_version="primitive_metadata_v1"
kernel="cadquery_axisymmetric_revolve_v0"
parameters=dict(params)
reference_dimensions=dict
warnings=list[str]
radial_zones=dict
profile_points=list
hole_patterns=list
safety=dict

warnings 必须包含：
- non-flight reference geometry only
- not airworthy
- not certified
- not manufacturing-ready
- no real fir-tree slots / blade attachment / material / stress / life / cooling-flow validation

reference_dimensions 必须包含：
outer_dia_mm
bore_dia_mm
axial_width_mm
hub_outer_dia_mm
web_outer_dia_mm
rim_inner_dia_mm
hub_width_mm
web_width_mm
rim_width_mm
bolt_hole_count
lightening_hole_count
cooling_hole_count
expected_through_hole_count

expected_through_hole_count = 1 + bolt_hole_count + lightening_hole_count + cooling_hole_count

safety 必须包含：
non_flight_reference_only=True
not_for_manufacturing=True
not_airworthy=True
not_certified=True

如果 CadQuery revolve 的 bbox 不符合 [outer_dia, outer_dia, axial_width]，不要调大 tolerance 掩盖，必须修正建模坐标。

====================
Phase 5：实现 turbine-specific metadata validation
====================

新增：
src/seekflow_engineering_tools/geometry_primitives/turbomachinery/metadata.py

实现：
validate_axisymmetric_turbine_disk_metadata(metadata: dict) -> list[str]

必须检查：
- radial_zones 存在且为 dict
- radial_zones 包含 bore_radius_mm / hub_outer_radius_mm / web_outer_radius_mm / rim_inner_radius_mm / outer_radius_mm
- profile_points 存在且为 list，长度 >= 4
- hole_patterns 存在且为 list
- hole_patterns 包含 bolt/lightening/cooling 三个 name
- safety 存在且为 dict
- safety.non_flight_reference_only is True
- safety.not_for_manufacturing is True
- safety.not_airworthy is True
- safety.not_certified is True

修改：
src/seekflow_engineering_tools/cadquery_backend/builder.py

扩展 _assert_primitive_specific_metadata：

elif pname == "axisymmetric_turbine_disk":
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.metadata import (
        validate_axisymmetric_turbine_disk_metadata,
    )
    errors = validate_axisymmetric_turbine_disk_metadata(primitive_entry)
    if errors:
        raise ValueError("Turbine disk metadata validation failed: " + "; ".join(errors))

不要删除齿轮 is_standard_involute 检查。

====================
Phase 6：实现 CadQuery compiler handler
====================

修改：
src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py

新增 _compile_axisymmetric_turbine_disk(feature) -> list[str]

它只能生成对 deterministic kernel 的调用：

from seekflow_engineering_tools.geometry_primitives.turbomachinery.axisymmetric_turbine_disk import (
    build_axisymmetric_turbine_disk_cadquery,
)

result, PRIMITIVE_METADATA["axisymmetric_turbine_disk"] = (
    build_axisymmetric_turbine_disk_cadquery(_params)
)

BUILD_WARNINGS.extend(
    PRIMITIVE_METADATA["axisymmetric_turbine_disk"].get("warnings", [])
)

注册：
register_primitive_compiler("axisymmetric_turbine_disk", _compile_axisymmetric_turbine_disk)

禁止：
- 不要在 compiler 中 inline 几何。
- 不要使用 fallback。
- 不要吞掉 kernel exception。

====================
Phase 7：实现 mechanical validation
====================

新增：
src/seekflow_engineering_tools/mechanical_validation/turbomachinery_validation.py

实现：
validate_axisymmetric_turbine_disk_result(
    params: dict,
    inspection: dict,
    metadata: dict | None = None,
    tolerance_mm: float = 0.5,
    expected: dict | None = None,
    raw_metadata: dict | None = None,
) -> dict

返回：
{
  "ok": bool,
  "primitive": "axisymmetric_turbine_disk",
  "issues": list[dict],
  "reference_dimensions": dict,
  "kernel": str,
}

必须 fail-closed 检查：
- metadata missing -> error
- metadata.primitive mismatch -> error
- metadata.kernel != "cadquery_axisymmetric_revolve_v0" -> error
- params.non_flight_reference_only is not True -> error
- quality_grade not allowed -> error
- metadata.safety flags 不完整 -> error
- metadata.parameters 与 CAD-IR params 不一致 -> error
- metadata.reference_dimensions 与 expected reference dimensions 不一致 -> error
- inspection.bbox_mm missing -> error
- bbox x/y 与 outer_dia_mm 超 tolerance -> error
- bbox z 与 axial_width_mm 超 tolerance -> error
- solid_count/body_count missing -> error
- body_count != 1 -> error
- expected.expected_kernel mismatch -> error
- expected.expected_through_hole_count mismatch -> error

修改：
src/seekflow_engineering_tools/mechanical_validation/common.py

注册：
register_primitive_mechanical_validator(
    "axisymmetric_turbine_disk",
    _validate_axisymmetric_turbine_disk_feature,
)

不要破坏 involute_spur_gear validator registration。

====================
Phase 8：capability registry 接入
====================

修改：
src/seekflow_engineering_tools/capabilities/registry.py

在 cadquery 中加入：
stable_primitives: "axisymmetric_turbine_disk"
primitive_strategy: "axisymmetric_turbine_disk": "native_cadquery_primitive"

在 solidworks2025 中加入：
stable_primitives: "axisymmetric_turbine_disk"
primitive_strategy: "axisymmetric_turbine_disk": "cadquery_step_import"

在 nx12 中加入：
stable_primitives: "axisymmetric_turbine_disk"
primitive_strategy: "axisymmetric_turbine_disk": "cadquery_step_import"

caveats 增加：
- Turbomachinery primitives are non-flight reference geometry only.
- Turbine disk primitives are imported via canonical STEP; native feature trees are not regenerated.

====================
Phase 9：demo_full_chain 新增 case
====================

修改：
demo_full_chain.py

新增：
TURBINE_DISK_REQUIRED_METRICS = [
    "kernel_used",
    "reference_dimensions.outer_dia_mm",
    "reference_dimensions.bore_dia_mm",
    "reference_dimensions.axial_width_mm",
    "reference_dimensions.hub_outer_dia_mm",
    "reference_dimensions.web_outer_dia_mm",
    "reference_dimensions.rim_inner_dia_mm",
    "reference_dimensions.expected_through_hole_count",
]

新增：
run_case_axisymmetric_turbine_disk(...)

使用参数：
outer_dia_mm=480.0
bore_dia_mm=80.0
axial_width_mm=60.0
hub_outer_dia_mm=200.0
web_outer_dia_mm=340.0
rim_inner_dia_mm=400.0
hub_width_mm=60.0
web_width_mm=32.0
rim_width_mm=56.0
hub_fillet_radius_mm=0.0
web_fillet_radius_mm=0.0
rim_fillet_radius_mm=0.0
edge_chamfer_mm=0.0
bolt_hole_count=12
bolt_pcd_mm=140.0
bolt_hole_dia_mm=10.0
bolt_hole_axis="Z"
lightening_hole_count=8
lightening_hole_pcd_mm=280.0
lightening_hole_dia_mm=24.0
lightening_hole_axis="Z"
cooling_hole_count=24
cooling_hole_pcd_mm=430.0
cooling_hole_dia_mm=5.0
cooling_hole_axis="Z"
quality_grade="concept_geometry"
non_flight_reference_only=True

expected_bbox_mm=[480.0, 480.0, 60.0]
expected_body_count=1
expected_through_hole_count=45
tolerance_mm=0.75
primitive_validation["primitive1"]["expected_kernel"]="cadquery_axisymmetric_revolve_v0"
primitive_validation["primitive1"]["expected_through_hole_count"]=45

加入 CASE_RUNNERS。
加入 argparse choices。
更新 usage docstring。

====================
Phase 10：新增 turbomachinery skill contract
====================

新增：
.claude/skills/turbomachinery-cad-ir/SKILL.md

必须声明：
- only emits CAD-IR
- never generate CadQuery scripts
- never generate SolidWorks COM/VBS
- never generate NXOpen
- never generate APDL
- turbine disks/blades are safety-critical rotating parts
- non-flight reference geometry only
- forbidden claims: flight-ready, airworthy, certified, manufacturing-ready, production-ready, installable
- reserved primitive names: axisymmetric_turbine_disk, parametric_turbine_blade
- only emit axisymmetric_turbine_disk if primitive/backend/compiler/kernel/mechanical validator/required params exist
- missing parameters -> missing-parameter diagnostic
- do not guess dimensions

====================
Phase 11：测试
====================

新增测试文件：

tests/test_primitive_bool_normalization.py
tests/test_axisymmetric_turbine_disk_registry.py
tests/test_axisymmetric_turbine_disk_parameters.py
tests/test_axisymmetric_turbine_disk_compiler.py
tests/test_axisymmetric_turbine_disk_metadata.py
tests/test_axisymmetric_turbine_disk_mechanical_validation.py
tests/test_demo_full_chain_turbine_disk.py
tests/test_turbomachinery_skill_contract.py

必要时更新：
tests/test_primitive_metadata_v1.py
tests/test_primitive_compiler_registry.py
tests/test_primitive_mechanical_validation_dispatch.py

测试要求：
1. axisymmetric_turbine_disk 已注册。
2. capabilities 支持 cadquery/native_cadquery_primitive。
3. capabilities 支持 solidworks2025/nx12 cadquery_step_import。
4. 参数 happy path normalize 成功。
5. invalid diameter ordering fail。
6. non_flight_reference_only=False fail。
7. quality_grade=flight_ready fail。
8. count=0 但 pcd/dia 非 0 fail。
9. count>0 但 pcd/dia 为 0 fail。
10. axis != Z fail。
11. "False" 不会被解析成 True。
12. compiler registered。
13. compiler script 调用 deterministic kernel。
14. metadata v1 happy path。
15. malformed warnings fail。
16. turbine-specific metadata 缺字段 fail。
17. mechanical validator happy path ok。
18. metadata missing fail。
19. kernel mismatch fail。
20. bbox mismatch fail。
21. params mismatch fail。
22. strategy None fail。
23. generic primitive runner 不裁剪 reference_dimensions。
24. demo cadquery case overall_ok=True。
25. 现有 gear case 不破坏。

====================
Phase 12：验收命令
====================

运行：

cd integrations/engineering_tools
python -m pytest tests -q

单独运行：

python -m pytest tests/test_primitive_bool_normalization.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_registry.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_parameters.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_compiler.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_metadata.py -q
python -m pytest tests/test_axisymmetric_turbine_disk_mechanical_validation.py -q
python -m pytest tests/test_demo_full_chain_turbine_disk.py -q
python -m pytest tests/test_turbomachinery_skill_contract.py -q

demo：

python demo_full_chain.py --case axisymmetric_turbine_disk --backend cadquery

可选环境具备时：

python demo_full_chain.py --case axisymmetric_turbine_disk --backend solidworks2025 --allow-step-import
python demo_full_chain.py --case axisymmetric_turbine_disk --backend nx12 --allow-step-import

完成后请输出：
1. 修改文件清单；
2. 新增文件清单；
3. 测试运行结果；
4. demo 运行结果；
5. 若有任何测试失败，说明失败原因，不要声称完成。
```

---

这版的核心取向是：**先把当前仍偏齿轮专用的 demo/metadata/bool/fail-closed 小问题修干净，再进入涡轮盘 primitive。**这样 Claude Code 实现出来的不会只是“能出 STEP 的几何脚本”，而是能进入你这个工程工具链的正式 primitive。

[1]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/demo_full_chain.py "seekflow-engineering/integrations/engineering_tools/demo_full_chain.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/ir/cad.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/ir/primitive.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/base.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/registry.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/primitive_compiler.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/common.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/backend_builders.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/geometry_primitives/turbomachinery/models.py "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/capabilities/registry.py "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/mechanical_validation/primitive_metadata.py "raw.githubusercontent.com"
