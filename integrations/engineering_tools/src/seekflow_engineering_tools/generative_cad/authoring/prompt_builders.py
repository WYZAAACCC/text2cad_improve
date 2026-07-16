"""Staged prompt builders for LLM authoring pipeline.

Each stage has a dedicated system prompt and user prompt builder.
The LLM is constrained to make only design decisions — the system handles
op_version, outputs, inputs, root_node, safety, constraints, and wiring.

Reference: lm_skill_base19.md §7
"""

from __future__ import annotations

import json
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# System Prompts
# ═══════════════════════════════════════════════════════════════════════════════

ROUTE_SYSTEM_PROMPT = """\
You are a CAD route planner for a constrained generative CAD compiler.

You must choose whether the request should be handled by the non-primitive
Generative CAD IR path.

You do not create CAD code.
You do not create RawGcadDocument.
You do not invent dialects, operations, parameter names, versions, or safety fields.
You only emit the tool arguments required by the strict schema.

Use the generative CAD IR route only when the requested shape can be
represented by the available dialects:
- axisymmetric: revolved solids, bores, grooves, circular holes, rim slots,
  threads, chamfers.
- sketch_extrude: rectangular plates/blocks, pockets, holes, linear hole
  patterns, bosses, ribs, safe fillets/chamfers.
- loft_sweep: 3D paths, pipe-like sweeps, simple loft sections, helices.
- shell_housing: shelling/hollowing an existing closed solid.
- sketch_profile: 2D sketch profiles and profile extrusion/cut.
- composition: assembly-level transforms, placement, boolean union/cut,
  patterns.

If the prompt asks for gears, involute teeth, bearings with rolling elements,
or other primitive-specific recipe objects, do not route them into this path
unless the user explicitly wants approximate reference geometry.

When uncertain, prefer the simplest reliable dialect combination.
Never select a dialect that is not registered in the provided context.
"""

FEATURE_SEQUENCE_SYSTEM_PROMPT = """\
You are a CAD feature-tree planner for a deterministic CAD compiler.

You must output only a high-level feature sequence draft.
You must not output operation parameters.
You must not output input references.
You must not output full RawGcadDocument.
The system assembler will fill op_version, outputs, inputs, root_node, safety,
constraints, and wiring.

Plan like a SolidWorks/NX feature tree:
1. Create a base solid first.
2. Apply subtractive cuts after the base solid exists.
3. Apply ribs/bosses after the base solid exists.
4. Apply edge treatments after main shape features.
5. Use shell only after a closed base solid exists.
6. Use composition only in the __assembly__ component to combine completed
   component solids.

Do not use boolean_union to create leaf features such as ribs, bosses, plates,
holes, or pockets. Use boolean_union only to combine completed component solids.

For sweep/loft workflows:
- create_sweep_path outputs a curve.
- sweep_profile consumes the latest curve and outputs a solid.
- sketch/profile operations output sketch/profile/solid in sequence.
The assembler handles these typed references. Do not write references manually.

For 3+ body assemblies: emit one high-level assembly boolean_union intent node;
the assembler will expand it into pairwise union operations.

If a requested object exceeds available dialect capability, create the closest
conservative reference geometry and state assumptions.
"""

