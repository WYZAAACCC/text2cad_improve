# SeekFlow Generative CAD v0.9 Release-Blocker Hardening Spec

目标仓库：`WYZAAACCC/seekflow-engineering`
目标目录：`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad`
执行对象：Claude Code
目标：修复 v0.8 release-candidate 中剩余的 metadata proof normalization、runner artifact consistency、builder initial metadata validation、prompt path 精度与 functional regression tests 问题，使 Generative CAD 成为真正可运行、可测试、可扩展的 LLM-Skill-Base / Generative CAD-IR 编译链路。

---

# 0. 当前最新状态

当前实现已经具备以下正确基础：

```text
1. validation/pipeline.py 已经 fixed RAW_STAGES / CANONICAL_STAGES。
2. validation pipeline 已经 single-pass，不再 double-run validators。
3. ValidationReport 已支持 stages_run。
4. builder.py 已使用 validate_and_canonicalize_with_bundle。
5. builder.py 已拒绝 legacy GenerativeCADSpec。
6. builder.py 已对 graph_out/script_out 做 workspace guard。
7. run.py 已区分 raw entrypoint 和 pre-validated canonical entrypoint。
8. run.py 已支持 require_full_validation_seed。
9. runtime/postconditions.py 已检查 final handle、object_store、root output binding。
10. metadata.py 已支持 require_validation_ok。
11. import_artifact.py 已完整维护 gate flags。
12. tools.py 已通过 native_importers module 调用 SolidWorks/NX helpers。
13. repair/patch.py 已有 RepairPatchV2、old_value check、applied count、give_up。
14. skills/prompts.py 已更新为 release-candidate prompt。
15. skills/schemas.py 已有 DialectSelectionPlan route invariants。
```

当前剩余风险不是“大架构错误”，而是 release-blocker 级别的 proof normalization 与 direct runner consistency：

```text
P0-1: build_generative_metadata(validation=partial_dict) 不会补全 missing validation stages。
P0-2: builder canonical harness 会先生成 partial metadata，再做 initial metadata validation；如果 P0-1 不修，builder 可能在重写 full proof 之前失败。
P0-3: run_canonical_gcad 写 metadata 时 validation_seed 会被原地 mutate。
P0-4: run_canonical_gcad 返回的 artifact 没有显式传入 metadata["validation"]，可能导致 result.artifact.validation 与 result.metadata.validation 不一致。
P0-5: run_gcad_core raw path 没有 STEP inspection，所以直接 runner 产物不应被误认为 native-importable artifact；必须用 validation proof 明确表达 inspection_validation=False/missing。
P1-1: prompts 里 repair path 示例仍显示 /nodes//params/，可读性差，应该改成 /nodes/<node_id>/params/<field>。
P1-2: tests 中还有过多 inspect-source 风格断言，需要补 functional behavior tests。
P1-3: legacy 根目录文件仍存在，必须继续用 production import isolation tests 锁住。
```

---

# 1. Final Architecture

最终架构必须保持：

```text
User natural language
  ↓
Level-1 Domain Routing Skill
  ↓
DialectSelectionPlan JSON
  ↓
System loads Dialect Contracts + Level-2 Usage Skills
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
Fixed canonical runner
  ↓
Runtime:
    BaseDialect.run_component
    OperationSpec.handler
    RuntimeObjectStore typed handles
  ↓
Runtime postconditions
  ↓
STEP export
  ↓
Builder-only strict STEP inspection
  ↓
generative_metadata_v2.1 with full proof
  ↓
CanonicalStepArtifact
  ↓
Optional native import through gate:
    generative_cad_import_artifact_to_solidworks
    generative_cad_import_artifact_to_nx
```

Important distinction:

```text
run_gcad_core / run_canonical_gcad:
  Runtime entrypoints.
  May produce STEP + runtime metadata.
  Not necessarily native-importable unless inspection_validation.ok == true.

build_generative_cad_model:
  Production build orchestrator.
  Produces native-importable artifact only after final metadata validation with require_validation_ok=True.

SW/NX import wrappers:
  Accept only validated STEP + metadata.
  Must never rebuild native feature tree.
```

The only merge point with deterministic Primitive path is:

```text
validated STEP artifact + validated metadata
```

Forbidden merge points:

```text
CADPartSpec
Primitive registry
Primitive compiler
geometry_primitives
SolidWorks native feature-tree authoring
NXOpen feature-tree authoring
LLM-generated CadQuery code
```

---

# 2. Hard Constraints

Claude Code must not violate:

```text
1. Do not modify deterministic primitive path semantics.
2. Do not register generative dialects as primitives.
3. Do not add generative fields to CADPartSpec.
4. Do not let LLM output CadQuery, Python, SolidWorks COM, NXOpen, APDL, shell commands, imports, exports, subprocess, or file paths.
5. Do not let RawGcadDocument directly enter runtime handlers.
6. Do not allow metadata without all REQUIRED_VALIDATION_STAGES to pass even when require_validation_ok=False.
7. Do not allow native import unless require_validation_ok=True passes.
8. Do not treat direct canonical runner metadata as builder-final metadata unless it contains full validation proof including inspection_validation.ok=True.
9. Do not weaken safety flags.
10. Do not allow native_rebuild_allowed=True.
11. Do not add new dialects or operations in this hardening pass.
12. Do not remove tests to pass CI.
13. Do not change Pydantic extra="forbid" to extra="allow".
```

---

# 3. Phase 1 — Normalize Validation Proof in metadata.py

## File

```text
generative_cad/pipeline/metadata.py
```

## Problem

`build_generative_metadata()` currently fills missing validation only when `validation is None`.

But runner often passes a partial dict:

```python
validation = {"runtime_postconditions": runtime_pc}
```

or:

```python
validation = validation_seed
validation["runtime_postconditions"] = runtime_pc
```

If this dict lacks `core_validation`, `dialect_semantics`, `geometry_preflight`, or `inspection_validation`, `validate_generative_metadata_v2(... require_validation_ok=False)` still reports `missing_*` issues because it requires each stage to be a dict.

This can break builder before it has a chance to rewrite metadata with full proof.

## Required Implementation

Add these functions to `metadata.py`:

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
    if validation is None:
        return normalized

    if not isinstance(validation, dict):
        return normalized

    for stage in REQUIRED_VALIDATION_STAGES:
        value = validation.get(stage)
        if isinstance(value, dict):
            normalized[stage] = value

    # Preserve any extra non-required diagnostic sections, but do not let them
    # replace required hard-gate sections.
    for key, value in validation.items():
        if key not in normalized:
            normalized[key] = value

    return normalized
```

Then change `build_generative_metadata()`:

```python
validation = normalize_validation_proof(validation)
```

This must happen unconditionally, regardless of whether validation is None or partial.

## Required Behavior

After this change:

```python
build_generative_metadata(canonical, ctx, validation={"runtime_postconditions": {"ok": True}})
```

must produce:

```text
core_validation.ok == False
dialect_semantics.ok == False
geometry_preflight.ok == False
runtime_postconditions.ok == True
inspection_validation.ok == False
```

This metadata should pass structural metadata validation when `require_validation_ok=False`, but must fail when `require_validation_ok=True`.

## Acceptance Tests

Create:

```text
tests/generative_cad/test_gcad_v09_metadata_normalization.py
```

Tests:

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


def test_partial_validation_passes_structure_not_hard_gate(canonical, runtime_ctx):
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

    soft = validate_generative_metadata_v2(
        metadata,
        canonical=canonical,
        registry_check=True,
        require_validation_ok=False,
    )
    hard = validate_generative_metadata_v2(
        metadata,
        canonical=canonical,
        registry_check=True,
        require_validation_ok=True,
    )

    assert soft["ok"] is True
    assert hard["ok"] is False
    assert any(i["code"] == "core_validation_not_ok" for i in hard["issues"])
```

---

# 4. Phase 2 — Fix run.py Validation Mutation and Artifact Consistency

## File

```text
generative_cad/pipeline/run.py
```

## Problems

### Problem A — validation_seed mutation

Current pattern:

```python
validation = validation_seed or {}
validation["runtime_postconditions"] = runtime_pc
```

If caller passed `validation_seed`, this mutates the caller's dict.

### Problem B — returned artifact may not match metadata

Current runner builds metadata with validation proof, then calls:

```python
artifact = build_canonical_step_artifact(
    canonical=canonical,
    step_path=out_step,
    metadata_path=metadata_path,
    ctx=ctx,
)
```

`RuntimeContext` has no `validation` attribute. Therefore artifact may contain default fail-closed validation instead of the metadata validation proof.

This is not fatal for builder path because builder reconstructs artifact, but it is wrong for direct `run_gcad_core()` results.

## Required Implementation

Import:

```python
import copy
```

Change validation construction:

```python
validation = copy.deepcopy(validation_seed) if validation_seed is not None else {}
validation["runtime_postconditions"] = runtime_pc
```

After metadata is built, pass the same validation to artifact:

```python
metadata = build_generative_metadata(
    canonical=canonical,
    ctx=ctx,
    validation=validation,
)

artifact = build_canonical_step_artifact(
    canonical=canonical,
    step_path=out_step,
    metadata_path=metadata_path,
    validation=metadata["validation"],
    ctx=ctx,
)
```

