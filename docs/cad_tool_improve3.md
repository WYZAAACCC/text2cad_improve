

# SeekFlow Engineering 修复与改进实施方案 v4

## 0. 本次深度检查结论

当前仓库已经比早期版本好很多：`registry.py` 已经接入 `build_cadquery_tools` 和 `build_natural_language_tools`，并扩展了 `cad.ir.*`、`cad.cadquery.*`、`cad.generic.*` capability。也就是说，LLM 理论上已经能看到自然语言 CAD-IR 工具和 CadQuery 工具。([GitHub][1])

但核心链条仍没有真正跑通。`engineering_build_cad_model` 只真正执行 CadQuery；当 backend 选择 `solidworks2025` 或 `nx12` 时，它仍返回错误，提示用户改用 `solidworks_create_*` 或 `nx_create_*` 工具。这不满足“统一自然语言建模入口”的要求。([GitHub][2])

`cadquery_backend/builder.py` 已能编译脚本、执行脚本、检查 STEP、做 inspection/validation，但默认脚本路径仍使用 `tempfile.mktemp`，脚本会写到 workspace 外；并且 builder 里自写了 `_run_inspection`，没有使用统一的 `inspection/validation.py`。([GitHub][3])

NX 侧还有两个 P0 级 bug：`nx_bridge_bootstrap.py` 需要确认 handler 的 `ok=False` 不会被外层覆盖成成功，并且 STEP export 不能把 `InputFile` 设置成输出 STEP 路径。当前 raw 文件被 GitHub 压缩成单行，无法逐行引用，但上次检查到的风险仍必须作为强制修复项处理。([GitHub][4])

测试仍严重不足。GitHub tests 目录仍只显示旧的 5 个测试，没有 CAD-IR、recipe、capability、CadQuery build、natural language build、NX heartbeat、ANSYS validation、inspection validation 等新架构测试。([GitHub][5])

---

# 1. Claude Code 必须达成的最终形态

必须把系统修成：

```text
自然语言 / 结构化建模需求
→ engineering_validate_cad_ir
→ CADPartSpec
→ Recipe 参数标准化
→ Capability backend 选择
→ engineering_build_cad_model
→ 后端真实执行：
   - cadquery: 生成 STEP
   - solidworks2025: 调用 SolidWorks recipe
   - nx12: 提交 NX bridge job
→ 输出文件存在且非空
→ inspect
→ validation
→ EngineeringActionResult
→ repair_diagnostics
```

绝对禁止：

```text
1. 只生成脚本但不执行。
2. 文件不存在时返回 ok=true。
3. SolidWorks/NX backend 返回“请使用别的工具”。
4. handler 失败被外层包装成成功。
5. validation 缺数据时静默通过。
6. 新模块没有测试。
7. 新架构没有接入 build_engineering_tools。
```

---

# 2. P0：必须优先修复的硬伤

## P0-1：`engineering_build_cad_model` 必须真正支持 SolidWorks 和 NX

### 当前问题

`engineering_build_cad_model` 目前只有 `cadquery` 分支是真执行；`solidworks2025` 和 `nx12` 分支直接返回失败，并提示用户改用其他工具。([GitHub][2])

这会让自然语言主链断裂。LLM 仍需要自己决定直接调用哪个具体工具，无法稳定走：

```text
CAD-IR → backend router → backend build
```

### 必须修改文件

```text
src/seekflow_engineering_tools/natural_language/tools.py
```

### 必须新增内部 builder

新增文件：

```text
src/seekflow_engineering_tools/natural_language/backend_builders.py
```

实现：