NODE_PARAMS_SYSTEM_PROMPT = """\
You are filling parameters for exactly one CAD feature node in a deterministic
feature-tree compiler.

You must emit only the strict tool arguments.
You must not change node_id, dialect, op, or op_version.
You must not add fields outside the strict schema.
You must not invent parameter names.
You must not include input references.
You must not include outputs.
You must not include safety or constraints.

Use millimeters for all length values unless the schema explicitly says otherwise.
Use degrees for angular values unless the schema explicitly says otherwise.
Prefer conservative dimensions that produce a closed, non-self-intersecting solid.

For subtractive features:
- Keep cuts within the base solid unless the operation explicitly allows
  through cuts.
- Hole centers must lie inside the parent face.
- Pocket depth must be less than base thickness unless through-cut is intended.

For ribs and bosses:
- Place them on or inside the base footprint.
- Do not create floating features.

For helix_sweep:
- turns must be positive.
- radius_mm is the centerline radius.
- profile_radius_mm is the swept wire/tube radius.
- height_mm is the total axial height.
- pitch_mm * turns should approximately equal height_mm if both are present.
- pitch_mm should be at least 2.2 * profile_radius_mm to avoid self-intersection.

For shell:
- thickness_mm must be positive.
- thickness_mm must be less than 40% of the smallest base dimension.

For axisymmetric revolve_profile:
- profile_stations describe the OUTER contour only — each Z position has exactly
  ONE radius (the maximum radius at that Z).
- z_rear_mm must be STRICTLY GREATER than z_front_mm (zero-width stations are
  forbidden and will be rejected by validation).
- Express Hub and Rim as continuous outer contour segments. The web is the
  transition zone between hub and rim — NOT a cut_annular_groove side recess.
  Example: r=1 Z=0->5 | r=30 Z=5->35 | r=100 Z=0->40 | r=1 Z=35->40.
- DO NOT use cut_annular_groove to create web/bore recess — that creates an
  unrealistic empty cavity in the disk body.
- DO NOT model an hourglass shape (narrow middle, wide ends).

For cut_rim_slot_pattern fir-tree slots:
- half_width MUST alternate wide (lobe) / narrow (neck) to create mechanical undercuts.
  A monotonically decreasing half_width produces a stepped V-shape, NOT a fir-tree.
  CORRECT: [8, 5, 7, 3] → lobe 8mm → neck 5mm → lobe 7mm(undercut!) → root 3mm.
  WRONG:   [7, 5, 4] → monotonic taper, no undercut, blade cannot lock.
- The undercut is created when a deeper station has LARGER half_width than the station
  above it (e.g., neck hw=5, next lobe hw=7 where 7 > 5).
- Typical turbine disk: 2-3 lobes alternating wide/narrow, ending with narrow root.

IR CAPABILITY BOUNDARIES (must respect):
- The IR can only represent what the registered dialects support. Do NOT
  attempt to model features outside the selected dialects' capability.
- axisymmetric: ONLY rotationally symmetric solids. Non-axisymmetric
  features (blades, cooling holes, asymmetrical pockets) are NOT
  representable — output closest conservative reference geometry and
  state assumptions.
- revolve_profile describes ONLY the outer contour. Internal features
  (bores, grooves, slots) must use their dedicated cut_* operations.
- cut_rim_slot_pattern produces fir-tree/slot profiles on the OUTER
  circumference only. Internal cooling channels are NOT supported.
- If the user requests unsupported features, output the closest
  representable geometry and add a note in llm_validation_hints.

TRUST LEVEL & SAFETY (mandatory):
- All generative output is reference_geometry or concept_geometry — NEVER
  manufacturing-ready, airworthy, or certified.
- trust_level must be one of: concept_geometry, reference_geometry.
  Do NOT output higher trust levels (e.g. production, certified).
- All 7 safety flags must be explicitly true:
  non_flight_reference_only, not_airworthy, not_certified,
  not_for_manufacturing, not_for_installation, no_structural_validation,
  no_life_prediction.
- The system fills safety/constraints fields — do NOT output them in
  node params. But understand that your geometry is reference-only.
"""

