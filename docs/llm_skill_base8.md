# SeekFlow Generative CAD v0.6 Final Wiring & Hard-Gate 修复规格书

目标：修复最新 v0.5 代码中的接线级阻断、artifact 不一致、validation report schema 漂移、runner/builder metadata proof 不一致、import wrapper 细节风险，最终形成真正可运行的 Generative CAD compiler hard-gate。

---

## 0. 当前最新状态判断

最新代码已有重大进展：

```text
1. validation/pipeline.py 已经移除 lazy optional canonical validators。
2. builder.py 已经调用 validate_and_canonicalize_with_bundle。
3. metadata.py 已经支持 require_validation_ok。
4. import_artifact.py 已经使用 require_validation_ok=True。
5. tools.py 已经新增 generative_cad_import_artifact_to_solidworks / generative_cad_import_artifact_to_nx。
6. runtime/postconditions.py 已经被 run.py 调用。
7. repair/patch.py 已经有 path validator 与 apply logic。
8. skills/schemas.py 已经有 route invariant validator。
```

但仍存在必须立即修复的阻断问题：

```text
P0-1: ValidationReport 没有 stages_run 字段，但 pipeline.py 正在构造 ValidationReport(..., stages_run=...)。
P0-2: artifact.py 的 build_canonical_step_artifact 签名与 builder.py 调用不一致。
P0-3: artifact.py 仍返回空 validation，不符合 metadata proof 语义。
P0-4: validation pipeline 现在会重复运行 validators：先运行一次判断，再重新运行一次构造 bundle。
P0-5: repair apply patch 如果 node/component 不存在，会静默 continue，不会报错。
P0-6: import wrappers 内部 helper 直接放在 tools.py，虽然可运行，但不利于测试与复用。
P0-7: native wrapper 调用真实 SolidWorks/NX helper 时没有把 helper 抽离成可 monkeypatch 的稳定模块 API。
P1-1: axisymmetric / sketch_extrude preflight 仍需补更多工程边界测试。
P1-2: legacy 根目录模块仍可能造成概念污染，但已不是当前最大阻断。
```

本次修复不新增 dialect，不新增 CAD operation，只修接线与 hard-gate。

---

# 1. Final Architecture

最终架构必须固定为：

```text
RawGcadDocument
  ↓
validate_and_canonicalize_with_bundle
  ↓
CanonicalGcadDocument + ValidationBundle
  ↓
Fixed canonical runner
  ↓
runtime postconditions
  ↓
STEP export
  ↓
runner metadata with runtime_postconditions
  ↓
builder STEP inspection
  ↓
builder rewrites metadata.validation with:
      core_validation
      dialect_semantics
      geometry_preflight
      runtime_postconditions
      inspection_validation
  ↓
validate_generative_metadata_v2(require_validation_ok=True)
  ↓
CanonicalStepArtifact
  ↓
optional SW/NX import through import gate only
```

不得绕过：

```text
ValidationBundle
runtime_postconditions
inspection_validation
metadata require_validation_ok
import gate
```

---

# 2. Phase 1 — 修复 ValidationReport schema

## 文件

```text
generative_cad/validation/reports.py
```

## 问题

`ValidationReport` 当前没有 `stages_run` 字段，并且 `extra=forbid`。但 `validation/pipeline.py` 已经构造：

```python
ValidationReport(..., stages_run=list(stages_run))
```

这会直接报错。

## 必须修改

将 `ValidationReport` 改为：

```python
class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    stage: str
    issues: list[ValidationIssue] = Field(default_factory=list)
    stages_run: list[str] = Field(default_factory=list)

    @classmethod
    def ok_report(cls, stage: str, stages_run: list[str] | None = None) -> "ValidationReport":
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
        **kwargs,
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
                    **kwargs,
                )
            ],
        )
```

## 验收测试

新增：

```text
tests/generative_cad/test_gcad_v06_report_schema.py
```

测试：

```python
def test_validation_report_accepts_stages_run():
    report = ValidationReport(ok=True, stage="complete", stages_run=["structure", "complete"])
    assert report.stages_run == ["structure", "complete"]


def test_validation_report_fail_preserves_stages_run():
    report = ValidationReport.fail(
        stage="geometry_preflight",
        code="x",
        message="bad",
        stages_run=["structure", "canonicalize", "geometry_preflight"],
    )
    assert report.stages_run[-1] == "geometry_preflight"
```

