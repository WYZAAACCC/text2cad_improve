

# SeekFlow Engineering 自然语言精确建模修复实施文档 v3

## 0. 当前代码审计结论

仓库已经比上一版多了一些目录，包括 `ir`、`recipes`、`capabilities`、`cadquery_backend`、`natural_language`、`inspection`、`repair`，说明 Claude Code 之前可能生成了部分脚手架。`ir` 目录已经存在 `cad.py`、`cae.py`、`defaults.py`、`validation.py`；`recipes` 目录也已有 `base.py`、`mechanical.py`、`registry.py`；`cadquery_backend` 也已有 `compiler.py`、`inspector.py`、`recipes.py`、`tools.py`。([GitHub][1])

但是，**这些模块目前没有真正接入主工具注册链，也没有形成可执行闭环**。`registry.py` 仍然只注册 SolidWorks、NX、ANSYS 工具，没有注册 CadQuery 工具、自然语言工具、inspection 工具或 CAD-IR 工具；搜索 `build_cadquery_tools`、`build_natural_language_tools` 在 registry 中没有匹配。([GitHub][2])

`natural_language/tools.py` 里虽然已经有 `engineering_validate_cad_ir` 和 `engineering_build_cad_model`，但它们是普通 Python 函数，不是 SeekFlow tool，也没有 `build_natural_language_tools`。更严重的是，当前 `engineering_build_cad_model` 对 CadQuery 只编译脚本并声称输出了 `out_step`，但没有真正执行脚本、没有真正创建文件；对 SolidWorks/NX 只是返回“请直接用 solidworks_create_* / nx_create_* 工具”，没有执行构建。([GitHub][3])

`.claude/skills` 目前仍不存在，访问 `.claude/skills` 返回 404。测试目录也仍然只有旧的 5 个测试，没有 CAD-IR、recipe、capability、CadQuery、自然语言建模、inspection、repair 的测试。

所以当前状态是：

```text
已有脚手架 ≠ 已有架构
已有 compiler ≠ 能真正建模
已有 natural_language 函数 ≠ LLM 能调用的工具
已有 CAD-IR ≠ 已完成 schema/recipe/backend/inspect/validation 闭环
```

---

# 1. 必须达到的最终架构

Claude Code 必须把系统修成下面这条链：

```text
用户自然语言 / 结构化 NL-CAD 输入
        ↓
engineering_validate_cad_ir
        ↓
CADPartSpec / CAEJobSpec
        ↓
Recipe Registry 校验
        ↓
Capability Registry 路由
        ↓
engineering_build_cad_model
        ↓
backend builder:
  - cadquery backend：真实生成 STEP
  - solidworks backend：真实生成 SLDPRT/STEP
  - nx backend：真实提交 bridge job 并生成 PRT/STEP
  - ansys backend：真实运行 APDL template
        ↓
inspection:
  - bbox
  - volume
  - body_count
  - feature / hole estimates
        ↓
validation:
  - expected_bbox_mm
  - expected_body_count
  - expected_hole_count
  - expected_through_hole_count
        ↓
EngineeringActionResult
        ↓
repair diagnostics
```

**不得只生成脚本。不得只返回“路由到某后端”。不得在没有文件生成的情况下返回 `ok=True`。**

---

# 2. 非协商验收标准

下面这些是硬性要求。Claude Code 不能选择性忽略。

## 2.1 工具必须真正注册

`build_engineering_tools(config)` 返回的工具列表中必须包含：

```text
engineering_validate_cad_ir
engineering_build_cad_model
cadquery_build_from_cad_ir
cadquery_compile_cad_ir_to_script
cadquery_inspect_step
solidworks_create_flanged_hub_part
solidworks_create_spur_gear_part
nx_create_block_with_hole
nx_create_l_bracket
nx_create_stepped_block
ansys_list_apdl_templates
```

当前 registry 只注册 SolidWorks、NX、ANSYS，这是不合格状态，必须修。([GitHub][2])

## 2.2 `engineering_build_cad_model` 必须真实执行

禁止以下行为：

```python
return ok=True, files_created=["xxx.step"]
```

但文件没有创建。

必须：

1. 生成或路由到后端。
2. 后端真实执行。
3. 检查输出文件存在。
4. 检查输出文件大小大于 0。
5. inspect。
6. validation。
7. 只有全部通过才返回 `ok=True`。

## 2.3 CadQuery backend 必须成为最小可运行 fallback

无 SolidWorks、NX、ANSYS 环境时，CI 仍然必须能用 CadQuery 后端完成：

```text
CAD-IR → STEP 文件 → inspect → validation
```

当前 `cadquery_backend/tools.py` 只提供 compile 和 inspect，没有 build tool；`engineering_build_cad_model` 也没有真正执行 CadQuery 脚本。必须修。([GitHub][4])

## 2.4 所有输出路径必须限制在 workspace 内

所有工具都必须使用：

```python
ensure_inside_workspace(...)
ensure_extension(...)
assert_file_created(...)
```

`common.paths` 已经有 `ensure_inside_workspace` 和 `ensure_extension`，必须统一使用。([GitHub][5])

## 2.5 不允许静默失败

SolidWorks、NX、ANSYS、CadQuery 任一后端失败，都不得返回 `ok=True`。

当前 SolidWorks `com_client.py` 仍有 `return True  # best-effort`、`subprocess.run(...)` 不检查结果、VBS 使用大量 `On Error Resume Next` 的问题。必须修。([GitHub][6])

## 2.6 所有新增能力必须有测试

必须新增测试，不允许只改源码。

至少新增：

```text
test_cad_ir_schema.py
test_recipe_registry.py
test_capability_registry.py
test_cadquery_backend.py
test_engineering_build_cad_model.py
test_natural_language_tools_registered.py
test_solidworks_recipe_tools_mock.py
test_nx_recipe_tools_mock.py
test_nx_heartbeat.py
test_ansys_template_registry.py
test_ansys_template_validation.py
test_inspection_validation.py
```

当前测试目录仍只有旧 5 个测试，覆盖严重不足。([GitHub][7])

---

# 3. 修复任务总览

Claude Code 必须按下面顺序实现，不要跳跃。

```text
P0：让已有工具真实可靠
  1. 修 registry，把新工具接入
  2. 修 natural_language tools，使其成为真正工具并真实执行
  3. 修 CadQuery backend，使其能真实 build
  4. 修路径、安全、文件存在校验
  5. 修 SolidWorks 静默失败
  6. 修 NX heartbeat、STEP export、文件校验
  7. 修 ANSYS 参数校验和 parser

P1：让 CAD-IR / Recipe / Capability 真正参与执行
  8. 强化 CAD-IR validators
  9. 强化 recipe registry schema 校验
  10. 强化 capability routing
  11. 让 engineering_validate_cad_ir 调用 recipe/capability 校验

P2：形成闭环
  12. inspection + validation 接入 build
  13. repair diagnostics 接入失败返回
  14. 增加 .claude/skills
  15. 增加完整 pytest
```