REPAIR_SYSTEM_PROMPT = """\
You are a local CAD IR repair agent.

You may only produce a minimal repair patch for the validation issues shown.
Do not change the design intent.
Do not change schema_version.
Do not change safety flags.
Do not change dialect/op unless the validation issue explicitly says the
dialect/op is invalid.
Do not delete nodes unless the issue explicitly says the node is impossible to
repair.
Do not use destructive cleanup to make validation pass.

Prefer fixing:
- enum aliases;
- missing required params when the value is implied;
- unit field names;
- small numeric values that violate obvious preflight constraints;
- wrong output names when type is known.

Give up when:
- the requested geometry cannot be represented by the selected dialects;
- a missing input requires changing feature order;
- the repair would require inventing design intent;
- multiple incompatible fixes are possible.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Prompt builders
# ═══════════════════════════════════════════════════════════════════════════════

def compact_json(obj: Any) -> str:
    """Serialize an object to compact JSON (stable key order, no whitespace waste)."""
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_route_user_prompt(user_request: str, dialect_summary: str = "") -> str:
    """Build the user prompt for the route planning stage.

    Args:
        user_request: The user's natural language part description.
        dialect_summary: A summary of available dialects and their capabilities.
    """
    return f"""USER REQUEST:
{user_request}

AVAILABLE DIALECTS AND CAPABILITIES:
{dialect_summary}

Return only the strict tool call arguments.
The selected route must be conservative and buildable.
"""


def build_feature_sequence_user_prompt(
    user_request: str,
    route_plan: Any,
    ctx: Any,
    operation_summary: str = "",
) -> str:
    """Build the user prompt for the feature sequence stage.

    Args:
        user_request: The original user request.
        route_plan: The RoutePlan from stage 1.
        ctx: The AuthoringContext with selected dialects and contracts.
        operation_summary: Summary of allowed operations per dialect.
    """
    return f"""USER REQUEST:
{user_request}

ROUTE PLAN:
{compact_json(route_plan)}

AUTHORING CONTEXT:
{compact_json(ctx)}

ALLOWED OPERATIONS:
{operation_summary}

PLANNING REQUIREMENTS:
- Use only allowed dialects and ops.
- Do not include params.
- Do not include inputs.
- Keep component ids stable and descriptive.
- Include __assembly__ only when multiple completed component solids must be
  combined or transformed.

Return only the strict tool call arguments.
"""


def build_node_params_user_prompt(
    user_request: str,
    route_plan: Any,
    feature_sequence: Any,
    node_plan: Any,
    op_contract: str = "",
    design_intent: Any = None,
) -> str:
    """Build the user prompt for a single node's params.

    Args:
        user_request: The original user request.
        route_plan: The RoutePlan from stage 1.
        feature_sequence: The FeatureSequenceDraft from stage 2.
        node_plan: The NodePlanDraft for the current node.
        op_contract: The operation contract (params schema, constraints).
        design_intent: Optional extracted design intent metrics.
    """
    return f"""USER REQUEST:
{user_request}

ROUTE PLAN:
{compact_json(route_plan)}

CURRENT NODE:
{compact_json(node_plan)}

OPERATION CONTRACT:
{op_contract}

FEATURE SEQUENCE:
{compact_json(feature_sequence)}

KNOWN DESIGN INTENT:
{compact_json(design_intent) if design_intent else "No design intent extracted."}

Return only the strict tool call arguments for this one node.
"""


def build_repair_user_prompt(
    current_doc: dict,
    validation_issues: list[dict],
    repairable_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
) -> str:
    """Build the user prompt for the repair stage.

    Args:
        current_doc: The current RawGcadDocument dict.
        validation_issues: List of validation issues to fix.
        repairable_paths: Paths that the repair agent may modify.
        forbidden_paths: Paths the repair agent must not touch.
    """
    return f"""VALIDATION ISSUES:
{compact_json(validation_issues)}

REPAIRABLE PATHS:
{compact_json(repairable_paths or [])}

FORBIDDEN PATHS:
{compact_json(forbidden_paths or [
    "/schema_version", "/selected_dialects", "/safety",
    "/constraints/require_step_file", "/constraints/require_metadata_sidecar",
    "/constraints/require_closed_solid",
])}

CURRENT DOCUMENT:
{compact_json(current_doc)}

Return only the strict repair patch tool arguments.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Context summarizers — extract essential info from registry/context for prompt
# ═══════════════════════════════════════════════════════════════════════════════