```python
from pathlib import Path
from seekflow_engineering_tools.ir.cad import CADPartSpec
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.common.models import EngineeringActionResult
from seekflow_engineering_tools.common.paths import ensure_inside_workspace, ensure_extension
from seekflow_engineering_tools.recipes.registry import normalize_recipe_parameters


def _single_recipe(spec: CADPartSpec):
    if len(spec.features) != 1 or spec.features[0].type != "recipe":
        raise ValueError("Only single recipe CAD-IR is supported for native SolidWorks/NX v1.")
    return spec.features[0]


def build_solidworks_from_cad_ir(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_native: str | None,
    out_step: str | None,
    inspect: bool = True,
) -> dict:
    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

    feat = _single_recipe(spec)
    params = normalize_recipe_parameters(feat.recipe_name, feat.parameters)

    if feat.recipe_name not in {"box", "flanged_hub", "spur_gear"}:
        return EngineeringActionResult(
            ok=False,
            software="solidworks",
            action="build_from_cad_ir",
            error=f"SolidWorks v1 does not support recipe: {feat.recipe_name}",
            metrics={"recipe": feat.recipe_name},
        ).model_dump()

    native_path = ensure_inside_workspace(
        config.workspace_root,
        out_native or f"models/{spec.name}.sldprt",
    )
    ensure_extension(native_path, {".sldprt"})

    step_path = None
    if out_step:
        step_path = ensure_inside_workspace(config.workspace_root, out_step)
        ensure_extension(step_path, {".step", ".stp"})

    client = SolidWorksClient(config.solidworks)
    model = client.new_part()

    if feat.recipe_name == "box":
        client.create_extruded_box(
            model,
            params["length_mm"] / 1000.0,
            params["width_mm"] / 1000.0,
            params["height_mm"] / 1000.0,
        )

    elif feat.recipe_name == "flanged_hub":
        client.create_flanged_hub(
            model,
            flange_dia_m=params["flange_dia_mm"] / 1000.0,
            flange_h_m=params["flange_thickness_mm"] / 1000.0,
            hub_dia_m=params["hub_dia_mm"] / 1000.0,
            hub_h_m=params["hub_height_mm"] / 1000.0,
            bore_dia_m=params["bore_dia_mm"] / 1000.0,
            bolt_pcd_m=params["bolt_pcd_mm"] / 1000.0,
            bolt_dia_m=params["bolt_dia_mm"] / 1000.0,
            bolt_count=params["bolt_count"],
        )

    elif feat.recipe_name == "spur_gear":
        client.create_spur_gear(
            model,
            module_m=params["module_mm"] / 1000.0,
            teeth=params["teeth"],
            face_width_m=params["face_width_mm"] / 1000.0,
            bore_dia_m=params["bore_dia_mm"] / 1000.0,
        )

    client.save_as(model, str(native_path))
    client._assert_file_created(native_path, "SLDPRT")

    files_created = [str(native_path)]

    if step_path:
        client.export_step(model, str(step_path))
        client._assert_file_created(step_path, "STEP")
        files_created.append(str(step_path))

    return EngineeringActionResult(
        ok=True,
        software="solidworks",
        action="build_from_cad_ir",
        message="SolidWorks model created from CAD-IR.",
        files_created=files_created,
        metrics={
            "backend_used": "solidworks2025",
            "recipe": feat.recipe_name,
            "parameters": params,
        },
    ).model_dump()


def build_nx_from_cad_ir(
    spec: CADPartSpec,
    config: EngineeringToolsConfig,
    out_native: str | None,
    out_step: str | None,
    inspect: bool = True,
) -> dict:
    from seekflow_engineering_tools.nx.job_queue import NXJobQueue

    feat = _single_recipe(spec)
    params = normalize_recipe_parameters(feat.recipe_name, feat.parameters)

    action_map = {
        "box": "create_block_part",
        "block_with_hole": "create_block_with_hole",
        "l_bracket": "create_l_bracket",
        "stepped_block": "create_stepped_block",
    }

    if feat.recipe_name not in action_map:
        return EngineeringActionResult(
            ok=False,
            software="nx",
            action="build_from_cad_ir",
            error=f"NX v1 does not support recipe: {feat.recipe_name}",
            metrics={"recipe": feat.recipe_name},
        ).model_dump()

    native_path = ensure_inside_workspace(
        config.workspace_root,
        out_native or f"models/{spec.name}.prt",
    )
    ensure_extension(native_path, {".prt"})

    job_params = dict(params)
    job_params["out_prt"] = str(native_path)

    if out_step:
        step_path = ensure_inside_workspace(config.workspace_root, out_step)
        ensure_extension(step_path, {".step", ".stp"})
        job_params["out_step"] = str(step_path)

    q = NXJobQueue(config.nx.job_queue_root)
    job_id = q.submit(action_map[feat.recipe_name], job_params)
    result = q.wait(job_id, timeout_s=config.nx.job_timeout_s)

    ok = bool(result.get("ok"))
    return EngineeringActionResult(
        ok=ok,
        software="nx",
        action="build_from_cad_ir",
        message="NX model created from CAD-IR." if ok else "NX CAD-IR build failed.",
        files_created=result.get("files_created", []),
        metrics={
            "backend_used": "nx12",
            "recipe": feat.recipe_name,
            "parameters": params,
            "job_id": job_id,
            "nx_result": result,
        },
        error=result.get("error"),
        warnings=result.get("warnings", []),
    ).model_dump()
```

### 修改 `engineering_build_cad_model`

把当前 SolidWorks/NX error return 删除，改成：

```python
from seekflow_engineering_tools.natural_language.backend_builders import (
    build_solidworks_from_cad_ir,
    build_nx_from_cad_ir,
)

if selected == "solidworks2025":
    return build_solidworks_from_cad_ir(
        spec=cad_spec,
        config=config,
        out_native=out_native,
        out_step=out_step,
        inspect=inspect,
    )

if selected == "nx12":
    return build_nx_from_cad_ir(
        spec=cad_spec,
        config=config,
        out_native=out_native,
        out_step=out_step,
        inspect=inspect,
    )
```

### 验收

新增测试：

```text
tests/test_engineering_build_cad_model.py
```

至少覆盖：

```python
def test_build_cad_model_does_not_return_use_other_tool_for_solidworks(monkeypatch, tmp_path):
    ...

def test_build_cad_model_routes_nx_recipe_to_job_queue(monkeypatch, tmp_path):
    ...
```

---

## P0-2：CadQuery builder 禁止写 workspace 外

### 当前问题

`builder.py` 默认使用：

```python
Path(tempfile.mktemp(suffix="_cq_build.py"))
```

这会把脚本放到系统临时目录，违反 workspace 沙箱要求。([GitHub][3])

### 必须修改文件

```text
src/seekflow_engineering_tools/cadquery_backend/builder.py
```

### 必须替换为

```python
if script_out:
    script_path = ensure_inside_workspace(workspace, script_out)
    ensure_extension(script_path, {".py"})
else:
    script_path = step_path.with_suffix(".cadquery_build.py")
    script_path = ensure_inside_workspace(workspace, script_path)
    ensure_extension(script_path, {".py"})
```

删除：

```python
import tempfile
Path(tempfile.mktemp(...))
```

### 验收测试

