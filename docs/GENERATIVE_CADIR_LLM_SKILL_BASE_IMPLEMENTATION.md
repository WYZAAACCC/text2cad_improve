# SeekFlow Engineering Tools — `llm_skill_base` / Generative CAD-IR Engineering Implementation Document

Version: v0.1 implementation proposal  
Date: 2026-05-29  
Target repository: `WYZAAACCC/seekflow-engineering`, package `integrations/engineering_tools`  
Audience: Claude Code / implementation agent / architecture reviewer  
Status: implementation-ready architecture, intended to be executed without altering the existing precise primitive path

---

## 0. Executive Summary

This document specifies how to add a new **Generative CAD-IR path** to the existing SeekFlow Engineering Tools codebase.

The new path supports the user goal:

> Let an LLM output structured modelling steps and construction strategy, choose and use generic CAD grammar bases, generate a controlled model through a verified base runner, export STEP, write metadata, inspect and validate the result, then merge into the existing engineering pipeline only at the canonical STEP artifact level.

This path must **not** replace, weaken, or contaminate the existing deterministic CAD-IR / recipe / primitive path.

The existing path remains:

```text
CADPartSpec
  -> recipe / primitive compiler
  -> deterministic CadQuery script
  -> STEP
  -> metadata sidecar
  -> inspection / validation / mechanical validation
```

The new path is:

```text
Natural language
  -> Base selection plan
  -> selected base contract loading
  -> LLM emits GenerativeCADSpec / FeatureGraph
  -> registry + schema + graph + semantic + geometry preflight validation
  -> fixed runner harness executes registered base operation handlers
  -> STEP + generative metadata sidecar
  -> STEP import inspection
  -> canonical_step_artifact
  -> existing downstream inspection/import style, but not primitive compiler
```

The most important design rule:

> **The LLM never writes CadQuery, SolidWorks COM, NXOpen, APDL, filesystem, subprocess, import, export, or metadata-writing code. The LLM only writes a schema-valid feature graph.**

---

## 1. Current Codebase Anchors and Constraints

The implementation must respect the current architecture.

### 1.1 Existing package structure

Relevant package root:

```text
integrations/engineering_tools/src/seekflow_engineering_tools/
```

Existing important modules:

```text
cadquery_backend/
  builder.py
  compiler.py
  primitive_compiler.py
  inspector.py
  tools.py

capabilities/
  registry.py

common/
  models.py
  paths.py

config.py

geometry_primitives/
  registry.py
  base.py
  gears/
  turbomachinery/

inspection/
  validation.py

ir/
  cad.py
  primitive.py

mechanical_validation/

natural_language/
  prompts.py
  tools.py

registry.py

repair/
  loop.py
```

### 1.2 Do not modify the precise primitive route

Do **not** change the semantics of:

```text
cadquery_backend/primitive_compiler.py
geometry_primitives/registry.py
geometry_primitives/*
mechanical_validation/* primitive validators
ir/primitive.py
```

The deterministic primitive path remains the high-trust path.

Do not add generative features into `PRIMITIVE_COMPILERS`.

Do not make `axisymmetric_turbine_disk` call the new generative path.

Do not make `involute_spur_gear` call the new generative path.

### 1.3 Do not alter `CADPartSpec` in v0

For v0, do **not** add generative feature types into the existing `CADFeature` union in:

```text
ir/cad.py
```

Reason: the current `CADPartSpec` is the precise CAD-IR boundary. Adding a generative feature into the same union would blur trust levels and likely affect existing validators, backend selection, and tests.

Instead, create a separate IR:

```text
generative_cad/ir.py
```

Later, after the path is stable, a higher-level wrapper can be introduced:

```text
EngineeringPartSpec
  deterministic_features: CADPartSpec
  generative_features: GenerativeCADSpec
  artifact_features: CanonicalStepArtifactSpec
```

But do not implement that wrapper in v0.

### 1.4 Existing builder style to reuse, not mutate

The current CadQuery build tool already compiles, executes, checks file creation, inspects STEP, validates, loads metadata, and returns `EngineeringActionResult`.

The new builder should follow the same return type and safety style:

```python
from seekflow_engineering_tools.common.models import EngineeringActionResult
```

Use existing workspace path safety:

```python
from seekflow_engineering_tools.common.paths import ensure_inside_workspace, ensure_extension
```

Use existing config:

```python
from seekflow_engineering_tools.config import EngineeringToolsConfig
```

Use existing STEP inspector:

```python
from seekflow_engineering_tools.cadquery_backend.inspector import inspect_step_with_cadquery
```

But do not call `compile_cad_ir_to_cadquery_script` from the generative path, because that compiler is for `CADPartSpec`, not `GenerativeCADSpec`.

---

## 2. Non-Negotiable Architecture Rules

Claude Code must implement the new path under these hard rules.

### Rule 1 — No LLM backend code

Never allow the LLM to output or modify:

```text
Python imports
CadQuery API calls
SolidWorks COM code
NXOpen code
APDL code
subprocess calls
file IO paths
STEP export logic
metadata write logic
validation pass/fail decisions
```

### Rule 2 — LLM outputs only data

The LLM output must be a strict JSON/Pydantic model:

```text
GenerativeCADSpec
```

containing:

```text
selected_bases
selected_skills
feature_graph
validation hints
safety flags
```

### Rule 3 — base is grammar, not part template

Base names must describe modelling grammar, not specific parts.

Allowed examples:

```text
axisymmetric_base
sketch_extrude_base
loft_sweep_base
shell_housing_base
composition_base
```

Disallowed examples:

```text
turbine_disk_base
flange_base
bracket_base
gearbox_base
bearing_seat_base
```

Specific domain behaviour belongs in `skill`, not `base`.

### Rule 4 — no arbitrary op invention

If the feature graph contains a `base_id` or `op` that is not registered, the build must fail closed.

No fuzzy matching.

No nearest-operation fallback.

No silent conversion.

### Rule 5 — no dynamic script generation beyond fixed harness

The generative path must not dynamically generate large CadQuery scripts from the LLM graph.

Instead:

```text
GenerativeCADSpec JSON
  -> fixed runner harness Python script
  -> runner loads JSON
  -> runner calls registered operation handlers
```

The generated script should be only a small fixed harness.