---

# 4. P0-1：修复主工具注册链

## 4.1 修改文件

```text
src/seekflow_engineering_tools/registry.py
```

当前只注册：

```python
build_solidworks_tools
build_nx_tools
build_ansys_tools
```

必须新增：

```python
build_cadquery_tools
build_natural_language_tools
```

## 4.2 必须实现

```python
from seekflow_engineering_tools.cadquery_backend.tools import build_cadquery_tools
from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools
```

然后：

```python
def build_engineering_tools(config: EngineeringToolsConfig | None = None) -> list:
    config = config or EngineeringToolsConfig.from_env()

    tools = []

    tools.extend(build_natural_language_tools(config))
    tools.extend(build_cadquery_tools(config))

    if config.solidworks.enabled:
        tools.extend(build_solidworks_tools(config))

    if config.nx.enabled:
        tools.extend(build_nx_tools(config))

    if config.ansys.enabled:
        tools.extend(build_ansys_tools(config))

    return tools
```

## 4.3 Capability 也要补

`ENGINEERING_CAPABILITIES` 当前只有 filesystem、SolidWorks、NX、ANSYS。必须加入：

```python
"cad.ir.read": "Read CAD-IR model specs.",
"cad.ir.write": "Write normalized CAD-IR model specs.",
"cad.cadquery.read": "Read CadQuery-generated CAD files.",
"cad.cadquery.write": "Generate CAD models using CadQuery fallback.",
"cad.generic.inspect": "Inspect CAD model geometry.",
"cad.generic.validate": "Validate CAD model geometry against expectations.",
```

## 4.4 验收测试

新增：

```python
def test_engineering_tools_register_natural_language_and_cadquery():
    from seekflow_engineering_tools.registry import build_engineering_tools
    from seekflow_engineering_tools.config import EngineeringToolsConfig

    config = EngineeringToolsConfig.from_env()
    tools = build_engineering_tools(config)
    names = {t.name for t in tools}

    assert "engineering_validate_cad_ir" in names
    assert "engineering_build_cad_model" in names
    assert "cadquery_build_from_cad_ir" in names
    assert "cadquery_compile_cad_ir_to_script" in names
    assert "cadquery_inspect_step" in names
```

---

# 5. P0-2：把 `natural_language/tools.py` 改成真正工具

## 5.1 当前问题

当前 `engineering_validate_cad_ir` 和 `engineering_build_cad_model` 是普通函数，不是 SeekFlow tool；没有 `build_natural_language_tools`。并且 `engineering_build_cad_model` 对 CadQuery 只编译脚本，不执行；对 SolidWorks/NX 只返回“请调用别的工具”。([GitHub][3])

## 5.2 必须修改

文件：

```text
src/seekflow_engineering_tools/natural_language/tools.py
```

必须新增：

```python
from seekflow_tools import ToolPolicy, tool
```

并实现：

```python
def build_natural_language_tools(config: EngineeringToolsConfig) -> list:
    @tool(
        name="engineering_validate_cad_ir",
        description=(
            "Validate and normalize a CAD-IR JSON spec before building a CAD model. "
            "This checks schema, recipe parameters, backend support, units, and validation expectations."
        ),
        policy=ToolPolicy(
            capabilities=["cad.ir.read", "cad.ir.write"],
            filesystem_roots=[str(config.workspace_root)],
            network=False,
            subprocess=False,
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def engineering_validate_cad_ir_tool(spec: dict) -> dict:
        return engineering_validate_cad_ir(spec)

    @tool(
        name="engineering_build_cad_model",
        description=(
            "Build a CAD model from validated CAD-IR using a selected backend. "
            "Supports cadquery fallback and selected SolidWorks/NX recipes. "
            "Always creates real output files and validates them before returning ok=true."
        ),
        policy=ToolPolicy(
            capabilities=[
                "cad.ir.read",
                "cad.cadquery.write",
                "cad.generic.inspect",
                "cad.generic.validate",
                "cad.solidworks.write",
                "cad.nx.write",
            ],
            filesystem_roots=[str(config.workspace_root)],
            network=False,
            subprocess=True,
        ),
        cache=False,
        sanitize=True,
        trusted=False,
    )
    def engineering_build_cad_model_tool(
        spec: dict,
        backend: str = "cadquery",
        out_native: str | None = None,
        out_step: str | None = None,
        inspect: bool = True,
        allow_fallback: bool = True,
    ) -> dict:
        return engineering_build_cad_model(
            spec=spec,
            backend=backend,
            out_native=out_native,
            out_step=out_step,
            inspect=inspect,
            allow_fallback=allow_fallback,
            config=config,
        )

    return [
        engineering_validate_cad_ir_tool,
        engineering_build_cad_model_tool,
    ]
```

## 5.3 `engineering_build_cad_model` 必须真实执行

函数签名改为：

```python
def engineering_build_cad_model(
    spec: dict,
    backend: str,
    out_native: str | None = None,
    out_step: str | None = None,
    inspect: bool = True,
    allow_fallback: bool = True,
    config: EngineeringToolsConfig | None = None,
) -> dict:
```

必须执行：

```python
cad_spec = CADPartSpec.model_validate(spec)
validate_recipe_features(cad_spec)
backend = choose_backend(cad_spec, preferred=[backend])
```

路由逻辑必须是：

```python
if backend == "cadquery":
    return build_cadquery_from_cad_ir(...)

if backend == "solidworks2025":
    return build_solidworks_from_cad_ir(...)

if backend == "nx12":
    return build_nx_from_cad_ir(...)

if unsupported and allow_fallback:
    return build_cadquery_from_cad_ir(..., warnings=["Fell back from ..."])
```

禁止：

```python
return ok=True, warnings=["Use solidworks tools directly"]
```

这种返回必须删除。

---

# 6. P0-3：实现真正的 CadQuery build backend

## 6.1 当前问题

`cadquery_backend/tools.py` 目前只有 `cadquery_compile_cad_ir_to_script` 和 `cadquery_inspect_step`，没有 `cadquery_build_from_cad_ir`。而且 `cadquery_inspect_step` 直接使用 `Path(step_path)`，没有走 `ensure_inside_workspace`；ToolPolicy 还错误使用了 `cad.solidworks.read`。([GitHub][4])

## 6.2 新增文件

```text
src/seekflow_engineering_tools/cadquery_backend/builder.py
```

## 6.3 必须实现