---

# 3. Phase 2 — 修复 validation pipeline 双重运行问题

## 文件

```text
generative_cad/validation/pipeline.py
```

## 问题

当前 pipeline 先 `_run_stages(...)` 运行所有 raw validators，再为了构造 bundle 重新运行一遍所有 validators。canonical stages 也是同样问题。

这会带来：

```text
1. validator 有副作用时结果不一致。
2. validator 变重后性能翻倍。
3. report 和 bundle 可能不一致。
4. warning 顺序可能漂移。
```

## 必须重构

删除 `_run_stages` / `_run_canonical_stages` 的“只返回 ok”模式，改成一次运行并收集 report。

实现 helper：

```python
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

然后在 `validate_and_canonicalize_with_bundle` 中：

```python
ok, failed_stage, raw_stage_reports = _run_stage_collect(
    raw,
    RAW_STAGES,
    all_issues,
    stages_run,
)
```

canonical 同理：

```python
ok, failed_stage, canonical_stage_reports = _run_stage_collect(
    canonical,
    CANONICAL_STAGES,
    all_issues,
    stages_run,
)
```

不得重新运行 validators。

## 验收测试

```python
def test_pipeline_runs_each_validator_once(monkeypatch, valid_doc):
    calls = {"structure": 0}

    def fake_structure(raw):
        calls["structure"] += 1
        return ValidationReport.ok_report("structure")

    monkeypatch.setattr(pipeline, "validate_structure", fake_structure)
    monkeypatch.setattr(
        pipeline,
        "RAW_STAGES",
        [("structure", fake_structure)] + pipeline.RAW_STAGES[1:],
    )

    validate_and_canonicalize_with_bundle(valid_doc)
    assert calls["structure"] == 1
```

---

# 4. Phase 3 — 修复 artifact.py 签名与语义

## 文件

```text
generative_cad/pipeline/artifact.py
```

## 问题

`builder.py` 当前调用：

```python
build_canonical_step_artifact(
    canonical=canonical,
    step_path=step_path,
    metadata_path=meta_path,
    graph_path=str(graph_path),
    runner_script_path=str(script_path),
    validation=validation_meta,
)
```

但 `artifact.py` 当前函数签名是：

```python
def build_canonical_step_artifact(canonical, step_path, metadata_path, ctx)
```

这会直接 TypeError。

并且 `artifact.py` 当前返回：

```python
"validation": {
  "core_validation": {},
  "geometry_preflight": {},
  "inspection_validation": {},
}
```

这与 v0.6 metadata proof 冲突。

## 必须修改

将 `artifact.py` 改为：

```python
from __future__ import annotations

from pathlib import Path
from typing import Any


def build_canonical_step_artifact(
    canonical,
    step_path: str | Path,
    metadata_path: str | Path,
    graph_path: str | Path | None = None,
    runner_script_path: str | Path | None = None,
    validation: dict[str, Any] | None = None,
    inspection: dict[str, Any] | None = None,
    ctx=None,
) -> dict[str, Any]:
    step_path = Path(step_path)
    metadata_path = Path(metadata_path)

    if validation is None and ctx is not None:
        validation = getattr(ctx, "validation", None)

    return {
        "artifact_type": "canonical_step_artifact",
        "artifact_version": "canonical_step_artifact_v0.2",
        "source_route": "llm_skill_base",
        "part_name": canonical.part_name,
        "document_id": canonical.document_id,
        "step_path": str(step_path),
        "metadata_path": str(metadata_path),
        "graph_path": str(graph_path) if graph_path else "",
        "runner_script_path": str(runner_script_path) if runner_script_path else None,
        "units": "mm",
        "trust_level": canonical.trust_level,
        "schema_version": canonical.schema_version,
        "canonical_version": canonical.canonical_version,
        "raw_graph_hash": canonical.raw_graph_hash,
        "canonical_graph_hash": canonical.canonical_graph_hash,
        "selected_dialects": [d.model_dump() for d in canonical.selected_dialects],
        "native_rebuild_allowed": False,
        "step_import_allowed": True,
        "inspection": inspection or {},
        "validation": validation or {
            "core_validation": {"ok": False, "issues": [{"code": "missing_core_validation"}]},
            "dialect_semantics": {"ok": False, "issues": [{"code": "missing_dialect_semantics"}]},
            "geometry_preflight": {"ok": False, "issues": [{"code": "missing_geometry_preflight"}]},
            "runtime_postconditions": {"ok": False, "issues": [{"code": "missing_runtime_postconditions"}]},
            "inspection_validation": {"ok": False, "issues": [{"code": "missing_inspection_validation"}]},
        },
    }