### Rule 6 — no change to existing main chain behaviour

All existing tests for CAD-IR, recipes, primitives, turbine disk, gear, SolidWorks mock, NX mock, ANSYS, metadata, and demo chains must continue to pass.

### Rule 7 — merge only at artifact level

The new path merges into the existing framework only after it has produced:

```text
STEP file
.metadata.json sidecar
artifact descriptor
inspection report
```

It does not merge at:

```text
CADPartSpec feature union
primitive compiler
primitive registry
mechanical primitive validator dispatch
```

### Rule 8 — generative artifacts are lower trust by default

Any output from `llm_skill_base` has trust level:

```text
reference_geometry
```

or lower. It must not claim:

```text
manufacturing-ready
production-ready
airworthy
certified
flight-ready
installable
structurally validated
life predicted
```

---

## 3. Target Directory Layout

Add this new package:

```text
integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/
  __init__.py
  artifact.py
  base.py
  builder.py
  contract.py
  errors.py
  graph_validation.py
  ir.py
  manifest.py
  metadata.py
  preflight.py
  registry.py
  repair_governor.py
  runner.py
  tools.py
  trust.py
  validation.py
  prompts.py
  bases/
    __init__.py
    axisymmetric/
      __init__.py
      contract.py
      manifest.py
      models.py
      preflight.py
      runner.py
    sketch_extrude/
      __init__.py
      contract.py
      manifest.py
      models.py
      preflight.py
      runner.py
  skills/
    generic_mechanical_skill.md
    turbomachinery_reference_skill.md
```

Add tests:

```text
integrations/engineering_tools/tests/test_generative_cad_ir.py
integrations/engineering_tools/tests/test_generative_base_registry.py
integrations/engineering_tools/tests/test_generative_axisymmetric_base.py
integrations/engineering_tools/tests/test_generative_sketch_extrude_base.py
integrations/engineering_tools/tests/test_generative_graph_validation.py
integrations/engineering_tools/tests/test_generative_preflight.py
integrations/engineering_tools/tests/test_generative_builder.py
integrations/engineering_tools/tests/test_generative_metadata.py
integrations/engineering_tools/tests/test_generative_repair_governor.py
integrations/engineering_tools/tests/test_generative_tools.py
integrations/engineering_tools/tests/test_generative_no_main_chain_pollution.py
```

Add optional demo:

```text
integrations/engineering_tools/demo_generative_cad.py
```

---

## 4. New IR: `generative_cad/ir.py`

Implement Pydantic models with `extra="forbid"` everywhere.

### 4.1 Core model

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

LengthUnit = Literal["mm"]
TrustLevel = Literal["concept_geometry", "reference_geometry"]
GenerationRoute = Literal["llm_skill_base"]


class SelectedBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_id: str
    base_version: str


class SelectedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    skill_version: str


class FeatureGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    base_id: str
    op: str
    phase: str
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    required: bool = True
    degradation_policy: Literal["fail", "may_skip_with_warning"] = "fail"

    @model_validator(mode="after")
    def validate_id(self):
        if not self.id.strip():
            raise ValueError("node id must be non-empty")
        if not self.base_id.strip():
            raise ValueError("base_id must be non-empty")
        if not self.op.strip():
            raise ValueError("op must be non-empty")
        if not self.phase.strip():
            raise ValueError("phase must be non-empty")
        if self.required and self.degradation_policy != "fail":
            raise ValueError("required nodes must use degradation_policy='fail'")
        return self


class FeatureGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[FeatureGraphNode]

    @model_validator(mode="after")
    def validate_unique_ids(self):
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("feature graph node ids must be unique")
        return self


class SystemValidationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_step_file: bool = True
    require_metadata_sidecar: bool = True
    require_closed_solid: bool = True
    expected_body_count: int = Field(default=1, ge=1)
    expected_bbox_mm: list[float] | None = None
    bbox_tolerance_mm: float = Field(default=1.0, gt=0)
    max_runtime_seconds: int = Field(default=120, ge=1, le=600)

    @model_validator(mode="after")
    def validate_bbox(self):
        if self.expected_bbox_mm is not None and len(self.expected_bbox_mm) != 3:
            raise ValueError("expected_bbox_mm must be [x, y, z]")
        if not self.require_step_file:
            raise ValueError("require_step_file cannot be false")
        if not self.require_metadata_sidecar:
            raise ValueError("require_metadata_sidecar cannot be false")
        if not self.require_closed_solid:
            raise ValueError("require_closed_solid cannot be false")
        return self


class LLMValidationHints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_outer_dia_mm: float | None = Field(default=None, gt=0)
    expected_length_mm: float | None = Field(default=None, gt=0)
    expected_axial_width_mm: float | None = Field(default=None, gt=0)
    expected_feature_notes: list[str] = Field(default_factory=list)


class SafetyFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    non_flight_reference_only: bool = True
    not_airworthy: bool = True
    not_certified: bool = True
    not_for_manufacturing: bool = True
    not_for_installation: bool = True
    no_structural_validation: bool = True
    no_life_prediction: bool = True

    @model_validator(mode="after")
    def enforce_true(self):
        for name, value in self.model_dump().items():
            if value is not True:
                raise ValueError(f"safety flag {name} must be true")
        return self


class GenerativeCADSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ir_version: Literal["g_cad_ir_v0.1"] = "g_cad_ir_v0.1"
    generation_route: GenerationRoute = "llm_skill_base"
    part_name: str
    units: LengthUnit = "mm"
    trust_level: TrustLevel = "reference_geometry"
    selected_bases: list[SelectedBase]
    selected_skills: list[SelectedSkill] = Field(default_factory=list)
    feature_graph: FeatureGraph
    system_validation_contract: SystemValidationContract = Field(default_factory=SystemValidationContract)
    llm_validation_hints: LLMValidationHints = Field(default_factory=LLMValidationHints)
    safety: SafetyFlags = Field(default_factory=SafetyFlags)

    @model_validator(mode="after")
    def validate_basic(self):
        if not self.part_name.strip():
            raise ValueError("part_name must be non-empty")
        if not self.selected_bases:
            raise ValueError("selected_bases must not be empty")
        selected_ids = {b.base_id for b in self.selected_bases}
        for node in self.feature_graph.nodes:
            if node.base_id not in selected_ids:
                raise ValueError(
                    f"node {node.id!r} uses base {node.base_id!r}, not present in selected_bases"
                )
        if self.trust_level not in {"concept_geometry", "reference_geometry"}:
            raise ValueError("generative CAD trust_level cannot exceed reference_geometry")
        return self
