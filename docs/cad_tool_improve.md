
---

# SeekFlow Engineering 自然语言精确建模落地方案 v2

## 0. 核心目标

把现在的：

```text
自然语言 → LLM 猜 SolidWorks/NX/ANSYS API → 调工具 → 成败看运气
```

改成：

```text
自然语言
→ NL-CAD / NL-CAE 规范化输入
→ CAD-IR / CAE-IR Pydantic 中间表示
→ schema 校验与参数补全
→ backend compiler / recipe layer
→ SolidWorks 2025 / NX 12.0 / ANSYS 18.1 执行
→ 几何/求解结果 inspect
→ 自动修复 loop
→ 导出 native + STEP + result summary
```

**关键原则：LLM 不直接写 SolidWorks COM、NXOpen、APDL。LLM 只输出受限、可校验、可编译的结构化建模意图。**

---

# 1. 重新阅读代码后的准确诊断

## 1.1 当前仓库架构已经有好底座，但工具粒度太粗

`integrations/engineering_tools` 当前已有 `examples`、`src/seekflow_engineering_tools`、`tests`、架构文档、Roadmap、demo 和 pyproject，说明它已经不是零散脚本，而是一个工具包雏形。([GitHub][1])

配置层 `EngineeringToolsConfig` 已经统一管理 `workspace_root`、SolidWorks、NX、ANSYS 路径与开关，并限制工具写入 workspace，这是正确方向。([GitHub][2])

统一返回结构 `EngineeringActionResult` 目前包含 `ok`、`software`、`action`、`files_created`、`files_modified`、`log_path`、`stdout_tail`、`stderr_tail`、`metrics`、`warnings`、`error`，这给后续“执行-校验-修复”闭环提供了基础。([GitHub][3])

但当前 `EngineeringActionResult.software` 只允许 `"solidworks" | "nx" | "ansys"`，后面如果引入 `cadquery` 或 `generic_cad` 作为几何 fallback，需要扩展这个 Literal。([GitHub][3])

---

## 1.2 SolidWorks 2025 当前问题

### 已暴露给 LLM 的工具太少

`solidworks/tools.py` 目前主要暴露：

```text
solidworks_health_check
solidworks_create_box_part
solidworks_export_step
```

`solidworks_create_box_part` 只接受长宽高并创建矩形块，`solidworks_export_step` 只负责 STEP 导出。也就是说，LLM 通过正式工具层只能稳定做“方块”和“导出”。([GitHub][4])

### com_client.py 里其实已有复杂能力，但没被工具化

`SolidWorksClient` 里已经有：

```text
create_cut_extrude
create_fillet
create_flanged_hub
create_spur_gear_involute
create_spur_gear_star_demo
create_spur_gear
```

尤其 `create_flanged_hub` 已能创建法兰轮毂，`create_spur_gear_involute` 已能做近似渐开线齿轮，但这些没有被 `tools.py` 暴露给 LLM，所以普通 tool-call 模型无法发现并调用。([GitHub][5])

### 错误处理仍然危险

代码里多处 VBS 片段使用 `On Error Resume Next`，并且 `create_cut_extrude`、`create_fillet` 等函数即使 `subprocess.run` 出错也 `return True # best-effort`，这会导致“模型没建对但工具返回成功”。([GitHub][5])

架构文档已经确认 SolidWorks 2025 的 `FeatureExtrusion2` 在宏录制中表现为 23 参数签名，pywin32 直接调复杂特征容易 TYPE_MISMATCH，因此当前采用 VBScript bridge 是有技术依据的。([GitHub][6])

---

## 1.3 NX 12.0 当前问题

### 版本描述错误

`nx/tools.py` 文件头和工具描述仍写 “NX 18.0”，但架构文档和用户环境目标是 Siemens NX 12.0。这个错误会污染 LLM 的上下文，让模型使用错误版本的 API 记忆。([GitHub][7])

`config.py` 里也写了 “NX / UG 18.0”，`__init__.py` 描述也写 “NX 18.0”，这些都应统一为 NX 12.0。([GitHub][2])

### 外层工具只暴露 block/export，内层 bridge 有更多 handler

`nx/tools.py` 目前正式暴露：

```text
nx_health_check
nx_create_block_part
nx_export_step
```

其中 health check 明确说只是检查 job queue 目录，不保证 NX bridge journal 正在运行。([GitHub][7])

但 `nx_bridge_bootstrap.py` 里实际已有 action handlers：

```python
ACTION_HANDLERS = {
  "create_block_part": create_block_part,
  "create_block_with_hole": create_block_with_hole,
  "create_l_bracket": create_l_bracket,
  "create_stepped_block": create_stepped_block,
  "export_step": export_step,
}
```

这说明 NX 也已经有更复杂一点的建模能力，只是外层 `tools.py` 没有把它们暴露出去。([GitHub][8])

NX bridge 当前采用文件队列：`pending`、`running`、`done`、`failed`，每 1 秒轮询；架构文档说明这样做是因为 NXOpen Python 必须在 NX 进程内运行，外部 Python 不能直接 import NXOpen。([GitHub][8])

### STEP 导出错误被吞掉

`create_block_part` 中 STEP 导出失败后 `except Exception: pass`，这会让用户以为导出成功，但其实可能只生成了 `.prt`。([GitHub][8])

---

## 1.4 ANSYS 18.1 当前问题

### 工具描述与模板库不一致

`ansys/tools.py` 只 import 了 `static_cantilever_beam_rect_apdl`，而 `ansys_run_apdl_template` 的描述也只告诉模型可用模板是 `static_cantilever_beam_rect`。([GitHub][9])

但 `apdl_templates.py` 的 `TEMPLATES` 实际包含 6 个模板：

```text
static_cantilever_beam_rect
plate_with_hole_tension
beam_thermal
cantilever_modal
buckling_column
bilinear_plastic
```

这导致 LLM 不知道已有模板能力。([GitHub][10])

ANSYS 18.1 继续用 APDL batch 是正确方向，因为 Mechanical APDL 官方支持 interactive 和 batch 模式；你们架构文档也说明 ANSYS 18.1 环境下 APDL batch 是最稳定路线。([ANSYS Help][11])

---

## 1.5 现有测试不足以保证“自然语言建模成功”

当前 tests 目录只有：

```text
test_ansys_runner_mock.py
test_nx_job_queue.py
test_paths.py
test_registry.py
test_solidworks_mock.py
```

也就是说，当前主要是 mock、路径、注册、队列层测试，没有覆盖“生成的模型是否符合用户语义”的 golden model 验收。([GitHub][12])

---

# 2. 要实现的最终能力

Claude Code 的实现目标不是“让 LLM 记住 CAD API”，而是实现以下 6 个层次。

