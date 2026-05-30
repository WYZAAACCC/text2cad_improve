# SeekFlow Generative CAD v0.7 Final Hard-Gate Wiring Spec

目标仓库：`WYZAAACCC/seekflow-engineering`
目标目录：`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad`
执行对象：Claude Code
目标：修复最新代码中的最后关键接线 bug，使 Generative CAD 从“hard-gate 基本成形”升级为“可运行、可测试、可证明、不可绕过”的 LLM-Skill-Base / Generative CAD-IR 编译链路。

---

# 0. 当前最新状态

最新代码已有明显进展：

```text
1. validation/pipeline.py 已使用直接 import，不再 lazy optional import dialect_semantics / geometry_preflight。
2. builder.py 已使用 validate_and_canonicalize_with_bundle。
3. builder.py 已拒绝 legacy GenerativeCADSpec。
4. builder.py 已对 graph_out / script_out 做 workspace guard。
5. metadata.py 已支持 require_validation_ok。
6. import_artifact.py 已使用 require_validation_ok=True。
7. tools.py 已新增 generative_cad_import_artifact_to_solidworks / generative_cad_import_artifact_to_nx。
8. native_importers.py 已存在。
9. runtime/postconditions.py 已存在，并且 run.py 已调用。
10. skills/schemas.py 已有 DialectSelectionPlan route invariant。
```

但最新代码仍存在以下关键阻断：

```text
P0-1: ValidationReport.fail 接口与 pipeline.py 调用不兼容。
P0-2: validation pipeline 仍重复运行 validators，可能造成 report/bundle 不一致。
P0-3: artifact.py 默认 validation 仍可为空 dict，不符合 proof 语义。
P0-4: tools.py 已有 native_importers.py 但 wrapper 仍调用本文件内部 helper，helper 抽离未完成。
P0-5: runtime_postconditions 没有验证 component root output 是否真的绑定。
P0-6: import gate 对 contract_hash_valid gate flag 不够精确。
P0-7: repair/patch.py 当前 raw 视图为空或未完整实现，必须确认并实现 RepairPatchV2。
P1-1: run.py 的 raw entrypoint 仍用 validate_and_canonicalize 而非 bundle，虽然不一定用于 builder，但长期容易产生 metadata proof 漂移。
P1-2: legacy 根目录模块仍存在，必须增加 production import isolation tests。
```

本次任务不允许新增 dialect，不允许新增 CAD operation，不允许重写 Primitive path。只修 hard-gate 与接线。

---

# 1. 最终正确架构

最终链路必须固定为：

```text
LLM
  ↓
DialectSelectionPlan JSON
  ↓
RawGcadDocument JSON
  ↓
single-pass fail-closed validation pipeline
  ↓
CanonicalGcadDocument + ValidationBundle
  ↓
fixed canonical runner
  ↓
BaseDialect / OperationSpec execution
  ↓
RuntimeObjectStore typed handles
  ↓
runtime_postconditions
  ↓
STEP export
  ↓
strict STEP inspection
  ↓
generative_metadata_v2.1 with validation proof
  ↓
CanonicalStepArtifact
  ↓
optional validated SolidWorks/NX STEP import wrapper
```

必须保持：

```text
Primitive deterministic path:
  CADPartSpec
    → primitive compiler
    → deterministic CAD kernel
    → STEP + primitive metadata

Generative path:
  RawGcadDocument
    → CanonicalGcadDocument
    → STEP + generative metadata
```

二者只能在这里合流：

```text
validated STEP artifact + validated metadata
```

绝不能在这里合流：

```text
CADPartSpec
PRIMITIVE_COMPILERS
PRIMITIVE_REGISTRY
geometry_primitives
SolidWorks native feature tree
NXOpen native feature tree
LLM-generated CadQuery code
```

---

# 2. Hard Constraints for Claude Code

Claude Code 必须遵守：

```text
1. 不得修改 deterministic primitive 主链路语义。
2. 不得把 generative dialect 注册成 primitive。
3. 不得让 LLM 输出 CAD code。
4. 不得让 RawGcadDocument 直接进入 runtime。
5. 不得让 metadata validation 在 native import path 中宽松。
6. 不得让 import gate 接受空 validation stage。
7. 不得用 prompt 规则替代 schema validator。
8. 不得让 repair patch 修改 safety / constraints / dialect / op / op_version。
9. 不得新增 dialect/op 来掩盖 hard-gate bug。
10. 不得通过 extra="allow" 来绕过 Pydantic schema 问题。
```

---

# 3. Phase 1 — 修复 ValidationReport.fail / ok_report 接口

## 文件

```text
generative_cad/validation/reports.py
```

## 当前问题

`ValidationReport` 已有：

```python
stages_run: list[str] = Field(default_factory=list)
```

但 `fail()` 现在是：

```python
def fail(cls, stage: str, code: str, message: str, **kwargs):
    return cls(
        ok=False,
        stage=stage,
        issues=[
            ValidationIssue(
                stage=stage,
                code=code,
                message=message,
                **kwargs,
            )
        ],
    )
```

`pipeline.py` 调用：

```python
ValidationReport.fail(..., stages_run=list(stages_run))
```

这会把 `stages_run` 传入 `ValidationIssue`，而 `ValidationIssue` 是 `extra=forbid`，所以会失败。