```

### 4.2 Important IR constraints

- `GenerativeCADSpec` is separate from `CADPartSpec`.
- `system_validation_contract` cannot be weakened by LLM.
- `SafetyFlags` must all be true.
- `FeatureGraphNode.params` is initially `dict[str, Any]`, but each operation validates it against its own Pydantic params model in the selected base.
- Do not include raw code fields in this IR. Reject any fields like `python_code`, `cadquery_script`, `script`, `import`, `export_code` via `extra="forbid"`.

---

## 5. Artifact Spec: `generative_cad/artifact.py`

Create a canonical artifact descriptor for merge into downstream pipeline.

```python
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class CanonicalStepArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["canonical_step_artifact"] = "canonical_step_artifact"
    source_route: Literal["llm_skill_base"] = "llm_skill_base"
    part_name: str
    step_path: str
    metadata_path: str
    graph_path: str
    runner_script_path: str | None = None
    units: Literal["mm"] = "mm"
    trust_level: Literal["concept_geometry", "reference_geometry"] = "reference_geometry"
    native_rebuild_allowed: bool = False
    step_import_allowed: bool = True
    inspection: dict = Field(default_factory=dict)
    validation: dict = Field(default_factory=dict)
```

This artifact is what downstream tooling may consume.

Never convert this artifact into a primitive.

---

## 6. Base API: `generative_cad/base.py`

Implement a strict interface.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from pydantic import BaseModel


@dataclass(frozen=True)
class OperationDefinition:
    op: str
    phase: str
    params_model: type[BaseModel]
    description: str
    required_context_flags: tuple[str, ...] = ()
    produced_context_flags: tuple[str, ...] = ()
    optional: bool = False


class BaseDefinition(Protocol):
    base_id: str
    version: str
    phase_order: tuple[str, ...]
    operation_definitions: dict[str, OperationDefinition]

    def export_manifest(self) -> dict[str, Any]: ...
    def export_contract(self) -> dict[str, Any]: ...
    def validate_semantics(self, graph: dict[str, Any]) -> list[dict[str, Any]]: ...
    def preflight(self, graph: dict[str, Any]) -> list[dict[str, Any]]: ...
    def run(self, graph: dict[str, Any], context: "GenerativeBuildContext") -> "GenerativeRunResult": ...
```

Do not let bases accept arbitrary unknown operations.

---

## 7. Registry: `generative_cad/registry.py`

Implement explicit base registration.

```python
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.base import BaseDefinition

BASE_REGISTRY: dict[str, BaseDefinition] = {}


def register_base(base: BaseDefinition) -> None:
    if base.base_id in BASE_REGISTRY:
        raise ValueError(f"Duplicate generative CAD base_id: {base.base_id}")
    if not base.base_id.endswith("_base"):
        raise ValueError("base_id must end with '_base'")
    forbidden_part_names = ["turbine_disk", "flange", "bracket", "gearbox", "bearing"]
    for token in forbidden_part_names:
        if token in base.base_id:
            raise ValueError(
                f"base_id {base.base_id!r} appears to name a part, not a CAD grammar"
            )
    BASE_REGISTRY[base.base_id] = base


def get_base(base_id: str) -> BaseDefinition | None:
    return BASE_REGISTRY.get(base_id)


def list_bases() -> list[str]:
    return sorted(BASE_REGISTRY.keys())


def export_base_catalog() -> dict:
    return {
        "base_catalog_version": "0.1.0",
        "bases": [BASE_REGISTRY[k].export_manifest() for k in sorted(BASE_REGISTRY.keys())],
    }


def _populate_registry() -> None:
    from seekflow_engineering_tools.generative_cad.bases.axisymmetric.runner import AXISYMMETRIC_BASE
    from seekflow_engineering_tools.generative_cad.bases.sketch_extrude.runner import SKETCH_EXTRUDE_BASE

    register_base(AXISYMMETRIC_BASE)
    register_base(SKETCH_EXTRUDE_BASE)


_populate_registry()
```

Do not use importlib magic in v0 unless necessary. Explicit registration is easier to review and avoids hidden side effects.

---

## 8. Base Manifest and Contract

Each base must expose two LLM-facing documents.

### 8.1 Manifest

Small, always safe to include in prompt.

Example for `axisymmetric_base`:

```python
AXISYMMETRIC_MANIFEST = {
    "base_id": "axisymmetric_base",
    "base_version": "0.1.0",
    "summary": "For rotationally symmetric solids generated from radial-axial profiles, with optional coaxial bores, grooves, circular hole patterns, and rim slot patterns.",
    "typical_parts": ["disk", "hub", "flange", "ring", "pulley", "shaft-like bodies"],
    "main_ops": [
        "revolve_profile",
        "cut_center_bore",
        "cut_annular_groove",
        "cut_circular_hole_pattern",
        "cut_rim_slot_pattern",
        "apply_safe_chamfer",
    ],
    "unsupported": [
        "freeform surfaces",
        "arbitrary Python",
        "internal cooling networks",
        "non-axisymmetric housings",
    ],
}
```

### 8.2 Contract

Detailed enough for the LLM to emit valid graphs, but not implementation code.

Example structure:

```json
{
  "base_id": "axisymmetric_base",
  "base_version": "0.1.0",
  "phase_order": [
    "base_solid",
    "primary_cut",
    "annular_detail",
    "pattern_cut",
    "rim_detail",
    "edge_treatment",
    "cleanup"
  ],
  "allowed_ops": {
    "revolve_profile": {
      "phase": "base_solid",
      "description": "Create a rotational solid from radial-axial profile stations.",
      "required_params": ["axis", "profile_stations"],
      "hard_constraints": [
        "axis must be 'Z' in v0",
        "all radii must be positive",
        "z_front_mm <= z_rear_mm for each station",
        "profile_stations must contain at least 2 stations"
      ]
    },
    "cut_circular_hole_pattern": {
      "phase": "pattern_cut",
      "description": "Cut a circular pattern of through holes along the Z axis.",
      "required_params": ["count", "pcd_mm", "hole_dia_mm", "axis", "through_all"],
      "hard_constraints": [
        "count between 2 and 240",
        "hole_dia_mm > 0",
        "pcd_mm > 0",
        "axis must be 'Z' in v0"
      ]
    }
  }
}
```

