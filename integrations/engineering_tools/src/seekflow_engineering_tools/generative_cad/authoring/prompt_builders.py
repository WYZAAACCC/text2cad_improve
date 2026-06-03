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