```text
Layer 1: NL-CAD/NL-CAE 输入规范
Layer 2: CAD-IR / CAE-IR Pydantic 数据模型
Layer 3: recipe registry，高层建模操作库
Layer 4: backend compiler，分别编译到 SW VBS、NX job、ANSYS APDL、CadQuery fallback
Layer 5: inspector，检查模型实际几何或求解结果
Layer 6: repair loop，错误结构化反馈给 LLM 修正 IR
```

引入 CadQuery 或 build123d 作为 fallback 是合理的：CadQuery 官方定位是 Python 参数化 CAD，可输出 STEP、AMF、3MF、STL，并且语法接近人类描述模型；build123d 是基于 OpenCascade 的 Python 参数化 BREP CAD 框架，可导出到 FreeCAD、SolidWorks 等 CAD 工具。([cadquery.readthedocs.io][13])

---

# 3. Claude Code 总任务说明

把下面这段作为 Claude Code 的总提示。

```markdown
你要在 integrations/engineering_tools 内实现“自然语言精确建模 v1”。

不要让 LLM 直接输出 SolidWorks COM、NXOpen 或 ANSYS APDL。请新增 CAD-IR / CAE-IR 中间层、recipe registry、backend compiler、inspector 和 tests。

优先保持现有 SeekFlow tool 风格、ToolPolicy、workspace_root 限制和 EngineeringActionResult 返回结构。不得破坏已有 health_check、create_box_part、create_block_part、ansys_static_cantilever_beam_rect 等 API。

实现顺序：
1. 修复版本描述、工具描述、错误处理和未暴露 handler。
2. 新增 CAD-IR / CAE-IR Pydantic 模型。
3. 新增 generic recipe registry。
4. 新增 cadquery backend 作为无需商业 CAD 的几何 fallback。
5. 新增 SolidWorks recipe wrappers，先暴露 flanged_hub 与 spur_gear。
6. 新增 NX tool wrappers，暴露 block_with_hole、l_bracket、stepped_block。
7. 新增 ANSYS template registry tool，暴露 6 个模板及 schema。
8. 新增 inspector 与 validation expectation。
9. 新增 .claude/skills 下的建模 skills。
10. 新增 golden model tests。

每一步都必须有 pytest。没有本机 SolidWorks/NX/ANSYS 时，使用 mock 或 cadquery backend 验证 IR、compiler、文件路径、错误返回。
```

Claude Code 现在官方支持通过 `.claude/skills/<name>/SKILL.md` 创建项目技能，且自定义 commands 已合并到 skills 机制，因此本方案把建模规范写入 `.claude/skills` 是合适的。([Claude Code][14])

---

# 4. 第一阶段：立即修复现有代码缺口

## 4.1 修复版本命名

修改这些文件里的 NX 18.0 / UG 18.0：

```text
integrations/engineering_tools/pyproject.toml
integrations/engineering_tools/src/seekflow_engineering_tools/__init__.py
integrations/engineering_tools/src/seekflow_engineering_tools/config.py
integrations/engineering_tools/src/seekflow_engineering_tools/nx/tools.py
```

改为：

```text
Siemens NX 12.0
NX 12.0
```

保留兼容表达：

```text
NX 12.0+ where tested
```

但不要再写 NX 18.0。

验收：

```bash
grep -R "NX 18.0\|UG 18.0" integrations/engineering_tools
# 应无结果，除非在 changelog 里说明历史错误
```

---

## 4.2 修复 ANSYS 模板描述

修改：

```text
src/seekflow_engineering_tools/ansys/tools.py
```

把：

```python
from seekflow_engineering_tools.ansys.apdl_templates import (
    static_cantilever_beam_rect_apdl,
)
```

改成：

```python
from seekflow_engineering_tools.ansys.apdl_templates import (
    static_cantilever_beam_rect_apdl,
    list_templates,
)
```

把 `ansys_run_apdl_template` 描述改成动态或完整描述：

```python
description=(
    "Run a named APDL template from the built-in library. "
    "Available templates: static_cantilever_beam_rect, "
    "plate_with_hole_tension, beam_thermal, cantilever_modal, "
    "buckling_column, bilinear_plastic. Units depend on template schema."
)
```

新增 tool：

```python
@tool(
    name="ansys_list_apdl_templates",
    description="List built-in ANSYS 18.1 APDL templates and their expected parameters.",
    ...
)
def ansys_list_apdl_templates() -> dict:
    ...
```

返回格式：

```json
{
  "ok": true,
  "software": "ansys",
  "action": "list_apdl_templates",
  "metrics": {
    "templates": {
      "static_cantilever_beam_rect": {
        "analysis_type": "static_structural",
        "units": "mm,N,MPa",
        "parameters": {
          "length_mm": "float",
          "width_mm": "float",
          "height_mm": "float",
          "force_n": "float",
          "element_size_mm": "float"
        }
      }
    }
  }
}
```

验收：

```bash
pytest tests/test_ansys_template_registry.py
```

新增测试：

```python
def test_ansys_list_templates_contains_all_six():
    from seekflow_engineering_tools.ansys.apdl_templates import list_templates
    assert set(list_templates()) == {
        "static_cantilever_beam_rect",
        "plate_with_hole_tension",
        "beam_thermal",
        "cantilever_modal",
        "buckling_column",
        "bilinear_plastic",
    }
```

---

## 4.3 暴露 SolidWorks 已有复杂 helper

修改：

```text
src/seekflow_engineering_tools/solidworks/tools.py
```

新增两个工具：

```text
solidworks_create_flanged_hub_part
solidworks_create_spur_gear_part
```

### solidworks_create_flanged_hub_part 参数

```python
def solidworks_create_flanged_hub_part(
    flange_dia_mm: float,
    flange_thickness_mm: float,
    hub_dia_mm: float,
    hub_height_mm: float,
    bore_dia_mm: float,
    bolt_pcd_mm: float,
    bolt_dia_mm: float,
    bolt_count: int,
    out_sldprt: str,
    out_step: str | None = None,
) -> dict:
```

调用现有：

```python
client.create_flanged_hub(
    model,
    flange_dia_m=flange_dia_mm / 1000,
    flange_h_m=flange_thickness_mm / 1000,
    hub_dia_m=hub_dia_mm / 1000,
    hub_h_m=hub_height_mm / 1000,
    bore_dia_m=bore_dia_mm / 1000,
    bolt_pcd_m=bolt_pcd_mm / 1000,
    bolt_dia_m=bolt_dia_mm / 1000,
    bolt_count=bolt_count,
)
```

返回 metrics：

```python
metrics={
    "flange_dia_mm": flange_dia_mm,
    "flange_thickness_mm": flange_thickness_mm,
    "hub_dia_mm": hub_dia_mm,
    "hub_height_mm": hub_height_mm,
    "bore_dia_mm": bore_dia_mm,
    "bolt_pcd_mm": bolt_pcd_mm,
    "bolt_dia_mm": bolt_dia_mm,
    "bolt_count": bolt_count,
    "expected_through_hole_count": bolt_count + 1,
}
```