Do not include CadQuery code in the contract.

---

## 9. Graph Validation: `generative_cad/graph_validation.py`

Implement a validation pipeline with deterministic reports.

### 9.1 Report format

```python
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Any

class GenerativeValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    node_id: str | None = None
    stage: str
    expected: Any | None = None
    actual: Any | None = None

class GenerativeValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    stage: str
    issues: list[GenerativeValidationIssue] = Field(default_factory=list)
```

### 9.2 Validation stages

Implement these functions:

```python
def validate_selected_bases_exist(spec: GenerativeCADSpec) -> GenerativeValidationReport: ...
def validate_node_ops_exist(spec: GenerativeCADSpec) -> GenerativeValidationReport: ...
def validate_op_params_schema(spec: GenerativeCADSpec) -> GenerativeValidationReport: ...
def validate_graph_dag(spec: GenerativeCADSpec) -> GenerativeValidationReport: ...
def validate_phase_order(spec: GenerativeCADSpec) -> GenerativeValidationReport: ...
def validate_base_semantics(spec: GenerativeCADSpec) -> GenerativeValidationReport: ...
def run_graph_validation(spec: GenerativeCADSpec) -> GenerativeValidationReport: ...
```

### 9.3 Hard requirements

- Unknown base => error.
- Unknown op => error.
- Op not supported by selected base => error.
- Phase mismatch => error.
- DAG cycle => error.
- `depends_on` reference missing => error.
- Node `params` failing op Pydantic model => error.
- Safety flag missing or false => error.
- LLM validation hints cannot override system validation contract.

---

## 10. Geometry Preflight: `generative_cad/preflight.py`

Preflight is a lightweight geometric reasoner that runs before CadQuery/OpenCascade.

It prevents obvious kernel failures and catches LLM hallucinated dimensions before runtime.

### 10.1 Global policy

```python
DEFAULT_GEOMETRY_POLICY = {
    "min_edge_length_mm": 0.25,
    "min_wall_thickness_mm": 1.0,
    "min_boolean_clearance_mm": 0.2,
    "min_hole_to_boundary_margin_mm": 1.0,
    "max_fillet_ratio_to_local_thickness": 0.25,
    "max_nodes": 64,
    "max_boolean_ops": 256,
    "max_profile_points": 128,
}
```

### 10.2 Axisymmetric preflight checks

For `axisymmetric_base` implement:

- `revolve_profile`
  - all radii > 0
  - all `z_front_mm <= z_rear_mm`
  - at least 2 stations
  - max radius derivable
  - axial width derivable
  - min axial thickness not below threshold
  - station labels optional, not semantically trusted

- `cut_center_bore`
  - bore radius < outer radius
  - bore radius > 0
  - axis == revolve axis

- `cut_circular_hole_pattern`
  - `count >= 2`
  - hole radius > 0
  - PCD radius + hole radius <= outer radius - margin
  - PCD radius - hole radius >= bore radius + margin, if bore exists
  - angular spacing leaves positive ligament approximately:
    `2 * pi * pcd_radius / count - hole_dia_mm >= min_wall_thickness_mm`

- `cut_rim_slot_pattern`
  - slot count >= 2
  - slot depth > 0
  - slot depth <= available radial rim thickness - margin, if rim region inferred
  - station depth monotonic increasing
  - half widths > 0
  - min segment length >= min_edge_length_mm
  - station polygon area > small epsilon

### 10.3 Preflight report

Preflight must return structured issues, not strings.

Example:

```json
{
  "ok": false,
  "stage": "geometry_preflight",
  "issues": [
    {
      "code": "hole_pattern_outside_material",
      "message": "PCD radius + hole radius exceeds inferred outer radius margin.",
      "node_id": "lightening_holes",
      "expected": "<= 259.0",
      "actual": 278.0,
      "severity": "error"
    }
  ]
}
```

---

## 11. Runner Design: `generative_cad/runner.py`

The runner executes feature graphs through registered base operation handlers.

### 11.1 Fixed harness

Builder writes a small harness script only:

```python
from seekflow_engineering_tools.generative_cad.runner import run_generative_cad_from_files

run_generative_cad_from_files(
    graph_path=r".../input.gcad.json",
    out_step=r".../output.step",
    metadata_path=r".../output.metadata.json",
)
```

The harness must never contain LLM-generated CadQuery code.

### 11.2 Runtime context

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class GenerativeBuildContext:
    out_step: Path
    metadata_path: Path
    workspace_root: Path
    bodies: dict[str, Any] = field(default_factory=dict)
    active_body_id: str | None = None
    frames: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    degraded_features: list[dict[str, Any]] = field(default_factory=list)
    operation_metrics: list[dict[str, Any]] = field(default_factory=list)
```

### 11.3 Postconditions

After each operation, if possible, record:

```text
bbox
volume
solid count
operation status
warnings
```

For cut operations, if volume does not decrease by a meaningful epsilon, fail unless the operation is optional and its degradation policy allows skipping.

For add operations, if volume does not increase, fail unless optional.

### 11.4 Required failure behaviour

- Required node failure => whole build fails.
- Optional node failure with `may_skip_with_warning` => skip node, record warning and metadata entry.
- Unknown node/op => should never reach runner; if it does, fail hard.
- Shape invalid or empty => fail.
- STEP export failure => fail.
- Metadata write failure => fail.

---

## 12. Axisymmetric Base v0

Path:

```text
generative_cad/bases/axisymmetric/
```

### 12.1 Operation models: `models.py`

Implement Pydantic models.

```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class ProfileStation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    r_mm: float = Field(gt=0)
    z_front_mm: float
    z_rear_mm: float
    label: str | None = None

    @model_validator(mode="after")
    def validate_z(self):
        if self.z_front_mm > self.z_rear_mm:
            raise ValueError("z_front_mm must be <= z_rear_mm")
        return self

class RevolveProfileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    axis: Literal["Z"] = "Z"
    profile_stations: list[ProfileStation] = Field(min_length=2)

class CutCenterBoreParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diameter_mm: float = Field(gt=0)
    axis: Literal["Z"] = "Z"
    through_all: bool = True

class CutAnnularGrooveParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    side: Literal["front", "rear"]
    inner_dia_mm: float = Field(gt=0)
    outer_dia_mm: float = Field(gt=0)
    depth_mm: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_dia(self):
        if self.inner_dia_mm >= self.outer_dia_mm:
            raise ValueError("inner_dia_mm must be < outer_dia_mm")
        return self

class CutCircularHolePatternParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(ge=2, le=240)
    pcd_mm: float = Field(gt=0)
    hole_dia_mm: float = Field(gt=0)
    axis: Literal["Z"] = "Z"
    through_all: bool = True

class SlotProfileStation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    depth_mm: float = Field(ge=0)
    half_width_mm: float = Field(gt=0)

class RimSlotProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["symmetric_station_profile"] = "symmetric_station_profile"
    stations: list[SlotProfileStation] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_depth_order(self):
        depths = [s.depth_mm for s in self.stations]
        if depths != sorted(depths):
            raise ValueError("slot profile station depths must be nondecreasing")
        return self

class CutRimSlotPatternParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(ge=2, le=360)
    slot_depth_mm: float = Field(gt=0)
    slot_profile: RimSlotProfile

class ApplySafeChamferParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    distance_mm: float = Field(gt=0)
    target: Literal["all_external_edges"] = "all_external_edges"
```

### 12.2 Axisymmetric runner operation list

MVP ops:

```text
revolve_profile
cut_center_bore
cut_annular_groove
cut_circular_hole_pattern
cut_rim_slot_pattern
apply_safe_chamfer
```

Do not implement `make_turbine_disk`.

### 12.3 Important implementation note

Axisymmetric v0 does not need to match the current deterministic `axisymmetric_turbine_disk` primitive. It is a lower-trust generative grammar.

However, it may borrow small safe utility ideas, not internal primitive semantics.

Do not import the current turbine disk primitive kernel from this base. That would collapse the distinction between base and primitive.

---

## 13. Sketch Extrude Base v0

Path:

```text
generative_cad/bases/sketch_extrude/
```

MVP ops:

```text
extrude_rectangle
cut_rectangular_pocket
cut_hole
cut_hole_pattern_linear
add_rectangular_boss
add_rib
apply_safe_fillet
apply_safe_chamfer
```

Typical parts:

```text
brackets
mounting plates
blocks
clevis-like concept parts
adapter plates
```

Do not implement organic freeform shapes in this base.

---

## 14. Builder: `generative_cad/builder.py`

Implement this public function:

```python
def build_generative_cad_model(
    spec: GenerativeCADSpec,
    config: EngineeringToolsConfig,
    out_step: str | Path,
    inspect: bool = True,
    graph_out: str | Path | None = None,
    script_out: str | Path | None = None,
) -> dict:
    """Build a STEP file from GenerativeCADSpec using fixed runner harness.

    Returns EngineeringActionResult.model_dump().
    """
```

### 14.1 Builder steps

1. Resolve `out_step` with `ensure_inside_workspace`.
2. Enforce `.step` or `.stp` with `ensure_extension`.
3. Respect `config.allow_overwrite`.
4. Run `GenerativeCADSpec.model_validate` if input is dict at tool layer.
5. Run graph validation.
6. Run geometry preflight.
7. Write graph JSON inside workspace.
8. Write fixed runner script inside workspace `.generative_cad_scripts/`.
9. Execute runner via `subprocess.run([sys.executable, script_path], ...)` with timeout from `spec.system_validation_contract.max_runtime_seconds`.
10. Assert STEP exists and non-empty.
11. Assert metadata exists and non-empty.
12. Validate generative metadata.
13. If `inspect=True`, call `inspect_step_with_cadquery`.
14. Validate artifact against `SystemValidationContract`.
15. Write validation result back into metadata.
16. Return `EngineeringActionResult` with files created and metrics.

### 14.2 Do not call existing `build_cadquery_from_cad_ir`

That function is for `CADPartSpec`.

Do not shoehorn `GenerativeCADSpec` into it.

### 14.3 Reuse helper pattern

Create local equivalent of current `assert_file_created` if not importable.

Return errors in `EngineeringActionResult` with repair diagnostics under `metrics["repair"]`.

---

## 15. Metadata: `generative_cad/metadata.py`

Metadata sidecar path:

```text
output.step -> output.metadata.json
```

Top-level structure:

```json
{
  "generative_metadata": {
    "metadata_version": "generative_metadata_v1",
    "source_route": "llm_skill_base",
    "trust_level": "reference_geometry",
    "part_name": "...",
    "base_stack": [
      {"base_id": "axisymmetric_base", "base_version": "0.1.0"}
    ],
    "skill_stack": [
      {"skill_id": "turbomachinery_reference_skill", "skill_version": "0.1.0"}
    ],
    "feature_graph_hash": "sha256:...",
    "base_contract_hashes": {
      "axisymmetric_base": "sha256:..."
    },
    "runner_version": "0.1.0",
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
    "graph_validation": {},
    "geometry_preflight": {},
    "inspection_validation": {}
  }
}
```

### 15.1 Validation requirements

Implement:

```python
def validate_generative_metadata_v1(metadata: dict) -> dict:
    ...
```

It returns:

```json
{"ok": true, "issues": []}
```

or:

```json
{"ok": false, "issues": [{"code": "...", "message": "..."}]}
```

Required checks:

- top-level `generative_metadata` exists and is dict.
- `metadata_version == "generative_metadata_v1"`.
- `source_route == "llm_skill_base"`.
- `trust_level` in `concept_geometry`, `reference_geometry`.
- `base_stack` is non-empty list.
- `feature_graph_hash` starts with `sha256:`.
- safety flags exist and are all true.
- `build_warnings` exists and is list.
- `validation` exists and is dict.

---

## 16. Artifact Validation

Create:

```text
generative_cad/validation.py
```

Implement:

```python
def validate_artifact_against_generative_contract(
    inspection: dict,
    spec: GenerativeCADSpec,
) -> dict:
    ...