```python
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_inside_workspace, ensure_extension
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.ir.cad import CADPartSpec
from seekflow_engineering_tools.cadquery_backend.compiler import compile_cad_ir_to_cadquery_script
from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
from seekflow_engineering_tools.inspection.validation import validate_inspection_against_spec


def assert_file_created(path: Path, label: str, min_size: int = 1) -> None:
    if not path.exists():
        raise RuntimeError(f"{label} was not created: {path}")
    if path.stat().st_size < min_size:
        raise RuntimeError(f"{label} is empty or too small: {path}")


def build_cadquery_from_cad_ir(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_step: str,
    inspect: bool = True,
    script_out: str | None = None,
) -> dict:
    workspace = config.workspace_root

    out_step_path = ensure_inside_workspace(workspace, out_step)
    ensure_extension(out_step_path, {".step", ".stp"})

    if script_out:
        script_path = ensure_inside_workspace(workspace, script_out)
        ensure_extension(script_path, {".py"})
    else:
        script_path = out_step_path.with_suffix(".cadquery_build.py")

    script = compile_cad_ir_to_cadquery_script(spec, out_step=str(out_step_path))
    script_path.write_text(script, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=120,
    )

    if proc.returncode != 0:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_from_cad_ir",
            files_created=[str(script_path)],
            stdout_tail=(proc.stdout or "")[-4000:],
            stderr_tail=(proc.stderr or "")[-4000:],
            error=f"CadQuery build failed with exit code {proc.returncode}",
        ).model_dump()

    try:
        assert_file_created(out_step_path, "STEP file")
    except Exception as exc:
        return EngineeringActionResult(
            ok=False,
            software="cadquery",
            action="build_from_cad_ir",
            files_created=[str(script_path)],
            stdout_tail=(proc.stdout or "")[-4000:],
            stderr_tail=(proc.stderr or "")[-4000:],
            error=str(exc),
        ).model_dump()

    metrics = {
        "step_path": str(out_step_path),
        "script_path": str(script_path),
    }
    warnings = []

    if inspect:
        inspection = inspect_step_with_cadquery(out_step_path)
        report = validate_inspection_against_spec(inspection, spec)

        metrics["inspection"] = inspection.model_dump() if hasattr(inspection, "model_dump") else inspection
        metrics["validation"] = report.model_dump() if hasattr(report, "model_dump") else report

        if not report.ok:
            return EngineeringActionResult(
                ok=False,
                software="cadquery",
                action="build_from_cad_ir",
                files_created=[str(out_step_path), str(script_path)],
                stdout_tail=(proc.stdout or "")[-4000:],
                stderr_tail=(proc.stderr or "")[-4000:],
                metrics=metrics,
                warnings=warnings,
                error="CAD validation failed",
            ).model_dump()

    return EngineeringActionResult(
        ok=True,
        software="cadquery",
        action="build_from_cad_ir",
        files_created=[str(out_step_path), str(script_path)],
        stdout_tail=(proc.stdout or "")[-4000:],
        stderr_tail=(proc.stderr or "")[-4000:],
        metrics=metrics,
        warnings=warnings,
    ).model_dump()
```

## 6.4 修改 `cadquery_backend/tools.py`

新增 tool：

```python
@tool(
    name="cadquery_build_from_cad_ir",
    description=(
        "Build a real STEP model from CAD-IR using CadQuery. "
        "This executes a deterministic CadQuery script, checks that files exist, "
        "inspects geometry, and validates it against CAD-IR expectations."
    ),
    policy=ToolPolicy(
        capabilities=["cad.cadquery.write", "cad.generic.inspect", "cad.generic.validate"],
        filesystem_roots=[str(config.workspace_root)],
        network=False,
        subprocess=True,
    ),
    cache=False,
    sanitize=True,
    trusted=False,
)
def cadquery_build_from_cad_ir(
    spec: dict,
    out_step: str,
    inspect: bool = True,
    script_out: str | None = None,
) -> dict:
    cad_spec = CADPartSpec.model_validate(spec)
    return build_cadquery_from_cad_ir(
        spec=cad_spec,
        config=config,
        out_step=out_step,
        inspect=inspect,
        script_out=script_out,
    )
```

## 6.5 修复 tool policy

把当前错误的：

```python
capabilities=["cad.solidworks.read"]
```

改为：

```python
capabilities=["cad.cadquery.read", "cad.generic.inspect"]
```

---

# 7. P0-4：修复 CadQuery compiler

## 7.1 当前问题

`cadquery_backend/compiler.py` 已经有 `_compile_recipe`、`_compile_extrude`、`_compile_hole`、`_compile_circular_pattern_holes`，但 `_compile_extrude` 实际假设 profile 一定是 rectangle；`_compile_hole` 忽略 `through_all`、`depth_mm`、`axis`；整个 compiler 只返回脚本，不负责执行，这一点由 builder 解决。([GitHub][8])

## 7.2 必须修复

`_compile_extrude` 必须支持：

```text
rectangle
circle
polygon
```

示例：

```python
def _compile_profile(profile) -> list[str]:
    if profile.type == "rectangle":
        return [f".rect({float(profile.width_mm)}, {float(profile.height_mm)})"]
    if profile.type == "circle":
        return [f".circle({float(profile.diameter_mm) / 2.0})"]
    if profile.type == "polygon":
        pts = [(float(x), float(y)) for x, y in profile.points_mm]
        return [f".polyline({pts}).close()"]
    raise CadQueryCompileError(...)
```

`_compile_extrude` 必须处理 `operation`：

```python
if result is None:
    result = cq.Workplane("XY").rect(...).extrude(depth)
elif operation == "add":
    result = result.union(cq.Workplane("XY").rect(...).extrude(depth))
elif operation == "cut":
    result = result.cut(cq.Workplane("XY").rect(...).extrude(depth))
```

第一版允许简化，但必须明确支持当前 recipe/golden test 所需的 feature，不得让 circle extrude 崩。

## 7.3 `hole` 必须处理 depth

```python
if feature.through_all:
    ".hole(diameter)"
else:
    ".hole(diameter, depth=depth_mm)"
```

如果 `axis != "Z"`，第一版可以拒绝：

```python
raise CadQueryCompileError("CadQuery v1 hole compiler only supports Z-axis holes")
```

不得静默忽略。

---

# 8. P0-5：强化 CAD-IR schema

## 8.1 当前问题

`ir/cad.py` 已有 CADPartSpec、features、ValidationSpec，但仍缺少大量数值约束。虽然 LengthUnit 允许 `"mm", "m", "inch"`，model validator 又拒绝非 mm，这可以保留，但应明确错误信息。当前没有充分限制孔径、深度、count、bbox 长度、位置长度、额外字段等。([GitHub][1])

## 8.2 必须修改

所有 Pydantic model 加：

```python
from pydantic import ConfigDict

model_config = ConfigDict(extra="forbid")
```

关键字段加约束：

```python
from pydantic import Field

diameter_mm: float = Field(gt=0)
depth_mm: float = Field(gt=0)
count: int = Field(ge=1)
radius_mm: float = Field(gt=0)
```

