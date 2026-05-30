# SeekFlow Generative CAD v1.0 Release-Blocker Final Hardening Spec

目标仓库：`WYZAAACCC/seekflow-engineering`
目标范围：`integrations/engineering_tools`
目标子系统：`seekflow_engineering_tools/generative_cad`
执行对象：Claude Code
目标版本：Generative CAD v1.0 release-candidate hard-gate

---

## 0. 执行摘要

当前 Generative CAD 架构已经非常接近正确形态：

```text
LLM
  → DialectSelectionPlan
  → RawGcadDocument
  → single-pass validation pipeline
  → CanonicalGcadDocument + ValidationBundle
  → fixed canonical runner
  → runtime postconditions
  → STEP export
  → builder strict inspection
  → generative_metadata_v2.1 proof
  → CanonicalStepArtifact
  → optional SW/NX import gate
```

但是 release 仍被几个一致性问题阻断：

```text
P0-1: build_generative_metadata(validation=partial_dict) 不会补齐 missing validation stages。
P0-2: run_canonical_gcad 会原地修改 validation_seed。
P0-3: run_canonical_gcad 返回的 artifact.validation 可能与 metadata.validation 不一致。
P0-4: builder artifact/metadata consistency check 仍需覆盖 selected_dialects、paths、native flags。
P1-1: import gate 成功路径缺内部 invariant。
P1-2: repair prompt path 示例仍可能使用 /nodes//params/ 这种无效格式。
P1-3: v1.0 release-blocker 行为测试不足。
```

本次任务只允许修 hard-gate、一致性、metadata proof、测试与 prompt。
**不得新增 dialect。不得新增 operation。不得修改 deterministic primitive path。**

---

# 1. 正确目标架构

## 1.1 Generative CAD 正确链路

最终系统必须满足：

```text
User natural language
  ↓
Level-1 routing skill
  ↓
DialectSelectionPlan JSON
  ↓
System loads selected dialect contracts and usage skills
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
ValidationBundle:
    core_validation
    dialect_semantics
    geometry_preflight
  ↓
Fixed canonical runner:
    BaseDialect.run_component
    OperationSpec.handler
    RuntimeObjectStore typed handles
  ↓
Runtime postconditions:
    final handle exists
    final object exists
    final handle type is solid
    component root outputs are bound
  ↓
STEP export
  ↓
Builder strict STEP inspection
  ↓
generative_metadata_v2.1:
    core_validation.ok == true
    dialect_semantics.ok == true
    geometry_preflight.ok == true
    runtime_postconditions.ok == true
    inspection_validation.ok == true
  ↓
CanonicalStepArtifact
  ↓
Optional native import:
    generative_cad_import_artifact_to_solidworks
    generative_cad_import_artifact_to_nx
```

## 1.2 Deterministic 与 Generative 唯一合流点

允许合流：

```text
validated STEP + validated metadata
```

禁止合流：

```text
CADPartSpec
PRIMITIVE_REGISTRY
PRIMITIVE_COMPILERS
geometry_primitives
SolidWorks feature-tree authoring
NXOpen feature-tree authoring
LLM-generated CadQuery
LLM-generated Python CAD script
```

## 1.3 Direct runner 与 builder 语义区分

必须明确：

```text
run_gcad_core:
  Raw runtime entrypoint.
  It validates raw input and can write metadata with core/dialect/preflight/runtime stages.
  It does not perform STEP inspection unless explicitly run through builder.

run_canonical_gcad:
  Pre-validated canonical runtime entrypoint.
  Without validation_seed, its metadata is runner-local and not importable.
  With validation_seed, it can carry core/dialect/preflight proof, but still lacks inspection unless builder adds it.

build_generative_cad_model:
  Production orchestrator.
  It validates raw, runs canonical harness, inspects STEP, rewrites metadata with full proof, validates final metadata with require_validation_ok=True, and returns native-importable artifact.

SW/NX wrappers:
  Native import wrappers.
  They only accept artifacts whose metadata passes import gate.
```

---

# 2. 不可违反的硬约束

Claude Code 必须遵守：