## 必须修改

将 `reports.py` 改成：

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["error", "warning"]


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    severity: Severity = "error"
    stage: str
    node_id: str | None = None
    component_id: str | None = None
    path: str | None = None
    expected: Any | None = None
    actual: Any | None = None


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    stage: str
    issues: list[ValidationIssue] = Field(default_factory=list)
    stages_run: list[str] = Field(default_factory=list)

    @classmethod
    def ok_report(
        cls,
        stage: str,
        stages_run: list[str] | None = None,
    ) -> "ValidationReport":
        return cls(
            ok=True,
            stage=stage,
            issues=[],
            stages_run=stages_run or [stage],
        )

    @classmethod
    def fail(
        cls,
        stage: str,
        code: str,
        message: str,
        stages_run: list[str] | None = None,
        severity: Severity = "error",
        node_id: str | None = None,
        component_id: str | None = None,
        path: str | None = None,
        expected: Any | None = None,
        actual: Any | None = None,
    ) -> "ValidationReport":
        return cls(
            ok=False,
            stage=stage,
            stages_run=stages_run or [stage],
            issues=[
                ValidationIssue(
                    stage=stage,
                    code=code,
                    message=message,
                    severity=severity,
                    node_id=node_id,
                    component_id=component_id,
                    path=path,
                    expected=expected,
                    actual=actual,
                )
            ],
        )
```

## 验收测试

新增：

```text
tests/generative_cad/test_gcad_v07_report_schema.py
```

测试：

```python
def test_validation_report_accepts_stages_run():
    report = ValidationReport(
        ok=True,
        stage="complete",
        stages_run=["structure", "complete"],
    )
    assert report.stages_run == ["structure", "complete"]


def test_validation_report_fail_accepts_stages_run_without_passing_to_issue():
    report = ValidationReport.fail(
        stage="geometry_preflight",
        code="bad_geometry",
        message="bad",
        stages_run=["structure", "canonicalize", "geometry_preflight"],
    )
    assert report.stages_run[-1] == "geometry_preflight"
    assert not hasattr(report.issues[0], "stages_run")


def test_validation_report_ok_report_sets_default_stage():
    report = ValidationReport.ok_report("structure")
    assert report.stages_run == ["structure"]
```

---

# 4. Phase 2 — 修复 validation pipeline 双重运行

## 文件

```text
generative_cad/validation/pipeline.py
```

## 当前问题

当前 `validate_and_canonicalize_with_bundle()` 做了：

```text
1. _run_stages(raw, RAW_STAGES, ...)
2. 再 for stage_name, validator in RAW_STAGES 重新运行 validator，构造 raw_stage_reports
3. canonical stages 同理重复运行
```

这会造成：

```text
1. validator 被运行两次。
2. 性能浪费。
3. 如果 validator 有非纯函数行为，report 与 bundle 可能不一致。
4. warning 顺序、issue 顺序可能漂移。
```

## 必须修改

用 single-pass collector。

新增 helper：

```python
from collections.abc import Callable

def _run_stage_collect(
    subject,
    stages: list[tuple[str, Callable]],
    all_issues: list,
    stages_run: list[str],
) -> tuple[bool, str | None, dict[str, ValidationReport]]:
    reports: dict[str, ValidationReport] = {}

    for stage_name, validator in stages:
        try:
            report = validator(subject)
        except Exception as exc:
            report = ValidationReport.fail(
                stage=stage_name,
                code=f"{stage_name}_validator_exception",
                message=str(exc),
                stages_run=list(stages_run) + [stage_name],
            )

        if not report.stages_run:
            report.stages_run = list(stages_run) + [stage_name]

        reports[stage_name] = report
        all_issues.extend(report.issues)
        stages_run.append(stage_name)

        if not report.ok:
            return False, stage_name, reports

    return True, None, reports
