# SeekFlow Engineering Tools — Generative CAD v0.4 Hard-Gate Architecture Implementation Spec

目标仓库：`WYZAAACCC/seekflow-engineering`
目标目录：`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad`
目标版本：Generative CAD v0.4 hard-gate implementation
执行对象：Claude Code
目标结果：将当前 v0.3 partial implementation 修复为真正 fail-closed、可验证、可扩展、可导入 SolidWorks/NX 的 LLM-Skill-Base / Generative CAD-IR 编译链路。

---

# 0. 本次实现的核心原则

本次任务不是继续增加 CAD operation。

本次任务不是继续扩大 dialect 能力。

本次任务不是让 LLM 直接生成 CadQuery / SolidWorks / NX / APDL 代码。

本次任务是修复当前 v0.3 链路中所有 fail-open、半接线、metadata 不可信、import gate 可绕过、legacy 自动适配、repair 半成品、skill schema 不强制的问题。

最终系统必须满足：

```text
LLM outputs only:
  1. DialectSelectionPlan JSON
  2. RawGcadDocument JSON
  3. RepairPatchV2 JSON

LLM never outputs:
  CadQuery
  Python CAD script
  SolidWorks COM
  NXOpen
  APDL
  shell command
  import/export call
  file path
  metadata override
  validation override
  native CAD feature-tree commands

Runtime accepts only:
  CanonicalGcadDocument

SolidWorks/NX generative import accepts only:
  validated STEP + valid generative_metadata_v2.1

Generative path must not enter:
  CADPartSpec
  primitive compiler
  primitive registry
  geometry_primitives
```

---

# 1. 当前代码状态判断

当前代码已经具备以下正确基础：

```text
generative_cad/ir/raw.py
generative_cad/ir/canonical.py
generative_cad/dialects/*
generative_cad/validation/*
generative_cad/pipeline/*
generative_cad/runtime/*
generative_cad/skills/*
generative_cad/repair/*
```

但存在以下阻断性问题：

```text
P0-1: validation pipeline canonical stages 通过 lazy import 接入，ImportError 会被静默跳过。
P0-2: builder 虽有 strict_inspection，但 metadata 写回时 geometry_preflight 仍为空 dict。
P0-3: runner 没有 runtime_postconditions。
P0-4: metadata validator 不要求 validation.*.ok == True。
P0-5: import gate 不真正比对 registry contract hash。
P0-6: import gate 接受空 geometry_preflight 或不完整 validation。
P0-7: tool 层没有 generative SW/NX import wrapper。
P0-8: build_generative_cad_model 自动接受 legacy GenerativeCADSpec 对象并适配到 RawGcadDocument。
P0-9: skill DialectSelectionPlan 没有 schema-level invariants。
P0-10: repair v0.3 只有模型和 stop condition，没有 patch scope validator / apply patch / forbidden path matcher。
```

这些问题必须先修复，才能继续扩展新 dialect 或新 operation。

---

# 2. 正确目标架构

最终架构必须是：

```text
User natural language
  ↓
Level-1 Domain Routing Skill
  ↓
DialectSelectionPlan
  ↓
Load selected Dialect Contracts + Level-2 Dialect Usage Skills
  ↓
LLM emits RawGcadDocument JSON only
  ↓
Raw validation:
    structure
    registry
    params
    ownership
    graph
    typecheck
    phase
    composition
    safety
  ↓
Canonical lowering:
    RawGcadDocument → CanonicalGcadDocument
  ↓
Canonical validation:
    dialect_semantics
    geometry_preflight
  ↓
Fixed runner harness:
    run_canonical_gcad
  ↓
Runtime execution:
    BaseDialect.run_component
    OperationSpec.handler
    RuntimeObjectStore typed handles
  ↓
Runtime postconditions:
    final handle exists
    final handle type is solid
    required component outputs bound
  ↓
STEP export
  ↓
Strict STEP inspection
  ↓
Generative metadata v2.1 with validation proof
  ↓
CanonicalStepArtifact
  ↓
Optional native CAD import:
    generative_cad_import_artifact_to_solidworks
    generative_cad_import_artifact_to_nx
```

Only merge point with existing deterministic path:

```text
canonical STEP artifact + validated metadata
```

Never merge at:

```text
CADPartSpec
Primitive
Primitive compiler
Geometry primitive registry
SolidWorks feature tree
NXOpen feature tree
```

---

# 3. Non-Negotiable Hard Constraints for Claude Code

Claude Code must follow these rules exactly.

## 3.1 Do not modify deterministic primitive semantics

Do not modify behavior of:

```text
seekflow_engineering_tools/ir/cad.py
seekflow_engineering_tools/cadquery_backend/primitive_compiler.py
seekflow_engineering_tools/geometry_primitives/
PRIMITIVE_COMPILERS
PRIMITIVE_REGISTRY
CADPartSpec existing semantics
engineering_build_cad_model existing primitive route
engineering_validate_cad_ir existing primitive route
```

Adding tests around these files is allowed.

## 3.2 Do not make generative dialects primitives

Forbidden:

```text
axisymmetric
sketch_extrude
composition
axisymmetric_base
sketch_extrude_base
composition_base
```

must never appear in:

```text
PRIMITIVE_COMPILERS
PRIMITIVE_REGISTRY
stable_primitives
CADPartSpec.features
```

## 3.3 No automatic legacy upgrade in production builder

`build_generative_cad_model()` must not automatically accept v0.1 `GenerativeCADSpec` object.

Current behavior to remove:

```python
if hasattr(spec, 'feature_graph') and not hasattr(spec, 'components'):
    from seekflow_engineering_tools.generative_cad.compatibility.legacy_spec_adapter import adapt_legacy_spec
    spec = adapt_legacy_spec(spec)
```

Replace with fail-closed:

```python
if hasattr(spec, "feature_graph") and not hasattr(spec, "components"):
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error=(
            "Legacy GenerativeCADSpec v0.1 is not accepted by the v0.4 production builder. "
            "Convert explicitly using generative_cad.compatibility.legacy_spec_adapter in a legacy-only workflow."
        ),
    ).model_dump()
```

Legacy adapter may remain for tests or manual migration, but production tools must not silently accept legacy input.

## 3.4 No optional canonical validators

`dialect_semantics` and `geometry_preflight` must not be optional.

If these modules cannot import, validation must fail at import time or at validation time.

Do not silently skip canonical validators.

## 3.5 Metadata must be proof, not decoration

Generative metadata must prove that validation ran.

Metadata with this shape must fail:

```json
{
  "validation": {
    "core_validation": {},
    "dialect_semantics": {},
    "geometry_preflight": {},
    "runtime_postconditions": {},
    "inspection_validation": {}
  }
}
```

Each required stage must contain `ok: true` for production artifact import.

---

# 4. Implementation Phase Plan

Implement in the following order.

```text
Phase 1: validation pipeline hardening
Phase 2: validation report capture and propagation
Phase 3: runtime postconditions
Phase 4: metadata v2.1 hard validation
Phase 5: strict artifact inspection persistence
Phase 6: native CAD import gate hardening
Phase 7: SolidWorks/NX generative wrappers
Phase 8: legacy isolation and production builder cleanup
Phase 9: Skill schema invariants and prompt hardening
Phase 10: RepairPatchV2 implementation
Phase 11: test suite cleanup and mandatory regression coverage
```