### solidworks_create_spur_gear_part 参数

```python
def solidworks_create_spur_gear_part(
    module_mm: float,
    teeth: int,
    face_width_mm: float,
    bore_dia_mm: float,
    out_sldprt: str,
    out_step: str | None = None,
) -> dict:
```

调用：

```python
client.create_spur_gear(
    model,
    module_m=module_mm / 1000,
    teeth=teeth,
    face_width_m=face_width_mm / 1000,
    bore_dia_m=bore_dia_mm / 1000,
)
```

### 必须先修复 VBS 错误处理

在 `SolidWorksClient` 增加统一方法：

```python
def _run_vbs_strict(self, vbs_code: str, timeout: int = 120, label: str = "sw_vbs") -> subprocess.CompletedProcess:
    wrapped = """
On Error GoTo 0

Sub CheckErr(stage)
  If Err.Number <> 0 Then
    WScript.StdErr.WriteLine "VBS_ERR|" & stage & "|" & Err.Number & "|" & Err.Description
    WScript.Quit 1
  End If
End Sub
""" + vbs_code + """
If Err.Number <> 0 Then
  WScript.StdErr.WriteLine "VBS_ERR|final|" & Err.Number & "|" & Err.Description
  WScript.Quit 1
End If
"""
```

注意 VBScript 没有 VBA 的 `On Error GoTo label`，可以使用：

```vbscript
On Error Resume Next
' operation
CheckErr "select_plane"
```

但每一步后必须 `CheckErr`，不能整段 best-effort。

替换所有：

```python
subprocess.run(..., capture_output=True)
return True
```

为：

```python
r = subprocess.run(..., timeout=timeout, capture_output=True, text=True)
if r.returncode != 0:
    raise RuntimeError(f"SolidWorks VBS failed: {r.stderr[-2000:]}")
if "VBS_ERR|" in (r.stderr or ""):
    raise RuntimeError(...)
return r
```

验收：

```bash
pytest tests/test_solidworks_recipes_mock.py
```

---

## 4.4 暴露 NX bridge 已有 handler

修改：

```text
src/seekflow_engineering_tools/nx/tools.py
```

新增：

```text
nx_create_block_with_hole
nx_create_l_bracket
nx_create_stepped_block
```

它们不需要先写 NXOpen 新代码，因为 `nx_bridge_bootstrap.py` 已有对应 handler；只需要在外层 submit job。([GitHub][8])

### nx_create_block_with_hole

参数：

```python
def nx_create_block_with_hole(
    length_mm: float,
    width_mm: float,
    height_mm: float,
    hole_dia_mm: float,
    hole_x_mm: float | None,
    hole_z_mm: float | None,
    out_prt: str,
    out_step: str | None = None,
) -> dict:
```

提交：

```python
job_id = q.submit("create_block_with_hole", params)
```

如果 `out_step` 不为空，当前 bridge handler 可能没有导出 STEP；Claude Code 应检查 handler 是否接受 `out_step`。若没有，先建 `.prt` 后再 submit `export_step` job。

### nx_create_l_bracket

参数：

```python
def nx_create_l_bracket(
    base_length_mm: float,
    base_width_mm: float,
    thickness_mm: float,
    leg_height_mm: float,
    out_prt: str,
    out_step: str | None = None,
) -> dict:
```

注意 bridge handler 参数名现在是 `base_length`、`base_width`、`thickness`、`leg_height`，外层工具应统一转成这些 key。

### nx_create_stepped_block

参数：

```python
def nx_create_stepped_block(
    base_length_mm: float,
    base_width_mm: float,
    base_height_mm: float,
    top_length_mm: float,
    top_width_mm: float,
    top_height_mm: float,
    out_prt: str,
    out_step: str | None = None,
) -> dict:
```

### 修复 health_check

给 `NXJobQueue` 增加：

```python
def heartbeat_path(self) -> Path:
    return self.root / "running" / "heartbeat.json"

def bridge_status(self, stale_after_s: float = 15.0) -> dict:
    hp = self.heartbeat_path()
    if not hp.exists():
        return {"bridge_running": False, "reason": "heartbeat_missing"}
    data = json.loads(hp.read_text(encoding="utf-8"))
    age_s = time.time() - float(data.get("time_epoch", 0))
    return {
        "bridge_running": age_s <= stale_after_s,
        "heartbeat_age_s": age_s,
        "heartbeat": data,
    }
```

在 `nx_bridge_bootstrap.py` 主循环里每 5 秒写：

```python
def write_heartbeat(session):
    payload = {
        "time_epoch": time.time(),
        "time_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "nx_version": str(session.GetEnvironmentVariableValue("UGII_VERSION")) if hasattr(session, "GetEnvironmentVariableValue") else "unknown",
        "job_root": str(JOB_ROOT),
    }
    (RUNNING / "heartbeat.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
```

`nx_health_check` 返回：

```json
{
  "bridge_running": true,
  "heartbeat_age_s": 2.3,
  "pending": 0,
  "running": 0,
  "done": 4,
  "failed": 0
}
```

验收：

```bash
pytest tests/test_nx_job_queue.py tests/test_nx_tools_mock.py
```

---

# 5. 第二阶段：新增 CAD-IR / CAE-IR

新增目录：

```text
src/seekflow_engineering_tools/ir/
  __init__.py
  cad.py
  cae.py
  validation.py
  defaults.py
```

## 5.1 CAD-IR Pydantic 模型

`ir/cad.py`：

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


LengthUnit = Literal["mm", "m", "inch"]
BackendName = Literal["solidworks2025", "nx12", "cadquery"]
PlaneName = Literal["XY", "YZ", "XZ", "front", "top", "right"]


class OutputSpec(BaseModel):
    native: bool = True
    step: bool = True
    stl: bool = False
    preview_png: bool = False


class ValidationSpec(BaseModel):
    expected_bbox_mm: list[float] | None = None
    expected_body_count: int | None = None
    expected_hole_count: int | None = None
    expected_through_hole_count: int | None = None
    expected_feature_count_min: int | None = None
    tolerance_mm: float = 0.1


class CircleProfile(BaseModel):
    type: Literal["circle"] = "circle"
    diameter_mm: float


class RectangleProfile(BaseModel):
    type: Literal["rectangle"] = "rectangle"
    width_mm: float
    height_mm: float
    centered: bool = True


class PolygonProfile(BaseModel):
    type: Literal["polygon"] = "polygon"
    points_mm: list[list[float]]


Profile = CircleProfile | RectangleProfile | PolygonProfile


class SketchSpec(BaseModel):
    plane: PlaneName
    origin_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    profile: Profile