Also ensure:

```python
assert artifact["validation"] == metadata["validation"]
```

Do not use Python assert in production code; if mismatch occurs, return `GcadRunResult(ok=False, error="runner artifact/metadata validation mismatch")`.

## Required Behavior

For raw entrypoint:

```python
run_gcad_core(raw, out_step, metadata_path)
```

result must satisfy:

```text
result.metadata["validation"]["core_validation"]["ok"] == True
result.metadata["validation"]["dialect_semantics"]["ok"] == True
result.metadata["validation"]["geometry_preflight"]["ok"] == True
result.metadata["validation"]["runtime_postconditions"]["ok"] == True
result.metadata["validation"]["inspection_validation"]["ok"] == False
result.artifact["validation"] == result.metadata["validation"]
```

Direct runner output is not native-importable until inspection_validation.ok becomes true.

## Acceptance Tests

Create:

```text
tests/generative_cad/test_gcad_v09_run_artifact_metadata_consistency.py
```

Tests:

```python
def test_run_metadata_does_not_mutate_validation_seed(canonical, tmp_path, monkeypatch):
    seed = {
        "core_validation": {"ok": True, "stage": "core_validation", "issues": []},
        "dialect_semantics": {"ok": True, "stage": "dialect_semantics", "issues": []},
        "geometry_preflight": {"ok": True, "stage": "geometry_preflight", "issues": []},
        "inspection_validation": {"ok": False, "stage": "inspection_validation", "issues": []},
    }
    original = copy.deepcopy(seed)

    # monkeypatch component execution/export as needed
    result = run_canonical_gcad(
        canonical,
        out_step=tmp_path / "part.step",
        metadata_path=tmp_path / "part.metadata.json",
        validation_seed=seed,
    )

    assert seed == original


def test_run_artifact_validation_matches_metadata(valid_raw_doc, tmp_path):
    result = run_gcad_core(
        valid_raw_doc,
        out_step=tmp_path / "part.step",
        metadata_path=tmp_path / "part.metadata.json",
    )

    assert result.ok
    assert result.artifact["validation"] == result.metadata["validation"]


def test_run_raw_path_not_importable_without_inspection(valid_raw_doc, tmp_path):
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

If CAD execution is too heavy for unit tests, monkeypatch `_run_components`, `_run_composition_or_select_final`, and `_export_final_solid`.

---

# 5. Phase 3 — Builder Initial Metadata Validation Must Pass Soft Mode

## File

```text
generative_cad/builder.py
```

## Current Flow

Builder runs canonical harness, loads runner metadata, then calls:

```python
validate_generative_metadata_v2(
    metadata,
    canonical=canonical,
    registry_check=True,
    require_validation_ok=False,
)
```

This is correct only if runner metadata contains all required validation sections as dicts, even when some are `ok=False`.

After Phase 1 normalization, this should work.

## Required Test

Create:

```text
tests/generative_cad/test_gcad_v09_builder_initial_metadata.py
```

Test using monkeypatch or a small synthetic metadata fixture:

```python
def test_builder_initial_metadata_soft_validation_accepts_normalized_partial_proof(canonical, runtime_ctx):
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

This test ensures builder can load runner-local metadata and then rewrite full proof.

---

# 6. Phase 4 — Builder Artifact/Metadata Consistency: Complete Checks

## File

```text
generative_cad/builder.py
```

## Current State

Builder already checks:

```text
artifact["canonical_graph_hash"] == metadata["generative_metadata"]["canonical_graph_hash"]
artifact["validation"] == metadata["validation"]
```

## Required Additional Checks

Before returning success, also check:

```python
if artifact.get("native_rebuild_allowed") is not False:
    return error

if artifact.get("step_import_allowed") is not True:
    return error

if artifact.get("step_path") != str(step_path):
    return error

if artifact.get("metadata_path") != str(meta_path):
    return error

artifact_dialects = artifact.get("selected_dialects")
metadata_dialects = metadata["generative_metadata"].get("selected_dialects")
if artifact_dialects != metadata_dialects:
    return error
```

## Acceptance Tests

Add to:

```text
tests/generative_cad/test_gcad_v09_builder_artifact_consistency.py
```

Tests can be source-inspection plus one behavior test if CAD runner is hard to execute.

Behavior target:

```python
def test_builder_artifact_has_same_selected_dialects_as_metadata(valid_build_result):
    artifact = valid_build_result["metrics"]["artifact"]
    metadata = json.loads(Path(valid_build_result["metrics"]["metadata_path"]).read_text())
    assert artifact["selected_dialects"] == metadata["generative_metadata"]["selected_dialects"]
```

