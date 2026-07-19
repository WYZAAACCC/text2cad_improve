"""Topology contracts — declares what semantic topology entities each operation produces.

Each operation that creates/modifies geometry SHOULD declare a TopologyContract
describing the expected faces, edges, and solids. The contract is used for:
  1. Validation: check that operation outputs match expectations
  2. Semantic naming: know what roles to assign
  3. Downstream resolution: know what can be referenced

Phase 2: core contracts for extrude, revolve, hole, boolean, fillet.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TopologyOutputRole(BaseModel):
    """One semantic topology output from an operation.

    Example: extrude produces:
      - "end_cap_positive" (exactly_one face)
      - "side_face" (one_or_more faces, one per sketch edge)
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Semantic role name, e.g. 'end_cap_positive'")

    entity_type: Literal["solid", "shell", "face", "wire", "edge", "vertex"] = Field(
        description="Topology entity type produced",
    )

    cardinality: Literal[
        "exactly_one",
        "zero_or_one",
        "one_or_more",
        "zero_or_more",
    ] = Field(description="Expected count of this entity type")

    persistence: Literal[
        "required",
        "best_effort",
        "not_exposed",
    ] = Field(
        default="required",
        description="How critical is stable naming for this role",
    )

    semantic_rule: str = Field(
        default="",
        description="Human-readable rule for identifying this entity",
    )