class ExtrudeFeature(BaseModel):
    id: str
    type: Literal["extrude"] = "extrude"
    sketch: SketchSpec
    depth_mm: float
    operation: Literal["add", "cut"] = "add"
    direction: Literal["+", "-"] = "+"


class HoleFeature(BaseModel):
    id: str
    type: Literal["hole"] = "hole"
    diameter_mm: float
    position_mm: list[float]
    axis: Literal["X", "Y", "Z"] = "Z"
    through_all: bool = True
    depth_mm: float | None = None


class CircularPatternHolesFeature(BaseModel):
    id: str
    type: Literal["circular_pattern_holes"] = "circular_pattern_holes"
    count: int
    hole_diameter_mm: float
    pitch_circle_diameter_mm: float
    axis: Literal["X", "Y", "Z"] = "Z"
    center_mm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    through_all: bool = True


class FilletFeature(BaseModel):
    id: str
    type: Literal["fillet"] = "fillet"
    radius_mm: float
    target: Literal["all_external_edges", "named_edges", "manual"] = "all_external_edges"
    edge_ids: list[str] = Field(default_factory=list)


class ChamferFeature(BaseModel):
    id: str
    type: Literal["chamfer"] = "chamfer"
    distance_mm: float
    target: Literal["all_external_edges", "named_edges", "manual"] = "all_external_edges"
    edge_ids: list[str] = Field(default_factory=list)


class RecipeFeature(BaseModel):
    id: str
    type: Literal["recipe"] = "recipe"
    recipe_name: str
    parameters: dict[str, Any]


CADFeature = (
    ExtrudeFeature
    | HoleFeature
    | CircularPatternHolesFeature
    | FilletFeature
    | ChamferFeature
    | RecipeFeature
)


class CADPartSpec(BaseModel):
    nlcad_version: str = "0.1"
    name: str
    units: LengthUnit = "mm"
    target_backend: list[BackendName] = Field(default_factory=lambda: ["cadquery"])
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    features: list[CADFeature]
    validation: ValidationSpec = Field(default_factory=ValidationSpec)
    outputs: OutputSpec = Field(default_factory=OutputSpec)

    @model_validator(mode="after")
    def validate_basic(self):
        if self.units != "mm":
            raise ValueError("v1 CAD-IR only accepts mm at the IR boundary")
        ids = [f.id for f in self.features]
        if len(ids) != len(set(ids)):
            raise ValueError("feature ids must be unique")
        return self
```

为什么要这么做：LLM 输出此结构时，错误会被 Pydantic 提前拦截；后端只处理合法 feature graph。

---

## 5.2 CAE-IR Pydantic 模型

`ir/cae.py`：

```python
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


AnalysisType = Literal[
    "static_structural",
    "modal",
    "thermal_steady",
    "buckling",
    "bilinear_plastic",
]

ElementType = Literal["SOLID185", "PLANE182", "SOLID70", "BEAM188"]


class MaterialSpec(BaseModel):
    name: str
    ex_mpa: float | None = None
    nu: float | None = None
    density_tonne_per_mm3: float | None = None
    k_w_per_mm_c: float | None = None
    yield_mpa: float | None = None
    tangent_mpa: float | None = None


class MeshSpec(BaseModel):
    element_type: ElementType
    element_size_mm: float


class GeometrySource(BaseModel):
    type: Literal["primitive", "step_file", "template"]
    path: str | None = None
    template_name: str | None = None
    parameters: dict = Field(default_factory=dict)


class LoadSpec(BaseModel):
    id: str
    type: Literal["force", "pressure", "temperature", "displacement"]
    target: str
    value: float | list[float]
    units: str


class ConstraintSpec(BaseModel):
    id: str
    type: Literal["fixed", "symmetry", "displacement"]
    target: str
    value: float | list[float] | None = None


class ResultRequest(BaseModel):
    type: Literal[
        "max_displacement",
        "max_von_mises",
        "reaction_force",
        "modal_frequencies",
        "buckling_load_factor",
        "max_temperature",
    ]


class CAEJobSpec(BaseModel):
    nlcae_version: str = "0.1"
    name: str
    analysis_type: AnalysisType
    units: Literal["mm,N,MPa,C"] = "mm,N,MPa,C"
    geometry: GeometrySource
    materials: list[MaterialSpec]
    mesh: MeshSpec
    loads: list[LoadSpec] = Field(default_factory=list)
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    results: list[ResultRequest]
```

---

# 6. 第三阶段：Recipe Registry

新增：

```text
src/seekflow_engineering_tools/recipes/
  __init__.py
  base.py
  registry.py
  mechanical.py
```

## 6.1 设计目的

让 LLM 优先输出：

```json
{
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
}
```

而不是输出几十个 sketch/cut/pattern 低级操作。

## 6.2 base.py

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class RecipeParameter(BaseModel):
    name: str
    type: Literal["float", "int", "str", "bool"]
    unit: str | None = None
    required: bool = True
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    description: str = ""


class RecipeDefinition(BaseModel):
    name: str
    category: str
    description: str
    parameters: list[RecipeParameter]
    supported_backends: list[str]
    validation_defaults: dict[str, Any] = Field(default_factory=dict)
```

## 6.3 mechanical.py 初始 recipes

必须先实现这 10 个：

```text
box
cylinder
plate_with_holes
block_with_hole
l_bracket
stepped_block
flanged_hub
spur_gear
shaft_basic
shaft_with_keyway
```

其中：

* `box` → SW/NX/CadQuery
* `block_with_hole` → NX/CadQuery，后续 SW
* `l_bracket` → NX/CadQuery，后续 SW
* `stepped_block` → NX/CadQuery，后续 SW
* `flanged_hub` → SW/CadQuery，后续 NX
* `spur_gear` → SW/CadQuery，后续 NX
* `shaft_basic`、`shaft_with_keyway` → CadQuery 优先，SW/NX 后续

---

# 7. 第四阶段：CadQuery backend 作为可测 fallback

新增：

```text
src/seekflow_engineering_tools/cadquery_backend/
  __init__.py
  compiler.py
  recipes.py
  inspector.py
  tools.py
```

修改 `pyproject.toml`：

```toml
[project.optional-dependencies]
cadquery = [
  "cadquery>=2.5",
]
```

CadQuery 默认 STEP 单位是 mm，并支持设置输入/输出单位，这很适合作为 CAD-IR 的默认单位系统。([cadquery.readthedocs.io][15])

## 7.1 compiler.py

