"""MetadataProofV3 — full provenance proof with paths, runtime, artifact hash, import policy.

Replaces v2.1 for production builds. v2.1 retained for compatibility tests.
"""

from __future__ import annotations

import hashlib, json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.pipeline.metadata import (
    REQUIRED_SAFETY_FLAGS,
    REQUIRED_VALIDATION_STAGES,
    normalize_validation_proof,
)
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext

# ── Pydantic proof models ──


class MetadataPathProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_ir_path: str
    validation_seed_path: str
    step_path: str
    metadata_path: str


class RuntimeProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runner_version: str
    geometry_runtime: str
    geometry_runtime_version: str


class ImportPolicyProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    native_rebuild_allowed: Literal[False]
    requires_import_gate: Literal[True]
    step_import_candidate: Literal[True]
    step_import_allowed: Literal[False]


class ArtifactHashProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_sha256: str
    metadata_schema_hash: str | None = None


class GenerativeMetadataV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata_version: Literal["generative_metadata_v3"]
    source_route: Literal["llm_skill_base"]
    schema_version: str
    canonical_version: str
    trust_level: Literal["concept_geometry", "reference_geometry"]

    document_id: str
    part_name: str

    selected_dialects: list[dict]
    op_versions: list[dict]

    raw_graph_hash: str
    canonical_graph_hash: str

    paths: MetadataPathProof
    runtime: RuntimeProof
    artifact: ArtifactHashProof
    import_policy: ImportPolicyProof

    repair_attempts: int = 0
    repair_patch_hashes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    degraded_features: list[dict] = Field(default_factory=list)
    operation_metrics: list[dict] = Field(default_factory=list)

    safety: dict


class MetadataProofV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generative_metadata: GenerativeMetadataV3
    build_warnings: list[str]
    validation: dict


# ── Builder ──


def _compute_step_sha256(step_path: Path) -> str:
    """Compute SHA256 of STEP file. Returns 'sha256:pending' if file not yet available."""
    try:
        return "sha256:" + hashlib.sha256(step_path.read_bytes()).hexdigest()
    except (FileNotFoundError, PermissionError, OSError):
        return "sha256:pending"
    # Fatal errors (MemoryError, etc.) propagate naturally


def build_generative_metadata_v3(
    *,
    canonical: CanonicalGcadDocument,
    ctx: RuntimeContext,
    validation: dict,
    canonical_ir_path: Path,
    validation_seed_path: Path,
    step_path: Path,
    metadata_path: Path,
    repair_summary: dict | None = None,
) -> dict:
    """Build MetadataProofV3 dict with full provenance proof."""
    normalized = normalize_validation_proof(validation)

    gm = GenerativeMetadataV3(
        metadata_version="generative_metadata_v3",
        source_route="llm_skill_base",
        schema_version=canonical.schema_version,
        canonical_version=canonical.canonical_version,
        trust_level=canonical.trust_level,
        document_id=canonical.document_id,
        part_name=canonical.part_name,
        selected_dialects=[
            {"dialect": d.dialect, "version": d.version, "contract_hash": d.contract_hash}
            for d in canonical.selected_dialects
        ],
        op_versions=[
            {"node_id": n.id, "dialect": n.dialect, "op": n.op, "op_version": n.op_version}
            for n in canonical.nodes
        ],
        raw_graph_hash=canonical.raw_graph_hash or "",
        canonical_graph_hash=canonical.canonical_graph_hash,
        paths=MetadataPathProof(
            canonical_ir_path=str(canonical_ir_path),
            validation_seed_path=str(validation_seed_path),
            step_path=str(step_path),
            metadata_path=str(metadata_path),
        ),
        runtime=RuntimeProof(
            runner_version=ctx.runner_version,
            geometry_runtime=ctx.geometry_runtime_name,
            geometry_runtime_version=ctx.geometry_runtime.runtime_version,
        ),
        artifact=ArtifactHashProof(
            step_sha256=_compute_step_sha256(step_path),
        ),
        import_policy=ImportPolicyProof(
            native_rebuild_allowed=False,
            requires_import_gate=True,
            step_import_candidate=True,
            step_import_allowed=False,
        ),
        repair_attempts=repair_summary.get("attempts", 0) if repair_summary else 0,
        repair_patch_hashes=repair_summary.get("patch_hashes", []) if repair_summary else [],
        warnings=list(ctx.warnings),
        degraded_features=list(ctx.degraded_features),
        operation_metrics=list(ctx.operation_metrics),
        safety=canonical.safety.model_dump(),
    )

    proof = MetadataProofV3(
        generative_metadata=gm,
        build_warnings=list(ctx.warnings),
        validation=normalized,
    )

    return json.loads(proof.model_dump_json())


# ── Validator ──