```text
1. Do not modify deterministic primitive route semantics.
2. Do not register generative dialects as primitives.
3. Do not add generative fields to CADPartSpec.
4. Do not let LLM output CAD code, Python, CadQuery, SolidWorks COM, NXOpen, APDL, shell commands, imports, exports, subprocess calls, or file paths.
5. Do not let RawGcadDocument directly enter runtime handlers.
6. Do not allow metadata without all REQUIRED_VALIDATION_STAGES to pass structural metadata validation.
7. Do not allow native import unless require_validation_ok=True passes.
8. Do not treat direct canonical runner metadata as builder-final metadata unless it includes full validation proof and inspection_validation.ok == true.
9. Do not weaken safety flags.
10. Do not allow native_rebuild_allowed=True.
11. Do not make Pydantic models permissive by changing extra="forbid" to extra="allow".
12. Do not add new dialects or operations in this hardening pass.
13. Do not delete tests to make CI pass.
```

---

# 3. Phase 1 — Metadata Proof Normalization

## 3.1 File

```text
generative_cad/pipeline/metadata.py
```

## 3.2 Problem

Current behavior:

```python
if validation is None:
    validation = {
        "core_validation": ...,
        "dialect_semantics": ...,
        "geometry_preflight": ...,
        "runtime_postconditions": ...,
        "inspection_validation": ...,
    }
```

This only fills defaults when `validation is None`.

But runner can pass partial validation such as:

```python
{
    "runtime_postconditions": {
        "ok": True,
        "stage": "runtime_postconditions",
        "issues": []
    }
}
```

In this case, missing required sections are not filled.
Then `validate_generative_metadata_v2(... require_validation_ok=False)` still fails because it requires every required validation stage to exist as a dict.

This can break builder before builder rewrites final full validation proof.

## 3.3 Required implementation

Add these helpers to `metadata.py`:

```python
def _missing_stage(stage: str) -> dict:
    return {
        "ok": False,
        "stage": stage,
        "issues": [
            {
                "code": f"missing_{stage}_report",
                "message": f"No {stage} report was provided.",
                "severity": "error",
            }
        ],
    }


def default_validation_proof() -> dict:
    return {stage: _missing_stage(stage) for stage in REQUIRED_VALIDATION_STAGES}


def normalize_validation_proof(validation: dict | None) -> dict:
    normalized = default_validation_proof()

    if not isinstance(validation, dict):
        return normalized

    for stage in REQUIRED_VALIDATION_STAGES:
        value = validation.get(stage)
        if isinstance(value, dict):
            normalized[stage] = value

    # Preserve extra diagnostic sections without replacing required hard-gate stages.
    for key, value in validation.items():
        if key not in normalized:
            normalized[key] = value

    return normalized
```

Then change `build_generative_metadata()` to unconditionally normalize:

```python
validation = normalize_validation_proof(validation)
```

This must replace the old `if validation is None:` block.

## 3.4 Required behavior

This call:

```python
metadata = build_generative_metadata(
    canonical=canonical,
    ctx=ctx,
    validation={
        "runtime_postconditions": {
            "ok": True,
            "stage": "runtime_postconditions",
            "issues": [],
        }
    },
)
```

must produce:

```python
metadata["validation"]["core_validation"]["ok"] is False
metadata["validation"]["dialect_semantics"]["ok"] is False
metadata["validation"]["geometry_preflight"]["ok"] is False
metadata["validation"]["runtime_postconditions"]["ok"] is True
metadata["validation"]["inspection_validation"]["ok"] is False
```

Soft validation must pass:

```python
validate_generative_metadata_v2(
    metadata,
    canonical=canonical,
    registry_check=True,
    require_validation_ok=False,
)["ok"] is True
```

Hard validation must fail:

```python
validate_generative_metadata_v2(
    metadata,
    canonical=canonical,
    registry_check=True,
    require_validation_ok=True,
)["ok"] is False
```

## 3.5 Tests

Create:

```text
tests/generative_cad/test_gcad_v10_metadata_normalization.py
```

Test cases:

```python
def test_build_metadata_normalizes_partial_validation(canonical, runtime_ctx):
    metadata = build_generative_metadata(
        canonical=canonical,
        ctx=runtime_ctx,
        validation={
            "runtime_postconditions": {
                "ok": True,
                "stage": "runtime_postconditions",
                "issues": [],
            }
        },
    )

    val = metadata["validation"]
    assert val["core_validation"]["ok"] is False
    assert val["dialect_semantics"]["ok"] is False
    assert val["geometry_preflight"]["ok"] is False
    assert val["runtime_postconditions"]["ok"] is True
    assert val["inspection_validation"]["ok"] is False


def test_partial_validation_passes_soft_metadata_validation(canonical, runtime_ctx):
    metadata = build_generative_metadata(
        canonical=canonical,
        ctx=runtime_ctx,
        validation={
            "runtime_postconditions": {
                "ok": True,
                "stage": "runtime_postconditions",
                "issues": [],
            }
        },
    )

    result = validate_generative_metadata_v2(
        metadata,
        canonical=canonical,
        registry_check=True,
        require_validation_ok=False,
    )

    assert result["ok"] is True


def test_partial_validation_fails_hard_metadata_validation(canonical, runtime_ctx):
    metadata = build_generative_metadata(
        canonical=canonical,
        ctx=runtime_ctx,
        validation={
            "runtime_postconditions": {
                "ok": True,
                "stage": "runtime_postconditions",
                "issues": [],
            }
        },
    )

    result = validate_generative_metadata_v2(
        metadata,
        canonical=canonical,
        registry_check=True,
        require_validation_ok=True,
    )

    assert not result["ok"]
    assert any(i["code"] == "core_validation_not_ok" for i in result["issues"])
    assert any(i["code"] == "inspection_validation_not_ok" for i in result["issues"])
```

---

# 4. Phase 2 — Runner Validation Seed Immutability

## 4.1 File

```text
generative_cad/pipeline/run.py
```

## 4.2 Problem

Current pattern:

```python
validation = validation_seed or {}
validation["runtime_postconditions"] = runtime_pc
```

This mutates caller-provided `validation_seed`.

Validation proof must be treated as an immutable snapshot.

## 4.3 Required implementation

Add import:

```python
import copy
```

Change:

```python
validation = validation_seed or {}
validation["runtime_postconditions"] = runtime_pc
```

to:

```python
validation = copy.deepcopy(validation_seed) if validation_seed is not None else {}
validation["runtime_postconditions"] = runtime_pc
```

## 4.4 Tests

Add to:

```text
tests/generative_cad/test_gcad_v10_run_metadata_consistency.py
```

Test:

```python
def test_run_canonical_gcad_does_not_mutate_validation_seed(canonical, tmp_path, monkeypatch):
    seed = {
        "core_validation": {"ok": True, "stage": "core_validation", "issues": []},
        "dialect_semantics": {"ok": True, "stage": "dialect_semantics", "issues": []},
        "geometry_preflight": {"ok": True, "stage": "geometry_preflight", "issues": []},
        "inspection_validation": {"ok": False, "stage": "inspection_validation", "issues": []},
    }
    original = copy.deepcopy(seed)

    # monkeypatch _run_components, _run_composition_or_select_final, _export_final_solid
    # to avoid heavy CadQuery execution

    result = run_canonical_gcad(
        canonical,
        out_step=tmp_path / "part.step",
        metadata_path=tmp_path / "part.metadata.json",
        validation_seed=seed,
    )

    assert seed == original
```

---

# 5. Phase 3 — Runner Artifact / Metadata Consistency

## 5.1 File

```text
generative_cad/pipeline/run.py
```

## 5.2 Problem

`run_canonical_gcad()` builds metadata with validation proof, but builds artifact without passing that validation proof:

```python
artifact = build_canonical_step_artifact(
    canonical=canonical,
    step_path=out_step,
    metadata_path=metadata_path,
    ctx=ctx,
)
```

This can produce:

```python
result.artifact["validation"] != result.metadata["validation"]
```

## 5.3 Required implementation

Change artifact construction:

```python
artifact = build_canonical_step_artifact(
    canonical=canonical,
    step_path=out_step,
    metadata_path=metadata_path,
    validation=metadata["validation"],
    ctx=ctx,
)
```

Then add runtime consistency check:

```python
if artifact.get("validation") != metadata.get("validation"):
    return GcadRunResult(
        ok=False,
        error="runner artifact/metadata validation mismatch",
        warnings=ctx.warnings,
        degraded_features=ctx.degraded_features,
        operation_metrics=ctx.operation_metrics,
    )
```

## 5.4 Required behavior

For raw runner path:

```python
result = run_gcad_core(raw, out_step, metadata_path)
```

must satisfy:

```python
result.artifact["validation"] == result.metadata["validation"]
```

and because builder inspection has not run:

```python
result.metadata["validation"]["inspection_validation"]["ok"] is False
```

## 5.5 Tests

Add to:

```text
tests/generative_cad/test_gcad_v10_run_metadata_consistency.py
```

Test:

```python
def test_run_artifact_validation_matches_metadata(valid_raw_doc, tmp_path):
    result = run_gcad_core(
        valid_raw_doc,
        out_step=tmp_path / "part.step",
        metadata_path=tmp_path / "part.metadata.json",
    )

    assert result.ok
    assert result.artifact["validation"] == result.metadata["validation"]


def test_run_raw_path_is_not_importable_without_inspection(valid_raw_doc, tmp_path):
    result = run_gcad_core(
        valid_raw_doc,
        out_step=tmp_path / "part.step",
        metadata_path=tmp_path / "part.metadata.json",
    )

    assert result.ok

    hard = validate_generative_metadata_v2(
        result.metadata,
        registry_check=True,
        require_validation_ok=True,
    )

    assert not hard["ok"]
    assert any(i["code"] == "inspection_validation_not_ok" for i in hard["issues"])
```

If full CAD execution is too heavy, monkeypatch runtime helpers.

---

# 6. Phase 4 — Builder Initial Metadata Soft Validation

## 6.1 File

```text
generative_cad/builder.py
```

## 6.2 Goal

After Phase 1 normalization, builder’s initial runner metadata validation should pass soft mode even when runner metadata is partial.

This is essential because builder must be allowed to:

```text
1. load runner-local metadata
2. structurally validate it
3. inspect STEP
4. merge full ValidationBundle + inspection proof
5. validate final metadata with require_validation_ok=True
```

## 6.3 Test

Create:

```text
tests/generative_cad/test_gcad_v10_builder_initial_metadata.py
```

Test:

```python
def test_runner_partial_metadata_passes_builder_soft_validation(canonical, runtime_ctx):
    metadata = build_generative_metadata(
        canonical=canonical,
        ctx=runtime_ctx,
        validation={
            "runtime_postconditions": {
                "ok": True,
                "stage": "runtime_postconditions",
                "issues": [],
            }
        },
    )

    result = validate_generative_metadata_v2(
        metadata,
        canonical=canonical,
        registry_check=True,
        require_validation_ok=False,
    )

    assert result["ok"] is True
```

This test is a direct guard for the current release-blocker.

---

# 7. Phase 5 — Builder Artifact / Metadata Full Consistency

## 7.1 File

```text
generative_cad/builder.py
```

## 7.2 Current State

Builder already checks some consistency, but release-grade consistency must cover all critical fields.

## 7.3 Required checks

After constructing final artifact and before returning success:

```python
artifact = build_canonical_step_artifact(
    canonical=canonical,
    step_path=step_path,
    metadata_path=meta_path,
    graph_path=str(graph_path),
    runner_script_path=str(script_path),
    validation=validation_meta,
    inspection=insp_val,
)
```

Add checks:

```python
metadata_gm = metadata["generative_metadata"]

if artifact.get("canonical_graph_hash") != metadata_gm.get("canonical_graph_hash"):
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error="Artifact/metadata canonical_graph_hash mismatch.",
        files_created=files_created,
    ).model_dump()

if artifact.get("selected_dialects") != metadata_gm.get("selected_dialects"):
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error="Artifact/metadata selected_dialects mismatch.",
        files_created=files_created,
    ).model_dump()

if artifact.get("validation") != metadata.get("validation"):
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error="Artifact/metadata validation proof mismatch.",
        files_created=files_created,
    ).model_dump()

if artifact.get("step_path") != str(step_path):
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error="Artifact/metadata step_path mismatch.",
        files_created=files_created,
    ).model_dump()

if artifact.get("metadata_path") != str(meta_path):
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error="Artifact/metadata metadata_path mismatch.",
        files_created=files_created,
    ).model_dump()

if artifact.get("native_rebuild_allowed") is not False:
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error="Artifact incorrectly allows native rebuild.",
        files_created=files_created,
    ).model_dump()

if artifact.get("step_import_allowed") is not True:
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error="Artifact incorrectly disallows STEP import.",
        files_created=files_created,
    ).model_dump()

metrics["artifact"] = artifact
```

## 7.4 Tests

Create:

```text
tests/generative_cad/test_gcad_v10_builder_artifact_consistency.py
```

Test:

```python
def test_builder_artifact_matches_final_metadata(valid_build_result):
    artifact = valid_build_result["metrics"]["artifact"]
    metadata = json.loads(Path(valid_build_result["metrics"]["metadata_path"]).read_text())

    assert artifact["canonical_graph_hash"] == metadata["generative_metadata"]["canonical_graph_hash"]
    assert artifact["selected_dialects"] == metadata["generative_metadata"]["selected_dialects"]
    assert artifact["validation"] == metadata["validation"]
    assert artifact["step_path"] == valid_build_result["metrics"]["step_path"]
    assert artifact["metadata_path"] == valid_build_result["metrics"]["metadata_path"]
    assert artifact["native_rebuild_allowed"] is False
    assert artifact["step_import_allowed"] is True
```

If `metrics["step_path"]` does not exist, add it to builder metrics.

---

# 8. Phase 6 — Import Gate Success Invariant

## 8.1 File

```text
generative_cad/pipeline/import_artifact.py
```

## 8.2 Problem

Gate is mostly correct, but release-grade gate should assert internal invariants before returning success.

## 8.3 Required implementation

Before success return:

```python
required_true = [
    "step_exists",
    "metadata_exists",
    "metadata_valid",
    "safety_valid",
    "contract_hash_valid",
    "core_validation_ok",
    "dialect_semantics_ok",
    "geometry_preflight_ok",
    "runtime_postconditions_ok",
    "inspection_ok",
    "step_import_allowed",
]

if not all(gate.get(k) is True for k in required_true):
    issues.append({
        "code": "gate_internal_invariant_failed",
        "message": "Import gate reached success path with incomplete true flags.",
    })
    gate["step_import_allowed"] = False
    return {
        "ok": False,
        "issues": issues,
        "metadata": metadata,
        "gate": gate,
    }

if gate.get("native_rebuild_allowed") is not False:
    issues.append({
        "code": "gate_internal_invariant_failed",
        "message": "native_rebuild_allowed must remain false.",
    })
    gate["step_import_allowed"] = False
    return {
        "ok": False,
        "issues": issues,
        "metadata": metadata,
        "gate": gate,
    }
```

Only then:

```python
return {"ok": True, "issues": [], "metadata": metadata, "gate": gate}
```

## 8.4 Tests

Create:

```text
tests/generative_cad/test_gcad_v10_import_gate_release.py
```

Tests:

```python
def test_import_gate_success_has_all_required_true_flags(step_file, valid_import_metadata):
    result = validate_generative_step_artifact_for_native_import(
        step_file,
        valid_import_metadata,
    )

    assert result["ok"]

    for key in [
        "step_exists",
        "metadata_exists",
        "metadata_valid",
        "safety_valid",
        "contract_hash_valid",
        "core_validation_ok",
        "dialect_semantics_ok",
        "geometry_preflight_ok",
        "runtime_postconditions_ok",
        "inspection_ok",
        "step_import_allowed",
    ]:
        assert result["gate"][key] is True

    assert result["gate"]["native_rebuild_allowed"] is False


def test_import_gate_failed_metadata_never_allows_step_import(step_file, bad_metadata):
    result = validate_generative_step_artifact_for_native_import(
        step_file,
        bad_metadata,
    )

    assert not result["ok"]
    assert result["gate"]["step_import_allowed"] is False
```