```

然后 `validate_and_canonicalize_with_bundle()` 必须变成：

```python
def validate_and_canonicalize_with_bundle(
    raw: dict | RawGcadDocument,
) -> tuple[CanonicalGcadDocument | None, ValidationReport, ValidationBundle]:
    from seekflow_engineering_tools.generative_cad.validation.bundle import ValidationBundle

    stages_run: list[str] = []
    all_issues: list = []

    if isinstance(raw, dict):
        try:
            raw = RawGcadDocument.model_validate(raw)
        except Exception as exc:
            stages_run.append("structure")
            report = ValidationReport.fail(
                stage="structure",
                code="raw_validation_failed",
                message=f"RawGcadDocument validation failed: {exc}",
                stages_run=list(stages_run),
            )
            bundle = ValidationBundle(
                ok=False,
                raw_stage_reports={},
                canonicalize_report=None,
                canonical_stage_reports={},
            )
            return None, report, bundle

    ok, failed_stage, raw_stage_reports = _run_stage_collect(
        raw,
        RAW_STAGES,
        all_issues,
        stages_run,
    )

    if not ok:
        report = ValidationReport(
            ok=False,
            stage=failed_stage or "validation",
            issues=all_issues,
            stages_run=list(stages_run),
        )
        bundle = ValidationBundle(
            ok=False,
            raw_stage_reports=raw_stage_reports,
            canonicalize_report=None,
            canonical_stage_reports={},
        )
        return None, report, bundle

    canonical, c_report = canonicalize(raw)
    if not c_report.stages_run:
        c_report.stages_run = list(stages_run) + ["canonicalize"]

    all_issues.extend(c_report.issues)
    stages_run.append("canonicalize")

    if not c_report.ok:
        report = ValidationReport(
            ok=False,
            stage="canonicalize",
            issues=all_issues,
            stages_run=list(stages_run),
        )
        bundle = ValidationBundle(
            ok=False,
            raw_stage_reports=raw_stage_reports,
            canonicalize_report=c_report,
            canonical_stage_reports={},
        )
        return None, report, bundle

    ok, failed_stage, canonical_stage_reports = _run_stage_collect(
        canonical,
        CANONICAL_STAGES,
        all_issues,
        stages_run,
    )

    if not ok:
        report = ValidationReport(
            ok=False,
            stage=failed_stage or "canonical_validation",
            issues=all_issues,
            stages_run=list(stages_run),
        )
        bundle = ValidationBundle(
            ok=False,
            raw_stage_reports=raw_stage_reports,
            canonicalize_report=c_report,
            canonical_stage_reports=canonical_stage_reports,
        )
        return None, report, bundle

    report = ValidationReport(
        ok=True,
        stage="complete",
        issues=all_issues,
        stages_run=list(stages_run),
    )
    bundle = ValidationBundle(
        ok=True,
        raw_stage_reports=raw_stage_reports,
        canonicalize_report=c_report,
        canonical_stage_reports=canonical_stage_reports,
    )
    return canonical, report, bundle
```

删除 `_run_stages` 和 `_run_canonical_stages`，避免双重运行。

## 验收测试

新增：

```text
tests/generative_cad/test_gcad_v07_pipeline_single_pass.py
```

测试：

```python
def test_pipeline_runs_each_stage_once(monkeypatch, valid_axisymmetric_doc):
    from seekflow_engineering_tools.generative_cad.validation import pipeline
    from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport

    calls = {"structure": 0}

    def fake_structure(raw):
        calls["structure"] += 1
        return ValidationReport.ok_report("structure")

    new_stages = [("structure", fake_structure)] + [
        s for s in pipeline.RAW_STAGES if s[0] != "structure"
    ]
    monkeypatch.setattr(pipeline, "RAW_STAGES", new_stages)

    pipeline.validate_and_canonicalize_with_bundle(valid_axisymmetric_doc)
    assert calls["structure"] == 1
```

---

# 5. Phase 3 — 修复 artifact builder 语义

## 文件

```text
generative_cad/pipeline/artifact.py
```

## 当前状态

当前函数签名已经兼容 builder 的 keyword 调用，但默认：

```python
"validation": validation or {}
```

这会让 artifact 返回空 validation。虽然 metadata 已硬化，但 artifact 仍然不应产生“看起来合法但无 proof”的对象。

## 必须修改

将默认 validation 改成失败 proof，而不是 `{}`：

```python
def _missing_validation_artifact() -> dict:
    return {
        "core_validation": {
            "ok": False,
            "stage": "core_validation",
            "issues": [{"code": "missing_core_validation", "message": "artifact missing core_validation", "severity": "error"}],
        },
        "dialect_semantics": {
            "ok": False,
            "stage": "dialect_semantics",
            "issues": [{"code": "missing_dialect_semantics", "message": "artifact missing dialect_semantics", "severity": "error"}],
        },
        "geometry_preflight": {
            "ok": False,
            "stage": "geometry_preflight",
            "issues": [{"code": "missing_geometry_preflight", "message": "artifact missing geometry_preflight", "severity": "error"}],
        },
        "runtime_postconditions": {
            "ok": False,
            "stage": "runtime_postconditions",
            "issues": [{"code": "missing_runtime_postconditions", "message": "artifact missing runtime_postconditions", "severity": "error"}],
        },
        "inspection_validation": {
            "ok": False,
            "stage": "inspection_validation",
            "issues": [{"code": "missing_inspection_validation", "message": "artifact missing inspection_validation", "severity": "error"}],
        },
    }
```

在 return 中：

```python
"validation": validation if validation is not None else _missing_validation_artifact(),
```

同时建议补齐 artifact 字段：

```python
"artifact_version": "canonical_step_artifact_v0.2",
"document_id": canonical.document_id,
"schema_version": canonical.schema_version,
"canonical_version": canonical.canonical_version,
"raw_graph_hash": canonical.raw_graph_hash,
"canonical_graph_hash": canonical.canonical_graph_hash,
"selected_dialects": [
    d.model_dump() if hasattr(d, "model_dump") else d
    for d in canonical.selected_dialects
],
```

## 验收测试

新增：

```text
tests/generative_cad/test_gcad_v07_artifact_builder.py
```

测试：

```python
def test_artifact_default_validation_is_not_empty(canonical, tmp_path):
    artifact = build_canonical_step_artifact(
        canonical=canonical,
        step_path=tmp_path / "part.step",
        metadata_path=tmp_path / "part.metadata.json",
    )

    assert "validation" in artifact
    assert artifact["validation"]["core_validation"]["ok"] is False
    assert artifact["validation"]["geometry_preflight"]["ok"] is False