```python
from __future__ import annotations

from pathlib import Path
from seekflow_engineering_tools.ir.cad import CADPartSpec


class CadQueryCompileError(RuntimeError):
    pass


def compile_cad_ir_to_cadquery_script(spec: CADPartSpec, out_step: str | None = None) -> str:
    lines = [
        "import cadquery as cq",
        "from cadquery import exporters",
        "",
        "result = None",
    ]

    for feature in spec.features:
        if feature.type == "recipe":
            lines.extend(_compile_recipe(feature))
        elif feature.type == "extrude":
            lines.extend(_compile_extrude(feature))
        elif feature.type == "hole":
            lines.extend(_compile_hole(feature))
        elif feature.type == "circular_pattern_holes":
            lines.extend(_compile_circular_pattern_holes(feature))
        else:
            raise CadQueryCompileError(f"Unsupported feature type for cadquery: {feature.type}")

    if out_step:
        lines.append(f'exporters.export(result, r"{out_step}")')

    return "\n".join(lines)
```

## 7.2 recipes.py 示例：flanged_hub

```python
def cadquery_flanged_hub(params: dict) -> str:
    return f"""
flange_dia = {params["flange_dia_mm"]}
flange_t = {params["flange_thickness_mm"]}
hub_dia = {params["hub_dia_mm"]}
hub_h = {params["hub_height_mm"]}
bore_dia = {params["bore_dia_mm"]}
bolt_pcd = {params["bolt_pcd_mm"]}
bolt_dia = {params["bolt_dia_mm"]}
bolt_count = {params["bolt_count"]}

result = (
    cq.Workplane("XY")
    .circle(flange_dia / 2).extrude(flange_t)
    .faces(">Z").workplane()
    .circle(hub_dia / 2).extrude(hub_h)
    .faces(">Z").workplane()
    .hole(bore_dia)
    .faces(">Z").workplane()
    .polarArray(bolt_pcd / 2, 0, 360, bolt_count)
    .hole(bolt_dia)
)
"""
```

## 7.3 inspector.py

先实现 STEP 文件存在、bbox、体积、solid count：

```python
def inspect_cadquery_shape(shape) -> dict:
    bb = shape.val().BoundingBox()
    return {
        "bbox_mm": [bb.xlen, bb.ylen, bb.zlen],
        "volume_mm3": shape.val().Volume(),
        "solid_count": len(shape.solids().vals()),
    }
```

如果只能 inspect STEP：

```python
def inspect_step_with_cadquery(step_path: Path) -> dict:
    import cadquery as cq
    obj = cq.importers.importStep(str(step_path))
    return inspect_cadquery_shape(obj)
```

## 7.4 新增工具

`cadquery_backend/tools.py`：

```text
cadquery_build_from_cad_ir
cadquery_inspect_step
cadquery_compile_cad_ir_to_script
```

注意要把 `EngineeringActionResult.software` 扩展为：

```python
Literal["solidworks", "nx", "ansys", "cadquery", "generic"]
```

---

# 8. 第五阶段：统一自然语言建模工具

新增：

```text
src/seekflow_engineering_tools/natural_language/
  __init__.py
  tools.py
  normalizer.py
  prompts.py
```

## 8.1 新工具：engineering_validate_cad_ir

输入：

```python
def engineering_validate_cad_ir(spec: dict) -> dict:
```

行为：

1. `CADPartSpec.model_validate(spec)`
2. 检查 backend capability
3. 检查 recipe 参数完整性
4. 返回规范化 spec 或错误列表

返回：

```json
{
  "ok": true,
  "software": "generic",
  "action": "validate_cad_ir",
  "metrics": {
    "normalized_spec": {},
    "feature_count": 5,
    "target_backend": ["solidworks2025"]
  }
}
```

## 8.2 新工具：engineering_build_cad_model

输入：

```python
def engineering_build_cad_model(
    spec: dict,
    backend: str,
    out_native: str | None = None,
    out_step: str | None = None,
    inspect: bool = True,
) -> dict:
```

路由逻辑：

```python
if backend == "cadquery":
    build via cadquery compiler
elif backend == "solidworks2025":
    if spec is single recipe flanged_hub:
        call SolidWorksClient.create_flanged_hub
    elif spec is single recipe spur_gear:
        call SolidWorksClient.create_spur_gear
    elif spec is box:
        call create_extruded_box
    else:
        fallback compile to cadquery STEP, then optionally import/export through SolidWorks
elif backend == "nx12":
    if recipe in existing NX handlers:
        submit NX job
    else:
        fallback cadquery STEP
```

第一版不要强行支持所有低级 feature 到 SW/NX。先做到：

| recipe          | cadquery | SolidWorks | NX |
| --------------- | -------: | ---------: | -: |
| box             |        ✅ |          ✅ |  ✅ |
| block_with_hole |        ✅ |         后续 |  ✅ |
| l_bracket       |        ✅ |         后续 |  ✅ |
| stepped_block   |        ✅ |         后续 |  ✅ |
| flanged_hub     |        ✅ |          ✅ | 后续 |
| spur_gear       |        ✅ |          ✅ | 后续 |

---

# 9. 第六阶段：Capability Registry

新增：

```text
src/seekflow_engineering_tools/capabilities/
  __init__.py
  registry.py
  capability_registry.yaml
```

`capability_registry.yaml`：

```yaml
solidworks2025:
  software: solidworks
  version: "2025"
  units_api: m
  units_ir: mm
  stable_recipes:
    - box
    - flanged_hub
    - spur_gear
  experimental_features:
    - cut_extrude
    - fillet
  exports:
    - sldprt
    - step
  caveats:
    - "Complex features must go through strict VBS recipe wrappers."
    - "Do not call FeatureExtrusion2 directly from LLM-generated Python."

nx12:
  software: nx
  version: "12.0"
  units_api: mm
  units_ir: mm
  stable_recipes:
    - box
    - block_with_hole
    - l_bracket
    - stepped_block
  exports:
    - prt
    - step
  caveats:
    - "NXOpen must run inside NX bridge journal."
    - "External Python submits JSON jobs only."

ansys181:
  software: ansys
  version: "18.1"
  units_ir: "mm,N,MPa"
  stable_templates:
    - static_cantilever_beam_rect
    - plate_with_hole_tension
    - beam_thermal
    - cantilever_modal
    - buckling_column
    - bilinear_plastic
  caveats:
    - "Use APDL batch only."
    - "Do not use PyMAPDL gRPC for ANSYS 18.1."

cadquery:
  software: cadquery
  units_ir: mm
  stable_recipes:
    - box
    - cylinder
    - block_with_hole
    - l_bracket
    - stepped_block
    - flanged_hub
    - spur_gear
    - shaft_basic
    - shaft_with_keyway
  exports:
    - step
    - stl
  caveats:
    - "No native SolidWorks or NX feature tree."
```

`registry.py`：

```python
def backend_supports_recipe(backend: str, recipe: str) -> bool: ...
def get_backend_caveats(backend: str) -> list[str]: ...
def choose_backend(spec: CADPartSpec, preferred: list[str] | None = None) -> str: ...
```

---

# 10. 第七阶段：Inspector 与 Validation