```

Do not reuse `validate_inspection_against_spec` directly because it expects `CADPartSpec`.

Checks:

- if `require_closed_solid` true, approximate by `solid_count == expected_body_count`; note that CadQuery inspector currently exposes `solid_count`, not full topological closedness.
- `expected_body_count` matches `solid_count` when available.
- if `expected_bbox_mm` exists, compare to `bbox_mm` using `bbox_tolerance_mm`.
- if inspector returns error, fail.

Return:

```json
{
  "ok": true,
  "issues": []
}
```

or issues.

---

## 17. Tools: `generative_cad/tools.py`

Add new SeekFlow tools, but do not modify existing CadQuery tools except registering these new tools in top-level `registry.py`.

### 17.1 Tool list

1. `generative_cad_list_bases`
2. `generative_cad_get_base_contract`
3. `generative_cad_validate_ir`
4. `generative_cad_build_from_ir`

### 17.2 Tool policies

Follow current tool patterns.

Read tools:

```text
capabilities={"cad.generative.read"}
risk="read"
timeout_s=30
parallel_safe=True
```

Build tool:

```text
capabilities={"cad.generative.write", "filesystem.write"}
risk="write"
timeout_s=180
workspace_root=config.workspace_root
path_params=frozenset({"out_step"})
parallel_safe=False
requires_approval=False
idempotent=False
```

### 17.3 Tool implementation pattern

```python
def build_generative_cad_tools(config):
    tools = []
    ...
    return tools
```

Then update:

```text
seekflow_engineering_tools/registry.py
```

Add import:

```python
from seekflow_engineering_tools.generative_cad.tools import build_generative_cad_tools
```

Add capabilities:

```python
"cad.generative.read",
"cad.generative.write",
```

Add registration:

```python
tools.extend(build_generative_cad_tools(config))
```

This is the only top-level integration needed in v0.

---

## 18. Capabilities Registry

Do not alter existing backend support logic for `CADPartSpec`.

Optionally add a separate function in:

```text
generative_cad/registry.py
```

or new file:

```text
generative_cad/capabilities.py
```

```python
GENERATIVE_CAPABILITIES = {
    "cadquery": {
        "stable_bases": ["axisymmetric_base", "sketch_extrude_base"],
        "strategy": "native_generative_runner_to_step",
        "exports": ["step"],
    },
    "solidworks2025": {
        "stable_bases": [],
        "strategy": "cadquery_step_import_only_after_artifact_validation",
    },
    "nx12": {
        "stable_bases": [],
        "strategy": "cadquery_step_import_only_after_artifact_validation",
    },
}
```

Do not put generative bases into `stable_primitives`.

Do not put generative bases into `primitive_strategy`.

---

## 19. Repair Governor: `generative_cad/repair_governor.py`

Do not implement a free-form infinite repair loop.

Implement deterministic repair state tracking.

### 19.1 Data models

```python
class RepairPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_node: str
    changes: list[dict]
    reason: str

class RepairState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempts: int = 0
    max_attempts: int = 3
    graph_hashes: list[str] = Field(default_factory=list)
    error_signature_hashes: list[str] = Field(default_factory=list)
    last_stage_rank: int = 0
```

### 19.2 Stop conditions

Stop repair if:

- attempts >= max_attempts
- graph hash repeated
- same error signature repeated twice
- repair tries to modify `safety`
- repair tries to modify `system_validation_contract`
- repair tries to modify `selected_bases` after graph generation stage
- repair introduces unknown base/op
- repair stage rank regresses twice
- repair does not reduce issue count

### 19.3 Allowed repair scope

The LLM may only produce JSON patch-like changes under:

```text
/feature_graph/nodes/<node_id>/params/...
/feature_graph/nodes/<node_id>/depends_on
/feature_graph/nodes/<node_id>/required
/feature_graph/nodes/<node_id>/degradation_policy
```

It may not modify:

```text
ir_version
generation_route
selected_bases
system_validation_contract
safety
metadata
runner
base contract
```

### 19.4 Initial v0 behaviour

In v0, implement repair diagnostics and patch application, but do not automatically call an LLM from inside the engineering tool. The tool should return diagnostics for an external orchestrator.

---

## 20. Prompt Contracts for LLM

Add:

```text
generative_cad/prompts.py
```

### 20.1 Base selection prompt

```python
BASE_SELECTION_SYSTEM_PROMPT = """
You are a CAD grammar routing assistant. Your task is to choose which registered CAD grammar bases can express the user's requested mechanical part.

Rules:
- You must only choose bases listed in the provided Base Catalog.
- Do not invent base_id values.
- If no listed base can express the part, return unsupported_by_current_base_catalog=true and list missing capabilities.
- Do not output CAD code.
- Do not output CadQuery, SolidWorks COM, NXOpen, APDL, or Python code.
- Do not claim manufacturing-ready, certified, airworthy, production-ready, or installable status.
- Output only JSON matching the requested schema.
"""
```

Expected output schema:

```json
{
  "part_intent": {
    "object_type": "string",
    "dominant_geometry": "string"
  },
  "selected_bases": [
    {
      "base_id": "string",
      "base_version": "string",
      "reason": "string"
    }
  ],
  "selected_skills": [
    {
      "skill_id": "string",
      "skill_version": "string",
      "reason": "string"
    }
  ],
  "unsupported_by_current_base_catalog": false,
  "missing_capabilities": []
}
```

### 20.2 Feature graph prompt

```python
FEATURE_GRAPH_SYSTEM_PROMPT = """
You are a Generative CAD-IR author. Your task is to write a feature graph for the selected CAD grammar bases.

Rules:
- You must output only GenerativeCADSpec JSON.
- Use only selected base_id values.
- Use only operations listed in the selected Base Contract.
- Do not invent operation names.
- Do not output natural-language modelling steps outside JSON.
- Do not output Python or CadQuery code.
- Do not control file paths, imports, exports, subprocesses, metadata writing, or validation pass/fail decisions.
- system_validation_contract must not be weakened. require_step_file, require_metadata_sidecar, and require_closed_solid must remain true.
- safety flags must all remain true.
- Use depends_on only for existing node ids.
- Prefer feature graph freedom through operation selection, feature count, layout, profiles, sections, and pattern parameters.
- If the requested part cannot be represented with the selected base contract, output an error object instead of inventing unsupported operations.
"""
```

### 20.3 Repair prompt

```python
GENERATIVE_REPAIR_PROMPT = """
The Generative CAD build failed. You may only return a local repair patch.

Rules:
- Do not rewrite the entire graph.
- Do not change selected_bases.
- Do not change system_validation_contract.
- Do not change safety flags.
- Do not invent new operations.
- Only modify the failed node params, depends_on, required, or degradation_policy if allowed.
- Return only JSON matching RepairPatch schema.
"""
```

---

## 21. Skill Files

### 21.1 `generic_mechanical_skill.md`

Include:

```markdown
# Generic Mechanical Skill v0.1

