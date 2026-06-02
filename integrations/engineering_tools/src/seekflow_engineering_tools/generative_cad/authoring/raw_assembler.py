"""System-side RawGcadDocument assembler.

The LLM MUST NOT write fixed fields like schema_version, trust_level,
safety, constraints, dialect versions, op_versions, outputs, or linear
graph wiring. The system fills these deterministically.

Assembly flow:
  RoutePlan + FeatureSequenceDraft + {node_id: NodeParamsDraft}
    → RawGcadDocument (dict, ready for parse/validate/canonicalize)
"""

from __future__ import annotations

import uuid
from typing import Any

from seekflow_engineering_tools.generative_cad.authoring.schemas import (
    FeatureSequenceDraft,
    NodeParamsDraft,
    RawAssemblyResult,
    RoutePlan,
)
from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash

# ── Output name policy ────────────────────────────────────────────────────────

_OUTPUT_NAME_MAP: dict[str, str] = {
    "solid": "body",
    "frame": "outer_frame",
    "profile": "profile",
    "sketch": "sketch",
    "solid_array": "bodies",
    "plane": "plane",
    "point": "point",
    "curve": "curve",
    "face_set": "faces",
    "edge_set": "edges",
    "component_ref": "component",
}


def _output_name_for_type(vtype: str) -> str:
    return _OUTPUT_NAME_MAP.get(vtype, vtype)


# ── Assembler ─────────────────────────────────────────────────────────────────


