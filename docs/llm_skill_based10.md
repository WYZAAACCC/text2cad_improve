# SeekFlow Generative CAD v0.8 Release-Candidate Hardening Spec

目标仓库：`WYZAAACCC/seekflow-engineering`
目标目录：`integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad`
执行对象：Claude Code
目标：把当前 v0.7 Generative CAD 从“hard-gate 基本闭合”推进到“release-candidate 级别的 LLM-Skill-Base / Generative CAD-IR 编译链路”。

---

## 0. 当前状态判断

当前代码已经完成了几项关键硬化：

```text
1. ValidationReport 已支持 stages_run。
2. validation/pipeline.py 已经 single-pass 收集 raw/canonical validation reports。
3. canonical validators 已强制导入，不再 lazy optional。
4. ValidationBundle 已接入 builder。
5. artifact.py 默认 validation 不再是空 dict，而是 fail-closed proof。
6. run_gcad_core raw entrypoint 已使用 validate_and_canonicalize_with_bundle。
7. runtime_postconditions 已检查 final handle、object_store、component root outputs。
8. metadata.py 已支持 require_validation_ok。
9. import gate 已要求 require_validation_ok=True。
10. tools.py 已新增 SolidWorks/NX generative import wrappers。
11. tools.py 已通过 native_importers module 调用 native CAD import helper。
12. builder.py 已拒绝 legacy GenerativeCADSpec。
13. builder.py 已对 graph_out / script_out 做 workspace guard。
14. RepairPatchV2 已具备 path validator 与 apply logic。
15. Skill DialectSelectionPlan 已具备 route invariant。
```

这说明当前系统已接近正确的 compiler hard-gate 架构。

但要达到可长期维护、可交给 agent 使用、可扩 dialect/op 的状态，还必须完成以下 release-candidate 收口：

```text
P0-RC1: direct canonical runner path 必须明确 metadata proof 语义，不能让人误以为 pre-validated canonical runner metadata 等价于 builder artifact metadata。
P0-RC2: builder final artifact / metadata / tool result 必须具有一致的 artifact manifest。
P0-RC3: native import wrappers 必须在测试中证明 gate fail 时不会调用 native import helper。
P0-RC4: RepairPatchV2 必须补齐 applied-count 与 give_up 语义测试。
P0-RC5: ValidationBundle / metadata / import gate / runtime postconditions 必须有完整 v0.8 regression tests。
P1-RC1: legacy 根目录模块必须被 production import isolation test 锁住。
P1-RC2: prompt 资产必须与 schema/contract 同步，禁止 selected_bases / feature_graph 等旧字段再次进入 LLM-facing prompt。
P1-RC3: 未来扩展 dialect/op 前必须建立 op-extension regression gate。
```

本次任务不新增 CAD 功能，不新增 dialect，不新增 operation，只做 release-candidate hardening。

---

# 1. 最终正确架构

Generative CAD v0.8 的最终架构必须固定为：

```text
User natural language
  ↓
Level-1 Domain Routing Skill
  ↓
DialectSelectionPlan JSON
  ↓
System loads selected Dialect Contracts + Level-2 Usage Skills
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
    run_canonical_gcad
  ↓
Runtime execution:
    BaseDialect.run_component
    OperationSpec.handler
    RuntimeObjectStore typed handles
  ↓
Runtime postconditions:
    final handle exists
    final object retrievable
    final handle is solid
    root outputs bound
  ↓
STEP export
  ↓
Strict STEP inspection
  ↓
generative_metadata_v2.1 with validation proof:
    core_validation.ok == true
    dialect_semantics.ok == true
    geometry_preflight.ok == true
    runtime_postconditions.ok == true
    inspection_validation.ok == true
  ↓
CanonicalStepArtifact manifest
  ↓
Optional native import:
    generative_cad_import_artifact_to_solidworks
    generative_cad_import_artifact_to_nx
```

The only merge point between deterministic and generative paths is:

```text
validated STEP artifact + validated metadata
```

Forbidden merge points:

```text
CADPartSpec
Primitive registry
Primitive compiler
geometry_primitives
SolidWorks feature-tree authoring
NXOpen feature-tree authoring
LLM-generated CadQuery code
LLM-generated Python scripts
```

---

# 2. Hard Constraints

Claude Code must not violate these constraints.