Do not start Phase 7 before Phases 1–6 are passing.

Do not add new dialects before all phases pass.

---

# 5. Phase 1 — Validation Pipeline Hardening

## 5.1 File to modify

```text
generative_cad/validation/pipeline.py
```

## 5.2 Required change

Remove `_get_canonical_stages()` entirely.

Replace lazy imports with direct imports:

```python
from seekflow_engineering_tools.generative_cad.validation.dialect_semantics import (
    validate_dialect_semantics,
)
from seekflow_engineering_tools.generative_cad.validation.geometry_preflight import (
    validate_geometry_preflight,
)
```

Canonical stages must be fixed:

```python
CANONICAL_STAGES = [
    ("dialect_semantics", validate_dialect_semantics),
    ("geometry_preflight", validate_geometry_preflight),
]
```

Raw stages must remain:

```python
RAW_STAGES = [
    ("structure", validate_structure),
    ("registry", validate_registry),
    ("params", validate_params),
    ("ownership", validate_ownership),
    ("graph", validate_graph),
    ("typecheck", validate_typecheck),
    ("phase", validate_phase),
    ("composition", validate_composition_requirements),
    ("safety", validate_safety),
]
```

## 5.3 Return value change

Current success returns:

```python
ValidationReport(ok=True, stage="canonicalize", issues=all_issues)
```

Change to:

```python
ValidationReport(
    ok=True,
    stage="complete",
    issues=all_issues,
    stages_run=[...],
)
```

If `ValidationReport` does not support `stages_run`, add it as an optional field with default empty list.

Recommended model:

```python
class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    stage: str
    issues: list[ValidationIssue] = Field(default_factory=list)
    stages_run: list[str] = Field(default_factory=list)
```

For failed report, `stages_run` must include every stage executed before failure and the failing stage.

## 5.4 Required behavior

If `dialect_semantics` import fails, test collection or module import must fail.

If `geometry_preflight` import fails, test collection or module import must fail.

No silent fallback.

## 5.5 Acceptance tests

Add:

```text
tests/generative_cad/test_gcad_v04_pipeline_hardening.py
```

Tests:

```python
def test_canonical_validators_are_not_lazy_optional():
    import inspect
    from seekflow_engineering_tools.generative_cad.validation import pipeline

    src = inspect.getsource(pipeline)
    assert "_get_canonical_stages" not in src
    assert "except ImportError" not in src
    assert "validate_dialect_semantics" in src
    assert "validate_geometry_preflight" in src


def test_success_report_stage_is_complete():
    canonical, report = validate_and_canonicalize(valid_minimal_axisymmetric_doc())
    assert canonical is not None
    assert report.ok
    assert report.stage == "complete"
    assert "geometry_preflight" in report.stages_run
```

---

# 6. Phase 2 — Validation Report Capture and Propagation

The system currently loses detailed canonical validation reports after `validate_and_canonicalize()` returns one combined `ValidationReport`.

For metadata and artifact import, we need structured stage reports.

## 6.1 Add validation bundle

Create:

```text
generative_cad/validation/bundle.py
```

Implement:

```python
from pydantic import BaseModel, ConfigDict, Field
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport

class ValidationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    raw_stage_reports: dict[str, ValidationReport] = Field(default_factory=dict)
    canonicalize_report: ValidationReport | None = None
    canonical_stage_reports: dict[str, ValidationReport] = Field(default_factory=dict)

    def to_metadata_dict(self) -> dict:
        core_issues = []
        for report in self.raw_stage_reports.values():
            core_issues.extend([i.model_dump() for i in report.issues])
        if self.canonicalize_report is not None:
            core_issues.extend([i.model_dump() for i in self.canonicalize_report.issues])

        dialect = self.canonical_stage_reports.get("dialect_semantics")
        preflight = self.canonical_stage_reports.get("geometry_preflight")

        return {
            "core_validation": {
                "ok": all(r.ok for r in self.raw_stage_reports.values())
                and (self.canonicalize_report.ok if self.canonicalize_report else False),
                "stages": {k: v.model_dump() for k, v in self.raw_stage_reports.items()},
                "canonicalize": self.canonicalize_report.model_dump() if self.canonicalize_report else None,
                "issues": core_issues,
            },
            "dialect_semantics": dialect.model_dump() if dialect else {"ok": False, "stage": "dialect_semantics", "issues": [{"code": "missing_dialect_semantics_report"}]},
            "geometry_preflight": preflight.model_dump() if preflight else {"ok": False, "stage": "geometry_preflight", "issues": [{"code": "missing_geometry_preflight_report"}]},
        }
```

## 6.2 Add validate function returning bundle

Modify `validation/pipeline.py`:

Keep existing:

```python
validate_and_canonicalize(raw) -> tuple[CanonicalGcadDocument | None, ValidationReport]
```

Add new:

```python
validate_and_canonicalize_with_bundle(
    raw: dict | RawGcadDocument,
) -> tuple[CanonicalGcadDocument | None, ValidationReport, ValidationBundle]
```

`validate_and_canonicalize()` should call the new function and return the first two values for backward compatibility.

## 6.3 Builder must use bundle

Modify:

```text
generative_cad/builder.py
```

Change:

```python
canonical, report = validate_and_canonicalize(spec)
```

to:

```python
canonical, report, validation_bundle = validate_and_canonicalize_with_bundle(spec)
```

When validation fails, include:

```python
metrics={
    "validation": report.model_dump(),
    "validation_bundle": validation_bundle.model_dump(),
}
```

When validation succeeds, pass `validation_bundle` into runner or metadata.

Because the runner is executed as a subprocess from canonical JSON, easiest implementation is:

1. Builder runs validation and gets bundle.
2. Builder writes canonical JSON.
3. Harness runs canonical JSON and creates metadata with placeholder validation.
4. Builder reloads metadata and overwrites `metadata["validation"]` with:

   * `validation_bundle.to_metadata_dict()`
   * `runtime_postconditions`
   * `inspection_validation`

This is acceptable for v0.4.

Do not lose stage reports.

---

# 7. Phase 3 — Runtime Postconditions

## 7.1 Add file

```text
generative_cad/runtime/postconditions.py
```

## 7.2 Implement

