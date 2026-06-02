"""Mock LLM injector — creates controlled hallucination patterns for A/B testing.

Generates realistic LLM-like responses with known hallucination types injected
at controlled rates. This allows measuring whether the new staged pipeline
catches/fixes more hallucinations than the old single-shot pipeline.

Hallucination types injected:
  H1: Invented op name (e.g., "make_flange" instead of "revolve_profile")
  H2: Extra param field (e.g., "material" in params)
  H3: Missing required param (e.g., missing "axis" in revolve_profile)
  H4: Wrong param type (e.g., string for a float field)
  H5: Wrong op_version (e.g., "2.0.0" instead of "1.0.0")
  H6: Wrong phase (e.g., "primary_cut" for a base_solid op)
  H7: Safety flag false (e.g., not_for_manufacturing=false)
  H8: Missing constraint flag (e.g., require_step_file missing)
  H9: Cross-dialect internal ref (direct node ref across dialects)
  H10: Wrong output name (e.g., "solid_body" instead of "body")
"""

from __future__ import annotations

import copy
from typing import Any


# ── Known valid patterns (used as base for injection) ────────────────────────

_VALID_WASHER_RAW: dict[str, Any] = {
    "schema_version": "g_cad_core_v0.2",
    "document_id": "washer-001",
    "part_name": "reference_washer",
    "units": "mm",
    "trust_level": "reference_geometry",
    "selected_dialects": [{"dialect": "axisymmetric", "version": "0.2.0"}],
    "components": [
        {"id": "washer_body", "owner_dialect": "axisymmetric", "root_node": "n_bore"}
    ],
    "nodes": [
        {
            "id": "n_revolve", "component": "washer_body",
            "dialect": "axisymmetric", "op": "revolve_profile",
            "op_version": "1.0.0", "phase": "base_solid",
            "inputs": [],
            "outputs": [{"name": "body", "type": "solid"}, {"name": "outer_frame", "type": "frame"}],
            "params": {
                "axis": "Z",
                "profile_stations": [
                    {"r_mm": 40.0, "z_front_mm": 0.0, "z_rear_mm": 2.0},
                    {"r_mm": 40.0, "z_front_mm": 2.0, "z_rear_mm": 12.0},
                    {"r_mm": 15.0, "z_front_mm": 12.0, "z_rear_mm": 13.0},
                ],
            },
            "required": True, "degradation_policy": "fail",
        },
        {
            "id": "n_bore", "component": "washer_body",
            "dialect": "axisymmetric", "op": "cut_center_bore",
            "op_version": "1.0.0", "phase": "primary_cut",
            "inputs": [{"node": "n_revolve", "output": "body"}],
            "outputs": [{"name": "body", "type": "solid"}],
            "params": {"diameter_mm": 30.0, "axis": "Z", "through_all": True},
            "required": True, "degradation_policy": "fail",
        },
    ],
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

# ── Injection helpers ────────────────────────────────────────────────────────


def inject_h1_invented_op(raw: dict, node_idx: int = 0) -> dict:
    """H1: Replace a valid op with an invented one."""
    r = copy.deepcopy(raw)
    r["nodes"][node_idx]["op"] = "make_washer"
    return r


def inject_h2_extra_param(raw: dict, node_idx: int = 0) -> dict:
    """H2: Add an extra field to params."""
    r = copy.deepcopy(raw)
    r["nodes"][node_idx]["params"]["material"] = "steel"
    return r


def inject_h3_missing_param(raw: dict, node_idx: int = 0) -> dict:
    """H3: Remove a required param field."""
    r = copy.deepcopy(raw)
    r["nodes"][node_idx]["params"].pop("axis", None)
    return r


def inject_h4_wrong_type(raw: dict, node_idx: int = 1) -> dict:
    """H4: Change a float param to string."""
    r = copy.deepcopy(raw)
    r["nodes"][node_idx]["params"]["diameter_mm"] = "thirty"
    return r


def inject_h5_wrong_op_version(raw: dict, node_idx: int = 0) -> dict:
    """H5: Use a non-existent op_version."""
    r = copy.deepcopy(raw)
    r["nodes"][node_idx]["op_version"] = "2.0.0"
    return r


def inject_h6_wrong_phase(raw: dict, node_idx: int = 1) -> dict:
    """H6: Use wrong phase for the op."""
    r = copy.deepcopy(raw)
    r["nodes"][node_idx]["phase"] = "base_solid"  # cut_center_bore should be primary_cut
    return r


def inject_h7_safety_false(raw: dict) -> dict:
    """H7: Set a safety flag to false."""
    r = copy.deepcopy(raw)
    r["safety"]["not_for_manufacturing"] = False
    return r


def inject_h8_missing_constraint(raw: dict) -> dict:
    """H8: Remove a required constraint."""
    r = copy.deepcopy(raw)
    r["constraints"].pop("require_step_file", None)
    return r


def inject_h9_cross_dialect_ref(raw: dict) -> dict:
    """H9: Reference internal node across dialect without composition."""
    r = copy.deepcopy(raw)
    r["selected_dialects"].append({"dialect": "sketch_extrude", "version": "0.2.0"})
    r["components"].append({"id": "sketch_part", "owner_dialect": "sketch_extrude", "root_node": "n_se"})
    r["nodes"].append({
        "id": "n_se", "component": "sketch_part",
        "dialect": "sketch_extrude", "op": "extrude_rectangle",
        "op_version": "1.0.0", "phase": "base_solid",
        "inputs": [{"node": "n_revolve", "output": "body"}],  # cross-dialect direct ref!
        "outputs": [{"name": "body", "type": "solid"}],
        "params": {"width_mm": 100, "height_mm": 80, "depth_mm": 10},
        "required": True, "degradation_policy": "fail",
    })
    return r


def inject_h10_wrong_output_name(raw: dict, node_idx: int = 0) -> dict:
    """H10: Use a non-canonical output name."""
    r = copy.deepcopy(raw)
    r["nodes"][node_idx]["outputs"] = [
        {"name": "solid_body", "type": "solid"},  # should be "body"
        {"name": "frame", "type": "frame"},        # should be "outer_frame"
    ]
    return r


# ── Hallucination catalog ────────────────────────────────────────────────────

HALLUCINATION_INJECTORS = {
    "H1_invented_op": (inject_h1_invented_op, "Unknown/invented operation name"),
    "H2_extra_param": (inject_h2_extra_param, "Extra/unknown parameter field"),
    "H3_missing_param": (inject_h3_missing_param, "Missing required parameter"),
    "H4_wrong_type": (inject_h4_wrong_type, "Wrong parameter type"),
    "H5_wrong_op_version": (inject_h5_wrong_op_version, "Non-existent op_version"),
    "H6_wrong_phase": (inject_h6_wrong_phase, "Wrong phase for operation"),
    "H7_safety_false": (inject_h7_safety_false, "Safety flag set to false"),
    "H8_missing_constraint": (inject_h8_missing_constraint, "Missing required constraint"),
    "H9_cross_dialect": (inject_h9_cross_dialect_ref, "Cross-dialect internal reference"),
    "H10_wrong_output_name": (inject_h10_wrong_output_name, "Wrong output field name"),
}


def generate_injected_raw(injection_id: str) -> dict:
    """Generate a RawGcadDocument dict with one specific hallucination injected."""
    injector, _ = HALLUCINATION_INJECTORS[injection_id]
    return injector(_VALID_WASHER_RAW)


def generate_clean_raw() -> dict:
    """Generate a clean (no hallucination) RawGcadDocument."""
    return copy.deepcopy(_VALID_WASHER_RAW)