```text
1. Do not modify deterministic primitive semantics.
2. Do not register generative dialects as primitives.
3. Do not add generative fields to CADPartSpec.
4. Do not let LLM output CadQuery, Python, SolidWorks COM, NXOpen, APDL, shell commands, imports, exports, or file paths.
5. Do not let RawGcadDocument directly enter runtime handlers.
6. Do not let metadata without full validation proof pass native import gate.
7. Do not treat prompt text as a security boundary; schema validators are mandatory.
8. Do not weaken safety flags.
9. Do not allow native_rebuild_allowed=True for generative artifacts.
10. Do not add new dialects or operations in this release-candidate hardening task.
11. Do not remove tests to pass CI.
12. Do not turn Pydantic extra="forbid" into extra="allow".
13. Do not make direct canonical runner output appear equivalent to builder-produced validated artifact unless it contains full validation proof.
```

---

# 3. Module-Level Architecture

The final module responsibilities must be:

```text
generative_cad/ir/raw.py
  LLM-authorable source IR.
  Raw schema must be strict and extra=forbid.

generative_cad/ir/canonical.py
  Typed canonical IR.
  Only canonical IR may enter runtime.

generative_cad/validation/*
  Compiler front-end passes.
  Must be fail-closed and single-pass.

generative_cad/validation/bundle.py
  Structured validation proof carrier.
  Converts validation reports into metadata sections.

generative_cad/dialects/*
  Grammar dialects.
  Must expose manifest, contract, op_specs, validate_component, preflight_component, run_component.

generative_cad/runtime/*
  Runtime context, object store, typed handles, postconditions.

generative_cad/pipeline/run.py
  Runtime execution entrypoints.
  Raw entrypoint must produce full validation metadata.
  Canonical entrypoint must document that validation_seed may be required for full proof.

generative_cad/pipeline/metadata.py
  Metadata builder and validator.
  require_validation_ok=True must be used for native import gate and builder final validation.

generative_cad/pipeline/import_artifact.py
  Native import gate.
  Must enforce metadata proof, contract hash, safety flags, no native rebuild.

generative_cad/pipeline/artifact.py
  CanonicalStepArtifact manifest builder.
  Defaults must be fail-closed.

generative_cad/builder.py
  Main production build orchestrator.
  Validates raw, writes canonical graph, runs fixed harness, inspects STEP, rewrites metadata with proof, validates final metadata.

generative_cad/tools.py
  Agent-facing tools.
  Must expose dialect tools, validate/build tools, and SW/NX import wrappers.
  Must not contain native CAD implementation details; use native_importers.

generative_cad/native_importers.py
  Thin, testable, monkeypatchable native import helpers.

generative_cad/skills/*
  Prompt assets and schema for Level-1/Level-2/repair.
  Must use dialect terminology, not legacy base terminology.

generative_cad/repair/*
  Controlled local patch repair loop.
  Must not modify safety, dialect, op, op_version, selected_dialects, or constraints hard gates.
```

---

# 4. Phase 1 — Direct Canonical Runner Metadata Semantics

## Problem

`run_canonical_gcad()` accepts a pre-validated `CanonicalGcadDocument`. When called by the builder harness, builder later rewrites metadata with full validation proof. When called directly via `run_canonical_gcad_from_files()`, it may only have runtime_postconditions in validation unless a `validation_seed` is provided.

This is not necessarily wrong, but it must be explicit and impossible to confuse with a builder-produced validated artifact.

## Required Changes

File:

```text
generative_cad/pipeline/run.py
```

### 4.1 Add explicit metadata proof mode

Modify `run_canonical_gcad()` signature:

```python
def run_canonical_gcad(
    canonical: CanonicalGcadDocument,
    out_step: str | Path,
    metadata_path: str | Path,
    validation_seed: dict | None = None,
    require_full_validation_seed: bool = False,
) -> GcadRunResult:
    ...
```

Behavior:

```python
if require_full_validation_seed and validation_seed is None:
    return GcadRunResult(
        ok=False,
        error=(
            "run_canonical_gcad requires validation_seed when "
            "require_full_validation_seed=True. Use run_gcad_core for raw input "
            "or pass ValidationBundle.to_metadata_dict()."
        ),
    )
```

### 4.2 Raw entrypoint must pass validation_seed

`run_gcad_core()` must continue using:

```python
canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
...
return run_canonical_gcad(
    canonical,
    out_step=out_step,
    metadata_path=metadata_path,
    validation_seed=bundle.to_metadata_dict(),
    require_full_validation_seed=True,
)
```

### 4.3 Builder harness canonical entrypoint

`run_canonical_gcad_from_files()` may continue to call canonical runner without validation_seed, because builder will rewrite metadata after process returns.

But add docstring:

```text
This entrypoint is for pre-validated canonical documents. Metadata produced here is runner-local and may not contain full validation proof unless validation_seed is provided. Production build_generative_cad_model rewrites metadata with ValidationBundle and inspection proof before returning success.
```

### 4.4 Optional warning in canonical metadata

When `validation_seed is None`, add warning to ctx:

```python
ctx.warnings.append(
    "Canonical runner executed without validation_seed; metadata is runner-local and not a full importable proof until builder attaches validation bundle and inspection."
)
```

This warning must not appear in final builder success metadata after builder rewrites validation, but it may remain in build warnings.

## Acceptance Tests

File:

```text
tests/generative_cad/test_gcad_v08_run_metadata_modes.py
```

Tests:

```python
def test_run_canonical_requires_seed_when_requested(canonical, tmp_path):
    result = run_canonical_gcad(
        canonical,
        out_step=tmp_path / "part.step",
        metadata_path=tmp_path / "part.metadata.json",
        validation_seed=None,
        require_full_validation_seed=True,
    )
    assert not result.ok
    assert "requires validation_seed" in result.error


def test_run_gcad_core_raw_path_writes_full_validation_metadata(valid_raw_doc, tmp_path):
    result = run_gcad_core(
        valid_raw_doc,
        out_step=tmp_path / "part.step",
        metadata_path=tmp_path / "part.metadata.json",
    )
    assert result.ok
    meta = json.loads((tmp_path / "part.metadata.json").read_text())
    for key in [
        "core_validation",
        "dialect_semantics",
        "geometry_preflight",
        "runtime_postconditions",
    ]:
        assert meta["validation"][key]["ok"] is True
```

---

# 5. Phase 2 — Builder Final Artifact / Metadata Consistency

## Problem

`builder.py` writes final metadata and includes `metrics["artifact"]`. The artifact manifest must be consistent with metadata:

```text
artifact.canonical_graph_hash == metadata.generative_metadata.canonical_graph_hash
artifact.selected_dialects == metadata.generative_metadata.selected_dialects
artifact.validation == metadata.validation
artifact.native_rebuild_allowed == False
```

## Required Changes

File:

```text
generative_cad/builder.py
```

After building `metrics["artifact"]`, add internal consistency check:

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

metadata_gm = metadata["generative_metadata"]

if artifact["canonical_graph_hash"] != metadata_gm["canonical_graph_hash"]:
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error="Artifact/metadata canonical_graph_hash mismatch.",
        files_created=files_created,
    ).model_dump()

if artifact["validation"] != metadata["validation"]:
    return EngineeringActionResult(
        ok=False,
        software="cadquery",
        action="build_generative_cad",
        error="Artifact/metadata validation proof mismatch.",
        files_created=files_created,
    ).model_dump()

metrics["artifact"] = artifact
```

## Acceptance Tests

File:

```text
tests/generative_cad/test_gcad_v08_builder_artifact_consistency.py
```

Tests:

```python
def test_builder_artifact_matches_final_metadata(valid_raw_doc, config, tmp_path):
    result = build_generative_cad_model(
        spec=valid_raw_doc,
        config=config,
        out_step=tmp_path / "part.step",
        inspect=True,
        strict_inspection=True,
    )
    assert result["ok"]

    artifact = result["metrics"]["artifact"]
    metadata = json.loads(Path(result["metrics"]["metadata_path"]).read_text())

    assert artifact["canonical_graph_hash"] == metadata["generative_metadata"]["canonical_graph_hash"]
    assert artifact["validation"] == metadata["validation"]
    assert artifact["native_rebuild_allowed"] is False
```

If `metadata_path` is not currently included in metrics, add:

```python
"metadata_path": str(meta_path)
```

---

# 6. Phase 3 — RepairPatchV2 Final Hardening

## Current Good State

RepairPatchV2 already has:

```text
RepairChange
RepairPatchV2
is_forbidden_repair_path
is_allowed_repair_path
validate_repair_patch_v2
apply_repair_patch_v2
```

It now raises for missing node/component.

## Remaining Required Hardening

File:

```text
generative_cad/repair/patch.py
```

### 6.1 Add applied count

Even though all known path branches should apply or raise, add explicit `applied` counter for future safety:

```python
applied = 0
...
applied += 1
...
if not patch.give_up and applied != len(patch.changes):
    raise ValueError(
        f"repair patch applied {applied} of {len(patch.changes)} change(s)"
    )
