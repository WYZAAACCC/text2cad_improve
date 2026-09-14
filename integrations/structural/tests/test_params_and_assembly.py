"""Where the physical values come from, and what is checked about them.

Nothing here invents a value. The parameter file is the only source of a
rotation, a temperature, a material or a blade load, and a file missing one of
them is a missing input rather than an invitation to fill it in from a similar
part.

What the module does do is compare the user's own numbers with each other.
Those comparisons are the substance of these tests: a stated blade force
beside a stated mass, radius and speed is two answers to one question, and
reporting the residual - without deciding which of the two is wrong - is the
whole of the module's job.
"""
from __future__ import annotations

import pytest

from seekflow_structural.agents import assembly
from seekflow_structural.case.model import (
    LoadBinding,
    ModelFacts,
    Physics,
    RotationBinding,
    Vec3,
    Written,
)
from seekflow_structural.pipeline import params as params_module


def a_params(**overrides) -> dict:
    base = {
        "case_id": "unit",
        "confirmation_status": "unconfirmed",
        "rotation": {"rpm": 15000.0, "source": "unit"},
        "temperature": {
            "model": "radial_power_law",
            "reference_temperature_c": 20.0,
            "bore_c": 500.0,
            "rim_c": 650.0,
            "bore_radius_mm": 60.0,
            "outer_radius_mm": 300.0,
            "exponent": 1.0,
            "source": "unit",
        },
        "material": {
            "name": "unit",
            "source": "unit",
            "poisson_ratio": 0.3,
            "density_t_mm3": 8.24e-9,
            "points": [
                {"temperature_c": 20.0, "young_mpa": 205000.0,
                 "alpha_per_c": 1.18e-5, "yield_mpa": 1100.0},
                {"temperature_c": 650.0, "young_mpa": 165000.0,
                 "alpha_per_c": 1.54e-5, "yield_mpa": 950.0},
            ],
        },
        "blade_load": {
            "model": "equivalent_total_force",
            "total_force_n_per_slot": 10000.0,
            "direction_rule": "flank_surface_normal",
            "distribution": "area_weighted_uniform_pressure",
            "source": "unit",
        },
        "constraints": {"cyclic_symmetry": True, "axial_symmetry_z0": True,
                        "tangential_anchor": True, "source": "unit"},
    }
    base.update(overrides)
    return base


def a_model(r_max=300.0, bore=60.0) -> ModelFacts:
    return ModelFacts(
        bounds_min_mm=Vec3(x=-r_max, y=-r_max, z=-42.0),
        bounds_max_mm=Vec3(x=r_max, y=r_max, z=42.0),
        r_max_mm=r_max,
        bore_radius_mm=bore,
        written=Written(by_stage="frame", kind="measured"),
    )


def test_the_users_values_are_copied_through_unchanged():
    physics = params_module.physics_from_params(a_params(), "unit")
    assert physics.rotation.rpm == 15000.0
    assert physics.blade_load.total_force_n_per_slot == 10000.0
    assert physics.material.poisson_ratio == 0.3
    assert len(physics.material.points) == 2
    assert physics.temperature.model == "radial_power_law"
    assert physics.written.kind == "user_input"


def test_a_missing_section_is_a_missing_input_not_a_default():
    """The chain does not invent a rotation, a temperature or a material."""
    for section in ("rotation", "temperature", "material"):
        data = a_params()
        data.pop(section)
        with pytest.raises(params_module.ParamsIncomplete) as exc:
            params_module.physics_from_params(data, "unit")
        assert section in exc.value.missing


def test_a_blade_load_missing_is_not_fatal_here():
    """Some analyses have no blade load; the load stage says so, not this one."""
    data = a_params()
    data.pop("blade_load")
    physics = params_module.physics_from_params(data, "unit")
    assert physics.blade_load.total_force_n_per_slot is None


def test_a_stated_force_beside_a_mass_radius_and_speed_is_compared():
    data = a_params()
    data["blade_load"].update({
        "effective_mass_kg": 0.5,
        "center_of_mass_radius_mm": 250.0,
    })
    physics = params_module.physics_from_params(data, "unit")
    findings = params_module.check_consistency(physics, a_model())
    force_finding = [
        f for f in findings
        if f.quantity == "blade_load.total_force_n_per_slot"
    ]
    assert len(force_finding) == 1
    finding = force_finding[0]
    # 0.5 kg at 0.25 m and 15000 rpm is m r omega^2 = 308 kN, not the
    # stated 10 kN. The same 10 kN at that radius implies 16.2 g.
    assert finding.implied == pytest.approx(308425.0, rel=0.001)
    assert finding.stated == 10000.0
    assert finding.relative_difference > 1.0
    assert "one of the two" in finding.note