```python
def test_cadquery_script_path_stays_inside_workspace(tmp_path):
    ...
    result = build_cadquery_from_cad_ir(...)
    script_path = Path(result["metrics"]["script_path"])
    assert tmp_path in script_path.parents or script_path == tmp_path
```

---

## P0-3：CadQuery builder 必须使用统一 inspection/validation

### 当前问题

`builder.py` 自己实现 `_run_inspection`，没有使用 `inspection/validation.py`；而 `inspection/validation.py` 当前只在字段存在时检查，缺失 bbox/body_count 会静默跳过。([GitHub][3])

### 必须修改

`cadquery_backend/inspector.py` 的 `inspect_step_with_cadquery` 可以继续返回 dict，但 builder 必须转换成 `ModelInspection`。

```python
from seekflow_engineering_tools.inspection.common import ModelInspection
from seekflow_engineering_tools.inspection.validation import validate_inspection_against_spec

def _run_inspection(step_path: Path, spec: CADPartSpec) -> dict:
    info = inspect_step_with_cadquery(step_path)

    if info.get("error"):
        inspection = ModelInspection(warnings=[info["error"]])
    else:
        inspection = ModelInspection(
            bbox_mm=info.get("bbox_mm"),
            volume_mm3=info.get("volume_mm3"),
            body_count=info.get("solid_count") or info.get("body_count"),
            face_count=info.get("face_count"),
            edge_count=info.get("edge_count"),
            hole_count_estimate=info.get("hole_count_estimate"),
            through_hole_count_estimate=info.get("through_hole_count_estimate"),
            warnings=info.get("warnings", []),
        )

    report = validate_inspection_against_spec(inspection, spec)

    return {
        "inspection": inspection.model_dump(),
        "validation": report.model_dump(),
    }
```

### 必须修改 validation

文件：

```text
src/seekflow_engineering_tools/inspection/validation.py
```

改为：

```python
def _issue(code, message, expected=None, actual=None, severity="error"):
    return ValidationIssue(
        code=code,
        message=message,
        expected=expected,
        actual=actual,
        severity=severity,
    )


def validate_inspection_against_spec(
    inspection: ModelInspection,
    spec: CADPartSpec,
) -> ValidationReport:
    issues = []
    vs = spec.validation

    if vs.expected_bbox_mm is not None:
        if inspection.bbox_mm is None:
            issues.append(_issue(
                "bbox_missing",
                "expected_bbox_mm was provided but inspector did not return bbox_mm",
                expected=vs.expected_bbox_mm,
                actual=None,
            ))
        else:
            tol = vs.tolerance_mm
            for axis, exp, act in zip("XYZ", vs.expected_bbox_mm, inspection.bbox_mm):
                if abs(exp - act) > tol:
                    issues.append(_issue(
                        "bbox_mismatch",
                        f"BBox {axis} mismatch",
                        expected=exp,
                        actual=act,
                    ))

    if vs.expected_body_count is not None:
        if inspection.body_count is None:
            issues.append(_issue(
                "body_count_missing",
                "expected_body_count was provided but inspector did not return body_count",
                expected=vs.expected_body_count,
                actual=None,
            ))
        elif inspection.body_count != vs.expected_body_count:
            issues.append(_issue(
                "body_count_mismatch",
                "Body count mismatch",
                expected=vs.expected_body_count,
                actual=inspection.body_count,
            ))

    if vs.expected_hole_count is not None:
        if inspection.hole_count_estimate is None:
            issues.append(_issue(
                "hole_count_not_inspected",
                "expected_hole_count was provided but inspector cannot estimate hole count",
                expected=vs.expected_hole_count,
                actual=None,
                severity="warning",
            ))
        elif inspection.hole_count_estimate != vs.expected_hole_count:
            issues.append(_issue(
                "hole_count_mismatch",
                "Hole count mismatch",
                expected=vs.expected_hole_count,
                actual=inspection.hole_count_estimate,
            ))

    if vs.expected_through_hole_count is not None:
        if inspection.through_hole_count_estimate is None:
            issues.append(_issue(
                "through_hole_count_not_inspected",
                "expected_through_hole_count was provided but inspector cannot estimate through holes",
                expected=vs.expected_through_hole_count,
                actual=None,
                severity="warning",
            ))
        elif inspection.through_hole_count_estimate != vs.expected_through_hole_count:
            issues.append(_issue(
                "through_hole_count_mismatch",
                "Through hole count mismatch",
                expected=vs.expected_through_hole_count,
                actual=inspection.through_hole_count_estimate,
            ))

    ok = not any(i.severity == "error" for i in issues)
    return ValidationReport(ok=ok, issues=issues, inspection=inspection)
```

### 验收

```python
def test_bbox_missing_is_error():
    ...

def test_hole_count_missing_is_warning_issue():
    ...
```

---

## P0-4：修复 CadQuery recipe 几何

### 当前问题

`cadquery_l_bracket` 当前通过 `.faces(">Y").workplane().rect(...).extrude(...)` 生成 L 支架，坐标语义不稳定，bbox 不可预测。([GitHub][6])

### 必须修改文件

```text
src/seekflow_engineering_tools/cadquery_backend/recipes.py
```

### 必须替换 `cadquery_l_bracket`

```python
def cadquery_l_bracket(params: dict) -> str:
    bl = params["base_length_mm"]
    bw = params["base_width_mm"]
    t = params["thickness_mm"]
    lh = params["leg_height_mm"]

    return f"""
base = cq.Workplane("XY").box({bl}, {bw}, {t})
leg = (
    cq.Workplane("XY")
    .box({t}, {bw}, {lh})
    .translate((-{bl}/2.0 + {t}/2.0, 0, {t}/2.0 + {lh}/2.0))
)
result = base.union(leg)
"""
```