新增：

```text
src/seekflow_engineering_tools/inspection/
  __init__.py
  common.py
  validation.py
  cadquery_inspector.py
  solidworks_inspector.py
  nx_inspector.py
```

## 10.1 common.py

```python
from pydantic import BaseModel, Field


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


class ValidationIssue(BaseModel):
    code: str
    message: str
    expected: object | None = None
    actual: object | None = None
    severity: str = "error"


class ValidationReport(BaseModel):
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    inspection: ModelInspection | None = None
```

## 10.2 validation.py

```python
def validate_inspection_against_spec(inspection: ModelInspection, spec: CADPartSpec) -> ValidationReport:
    issues = []

    if spec.validation.expected_bbox_mm and inspection.bbox_mm:
        tol = spec.validation.tolerance_mm
        for axis, exp, act in zip("XYZ", spec.validation.expected_bbox_mm, inspection.bbox_mm):
            if abs(exp - act) > tol:
                issues.append(ValidationIssue(
                    code="bbox_mismatch",
                    message=f"BBox {axis} mismatch",
                    expected=exp,
                    actual=act,
                ))

    if spec.validation.expected_body_count is not None and inspection.body_count is not None:
        if spec.validation.expected_body_count != inspection.body_count:
            issues.append(...)

    return ValidationReport(ok=not issues, issues=issues, inspection=inspection)
```

## 10.3 第一版验收标准

对 `flanged_hub`：

```yaml
expected_bbox_mm: [80, 80, 40]
expected_body_count: 1
expected_through_hole_count: 5
tolerance_mm: 0.2
```

CadQuery inspector 先能验 bbox 和 body_count。孔数量估计可以第二版实现。

---

# 11. 第八阶段：Repair Loop

新增：

```text
src/seekflow_engineering_tools/repair/
  __init__.py
  loop.py
  diagnostics.py
```

第一版不直接调用外部 LLM，只提供结构化诊断对象，供上层 agent 看到后修。

`diagnostics.py`：

```python
def build_repair_prompt(spec: dict, result: dict, validation_report: dict) -> str:
    return f"""
The CAD build failed or validation failed.

Original CAD-IR:
{json.dumps(spec, ensure_ascii=False, indent=2)}

Execution result:
{json.dumps(result, ensure_ascii=False, indent=2)}

Validation report:
{json.dumps(validation_report, ensure_ascii=False, indent=2)}

Return ONLY a corrected CAD-IR JSON. Do not write backend API code.
"""
```

`loop.py`：

```python
def run_build_once(spec: CADPartSpec, backend: str, ...): ...
def classify_failure(result: EngineeringActionResult | dict) -> dict: ...
```

返回错误必须包含：

```json
{
  "stage": "compile|execute|inspect|validate",
  "feature_id": "bolt_holes",
  "error_type": "selection_failed|export_failed|bbox_mismatch|missing_file",
  "suggested_fix": "..."
}
```

---

# 12. 第九阶段：Claude Code Skills

新增：

```text
.claude/
  skills/
    nl-cad-core/
      SKILL.md
      cad_ir_schema_excerpt.md
      examples/
        flanged_hub.yaml
        l_bracket.yaml
        block_with_hole.yaml
    solidworks-2025/
      SKILL.md
      known_errors.md
      recipes.md
    nx12/
      SKILL.md
      known_errors.md
      recipes.md
    ansys181/
      SKILL.md
      templates.md
      known_errors.md
    engineering-implementation/
      SKILL.md
```

## 12.1 `.claude/skills/nl-cad-core/SKILL.md`

```markdown
---
name: nl-cad-core
description: Use when implementing or generating structured CAD-IR for natural language mechanical modeling.
---

# NL-CAD Core Rules

You must not generate SolidWorks COM, NXOpen, or APDL directly from natural language.

Always convert modeling intent into CAD-IR first.

CAD-IR v0.1 constraints:
- Units are mm.
- Every feature must have a unique id.
- Prefer recipe features for common mechanical parts.
- Use validation expectations whenever dimensions are known.
- If required dimensions are missing, return ambiguities rather than guessing.
- Backend-specific compilers handle software APIs.

Preferred recipes:
- box
- cylinder
- block_with_hole
- l_bracket
- stepped_block
- flanged_hub
- spur_gear
- shaft_basic
- shaft_with_keyway

When editing code, add tests for:
- schema validation
- compiler output
- workspace path safety
- EngineeringActionResult shape
```

## 12.2 `.claude/skills/solidworks-2025/SKILL.md`

```markdown
---
name: solidworks-2025
description: Use when implementing SolidWorks 2025 automation in this repository.
---

# SolidWorks 2025 Rules

SolidWorks tool parameters use mm. SolidWorks COM/VBS internal values use meters.

Never allow LLM-generated freeform calls to:
- FeatureExtrusion2
- FeatureCut4
- FeatureFillet2

All complex calls must be wrapped in recipe methods.

Current stable recipes:
- box
- flanged_hub
- spur_gear

Technical constraints:
- Use strict VBS wrappers.
- Every VBS operation must be followed by CheckErr.
- Do not use best-effort returns for modeling features.
- Do not return success unless the output file exists.
- Export STEP must verify the STEP file exists and has non-zero size.
```

## 12.3 `.claude/skills/nx12/SKILL.md`

```markdown
---
name: nx12
description: Use when implementing Siemens NX 12.0 bridge and tools.
---

# NX 12.0 Rules

External Python cannot import NXOpen directly. It must submit JSON jobs to the NX bridge.

Version text must say NX 12.0, not NX 18.0.

Current stable bridge actions:
- create_block_part
- create_block_with_hole
- create_l_bracket
- create_stepped_block
- export_step

Rules:
- Add heartbeat detection.
- Health check must report whether bridge is alive.
- Do not swallow STEP export errors.
- Job result must include action, files_created, metrics, and error if any.
- Keep NX bridge Python 3.6 compatible.
```

## 12.4 `.claude/skills/ansys181/SKILL.md`

```markdown
---
name: ansys181
description: Use when implementing ANSYS 18.1 Mechanical APDL batch tools.
---

# ANSYS 18.1 Rules

Use APDL batch via ansys181.exe. Do not use PyMAPDL gRPC for ANSYS 18.1.

Built-in templates:
- static_cantilever_beam_rect
- plate_with_hole_tension
- beam_thermal
- cantilever_modal
- buckling_column
- bilinear_plastic

Every template must expose:
- analysis_type
- units
- parameters
- result metrics
- validation expectations

Every run must parse:
- *** ERROR ***
- *** WARNING ***
- result_summary.txt if present
- stdout_tail
- stderr_tail
```

---

# 13. 第十阶段：自然语言建模规范 NL-CAD v0.1

这部分用于用户输入，也用于 Claude Code 写文档。