def test_the_comparison_is_reported_and_does_not_stop_anything():
    """A finding is a measurement. Which of the two numbers is wrong is the
    user's to know, and the run continues either way."""
    data = a_params()
    data["blade_load"].update({
        "effective_mass_kg": 0.5, "center_of_mass_radius_mm": 250.0,
    })
    physics = params_module.physics_from_params(data, "unit")
    findings = params_module.check_consistency(physics, a_model())
    assert findings, "a disagreeing pair should produce a finding"
    assert all(f.quantity for f in findings)


def test_a_consistent_pair_produces_a_finding_with_a_small_residual():
    data = a_params()
    # pick a mass and radius that give back exactly the stated force
    data["blade_load"].update({
        "effective_mass_kg": 0.01621, "center_of_mass_radius_mm": 250.0,
    })
    implied = params_module._rotor_force_n(15000.0, 0.01621, 250.0)
    data["blade_load"]["total_force_n_per_slot"] = implied
    physics = params_module.physics_from_params(data, "unit")
    findings = params_module.check_consistency(physics, a_model())
    force_finding = [
        f for f in findings
        if f.quantity == "blade_load.total_force_n_per_slot"
    ][0]
    assert force_finding.relative_difference < 1e-6


def test_the_temperature_profiles_radii_are_compared_with_the_part():
    """A profile whose radii are not the part's is a profile for a part that
    is not this one."""
    physics = params_module.physics_from_params(a_params(), "unit")
    findings = params_module.check_consistency(physics, a_model(r_max=250.0))
    outer = [
        f for f in findings if f.quantity == "temperature.outer_radius_mm"
    ][0]
    assert outer.stated == 300.0
    assert outer.implied == 250.0
    assert outer.relative_difference == pytest.approx(0.2)


def test_a_temperature_range_outside_the_material_data_is_reported():
    data = a_params()
    data["temperature"]["rim_c"] = 800.0  # material data stops at 650
    physics = params_module.physics_from_params(data, "unit")
    findings = params_module.check_consistency(physics, a_model())
    span = [f for f in findings if "material data" in f.quantity]
    assert span, "the field reaching past the material table should be flagged"
    assert "extrapolated" in span[0].note


def test_a_field_inside_the_material_range_is_not_flagged():
    physics = params_module.physics_from_params(a_params(), "unit")
    findings = params_module.check_consistency(physics, a_model())
    assert not [f for f in findings if "material data" in f.quantity]


def test_the_requirement_is_derived_from_the_load_not_hard_coded():
    """What the face-finding agent is asked for follows from the physics."""
    physics = params_module.physics_from_params(a_params(), "unit")
    requirement = assembly.requirement_for(physics)
    assert "blade load" in requirement
    assert "normal to the bearing surface" in requirement

    physics.blade_load = LoadBinding(
        direction_rule="radial_outward_from_rotation_axis"
    )
    other = assembly.requirement_for(physics)
    assert "radial pull" in other
    assert other != requirement


def test_an_unknown_load_rule_still_gets_a_usable_requirement():
    physics = Physics(
        rotation=RotationBinding(rpm=1.0),
        blade_load=LoadBinding(direction_rule="something_new"),
        written=Written(by_stage="assembly", kind="user_input"),
    )
    requirement = assembly.requirement_for(physics)
    assert "external load" in requirement


def test_the_mesh_reads_the_load_radius_from_the_case_and_nowhere_else():
    """The seam fix, as a property of the interface.

    `load_radius_for_mesh` is a function on the case rather than a parameter on
    the mesh stage, so there is exactly one way for the meshing stage to learn
    where the load is. A second way is how the two came apart.
    """
    from seekflow_structural.case.model import Case, LoadSurface
    from seekflow_structural.errors import StructuralError

    case = Case(
        case_id="unit",
        bundle=__import__(
            "seekflow_structural.case.model", fromlist=["BundleRef"]
        ).BundleRef(path="/tmp/b"),
    )
    with pytest.raises(StructuralError) as exc:
        assembly.load_radius_for_mesh(case)
    assert exc.value.diagnostic.code == "no_load_surface"

    case.load_surface = LoadSurface(
        feature="f", load_radius_mm=212.6664,
        written=Written(by_stage="assembly", kind="measured"),
    )
    assert assembly.load_radius_for_mesh(case) == pytest.approx(212.6664)