### 必须确认 stepped block bbox

当前 stepped block 写法大概率可行，但必须加 test：

```text
expected_bbox_mm = [base_length, base_width, base_height + top_height]
expected_body_count = 1
```

### 验收

```python
def test_cadquery_l_bracket_bbox(tmp_path):
    ...

def test_cadquery_stepped_block_bbox(tmp_path):
    ...
```

---

## P0-5：NX bridge 必须尊重 handler 的失败状态

### 当前问题

需要确认 `process_one_job` 是否把 handler 返回的 `ok=False` 继续包装成 `ok=True`。如果是，这是 P0 bug。`nx_bridge_bootstrap.py` 是 NX 内运行 bridge 的核心文件，当前文件说明其作用是监控 pending 并处理 jobs。([GitHub][4])

### 必须修改文件

```text
src/seekflow_engineering_tools/nx/nx_bridge_bootstrap.py
```

### 必须实现逻辑

```python
def process_one_job(job_path):
    ...
    try:
        result_payload = ACTION_HANDLERS[action](session, params)
        payload_ok = bool(result_payload.get("ok", True))

        result = {
            "job_id": job_id,
            "ok": payload_ok,
            "message": "NX job finished." if payload_ok else "NX job failed.",
            "files_created": result_payload.get("files_created", []),
            "metrics": result_payload.get("metrics", {}),
            "warnings": result_payload.get("warnings", []),
            "error": result_payload.get("error"),
        }

        if payload_ok:
            write_result(DONE, job_id, result)
        else:
            write_result(FAILED, job_id, result)

    except Exception as exc:
        write_result(FAILED, job_id, {
            "job_id": job_id,
            "ok": False,
            "error": str(exc),
            "files_created": [],
            "metrics": {},
        })
```

### 验收测试

在不 import NXOpen 的前提下，抽取纯函数：

```python
def wrap_nx_handler_result(job_id: str, payload: dict) -> tuple[str, dict]:
    ...
```

测试：

```python
def test_nx_handler_ok_false_goes_to_failed():
    target_dir, result = wrap_nx_handler_result("j1", {"ok": False, "error": "bad"})
    assert target_dir == "failed"
    assert result["ok"] is False
```

---

## P0-6：修复 NX STEP export

### 当前问题

上次审计发现 bridge 中存在 `step_creator.InputFile = out_step` 的错误模式。即使当前 raw 文件压缩难以逐行展示，也必须全局搜索并修掉。([GitHub][4])

### Claude Code 必须执行

```bash
grep -R "InputFile.*out_step\|InputFile.*OutputFile\|InputFile = out_step" \
  integrations/engineering_tools/src/seekflow_engineering_tools/nx
```

如果存在，必须改。

### 推荐 helper

```python
def assert_nx_file_created(path, label):
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"{label} was not created: {p}")
    if p.stat().st_size <= 0:
        raise RuntimeError(f"{label} is empty: {p}")


def export_display_part_to_step(session, out_step_path):
    import NXOpen

    out_step_path = Path(out_step_path)
    step_creator = session.DexManager.CreateStep214Creator()

    # NX 12 API 可能略有差异；优先使用 DisplayPart export。
    if hasattr(step_creator, "ExportFrom"):
        step_creator.ExportFrom = NXOpen.Step214Creator.ExportFromOption.DisplayPart

    step_creator.OutputFile = str(out_step_path)

    # 禁止 InputFile = out_step_path。
    # 如果 NX 12 必须 InputFile，则应使用当前 DisplayPart 的 FullPath。
    display_part = session.Parts.Display
    if hasattr(step_creator, "InputFile") and getattr(display_part, "FullPath", None):
        step_creator.InputFile = str(display_part.FullPath)

    step_creator.Commit()
    step_creator.Destroy()

    assert_nx_file_created(out_step_path, "STEP")
```

### 所有 create handler 必须

如果 `params["out_step"]` 存在：

```python
export_display_part_to_step(session, params["out_step"])
files_created.append(params["out_step"])
```

不能吞异常，不能 `pass`。

---

## P0-7：NX tools 必须补扩展名和参数校验

### 当前问题

`nx/tools.py` 已暴露复杂工具，但必须确认所有输出路径都经过 `ensure_extension`，所有尺寸做几何约束。否则仍可能把错误参数送入 NX bridge。([GitHub][4])

### 必须修改

文件：

```text
src/seekflow_engineering_tools/nx/tools.py
```

新增 helper：

```python
def _positive(name: str, value: float):
    if value <= 0:
        raise ValueError(f"{name} must be > 0")


def _validate_prt_step(config, out_prt: str, out_step: str | None):
    prt = ensure_inside_workspace(config.workspace_root, out_prt)
    ensure_extension(prt, {".prt"})

    step = None
    if out_step:
        step = ensure_inside_workspace(config.workspace_root, out_step)
        ensure_extension(step, {".step", ".stp"})

    return prt, step
```

每个工具必须调用：

```python
_positive("length_mm", length_mm)
...
```

几何约束：

```python
if hole_dia_mm >= min(width_mm, height_mm):
    raise ValueError("hole_dia_mm must be smaller than min(width_mm, height_mm)")
```

阶梯块：