def test_artifact_preserves_validation_when_provided(canonical, tmp_path):
    validation = {
        "core_validation": {"ok": True},
        "dialect_semantics": {"ok": True},
        "geometry_preflight": {"ok": True},
        "runtime_postconditions": {"ok": True},
        "inspection_validation": {"ok": True},
    }

    artifact = build_canonical_step_artifact(
        canonical=canonical,
        step_path=tmp_path / "part.step",
        metadata_path=tmp_path / "part.metadata.json",
        validation=validation,
    )

    assert artifact["validation"]["core_validation"]["ok"] is True
```

---

# 6. Phase 4 — runtime postconditions 增强 root output binding

## 文件

```text
generative_cad/runtime/postconditions.py
```

## 当前问题

当前只检查：

```text
final_handle exists
final_handle type solid
component.root_node exists
```

但没有检查：

```text
component.root_node 是否能在 RuntimeContext 中 resolve body output
root node outputs 是否实际绑定
```

## 必须修改

在每个 non-assembly component 检查：

```python
root = next((n for n in canonical.nodes if n.id == comp.root_node), None)
if root is None:
    issues.append({
        "stage": "runtime_postconditions",
        "code": "component_root_node_not_found",
        "message": f"Component {comp.id!r} root_node {comp.root_node!r} not found.",
        "severity": "error",
        "component_id": comp.id,
    })
    continue

for output in root.outputs:
    try:
        ctx.resolve_node_output(root.id, output.name)
    except Exception as exc:
        issues.append({
            "stage": "runtime_postconditions",
            "code": "component_root_output_not_bound",
            "message": f"Root output {root.id}.{output.name} for component {comp.id!r} is not bound: {exc}",
            "severity": "error",
            "component_id": comp.id,
            "node_id": root.id,
        })
```

也检查 final object 可取出：

```python
try:
    ctx.object_store.get(final_handle_id)
except Exception as exc:
    issues.append({
        "stage": "runtime_postconditions",
        "code": "final_object_lookup_failed",
        "message": f"Final object {final_handle_id!r} not found in object store: {exc}",
        "severity": "error",
    })
```

注意：不要要求所有中间 node 都绑定，只要求 final handle 和 component root outputs。

## 验收测试

新增：

```text
tests/generative_cad/test_gcad_v07_runtime_postconditions.py
```

测试：

```python
def test_runtime_postconditions_reject_unbound_root_output(canonical, ctx):
    result = validate_runtime_postconditions(
        canonical=canonical,
        ctx=ctx,
        final_handle_id="some_existing_solid_handle",
    )
    assert not result["ok"]
    assert any(i["code"] == "component_root_output_not_bound" for i in result["issues"])
```

---

# 7. Phase 5 — 修复 tools.py native importer 接线

## 文件

```text
generative_cad/tools.py
generative_cad/native_importers.py
```

## 当前问题

仓库已新增：

```text
generative_cad/native_importers.py
```

但 `tools.py` 仍定义并调用内部：

```python
_import_step_to_solidworks
_import_step_to_nx
```

这使 `native_importers.py` 成为半死模块，也不利于 monkeypatch 测试。

## 必须修改

删除 `tools.py` 中：

```python
def _import_step_to_solidworks(...)
def _import_step_to_nx(...)
```

或至少不再使用它们。

在 `tools.py` 顶部导入：

```python
from seekflow_engineering_tools.generative_cad.native_importers import (
    import_step_to_solidworks,
    import_step_to_nx,
)
```

SolidWorks wrapper 中改为：

```python
sw_result = import_step_to_solidworks(config, step, out)
```

NX wrapper 中改为：

```python
nx_result = import_step_to_nx(config, config.workspace_root, step, out)
```

## monkeypatch 友好性

为了让 monkeypatch 稳定，推荐在 `tools.py` 中不要 `from ... import function`，而是：

```python
from seekflow_engineering_tools.generative_cad import native_importers
```

然后调用：

```python
sw_result = native_importers.import_step_to_solidworks(config, step, out)
nx_result = native_importers.import_step_to_nx(config, config.workspace_root, step, out)
```

这样测试可以 patch：

```python
monkeypatch.setattr(
    native_importers,
    "import_step_to_solidworks",
    fake_import,
)
```

## 验收测试

新增：

```text
tests/generative_cad/test_gcad_v07_native_import_wrappers.py
```

测试：

```python
def test_solidworks_wrapper_uses_native_importers_module(monkeypatch, config, valid_step, valid_metadata):
    from seekflow_engineering_tools.generative_cad import native_importers

    called = {"sw": False}

    def fake_import(config, step, out):
        called["sw"] = True
        return {"ok": True, "files_created": [str(out)]}

    monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_import)

    tools = build_generative_cad_tools(config)
    tool = next(t for t in tools if t.name == "generative_cad_import_artifact_to_solidworks")

    result = tool(
        step_path=str(valid_step),
        metadata_path=str(valid_metadata),
        out_sldprt="out.sldprt",
    )

    assert result["ok"]
    assert called["sw"] is True
```

同时测试 gate fail 不调用 native helper：

```python
def test_solidworks_wrapper_does_not_call_import_when_gate_fails(monkeypatch, config, valid_step, bad_metadata):
    called = {"sw": False}

    def fake_import(*args, **kwargs):
        called["sw"] = True
        return {"ok": True}

    monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_import)

    result = call_wrapper(valid_step, bad_metadata, "out.sldprt")

    assert not result["ok"]
    assert called["sw"] is False