class TopologyContract(BaseModel):
    """Complete topology contract for one operation.

    Declares what the operation produces in terms of persistent topology entities,
    how it tracks history, and what resolution quality is required by downstream
    consumers.

    Example for extrude_rectangle:
      - history_capability: "full_kernel_history" (BRepPrimAPI_MakePrism)
      - output_roles: [end_cap_positive, end_cap_negative, side_face, body]
      - required_resolution_quality: "deterministic"
    """

    model_config = ConfigDict(extra="forbid")

    history_capability: Literal[
        "full_kernel_history",
        "partial_kernel_history",
        "deterministic_semantic",
        "fingerprint_fallback",
        "unsupported",
    ] = Field(
        default="unsupported",
        description="What level of history tracking the operation provides",
    )

    output_roles: list[TopologyOutputRole] = Field(
        default_factory=list,
        description="Expected topology outputs from this operation",
    )

    allows_split: bool = Field(
        default=False,
        description="Operation may split one input entity into multiple outputs",
    )

    allows_merge: bool = Field(
        default=False,
        description="Operation may merge multiple input entities into one output",
    )

    required_resolution_quality: Literal[
        "exact",
        "deterministic",
        "best_effort",
    ] = Field(
        default="deterministic",
        description="Minimum resolution quality for downstream consumers",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-defined contracts for common operations
# ═══════════════════════════════════════════════════════════════════════════════

EXTRUDE_RECTANGLE_CONTRACT = TopologyContract(
    history_capability="full_kernel_history",
    output_roles=[
        TopologyOutputRole(
            name="body",
            entity_type="solid",
            cardinality="exactly_one",
            persistence="required",
            semantic_rule="Result solid body from extrusion",
        ),
        TopologyOutputRole(
            name="end_cap_positive",
            entity_type="face",
            cardinality="exactly_one",
            persistence="required",
            semantic_rule="Planar face at the positive extrude direction end",
        ),
        TopologyOutputRole(
            name="end_cap_negative",
            entity_type="face",
            cardinality="exactly_one",
            persistence="required",
            semantic_rule="Planar face at the negative extrude direction end",
        ),
        TopologyOutputRole(
            name="side_face",
            entity_type="face",
            cardinality="one_or_more",
            persistence="required",
            semantic_rule="Lateral faces generated from each sketch profile edge",
        ),
    ],
)

REVOLVE_PROFILE_CONTRACT = TopologyContract(
    history_capability="full_kernel_history",
    output_roles=[
        TopologyOutputRole(
            name="body",
            entity_type="solid",
            cardinality="exactly_one",
            persistence="required",
            semantic_rule="Result solid body from revolution",
        ),
        TopologyOutputRole(
            name="revolved_face",
            entity_type="face",
            cardinality="one_or_more",
            persistence="required",
            semantic_rule="Faces generated by revolving each profile edge",
        ),
        TopologyOutputRole(
            name="start_cap",
            entity_type="face",
            cardinality="zero_or_one",
            persistence="best_effort",
            semantic_rule="Planar cap at revolution start angle (absent if full 360)",
        ),
        TopologyOutputRole(
            name="end_cap",
            entity_type="face",
            cardinality="zero_or_one",
            persistence="best_effort",
            semantic_rule="Planar cap at revolution end angle (absent if full 360)",
        ),
    ],
)

CUT_HOLE_CONTRACT = TopologyContract(
    history_capability="full_kernel_history",
    output_roles=[
        TopologyOutputRole(
            name="body",
            entity_type="solid",
            cardinality="exactly_one",
            persistence="required",
            semantic_rule="Result body after hole cut (modified input)",
        ),
        TopologyOutputRole(
            name="hole_wall",
            entity_type="face",
            cardinality="exactly_one",
            persistence="required",
            semantic_rule="Cylindrical wall of the hole",
        ),
        TopologyOutputRole(
            name="entry_rim",
            entity_type="edge",
            cardinality="exactly_one",
            persistence="required",
            semantic_rule="Circular edge at hole entry (intersection with host face)",
        ),
        TopologyOutputRole(
            name="exit_rim",
            entity_type="edge",
            cardinality="zero_or_one",
            persistence="best_effort",
            semantic_rule="Circular edge at hole exit (absent for blind hole)",
        ),
    ],
    allows_split=True,
)

BOOLEAN_UNION_CONTRACT = TopologyContract(
    history_capability="full_kernel_history",
    output_roles=[
        TopologyOutputRole(
            name="body",
            entity_type="solid",
            cardinality="exactly_one",
            persistence="required",
            semantic_rule="Unioned solid body",
        ),
        TopologyOutputRole(
            name="modified_argument_face",
            entity_type="face",
            cardinality="one_or_more",
            persistence="best_effort",
            semantic_rule="Faces from argument body that were modified",
        ),
        TopologyOutputRole(
            name="modified_tool_face",
            entity_type="face",
            cardinality="one_or_more",
            persistence="best_effort",
            semantic_rule="Faces from tool body that were modified",
        ),
        TopologyOutputRole(
            name="generated_intersection_face",
            entity_type="face",
            cardinality="zero_or_more",
            persistence="best_effort",
            semantic_rule="New faces created at the intersection boundary",
        ),
    ],
    allows_split=True,
    allows_merge=True,
)

FILLET_CONTRACT = TopologyContract(
    history_capability="partial_kernel_history",
    output_roles=[
        TopologyOutputRole(
            name="body",
            entity_type="solid",
            cardinality="exactly_one",
            persistence="required",
            semantic_rule="Result body after fillet",
        ),
        TopologyOutputRole(
            name="fillet_face",
            entity_type="face",
            cardinality="one_or_more",
            persistence="required",
            semantic_rule="Rounded faces generated from each filleted edge",
        ),
        TopologyOutputRole(
            name="modified_adjacent_face",
            entity_type="face",
            cardinality="one_or_more",
            persistence="best_effort",
            semantic_rule="Original faces adjacent to filleted edges (now modified)",
        ),
    ],
    allows_split=False,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Contract registry (lookup by (dialect, op))
# ═══════════════════════════════════════════════════════════════════════════════

CHAMFER_CONTRACT = TopologyContract(
    history_capability="partial_kernel_history",
    output_roles=[
        TopologyOutputRole(name="body", entity_type="solid", cardinality="exactly_one",
                           persistence="required", semantic_rule="Result body after chamfer"),
        TopologyOutputRole(name="chamfer_face", entity_type="face", cardinality="one_or_more",
                           persistence="required",
                           semantic_rule="Flat faces generated from each chamfered edge"),
        TopologyOutputRole(name="modified_adjacent_face", entity_type="face",
                           cardinality="one_or_more", persistence="best_effort",
                           semantic_rule="Original faces adjacent to chamfered edges"),
    ],
    allows_split=False,
)

SHELL_CONTRACT = TopologyContract(
    history_capability="partial_kernel_history",
    output_roles=[
        TopologyOutputRole(name="body", entity_type="solid", cardinality="exactly_one",
                           persistence="required", semantic_rule="Result hollow shell body"),
        TopologyOutputRole(name="removed_face", entity_type="face", cardinality="one_or_more",
                           persistence="required",
                           semantic_rule="Faces removed to create the opening"),
        TopologyOutputRole(name="offset_face", entity_type="face", cardinality="one_or_more",
                           persistence="best_effort",
                           semantic_rule="Original faces offset to create wall thickness"),
    ],
    allows_split=False,
)

LOFT_CONTRACT = TopologyContract(
    history_capability="partial_kernel_history",
    output_roles=[
        TopologyOutputRole(name="body", entity_type="solid", cardinality="exactly_one",
                           persistence="required", semantic_rule="Result lofted solid"),
        TopologyOutputRole(name="lateral_face", entity_type="face", cardinality="one_or_more",
                           persistence="required",
                           semantic_rule="Transition faces between adjacent sections"),
        TopologyOutputRole(name="cap_start", entity_type="face", cardinality="zero_or_one",
                           persistence="best_effort",
                           semantic_rule="Start section face (planar)"),
        TopologyOutputRole(name="cap_end", entity_type="face", cardinality="zero_or_one",
                           persistence="best_effort",
                           semantic_rule="End section face (planar)"),
    ],
    allows_split=False,
)

SWEEP_CONTRACT = TopologyContract(
    history_capability="partial_kernel_history",
    output_roles=[
        TopologyOutputRole(name="body", entity_type="solid", cardinality="exactly_one",
                           persistence="required", semantic_rule="Result swept solid"),
        TopologyOutputRole(name="lateral_face", entity_type="face", cardinality="one_or_more",
                           persistence="required",
                           semantic_rule="Side faces along the sweep path"),
        TopologyOutputRole(name="cap_start", entity_type="face", cardinality="zero_or_one",
                           persistence="best_effort",
                           semantic_rule="Start profile face"),
        TopologyOutputRole(name="cap_end", entity_type="face", cardinality="zero_or_one",
                           persistence="best_effort",
                           semantic_rule="End profile face"),
    ],
)

HELIX_SWEEP_CONTRACT = TopologyContract(
    history_capability="partial_kernel_history",
    output_roles=[
        TopologyOutputRole(name="body", entity_type="solid", cardinality="exactly_one",
                           persistence="required", semantic_rule="Result helical swept solid"),
        TopologyOutputRole(name="helical_face", entity_type="face", cardinality="one_or_more",
                           persistence="required",
                           semantic_rule="Helical side faces along the coil"),
        TopologyOutputRole(name="cap_start", entity_type="face", cardinality="zero_or_one",
                           persistence="best_effort",
                           semantic_rule="Start coil end face"),
        TopologyOutputRole(name="cap_end", entity_type="face", cardinality="zero_or_one",
                           persistence="best_effort",
                           semantic_rule="End coil end face"),
    ],
)

CONTRACT_REGISTRY: dict[tuple[str, str], TopologyContract] = {
    ("sketch_extrude", "extrude_rectangle"): EXTRUDE_RECTANGLE_CONTRACT,
    ("axisymmetric", "revolve_profile"): REVOLVE_PROFILE_CONTRACT,
    ("sketch_extrude", "cut_hole"): CUT_HOLE_CONTRACT,
    ("composition", "boolean_union"): BOOLEAN_UNION_CONTRACT,
    ("sketch_extrude", "apply_safe_fillet"): FILLET_CONTRACT,
    ("sketch_extrude", "apply_safe_chamfer"): CHAMFER_CONTRACT,
    ("shell_housing", "shell_body"): SHELL_CONTRACT,
    ("loft_sweep", "loft_sections"): LOFT_CONTRACT,
    ("loft_sweep", "sweep_profile"): SWEEP_CONTRACT,
    ("loft_sweep", "helix_sweep"): HELIX_SWEEP_CONTRACT,
}


def get_contract(dialect: str, op: str) -> TopologyContract | None:
    """Look up a topology contract by (dialect, op) tuple."""
    return CONTRACT_REGISTRY.get((dialect, op))