`CircularPatternHolesFeature.count` 必须：

```python
count: int = Field(ge=2)
```

机械螺栓孔 recipe 中由 recipe registry 限制 `bolt_count >= 3`。

`ValidationSpec.expected_bbox_mm` 必须验证长度为 3：

```python
@model_validator(mode="after")
def validate_bbox(self):
    if self.expected_bbox_mm is not None and len(self.expected_bbox_mm) != 3:
        raise ValueError("expected_bbox_mm must contain exactly 3 values")
    return self
```

`HoleFeature.position_mm` 必须长度 2 或 3。第一版只支持 Z 向孔时，建议强制长度 2：

```python
if len(self.position_mm) not in (2, 3):
    raise ValueError("position_mm must contain 2 or 3 values")
```

## 8.3 RecipeFeature 必须校验 recipe 参数

`CADPartSpec.model_validate` 只能校验语法，不知道 recipe 参数是否完整。因此需要：

```python
def validate_cad_part_semantics(spec: CADPartSpec) -> list[ValidationIssue]:
    ...
```

放在：

```text
src/seekflow_engineering_tools/ir/validation.py
```

它必须调用 recipe registry：

```python
validate_recipe_parameters(feature.recipe_name, feature.parameters)
```

`engineering_validate_cad_ir` 必须调用它。

---

# 9. P0-6：Recipe Registry 必须真校验

## 9.1 当前目标

`recipes` 不是摆设。它必须用于：

1. 校验 recipe 是否存在。
2. 校验参数是否完整。
3. 校验类型。
4. 校验 min/max。
5. 给 capability routing 提供支持矩阵。
6. 给 compiler/backend 确定 recipe build 方式。

## 9.2 必须实现

文件：

```text
src/seekflow_engineering_tools/recipes/registry.py
```

必须提供：

```python
def list_recipe_names() -> list[str]: ...

def get_recipe(name: str) -> RecipeDefinition: ...

def validate_recipe_parameters(recipe_name: str, parameters: dict) -> dict:
    ...
```

`validate_recipe_parameters` 必须：

```python
unknown = set(parameters) - known
if unknown:
    raise ValueError(f"Unknown parameters for recipe {recipe_name}: {sorted(unknown)}")
```

必须类型转换：

```python
float -> float(value)
int -> int(value)
str -> str(value)
bool -> bool(value)
```

必须检查：

```python
min_value
max_value
required
```

## 9.3 必须注册的 recipe

```text
box
cylinder
block_with_hole
l_bracket
stepped_block
flanged_hub
spur_gear
shaft_basic
shaft_with_keyway
```

其中第一版至少要能 build：

```text
cadquery:
  box
  cylinder
  block_with_hole
  l_bracket
  stepped_block
  flanged_hub
  spur_gear

solidworks2025:
  box
  flanged_hub
  spur_gear

nx12:
  box
  block_with_hole
  l_bracket
  stepped_block
```

---

# 10. P0-7：Capability Registry 必须参与路由

## 10.1 当前目标

`capabilities/capability_registry.yaml` 已存在，但必须被执行链真实使用。目录存在本身不代表路由生效。([GitHub][9])

## 10.2 必须实现

文件：

```text
src/seekflow_engineering_tools/capabilities/registry.py
```

必须提供：

```python
def load_capability_registry() -> dict: ...

def backend_supports_recipe(backend: str, recipe: str) -> bool: ...

def choose_backend(spec: CADPartSpec, preferred: list[str] | None = None) -> str:
    ...
```

`choose_backend` 规则：

1. 用户指定 backend 且支持所有 recipe → 返回该 backend。
2. 用户指定 backend 但不支持 → 如果 `cadquery` 支持并允许 fallback，返回 `cadquery` 并带 warning。
3. 没指定 backend → 优先 `cadquery`，因为 CI 可用；如果用户 target_backend 包含 SolidWorks/NX，则按顺序尝试。
4. 如果没有 backend 支持 → 返回错误，不得瞎选。

`engineering_build_cad_model` 必须调用它。

---

# 11. P0-8：修复 SolidWorks 后端可靠性

## 11.1 当前问题

`solidworks/tools.py` 现在已经暴露了 `solidworks_create_flanged_hub_part`、`solidworks_create_spur_gear_part`，这比之前有进步。但 `com_client.py` 仍有大量静默失败风险：VBS 使用 `On Error Resume Next`，`create_cut_extrude` / `create_fillet` 有 best-effort 返回，`_run_vbs` 不充分检查 subprocess 结果，`save_as` / `export_step` 的返回结果在调用链中没有强制验证文件存在。([GitHub][6])

## 11.2 必须修复 `com_client.py`

新增统一 helper：

```python
def _assert_file_created(self, path: str | Path, label: str, min_size: int = 1) -> None:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"{label} was not created: {p}")
    if p.stat().st_size < min_size:
        raise RuntimeError(f"{label} is empty: {p}")
```

新增 VBS 字符串转义：

```python
def _vbs_str(self, value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
```

重写 `_run_vbs`：

```python
def _run_vbs(self, vbs: str, timeout: int = 120, label: str = "solidworks_vbs") -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["cscript.exe", "//Nologo", str(script_path)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    stderr = proc.stderr or ""
    stdout = proc.stdout or ""

    if proc.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit code {proc.returncode}\nSTDOUT:\n{stdout[-4000:]}\nSTDERR:\n{stderr[-4000:]}"
        )

    if "VBS_ERR|" in stderr or "VBS_ERR|" in stdout:
        raise RuntimeError(
            f"{label} reported VBS_ERR\nSTDOUT:\n{stdout[-4000:]}\nSTDERR:\n{stderr[-4000:]}"
        )

    return proc
```

所有手写 `subprocess.run` 必须改成 `_run_vbs`。特别是：

```text
create_flanged_hub
create_spur_gear
create_spur_gear_involute
create_cut_extrude
create_fillet
```

禁止：

```python
return True  # best-effort
```

## 11.3 VBS 必须每步检查

VBS 模板必须包含：

```vbscript
Sub CheckErr(stage)
  If Err.Number <> 0 Then
    WScript.StdErr.WriteLine "VBS_ERR|" & stage & "|" & Err.Number & "|" & Err.Description
    WScript.Quit 1
  End If
End Sub
```

每个关键操作后：

```vbscript
part.Extension.SelectByID2 ...
CheckErr "select_front_plane"

part.InsertSketch2 True
CheckErr "insert_sketch"

feat = part.FeatureManager.FeatureExtrusion2(...)
CheckErr "feature_extrusion"
```

## 11.4 修复 tools.py 参数校验

所有 SolidWorks 工具必须：

```python
ensure_inside_workspace(...)
ensure_extension(out_sldprt_path, {".sldprt"})
ensure_extension(out_step_path, {".step", ".stp"})
```