```python
if top_length_mm > base_length_mm:
    raise ValueError("top_length_mm must be <= base_length_mm")
if top_width_mm > base_width_mm:
    raise ValueError("top_width_mm must be <= base_width_mm")
```

L bracket：

```python
if thickness_mm >= base_length_mm:
    raise ValueError("thickness_mm must be smaller than base_length_mm")
if thickness_mm >= leg_height_mm:
    raise ValueError("thickness_mm must be smaller than leg_height_mm")
```

---

## P0-8：SolidWorks tools 必须补扩展名、文件与几何校验

### 当前问题

`solidworks/tools.py` 已暴露复杂工具，但文件为空或压缩后不易逐行查看；按上次审计，必须确认所有 SolidWorks 工具都用 `ensure_extension`、参数校验、文件存在校验。([GitHub][7])

### 必须修改

文件：

```text
src/seekflow_engineering_tools/solidworks/tools.py
```

新增 helper：

```python
def _positive(name: str, value: float):
    if value <= 0:
        raise ValueError(f"{name} must be > 0")


def _assert_created(path: Path, label: str):
    if not path.exists():
        raise RuntimeError(f"{label} was not created: {path}")
    if path.stat().st_size <= 0:
        raise RuntimeError(f"{label} is empty: {path}")
```

### 所有 SolidWorks 输出必须

```python
out_sldprt_path = ensure_inside_workspace(config.workspace_root, out_sldprt)
ensure_extension(out_sldprt_path, {".sldprt"})

if out_step:
    out_step_path = ensure_inside_workspace(config.workspace_root, out_step)
    ensure_extension(out_step_path, {".step", ".stp"})
```

### flanged_hub 必须检查

```python
_positive("flange_dia_mm", flange_dia_mm)
_positive("flange_thickness_mm", flange_thickness_mm)
_positive("hub_dia_mm", hub_dia_mm)
_positive("hub_height_mm", hub_height_mm)
_positive("bore_dia_mm", bore_dia_mm)
_positive("bolt_pcd_mm", bolt_pcd_mm)
_positive("bolt_dia_mm", bolt_dia_mm)

if not (flange_dia_mm > hub_dia_mm > bore_dia_mm):
    raise ValueError("Require flange_dia_mm > hub_dia_mm > bore_dia_mm")

if bolt_count < 3:
    raise ValueError("bolt_count must be >= 3")

if not (hub_dia_mm < bolt_pcd_mm < flange_dia_mm):
    raise ValueError("Require hub_dia_mm < bolt_pcd_mm < flange_dia_mm")

if bolt_dia_mm >= (flange_dia_mm - bolt_pcd_mm):
    raise ValueError("bolt_dia_mm too large for flange rim")
```

### spur_gear 必须检查

```python
_positive("module_mm", module_mm)
_positive("face_width_mm", face_width_mm)
_positive("bore_dia_mm", bore_dia_mm)

if teeth < 6:
    raise ValueError("teeth must be >= 6")
```

### 保存后必须

```python
client.save_as(model, str(out_sldprt_path))
_assert_created(out_sldprt_path, "SLDPRT")

if out_step_path:
    client.export_step(model, str(out_step_path))
    _assert_created(out_step_path, "STEP")
```

---

## P0-9：SolidWorks VBS 必须逐步 `CheckErr`

### 当前问题

即使有 `_run_vbs_strict`，如果 VBS 内部继续 `On Error Resume Next` 且不逐步检查，失败点仍不可诊断。

### 必须修改文件

```text
src/seekflow_engineering_tools/solidworks/com_client.py
```

### VBS 模板必须包含

```vbscript
Sub CheckErr(stage)
  If Err.Number <> 0 Then
    WScript.StdErr.WriteLine "VBS_ERR|" & stage & "|" & Err.Number & "|" & Err.Description
    WScript.Quit 1
  End If
End Sub
```

关键操作后必须加：

```vbscript
CheckErr "select_front_plane"
CheckErr "insert_sketch"
CheckErr "create_circle"
CheckErr "extrude_feature"
CheckErr "select_top_face"
CheckErr "create_cut"
CheckErr "save_as"
CheckErr "export_step"
```

Python 端 `_run_vbs_strict` 必须检查：

```python
if proc.returncode != 0:
    raise RuntimeError(...)

if "VBS_ERR|" in (proc.stdout or "") or "VBS_ERR|" in (proc.stderr or ""):
    raise RuntimeError(...)
```

禁止：

```python
return True  # best-effort
```

---

## P1-1：Recipe registry 必须返回标准化参数

### 当前问题

`validate_recipe_parameters` 只返回 error list，并没有返回转换后的参数。`"bolt_count": "4"` 可能验证通过，但后续仍是字符串。([GitHub][8])

### 必须修改文件

```text
src/seekflow_engineering_tools/recipes/registry.py
```

### 新增