```

## 同时修改 run.py 调用

`run.py` 当前调用：

```python
artifact = build_canonical_step_artifact(
    canonical=canonical,
    step_path=out_step,
    metadata_path=metadata_path,
    ctx=ctx,
)
```

这仍可兼容，但最好显式传：

```python
artifact = build_canonical_step_artifact(
    canonical=canonical,
    step_path=out_step,
    metadata_path=metadata_path,
    validation=metadata.get("validation", {}),
    ctx=ctx,
)
```

## 验收测试

```python
def test_artifact_builder_accepts_builder_signature(canonical, tmp_path):
    artifact = build_canonical_step_artifact(
        canonical=canonical,
        step_path=tmp_path / "a.step",
        metadata_path=tmp_path / "a.metadata.json",
        graph_path=tmp_path / "graph.json",
        runner_script_path=tmp_path / "run.py",
        validation={"core_validation": {"ok": True}},
    )

    assert artifact["graph_path"].endswith("graph.json")
    assert artifact["runner_script_path"].endswith("run.py")
    assert artifact["native_rebuild_allowed"] is False
```

---

# 5. Phase 4 — 修复 runtime postconditions 强度

## 文件

```text
generative_cad/runtime/postconditions.py
```

## 当前问题

当前只检查 final handle、handle type、component root_node 是否存在，但没有检查 component root output 是否真的绑定，也没有验证 final solid object 是否可从 object_store 取出。

## 必须增强

增加检查：

```python
try:
    _obj = ctx.object_store.get(final_handle_id)
except Exception as exc:
    issues.append({
        "stage": "runtime_postconditions",
        "code": "final_object_lookup_failed",
        "message": f"Final object {final_handle_id!r} not found in object store: {exc}",
        "severity": "error",
    })
```

对每个 non-assembly component：

```python
root = next((n for n in canonical.nodes if n.id == comp.root_node), None)
if root is None:
    issue component_root_node_not_found

for output in root.outputs:
    try:
        ctx.resolve_node_output(root.id, output.name)
    except Exception:
        issue component_root_output_not_bound
```

注意：只要求 root outputs 被绑定，不要求每个中间 node outputs 都绑定，因为可选 degraded feature 可能被跳过。

## 验收测试

```python
def test_runtime_postconditions_reject_unbound_component_root_output(canonical, ctx):
    result = validate_runtime_postconditions(canonical, ctx, final_handle_id="some_solid")
    assert not result["ok"]
    assert any(i["code"] == "component_root_output_not_bound" for i in result["issues"])
```

---

# 6. Phase 5 — 修复 RepairPatchV2 apply 静默失败

## 文件

```text
generative_cad/repair/patch.py
```

## 当前问题

`apply_repair_patch_v2` 中，如果 node/component 不存在，循环结束后会直接 continue，不报错。这会让 repair patch 表面成功，实际未修改任何内容。

## 必须修改

对每种 path，必须有 `found` 标记：

```python
found = False
for node in updated.get("nodes", []):
    if node.get("id") == node_id:
        ...
        found = True
        break
if not found:
    raise ValueError(f"repair target node not found: {node_id}")
```

component 同理。

对 `/llm_validation_hints`：

```python
if not isinstance(change.new_value, dict):
    raise ValueError("/llm_validation_hints repair value must be dict")