---

# 9. Phase 7 — Repair Prompt Path Precision

## 9.1 File

```text
generative_cad/skills/prompts.py
```

## 9.2 Problem

Repair prompt currently uses ambiguous path examples:

```text
/nodes//params/
/nodes//inputs
/components//root_node
```

These are not valid RepairPatchV2 paths.

## 9.3 Required replacement

Update repair prompt rules 15–17 to:

```text
15. Prefer changing only /nodes/<node_id>/params/<field>.
16. You may change /nodes/<node_id>/inputs, /nodes/<node_id>/outputs, /nodes/<node_id>/required, /nodes/<node_id>/degradation_policy, or /components/<component_id>/root_node only when the validation error explicitly requires that exact structural repair.
17. Use old_value when available. If old_value no longer matches, the patch must not apply.
```

Also ensure prompt contains:

```text
Do not modify /schema_version.
Do not modify /selected_dialects.
Do not modify /safety.
Do not modify /constraints/require_step_file.
Do not modify /constraints/require_metadata_sidecar.
Do not modify /constraints/require_closed_solid.
Do not modify /nodes/<node_id>/dialect.
Do not modify /nodes/<node_id>/op.
Do not modify /nodes/<node_id>/op_version.
Do not modify /components/<component_id>/owner_dialect.
```

## 9.4 Tests

Create:

```text
tests/generative_cad/test_gcad_v10_prompt_paths.py
```

Test:

```python
def test_repair_prompt_uses_valid_placeholder_paths():
    assert "/nodes/<node_id>/params/<field>" in REPAIR_PATCH_SYSTEM_PROMPT_V2
    assert "/components/<component_id>/root_node" in REPAIR_PATCH_SYSTEM_PROMPT_V2
    assert "/nodes//params/" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
    assert "/nodes//inputs" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
    assert "/components//root_node" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
```

---

# 10. Phase 8 — Native Wrapper Functional Tests

## 10.1 Files

```text
generative_cad/tools.py
generative_cad/native_importers.py
```

## 10.2 Required behavior

Native wrappers must satisfy:

```text
1. If import gate fails, native_importers.import_step_to_solidworks/import_step_to_nx must not be called.
2. If import gate passes, native helper must be called exactly once.
3. Native helper failure must propagate as tool ok=False.
4. Tool metrics must include:
   source_route
   strategy
   native_rebuild_allowed=False
   step_import_allowed=True
   import_gate
   canonical_graph_hash
   selected_dialects
```

## 10.3 Tests

Create:

```text
tests/generative_cad/test_gcad_v10_native_wrapper_behavior.py
```

Tests:

```python
def test_solidworks_wrapper_does_not_call_native_import_when_gate_fails(
    monkeypatch,
    config,
    step_file,
    bad_metadata,
):
    from seekflow_engineering_tools.generative_cad import native_importers

    called = {"sw": False}

    def fake_import(*args, **kwargs):
        called["sw"] = True
        return {"ok": True, "files_created": ["x.sldprt"]}

    monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_import)

    tool = get_tool(
        build_generative_cad_tools(config),
        "generative_cad_import_artifact_to_solidworks",
    )

    result = tool(
        step_path=str(step_file),
        metadata_path=str(bad_metadata),
        out_sldprt="out.sldprt",
    )

    assert not result["ok"]
    assert called["sw"] is False


def test_solidworks_wrapper_calls_native_import_when_gate_passes(
    monkeypatch,
    config,
    step_file,
    valid_import_metadata,
):
    from seekflow_engineering_tools.generative_cad import native_importers

    called = {"sw": 0}

    def fake_import(config, step, out):
        called["sw"] += 1
        return {"ok": True, "files_created": [str(out)]}

    monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_import)

    tool = get_tool(
        build_generative_cad_tools(config),
        "generative_cad_import_artifact_to_solidworks",
    )

    result = tool(
        step_path=str(step_file),
        metadata_path=str(valid_import_metadata),
        out_sldprt="out.sldprt",
    )

    assert result["ok"]
    assert called["sw"] == 1
    assert result["metrics"]["native_rebuild_allowed"] is False
    assert result["metrics"]["step_import_allowed"] is True
```