```

---

# 8. Phase 6 — RepairPatchV2 必须确认并实现

## 文件

```text
generative_cad/repair/patch.py
```

## 当前问题

当前 raw 文件视图显示为空或未完整输出。无论实际文件是否为空，都必须保证下列 API 存在且测试通过。

## 必须实现

```python
from __future__ import annotations

import copy
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class RepairChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    old_value: Any | None = None
    new_value: Any
    reason: str


class RepairPatchV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_node: str | None = None
    target_component: str | None = None
    changes: list[RepairChange] = Field(default_factory=list)
    reason: str = ""
    give_up: bool = False


def is_forbidden_repair_path(path: str) -> bool:
    forbidden_exact = {
        "/schema_version",
        "/selected_dialects",
        "/safety",
        "/constraints/require_step_file",
        "/constraints/require_metadata_sidecar",
        "/constraints/require_closed_solid",
    }
    if path in forbidden_exact:
        return True

    parts = path.strip("/").split("/")
    if len(parts) >= 3 and parts[0] == "nodes" and parts[2] in {"dialect", "op", "op_version"}:
        return True
    if len(parts) >= 3 and parts[0] == "components" and parts[2] == "owner_dialect":
        return True

    return False


def is_allowed_repair_path(path: str) -> bool:
    if is_forbidden_repair_path(path):
        return False

    if path == "/llm_validation_hints":
        return True

    parts = path.strip("/").split("/")
    if len(parts) >= 4 and parts[0] == "nodes" and parts[2] == "params":
        return True
    if len(parts) == 3 and parts[0] == "nodes" and parts[2] in {
        "inputs",
        "outputs",
        "required",
        "degradation_policy",
    }:
        return True
    if len(parts) == 3 and parts[0] == "components" and parts[2] == "root_node":
        return True

    return False


def validate_repair_patch_v2(patch: RepairPatchV2) -> tuple[bool, list[dict]]:
    issues = []

    if patch.give_up:
        return True, issues

    if not patch.changes:
        issues.append({
            "code": "empty_repair_patch",
            "message": "repair patch has no changes",
        })

    for change in patch.changes:
        if is_forbidden_repair_path(change.path):
            issues.append({
                "code": "forbidden_repair_path",
                "message": f"repair path is forbidden: {change.path}",
            })
        elif not is_allowed_repair_path(change.path):
            issues.append({
                "code": "unsupported_repair_path",
                "message": f"repair path is not supported: {change.path}",
            })

    return len(issues) == 0, issues


def apply_repair_patch_v2(raw: dict, patch: RepairPatchV2) -> dict:
    ok, issues = validate_repair_patch_v2(patch)
    if not ok:
        raise ValueError(
            "invalid repair patch: "
            + "; ".join(i["message"] for i in issues)
        )

    if patch.give_up:
        return copy.deepcopy(raw)

    updated = copy.deepcopy(raw)
    applied = 0

    for change in patch.changes:
        path = change.path
        parts = path.strip("/").split("/")

        if path == "/llm_validation_hints":
            if not isinstance(change.new_value, dict):
                raise ValueError("/llm_validation_hints repair value must be dict")
            updated["llm_validation_hints"] = change.new_value
            applied += 1
            continue

        if parts[0] == "nodes":
            node_id = parts[1]
            node = next((n for n in updated.get("nodes", []) if n.get("id") == node_id), None)
            if node is None:
                raise ValueError(f"repair target node not found: {node_id}")

            field = parts[2]
            if field == "params":
                param_name = parts[3]
                node.setdefault("params", {})[param_name] = change.new_value
            elif field in {"inputs", "outputs", "required", "degradation_policy"}:
                node[field] = change.new_value
            else:
                raise ValueError(f"unsupported node repair field: {field}")

            applied += 1
            continue

        if parts[0] == "components":
            component_id = parts[1]
            comp = next((c for c in updated.get("components", []) if c.get("id") == component_id), None)
            if comp is None:
                raise ValueError(f"repair target component not found: {component_id}")

            field = parts[2]
            if field == "root_node":
                comp["root_node"] = change.new_value
            else:
                raise ValueError(f"unsupported component repair field: {field}")

            applied += 1
            continue

        raise ValueError(f"unsupported repair path: {path}")

    if applied == 0:
        raise ValueError("repair patch did not apply any changes")

    return updated
```

## 验收测试

新增：

```text
tests/generative_cad/test_gcad_v07_repair_patch.py
```

测试：

```python
def test_repair_patch_rejects_safety_change():
    patch = RepairPatchV2(
        changes=[
            RepairChange(
                path="/safety/not_certified",
                new_value=False,
                reason="bad",
            )
        ],
        reason="bad",
    )
    ok, issues = validate_repair_patch_v2(patch)
    assert not ok
    assert any(i["code"] == "forbidden_repair_path" for i in issues)


def test_repair_patch_allows_node_param_change():
    patch = RepairPatchV2(
        target_node="n_holes",
        changes=[
            RepairChange(
                path="/nodes/n_holes/params/hole_dia_mm",
                new_value=24,
                reason="reduce hole diameter",
            )
        ],
        reason="repair preflight",
    )
    ok, issues = validate_repair_patch_v2(patch)
    assert ok