尺寸必须校验：

```python
def _require_positive(name: str, value: float):
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
```

`flanged_hub` 必须检查：

```text
flange_dia_mm > hub_dia_mm
hub_dia_mm > bore_dia_mm
bolt_count >= 3
bolt_pcd_mm < flange_dia_mm
bolt_pcd_mm > hub_dia_mm
bolt_dia_mm > 0
```

`spur_gear` 必须检查：

```text
module_mm > 0
teeth >= 6
face_width_mm > 0
bore_dia_mm > 0
```

## 11.5 输出文件必须验证

`solidworks_create_flanged_hub_part` 只有在以下都成立时才能 `ok=True`：

```text
.sldprt exists and size > 0
if out_step: .step exists and size > 0
```

---

# 12. P0-9：修复 NX 后端可靠性

## 12.1 当前问题

NX 工具已暴露 `block_with_hole`、`l_bracket`、`stepped_block`，但是 `NXJobQueue` 本身没有 heartbeat 方法，没有 action allowlist；`nx_bridge_bootstrap.py` 没有实际写 heartbeat；部分 STEP export 错误被吞掉；handler 对 `out_step` 支持不完整。([GitHub][10])

## 12.2 修改 `NXJobQueue`

文件：

```text
src/seekflow_engineering_tools/nx/job_queue.py
```

必须新增：

```python
ALLOWED_ACTIONS = {
    "create_block_part",
    "create_block_with_hole",
    "create_l_bracket",
    "create_stepped_block",
    "export_step",
}
```

在 `submit` 中：

```python
if action not in ALLOWED_ACTIONS:
    raise ValueError(f"Unsupported NX action: {action}")
```

新增 heartbeat：

```python
def heartbeat_path(self) -> Path:
    return self.running_dir / "heartbeat.json"

def bridge_status(self, stale_after_s: float = 15.0) -> dict:
    hp = self.heartbeat_path()
    if not hp.exists():
        return {
            "bridge_running": False,
            "reason": "heartbeat_missing",
        }

    try:
        data = json.loads(hp.read_text(encoding="utf-8"))
        age_s = time.time() - float(data.get("time_epoch", 0))
        return {
            "bridge_running": age_s <= stale_after_s,
            "heartbeat_age_s": round(age_s, 3),
            "heartbeat": data,
        }
    except Exception as exc:
        return {
            "bridge_running": False,
            "reason": f"heartbeat_invalid: {exc}",
        }
```

## 12.3 修改 `nx_bridge_bootstrap.py`

必须在主循环里真实写 heartbeat。

新增：

```python
def write_heartbeat():
    payload = {
        "time_epoch": time.time(),
        "time_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "bridge": "nx_bridge_bootstrap",
        "version": "nx12",
    }
    RUNNING.mkdir(parents=True, exist_ok=True)
    (RUNNING / "heartbeat.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
```

主循环必须：

```python
while True:
    write_heartbeat()
    process_one_or_more_jobs()
    time.sleep(1)
```

## 12.4 修复 STEP export

当前有位置吞掉 STEP export 异常，甚至 `InputFile` 可能使用了错误路径。必须统一写 helper：

```python
def export_step_file(work_part, input_prt_path: Path, out_step_path: Path):
    step_creator = the_session.DexManager.CreateStep214Creator()
    step_creator.InputFile = str(input_prt_path)
    step_creator.OutputFile = str(out_step_path)
    step_creator.Commit()
    step_creator.Destroy()

    if not out_step_path.exists() or out_step_path.stat().st_size <= 0:
        raise RuntimeError(f"STEP export failed: {out_step_path}")
```

所有 create handler 如果收到 `out_step`，必须导出。不能忽略。

## 12.5 修改 `nx/tools.py`

所有工具必须：

```python
ensure_inside_workspace(...)
ensure_extension(out_prt_path, {".prt"})
ensure_extension(out_step_path, {".step", ".stp"})
```

数值必须：

```text
length/width/height/thickness > 0
hole_dia_mm > 0
hole_dia_mm < min(width_mm, height_mm)
```

`nx_health_check` 必须调用：

```python
q.bridge_status()
```

并返回：

```json
{
  "bridge_running": true,
  "heartbeat_age_s": 1.2,
  "pending": 0,
  "running": 0,
  "done": 3,
  "failed": 0
}
```

---

# 13. P0-10：修复 ANSYS 参数校验与 parser

## 13.1 当前问题

ANSYS `template_registry.py` 已经有 6 个模板，但 `validate_template_parameters` 只检查模板存在、必填和默认值，没有 reject unknown params，没有类型转换，没有 min/max 校验。([GitHub][11])

`parsers.py` 只解析 `MAX_DISPLACEMENT_MM`、`MAX_STRESS_MPA`、`STRESS_CONCENTRATION_Kt` 和温度字段，不解析 modal、buckling、plastic 等 schema 声称的 metrics。([GitHub][12])

## 13.2 修改 `template_registry.py`

必须实现：

```python
def validate_template_parameters(template_name: str, parameters: dict) -> dict:
    if template_name not in ANSYS_TEMPLATE_SCHEMAS:
        raise ValueError(f"Unknown ANSYS template: {template_name}")

    schema = ANSYS_TEMPLATE_SCHEMAS[template_name]
    param_schema = schema["parameters"]

    unknown = set(parameters) - set(param_schema)
    if unknown:
        raise ValueError(f"Unknown parameters for {template_name}: {sorted(unknown)}")

    validated = {}

    for name, info in param_schema.items():
        if name in parameters:
            raw = parameters[name]
        elif "default" in info:
            raw = info["default"]
        elif info.get("required", False):
            raise ValueError(f"Missing required parameter for {template_name}: {name}")
        else:
            continue

        typ = info.get("type", "float")
        try:
            if typ == "float":
                value = float(raw)
            elif typ == "int":
                value = int(raw)
            elif typ == "str":
                value = str(raw)
            elif typ == "bool":
                value = bool(raw)
            else:
                raise ValueError(f"Unsupported parameter type: {typ}")
        except Exception as exc:
            raise ValueError(f"Invalid value for {name}: expected {typ}, got {raw!r}") from exc

        if "min" in info and value < info["min"]:
            raise ValueError(f"{name} must be >= {info['min']}")
        if "max" in info and value > info["max"]:
            raise ValueError(f"{name} must be <= {info['max']}")

        validated[name] = value

    _validate_template_constraints(template_name, validated)

    return validated
```

新增：

```python
def _validate_template_constraints(template_name: str, params: dict) -> None:
    if template_name == "plate_with_hole_tension":
        if params["hole_diameter_mm"] >= min(params["plate_width_mm"], params["plate_height_mm"]):
            raise ValueError("hole_diameter_mm must be smaller than plate dimensions")

    if template_name == "static_cantilever_beam_rect":
        if params["element_size_mm"] > params["length_mm"]:
            raise ValueError("element_size_mm must be smaller than length_mm")
```

