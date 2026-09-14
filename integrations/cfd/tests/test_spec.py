import pytest
from pydantic import ValidationError
from seekflow_cfd.agents import RepairProposal, apply_repair, validate_hard_parameters
from seekflow_cfd.models import CFDError, SimulationSpec, canonical, digest


def test_roundtrip_and_hash(spec):
    assert SimulationSpec.model_validate_json(spec.model_dump_json()) == spec
    assert digest(spec) == digest(spec.model_dump(mode="json"))
    assert canonical(spec) == canonical(
        SimulationSpec.model_validate_json(spec.model_dump_json())
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["mesh_strategy"].update(global_size_m=-1),
        lambda d: d["physics_spec"].update(reference_temperature_k=float("nan")),
        lambda d: d["geometry_ref"]["geometry"].update(sha256="bad"),
        lambda d: d.update(command="rm -rf"),
        lambda d: d["boundary_specs"][0].update(velocity_m_s=None),
        lambda d: d["boundary_specs"][1].update(name="inlet"),
        lambda d: d["physics_spec"].update(time_mode="transient"),
        lambda d: d["physics_spec"].update(turbulence="k_omega_sst"),
        lambda d: d["material_spec"][0]["density_kg_m3"].update(
            temperature_table=[[300, 1], [400, 2]]
        ),
        lambda d: d["result_requests"][0].update(boundary="absent"),
        lambda d: d["solver_control"].update(time_step_s=0.1),
        lambda d: d["convergence_criteria"].update(residuals={"continuity": 1e-3}),
    ],
)
def test_reject_invalid(spec, change):
    data = spec.model_dump(mode="json")
    change(data)
    with pytest.raises(ValidationError):
        SimulationSpec.model_validate(data)


def test_repair_changes_only_numerical_fields(spec):
    repaired = apply_repair(
        spec,
        RepairProposal(action="reduce_relaxation", factor=0.5, rationale="test"),
        "solver",
    )
    assert repaired.spec_hash != spec.spec_hash
    a, b = spec.model_dump(), repaired.model_dump()
    b["solver_control"]["relaxation"] = a["solver_control"]["relaxation"]
    assert a == b
    with pytest.raises(CFDError):
        apply_repair(
            spec,
            RepairProposal(action="refine_mesh", factor=0.5, rationale="test"),
            "solver",
        )


def test_hard_parameter_guard(spec):
    d = spec.model_dump(mode="json")
    validate_hard_parameters(d, {"physics_spec": {"reference_pressure_pa": 101325}})
    with pytest.raises(CFDError):
        validate_hard_parameters(d, {"physics_spec": {"reference_pressure_pa": 2}})