```python
def normalize_recipe_parameters(recipe_name: str, parameters: dict) -> dict:
    rd = get_recipe_definition(recipe_name)
    if rd is None:
        raise ValueError(f"Unknown recipe: {recipe_name}")

    schema = {p.name: p for p in rd.parameters}
    unknown = set(parameters) - set(schema)
    if unknown:
        raise ValueError(f"Unknown parameters for recipe {recipe_name}: {sorted(unknown)}")

    normalized = {}

    for name, p in schema.items():
        if name in parameters:
            raw = parameters[name]
        elif p.default is not None:
            raw = p.default
        elif p.required:
            raise ValueError(f"Missing required parameter '{name}' for recipe '{recipe_name}'")
        else:
            continue

        if p.type == "float":
            if isinstance(raw, bool):
                raise ValueError(f"{name} must be float, got bool")
            value = float(raw)
        elif p.type == "int":
            if isinstance(raw, bool):
                raise ValueError(f"{name} must be int, got bool")
            value = int(raw)
        elif p.type == "str":
            value = str(raw)
        elif p.type == "bool":
            if not isinstance(raw, bool):
                raise ValueError(f"{name} must be bool")
            value = raw
        else:
            raise ValueError(f"Unsupported recipe parameter type: {p.type}")

        if p.min_value is not None and value < p.min_value:
            raise ValueError(f"{name} value {value} < min {p.min_value}")
        if p.max_value is not None and value > p.max_value:
            raise ValueError(f"{name} value {value} > max {p.max_value}")

        normalized[name] = value

    validate_recipe_geometry(recipe_name, normalized)
    return normalized
```

新增：

```python
def validate_recipe_geometry(recipe_name: str, p: dict) -> None:
    if recipe_name == "flanged_hub":
        if not (p["flange_dia_mm"] > p["hub_dia_mm"] > p["bore_dia_mm"]):
            raise ValueError("Require flange_dia_mm > hub_dia_mm > bore_dia_mm")
        if not (p["hub_dia_mm"] < p["bolt_pcd_mm"] < p["flange_dia_mm"]):
            raise ValueError("Require hub_dia_mm < bolt_pcd_mm < flange_dia_mm")

    if recipe_name == "block_with_hole":
        if p["hole_dia_mm"] >= min(p["width_mm"], p["height_mm"]):
            raise ValueError("hole_dia_mm too large for block")

    if recipe_name == "stepped_block":
        if p["top_length_mm"] > p["base_length_mm"]:
            raise ValueError("top_length_mm must be <= base_length_mm")
        if p["top_width_mm"] > p["base_width_mm"]:
            raise ValueError("top_width_mm must be <= base_width_mm")
```

`validate_recipe_parameters` 可以改成 wrapper：

```python
def validate_recipe_parameters(recipe_name: str, parameters: dict) -> list[str]:
    try:
        normalize_recipe_parameters(recipe_name, parameters)
        return []
    except Exception as exc:
        return [str(exc)]
```

---

## P1-2：Capability registry 必须返回 fallback 信息

### 当前问题

`choose_backend` 当前在 fallback 到 CadQuery 时只返回字符串，warning 不会传递给用户。`engineering_build_cad_model` 因此无法说明“你请求 NX，但实际用了 CadQuery”。([GitHub][2])

### 必须修改文件

```text
src/seekflow_engineering_tools/capabilities/registry.py
```

### 新增 dataclass

```python
from dataclasses import dataclass, field

@dataclass
class BackendChoice:
    backend: str
    fallback_used: bool = False
    requested: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reason: str = ""
```

### 修改 choose_backend

```python
def choose_backend(spec: CADPartSpec, preferred: list[str] | None = None) -> BackendChoice:
    requested = preferred or spec.target_backend or ["cadquery"]

    for backend in requested:
        if _backend_supports_spec(backend, spec):
            return BackendChoice(
                backend=backend,
                requested=requested,
                reason=f"{backend} supports all requested features",
            )

    if _backend_supports_spec("cadquery", spec):
        return BackendChoice(
            backend="cadquery",
            fallback_used=True,
            requested=requested,
            warnings=[
                f"Requested backend(s) {requested} do not support this CAD-IR; fell back to cadquery STEP backend."
            ],
            reason="cadquery supports all requested recipe features",
        )

    return BackendChoice(
        backend="",
        fallback_used=False,
        requested=requested,
        warnings=[f"No backend supports this CAD-IR. Requested: {requested}"],
        reason="unsupported",
    )
```

### 修改调用处

当前代码：

```python
selected = choose_backend(cad_spec, preferred=[backend])
if selected == "cadquery":
```

必须改为：

```python
choice = choose_backend(cad_spec, preferred=[backend])
selected = choice.backend

if not selected:
    return EngineeringActionResult(
        ok=False,
        software="generic",
        action="build_cad_model",
        error=choice.reason,
        warnings=choice.warnings,
    ).model_dump()
```

并把 `choice.warnings` 合并到 backend result。

---

## P1-3：`engineering_validate_cad_ir` 必须返回 normalized spec

### 当前问题

它现在只 `CADPartSpec.model_validate`，然后检查 target backend 是否支持 recipe。([GitHub][2])
但它没有把 recipe 参数标准化，也没有把 `"4"` 转成 `4`。

### 必须修改

在 `engineering_validate_cad_ir` 中：

```python
from seekflow_engineering_tools.recipes.registry import normalize_recipe_parameters

normalized = CADPartSpec.model_validate(spec)

for feat in normalized.features:
    if feat.type == "recipe":
        feat.parameters = normalize_recipe_parameters(feat.recipe_name, feat.parameters)
```

返回：

```python
metrics={
    "normalized_spec": normalized.model_dump(),
    ...
}
```

不要 `exclude_defaults=True`，因为 normalized spec 需要包含默认值，便于后续复现。

---

## P1-4：补 `.claude/skills`

当前仓库 root 下 `.claude/skills` 仍未看到。用户明确要交给 Claude Code，因此必须补。

新增：

```text
.claude/skills/nl-cad-core/SKILL.md
.claude/skills/cadquery-fallback/SKILL.md
.claude/skills/solidworks-2025/SKILL.md
.claude/skills/nx12/SKILL.md
.claude/skills/ansys181/SKILL.md
```