def test_apply_repair_patch_rejects_missing_node(raw_doc):
    patch = RepairPatchV2(
        target_node="missing",
        changes=[
            RepairChange(
                path="/nodes/missing/params/hole_dia_mm",
                new_value=10,
                reason="test",
            )
        ],
        reason="test",
    )

    with pytest.raises(ValueError, match="repair target node not found"):
        apply_repair_patch_v2(raw_doc, patch)


def test_apply_repair_patch_updates_target_param(raw_doc):
    patch = RepairPatchV2(
        target_node="n_holes",
        changes=[
            RepairChange(
                path="/nodes/n_holes/params/hole_dia_mm",
                new_value=24,
                reason="reduce",
            )
        ],
        reason="repair",
    )
    updated = apply_repair_patch_v2(raw_doc, patch)
    node = next(n for n in updated["nodes"] if n["id"] == "n_holes")
    assert node["params"]["hole_dia_mm"] == 24
```

---

# 9. Phase 7 — import gate flag 精度修复

## 文件

```text
generative_cad/pipeline/import_artifact.py
```

## 当前问题

当前 gate 在 metadata validator 失败时直接返回，`contract_hash_valid` 仍是 False，这是安全的；但 issue 没有被分类成 gate flag。更重要的是，如果 `require_geometry_preflight_ok=False` 或 `require_inspection_ok=False`，gate flag 不应被默认视为 True；它应该反映实际状态。

## 必须修改

metadata validation 失败时：

```python
if not meta_result["ok"]:
    issues.extend(meta_result["issues"])

    if any(i.get("code") in {"contract_hash_mismatch", "unknown_metadata_dialect"} for i in meta_result["issues"]):
        gate["contract_hash_valid"] = False

    return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
```

metadata validation 成功后：

```python
gate["metadata_valid"] = True
gate["contract_hash_valid"] = True
```

对于可选 strict 参数：

```python
gp = val.get("geometry_preflight", {})
gate["geometry_preflight_ok"] = isinstance(gp, dict) and gp.get("ok") is True

if require_geometry_preflight_ok and not gate["geometry_preflight_ok"]:
    fail
```

Inspection 同理：

```python
insp = val.get("inspection_validation", {})
gate["inspection_ok"] = isinstance(insp, dict) and insp.get("ok") is True

if require_inspection_ok and not gate["inspection_ok"]:
    fail
```

## 验收测试

新增：

```text
tests/generative_cad/test_gcad_v07_import_gate_flags.py
```

测试：

```python
def test_import_gate_contract_hash_flag_false_on_mismatch(step_file, metadata_file):
    meta = load_metadata(metadata_file)
    meta["generative_metadata"]["selected_dialects"][0]["contract_hash"] = "sha256:bad"
    write_metadata(metadata_file, meta)

    result = validate_generative_step_artifact_for_native_import(step_file, metadata_file)

    assert not result["ok"]
    assert result["gate"]["contract_hash_valid"] is False


def test_import_gate_optional_inspection_flag_reflects_actual_state(step_file, metadata_file):
    meta = load_metadata(metadata_file)
    meta["validation"]["inspection_validation"] = {"ok": False, "issues": []}
    write_metadata(metadata_file, meta)

    result = validate_generative_step_artifact_for_native_import(
        step_file,
        metadata_file,
        require_inspection_ok=False,
    )

    assert result["gate"]["inspection_ok"] is False
```

---

# 10. Phase 8 — run.py metadata/artifact consistency

## 文件

```text
generative_cad/pipeline/run.py
```

## 当前状态

`run_canonical_gcad()` 构造 metadata：

```python
metadata = build_generative_metadata(
    canonical=canonical,
    ctx=ctx,
    validation={"runtime_postconditions": runtime_pc},
)
```

这会让 runner metadata 里其他 validation stages 是缺失的，而 builder 会再合并完整 proof。这对 builder path 可以接受，但 raw runner path `run_gcad_core` 直接运行时 metadata 会不满足 `require_validation_ok=True`。

## 推荐修复

在 `run_gcad_core(raw, ...)` 中改用 bundle：

```python
canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
if canonical is None or not report.ok:
    ...
return run_canonical_gcad(
    canonical,
    out_step=out_step,
    metadata_path=metadata_path,
    validation_seed=bundle.to_metadata_dict(),
)
```

修改 `run_canonical_gcad` 签名：

```python
def run_canonical_gcad(
    canonical: CanonicalGcadDocument,
    out_step: str | Path,
    metadata_path: str | Path,
    validation_seed: dict | None = None,
) -> GcadRunResult:
```

metadata 构造：

```python
validation = validation_seed or {}
validation["runtime_postconditions"] = runtime_pc