## 13.3 修改 `parsers.py`

必须统一 metric 名称。

推荐统一为：

```text
max_displacement_mm
max_von_mises_mpa
stress_concentration_factor
min_temperature_c
max_temperature_c
mid_temperature_c
modal_frequencies_hz
buckling_load_factor
critical_load_n
max_plastic_strain
tip_displacement_mm
```

parser 必须兼容旧 summary key：

```python
if key == "MAX_STRESS_MPA":
    metrics["max_von_mises_mpa"] = value
    metrics["max_stress_mpa"] = value  # backward compatibility
```

新增解析：

```text
MODE_1_HZ
MODE_2_HZ
MODE_3_HZ
BUCKLING_LOAD_FACTOR
PCR_N
MAX_PLASTIC_STRAIN
TIP_DISPLACEMENT_MM
```

`scan_out_for_errors` 必须同时扫描 warnings：

```python
def scan_out_for_errors(out_path: Path) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    ...
    if "*** ERROR ***" in line:
        errors.append(...)
    if "*** WARNING ***" in line:
        warnings.append(...)
    return errors, warnings
```

## 13.4 修改 `ansys/tools.py`

`ansys_run_apdl_template` 必须返回：

```text
stdout_tail
stderr_tail
metrics
warnings
error
```

如果 summary 不存在：

```python
warnings.append("result_summary.txt was not generated.")
```

不得直接 traceback。

---

# 14. P1：Inspection 与 Validation 必须接入 build

## 14.1 当前目标

`inspection` 目录已经存在，但必须确保它不是摆设。([GitHub][13])

## 14.2 必须实现的数据结构

文件：

```text
src/seekflow_engineering_tools/inspection/common.py
```

必须包含：

```python
class ModelInspection(BaseModel):
    bbox_mm: list[float] | None = None
    volume_mm3: float | None = None
    mass_g: float | None = None
    body_count: int | None = None
    face_count: int | None = None
    edge_count: int | None = None
    hole_count_estimate: int | None = None
    through_hole_count_estimate: int | None = None
    feature_names: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

## 14.3 必须实现 validation

文件：

```text
src/seekflow_engineering_tools/inspection/validation.py
```

必须：

```python
def validate_inspection_against_spec(
    inspection: ModelInspection,
    spec: CADPartSpec,
) -> ValidationReport:
```

至少检查：

```text
expected_bbox_mm
expected_body_count
expected_hole_count
expected_through_hole_count
```

如果 inspection 无法估计孔数，但 spec 要求孔数，第一版可以给 warning，但不能假装通过。建议：

```python
if expected_hole_count is not None and inspection.hole_count_estimate is None:
    issues.append(
        ValidationIssue(
            code="hole_count_not_inspected",
            severity="warning",
            message="Hole count expectation exists but inspector could not estimate holes.",
        )
    )
```

对于 bbox/body_count 必须严格失败。

## 14.4 Build 必须调用 validation

`engineering_build_cad_model` 和 `cadquery_build_from_cad_ir` 必须在成功前调用：

```python
inspection = inspect_step_with_cadquery(out_step_path)
report = validate_inspection_against_spec(inspection, spec)
if not report.ok:
    return ok=False
```

---

# 15. P1：Repair diagnostics 必须接入失败返回

## 15.1 当前目标

`repair` 目录已存在，但必须被实际使用。([GitHub][14])

## 15.2 必须实现

文件：

```text
src/seekflow_engineering_tools/repair/diagnostics.py
```

必须提供：

```python
def make_repair_diagnostics(
    stage: str,
    error_type: str,
    message: str,
    spec: dict | None = None,
    feature_id: str | None = None,
    validation_report: dict | None = None,
    suggested_fix: str | None = None,
) -> dict:
    return {
        "stage": stage,
        "error_type": error_type,
        "feature_id": feature_id,
        "message": message,
        "suggested_fix": suggested_fix,
        "validation_report": validation_report,
    }
```

失败返回必须把它放进：

```python
metrics["repair_diagnostics"] = ...
```

例如 bbox 不匹配：

```json
{
  "stage": "validate",
  "error_type": "bbox_mismatch",
  "feature_id": null,
  "message": "Expected bbox [80, 80, 40], got [80, 80, 39]",
  "suggested_fix": "Check extrusion depths for flange_thickness_mm and hub_height_mm."
}
```

---

# 16. P1：补 `.claude/skills`

当前 `.claude/skills` 不存在，必须新增。

必须新增：

```text
.claude/skills/nl-cad-core/SKILL.md
.claude/skills/solidworks-2025/SKILL.md
.claude/skills/nx12/SKILL.md
.claude/skills/ansys181/SKILL.md
.claude/skills/cadquery-fallback/SKILL.md
```

## 16.1 `nl-cad-core/SKILL.md`

```markdown
---
name: nl-cad-core
description: Use for implementing or editing natural-language-to-CAD logic in this repository.
---

# Mandatory Rules

Do not generate SolidWorks COM, NXOpen, or APDL directly from natural language.

Always use:
natural language -> CAD-IR -> recipe/capability validation -> backend builder -> inspection -> validation.

Hard requirements:
- CAD-IR units are mm.
- Every feature has a unique id.
- Prefer recipe features for common mechanical parts.
- Unknown recipe parameters are errors.
- Missing required recipe parameters are errors.
- Do not return ok=true unless output files exist and validation passes.
- If backend cannot support a recipe, use capability registry to fall back to cadquery or return a clear error.

Required tools:
- engineering_validate_cad_ir
- engineering_build_cad_model
- cadquery_build_from_cad_ir
```

## 16.2 `solidworks-2025/SKILL.md`

```markdown
---
name: solidworks-2025
description: Use for SolidWorks 2025 automation code in this repository.
---

# Mandatory Rules

SolidWorks public tool inputs use mm.
SolidWorks COM/VBS internal units use meters.

Never use best-effort success.
Never return ok=true if a feature script fails.
Never ignore subprocess returncode.
Every output file must exist and be non-empty.

Complex API calls must be wrapped in tested recipes:
- box
- flanged_hub
- spur_gear

VBS requirements:
- Use CheckErr(stage) after every critical operation.
- VBS_ERR must cause Python RuntimeError.
- Do not expose arbitrary VBS code to LLM.
```

## 16.3 `nx12/SKILL.md`

```markdown
---
name: nx12
description: Use for Siemens NX 12.0 bridge code in this repository.
---

# Mandatory Rules

External Python submits JSON jobs only.
NXOpen runs inside nx_bridge_bootstrap.py.

Health check must report real bridge heartbeat.
Job queue must reject unsupported actions.
STEP export must not be silently ignored.
If out_step is requested, either create it or return ok=false.