```python
from pathlib import Path
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext

def validate_runtime_postconditions(
    canonical: CanonicalGcadDocument,
    ctx: RuntimeContext,
    final_handle_id: str,
) -> dict:
    issues = []

    if not final_handle_id:
        issues.append({
            "stage": "runtime_postconditions",
            "code": "missing_final_handle",
            "message": "Runner did not produce a final solid handle.",
            "severity": "error",
        })
        return {"ok": False, "stage": "runtime_postconditions", "issues": issues}

    try:
        handle = ctx.object_store.get_handle(final_handle_id)
    except AttributeError:
        handle = None
    except Exception as exc:
        issues.append({
            "stage": "runtime_postconditions",
            "code": "final_handle_lookup_failed",
            "message": str(exc),
            "severity": "error",
        })
        return {"ok": False, "stage": "runtime_postconditions", "issues": issues}

    if handle is not None:
        htype = getattr(handle, "type", None) or getattr(handle, "value_type", None)
        if str(htype) not in ("solid", "ValueType.SOLID"):
            issues.append({
                "stage": "runtime_postconditions",
                "code": "final_handle_not_solid",
                "message": f"Final handle must be solid, got {htype!r}.",
                "severity": "error",
            })

    for comp in canonical.components:
        if comp.id == "__assembly__":
            continue
        if not comp.root_node:
            issues.append({
                "stage": "runtime_postconditions",
                "code": "component_missing_root_node",
                "message": f"Component {comp.id!r} has no root_node.",
                "severity": "error",
                "component_id": comp.id,
            })

    return {
        "ok": not any(i["severity"] == "error" for i in issues),
        "stage": "runtime_postconditions",
        "issues": issues,
    }
```

Adapt object store access to actual `RuntimeObjectStore` API. If `get_handle` does not exist, add it.

## 7.3 Modify runner

File:

```text
generative_cad/pipeline/run.py
```

After:

```python
final_handle_id = _run_composition_or_select_final(canonical, ctx)
```

add:

```python
runtime_postconditions = validate_runtime_postconditions(canonical, ctx, final_handle_id)
if not runtime_postconditions["ok"]:
    return GcadRunResult(
        ok=False,
        error="runtime postconditions failed: "
        + "; ".join(i["message"] for i in runtime_postconditions["issues"]),
        warnings=ctx.warnings,
        degraded_features=ctx.degraded_features,
        operation_metrics=ctx.operation_metrics,
    )
```

Then export:

```python
_export_final_solid(final_handle_id, ctx)
```

Then metadata:

```python
metadata = build_generative_metadata(
    canonical=canonical,
    ctx=ctx,
    validation={
        "runtime_postconditions": runtime_postconditions,
    },
)
```

Do not mark runtime postconditions as skipped.

## 7.4 Acceptance tests

```python
def test_runtime_postconditions_reject_missing_final_handle():
    result = validate_runtime_postconditions(canonical, ctx, "")
    assert not result["ok"]
    assert any(i["code"] == "missing_final_handle" for i in result["issues"])
```

---

# 8. Phase 4 — Metadata v2.1 Hard Validation

## 8.1 File to modify

```text
generative_cad/pipeline/metadata.py
```

## 8.2 Required metadata shape

Metadata must be:

```json
{
  "generative_metadata": {
    "metadata_version": "generative_metadata_v2",
    "metadata_schema_minor": "2.1",
    "source_route": "llm_skill_base",
    "schema_version": "...",
    "canonical_version": "...",
    "trust_level": "reference_geometry",
    "part_name": "...",
    "selected_dialects": [
      {
        "dialect": "axisymmetric",
        "version": "0.2.0",
        "contract_hash": "sha256:..."
      }
    ],
    "op_versions": [
      {
        "node_id": "...",
        "dialect": "...",
        "op": "...",
        "op_version": "..."
      }
    ],
    "raw_graph_hash": "sha256:...",
    "canonical_graph_hash": "sha256:...",
    "runner_version": "...",
    "geometry_runtime": "...",
    "operation_metrics": [],
    "degraded_features": [],
    "repair_attempts": 0,
    "warnings": [],
    "safety": {
      "non_flight_reference_only": true,
      "not_airworthy": true,
      "not_certified": true,
      "not_for_manufacturing": true,
      "not_for_installation": true,
      "no_structural_validation": true,
      "no_life_prediction": true
    }
  },
  "build_warnings": [],
  "validation": {
    "core_validation": {"ok": true, "...": "..."},
    "dialect_semantics": {"ok": true, "...": "..."},
    "geometry_preflight": {"ok": true, "...": "..."},
    "runtime_postconditions": {"ok": true, "...": "..."},
    "inspection_validation": {"ok": true, "...": "..."}
  }
}
```

## 8.3 build_generative_metadata behavior

Current default validation is unsafe because it creates empty dicts.

Change default:

```python
if validation is None:
    validation = {
        "core_validation": {
            "ok": False,
            "stage": "core_validation",
            "issues": [{"code": "missing_core_validation_report"}],
        },
        "dialect_semantics": {
            "ok": False,
            "stage": "dialect_semantics",
            "issues": [{"code": "missing_dialect_semantics_report"}],
        },
        "geometry_preflight": {
            "ok": False,
            "stage": "geometry_preflight",
            "issues": [{"code": "missing_geometry_preflight_report"}],
        },
        "runtime_postconditions": {
            "ok": False,
            "stage": "runtime_postconditions",
            "issues": [{"code": "missing_runtime_postconditions_report"}],
        },
        "inspection_validation": {
            "ok": False,
            "stage": "inspection_validation",
            "issues": [{"code": "missing_inspection_validation_report"}],
        },
    }
```

This ensures metadata generated without validation proof fails validation.

## 8.4 validate_generative_metadata_v2 behavior

Add parameter:

```python
def validate_generative_metadata_v2(
    metadata: dict,
    canonical: CanonicalGcadDocument | None = None,
    registry_check: bool = True,
    require_validation_ok: bool = False,
) -> dict:
```

Default `require_validation_ok=False` for backward compatibility, but import gate must call with `require_validation_ok=True`.

Required checks always:

```text
generative_metadata exists
metadata_version == generative_metadata_v2
metadata_schema_minor exists
source_route == llm_skill_base
trust_level in concept_geometry/reference_geometry
selected_dialects non-empty
each selected dialect has dialect/version/contract_hash
canonical_graph_hash starts sha256:
raw_graph_hash starts sha256:
runner_version non-empty
geometry_runtime non-empty
safety flags all true
build_warnings is list
validation is dict
validation.core_validation exists and is dict
validation.dialect_semantics exists and is dict
validation.geometry_preflight exists and is dict
validation.runtime_postconditions exists and is dict
validation.inspection_validation exists and is dict
```

If `require_validation_ok=True`, additionally require:

```python
for key in [
    "core_validation",
    "dialect_semantics",
    "geometry_preflight",
    "runtime_postconditions",
    "inspection_validation",
]:
    stage = validation.get(key)
    if not isinstance(stage, dict) or stage.get("ok") is not True:
        issue(code=f"{key}_not_ok")
```

If `registry_check=True`, always compare metadata contract hashes against current registry, even when `canonical is None`.

Implementation:

```python
if registry_check:
    for d in gm.get("selected_dialects", []):
        did = d.get("dialect")
        try:
            reg_hash = dialect_contract_hash(did)
        except KeyError:
            issues.append({
                "code": "unknown_metadata_dialect",
                "message": f"metadata references unknown dialect {did!r}",
            })
            continue

        if d.get("contract_hash") != reg_hash:
            issues.append({
                "code": "contract_hash_mismatch",
                "message": (
                    f"dialect {did!r} contract_hash mismatch: "
                    f"metadata={d.get('contract_hash')}, registry={reg_hash}"
                ),
            })
```

Do not gate this behind `canonical is not None`.

## 8.5 Acceptance tests