metadata = build_generative_metadata(
    canonical=canonical,
    ctx=ctx,
    validation=validation,
)
```

`run_canonical_gcad_from_files()` 仍然可以传 `validation_seed=None`，因为 builder 会最终合并 validation proof。

这能保证 raw runner path 也具备 full validation metadata，而 canonical runner path 仍保持可用。

## 验收测试

```python
def test_run_gcad_core_raw_path_writes_full_validation_metadata(valid_raw_doc, tmp_path):
    result = run_gcad_core(
        valid_raw_doc,
        out_step=tmp_path / "part.step",
        metadata_path=tmp_path / "part.metadata.json",
    )
    assert result.ok
    meta = json.loads((tmp_path / "part.metadata.json").read_text())
    assert meta["validation"]["core_validation"]["ok"] is True
    assert meta["validation"]["dialect_semantics"]["ok"] is True
    assert meta["validation"]["geometry_preflight"]["ok"] is True
    assert meta["validation"]["runtime_postconditions"]["ok"] is True
```

---

# 11. Phase 9 — legacy isolation tests

## 目标

当前可以暂不移动所有 legacy 根目录模块，但必须保证 production modules 不 import legacy schema。

## 新增测试

```text
tests/generative_cad/test_gcad_v07_legacy_isolation.py
```

测试：

```python
def test_production_modules_do_not_import_legacy_symbols():
    import inspect
    import importlib

    modules = [
        "seekflow_engineering_tools.generative_cad.builder",
        "seekflow_engineering_tools.generative_cad.pipeline.run",
        "seekflow_engineering_tools.generative_cad.validation.pipeline",
        "seekflow_engineering_tools.generative_cad.tools",
        "seekflow_engineering_tools.generative_cad.pipeline.metadata",
        "seekflow_engineering_tools.generative_cad.pipeline.import_artifact",
    ]

    forbidden = [
        "GenerativeCADSpec",
        "SelectedBase",
        "FeatureGraph",
        "BASE_REGISTRY",
        "selected_bases",
        "feature_graph",
    ]

    for name in modules:
        src = inspect.getsource(importlib.import_module(name))
        for token in forbidden:
            assert token not in src