def _build_dialect_summary(dialect_registry) -> str:
    """Build a compact summary of all registered dialects for the route prompt.

    Extracts dialect id, version, typical geometry, and unsupported cases from
    each registered dialect's BasePackage manifest.
    """
    lines: list[str] = []
    for did in dialect_registry.list_ids():
        d = dialect_registry.get(did)
        if d is None:
            continue
        lines.append(f"- {did} (v{d.version}): {getattr(d, 'summary', '')}")
        typical_geom = getattr(d, 'typical_geometry', None) or []
        if typical_geom:
            lines.append(f"  Typical geometry: {', '.join(typical_geom[:5])}")
    return "\n".join(lines) if lines else "(no dialects registered)"


def _build_operation_summary(ctx) -> str:
    """Build a compact summary of allowed operations per selected dialect.

    Extracts op names, phases, and short descriptions from each dialect's contract.
    Also includes examples and usage skills for few-shot guidance.
    """
    from seekflow_engineering_tools.generative_cad.skills.authoring_context import (
        pack_authoring_context,
    )

    parts: list[str] = []

    # ── Operation list per dialect ──
    for did in ctx.selected_dialects:
        contract = ctx.dialect_contracts.get(did, {})
        parts.append(f"## {did} — Allowed Operations")
        phases = contract.get("phase_order", [])
        if phases:
            parts.append(f"Phase order: {' → '.join(phases)}")
        allowed_ops = contract.get("allowed_ops", {})
        if allowed_ops:
            for op_name, op_info in allowed_ops.items():
                phase = op_info.get("phase", "?")
                desc = op_info.get("description", "")[:150]
                parts.append(f"- `{op_name}` [{phase}]: {desc}")
        parts.append("")

    # ── Usage skills + examples (few-shot) ──
    if ctx.level2_usage_skills or ctx.base_package_manifests:
        packed = pack_authoring_context(
            package_manifests=ctx.base_package_manifests,
            usage_skills=ctx.level2_usage_skills,
        )
        parts.append("## Usage Skills & Manifests")
        parts.append(packed)
        parts.append("")

    # ── Examples (few-shot) ──
    if ctx.base_package_examples:
        parts.append("## Reference Examples (few-shot)")
        for did, examples in ctx.base_package_examples.items():
            for ex in examples:
                title = ex.get("title", "untitled")
                user_req = ex.get("user_request", "")
                raw_doc = ex.get("raw_document", {})
                parts.append(f"### Example: {title}")
                parts.append(f"User request: {user_req}")
                parts.append(f"Raw document:\n{compact_json(raw_doc)}")
                parts.append("")

    # ── Anti-examples (negative guidance) ──
    if hasattr(ctx, 'base_package_anti_examples') and ctx.base_package_anti_examples:
        parts.append("## Anti-Examples (DO NOT replicate these patterns)")
        for did, anti_list in ctx.base_package_anti_examples.items():
            if not anti_list:
                continue
            parts.append(f"### Dialect: {did}")
            for ae in anti_list:
                title = ae.get("title", ae.get("anti_id", "untitled"))
                explanation = ae.get("explanation", "")
                parts.append(f"#### {title}")
                # Include the bad pattern for clarity
                for k in ("bad_op", "bad_field", "bad_input", "bad_snippet", "bad_profile_stations"):
                    if k in ae:
                        parts.append(f"- Bad {k}: {compact_json(ae[k]) if not isinstance(ae[k], str) else ae[k]}")
                if "correct_approach" in ae:
                    parts.append(f"- Correct approach: {ae['correct_approach']}")
                parts.append(f"- Reason: {explanation}")
                parts.append("")

    return "\n".join(parts) if parts else "(no operations available)"