Use this skill to guide selection and construction of generic mechanical reference geometry.

## Base selection guidance
- Use `axisymmetric_base` for rotational parts: rings, disks, shafts, hubs, flanges, pulleys.
- Use `sketch_extrude_base` for prismatic machined parts: plates, brackets, blocks, lugs, mounting adapters.
- Do not choose a base that is not in the catalog.
- If no base can express the requested geometry, report missing capabilities.

## General modelling rules
- Prefer stable mechanical features: extrudes, cuts, bores, pockets, hole patterns, ribs, bosses, chamfers.
- Avoid unsupported organic freeform geometry.
- Do not invent operations.
- All units are mm.

## Safety
- Generative output is reference geometry only.
- Never claim production-ready, certified, or manufacturing-ready status.
```

### 21.2 `turbomachinery_reference_skill.md`

Include:

```markdown
# Turbomachinery Reference Skill v0.1

This skill is for non-flight, non-certified reference geometry only.

## Base selection guidance
- Use `axisymmetric_base` for rotating disks, rings, hubs, flanges, rotor-like reference bodies.
- Use `loft_sweep_base` only when it exists and the requested part is a blade, vane, duct, or swept aerodynamic feature.
- Do not model flight-ready or manufacturing-ready turbomachinery.

## Disk-like modelling guidance
- A rotating disk often has hub, web, and rim regions.
- The main body should usually be generated by `revolve_profile`.
- Central bores should be coaxial with the revolve axis.
- Bolt holes and lightening holes should use circular patterns.
- Rim slots may use `cut_rim_slot_pattern` if available.