Stable actions:
- create_block_part
- create_block_with_hole
- create_l_bracket
- create_stepped_block
- export_step
```

## 16.4 `ansys181/SKILL.md`

```markdown
---
name: ansys181
description: Use for ANSYS 18.1 Mechanical APDL batch tools.
---

# Mandatory Rules

Use APDL batch for ANSYS 18.1.
Do not rely on PyMAPDL gRPC.

All templates must validate:
- unknown parameters
- required parameters
- type
- min/max
- geometry constraints

All runs must return:
- stdout_tail
- stderr_tail
- metrics
- warnings
- error if failed

Parser must support static, thermal, modal, buckling, and bilinear plastic metrics.
```

---

# 17. P2：必须新增测试

当前测试目录没有新架构测试，必须补。([GitHub][7])

## 17.1 `test_natural_language_tools_registered.py`

```python
def test_natural_language_and_cadquery_tools_registered():
    from seekflow_engineering_tools.registry import build_engineering_tools
    from seekflow_engineering_tools.config import EngineeringToolsConfig

    config = EngineeringToolsConfig.from_env()
    tools = build_engineering_tools(config)
    names = {t.name for t in tools}

    assert "engineering_validate_cad_ir" in names
    assert "engineering_build_cad_model" in names
    assert "cadquery_build_from_cad_ir" in names
```

## 17.2 `test_cad_ir_schema.py`

```python
import pytest
from pydantic import ValidationError
from seekflow_engineering_tools.ir.cad import CADPartSpec

def test_valid_flanged_hub_recipe_spec():
    spec = CADPartSpec.model_validate({
        "name": "hub_demo",
        "units": "mm",
        "target_backend": ["cadquery"],
        "features": [{
            "id": "main",
            "type": "recipe",
            "recipe_name": "flanged_hub",
            "parameters": {
                "flange_dia_mm": 80,
                "flange_thickness_mm": 12,
                "hub_dia_mm": 40,
                "hub_height_mm": 28,
                "bore_dia_mm": 20,
                "bolt_pcd_mm": 60,
                "bolt_dia_mm": 8,
                "bolt_count": 4
            }
        }],
        "validation": {
            "expected_bbox_mm": [80, 80, 40],
            "expected_body_count": 1,
            "tolerance_mm": 0.2
        }
    })
    assert spec.name == "hub_demo"

def test_reject_non_mm_units():
    with pytest.raises(ValidationError):
        CADPartSpec.model_validate({
            "name": "bad",
            "units": "inch",
            "features": []
        })
```

## 17.3 `test_recipe_registry.py`

```python
import pytest
from seekflow_engineering_tools.recipes.registry import (
    list_recipe_names,
    validate_recipe_parameters,
)

def test_core_recipes_exist():
    names = set(list_recipe_names())
    assert "flanged_hub" in names
    assert "spur_gear" in names
    assert "l_bracket" in names
    assert "block_with_hole" in names

def test_recipe_rejects_unknown_param():
    with pytest.raises(ValueError):
        validate_recipe_parameters("flanged_hub", {
            "flange_dia_mm": 80,
            "bad_param": 1,
        })

def test_recipe_rejects_invalid_bolt_count():
    with pytest.raises(ValueError):
        validate_recipe_parameters("flanged_hub", {
            "flange_dia_mm": 80,
            "flange_thickness_mm": 12,
            "hub_dia_mm": 40,
            "hub_height_mm": 28,
            "bore_dia_mm": 20,
            "bolt_pcd_mm": 60,
            "bolt_dia_mm": 8,
            "bolt_count": 2,
        })
```

## 17.4 `test_cadquery_backend.py`

```python
import pytest

def test_cadquery_build_creates_real_step(tmp_path, monkeypatch):
    pytest.importorskip("cadquery")

    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir
    from seekflow_engineering_tools.ir.cad import CADPartSpec

    config = EngineeringToolsConfig(workspace_root=tmp_path)

    spec = CADPartSpec.model_validate({
        "name": "hub_demo",
        "units": "mm",
        "target_backend": ["cadquery"],
        "features": [{
            "id": "main",
            "type": "recipe",
            "recipe_name": "flanged_hub",
            "parameters": {
                "flange_dia_mm": 80,
                "flange_thickness_mm": 12,
                "hub_dia_mm": 40,
                "hub_height_mm": 28,
                "bore_dia_mm": 20,
                "bolt_pcd_mm": 60,
                "bolt_dia_mm": 8,
                "bolt_count": 4
            }
        }],
        "validation": {
            "expected_bbox_mm": [80, 80, 40],
            "expected_body_count": 1,
            "tolerance_mm": 0.5
        }
    })

    result = build_cadquery_from_cad_ir(
        spec=spec,
        config=config,
        out_step="models/hub_demo.step",
        inspect=True,
    )

    assert result["ok"] is True
    step_path = tmp_path / "models" / "hub_demo.step"
    assert step_path.exists()
    assert step_path.stat().st_size > 0
```

## 17.5 `test_nx_heartbeat.py`

```python
import json
import time

def test_nx_bridge_status_missing_heartbeat(tmp_path):
    from seekflow_engineering_tools.nx.job_queue import NXJobQueue
    q = NXJobQueue(tmp_path)
    status = q.bridge_status()
    assert status["bridge_running"] is False

def test_nx_bridge_status_valid_heartbeat(tmp_path):
    from seekflow_engineering_tools.nx.job_queue import NXJobQueue
    q = NXJobQueue(tmp_path)
    hp = q.heartbeat_path()
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_text(json.dumps({"time_epoch": time.time()}), encoding="utf-8")

    status = q.bridge_status()
    assert status["bridge_running"] is True
```

## 17.6 `test_ansys_template_validation.py`

```python
import pytest
from seekflow_engineering_tools.ansys.template_registry import validate_template_parameters

def test_ansys_rejects_unknown_parameter():
    with pytest.raises(ValueError):
        validate_template_parameters("static_cantilever_beam_rect", {
            "length_mm": 100,
            "width_mm": 10,
            "height_mm": 10,
            "force_n": 100,
            "unknown": 1,
        })

def test_ansys_rejects_negative_length():
    with pytest.raises(ValueError):
        validate_template_parameters("static_cantilever_beam_rect", {
            "length_mm": -100,
            "width_mm": 10,
            "height_mm": 10,
            "force_n": 100,
        })
```

---

# 18. 最终验收命令

Claude Code 完成后必须运行：

```bash
cd integrations/engineering_tools
pytest
```

还必须运行：

```bash
grep -R "NX 18.0\|UG 18.0" src pyproject.toml
```

结果必须为空。

还必须检查工具注册：

```python
from seekflow_engineering_tools.registry import build_engineering_tools
from seekflow_engineering_tools.config import EngineeringToolsConfig