```

如果此测试因 error string 中出现 `Legacy GenerativeCADSpec` 失败，则允许改成更精细：

```python
forbidden_import_tokens = [
    "from seekflow_engineering_tools.generative_cad.ir import",
    "from seekflow_engineering_tools.generative_cad.registry import BASE_REGISTRY",
    "GenerativeCADSpec(",
    "SelectedBase(",
    "FeatureGraph(",
]
```

不要因为错误消息包含 legacy 名称就误判。

---

# 12. Required Test Matrix

必须新增或确认存在以下测试：

```text
tests/generative_cad/test_gcad_v07_report_schema.py
tests/generative_cad/test_gcad_v07_pipeline_single_pass.py
tests/generative_cad/test_gcad_v07_artifact_builder.py
tests/generative_cad/test_gcad_v07_runtime_postconditions.py
tests/generative_cad/test_gcad_v07_native_import_wrappers.py
tests/generative_cad/test_gcad_v07_repair_patch.py
tests/generative_cad/test_gcad_v07_import_gate_flags.py
tests/generative_cad/test_gcad_v07_run_metadata.py
tests/generative_cad/test_gcad_v07_legacy_isolation.py
```

必须继续通过：

```bash
pytest integrations/engineering_tools/tests/generative_cad
pytest integrations/engineering_tools/tests/test_generative_no_main_chain_pollution.py
```

如果旧 repair governor 测试仍基于 v0.1 schema，必须明确改成 legacy test，不得约束 v0.7 production repair。

---

# 13. Prompt Assets — Final Version

## Level-1 Routing Prompt

```python
LEVEL1_ROUTING_SYSTEM_PROMPT = """
You are a CAD grammar routing compiler front-end.

Your job is to choose the safest modelling route for a mechanical CAD request.

You must choose exactly one route_decision:
- deterministic_primitive
- generative_cad_ir
- unsupported

Hard rules:
1. Use deterministic_primitive only when the requested part is covered by the existing deterministic primitive path and the user needs high determinism.
2. Use generative_cad_ir only when the requested geometry can be expressed by registered CAD grammar dialects in the provided Dialect Catalog.
3. Use unsupported when the request requires missing dialects, native feature-tree authoring, structural validation, certification, manufacturing readiness, arbitrary code, external simulation truth, or unconstrained freeform modelling.
4. You may only select dialects listed in the provided Dialect Catalog.
5. Do not invent dialect names.
6. Do not invent operation names.
7. Do not output CAD code.
8. Do not output CadQuery, SolidWorks COM, NXOpen, APDL, Python, shell commands, imports, exports, file paths, or subprocesses.
9. Generative turbomachinery output is non-flight reference geometry only.
10. Never claim airworthy, certified, production-ready, manufacturing-ready, installable, structurally validated, or life-predicted status.
11. If more than one independent component must be combined, select the composition dialect.
12. If a request needs SolidWorks or NX, the generative route may only produce validated STEP for later native import; it must not produce native feature-tree commands.
13. Output JSON only.
14. Output must match DialectSelectionPlan schema exactly.
15. Do not include markdown, prose, comments, or trailing commas.
"""
```

## Level-2 Authoring Prompt

```python
LEVEL2_AUTHORING_SYSTEM_PROMPT = """
You are a G-CAD Core IR author.

Your task is to produce RawGcadDocument JSON only.

You are not a CAD kernel.
You are not a CadQuery programmer.
You are not a SolidWorks automation author.
You are not an NXOpen automation author.
You are a constrained feature-graph author.

Hard rules:
1. Output only JSON matching RawGcadDocument schema.
2. Use schema_version exactly "g_cad_core_v0.2".
3. Use units exactly "mm".
4. trust_level must be "reference_geometry" or "concept_geometry"; never higher.
5. Use only selected_dialects provided by the routing step.
6. Use only operations listed in the selected dialect contracts.
7. Every node must specify dialect, op, op_version, phase, inputs, outputs, params, required, and degradation_policy.
8. Every node phase must match its operation contract.
9. Every node input type must match operation input_types.
10. Every node output type must match operation output_types.
11. Every component must have owner_dialect and explicit root_node.
12. A non-assembly component may only contain nodes from its owner_dialect.
13. Cross-component composition must happen only inside "__assembly__" using the "composition" dialect.
14. If more than one non-assembly component exists, include "__assembly__" with owner_dialect "composition".
15. The final component root_node must output "body" of type "solid".
16. constraints.require_step_file must be true.
17. constraints.require_metadata_sidecar must be true.
18. constraints.require_closed_solid must be true.
19. All safety flags must be true.
20. Do not weaken constraints.
21. Do not include file paths.
22. Do not include code.
23. Do not include natural language outside JSON.
24. Do not include comments, markdown, prose, or trailing commas.
25. Do not use deprecated fields: selected_bases, feature_graph, base_id, system_validation_contract, ir_version.
26. Use only selected_dialects, components, nodes, constraints, safety, and schema-defined fields.
27. If the request cannot be expressed with the selected contracts, do not invent operations or fallback fields. The request must be returned to Level-1 routing as unsupported.
28. Do not set trust_level above reference_geometry.
29. Do not claim manufacturing readiness, certification, airworthiness, installation readiness, structural validation, life prediction, or production readiness.
"""
```

## Repair Prompt

```python
REPAIR_PATCH_SYSTEM_PROMPT_V2 = """
You are a local G-CAD IR repair patch author.

You may only repair the provided RawGcadDocument by returning a local RepairPatchV2 JSON.

Hard rules:
1. Do not rewrite the entire graph.
2. Do not modify schema_version.
3. Do not modify selected_dialects.
4. Do not modify safety.
5. Do not modify constraints.require_step_file.
6. Do not modify constraints.require_metadata_sidecar.
7. Do not modify constraints.require_closed_solid.
8. Do not modify node.dialect.
9. Do not modify node.op.
10. Do not modify node.op_version.
11. Do not modify component.owner_dialect.
12. Do not invent dialects.
13. Do not invent operations.
14. Do not weaken validation.
15. Prefer changing only /nodes/<node_id>/params/<field>.
16. You may change /nodes/<node_id>/inputs, /nodes/<node_id>/outputs, /nodes/<node_id>/required, /nodes/<node_id>/degradation_policy, or /components/<component_id>/root_node only when the validation error explicitly requires that exact structural repair.
17. If the same error signature repeated, output {"give_up": true, "reason": "..."}.
18. Output JSON only.
19. Output must match RepairPatchV2 schema.
20. Do not include markdown, prose, comments, or trailing commas.
"""
```

---

# 14. Prohibited Shortcuts

Claude Code 不得：

```text
1. 将 ValidationReport.model_config 改成 extra="allow"。
2. 删除 stages_run 来绕过 schema 问题。
3. 在 pipeline 中继续重复运行 validators。
4. 让 artifact.validation 默认为 {}。
5. 在 tools.py 中继续调用内部 _import_step_to_solidworks/_import_step_to_nx。
6. 在 native wrapper 中绕过 import gate。
7. 让 repair patch 找不到 node/component 时静默成功。
8. 通过删除测试降低 hard-gate 要求。
9. 新增 dialect/op。
10. 修改 deterministic primitive path。
```

---

# 15. Definition of Done

完成标准：

```text
1. ValidationReport.fail 正确支持 stages_run。
2. ValidationReport.ok_report 默认写入 stages_run。
3. validation pipeline single-pass，无重复 validator 执行。
4. validate_and_canonicalize_with_bundle 返回完整且一致的 bundle。
5. artifact.py 默认 validation 为失败 proof，不是 {}。
6. runtime_postconditions 检查 component root outputs 是否绑定。
7. tools.py 使用 native_importers module，不再使用内部 native import helpers。
8. RepairPatchV2 完整实现 validate/apply。
9. import gate flags 准确反映 contract/inspection/preflight 状态。
10. run_gcad_core raw path 能写 full validation metadata。
11. legacy isolation tests 通过。
12. primitive pollution tests 通过。
13. 所有 generative_cad tests 通过。
14. 未新增 dialect/op。
```

---

# 16. Final Architecture Statement

v0.7 完成后，系统必须具备以下性质：

```text
LLM output is grammar, not CAD code.
RawGcadDocument is source text.
Validation pipeline is compiler front-end.
CanonicalGcadDocument is typed IR.
BaseDialect/OperationSpec are backend lowering rules.
RuntimeObjectStore is typed value storage.
STEP is object code.
generative_metadata_v2.1 is provenance proof.
SW/NX wrappers are import gates, not native rebuilders.
```

最终合流点唯一：

```text
validated STEP + validated metadata
```

这才是正确的 LLM-Skill-Base / Generative CAD-IR 工程架构。