updated["llm_validation_hints"] = change.new_value
```

## 额外要求

如果 patch 没有任何 change 实际应用，也必须报错。

## 验收测试

```python
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
```

---

# 7. Phase 6 — 修复 native wrappers 可测试性

## 文件

```text
generative_cad/tools.py
```

## 当前状态

`tools.py` 已新增 SW/NX wrappers，这是正确方向。但 `_import_step_to_solidworks` 和 `_import_step_to_nx` 直接写在 `tools.py` 内，不利于单元测试和复用。

## 必须新增模块

```text
generative_cad/native_importers.py
```

内容：

```python
from __future__ import annotations

from pathlib import Path


def import_step_to_solidworks(config, input_step: str | Path, out_sldprt: str | Path) -> dict:
    from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

    client = SolidWorksClient(
        visible=config.solidworks_visible,
        part_template=config.solidworks_part_template,
    ).connect()

    ok = client.import_step_as_part(str(input_step), str(out_sldprt))
    if not ok:
        raise RuntimeError(f"SolidWorks STEP import failed for {out_sldprt}")

    out = Path(out_sldprt)
    if not out.exists() or out.stat().st_size < 1:
        raise RuntimeError(f"SolidWorks import reported success but SLDPRT not found: {out_sldprt}")

    return {"ok": True, "files_created": [str(out)]}


def import_step_to_nx(config, job_root: str | Path, input_step: str | Path, out_prt: str | Path) -> dict:
    from seekflow_engineering_tools.nx.nx_job_queue import NXJobQueue

    q = NXJobQueue(Path(job_root))
    job_id = q.submit(
        "import_step_as_prt",
        {
            "input_step": str(input_step),
            "out_prt": str(out_prt),
        },
    )
    return q.wait(job_id, timeout_s=config.nx_default_timeout_s)