Repeat equivalent NX tests.

---

# 11. Phase 9 — Legacy Isolation Release Gate

## 11.1 Problem

Legacy root modules still exist. They are acceptable only if production modules do not import legacy schema.

## 11.2 Test

Create or update:

```text
tests/generative_cad/test_gcad_v10_legacy_isolation.py
```

Use precise import-pattern checks:

```python
def test_production_modules_do_not_import_legacy_schema():
    import inspect
    import importlib

    modules = [
        "seekflow_engineering_tools.generative_cad.builder",
        "seekflow_engineering_tools.generative_cad.pipeline.run",
        "seekflow_engineering_tools.generative_cad.pipeline.metadata",
        "seekflow_engineering_tools.generative_cad.pipeline.import_artifact",
        "seekflow_engineering_tools.generative_cad.validation.pipeline",
        "seekflow_engineering_tools.generative_cad.tools",
        "seekflow_engineering_tools.generative_cad.skills.prompts",
    ]

    forbidden_import_patterns = [
        "from seekflow_engineering_tools.generative_cad.ir import",
        "from seekflow_engineering_tools.generative_cad.registry import",
        "from seekflow_engineering_tools.generative_cad.base import",
        "GenerativeCADSpec(",
        "SelectedBase(",
        "FeatureGraph(",
        "BASE_REGISTRY",
        "selected_bases=",
        "feature_graph=",
    ]

    for module_name in modules:
        src = inspect.getsource(importlib.import_module(module_name))
        for pattern in forbidden_import_patterns:
            assert pattern not in src, f"{module_name} contains legacy pattern {pattern!r}"
```

Do not fail simply because an error message contains the phrase `"Legacy GenerativeCADSpec"`. Check import patterns and constructor usage only.

---

# 12. Final Prompt Assets

## 12.1 Level-1 Routing Prompt