```text
tests/generative_cad/test_gcad_v04_metadata_hard_validation.py
```

Tests:

```python
def test_metadata_validator_rejects_empty_validation_when_required():
    meta = valid_metadata()
    meta["validation"] = {
        "core_validation": {},
        "dialect_semantics": {},
        "geometry_preflight": {},
        "runtime_postconditions": {},
        "inspection_validation": {},
    }
    result = validate_generative_metadata_v2(meta, require_validation_ok=True)
    assert not result["ok"]
    assert any(i["code"] == "core_validation_not_ok" for i in result["issues"])


def test_metadata_validator_checks_registry_contract_without_canonical():
    meta = valid_metadata()
    meta["generative_metadata"]["selected_dialects"][0]["contract_hash"] = "sha256:bad"
    result = validate_generative_metadata_v2(meta, canonical=None, registry_check=True)
    assert not result["ok"]
    assert any(i["code"] == "contract_hash_mismatch" for i in result["issues"])


def test_metadata_validator_requires_runtime_postconditions():
    meta = valid_metadata()
    del meta["validation"]["runtime_postconditions"]
    result = validate_generative_metadata_v2(meta, require_validation_ok=True)
    assert not result["ok"]
```

---

# 9. Phase 5 — Strict Artifact Inspection Persistence

## 9.1 File to modify

```text
generative_cad/builder.py
```

## 9.2 Existing good behavior to preserve

`build_generative_cad_model()` already has:

```python
strict_inspection: bool = True
```

and already fails if inspection returns error while strict inspection is true.

Keep that.

## 9.3 Required fix: write real validation into metadata

Current code writes:

```python
metadata["validation"] = {
    "core_validation": report.model_dump(),
    "geometry_preflight": {},
    "inspection_validation": insp_val,
}
```

This is wrong.

It must write:

```python
validation_meta = validation_bundle.to_metadata_dict()
validation_meta["runtime_postconditions"] = metadata.get("validation", {}).get(
    "runtime_postconditions",
    {
        "ok": False,
        "stage": "runtime_postconditions",
        "issues": [{"code": "missing_runtime_postconditions_report"}],
    },
)
validation_meta["inspection_validation"] = insp_val

metadata["validation"] = validation_meta
```

Then revalidate metadata after writing:

```python
meta_validation = validate_generative_metadata_v2(
    metadata,
    canonical=canonical,
    registry_check=True,
    require_validation_ok=True,
)
if not meta_validation["ok"]:
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error="Metadata v2.1 invalid after inspection: "
        + "; ".join(i["message"] for i in meta_validation["issues"]),
        files_created=files_created,
        metrics=metrics,
    ).model_dump()
```

Important ordering:

```text
1. Runner creates STEP + initial metadata.
2. Builder loads initial metadata.
3. Builder validates initial metadata without require_validation_ok if runtime/inspection not yet attached.
4. Builder inspects STEP.
5. Builder overwrites metadata.validation with full validation bundle + runtime + inspection.
6. Builder revalidates metadata with require_validation_ok=True.
7. Only then return ok=True.
```

## 9.4 Required fix: path guard for graph_out/script_out

Current code does not enforce workspace guard for explicit `graph_out` and `script_out`.

Replace:

```python
graph_path = graph_out if graph_out else ...
graph_path = Path(graph_path)
```

with:

```python
if graph_out is not None:
    graph_path = ensure_inside_workspace(workspace, graph_out)
else:
    graph_path = graph_dir / f"gcad_{uuid.uuid4().hex[:12]}.json"
```

Same for `script_out`.

## 9.5 Acceptance tests

```text
tests/generative_cad/test_gcad_v04_builder_metadata.py
```

Tests:

```python
def test_builder_metadata_contains_all_validation_stages(tmp_path):
    result = build_generative_cad_model(valid_doc(), config, tmp_path / "part.step")
    assert result["ok"]
    meta = json.loads(Path(result["files_created"][-1]).read_text())
    val = meta["validation"]
    for key in [
        "core_validation",
        "dialect_semantics",
        "geometry_preflight",
        "runtime_postconditions",
        "inspection_validation",
    ]:
        assert key in val
        assert val[key]["ok"] is True


def test_graph_out_outside_workspace_rejected(tmp_path):
    result = build_generative_cad_model(
        valid_doc(),
        config,
        tmp_path / "part.step",
        graph_out="/tmp/outside.json",
    )
    assert not result["ok"]
```

---

# 10. Phase 6 — Native Import Gate Hardening

## 10.1 File to modify

```text
generative_cad/pipeline/import_artifact.py
```

## 10.2 Required behavior

`validate_generative_step_artifact_for_native_import()` must call:

```python
meta_result = validate_generative_metadata_v2(
    metadata,
    canonical=None,
    registry_check=registry_check,
    require_validation_ok=True,
)
```

No artifact with incomplete validation may pass.

## 10.3 Fix geometry_preflight check

Current logic allows `{}`.

Change to:

```python
gp = val.get("geometry_preflight")
if require_geometry_preflight_ok:
    if not isinstance(gp, dict) or gp.get("ok") is not True:
        issues.append({
            "code": "geometry_preflight_not_ok",
            "message": "geometry_preflight.ok must be true for native import",
        })
        return fail
```

## 10.4 Fix inspection check

Use:

```python
insp = val.get("inspection_validation")
if require_inspection_ok:
    if not isinstance(insp, dict) or insp.get("ok") is not True:
        issues.append({
            "code": "inspection_not_ok",
            "message": "inspection_validation.ok must be true for native import",
        })
        return fail
```

## 10.5 Fix contract hash

Remove local prefix-only contract hash check as sufficient proof.

Keep prefix check as basic format, but always compare registry:

```python
for d in gm.get("selected_dialects", []):
    did = d.get("dialect")
    try:
        expected_hash = dialect_contract_hash(did)
    except KeyError:
        fail unknown dialect
    if d.get("contract_hash") != expected_hash:
        fail contract_hash_mismatch
```

## 10.6 Native rebuild flag

Explicitly reject any metadata or top-level artifact field indicating native rebuild.

```python
if gm.get("native_rebuild_allowed") is True:
    issues.append({
        "code": "native_rebuild_forbidden",
        "message": "Generative artifacts may only be imported as canonical STEP; native rebuild is forbidden.",
    })
```

Also reject:

```python
if metadata.get("native_rebuild_allowed") is True:
    ...
```

## 10.7 Return shape

Return:

```python
{
    "ok": bool,
    "issues": issues,
    "metadata": metadata,
    "gate": {
        "step_exists": True,
        "metadata_exists": True,
        "metadata_valid": True,
        "safety_valid": True,
        "contract_hash_valid": True,
        "core_validation_ok": True,
        "dialect_semantics_ok": True,
        "geometry_preflight_ok": True,
        "runtime_postconditions_ok": True,
        "inspection_ok": True,
        "native_rebuild_allowed": False,
        "step_import_allowed": True,
    },
}
```

## 10.8 Acceptance tests

```text
tests/generative_cad/test_gcad_v04_import_gate.py
```

Tests:

```python
def test_import_gate_rejects_empty_geometry_preflight():
    meta = valid_metadata()
    meta["validation"]["geometry_preflight"] = {}
    write step + metadata
    result = validate_generative_step_artifact_for_native_import(step, meta_path)
    assert not result["ok"]
    assert any(i["code"] == "geometry_preflight_not_ok" for i in result["issues"])


def test_import_gate_rejects_contract_hash_mismatch():
    meta = valid_metadata()
    meta["generative_metadata"]["selected_dialects"][0]["contract_hash"] = "sha256:bad"
    result = validate_generative_step_artifact_for_native_import(step, meta_path)
    assert not result["ok"]


def test_import_gate_rejects_native_rebuild_allowed():
    meta = valid_metadata()
    meta["generative_metadata"]["native_rebuild_allowed"] = True
    result = validate_generative_step_artifact_for_native_import(step, meta_path)
    assert not result["ok"]
```

---

# 11. Phase 7 — SolidWorks/NX Generative Import Wrappers

## 11.1 File to modify

```text
generative_cad/tools.py
```

## 11.2 Add tools

Add:

```text
generative_cad_import_artifact_to_solidworks
generative_cad_import_artifact_to_nx
```

These tools are mandatory.

## 11.3 Shared helper recommendation

Do not call decorated tool functions from tools.

Extract import helpers if necessary:

```text
solidworks/importers.py
  import_step_as_sldprt(config, input_step, out_sldprt) -> dict

nx/importers.py
  import_step_as_prt(config, input_step, out_prt) -> dict
```

If existing SolidWorks/NX code already has helpers, reuse them.

## 11.4 SolidWorks wrapper signature

```python
@tool(
    name="generative_cad_import_artifact_to_solidworks",
    description=(
        "Import a validated Generative CAD canonical STEP artifact into SolidWorks "
        "as SLDPRT. Requires generative_metadata_v2.1 import gate to pass. "
        "Does not rebuild native feature tree."
    ),
    cache=False,
    sanitize=True,
    trusted=False,
)
def generative_cad_import_artifact_to_solidworks(
    step_path: str,
    metadata_path: str,
    out_sldprt: str,
) -> dict:
    ...
```

Implementation:

```python
step = ensure_inside_workspace(config.workspace_root, step_path)
meta = ensure_inside_workspace(config.workspace_root, metadata_path)
out = ensure_inside_workspace(config.workspace_root, out_sldprt)

ensure_extension(step, {".step", ".stp"})
ensure_extension(meta, {".json"})
ensure_extension(out, {".sldprt"})

gate = validate_generative_step_artifact_for_native_import(
    step,
    meta,
    require_inspection_ok=True,
    require_geometry_preflight_ok=True,
    registry_check=True,
)

if not gate["ok"]:
    return EngineeringActionResult(
        ok=False,
        software="solidworks",
        action="generative_cad_import_artifact_to_solidworks",
        error="Generative artifact import gate failed: "
        + "; ".join(i["message"] for i in gate["issues"]),
        metrics={"import_gate": gate["gate"], "issues": gate["issues"]},
    ).model_dump()

result = import_step_as_sldprt(config, step, out)

return EngineeringActionResult(
    ok=result["ok"],
    software="solidworks",
    action="generative_cad_import_artifact_to_solidworks",
    message="Validated generative STEP imported into SolidWorks.",
    files_created=[str(out)] if result["ok"] else [],
    error=result.get("error"),
    metrics={
        "source_route": "llm_skill_base",
        "strategy": "validated_generative_step_import",
        "native_rebuild_allowed": False,
        "step_import_allowed": True,
        "source_step": str(step),
        "source_metadata": str(meta),
        "native_path": str(out),
        "import_gate": gate["gate"],
        "canonical_graph_hash": gate["metadata"]["generative_metadata"]["canonical_graph_hash"],
        "selected_dialects": gate["metadata"]["generative_metadata"]["selected_dialects"],
        "native_import_result": result,
    },
    warnings=[
        "Native SolidWorks file was created by importing validated generative canonical STEP.",
        "Native feature tree was not regenerated.",
        "Generative output is reference geometry only.",
        "Not certified, not manufacturing-ready, not installable.",
    ],
).model_dump()
```

## 11.5 NX wrapper signature

```python
@tool(
    name="generative_cad_import_artifact_to_nx",
    description=(
        "Import a validated Generative CAD canonical STEP artifact into Siemens NX "
        "as PRT. Requires generative_metadata_v2.1 import gate to pass. "
        "Does not rebuild native feature tree."
    ),
    cache=False,
    sanitize=True,
    trusted=False,
)
def generative_cad_import_artifact_to_nx(
    step_path: str,
    metadata_path: str,
    out_prt: str,
) -> dict:
    ...
```

Same gate and warning policy as SolidWorks.

## 11.6 Tool policy

SolidWorks wrapper:

```python
ToolPolicy(
    capabilities={"cad.generative.read", "cad.solidworks.write", "filesystem.write"},
    risk="write",
    timeout_s=180,
    workspace_root=config.workspace_root,
    path_params=frozenset({"step_path", "metadata_path", "out_sldprt"}),
    parallel_safe=False,
    requires_approval=False,
    idempotent=False,
)
```

NX wrapper:

```python
ToolPolicy(
    capabilities={"cad.generative.read", "cad.nx.write", "filesystem.write"},
    risk="write",
    timeout_s=180,
    workspace_root=config.workspace_root,
    path_params=frozenset({"step_path", "metadata_path", "out_prt"}),
    parallel_safe=False,
    requires_approval=False,
    idempotent=False,
)
```

## 11.7 Acceptance tests

```text
tests/generative_cad/test_gcad_v04_native_import_wrappers.py
```

Tests with monkeypatch:

```python
def test_solidworks_wrapper_does_not_call_import_when_gate_fails(monkeypatch):
    called = False

    def fake_import(*args, **kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(..., fake_import)
    result = tool(step_path=valid_step, metadata_path=bad_meta, out_sldprt="x.sldprt")
    assert not result["ok"]
    assert called is False


def test_nx_wrapper_does_not_call_import_when_gate_fails(monkeypatch):
    ...
```

---

# 12. Phase 8 — Legacy Isolation and Production Cleanup

## 12.1 Current acceptable legacy files

The following may remain only as compatibility re-exports or under `legacy/`:

```text
generative_cad/legacy/*
generative_cad/compatibility/legacy_spec_adapter.py
generative_cad/prompts.py as backward-compat re-export only
```

## 12.2 Production code must not import legacy

Production files must not import:

```text
generative_cad.legacy.*
GenerativeCADSpec
FeatureGraph
SelectedBase
BASE_REGISTRY
selected_bases
feature_graph
```

Allowed exception:

```text
generative_cad/compatibility/legacy_spec_adapter.py
legacy-only tests
generative_cad/prompts.py backward-compat re-export
```

## 12.3 Remove automatic legacy adaptation from builder

As specified in Section 3.3, production builder must reject legacy object input.

## 12.4 Tests

```text
tests/generative_cad/test_gcad_v04_legacy_isolation.py
```

Tests:

```python
def test_builder_does_not_auto_adapt_legacy_spec():
    legacy = make_legacy_generative_spec()
    result = build_generative_cad_model(legacy, config, "out.step")
    assert not result["ok"]
    assert "Legacy GenerativeCADSpec" in result["error"]


def test_production_modules_do_not_import_legacy():
    modules = [
        "seekflow_engineering_tools.generative_cad.builder",
        "seekflow_engineering_tools.generative_cad.pipeline.run",
        "seekflow_engineering_tools.generative_cad.validation.pipeline",
        "seekflow_engineering_tools.generative_cad.tools",
    ]
    for modname in modules:
        mod = importlib.import_module(modname)
        src = inspect.getsource(mod)
        assert "GenerativeCADSpec" not in src
        assert "selected_bases" not in src
        assert "BASE_REGISTRY" not in src
```

---

# 13. Phase 9 — Skill Schema Invariants and Prompt Hardening

## 13.1 File to modify

```text
generative_cad/skills/schemas.py
```

## 13.2 Add validators

Add:

```python
from pydantic import model_validator
```

Implement:

```python
@model_validator(mode="after")
def validate_route_invariants(self):
    if self.route_decision == "generative_cad_ir":
        if not self.selected_dialects:
            raise ValueError("generative_cad_ir requires selected_dialects")

    if self.route_decision == "deterministic_primitive":
        if self.selected_dialects:
            raise ValueError("deterministic_primitive must not select generative dialects")

    if self.route_decision == "unsupported":
        if not self.unsupported_capabilities:
            raise ValueError("unsupported route requires unsupported_capabilities")

    seen = set()
    for d in self.selected_dialects:
        if d.dialect in seen:
            raise ValueError(f"duplicate selected dialect: {d.dialect}")
        seen.add(d.dialect)

    return self
```

## 13.3 Catalog validation

Add optional function:

```python
def validate_selection_plan_against_catalog(
    plan: DialectSelectionPlan,
    catalog: dict,
) -> tuple[bool, list[dict]]:
    allowed = {d["dialect_id"] for d in catalog.get("dialects", [])}
    issues = []
    for item in plan.selected_dialects:
        if item.dialect not in allowed:
            issues.append({
                "code": "unknown_selected_dialect",
                "message": f"selected dialect {item.dialect!r} not present in catalog",
            })
    return len(issues) == 0, issues
```

Do not rely on prompt text for dialect existence.

## 13.4 Prompt hardening

File:

```text
generative_cad/skills/prompts.py
```

Update Level-2 prompt rule 24.

Current rule:

```text
If the request cannot be expressed with the selected contracts, output a JSON object with unsupported_capabilities instead of inventing ops.
```

This conflicts with `RawGcadDocument` schema because RawGcadDocument does not contain top-level `unsupported_capabilities`.

Change to:

```text
24. If the request cannot be expressed with the selected contracts, do not produce RawGcadDocument. Return the Level-1 route_decision "unsupported" in the routing step. During Level-2 authoring, never invent fallback fields such as unsupported_capabilities because RawGcadDocument forbids extra fields.
```

Add rule:

```text
25. Do not include comments, markdown, prose, or trailing commas.
26. Do not use deprecated fields: selected_bases, feature_graph, base_id, system_validation_contract, ir_version.
27. Use selected_dialects, components, nodes, constraints, safety only.
```

## 13.5 Orchestrator output schema

File:

```text
generative_cad/skills/orchestrator.py
```

`build_repair_prompt_v2()` must include output schema:

```python
from seekflow_engineering_tools.generative_cad.repair.patch import RepairPatchV2

return {
    "system": REPAIR_PATCH_SYSTEM_PROMPT_V2,
    "user": ...,
    "output_schema": RepairPatchV2.model_json_schema(),
}
```

## 13.6 Tests

```text
tests/generative_cad/test_gcad_v04_skills.py
```

Tests:

```python
def test_generative_route_requires_dialects():
    with pytest.raises(ValueError):
        DialectSelectionPlan(route_decision="generative_cad_ir", selected_dialects=[])


def test_unsupported_route_requires_unsupported_capabilities():
    with pytest.raises(ValueError):
        DialectSelectionPlan(route_decision="unsupported", unsupported_capabilities=[])


def test_level2_prompt_does_not_suggest_extra_unsupported_capabilities_field():
    assert "output a JSON object with unsupported_capabilities" not in LEVEL2_AUTHORING_SYSTEM_PROMPT


def test_repair_prompt_has_schema():
    prompt = build_repair_prompt_v2({}, {"issues": []}, {})
    assert "output_schema" in prompt
```

---

# 14. Phase 10 — RepairPatchV2 Implementation

Current repair v0.3 is incomplete. Implement actual patch validation and application.

## 14.1 File to modify

```text
generative_cad/repair/patch.py
```

## 14.2 Replace path constants

Current constants like:

```python
"/nodes//params/"
```

are not usable.

Replace with path parser functions.

## 14.3 Required functions

Implement:

```python
def is_forbidden_repair_path(path: str) -> bool:
    ...
```

Forbidden exact prefixes:

```text
/schema_version
/selected_dialects
/safety
/constraints/require_step_file
/constraints/require_metadata_sidecar
/constraints/require_closed_solid
```

Forbidden node fields:

```text
/nodes/<node_id>/dialect
/nodes/<node_id>/op
/nodes/<node_id>/op_version
```

Forbidden component fields:

```text
/components/<component_id>/owner_dialect
```

Implement:

```python
def is_allowed_repair_path(path: str) -> bool:
    ...
```

Allowed:

```text
/nodes/<node_id>/params/<field>
/nodes/<node_id>/inputs
/nodes/<node_id>/outputs
/nodes/<node_id>/required
/nodes/<node_id>/degradation_policy
/components/<component_id>/root_node
/llm_validation_hints
```

Implement:

```python
def validate_repair_patch_v2(patch: RepairPatchV2) -> tuple[bool, list[dict]]:
    issues = []
    if patch.give_up:
        return True, []
    if not patch.changes:
        issues.append({"code": "empty_repair_patch", "message": "repair patch has no changes"})
    for change in patch.changes:
        if is_forbidden_repair_path(change.path):
            issues.append({"code": "forbidden_repair_path", "message": f"path {change.path!r} is forbidden"})
        elif not is_allowed_repair_path(change.path):
            issues.append({"code": "unsupported_repair_path", "message": f"path {change.path!r} is not allowed"})
    return len(issues) == 0, issues
```

Implement:

```python
def apply_repair_patch_v2(raw: dict, patch: RepairPatchV2) -> dict:
    ok, issues = validate_repair_patch_v2(patch)
    if not ok:
        raise ValueError("invalid repair patch: " + "; ".join(i["message"] for i in issues))

    updated = copy.deepcopy(raw)
    for change in patch.changes:
        apply_one_change(updated, change)
    return updated
```

Path semantics:

* `/nodes/<node_id>/params/<field>` finds node by `id`, updates `node["params"][field]`.
* `/nodes/<node_id>/inputs` replaces node inputs.
* `/nodes/<node_id>/outputs` replaces node outputs.
* `/components/<component_id>/root_node` finds component by `id`, updates root_node.
* `/llm_validation_hints` replaces or merges `llm_validation_hints`.