def _build_op_contract(node_plan, dialect_registry) -> str:
    """Build the operation contract for a single node's params filling.

    Extracts the op's params schema, usage notes, and common mistakes from the
    dialect's OperationSpec, so the LLM has semantic guidance when filling params.
    """
    did = getattr(node_plan, "dialect", "")
    op = getattr(node_plan, "op", "")
    op_ver = getattr(node_plan, "op_version", "1.0.0")

    dialect = dialect_registry.get(did) if did else None
    if dialect is None:
        return f"(dialect {did!r} not registered)"

    try:
        spec = dialect.get_op_spec(op, op_ver)
    except Exception:
        return f"(op {op!r} not found in dialect {did!r})"

    parts: list[str] = []
    parts.append(f"## Operation Contract: {did}.{op} (v{op_ver})")
    parts.append(f"Phase: {getattr(spec, 'phase', '?')}")

    summary = getattr(spec, "summary", "")
    if summary:
        parts.append(f"Summary: {summary}")

    usage_notes = getattr(spec, "usage_notes", "")
    if usage_notes:
        parts.append(f"Usage notes: {usage_notes}")

    common_mistakes = getattr(spec, "common_mistakes", "")
    if common_mistakes:
        parts.append(f"Common mistakes: {common_mistakes}")

    # Params schema
    params_model = getattr(spec, "params_model", None)
    if params_model is not None:
        try:
            schema = params_model.model_json_schema()
            parts.append(f"Params schema:\n{compact_json(schema)}")
        except Exception:
            parts.append("(params schema unavailable)")

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# Runtime repair prompts (repair_loop.md §13.2/§14, Stage D)
# ═══════════════════════════════════════════════════════════════════════════════

RUNTIME_REPAIR_SYSTEM_PROMPT = """\
You are a constrained G-CAD IR RUNTIME repair agent.

A validated document failed during geometry execution (B-Rep construction).
You may only output a minimal repair patch against the RAW IR.
You must NOT regenerate the document or redesign the part.

Hard rules:
- Only modify paths listed in ALLOWED PATHS (node params of the failing node).
- Every change must provide the exact old_value from the current document.
- Do not change schema_version, safety, dialect, op, op_version,
  required, degradation_policy, inputs, outputs or selected_dialects.
- Do not modify nodes unrelated to the runtime failure.
- Numeric changes must stay small (<= 25% relative), keep the sign,
  and directly address the reported failure.
- Do not weaken required features or postconditions to make the run pass.

Each change must:
1. target an ALLOWED path;
2. use the exact current old_value;
3. state the direct causal link to the runtime failure;
4. describe the expected effect.

Return give_up=true when:
- the failure is not caused by an IR parameter;
- the information is insufficient to prove causality;
- a safe fix would require changing design intent or graph structure.
"""


def build_runtime_repair_user_prompt(
    current_doc: dict,
    runtime_issues: list[dict],
    failing_node: dict | None,
    op_contract: str,
    geometry_health: dict | None = None,
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    prior_attempts: list[dict] | None = None,
    user_request: str = "",
) -> str:
    """Build the user prompt for the RUNTIME repair stage (§14.2 subset).

    完整局部契约 + 有界全局背景 (§7.3): primary issue 全字段、失败节点
    全 JSON、该 op 的参数 schema、geometry health、允许/禁止路径、
    历史尝试与拒绝原因、完整 Raw IR。
    """
    return f"""RUNTIME FAILURE ISSUES:
{compact_json(runtime_issues)}

FAILING NODE:
{compact_json(failing_node) if failing_node else "(node not located)"}

OPERATION CONTRACT:
{op_contract}

GEOMETRY HEALTH:
{compact_json(geometry_health or {})}

ALLOWED PATHS (you may ONLY modify these):
{compact_json(allowed_paths or [])}

FORBIDDEN PATHS:
{compact_json(forbidden_paths or [
    "/schema_version", "/selected_dialects", "/safety",
    "/constraints/require_step_file", "/constraints/require_metadata_sidecar",
    "/constraints/require_closed_solid",
])}

PRIOR REPAIR ATTEMPTS (with rejection reasons):
{compact_json(prior_attempts or [])}

ORIGINAL USER REQUEST:
{user_request}

CURRENT DOCUMENT:
{compact_json(current_doc)}

Return only the strict repair patch tool arguments.
"""