tools = build_engineering_tools(EngineeringToolsConfig.from_env())
names = {t.name for t in tools}

required = {
    "engineering_validate_cad_ir",
    "engineering_build_cad_model",
    "cadquery_build_from_cad_ir",
    "cadquery_compile_cad_ir_to_script",
    "cadquery_inspect_step",
    "solidworks_create_flanged_hub_part",
    "solidworks_create_spur_gear_part",
    "nx_create_block_with_hole",
    "nx_create_l_bracket",
    "nx_create_stepped_block",
    "ansys_list_apdl_templates",
}

missing = required - names
assert not missing, missing
```

---

# 19. 给 Claude Code 的强制执行提示

下面这段建议原样复制给 Claude Code：

```markdown
你必须完整修复 integrations/engineering_tools，使其达到自然语言精确建模架构。不要只做表面改动。不要只生成脚手架。不要返回假成功。

硬性要求：

1. build_engineering_tools 必须注册：
   - engineering_validate_cad_ir
   - engineering_build_cad_model
   - cadquery_build_from_cad_ir
   - cadquery_compile_cad_ir_to_script
   - cadquery_inspect_step
   - solidworks_create_flanged_hub_part
   - solidworks_create_spur_gear_part
   - nx_create_block_with_hole
   - nx_create_l_bracket
   - nx_create_stepped_block
   - ansys_list_apdl_templates

2. engineering_build_cad_model 必须真实执行后端构建。
   - CadQuery 后端必须真实生成 STEP 文件。
   - 不允许只 compile script。
   - 不允许只返回“请调用其他工具”。
   - 不允许在文件不存在时返回 ok=true。

3. CadQuery backend 必须实现 cadquery_build_from_cad_ir。
   - 使用 CAD-IR。
   - 生成确定性 CadQuery 脚本。
   - 执行脚本。
   - 检查 STEP 存在且非空。
   - inspect。
   - validation。
   - 返回 EngineeringActionResult。

4. 所有路径必须通过 ensure_inside_workspace。
   所有输出扩展名必须通过 ensure_extension。
   所有输出文件必须检查 exists + size > 0。

5. SolidWorks 后端必须去掉 best-effort success。
   - 不允许 return True # best-effort。
   - 不允许忽略 subprocess returncode。
   - VBS 必须 CheckErr(stage)。
   - SaveAs/export 后必须检查文件存在。

6. NX 后端必须实现真实 heartbeat。
   - NXJobQueue 增加 heartbeat_path 和 bridge_status。
   - nx_bridge_bootstrap.py 主循环必须写 running/heartbeat.json。
   - nx_health_check 必须报告 bridge_running。
   - JobQueue submit 必须拒绝 unknown action。
   - STEP export 失败不得 pass。

7. ANSYS 必须严格校验模板参数。
   - unknown params 报错。
   - 类型错误报错。
   - min/max 报错。
   - 几何约束错误报错。
   - parser 必须覆盖 static、thermal、modal、buckling、plastic metrics。
   - ansys_run_apdl_template 必须返回 stdout_tail 和 stderr_tail。

8. CAD-IR 必须强化验证。
   - extra=forbid。
   - 所有尺寸 > 0。
   - bbox 必须长度 3。
   - feature id 唯一。
   - RecipeFeature 必须通过 recipe registry 校验。

9. Recipe registry 必须真实校验参数。
   - required
   - unknown
   - type
   - min/max

10. Capability registry 必须参与 backend routing。
    - backend 不支持 recipe 时不能瞎执行。
    - 支持 fallback 到 cadquery。
    - 不支持且无法 fallback 时必须 ok=false。

11. Inspection 和 validation 必须接入 build。
    - expected_bbox_mm 不匹配必须 ok=false。
    - expected_body_count 不匹配必须 ok=false。
    - validation report 必须放入 metrics。

12. 必须新增 .claude/skills：
    - nl-cad-core
    - solidworks-2025
    - nx12
    - ansys181
    - cadquery-fallback

13. 必须新增测试：
    - test_natural_language_tools_registered.py
    - test_cad_ir_schema.py
    - test_recipe_registry.py
    - test_capability_registry.py
    - test_cadquery_backend.py
    - test_engineering_build_cad_model.py
    - test_solidworks_recipe_tools_mock.py
    - test_nx_recipe_tools_mock.py
    - test_nx_heartbeat.py
    - test_ansys_template_registry.py
    - test_ansys_template_validation.py
    - test_inspection_validation.py

完成后运行：
cd integrations/engineering_tools
pytest

并修复所有失败。

不要说“已实现”除非：
- pytest 通过；
- build_engineering_tools 能列出所有 required tools；
- cadquery_build_from_cad_ir 能真实生成 STEP；
- engineering_build_cad_model 用 cadquery 能真实生成 STEP 并 validation。
```

---

# 20. 最终判断

现在仓库已经有部分模块名称，但还没有形成真正闭环。最危险的问题是：

```text
1. 新模块没有注册，LLM 根本用不到。
2. engineering_build_cad_model 不真实建模。
3. CadQuery backend 不能 build，只能 compile/inspect。
4. SolidWorks 仍可能静默失败。
5. NX heartbeat 没有真正写入。
6. ANSYS 参数校验和 parser 不完整。
7. 没有 skills。
8. 没有新架构测试。
```

修复的核心不是再加几个文件，而是保证：

```text
CAD-IR → recipe 校验 → capability 路由 → backend 真实执行 → 文件存在校验 → inspect → validation → EngineeringActionResult
```

这条链真正跑通。只有这样，后续让 LLM 输出自然语言建模规范或 CAD-IR，才会显著提高建模成功率。

[1]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/src/seekflow_engineering_tools/ir "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/ir at main · WYZAAACCC/seekflow-engineering · GitHub"
[2]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/registry.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/registry.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[3]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[4]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend at main · WYZAAACCC/seekflow-engineering · GitHub"
[5]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/common/paths.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/common/paths.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/com_client.py "raw.githubusercontent.com"
[7]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/tests "seekflow-engineering/integrations/engineering_tools/tests at main · WYZAAACCC/seekflow-engineering · GitHub"
[8]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/compiler.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/compiler.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[9]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/src/seekflow_engineering_tools/capabilities "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/capabilities at main · WYZAAACCC/seekflow-engineering · GitHub"
[10]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx/job_queue.py "raw.githubusercontent.com"
[11]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/ansys/template_registry.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/ansys/template_registry.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[12]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/ansys/parsers.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/ansys/parsers.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[13]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/src/seekflow_engineering_tools/inspection "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/inspection at main · WYZAAACCC/seekflow-engineering · GitHub"
[14]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/src/seekflow_engineering_tools/repair "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/repair at main · WYZAAACCC/seekflow-engineering · GitHub"