Do not support arbitrary JSON pointer traversal. Explicitly support only allowed paths.

## 14.4 Governor fix

File:

```text
generative_cad/repair/governor.py
```

Current progress check rejects same or earlier stage. This is too strict: a repair can stay at the same stage but fix a different issue.

Change rule:

```python
if current_stage_rank < state.last_stage_rank:
    return False, "Validation regressed to an earlier stage"
```

Do not reject equal stage automatically.

Add:

```python
if current_stage_rank == state.last_stage_rank and error_sig_hash in state.error_signature_hashes:
    return False, "Same stage and same error signature repeated"
```

## 14.5 Tests

```text
tests/generative_cad/test_gcad_v04_repair_patch.py
```

Tests:

```python
def test_repair_patch_rejects_safety_change():
    patch = RepairPatchV2(
        changes=[RepairChange(path="/safety/not_certified", new_value=False, reason="bad")],
        reason="bad",
    )
    ok, issues = validate_repair_patch_v2(patch)
    assert not ok


def test_repair_patch_allows_node_param_change():
    patch = RepairPatchV2(
        target_node="n_holes",
        changes=[
            RepairChange(
                path="/nodes/n_holes/params/hole_dia_mm",
                old_value=32,
                new_value=24,
                reason="reduce hole diameter",
            )
        ],
        reason="preflight failed",
    )
    ok, issues = validate_repair_patch_v2(patch)
    assert ok


def test_apply_repair_patch_updates_node_param_only():
    updated = apply_repair_patch_v2(raw_doc, patch)
    assert updated["nodes"][...]["params"]["hole_dia_mm"] == 24
```

---

# 15. Phase 11 — Dialect Semantics and Preflight Strengthening

Current dialect checks are better than before but still too shallow.

## 15.1 axisymmetric semantic strengthening

File:

```text
generative_cad/dialects/axisymmetric/dialect.py
```

Add checks:

```text
A-S1: exactly one node with op == revolve_profile.
A-S2: that node phase must be base_solid.
A-S3: component.root_node must exist in component nodes.
A-S4: component.root_node must output body:solid.
A-S5: every non-base op must have at least one input.
A-S6: every non-base op must consume exactly the previous body chain or a valid solid input.
A-S7: no non-base op may have empty inputs.
A-S8: no second base_solid op.
```

Implementation helper:

```python
def _node_outputs_body_solid(n):
    return any(o.name == "body" and o.type == "solid" for o in n.outputs)
```

For input check:

```python
if n.phase != "base_solid" and not n.inputs:
    issue("axisymmetric_non_base_requires_input")
```

## 15.2 axisymmetric preflight strengthening

Track envelope:

```python
profile_max_radius = max(station["r_mm"] for station in profile_stations)
profile_min_radius = min(station["r_mm"] for station in profile_stations)
center_bore_radius = None
```

For `cut_center_bore`:

```text
diameter_mm > 0
diameter_mm / 2 < profile_max_radius - min_hole_to_boundary_margin_mm
```

For `cut_circular_hole_pattern`:

```text
count >= 3
hole_dia_mm > 0
pcd_mm > 0
pcd_radius + hole_radius < profile_max_radius - min_hole_to_boundary_margin_mm
if center_bore_radius is not None:
    pcd_radius - hole_radius > center_bore_radius + min_hole_to_boundary_margin_mm
```

For `cut_annular_groove`:

```text
inner_dia_mm < outer_dia_mm
outer_dia_mm / 2 < profile_max_radius - margin
```

For `cut_rim_slot_pattern`, use actual params fields. If actual params do not expose enough data, at least check:

```text
count >= 3
all numeric dimensions > 0
pattern radius within profile_max_radius if radius field exists
```

## 15.3 sketch_extrude semantic strengthening

File:

```text
generative_cad/dialects/sketch_extrude/dialect.py
```

Add:

```text
SE-S1: exactly one extrude_rectangle.
SE-S2: extrude_rectangle phase == base_solid.
SE-S3: component.root_node exists.
SE-S4: root_node outputs body:solid.
SE-S5: every non-base op must have solid input and solid output.
SE-S6: no non-base op may have empty inputs.
```

## 15.4 sketch_extrude preflight strengthening

Infer base dimensions from `extrude_rectangle`.

For pocket:

```text
pocket width < base width
pocket height/depth less than corresponding base dimension if fields exist
```

For hole:

```text
diameter < min(base width, base height) - 2 * margin
```

For linear hole pattern:

```text
count >= 1
spacing > 0
diameter > 0
(count - 1) * spacing + diameter < base width or base height depending axis if axis field exists
```

## 15.5 composition semantic strengthening

File:

```text
generative_cad/dialects/composition/dialect.py
```

Add:

```text
C-S1: boolean_union must have exactly 2 inputs for v0.4, because OperationSpec declares ["solid", "solid"].
C-S2: place_component / transform / pattern ops must have exactly 1 solid input.
C-S3: root_node exists.
C-S4: root_node outputs body:solid.
```

## 15.6 composition preflight strengthening

Use real param names.

For rotate:

```text
axis_dir must be numeric vector length 3
norm(axis_dir) > 1e-9
angle_deg finite
```

For translate:

```text
x_mm/y_mm/z_mm finite numbers
```

For pattern:

```text
count >= 1
count <= DEFAULT_GEOMETRY_POLICY["max_pattern_instances"]
```

---

# 16. Tool Naming Cleanup

Current tools use old base names:

```text
generative_cad_list_bases
generative_cad_get_base_contract
```

Keep these as compatibility aliases, but add canonical tools:

```text
generative_cad_list_dialects
generative_cad_get_dialect_contract
```

## 16.1 Implementation

In `tools.py`, implement canonical functions first:

```python
@tool(name="generative_cad_list_dialects", ...)
def generative_cad_list_dialects() -> dict:
    ...
```

Then legacy alias:

```python
@tool(name="generative_cad_list_bases", ...)
def generative_cad_list_bases() -> dict:
    return generative_cad_list_dialects()
```

If decorated tool cannot be called directly, extract helper:

```python
def _list_dialects_result() -> dict:
    ...
```

Do same for contract.

## 16.2 Add tools to return list

Final tools list must include:

```text
generative_cad_list_dialects
generative_cad_get_dialect_contract
generative_cad_list_bases
generative_cad_get_base_contract
generative_cad_validate_ir
generative_cad_build_from_ir
generative_cad_import_artifact_to_solidworks
generative_cad_import_artifact_to_nx
```

---

# 17. Required Test Matrix

All tests below are mandatory.

## 17.1 Pipeline hardening

```text
tests/generative_cad/test_gcad_v04_pipeline_hardening.py
```

Must cover:

```text
canonical validators are not optional
no ImportError pass in pipeline
success report stage == complete
stages_run includes all raw and canonical stages
failure report stages_run includes failing stage
```

## 17.2 Metadata hard validation

```text
tests/generative_cad/test_gcad_v04_metadata_hard_validation.py
```

Must cover:

```text
empty validation fails when require_validation_ok=True
missing dialect_semantics fails
missing runtime_postconditions fails
missing inspection_validation fails
geometry_preflight ok false fails
contract hash mismatch fails without canonical
safety false fails
trust_level too high fails
```