---

# 7. Phase 5 — Import Gate Release Semantics

## File

```text
generative_cad/pipeline/import_artifact.py
```

## Current State

Gate flags are now initialized false and become true only on success. This is correct.

## Required Additional Invariants

Add a postcondition before returning ok:

```python
if not all(gate[k] is True for k in [
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
]):
    issues.append({
        "code": "gate_internal_invariant_failed",
        "message": "Import gate reached success path with incomplete true flags.",
    })
    gate["step_import_allowed"] = False
    return {"ok": False, "issues": issues, "metadata": metadata, "gate": gate}
```

Do not require `native_rebuild_allowed` to be true; it must remain false.

## Acceptance Tests

Create or extend:

```text
tests/generative_cad/test_gcad_v09_import_gate_release.py
```

Tests:

```python
def test_import_gate_success_has_all_required_true_flags(step_file, valid_import_metadata):
    result = validate_generative_step_artifact_for_native_import(step_file, valid_import_metadata)
    assert result["ok"]

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
    for key in required_true:
        assert result["gate"][key] is True

    assert result["gate"]["native_rebuild_allowed"] is False


def test_import_gate_failed_metadata_never_allows_step_import(step_file, bad_metadata):
    result = validate_generative_step_artifact_for_native_import(step_file, bad_metadata)
    assert not result["ok"]
    assert result["gate"]["step_import_allowed"] is False
```

---

# 8. Phase 6 — RepairPatchV2 Release Semantics

## File

```text
generative_cad/repair/patch.py
```

## Current State

RepairPatchV2 already supports:

```text
forbidden paths
allowed paths
missing target errors
old_value mismatch
applied count
give_up
```

## Required Additional Tests

Create:

```text
tests/generative_cad/test_gcad_v09_repair_release.py
```

Tests:

```python
def test_repair_patch_give_up_accepts_empty_changes(raw_doc):
    patch = RepairPatchV2(give_up=True, changes=[], reason="same error repeated")
    updated = apply_repair_patch_v2(raw_doc, patch)
    assert updated == raw_doc
    assert updated is not raw_doc


def test_repair_patch_old_value_none_skips_stale_check(raw_doc):
    patch = RepairPatchV2(
        target_node="n_holes",
        changes=[
            RepairChange(
                path="/nodes/n_holes/params/hole_dia_mm",
                old_value=None,
                new_value=24,
                reason="repair",
            )
        ],
        reason="repair",
    )
    updated = apply_repair_patch_v2(raw_doc, patch)
    node = next(n for n in updated["nodes"] if n["id"] == "n_holes")
    assert node["params"]["hole_dia_mm"] == 24


def test_repair_patch_rejects_selected_dialects_change():
    patch = RepairPatchV2(
        changes=[
            RepairChange(
                path="/selected_dialects",
                old_value=None,
                new_value=[],
                reason="bad",
            )
        ],
        reason="bad",
    )
    ok, issues = validate_repair_patch_v2(patch)
    assert not ok
    assert any(i["code"] == "forbidden_repair_path" for i in issues)
```

---

# 9. Phase 7 — Prompt Precision Fix

## File

```text
generative_cad/skills/prompts.py
```

## Problem

Current repair prompt contains paths rendered as:

```text
/nodes//params/
/nodes//inputs
/components//root_node
```

These are ambiguous and can lead an LLM to output invalid repair paths.

## Required Changes

Replace all such path examples with explicit placeholders:

```text
/nodes/<node_id>/params/<field>
/nodes/<node_id>/inputs
/nodes/<node_id>/outputs
/nodes/<node_id>/required
/nodes/<node_id>/degradation_policy
/components/<component_id>/root_node
```

Final repair prompt section must say:

```text
15. Prefer changing only /nodes/<node_id>/params/<field>.
16. You may change /nodes/<node_id>/inputs, /nodes/<node_id>/outputs, /nodes/<node_id>/required, /nodes/<node_id>/degradation_policy, or /components/<component_id>/root_node only when the validation error explicitly requires that exact structural repair.
17. Use old_value when available. If old_value no longer matches, the patch must not apply.
```

## Acceptance Tests

Create:

```text
tests/generative_cad/test_gcad_v09_prompt_paths.py
```

Tests:

```python
def test_repair_prompt_uses_placeholder_paths():
    assert "/nodes/<node_id>/params/<field>" in REPAIR_PATCH_SYSTEM_PROMPT_V2
    assert "/components/<component_id>/root_node" in REPAIR_PATCH_SYSTEM_PROMPT_V2
    assert "/nodes//params/" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
    assert "/components//root_node" not in REPAIR_PATCH_SYSTEM_PROMPT_V2
```