`nl-cad-core/SKILL.md`：

```markdown
---
name: nl-cad-core
description: Use when implementing natural-language-to-CAD logic in this repository.
---

# Mandatory architecture

Natural language must be converted to CAD-IR first.

Required chain:
natural language -> CADPartSpec -> recipe normalization -> capability routing -> backend build -> file verification -> inspection -> validation -> EngineeringActionResult.

Never return ok=true unless output files exist and validation has no error-level issues.

Do not generate SolidWorks COM, NXOpen, or APDL directly from natural language.
```

`cadquery-fallback/SKILL.md`：

```markdown
---
name: cadquery-fallback
description: Use when implementing CadQuery fallback generation and inspection.
---

# Mandatory rules

CadQuery scripts must be written inside workspace_root.
Do not use tempfile.mktemp.
STEP output must exist and be non-empty.
Builder must use ModelInspection and ValidationReport.
Expected bbox/body count missing inspection data is an error.
Hole count not inspected is a warning issue.
```

`nx12/SKILL.md`：

```markdown
---
name: nx12
description: Use when implementing Siemens NX 12.0 bridge jobs.
---

# Mandatory rules

External Python submits JSON jobs only.
NXOpen runs inside nx_bridge_bootstrap.py.
JobQueue must reject unknown actions.
handler ok=false must produce final ok=false and failed job.
STEP export must not use InputFile=out_step.
Health check must report heartbeat.
```

---

# 3. 必须新增的测试清单

当前 tests 目录只有旧测试。([GitHub][5])
必须新增以下文件。

```text
tests/test_natural_language_tools_registered.py
tests/test_cad_ir_schema.py
tests/test_recipe_registry.py
tests/test_capability_registry.py
tests/test_cadquery_backend.py
tests/test_engineering_build_cad_model.py
tests/test_solidworks_recipe_tools_mock.py
tests/test_nx_recipe_tools_mock.py
tests/test_nx_heartbeat.py
tests/test_ansys_template_registry.py
tests/test_ansys_template_validation.py
tests/test_inspection_validation.py
```

最关键的几个测试如下。

## `test_natural_language_tools_registered.py`

```python
def test_required_tools_registered():
    from seekflow_engineering_tools.registry import build_engineering_tools
    from seekflow_engineering_tools.config import EngineeringToolsConfig

    cfg = EngineeringToolsConfig.from_env()
    tools = build_engineering_tools(cfg)
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

## `test_inspection_validation.py`

```python
from seekflow_engineering_tools.inspection.common import ModelInspection
from seekflow_engineering_tools.inspection.validation import validate_inspection_against_spec
from seekflow_engineering_tools.ir.cad import CADPartSpec

def _spec():
    return CADPartSpec.model_validate({
        "name": "x",
        "units": "mm",
        "features": [{
            "id": "main",
            "type": "recipe",
            "recipe_name": "box",
            "parameters": {
                "length_mm": 10,
                "width_mm": 20,
                "height_mm": 30,
            },
        }],
        "validation": {
            "expected_bbox_mm": [10, 20, 30],
            "expected_body_count": 1,
            "expected_through_hole_count": 2,
        },
    })

def test_missing_bbox_is_error():
    report = validate_inspection_against_spec(ModelInspection(body_count=1), _spec())
    assert not report.ok
    assert any(i.code == "bbox_missing" for i in report.issues)

def test_missing_hole_count_is_warning_issue():
    report = validate_inspection_against_spec(
        ModelInspection(bbox_mm=[10, 20, 30], body_count=1),
        _spec(),
    )
    assert report.ok
    assert any(i.code == "through_hole_count_not_inspected" for i in report.issues)
```

## `test_recipe_registry.py`

```python
import pytest
from seekflow_engineering_tools.recipes.registry import normalize_recipe_parameters

def test_normalize_recipe_converts_int_string():
    p = normalize_recipe_parameters("flanged_hub", {
        "flange_dia_mm": "80",
        "flange_thickness_mm": "12",
        "hub_dia_mm": "40",
        "hub_height_mm": "28",
        "bore_dia_mm": "20",
        "bolt_pcd_mm": "60",
        "bolt_dia_mm": "8",
        "bolt_count": "4",
    })
    assert isinstance(p["bolt_count"], int)
    assert p["bolt_count"] == 4
    assert isinstance(p["flange_dia_mm"], float)

def test_flanged_hub_rejects_bad_geometry():
    with pytest.raises(ValueError):
        normalize_recipe_parameters("flanged_hub", {
            "flange_dia_mm": 40,
            "flange_thickness_mm": 12,
            "hub_dia_mm": 80,
            "hub_height_mm": 28,
            "bore_dia_mm": 20,
            "bolt_pcd_mm": 60,
            "bolt_dia_mm": 8,
            "bolt_count": 4,
        })
```

## `test_engineering_build_cad_model.py`

```python
def test_cadquery_build_model_creates_step(tmp_path):
    import pytest
    pytest.importorskip("cadquery")

    from seekflow_engineering_tools.config import EngineeringToolsConfig
    from seekflow_engineering_tools.natural_language.tools import build_natural_language_tools

    cfg = EngineeringToolsConfig(workspace_root=tmp_path)
    tools = build_natural_language_tools(cfg)
    build_tool = next(t for t in tools if t.name == "engineering_build_cad_model")

    spec = {
        "name": "box_demo",
        "units": "mm",
        "target_backend": ["cadquery"],
        "features": [{
            "id": "main",
            "type": "recipe",
            "recipe_name": "box",
            "parameters": {
                "length_mm": 10,
                "width_mm": 20,
                "height_mm": 30,
            },
        }],
        "validation": {
            "expected_bbox_mm": [10, 20, 30],
            "expected_body_count": 1,
            "tolerance_mm": 0.5,
        },
    }

    result = build_tool(spec=spec, backend="cadquery", out_step="models/box.step")
    assert result["ok"] is True
    assert (tmp_path / "models" / "box.step").exists()