## 17.3 Builder metadata persistence

```text
tests/generative_cad/test_gcad_v04_builder_metadata.py
```

Must cover:

```text
strict inspection failure returns ok=False
non-strict inspection may warn
metadata written by builder contains all validation stages
metadata revalidates with require_validation_ok=True
graph_out outside workspace rejected
script_out outside workspace rejected
legacy spec object rejected by production builder
```

## 17.4 Import gate

```text
tests/generative_cad/test_gcad_v04_import_gate.py
```

Must cover:

```text
missing metadata fails
invalid metadata JSON fails
empty geometry_preflight fails
inspection_validation not ok fails
runtime_postconditions not ok fails
contract hash mismatch fails
native_rebuild_allowed fails
valid metadata + step passes
```

## 17.5 Native wrappers

```text
tests/generative_cad/test_gcad_v04_native_import_wrappers.py
```

Must cover:

```text
solidworks wrapper does not call import helper when gate fails
nx wrapper does not call import helper when gate fails
solidworks wrapper calls helper when gate passes
nx wrapper calls helper when gate passes
wrapper metrics include native_rebuild_allowed=False
wrapper warnings include reference geometry disclaimer
```

## 17.6 Skills

```text
tests/generative_cad/test_gcad_v04_skills.py
```

Must cover:

```text
generative route requires selected_dialects
unsupported route requires unsupported_capabilities
deterministic primitive route rejects selected_dialects
duplicate selected dialect rejected
level2 prompt does not mention selected_bases
level2 prompt does not mention feature_graph
level2 prompt does not suggest unsupported_capabilities inside RawGcadDocument
repair prompt contains RepairPatchV2 output schema
```

## 17.7 Repair

```text
tests/generative_cad/test_gcad_v04_repair_patch.py
```

Must cover:

```text
forbidden safety path rejected
forbidden selected_dialects path rejected
forbidden node op path rejected
allowed node params path accepted
allowed component root_node path accepted
apply patch updates only target param
repeat patch hash stops governor
same stage + same error signature stops governor
earlier stage rank stops governor
equal stage with different error allowed
```

## 17.8 Dialect semantics and preflight

```text
tests/generative_cad/test_gcad_v04_dialect_semantics_preflight.py
```

Must cover:

```text
axisymmetric requires exactly one revolve_profile
axisymmetric non-base op requires input
axisymmetric root_node outputs body solid
axisymmetric hole PCD outside profile fails preflight
axisymmetric center bore too large fails preflight
sketch_extrude requires exactly one extrude_rectangle
sketch_extrude pocket larger than base fails
sketch_extrude hole too large fails
composition boolean_union requires exactly 2 inputs
composition rotate zero axis fails
composition pattern count over limit fails
```

## 17.9 Primitive isolation regression

```text
tests/generative_cad/test_gcad_v04_primitive_isolation.py
```

Must cover:

```text
generative dialects not in PRIMITIVE_COMPILERS
generative dialects not in PRIMITIVE_REGISTRY
CADPartSpec rejects generative fields
engineering_build_cad_model does not accept RawGcadDocument
generative tools do not register primitive builders
```

---

# 18. High-Quality Prompt Assets

Use these prompt constants after Phase 9.

## 18.1 Level-1 Routing Prompt

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

## 18.2 Level-2 Authoring Prompt

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

## 18.3 Repair Prompt

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

# 19. Final Acceptance Criteria

The implementation is complete only when all statements below are true:

```text
1. validation.pipeline has no optional canonical validators.
2. validate_and_canonicalize success returns stage="complete".
3. validation bundle preserves raw, canonicalize, dialect_semantics, and geometry_preflight reports.
4. builder writes full validation proof into metadata.
5. metadata validator rejects empty validation when require_validation_ok=True.
6. import gate rejects empty geometry_preflight.
7. import gate compares contract hashes against current registry without requiring canonical input.
8. runner records runtime_postconditions.
9. builder revalidates metadata after inspection with require_validation_ok=True.
10. production builder rejects legacy GenerativeCADSpec objects.
11. tool layer exposes generative_cad_import_artifact_to_solidworks.
12. tool layer exposes generative_cad_import_artifact_to_nx.
13. SW/NX generative wrappers call import gate before native import.
14. SW/NX generative wrappers never rebuild native feature trees.
15. DialectSelectionPlan enforces route invariants in schema.
16. RepairPatchV2 validates forbidden paths.
17. RepairPatchV2 can apply allowed node param patches.
18. Legacy v0.1 modules are not imported by production modules.
19. Primitive path tests still pass.
20. No new dialect/op was added during this hardening work.
```

---

# 20. Prohibited Shortcuts

Claude Code must not take these shortcuts:

```text
Do not silence tests by weakening assertions.
Do not make metadata validator permissive to pass tests.
Do not treat missing validation reports as ok.
Do not leave geometry_preflight as {}.
Do not mark runtime_postconditions as skipped in production build.
Do not compare contract hash by checking only "sha256:" prefix.
Do not call SolidWorks/NX generic STEP import from generative flow without import gate.
Do not keep legacy automatic adapter in production builder.
Do not add new dialects before hard gates are complete.
Do not make prompt-only rules without schema validators.
Do not accept unsupported_capabilities inside RawGcadDocument.
```

---

# 21. Definition of Done

Run:

```bash
pytest integrations/engineering_tools/tests/generative_cad
pytest integrations/engineering_tools/tests/test_generative_no_main_chain_pollution.py
pytest integrations/engineering_tools/tests/test_generative_repair_governor.py
```

If old legacy repair tests conflict with v0.4 policy, move them to explicit legacy tests and add new v0.4 repair tests.

Definition of done:

```text
All v0.4 tests pass.
All previous primitive-isolation tests pass.
No production module imports legacy GenerativeCADSpec.
No production builder accepts v0.1 spec silently.
No metadata without validation proof can pass native import gate.
No native CAD generative import can bypass metadata gate.
```

---

# 22. Final Architecture Statement

After this implementation, the correct architecture is:

```text
Deterministic Primitive Path:
  User NL
    → CADPartSpec
    → deterministic primitive compiler
    → CadQuery deterministic kernel
    → STEP + primitive metadata
    → optional SW/NX STEP import

Generative CAD Path:
  User NL
    → Level-1 routing skill
    → DialectSelectionPlan
    → Level-2 dialect authoring context
    → RawGcadDocument
    → fail-closed raw validation
    → CanonicalGcadDocument
    → fail-closed dialect semantics
    → fail-closed geometry preflight
    → fixed canonical runner
    → BaseDialect / OperationSpec handlers
    → runtime postconditions
    → STEP export
    → strict STEP inspection
    → generative_metadata_v2.1 with validation proof
    → CanonicalStepArtifact
    → optional validated SW/NX STEP import
```

The two paths meet only at:

```text
validated STEP artifact + validated metadata
```

They never meet at:

```text
CADPartSpec
Primitive registry
Primitive compiler
geometry_primitives
native SolidWorks feature tree
native NXOpen feature tree
```

This is the v0.4 hard-gate architecture.