```

### 6.2 Give-up semantics

If `patch.give_up is True`, do not require changes and return unchanged deep copy:

```python
if patch.give_up:
    return copy.deepcopy(raw)
```

This must be explicit at top of `apply_repair_patch_v2()` after validation.

### 6.3 old_value optional verification

Add optional safety check:

```python
def _old_value_matches(current, expected) -> bool:
    return expected is None or current == expected
```

For `/nodes/<id>/params/<field>`, if `old_value is not None` and current value differs, raise:

```python
raise ValueError(
    f"repair old_value mismatch at {path}: expected {change.old_value!r}, got {current!r}"
)
```

This prevents stale repair patches from applying to a mutated graph.

Apply old_value check to:

```text
/nodes/<id>/params/<field>
/nodes/<id>/inputs
/nodes/<id>/outputs
/nodes/<id>/required
/nodes/<id>/degradation_policy
/components/<id>/root_node
/llm_validation_hints
```

## Acceptance Tests

File:

```text
tests/generative_cad/test_gcad_v08_repair_patch.py
```

Tests:

```python
def test_repair_patch_give_up_returns_unchanged(raw_doc):
    patch = RepairPatchV2(give_up=True, changes=[], reason="repeat error")
    updated = apply_repair_patch_v2(raw_doc, patch)
    assert updated == raw_doc
    assert updated is not raw_doc


def test_repair_patch_old_value_mismatch_rejected(raw_doc):
    patch = RepairPatchV2(
        target_node="n_holes",
        changes=[
            RepairChange(
                path="/nodes/n_holes/params/hole_dia_mm",
                old_value=999,
                new_value=24,
                reason="reduce",
            )
        ],
        reason="repair",
    )
    with pytest.raises(ValueError, match="old_value mismatch"):
        apply_repair_patch_v2(raw_doc, patch)


def test_repair_patch_applied_count_matches_changes(raw_doc):
    patch = RepairPatchV2(
        target_node="n_holes",
        changes=[
            RepairChange(
                path="/nodes/n_holes/params/hole_dia_mm",
                old_value=32,
                new_value=24,
                reason="reduce",
            )
        ],
        reason="repair",
    )
    updated = apply_repair_patch_v2(raw_doc, patch)
    assert updated != raw_doc
```

---

# 7. Phase 4 — Import Gate Release Invariants

## Current State

Import gate already validates:

```text
STEP exists
metadata exists
metadata JSON parses
metadata validate_generative_metadata_v2(require_validation_ok=True)
safety
contract hash via metadata validator
native rebuild forbidden
geometry_preflight
inspection_validation
runtime_postconditions
```

## Required Hardening

File:

```text
generative_cad/pipeline/import_artifact.py
```

### 7.1 Gate flags must be complete at every return

Every return path must include a `gate` dict with all keys:

```python
REQUIRED_GATE_FLAGS = [
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
    "native_rebuild_allowed",
    "step_import_allowed",
]
```

Initialize all to conservative defaults:

```python
gate = {
    "step_exists": False,
    "metadata_exists": False,
    "metadata_valid": False,
    "safety_valid": False,
    "contract_hash_valid": False,
    "core_validation_ok": False,
    "dialect_semantics_ok": False,
    "geometry_preflight_ok": False,
    "runtime_postconditions_ok": False,
    "inspection_ok": False,
    "native_rebuild_allowed": False,
    "step_import_allowed": False,
}
```

No early return may omit these keys.

### 7.2 Optional strict flags must reflect state

Even when `require_inspection_ok=False`, set:

```python
gate["inspection_ok"] = isinstance(insp, dict) and insp.get("ok") is True
```

Even when `require_geometry_preflight_ok=False`, set:

```python
gate["geometry_preflight_ok"] = isinstance(gp, dict) and gp.get("ok") is True
```

### 7.3 Metadata failure classification

If metadata validator fails:

```python
for issue in meta_result["issues"]:
    if issue["code"] in {"contract_hash_mismatch", "unknown_metadata_dialect"}:
        gate["contract_hash_valid"] = False