```

## 修改 tools.py

删除 `_import_step_to_solidworks` / `_import_step_to_nx` 内部函数。

改为：

```python
from seekflow_engineering_tools.generative_cad.native_importers import (
    import_step_to_solidworks,
    import_step_to_nx,
)
```

wrapper 调用：

```python
sw_result = import_step_to_solidworks(config, step, out)
nx_result = import_step_to_nx(config, config.workspace_root, step, out)
```

这样测试可 monkeypatch：

```python
monkeypatch.setattr(
    "seekflow_engineering_tools.generative_cad.native_importers.import_step_to_solidworks",
    fake_import,
)
```

## 验收测试

```python
def test_solidworks_wrapper_does_not_call_native_import_when_gate_fails(monkeypatch):
    called = False

    def fake_import(*args, **kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(
        "seekflow_engineering_tools.generative_cad.native_importers.import_step_to_solidworks",
        fake_import,
    )

    result = generative_cad_import_artifact_to_solidworks(
        step_path="valid.step",
        metadata_path="bad.metadata.json",
        out_sldprt="out.sldprt",
    )

    assert not result["ok"]
    assert called is False
```

---

# 8. Phase 7 — 修复 import gate gate flags 精度

## 文件

```text
generative_cad/pipeline/import_artifact.py
```

## 当前状态

当前 import gate 主要逻辑已经正确，但 `contract_hash_valid` 只在 metadata validator 成功后最终设为 True，没有把 metadata validator 的具体 contract hash 检查结果显式反映出来。

## 必须增强

在 `validate_generative_metadata_v2` 返回失败时，如果 issue code 是 `contract_hash_mismatch` 或 `unknown_metadata_dialect`，gate 必须显式：

```python
gate["contract_hash_valid"] = False
```

如果 metadata validator 成功：

```python
gate["contract_hash_valid"] = True
```

另外，如果 `require_geometry_preflight_ok=False`，不要把 `geometry_preflight_ok=True` 写死，应该：

```python
gate["geometry_preflight_ok"] = (
    isinstance(gp, dict) and gp.get("ok") is True
)
```

同理 `require_inspection_ok=False` 时：

```python
gate["inspection_ok"] = (
    isinstance(insp, dict) and insp.get("ok") is True
)
```

不要求失败，但 gate flag 要真实。

---

# 9. Phase 8 — dialect preflight 最小补强

## 文件

```text
generative_cad/dialects/axisymmetric/dialect.py
generative_cad/dialects/sketch_extrude/dialect.py
```

## Axisymmetric

当前 axisymmetric 已有 PCD 外径和中心孔检查，但要补三个 case：

```text
1. cut_center_bore 必须先于 hole pattern 时才能用于 bore clearance；如果 hole pattern 出现在 bore 前，仍需要通过 node dependency 判断是否可用。
2. 如果存在多个 revolve_profile，semantic 已应失败；preflight 不应继续用不确定 envelope，应直接返回 error。
3. 所有数值必须 finite，不能是 NaN / inf。
```

实现 helper：

```python
import math

def _is_finite_number(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)
```

所有 r/z/diameter/pcd/count 前都检查。

## SketchExtrude

必须从 `extrude_rectangle` 推断 envelope，然后检查：

```text
1. cut_hole diameter < min(width, height) - 2mm
2. cut_rectangular_pocket width/depth 不得超过 base envelope
3. linear hole pattern 总跨度不得超过对应方向 envelope
```

如果字段名不确定，使用实际 params model 字段，不要猜字段。

---

# 10. Phase 9 — legacy 隔离最低要求

当前不强制移动所有 legacy 根目录文件，但必须新增 regression test，保证 production 模块不 import 旧 schema。

## 测试

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

---

# 11. 必须新增测试矩阵

新增以下测试文件：

```text
tests/generative_cad/test_gcad_v06_report_schema.py
tests/generative_cad/test_gcad_v06_pipeline_single_pass.py
tests/generative_cad/test_gcad_v06_artifact_builder.py
tests/generative_cad/test_gcad_v06_runtime_postconditions.py
tests/generative_cad/test_gcad_v06_repair_patch.py
tests/generative_cad/test_gcad_v06_native_import_wrappers.py
tests/generative_cad/test_gcad_v06_import_gate_flags.py
tests/generative_cad/test_gcad_v06_legacy_isolation.py
tests/generative_cad/test_gcad_v06_dialect_preflight.py
```

必须继续跑：

```bash
pytest integrations/engineering_tools/tests/generative_cad
pytest integrations/engineering_tools/tests/test_generative_no_main_chain_pollution.py
```

如果存在旧 repair governor 测试，必须明确归入 legacy，不得约束 v0.6 production repair。

---

# 12. 禁止的捷径

Claude Code 不得：

```text
1. 删除 stages_run 调用来绕过 ValidationReport schema 问题。
2. 把 ValidationReport model_config 改成 extra="allow"。
3. 让 artifact.py 接受 **kwargs 但不写入 validation。
4. 继续让 artifact.validation 返回空 dict。
5. 在 pipeline 中重复运行 validators。
6. 在 repair apply 中静默忽略不存在的 node/component。
7. 在 import wrapper 中绕过 import gate。
8. 新增 dialect/op 掩盖 hard-gate 问题。
9. 让 metadata require_validation_ok 在 native import 路径中可选。
10. 修改 Primitive 主链路。
```

---

# 13. Definition of Done

完成标准：

```text
1. ValidationReport 支持 stages_run。
2. pipeline 单次运行 validators，不重复运行。
3. validate_and_canonicalize_with_bundle 返回完整 bundle。
4. artifact.py 签名兼容 builder.py 和 run.py。
5. artifact.validation 不再是空 dict。
6. runner 调用 runtime_postconditions，并写入 metadata。
7. builder 写入完整 validation proof。
8. metadata final validation require_validation_ok=True 通过。
9. import gate 对 invalid metadata、contract mismatch、empty validation 全部 fail。
10. SW/NX wrapper 通过 import gate 后才调用 native import helper。
11. native import helper 已从 tools.py 抽出，便于 monkeypatch。
12. repair patch 对不存在 node/component 报错。
13. production modules 不 import legacy schema。
14. primitive path regression tests 通过。
15. 未新增 dialect/op。
```

---

# 14. 最终正确架构声明

完成 v0.6 后，系统应具备以下结构：

```text
LLM
  ↓
DialectSelectionPlan
  ↓
RawGcadDocument
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
strict inspection
  ↓
generative_metadata_v2.1 with validation proof
  ↓
CanonicalStepArtifact
  ↓
validated SW/NX STEP import wrapper
```

这才是正确的 LLM-Skill-Base / Generative CAD-IR 工程架构。

当前阶段只允许修 hard-gate 和接线问题，不允许扩展 loft/sweep/shell，不允许新增 operation。