## Safety requirements
- Always mark non_flight_reference_only=true.
- Always mark not_airworthy=true.
- Always mark not_certified=true.
- Always mark not_for_manufacturing=true.
- Always mark not_for_installation=true.
- Always mark no_structural_validation=true.
- Always mark no_life_prediction=true.
```

---

## 22. Integration With Existing Main Chain

### 22.1 Top-level tool registration

Modify only:

```text
seekflow_engineering_tools/registry.py
```

Add capabilities:

```python
"cad.generative.read",
"cad.generative.write",
```

Register generative tools after CadQuery and natural language tools:

```python
tools.extend(build_cadquery_tools(config))
tools.extend(build_natural_language_tools(config))
tools.extend(build_generative_cad_tools(config))
```

This does not affect existing tools.

### 22.2 No changes to CADPartSpec v0

Do not modify:

```text
ir/cad.py
```

except if absolutely necessary for import typing, but v0 should require no changes.

### 22.3 No changes to primitive compiler

Do not modify:

```text
cadquery_backend/primitive_compiler.py
```

### 22.4 No changes to primitive validators

Do not modify:

```text
mechanical_validation/common.py
mechanical_validation/primitive_metadata.py
geometry_primitives/turbomachinery/*
geometry_primitives/gears/*
```

### 22.5 Existing backend import

In v0, the generative path produces CadQuery STEP only.

Do not implement SolidWorks/NX native rebuild.

If downstream import is added later, it must import the validated STEP artifact only.

---

## 23. Required Tests

### 23.1 `test_generative_cad_ir.py`

Test:

- minimal valid `GenerativeCADSpec` validates.
- missing selected_bases fails.
- node base not in selected_bases fails.
- safety flag false fails.
- `system_validation_contract.require_step_file=false` fails.
- extra unknown field fails.

### 23.2 `test_generative_base_registry.py`

Test:

- `axisymmetric_base` is registered.
- `sketch_extrude_base` is registered.
- `export_base_catalog()` returns both.
- duplicate base registration fails.
- part-specific base naming fails.
- every op in manifest exists in contract/runner.

### 23.3 `test_generative_graph_validation.py`

Test fail-closed for:

- unknown base.
- unknown op.
- op not in selected base.
- invalid phase.
- missing depends_on.
- DAG cycle.
- params schema error.
- attempt to use arbitrary code field.

### 23.4 `test_generative_preflight.py`

Axisymmetric invalid cases:

- hole outside outer radius.
- hole intersects bore.
- PCD hole ligament too small.
- rim slot too deep.
- slot station depths non-monotonic.
- profile station z inverted.

### 23.5 `test_generative_builder.py`

Test:

- valid axisymmetric graph builds STEP.
- metadata sidecar exists.
- artifact descriptor returned.
- inspection metrics present when CadQuery available.
- invalid graph fails before subprocess.
- no output outside workspace.
- overwrite respected.

### 23.6 `test_generative_metadata.py`

Test:

- valid metadata passes.
- missing `generative_metadata` fails.
- missing safety fails.
- false safety fails.
- missing base_stack fails.
- missing feature_graph_hash fails.
- missing build_warnings fails.

### 23.7 `test_generative_repair_governor.py`

Test:

- repeated graph hash stops.
- repeated error signature stops.
- forbidden safety modification rejected.
- forbidden validation contract modification rejected.
- attempts over max rejected.
- repair patch to node params accepted.

### 23.8 `test_generative_no_main_chain_pollution.py`

Test:

- `CADPartSpec` still rejects `type="generative"`.
- `PRIMITIVE_REGISTRY` does not contain generative bases.
- `CAPABILITIES["cadquery"]["stable_primitives"]` does not contain generative bases.
- existing `cadquery_build_from_cad_ir` still builds a simple existing CAD-IR.

---

## 24. Demo Cases

Add:

```text
demo_generative_cad.py
```

### Demo 1: Axisymmetric reference disk

Graph:

```text
revolve_profile
cut_center_bore
cut_circular_hole_pattern
apply_safe_chamfer optional
```

Expected:

```text
STEP created
metadata created
artifact descriptor returned
body_count = 1 if inspection available
```

### Demo 2: Sketch extrude bracket

Graph:

```text
extrude_rectangle
cut_hole
add_rectangular_boss optional
apply_safe_chamfer optional
```

---

## 25. Claude Code Implementation Prompt

Use this prompt for Claude Code.

```text
You are implementing a new Generative CAD-IR path in `integrations/engineering_tools` of the SeekFlow Engineering repository.

Hard constraints:
1. Do not modify the existing deterministic primitive path semantics.
2. Do not modify `cadquery_backend/primitive_compiler.py`.
3. Do not add generative feature types to `ir/cad.py` in v0.
4. Do not add generative bases to primitive registries or primitive capabilities.
5. The LLM-facing generative path must output only JSON/Pydantic data, never CadQuery/Python/SolidWorks/NX/APDL code.
6. The build path must use a fixed runner harness that loads a graph JSON and calls registered base operation handlers. Do not dynamically generate large CadQuery scripts from the graph.
7. Unknown base or unknown op must fail closed. No fuzzy matching. No silent fallback.
8. Generative output trust level must not exceed `reference_geometry`.
9. Safety flags must be required and true.
10. The new path may merge into existing tooling only as a canonical STEP artifact with metadata, not as a primitive.

Implement the new package:
`seekflow_engineering_tools/generative_cad/`
with these modules:
- ir.py
- artifact.py
- base.py
- registry.py
- graph_validation.py
- preflight.py
- runner.py
- builder.py
- metadata.py
- validation.py
- repair_governor.py
- tools.py
- prompts.py
- bases/axisymmetric/*
- bases/sketch_extrude/*
- skills/*.md

Implement Pydantic models with `extra="forbid"`.

Implement two MVP bases:
1. `axisymmetric_base`
2. `sketch_extrude_base`

Implement a fixed runner script pattern:
`run_generative_cad_from_files(graph_path, out_step, metadata_path)`.

Update only top-level tool registration in `seekflow_engineering_tools/registry.py` to include generative tools and capabilities.

Add tests listed in the implementation document. The test suite must prove:
- valid generative graphs can build STEP;
- invalid graphs fail before execution;
- metadata is mandatory;
- repair governor stops loops;
- existing `CADPartSpec` and primitive paths are not polluted.

Run:
`python -m pytest tests -q`

If full CadQuery-dependent tests cannot run in the environment, keep tests skipped only with explicit `pytest.importorskip("cadquery")` and ensure non-CadQuery validation tests still run.
```

---

## 26. Acceptance Criteria

Implementation is acceptable only if all are true:

1. Existing deterministic CAD-IR tests pass.
2. Existing primitive tests pass.
3. New generative IR validates with strict Pydantic models.
4. Unknown generative base/op hard fails.
5. Valid axisymmetric generative graph can produce STEP when CadQuery is installed.
6. Generative metadata sidecar is mandatory.
7. Generative output returns `EngineeringActionResult`.
8. New tools are registered without changing existing tool names or behaviour.
9. `CADPartSpec` still rejects generative feature types.
10. `PRIMITIVE_REGISTRY` does not contain generative bases.
11. `CAPABILITIES[*].stable_primitives` does not contain generative bases.
12. Repair governor detects repeated graph/error and stops.
13. No generated runner script contains LLM-authored CadQuery logic.
14. No SolidWorks COM / NXOpen / APDL generation is added.
15. Generated artifacts are labelled `source_route="llm_skill_base"` and `trust_level="reference_geometry"`.

---

## 27. Why This Solves the Known Risks

### LLM hallucination

Solved by registry validation, base contract, JSON schema, and hard failure for unknown base/op.

### Base too strict becomes primitive

Solved by grammar-based base naming, generativity test, and prohibition against part-specific base names.

### Base too broad loses constraint

Solved by supported operation lists, op schemas, phase order, preconditions, postconditions, and resource limits.

### Base compilation uncertainty

Solved by replacing dynamic compilation with fixed harness + tested runner + op handlers.

### Generated script low-level errors

Solved because the generated script is only a fixed harness. Dynamic content is graph JSON, not Python code.

### Many-base combination complexity

Deferred in v0. v0 supports one owner base per graph. Future composition must use component graph + named frames + composition base.

### Repair loop infinite cycling

Solved by graph hash, error signature hash, max attempts, forbidden patch zones, and stage-rank monotonicity.

### Sliding back into primitive-only architecture

Solved by separating base grammar from primitives, preserving base as lower-trust exploration, and promoting only stable high-trust patterns into deterministic primitives.

---

## 28. Implementation Order

Implement in this order only:

1. `generative_cad/ir.py`
2. `generative_cad/artifact.py`
3. `generative_cad/base.py`
4. `generative_cad/bases/axisymmetric/models.py`
5. `generative_cad/bases/sketch_extrude/models.py`
6. `generative_cad/bases/*/manifest.py`
7. `generative_cad/bases/*/contract.py`
8. `generative_cad/registry.py`
9. `generative_cad/graph_validation.py`
10. `generative_cad/preflight.py`
11. `generative_cad/bases/*/preflight.py`
12. `generative_cad/runner.py`
13. `generative_cad/bases/*/runner.py`
14. `generative_cad/metadata.py`
15. `generative_cad/validation.py`
16. `generative_cad/builder.py`
17. `generative_cad/tools.py`
18. update `seekflow_engineering_tools/registry.py`
19. tests
20. demo
21. documentation

Do not implement prompts first. Prompts are not the system boundary. The system boundary is the schema/registry/validator/runner.

---

## 29. Final Architectural Statement

This implementation creates a third path in SeekFlow Engineering Tools:

```text
1. Deterministic primitive path: exact, high-trust, fixed kernels.
2. Recipe path: generic deterministic CAD features.
3. Generative CAD grammar path: LLM-authored feature graph, base-runner executed, lower-trust reference geometry.
```

The third path is deliberately isolated. It does not weaken the first two paths. It exists to explore LLM modelling freedom while retaining engineering safety, fail-closed behaviour, metadata provenance, artifact validation, and downstream compatibility.