def validate_generative_metadata_v3(
    metadata: dict,
    *,
    canonical: CanonicalGcadDocument | None = None,
    registry=None,
    require_validation_ok: bool = False,
    require_final_artifact_hash: bool = True,
) -> dict:
    """Validate MetadataProofV3. Returns {"ok": bool, "issues": list[dict]}."""
    issues: list[dict] = []

    gm = metadata.get("generative_metadata", {})
    if not isinstance(gm, dict):
        return {"ok": False, "issues": [{"code": "missing_generative_metadata", "message": "generative_metadata must be a dict"}]}

    # Version — accept v2 and v3
    mver = gm.get("metadata_version", "")
    if mver not in ("generative_metadata_v2", "generative_metadata_v3"):
        issues.append({"code": "invalid_metadata_version", "message": "metadata_version must be generative_metadata_v2 or generative_metadata_v3"})

    # source_route
    if gm.get("source_route") != "llm_skill_base":
        issues.append({"code": "invalid_source_route", "message": "source_route must be llm_skill_base"})

    # trust_level
    if gm.get("trust_level") not in ("concept_geometry", "reference_geometry"):
        issues.append({"code": "trust_level_too_high", "message": f"trust_level {gm.get('trust_level')!r} exceeds reference_geometry"})

    # selected_dialects
    dialects = gm.get("selected_dialects")
    if not isinstance(dialects, list) or not dialects:
        issues.append({"code": "empty_selected_dialects", "message": "selected_dialects must be non-empty"})
    else:
        for d in dialects:
            if not isinstance(d.get("contract_hash"), str) or not d["contract_hash"].startswith("sha256:"):
                issues.append({"code": "missing_dialect_contract_hash", "message": f"dialect {d.get('dialect')} missing valid contract_hash"})

    # graph hashes
    for hk in ("raw_graph_hash", "canonical_graph_hash"):
        val = gm.get(hk, "")
        if not isinstance(val, str) or not val.startswith("sha256:"):
            issues.append({"code": f"invalid_{hk}", "message": f"{hk} must be sha256:..."})

    # paths — v3 only
    paths = gm.get("paths")
    if mver == "generative_metadata_v3":
        if isinstance(paths, dict):
            for pk in ("canonical_ir_path", "validation_seed_path", "step_path", "metadata_path"):
                if not paths.get(pk):
                    issues.append({"code": f"missing_path_{pk}", "message": f"paths.{pk} is required"})
        else:
            issues.append({"code": "missing_paths", "message": "paths proof is required"})

    # runtime — v3 only
    runtime = gm.get("runtime")
    if mver == "generative_metadata_v3":
        if isinstance(runtime, dict):
            if not runtime.get("runner_version"):
                issues.append({"code": "missing_runner_version", "message": "runtime.runner_version is required"})
            if not runtime.get("geometry_runtime"):
                issues.append({"code": "missing_geometry_runtime", "message": "runtime.geometry_runtime is required"})
            if not runtime.get("geometry_runtime_version"):
                issues.append({"code": "missing_geometry_runtime_version", "message": "runtime.geometry_runtime_version is required"})
        else:
            issues.append({"code": "missing_runtime", "message": "runtime proof is required"})

    # artifact — v3 only
    artifact = gm.get("artifact")
    if mver == "generative_metadata_v3":
        if isinstance(artifact, dict):
            step_hash = artifact.get("step_sha256", "")
            if not isinstance(step_hash, str) or not step_hash.startswith("sha256:"):
                issues.append({"code": "invalid_step_sha256", "message": "artifact.step_sha256 must be sha256:..."})
            if require_final_artifact_hash and step_hash == "sha256:pending":
                issues.append({"code": "step_sha256_pending", "message": "artifact.step_sha256 is still pending"})
            # Verify against file if path exists
            if step_hash not in ("sha256:pending", "") and paths and paths.get("step_path"):
                sp = Path(paths["step_path"])
                if sp.exists():
                    actual = "sha256:" + hashlib.sha256(sp.read_bytes()).hexdigest()
                    if actual != step_hash:
                        issues.append({"code": "step_sha256_mismatch", "message": f"artifact.step_sha256 {step_hash} does not match file"})
        else:
            issues.append({"code": "missing_artifact", "message": "artifact hash proof is required"})

    # import_policy — v3 only
    policy = gm.get("import_policy")
    if mver == "generative_metadata_v3":
        if isinstance(policy, dict):
            if policy.get("native_rebuild_allowed") is not False:
                issues.append({"code": "native_rebuild_not_false", "message": "import_policy.native_rebuild_allowed must be False"})
            if policy.get("requires_import_gate") is not True:
                issues.append({"code": "requires_import_gate_not_true", "message": "import_policy.requires_import_gate must be True"})
            if policy.get("step_import_allowed") is not False:
                issues.append({"code": "step_import_allowed_not_false", "message": "import_policy.step_import_allowed must be False"})
        else:
            issues.append({"code": "missing_import_policy", "message": "import_policy proof is required"})

    # safety
    safety = gm.get("safety", {})
    for flag in REQUIRED_SAFETY_FLAGS:
        if safety.get(flag) is not True:
            issues.append({"code": f"safety_{flag}_false", "message": f"Safety flag {flag} must be true"})

    # validation
    val = metadata.get("validation", {})
    if not isinstance(val, dict):
        issues.append({"code": "missing_validation", "message": "validation proof is required"})
    else:
        for stage in REQUIRED_VALIDATION_STAGES:
            stage_val = val.get(stage)
            if not isinstance(stage_val, dict):
                issues.append({"code": f"missing_{stage}", "message": f"validation.{stage} is required"})
            elif require_validation_ok and stage_val.get("ok") is not True:
                issues.append({"code": f"{stage}_not_ok", "message": f"validation.{stage}.ok must be true"})

    # Registry check
    if registry is not None and dialects:
        for d in dialects:
            try:
                expected = registry.contract_hash(d["dialect"])
                if d["contract_hash"] != expected:
                    issues.append({"code": "contract_hash_mismatch", "message": f"dialect {d['dialect']}: expected {expected}, got {d['contract_hash']}"})
            except Exception as exc:
                issues.append({"code": "unknown_metadata_dialect", "message": str(exc)})

    # Canonical cross-check
    if canonical is not None:
        if gm.get("canonical_graph_hash") != canonical.canonical_graph_hash:
            issues.append({"code": "canonical_graph_hash_mismatch", "message": "metadata canonical_graph_hash != canonical.canonical_graph_hash"})

    return {"ok": len(issues) == 0, "issues": issues}