```

If metadata validator succeeds:

```python
gate["metadata_valid"] = True
gate["contract_hash_valid"] = True
```

### 7.4 Safety flag

Only set:

```python
gate["safety_valid"] = True
```

after all safety flags are true and metadata validator has passed.

## Acceptance Tests

File:

```text
tests/generative_cad/test_gcad_v08_import_gate_flags.py
```

Tests:

```python
def test_import_gate_all_returns_have_required_flags(missing_step, metadata_path):
    result = validate_generative_step_artifact_for_native_import(missing_step, metadata_path)
    for key in REQUIRED_GATE_FLAGS:
        assert key in result["gate"]


def test_import_gate_optional_inspection_records_false_state(step_file, valid_metadata):
    metadata = load(valid_metadata)
    metadata["validation"]["inspection_validation"] = {"ok": False, "issues": []}
    save(valid_metadata, metadata)

    result = validate_generative_step_artifact_for_native_import(
        step_file,
        valid_metadata,
        require_inspection_ok=False,
    )

    assert result["gate"]["inspection_ok"] is False


def test_import_gate_contract_hash_flag_false_on_mismatch(step_file, valid_metadata):
    metadata = load(valid_metadata)
    metadata["generative_metadata"]["selected_dialects"][0]["contract_hash"] = "sha256:bad"
    save(valid_metadata, metadata)

    result = validate_generative_step_artifact_for_native_import(step_file, valid_metadata)

    assert not result["ok"]
    assert result["gate"]["contract_hash_valid"] is False
```

---

# 8. Phase 5 — Native Wrapper Testability and Failure Semantics

## Current State

`tools.py` already uses:

```python
from seekflow_engineering_tools.generative_cad import native_importers
...
native_importers.import_step_to_solidworks(...)
native_importers.import_step_to_nx(...)
```

This is correct.

## Required Tests

File:

```text
tests/generative_cad/test_gcad_v08_native_import_wrappers.py
```

### 8.1 Gate failure must not call native import

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

    tool = get_tool(build_generative_cad_tools(config), "generative_cad_import_artifact_to_solidworks")

    result = tool(
        step_path=str(step_file),
        metadata_path=str(bad_metadata),
        out_sldprt="out.sldprt",
    )

    assert not result["ok"]
    assert called["sw"] is False
```

### 8.2 Gate success calls native import

```python
def test_solidworks_wrapper_calls_native_import_after_gate_passes(
    monkeypatch,
    config,
    step_file,
    valid_metadata,
):
    from seekflow_engineering_tools.generative_cad import native_importers

    called = {"sw": False}

    def fake_import(config, step, out):
        called["sw"] = True
        return {"ok": True, "files_created": [str(out)]}

    monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_import)

    tool = get_tool(build_generative_cad_tools(config), "generative_cad_import_artifact_to_solidworks")

    result = tool(
        step_path=str(step_file),
        metadata_path=str(valid_metadata),
        out_sldprt="out.sldprt",
    )

    assert result["ok"]
    assert called["sw"] is True
    assert result["metrics"]["native_rebuild_allowed"] is False
```

Repeat equivalent tests for NX.

### 8.3 Native import failure propagates

```python
def test_solidworks_wrapper_propagates_native_import_failure(
    monkeypatch,
    config,
    step_file,
    valid_metadata,
):
    def fake_import(*args, **kwargs):
        raise RuntimeError("mock SW failure")

    monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_import)

    result = call_sw_wrapper(...)

    assert not result["ok"]
    assert "mock SW failure" in result["error"]
```

---

# 9. Phase 6 — Prompt Assets Final Synchronization

## Files

```text
generative_cad/skills/prompts.py
generative_cad/skills/schemas.py
```

## Required Final Prompt Content

### 9.1 Level-1 Routing Prompt

Replace with:

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

### 9.2 Level-2 Authoring Prompt

Replace with:

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

### 9.3 Repair Prompt

Replace with:

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

## Prompt Tests

File:

```text
tests/generative_cad/test_gcad_v08_prompts.py
```

Tests:

```python
def test_prompts_do_not_use_legacy_terms():
    legacy_terms = ["selected_bases", "feature_graph", "base_id", "GenerativeCADSpec"]
    prompts = [
        LEVEL1_ROUTING_SYSTEM_PROMPT,
        LEVEL2_AUTHORING_SYSTEM_PROMPT,
        REPAIR_PATCH_SYSTEM_PROMPT_V2,
    ]
    for prompt in prompts:
        for term in legacy_terms:
            if term in {"selected_bases", "feature_graph", "base_id", "GenerativeCADSpec"}:
                # allowed only when listed as deprecated/forbidden
                assert f"Do not use" in prompt or "deprecated" in prompt


def test_level2_prompt_forbids_unsupported_capabilities_in_raw():
    assert "Never include unsupported_capabilities inside RawGcadDocument" in LEVEL2_AUTHORING_SYSTEM_PROMPT
```

---

# 10. Phase 7 — Legacy Isolation Release Gate

## Problem

Legacy root modules may still exist:

```text
generative_cad/base.py
generative_cad/ir.py
generative_cad/registry.py
generative_cad/graph_validation.py
generative_cad/metadata.py
generative_cad/preflight.py
generative_cad/prompts.py
generative_cad/repair_governor.py
generative_cad/runner.py
generative_cad/validation.py
```

They are not automatically wrong, but production modules must not import legacy schema.

## Required Test

File:

```text
tests/generative_cad/test_gcad_v08_legacy_isolation.py
```

Test:

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

## Optional Future Cleanup

After v0.8 release candidate passes, migrate legacy modules under:

```text
generative_cad/legacy/
```

But do not do that in this hardening pass unless tests force it.

---

# 11. Required v0.8 Test Matrix

Claude Code must add or ensure these test files exist:

```text
tests/generative_cad/test_gcad_v08_run_metadata_modes.py
tests/generative_cad/test_gcad_v08_builder_artifact_consistency.py
tests/generative_cad/test_gcad_v08_repair_patch.py
tests/generative_cad/test_gcad_v08_import_gate_flags.py
tests/generative_cad/test_gcad_v08_native_import_wrappers.py
tests/generative_cad/test_gcad_v08_prompts.py
tests/generative_cad/test_gcad_v08_legacy_isolation.py
```

Existing v0.7 tests should remain.

Run:

```bash
pytest integrations/engineering_tools/tests/generative_cad
pytest integrations/engineering_tools/tests/test_generative_no_main_chain_pollution.py
```

If old repair governor tests are v0.1-specific, mark them as legacy tests and make sure they do not constrain v0.8 production repair behavior.

---

# 12. Acceptance Criteria

Implementation is complete only when all statements are true:

```text
1. Raw → Canonical validation is fail-closed and single-pass.
2. validate_and_canonicalize_with_bundle returns consistent report + bundle.
3. run_gcad_core raw path writes full validation metadata.
4. run_canonical_gcad can enforce require_full_validation_seed.
5. Builder final metadata passes validate_generative_metadata_v2(require_validation_ok=True).
6. Builder artifact matches final metadata validation and canonical hash.
7. Artifact default validation is fail-closed, never {}.
8. Import gate returns complete gate flags on every return path.
9. Import gate rejects missing/failed validation proof.
10. SW/NX wrappers never call native import helper when gate fails.
11. SW/NX wrappers propagate native import failure.
12. RepairPatchV2 rejects forbidden paths.
13. RepairPatchV2 rejects stale old_value.
14. RepairPatchV2 raises on missing target node/component.
15. RepairPatchV2 supports give_up without changes.
16. Prompts forbid legacy fields and code generation.
17. Skill schema route invariants remain enforced.
18. Production modules do not import legacy schema.
19. Primitive pollution tests pass.
20. No dialect/op added during this task.
```

---

# 13. Prohibited Shortcuts

Claude Code must not:

```text
1. Turn extra="forbid" into extra="allow".
2. Remove stages_run or validation proof to pass tests.
3. Make import gate permissive.
4. Mark missing validation as ok.
5. Allow native rebuild for generative artifacts.
6. Skip native wrapper tests by mocking the whole wrapper.
7. Apply repair patches silently when target does not exist.
8. Ignore old_value mismatch.
9. Add dialect/op functionality.
10. Modify deterministic primitive path semantics.
```

---

# 14. Final Release-Candidate Architecture Statement

v0.8 release-candidate architecture:

```text
LLM output is grammar, not code.
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

This is the correct LLM-Skill-Base / Generative CAD-IR architecture.

No new geometry capability should be added until this hardening pass is complete.