```

---

# 4. 最终验收命令

Claude Code 完成后必须运行：

```bash
cd integrations/engineering_tools
pytest
```

必须运行：

```bash
grep -R "tempfile.mktemp" src
```

结果必须为空。

必须运行：

```bash
grep -R "InputFile.*out_step\|InputFile = out_step" src/seekflow_engineering_tools/nx
```

结果必须为空。

必须验证工具：

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

assert not (required - names), required - names
```

---

# 5. 给 Claude Code 的强制执行提示

```markdown
你必须继续修复 integrations/engineering_tools，目标是把已有脚手架变成可执行闭环。

不要只做表面修改。不要只新增文件名。不要返回假成功。

必须完成：

1. engineering_build_cad_model 必须真正支持 cadquery、solidworks2025、nx12。
   - cadquery：真实生成 STEP。
   - solidworks2025：路由单 recipe：box、flanged_hub、spur_gear。
   - nx12：路由单 recipe：box、block_with_hole、l_bracket、stepped_block。
   - 不允许再返回 “Use solidworks_create_* tools” 或 “Use nx_create_* tools”。

2. cadquery_backend/builder.py
   - 删除 tempfile.mktemp。
   - 默认脚本路径必须在 workspace 内。
   - 使用 inspection.common.ModelInspection 和 inspection.validation.validate_inspection_against_spec。
   - 不允许自写一套 dict validation 替代统一 validation。

3. cadquery_backend/recipes.py
   - 修复 l_bracket，用 base.union(leg) 明确生成 L 形支架。
   - 给 l_bracket、stepped_block、flanged_hub 增加 bbox/body_count golden tests。

4. inspection/validation.py
   - expected_bbox_mm 存在但 bbox 缺失 → error。
   - expected_body_count 存在但 body_count 缺失 → error。
   - expected_hole_count / expected_through_hole_count 存在但无法估计 → warning issue。
   - ok 只在没有 severity="error" 时为 True。

5. nx/nx_bridge_bootstrap.py
   - handler 返回 ok=False 时最终 job 必须 ok=False，并写入 failed。
   - 修复所有 STEP export，禁止 InputFile=out_step。
   - STEP 导出后检查文件存在且非空。

6. nx/tools.py
   - 所有 out_prt 必须 ensure_extension .prt。
   - 所有 out_step 必须 ensure_extension .step/.stp。
   - 所有尺寸必须 >0。
   - block_with_hole、stepped_block、l_bracket 必须做几何约束。

7. solidworks/tools.py
   - 所有 out_sldprt 必须 ensure_extension .sldprt。
   - 所有 out_step 必须 ensure_extension .step/.stp。
   - flanged_hub、spur_gear 必须做几何约束。
   - save/export 后必须检查文件存在且非空。

8. solidworks/com_client.py
   - 所有关键 VBS 操作后加 CheckErr(stage)。
   - _run_vbs_strict 检查 returncode、stdout/stderr 中的 VBS_ERR。
   - 删除 return True # best-effort。

9. recipes/registry.py
   - 新增 normalize_recipe_parameters。
   - 进行默认值填充、类型转换、min/max、跨参数几何约束。
   - engineering_validate_cad_ir 必须返回 normalized spec。

10. capabilities/registry.py
    - choose_backend 返回 BackendChoice，而不是裸字符串。
    - fallback 到 cadquery 时必须把 warning 传到 EngineeringActionResult.warnings。

11. 新增 .claude/skills：
    - nl-cad-core
    - cadquery-fallback
    - solidworks-2025
    - nx12
    - ansys181

12. 新增并通过测试：
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
```

---

# 6. 最终判断

当前仓库已经具备目标架构的雏形，但仍有 6 个会直接导致自然语言建模失败的硬伤：

```text
1. engineering_build_cad_model 不能真正驱动 SolidWorks/NX。
2. CadQuery builder 默认把脚本写到 workspace 外。
3. CadQuery validation 没使用统一 ValidationReport。
4. NX bridge 可能把失败 job 包装成成功。
5. NX STEP export 需要强制排查 InputFile=out_step。
6. 测试与 skills 仍不足。
```

只要按上面 P0/P1 修完，系统才会从“有脚手架”变成“可执行闭环”：
**CAD-IR → recipe normalization → backend routing → real build → file verification → inspection → validation → repair-ready result**。

[1]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/registry.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/natural_language/tools.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/builder.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/nx/nx_bridge_bootstrap.py "raw.githubusercontent.com"
[5]: https://github.com/WYZAAACCC/seekflow-engineering/tree/main/integrations/engineering_tools/tests "seekflow-engineering/integrations/engineering_tools/tests at main · WYZAAACCC/seekflow-engineering · GitHub"
[6]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/cadquery_backend/recipes.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/solidworks/tools.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/seekflow-engineering/main/integrations/engineering_tools/src/seekflow_engineering_tools/recipes/registry.py "raw.githubusercontent.com"