## 13.1 用户推荐输入模板

```yaml
nlcad_version: "0.1"

part:
  name: "flanged_hub"
  units: "mm"
  target_backend: ["solidworks2025", "cadquery"]

intent:
  summary: "创建一个法兰轮毂，中心通孔，4 个螺栓孔，导出 STEP 和 SolidWorks 原生文件。"

parameters:
  flange_dia_mm: 80
  flange_thickness_mm: 12
  hub_dia_mm: 40
  hub_height_mm: 28
  bore_dia_mm: 20
  bolt_pcd_mm: 60
  bolt_dia_mm: 8
  bolt_count: 4

features:
  - id: "main"
    type: "recipe"
    recipe_name: "flanged_hub"
    parameters:
      flange_dia_mm: 80
      flange_thickness_mm: 12
      hub_dia_mm: 40
      hub_height_mm: 28
      bore_dia_mm: 20
      bolt_pcd_mm: 60
      bolt_dia_mm: 8
      bolt_count: 4

validation:
  expected_bbox_mm: [80, 80, 40]
  expected_body_count: 1
  expected_through_hole_count: 5
  tolerance_mm: 0.2

outputs:
  native: true
  step: true
  stl: false
```

## 13.2 不完整自然语言的处理

如果用户说：

```text
帮我建一个带孔法兰
```

模型不应直接生成 API。应输出：

```json
{
  "ambiguities": [
    "缺少法兰外径",
    "缺少法兰厚度",
    "缺少中心孔直径",
    "缺少螺栓孔数量",
    "缺少螺栓孔直径",
    "缺少螺栓孔分布圆直径 PCD"
  ],
  "suggested_template": "flanged_hub"
}
```

只有用户明确允许默认值时，才使用默认参数。

---

# 14. 第十一阶段：ANSYS CAE-IR 与模板 schema

新增：

```text
src/seekflow_engineering_tools/ansys/template_registry.py
```

内容：

```python
ANSYS_TEMPLATE_SCHEMAS = {
    "static_cantilever_beam_rect": {
        "analysis_type": "static_structural",
        "units": "mm,N,MPa",
        "parameters": {
            "length_mm": {"type": "float", "required": True, "min": 1},
            "width_mm": {"type": "float", "required": True, "min": 0.1},
            "height_mm": {"type": "float", "required": True, "min": 0.1},
            "force_n": {"type": "float", "required": True},
            "element_size_mm": {"type": "float", "required": False, "default": 10.0},
        },
        "metrics": ["max_displacement_mm", "max_von_mises_mpa"],
    },
    "plate_with_hole_tension": {
        "analysis_type": "static_structural",
        "units": "mm,N,MPa",
        "parameters": {
            "plate_width_mm": {"type": "float", "default": 200.0},
            "plate_height_mm": {"type": "float", "default": 100.0},
            "plate_thickness_mm": {"type": "float", "default": 10.0},
            "hole_diameter_mm": {"type": "float", "default": 20.0},
            "tensile_stress_mpa": {"type": "float", "default": 100.0},
            "element_size_mm": {"type": "float", "default": 5.0},
        },
        "metrics": ["max_von_mises_mpa", "stress_concentration_factor"],
    },
}
```

然后 `ansys_run_apdl_template` 在 render 前校验参数：

```python
from seekflow_engineering_tools.ansys.template_registry import validate_template_parameters

params = validate_template_parameters(template_name, parameters)
apdl = render_template(template_name, **params)
```

如果 summary 不存在，不应直接 `parse_result_summary(summary_path)` 报错，而应：

```python
metrics = {}
warnings = []
if summary_path.exists():
    metrics = parse_result_summary(summary_path)
else:
    warnings.append("result_summary.txt was not generated.")
```

---

# 15. 第十二阶段：Tests / Golden Models

新增：

```text
tests/
  test_cad_ir_schema.py
  test_recipe_registry.py
  test_cadquery_backend.py
  test_engineering_build_cad_model.py
  test_solidworks_recipe_tools_mock.py
  test_nx_recipe_tools_mock.py
  test_ansys_template_registry.py
  golden_models/
    flanged_hub.yaml
    l_bracket.yaml
    block_with_hole.yaml
    stepped_block.yaml
    spur_gear.yaml
```

## 15.1 test_cad_ir_schema.py

```python
def test_flanged_hub_recipe_validates():
    spec = CADPartSpec.model_validate({
        "name": "hub",
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
                "bolt_count": 4,
            }
        }]
    })
    assert spec.name == "hub"
```

## 15.2 test_recipe_registry.py

```python
def test_registry_knows_core_recipes():
    names = set(list_recipe_names())
    assert "flanged_hub" in names
    assert "l_bracket" in names
    assert "block_with_hole" in names
```

## 15.3 test_nx_recipe_tools_mock.py

mock `NXJobQueue.submit`，检查 action：

```python
def test_nx_l_bracket_submits_correct_action(monkeypatch, tmp_path):
    submitted = {}

    class FakeQueue:
        def __init__(self, root): pass
        def submit(self, action, params):
            submitted["action"] = action
            submitted["params"] = params
            return "job1"
        def wait(self, job_id, timeout_s):
            return {"ok": True, "files_created": ["x.prt"], "metrics": {}}

    monkeypatch.setattr("seekflow_engineering_tools.nx.tools.NXJobQueue", FakeQueue)
    ...
    assert submitted["action"] == "create_l_bracket"
```

## 15.4 test_ansys_template_registry.py

```python
def test_ansys_tool_description_lists_all_templates():
    from seekflow_engineering_tools.ansys.apdl_templates import list_templates
    assert len(list_templates()) == 6
```

---

# 16. 第十三阶段：对现有代码的具体改造优先级

## P0：1 天内完成

1. NX 全局版本描述修正为 NX 12.0。
2. ANSYS tool 描述列出 6 个模板。
3. 新增 `ansys_list_apdl_templates`。
4. SolidWorks 暴露 `flanged_hub` 和 `spur_gear`。
5. NX 暴露 `block_with_hole`、`l_bracket`、`stepped_block`。
6. 所有新工具返回 `EngineeringActionResult`。
7. 新增 mock tests。

这是收益最高的一步，因为几乎不需要写底层 CAD API，只是把已存在能力暴露给 LLM。

## P1：3–5 天完成

1. 新增 `ir/cad.py`、`ir/cae.py`。
2. 新增 recipe registry。
3. 新增 capability registry。
4. 新增 `engineering_validate_cad_ir`。
5. 新增 `.claude/skills`。
6. 新增 golden YAML。

## P2：1 周完成

1. 新增 CadQuery backend。
2. 实现 `flanged_hub`、`l_bracket`、`block_with_hole`、`stepped_block`、`spur_gear` 的 CadQuery fallback。
3. 新增 STEP inspect。
4. 新增 validation report。
5. `engineering_build_cad_model` 支持 cadquery backend。