def assemble_raw_gcad_document(
    *,
    user_request: str,
    route_plan: RoutePlan,
    feature_sequence: FeatureSequenceDraft,
    node_params: dict[str, NodeParamsDraft],
    dialect_registry,  # DialectRegistry
    document_id: str | None = None,
    units: str = "mm",
) -> RawAssemblyResult:
    """Assemble a RawGcadDocument dict from staged authoring outputs.

    The system fills:
      - schema_version (always g_cad_core_v0.2)
      - trust_level (always reference_geometry)
      - document_id (auto-generated if not provided)
      - units
      - constraints (all safety flags explicitly true)
      - safety (all flags explicitly true)
      - selected_dialects with versions from registry
      - components with owner_dialect
      - node op_version from OperationSpec
      - node outputs from OperationSpec.output_types
      - simple linear solid-chain wiring
      - root_node references
    """
    if document_id is None:
        document_id = f"gcad-{uuid.uuid4().hex[:12]}"

    # ── Build selected_dialects from registry versions ──
    selected_dialects = []
    for sd in route_plan.selected_dialects:
        dialect = dialect_registry.get(sd.dialect)
        version = dialect.version if dialect else sd.version
        selected_dialects.append({
            "dialect": sd.dialect,
            "version": version,
        })

    # ── Build components ──
    components = []
    for cd in feature_sequence.components:
        comp = {
            "id": cd.component_id,
            "owner_dialect": cd.owner_dialect,
        }
        if cd.kind_hint:
            comp["kind_hint"] = cd.kind_hint
        # root_node filled after nodes
        components.append(comp)

    # ── Build nodes with system-filled fields ──
    nodes = []
    system_filled: list[str] = [
        "schema_version", "trust_level", "units",
        "constraints", "safety", "selected_dialects versions",
        "op_version (from OperationSpec)", "outputs", "linear wiring",
    ]

    # Per-component: track last solid-producing node for linear wiring
    last_solid: dict[str, str | None] = {c.component_id: None for c in feature_sequence.components}

    for node_plan in feature_sequence.node_sequence:
        nd = node_params.get(node_plan.node_id)

        # Build outputs from OperationSpec
        outputs = _build_outputs(node_plan, dialect_registry)

        # Build inputs (linear solid chain)
        inputs = _build_inputs(node_plan, last_solid, dialect_registry)

        # Resolve op_version from OperationSpec
        op_version = _resolve_op_version(node_plan, dialect_registry)

        node = {
            "id": node_plan.node_id,
            "component": node_plan.component_id,
            "dialect": node_plan.dialect,
            "op": node_plan.op,
            "op_version": op_version,
            "phase": node_plan.phase,
            "inputs": inputs,
            "outputs": outputs,
            "params": nd.params if nd else {},
            "required": node_plan.required,
            "degradation_policy": node_plan.degradation_policy,
        }

        nodes.append(node)

        # Track last solid output
        for o in outputs:
            if o["type"] == "solid":
                last_solid[node_plan.component_id] = node_plan.node_id
                break

    # ── Fill root_node on each component ──
    for comp in components:
        cid = comp["id"]
        last = last_solid.get(cid)
        if last:
            comp["root_node"] = last
            system_filled.append(f"root_node:{cid}")

    # ── Build RawGcadDocument ──
    raw_document = {
        "schema_version": "g_cad_core_v0.2",
        "document_id": document_id,
        "part_name": route_plan.part_intent.get("object_type", user_request[:60]),
        "units": units,
        "trust_level": "reference_geometry",
        "selected_dialects": selected_dialects,
        "components": components,
        "nodes": nodes,
        "constraints": {
            "require_step_file": True,
            "require_metadata_sidecar": True,
            "require_closed_solid": True,
            "expected_body_count": 1,
        },
        "safety": {
            "non_flight_reference_only": True,
            "not_airworthy": True,
            "not_certified": True,
            "not_for_manufacturing": True,
            "not_for_installation": True,
            "no_structural_validation": True,
            "no_life_prediction": True,
        },
    }

    # ── Compute source hashes ──
    route_hash = stable_hash(route_plan.model_dump())
    feature_hash = stable_hash(feature_sequence.model_dump())
    node_hashes = {
        nid: stable_hash(np.model_dump()) for nid, np in node_params.items()
    }

    return RawAssemblyResult(
        raw_document=raw_document,
        source_route_plan_hash=route_hash,
        source_feature_sequence_hash=feature_hash,
        source_node_params_hashes=node_hashes,
        system_filled_fields=system_filled,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _build_outputs(
    node_plan: Any,  # NodePlanDraft
    dialect_registry,
) -> list[dict[str, str]]:
    """Build node outputs from OperationSpec.output_types."""
    dialect = dialect_registry.get(node_plan.dialect)
    if dialect is None:
        return [{"name": node_plan.expected_output_name, "type": "solid"}]

    try:
        spec = dialect.get_op_spec(node_plan.op, node_plan.op_version)
        return [
            {"name": _output_name_for_type(t), "type": t}
            for t in spec.output_types
        ]
    except Exception:
        return [{"name": node_plan.expected_output_name, "type": "solid"}]


def _build_inputs(
    node_plan: Any,  # NodePlanDraft
    last_solid: dict[str, str | None],
    dialect_registry,
) -> list[dict[str, str]]:
    """Build simple linear chain inputs.

    If the operation has no input_types, return empty.
    If it expects 1 solid input and there's a previous solid node, wire it.
    Otherwise return empty (LLM would need to wire it, but simple chains
    are auto-wired).
    """
    dialect = dialect_registry.get(node_plan.dialect)
    if dialect is None:
        return []

    try:
        spec = dialect.get_op_spec(node_plan.op, node_plan.op_version)
        input_count = len(spec.input_types)
    except Exception:
        input_count = 0

    if input_count == 0:
        return []

    # Simple linear chain: if exactly 1 solid input expected
    if input_count == 1:
        prev = last_solid.get(node_plan.component_id)
        if prev:
            return [{"node": prev, "output": "body"}]

    return []


def _resolve_op_version(
    node_plan: Any,  # NodePlanDraft
    dialect_registry,
) -> str:
    """Resolve op_version from OperationSpec, falling back to what LLM provided."""
    dialect = dialect_registry.get(node_plan.dialect)
    if dialect is None:
        return node_plan.op_version

    try:
        spec = dialect.get_op_spec(node_plan.op, node_plan.op_version)
        return spec.op_version
    except Exception:
        return node_plan.op_version
