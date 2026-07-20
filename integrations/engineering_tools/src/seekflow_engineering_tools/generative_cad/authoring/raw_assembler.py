"""System-side RawGcadDocument assembler — typed wiring compiler.

The LLM MUST NOT write fixed fields like schema_version, trust_level,
safety, constraints, dialect versions, op_versions, outputs, or graph wiring.
The system fills these deterministically.

v5.1: AvailabilityMap with scope separation, fail-closed assembly,
pairwise boolean_union expansion, and typed input selection.

Assembly flow:
  RoutePlan + FeatureSequenceDraft + {node_id: NodeParamsDraft}
    → RawGcadDocument (dict, ready for parse/validate/canonicalize)
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, DefaultDict

from seekflow_engineering_tools.generative_cad.topology.design_identity import (
    DesignIdentity,
    FeatureIdentityReconciler,
    IdentitySource,
)

from seekflow_engineering_tools.generative_cad.authoring.schemas import (
    FeatureSequenceDraft,
    NodeParamsDraft,
    RawAssemblyResult,
    RoutePlan,
)
from seekflow_engineering_tools.generative_cad.ir.hashing import stable_hash


# ═══════════════════════════════════════════════════════════════════════════════
# Fail-closed error
# ═══════════════════════════════════════════════════════════════════════════════

class AssemblyError(ValueError):
    """Fail-closed error raised by RawGcadDocument assembly.

    Raised when the assembler cannot resolve a required input, encounters
    an unknown dialect/operation/output type, or detects an irrecoverable
    wiring inconsistency.
    """


# ═══════════════════════════════════════════════════════════════════════════════
# Typed value reference
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ValueRef:
    """A typed reference to a node's output value.

    Used by the AvailabilityMap to track what values are available
    in each scope for typed wiring.
    """
    node_id: str
    output_name: str
    value_type: str
    component_id: str
    dialect: str
    op: str

    def as_input(self) -> dict[str, str]:
        return {"node": self.node_id, "output": self.output_name}


# scope → type → list of ValueRef
AvailabilityMap = DefaultDict[str, DefaultDict[str, list[ValueRef]]]


# ═══════════════════════════════════════════════════════════════════════════════
# Output name policy — fail-closed for unknown types
# ═══════════════════════════════════════════════════════════════════════════════

_OUTPUT_NAME_BY_TYPE: dict[str, str] = {
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


def _output_name_for_type(value_type: str) -> str:
    """Map output type string to canonical output name.

    Raises AssemblyError for unknown types — no silent fallback.
    """
    try:
        return _OUTPUT_NAME_BY_TYPE[value_type]
    except KeyError:
        raise AssemblyError(
            f"Unsupported output type: {value_type!r}. "
            f"Known types: {sorted(_OUTPUT_NAME_BY_TYPE.keys())}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Assembler
# ═══════════════════════════════════════════════════════════════════════════════


def assemble_raw_gcad_document(
    *,
    user_request: str,
    route_plan: RoutePlan,
    feature_sequence: FeatureSequenceDraft,
    node_params: dict[str, NodeParamsDraft],
    dialect_registry,  # DialectRegistry
    document_id: str | None = None,
    units: str = "mm",
    design_identity: DesignIdentity | None = None,
) -> RawAssemblyResult:
    """Assemble a RawGcadDocument dict from staged authoring outputs.

    The system fills:
      - schema_version, trust_level, document_id, units
      - constraints, safety (all flags explicitly true)
      - selected_dialects with registry versions
      - components with owner_dialect, root_node
      - node op_version, outputs, inputs (typed wiring), phase
      - pairwise boolean_union expansion for 3+ assembly solids

    design_identity (V3 §2.1): When provided and is_strong=True,
    enables strong persistent topology claims across rebuilds.
    When None or is_strong=False, the system runs in ephemeral mode.

    Raises AssemblyError on unrecoverable wiring failures.
    """
    if document_id is None:
        document_id = f"gcad-{uuid.uuid4().hex[:12]}"

    if design_identity is None:
        design_identity = DesignIdentity(
            design_id=document_id,
            run_id=uuid.uuid4().hex[:8],
            identity_source=IdentitySource.EPHEMERAL_GENERATED,
        )

    # ── Build selected_dialects ──
    selected_dialects = []
    for sd in route_plan.selected_dialects:
        dialect = dialect_registry.get(sd.dialect)
        version = dialect.version if dialect else sd.version
        selected_dialects.append({"dialect": sd.dialect, "version": version})

    # ── Build components ──
    components = []
    for cd in feature_sequence.components:
        comp = {"id": cd.component_id, "owner_dialect": cd.owner_dialect}
        if cd.kind_hint:
            comp["kind_hint"] = cd.kind_hint
        components.append(comp)

    system_filled: list[str] = [
        "schema_version", "trust_level", "units",
        "constraints", "safety", "selected_dialects versions",
        "op_version (from OperationSpec)", "outputs", "typed wiring",
    ]

    # ── Availability map (scope → type → [ValueRef]) ──
    available: AvailabilityMap = defaultdict(lambda: defaultdict(list))

    # ── Build leaf component nodes first ──
    leaf_nodes: list[dict] = []
    leaf_sequence = [n for n in feature_sequence.node_sequence
                     if n.component_id != "__assembly__"]
    assembly_sequence = [n for n in feature_sequence.node_sequence
                         if n.component_id == "__assembly__"]

    for node_plan in leaf_sequence:
        nd = node_params.get(node_plan.node_id)
        outputs = _build_outputs(node_plan, dialect_registry)
        inputs = _build_inputs_typed(node_plan, dialect_registry, available)
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
            # V3 §2.2: inject stable feature_uid for persistent topology
            "_meta": {
                "feature_uid": FeatureIdentityReconciler.generate_feature_uid(
                    component_uid=node_plan.component_id,
                    operation_kind=node_plan.op,
                ),
            },
        }
        leaf_nodes.append(node)

        # Register outputs in component scope
        cid = node_plan.component_id
        for o in outputs:
            ref = ValueRef(
                node_id=node_plan.node_id,
                output_name=o["name"],
                value_type=o["type"],
                component_id=cid,
                dialect=node_plan.dialect,
                op=node_plan.op,
            )
            available[cid][o["type"]].append(ref)

    # ── Promote leaf component root solids to assembly scope ──
    for comp in components:
        cid = comp["id"]
        if cid == "__assembly__":
            continue
        solids = available.get(cid, {}).get("solid", [])
        if solids:
            last_solid = solids[-1]
            available["__assembly__"]["solid"].append(last_solid)
            comp["root_node"] = last_solid.node_id
            system_filled.append(f"root_node:{cid}")
        else:
            raise AssemblyError(
                f"Component {cid!r} has no solid output. "
                f"Every leaf component must produce at least one solid."
            )

    # ── Build assembly nodes with scope-appropriate wiring ──
    assembly_nodes = _build_assembly_nodes(
        assembly_sequence, node_params, dialect_registry, available, system_filled
    )

    all_nodes = leaf_nodes + assembly_nodes

    # ── Assembly component root_node ──
    if assembly_nodes:
        assy_solids = available["__assembly__"].get("solid", [])
        if assy_solids:
            assy_comp = next((c for c in components if c["id"] == "__assembly__"), None)
            if assy_comp:
                assy_comp["root_node"] = assy_solids[-1].node_id
                system_filled.append("root_node:__assembly__")

    # ── Build RawGcadDocument ──
    raw_document = {
        "schema_version": "g_cad_core_v0.2",
        "document_id": document_id,
        "part_name": route_plan.part_intent.get("object_type", user_request[:60]),
        "units": units,
        "trust_level": "reference_geometry",
        "selected_dialects": selected_dialects,
        "components": components,
        "nodes": all_nodes,
        "design_identity": {  # V3 §2.1: embedded for downstream consumers
            "design_id": design_identity.design_id,
            "revision_id": design_identity.revision_id,
            "run_id": design_identity.run_id,
            "identity_source": design_identity.identity_source.value,
        },
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


# ═══════════════════════════════════════════════════════════════════════════════
# Assembly node builder — pairwise boolean_union expansion
# ═══════════════════════════════════════════════════════════════════════════════


def _build_assembly_nodes(
    assembly_sequence: list,
    node_params: dict,
    dialect_registry,
    available: AvailabilityMap,
    system_filled: list[str],
) -> list[dict]:
    """Build assembly-level nodes with pairwise boolean_union expansion.

    When the assembly scope has 3+ solids, the LLM's single boolean_union
    intent node is expanded into pairwise synthetic union nodes.
    """
    nodes = []

    for node_plan in assembly_sequence:
        nd = node_params.get(node_plan.node_id)
        op_version = _resolve_op_version(node_plan, dialect_registry)

        if node_plan.op == "boolean_union":
            # Pairwise expansion for 3+ solids
            nodes.extend(_expand_boolean_union(
                node_plan, nd, op_version, available, system_filled
            ))
        else:
            # Other composition ops: standard typed wiring
            outputs = _build_outputs(node_plan, dialect_registry)
            inputs = _build_inputs_typed(node_plan, dialect_registry, available)

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

            for o in outputs:
                ref = ValueRef(
                    node_id=node_plan.node_id,
                    output_name=o["name"],
                    value_type=o["type"],
                    component_id=node_plan.component_id,
                    dialect=node_plan.dialect,
                    op=node_plan.op,
                )
                available["__assembly__"][o["type"]].append(ref)

    return nodes


def _expand_boolean_union(
    node_plan,
    node_params_draft,
    op_version: str,
    available: AvailabilityMap,
    system_filled: list[str],
) -> list[dict]:
    """Expand a single boolean_union intent into pairwise operations.

    When __assembly__ scope has >2 solids, generate synthetic nodes:
      union_1 = solids[0] ∪ solids[1]
      union_2 = union_1 ∪ solids[2]
      ...

    The first synthetic node reuses the LLM's original node_id for
    audit trail consistency.
    """
    solids = list(available["__assembly__"].get("solid", []))
    if len(solids) < 2:
        raise AssemblyError(
            f"boolean_union requires at least 2 assembly solids, "
            f"got {len(solids)}"
        )

    synthetic_nodes = []
    current_ref = solids[0]
    # Output spec for boolean_union
    out_name = _output_name_for_type("solid")

    for i, next_ref in enumerate(solids[1:], start=1):
        nid = node_plan.node_id if i == 1 else f"{node_plan.node_id}__auto_{i}"
        is_synthetic = (i > 1)

        node = {
            "id": nid,
            "component": node_plan.component_id,
            "dialect": node_plan.dialect,
            "op": node_plan.op,
            "op_version": op_version,
            "phase": node_plan.phase,
            "inputs": [
                current_ref.as_input(),
                next_ref.as_input(),
            ],
            "outputs": [
                {"name": out_name, "type": "solid"},
            ],
            "params": node_params_draft.params if node_params_draft else {},
            "required": node_plan.required,
            "degradation_policy": node_plan.degradation_policy,
        }
        synthetic_nodes.append(node)

        if is_synthetic:
            system_filled.append(f"synthetic_union:{nid}")

        # Update current for chain
        current_ref = ValueRef(
            node_id=nid,
            output_name=out_name,
            value_type="solid",
            component_id=node_plan.component_id,
            dialect=node_plan.dialect,
            op=node_plan.op,
        )

    # Register final union solid in assembly scope
    available["__assembly__"]["solid"].append(current_ref)

    return synthetic_nodes


# ═══════════════════════════════════════════════════════════════════════════════
# Typed wiring helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _build_outputs(node_plan, dialect_registry) -> list[dict[str, str]]:
    """Build node outputs from OperationSpec.output_types. Fail-closed."""
    dialect = dialect_registry.get(node_plan.dialect)
    if dialect is None:
        raise AssemblyError(
            f"Unknown dialect: {node_plan.dialect!r} "
            f"for node {node_plan.node_id!r}"
        )

    spec = dialect.get_op_spec(node_plan.op, node_plan.op_version)
    if spec is None:
        raise AssemblyError(
            f"Unknown operation: {node_plan.dialect!r}.{node_plan.op!r} "
            f"version={node_plan.op_version!r} for node {node_plan.node_id!r}"
        )

    outputs = []
    for t in spec.output_types:
        outputs.append({"name": _output_name_for_type(t), "type": t})
    return outputs


def _choose_latest_available(
    available: AvailabilityMap,
    scope: str,
    expected_type: str,
) -> ValueRef:
    """Select the most recent ValueRef of expected_type in the given scope.

    Raises AssemblyError if no candidate exists — fail-closed, no silent skip.
    """
    candidates = available.get(scope, {}).get(expected_type, [])
    if not candidates:
        raise AssemblyError(
            f"Missing input of type {expected_type!r} in scope {scope!r}. "
            f"Available types in scope: {sorted(available.get(scope, {}).keys())}"
        )
    return candidates[-1]


def _build_inputs_typed(
    node_plan,
    dialect_registry,
    available: AvailabilityMap,
) -> list[dict[str, str]]:
    """Build inputs using scope-appropriate typed wiring.

    - Non-composition ops consume from their own component scope.
    - Composition ops consume from the __assembly__ scope.
    - Missing inputs → AssemblyError (fail-closed).
    """
    dialect = dialect_registry.get(node_plan.dialect)
    if dialect is None:
        raise AssemblyError(
            f"Unknown dialect: {node_plan.dialect!r} "
            f"for node {node_plan.node_id!r}"
        )

    spec = dialect.get_op_spec(node_plan.op, node_plan.op_version)
    if spec is None:
        raise AssemblyError(
            f"Unknown operation: {node_plan.dialect!r}.{node_plan.op!r} "
            f"for node {node_plan.node_id!r}"
        )

    if not spec.input_types:
        return []

    # Composition ops use __assembly__ scope; leaf ops use own component scope
    scope = "__assembly__" if node_plan.dialect == "composition" else node_plan.component_id

    inputs = []
    for expected_type in spec.input_types:
        ref = _choose_latest_available(available, scope, expected_type)
        inputs.append(ref.as_input())
    return inputs


def _resolve_op_version(node_plan, dialect_registry) -> str:
    """Resolve op_version from OperationSpec, falling back to what LLM provided."""
    dialect = dialect_registry.get(node_plan.dialect)
    if dialect is None:
        return node_plan.op_version

    try:
        spec = dialect.get_op_spec(node_plan.op, node_plan.op_version)
        return spec.op_version
    except Exception:
        return node_plan.op_version