---

# 10. Phase 8 — Functional Tests Must Replace Source-Only Tests for Critical Gates

## Problem

Some current tests use `inspect.getsource()` to check that code strings exist. Source inspection tests are useful as smoke tests, but release gates must include behavior tests.

## Required Functional Test Categories

Add behavior tests for:

```text
1. metadata normalization with partial validation
2. run_gcad_core artifact/metadata consistency
3. builder final metadata hard validation
4. import gate success and failure flags
5. SW/NX wrapper gate-fail no native call
6. repair old_value mismatch and give_up
7. prompt path placeholders
8. production legacy import isolation
```

## Minimum Test Files

Ensure these exist:

```text
tests/generative_cad/test_gcad_v09_metadata_normalization.py
tests/generative_cad/test_gcad_v09_run_artifact_metadata_consistency.py
tests/generative_cad/test_gcad_v09_builder_initial_metadata.py
tests/generative_cad/test_gcad_v09_builder_artifact_consistency.py
tests/generative_cad/test_gcad_v09_import_gate_release.py
tests/generative_cad/test_gcad_v09_repair_release.py
tests/generative_cad/test_gcad_v09_prompt_paths.py
tests/generative_cad/test_gcad_v09_native_wrapper_behavior.py
tests/generative_cad/test_gcad_v09_legacy_isolation.py
```

---

# 11. Phase 9 — Legacy Isolation Gate

## Current State

Legacy root modules may still exist. That is acceptable for now only if production modules do not import legacy schema.

## Required Test

Create or update:

```text
tests/generative_cad/test_gcad_v09_legacy_isolation.py
```

Use precise import-pattern checks, not broad string checks that fail on error messages.

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

---

# 12. Final Prompt Assets

## Level-1 Routing Prompt

Use:

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

## Level-2 Authoring Prompt

Use:

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

## Repair Prompt

Use:

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
17. Use old_value when available. If old_value no longer matches, the patch must not apply.
18. If the same error signature repeated, output {"give_up": true, "reason": "..."}.
19. Output JSON only.
20. Output must match RepairPatchV2 schema.
21. Do not include markdown, prose, comments, or trailing commas.
"""
```

---

# 13. Release Acceptance Criteria

The implementation is complete only if all are true:

```text
1. build_generative_metadata normalizes partial validation dicts.
2. validate_generative_metadata_v2(require_validation_ok=False) accepts structurally complete but not-ok validation stages.
3. validate_generative_metadata_v2(require_validation_ok=True) rejects any not-ok stage.
4. builder canonical harness no longer fails initial metadata validation because runner metadata is partial.
5. run_canonical_gcad does not mutate validation_seed.
6. run_canonical_gcad result.artifact.validation equals result.metadata.validation.
7. run_gcad_core raw path produces metadata with inspection_validation.ok == False unless explicitly inspected.
8. import gate rejects runner-only metadata because inspection_validation.ok is false.
9. builder final metadata passes require_validation_ok=True.
10. builder artifact matches final metadata: canonical hash, selected dialects, validation, paths, native flags.
11. import gate success path has all required true flags except native_rebuild_allowed remains false.
12. SW/NX wrappers never call native import helper when gate fails.
13. RepairPatchV2 rejects stale old_value.
14. RepairPatchV2 give_up returns unchanged deep copy.
15. Repair prompt uses /nodes/<node_id>/params/<field>, not /nodes//params/.
16. production modules do not import legacy schema.
17. primitive pollution tests still pass.
18. no dialect/op added during this hardening pass.
```

---

# 14. Prohibited Shortcuts

Claude Code must not:

```text
1. Make metadata validator permissive.
2. Allow missing validation stages.
3. Mark inspection_validation ok without actual inspection.
4. Treat direct runner output as native-importable builder artifact.
5. Mutate validation_seed in place.
6. Allow import gate success when any required proof flag is false.
7. Suppress repair old_value mismatch.
8. Keep ambiguous prompt paths like /nodes//params/.
9. Add new dialects or operations.
10. Modify deterministic primitive semantics.
11. Turn Pydantic extra="forbid" into extra="allow".
12. Delete tests to make CI pass.
```

---

# 15. Final Architecture Statement

After v0.9 hardening, the system must satisfy:

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
validated STEP
+ metadata where all required validation stages are ok
+ import gate success
→ SolidWorks/NX STEP import
```

Do not expand geometry capability until this hardening pass passes all tests.