Use exactly:

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
16. Do not use deprecated terminology: selected_bases, base_id, feature_graph, GenerativeCADSpec.
"""
```

## 12.2 Level-2 Authoring Prompt

Use exactly:

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
25. Do not use deprecated fields: selected_bases, feature_graph, base_id, system_validation_contract, ir_version, GenerativeCADSpec.
26. Use only selected_dialects, components, nodes, constraints, safety, and schema-defined fields.
27. If the request cannot be expressed with the selected contracts, do not invent operations or fallback fields. The request must be returned to Level-1 routing as unsupported.
28. Do not set trust_level above reference_geometry.
29. Do not claim manufacturing readiness, certification, airworthiness, installation readiness, structural validation, life prediction, or production readiness.
30. Never include unsupported_capabilities inside RawGcadDocument; unsupported_capabilities belongs only to DialectSelectionPlan.
"""
```

## 12.3 Repair Prompt

Use exactly:

```python
REPAIR_PATCH_SYSTEM_PROMPT_V2 = """
You are a local G-CAD IR repair patch author.

You may only repair the provided RawGcadDocument by returning a local RepairPatchV2 JSON.

Hard rules:
1. Do not rewrite the entire graph.
2. Do not modify /schema_version.
3. Do not modify /selected_dialects.
4. Do not modify /safety.
5. Do not modify /constraints/require_step_file.
6. Do not modify /constraints/require_metadata_sidecar.
7. Do not modify /constraints/require_closed_solid.
8. Do not modify /nodes/<node_id>/dialect.
9. Do not modify /nodes/<node_id>/op.
10. Do not modify /nodes/<node_id>/op_version.
11. Do not modify /components/<component_id>/owner_dialect.
12. Do not invent dialects.
13. Do not invent operations.
14. Do not weaken validation.
15. Prefer changing only /nodes/<node_id>/params/<field>.
16. You may change /nodes/<node_id>/inputs, /nodes/<node_id>/outputs, /nodes/<node_id>/required, /nodes/<node_id>/degradation_policy, or /components/<component_id>/root_node only when the validation error explicitly requires that exact structural repair.
17. Use old_value when available. If old_value no longer matches, the patch must not apply.
18. If the same error signature repeated, output {"give_up": true, "reason": "..."}.
19. Output JSON only.
20. Output must match RepairPatchV2 schema.
21. Do not include markdown, prose, comments, or trailing commas.
"""
```

---

# 13. Required Tests Matrix

Add or update:

```text
tests/generative_cad/test_gcad_v10_metadata_normalization.py
tests/generative_cad/test_gcad_v10_run_metadata_consistency.py
tests/generative_cad/test_gcad_v10_builder_initial_metadata.py
tests/generative_cad/test_gcad_v10_builder_artifact_consistency.py
tests/generative_cad/test_gcad_v10_import_gate_release.py
tests/generative_cad/test_gcad_v10_prompt_paths.py
tests/generative_cad/test_gcad_v10_native_wrapper_behavior.py
tests/generative_cad/test_gcad_v10_legacy_isolation.py
```

Run:

```bash
pytest integrations/engineering_tools/tests/generative_cad
pytest integrations/engineering_tools/tests/test_generative_no_main_chain_pollution.py
```

If old v0.1 repair governor tests exist, keep them as legacy tests only. They must not constrain production v1.0 repair behavior.

---

# 14. Acceptance Criteria

Implementation is complete only when all are true:

```text
1. build_generative_metadata normalizes partial validation dicts.
2. build_generative_metadata always emits all REQUIRED_VALIDATION_STAGES.
3. Soft metadata validation accepts normalized partial proof.
4. Hard metadata validation rejects normalized partial proof with missing/not-ok stages.
5. Builder initial runner metadata validation no longer fails due to missing validation stages.
6. run_canonical_gcad does not mutate validation_seed.
7. run_canonical_gcad artifact.validation equals metadata.validation.
8. run_gcad_core direct output is not native-importable without inspection_validation.ok == true.
9. Builder final metadata passes require_validation_ok=True.
10. Builder artifact matches final metadata on canonical hash, selected_dialects, validation, paths, native flags.
11. Import gate success path enforces all required true flags.
12. Import gate failure always has step_import_allowed == False.
13. SW/NX wrappers do not call native helper when gate fails.
14. SW/NX wrappers call native helper exactly once when gate passes.
15. Repair prompt uses valid placeholder paths.
16. RepairPatchV2 old_value, give_up, forbidden paths, missing target behavior remain tested.
17. Production modules do not import legacy schema.
18. Primitive pollution tests pass.
19. No new dialects or operations were added.
```

---

# 15. Prohibited Shortcuts

Claude Code must not:

```text
1. Make validate_generative_metadata_v2 permissive.
2. Allow missing REQUIRED_VALIDATION_STAGES.
3. Mark inspection_validation ok without real inspection.
4. Treat runner-only metadata as native-importable.
5. Mutate validation_seed in place.
6. Return import gate ok=True when any required proof flag is false.
7. Keep ambiguous repair prompt paths like /nodes//params/.
8. Suppress old_value mismatch.
9. Add new dialects or operations.
10. Modify deterministic primitive semantics.
11. Change Pydantic extra="forbid" to extra="allow".
12. Delete tests to make CI pass.
```

---

# 16. Final Release Architecture Statement

After this hardening pass, the system must satisfy:

```text
LLM output is grammar, not CAD code.
RawGcadDocument is source text.
Validation pipeline is compiler front-end.
CanonicalGcadDocument is typed IR.
BaseDialect/OperationSpec are backend lowering rules.
RuntimeObjectStore is typed value storage.
Runtime postconditions are backend verification.
STEP is object code.
generative_metadata_v2.1 is provenance proof.
CanonicalStepArtifact is build manifest.
SW/NX wrappers are import gates, not native rebuilders.
```

The only valid native import path is:

```text
STEP file
+ metadata where all required validation stages are ok
+ import gate success
→ SolidWorks/NX STEP import
```

No geometry capability expansion is allowed until all release-blocker tests pass.