## P3：2–3 周完成

1. SolidWorks strict VBS runtime 重构。
2. 去掉所有 best-effort success。
3. SolidWorks inspector 初版：bbox、mass、feature count。
4. NX heartbeat。
5. NX 不再吞 STEP export 错误。
6. NX inspector 初版。
7. ANSYS template schema + result validator。

## P4：1–2 个月完成

1. SolidWorks C# COM local service 或 add-in。
2. NX 文件队列升级 TCP/named pipe。
3. 低级 feature compiler：extrude、cut、hole、pattern、fillet。
4. 自动 repair loop 接入上层 LLM。
5. 建立自然语言 benchmark 数据集。

---

# 17. 为什么这套方案能提高成功率

现在的失败模式是：

```text
LLM 看到“做复杂模型”
→ 不知道工具能力边界
→ 瞎编 API
→ 工具执行失败或静默失败
→ 没有几何校验
```

改完后的模式是：

```text
LLM 看到“做复杂模型”
→ 先选 recipe / CAD-IR
→ schema 校验
→ capability registry 选择后端
→ backend 只执行已测试 recipe
→ inspector 验证 bbox/孔/体积/文件
→ 失败时返回结构化修复信息
```

这会显著减少 hallucination，因为 LLM 的自由度从“三套复杂软件 API”被压缩到“有限、可验证的建模 DSL”。

---

# 18. 最终验收标准

Claude Code 完成后，必须满足：

```bash
cd integrations/engineering_tools
pytest
```

必须新增并通过以下验收：

```bash
pytest tests/test_cad_ir_schema.py
pytest tests/test_recipe_registry.py
pytest tests/test_cadquery_backend.py
pytest tests/test_nx_recipe_tools_mock.py
pytest tests/test_solidworks_recipe_tools_mock.py
pytest tests/test_ansys_template_registry.py
```

手工 smoke test：

```python
from seekflow_engineering_tools.ir.cad import CADPartSpec
from seekflow_engineering_tools.natural_language.tools import engineering_build_cad_model

spec = {
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
        "expected_through_hole_count": 5,
        "tolerance_mm": 0.2
    }
}

result = engineering_build_cad_model(
    spec=spec,
    backend="cadquery",
    out_step="models/hub_demo.step",
    inspect=True,
)

assert result["ok"] is True
```

商业软件环境 smoke test：

```text
SolidWorks:
- solidworks_create_flanged_hub_part 能生成 .sldprt 和 .step
- solidworks_create_spur_gear_part 能生成 .sldprt 和 .step
- 失败时不允许返回 ok=true

NX:
- nx_health_check 能报告 bridge_running
- nx_create_l_bracket 能生成 .prt
- nx_create_block_with_hole 能生成 .prt
- STEP 导出失败必须进入 warnings/error，不得静默 pass

ANSYS:
- ansys_list_apdl_templates 返回 6 个模板
- ansys_run_apdl_template 可运行 plate_with_hole_tension
- summary 不存在时返回 warning，而不是 traceback
```

---

# 19. 最应该先交给 Claude Code 的执行指令

下面这段可以直接复制给 Claude Code：

```markdown
请在 integrations/engineering_tools 中实现 P0+P1：

1. 修正所有 NX 18.0 / UG 18.0 描述为 NX 12.0。
2. 在 ansys/tools.py 中新增 ansys_list_apdl_templates，并修正 ansys_run_apdl_template 描述，使其列出 apdl_templates.py 中的 6 个模板。
3. 在 solidworks/tools.py 中新增 solidworks_create_flanged_hub_part 与 solidworks_create_spur_gear_part，调用 com_client.py 已有 create_flanged_hub 和 create_spur_gear。
4. 在 nx/tools.py 中新增 nx_create_block_with_hole、nx_create_l_bracket、nx_create_stepped_block，调用 nx_bridge_bootstrap.py 已有 action handlers。
5. 新增 ir/cad.py 和 ir/cae.py，使用 Pydantic v2 定义 CADPartSpec 和 CAEJobSpec。
6. 新增 recipes/base.py、recipes/registry.py、recipes/mechanical.py，注册 box、block_with_hole、l_bracket、stepped_block、flanged_hub、spur_gear。
7. 新增 capabilities/capability_registry.yaml 与 registry.py。
8. 新增 .claude/skills/nl-cad-core、solidworks-2025、nx12、ansys181 的 SKILL.md。
9. 新增 tests：test_cad_ir_schema.py、test_recipe_registry.py、test_nx_recipe_tools_mock.py、test_solidworks_recipe_tools_mock.py、test_ansys_template_registry.py。
10. 保持现有 API 不破坏，所有工具继续返回 EngineeringActionResult.model_dump()。
11. 没有商业软件时，测试必须使用 mock，不得依赖本机安装 SolidWorks/NX/ANSYS。
12. 跑 pytest 并修复失败。
```

这一步完成后，你的系统就已经从“只能建方块”变成“至少能稳定建法兰、齿轮、带孔块、L 支架、阶梯块，并且 LLM 知道这些能力存在”。

下一步再让 Claude Code 实现 P2，也就是 CadQuery fallback + inspector。

[1]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools "seekflow-engineering/integrations/engineering_tools at main · WYZAAACCC/seekflow-engineering · GitHub"
[2]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/config.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/config.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[3]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/common/models.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/common/models.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/tools.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/com_client.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/INTEGRATION_ARCHITECTURE.md "raw.githubusercontent.com"
[7]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx/tools.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/nx/tools.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[8]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx/nx_bridge_bootstrap.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/nx/nx_bridge_bootstrap.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[9]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/ansys/tools.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/ansys/tools.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[10]: https://github.com/WYZAAACCC/seekflow-engineering/blob/main/integrations/engineering_tools/src/seekflow_engineering_tools/ansys/apdl_templates.py "seekflow-engineering/integrations/engineering_tools/src/seekflow_engineering_tools/ansys/apdl_templates.py at main · WYZAAACCC/seekflow-engineering · GitHub"
[11]: https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/ans_ope/Hlp_G_OPE3.html?utm_source=chatgpt.com "Chapter 4: Running the Mechanical APDL Program"
[12]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/tests "seekflow-engineering/integrations/engineering_tools/tests at main · WYZAAACCC/seekflow-engineering · GitHub"
[13]: https://cadquery.readthedocs.io/?utm_source=chatgpt.com "CadQuery Documentation — CadQuery Documentation"
[14]: https://code.claude.com/docs/en/skills?utm_source=chatgpt.com "Extend Claude with skills - Claude Code Docs"
[15]: https://cadquery.readthedocs.io/en/latest/importexport.html?utm_source=chatgpt.com "Importing and Exporting Files - CadQuery Documentation"
