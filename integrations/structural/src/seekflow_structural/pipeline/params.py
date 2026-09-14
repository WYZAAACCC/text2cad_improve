"""Reading the user's parameter file into the case.

This is the only place physical values enter the chain, and nothing here
invents one. A missing rotation, temperature, material or blade load is a
missing input, not something to be filled in from a similar part: the whole
point of the parameter file is that a person decided those numbers.

What this module does do is check the user's own numbers against each other.
Those checks are measurements, not verdicts - they report which two quantities
disagree and by how much, and the run continues either way. A stated blade
force that does not match the mass, radius and speed given beside it is worth
knowing about; it is not this module's job to decide which of the two is wrong.
"""
from __future__ import annotations

import math

from seekflow_structural.case.model import (
    ConsistencyFinding,
    ConstraintBinding,
    LoadBinding,
    MaterialBinding,
    MaterialPoint,
    Physics,
    RotationBinding,
    TemperatureBinding,
    Vec3,
    Written,
)

REQUIRED_SECTIONS = ("rotation", "temperature", "material")


class ParamsIncomplete(Exception):
    """A section the chain cannot run without is absent from the file."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(
            "the parameter file does not supply " + ", ".join(missing)
        )


def _vec(values) -> Vec3:
    return Vec3(x=float(values[0]), y=float(values[1]), z=float(values[2]))


def physics_from_params(params: dict, source: str) -> Physics:
    """The user's values, copied through unchanged."""
    missing = [name for name in REQUIRED_SECTIONS if not params.get(name)]
    if missing:
        raise ParamsIncomplete(missing)

    rotation = params["rotation"]
    temperature = params["temperature"]
    material = params["material"]
    load = params.get("blade_load") or {}
    constraints = params.get("constraints") or {}

    # The axis may be given with the rotation or measured later; absent means
    # the parameter file did not say, which the frame stage resolves.
    origin = rotation.get("axis_origin_mm")
    direction = rotation.get("axis_direction")

    return Physics(
        rotation=RotationBinding(
            rpm=float(rotation["rpm"]),
            axis_origin_mm=_vec(origin) if origin else None,
            axis_direction=_vec(direction) if direction else None,
            source=str(rotation.get("source", "")),
        ),
        temperature=TemperatureBinding(
            model=str(temperature.get("model", "")),
            reference_temperature_c=float(
                temperature.get("reference_temperature_c", 20.0)
            ),
            payload=dict(temperature),
            source=str(temperature.get("source", "")),
        ),
        material=MaterialBinding(
            name=str(material.get("name", "")),
            poisson_ratio=float(material["poisson_ratio"]),
            density_t_mm3=float(material["density_t_mm3"]),
            points=[
                MaterialPoint(**point) for point in material["points"]
            ],
            source=str(material.get("source", "")),
        ),
        blade_load=LoadBinding(
            model=str(load.get("model", "")),
            total_force_n_per_slot=(
                float(load["total_force_n_per_slot"])
                if load.get("total_force_n_per_slot") is not None
                else None
            ),
            effective_mass_kg=(
                float(load["effective_mass_kg"])
                if load.get("effective_mass_kg") is not None
                else None
            ),
            center_of_mass_radius_mm=(
                float(load["center_of_mass_radius_mm"])
                if load.get("center_of_mass_radius_mm") is not None
                else None
            ),
            blades_per_slot=int(load.get("blades_per_slot", 1)),
            direction_rule=str(load.get("direction_rule", "")),
            distribution=str(load.get("distribution", "")),
            source=str(load.get("source", "")),
        ),
        constraints=ConstraintBinding(
            cyclic_symmetry=bool(constraints.get("cyclic_symmetry")),
            axial_symmetry_z0=bool(constraints.get("axial_symmetry_z0")),
            tangential_anchor=bool(constraints.get("tangential_anchor")),
            source=str(constraints.get("source", "")),
        ),
        written=Written(by_stage="setup", kind="user_input", source=source),
    )


def _rotor_force_n(rpm: float, mass_kg: float, radius_mm: float) -> float:
    """m r omega^2, with the radius in metres and the answer in newtons."""
    omega = rpm * 2.0 * math.pi / 60.0
    return mass_kg * (radius_mm / 1000.0) * omega * omega


def check_consistency(physics: Physics, model=None) -> list[ConsistencyFinding]:
    """Pairs of the user's own numbers, with the gap between them measured.

    Every comparison that can be made is reported, not only the ones that
    disagree. The residual is the substance - a pair that agrees to six
    decimals is evidence that the run read the parameter file it was given,
    and dropping those entries would throw that evidence away and leave only
    the complaints. What a reader must not do is read the length of this list
    as a count of problems: two entries whose `relative_difference` is zero
    are two checks that passed.

    Every finding names the two quantities compared, so a reader can tell
    which of them to look at. None of them stops the run.
    """
    findings: list[ConsistencyFinding] = []
    load = physics.blade_load
    rotation = physics.rotation

    # A stated force beside a stated mass, radius and speed is two answers to
    # one question. Which is right is the user's to know.
    if (
        load.total_force_n_per_slot
        and load.effective_mass_kg
        and load.center_of_mass_radius_mm
        and rotation.rpm
    ):
        implied = _rotor_force_n(
            rotation.rpm, load.effective_mass_kg,
            load.center_of_mass_radius_mm,
        )
        stated = float(load.total_force_n_per_slot)
        findings.append(
            ConsistencyFinding(
                quantity="blade_load.total_force_n_per_slot",
                stated=stated,
                implied=round(implied, 6),
                relative_difference=round(
                    abs(stated - implied) / max(abs(stated), 1e-9), 6
                ),
                note=(
                    "the stated force and the force implied by the mass, "
                    "radius and speed differ; one of the two is not what was "
                    "meant"
                ),
            )
        )

    temperature = physics.temperature.payload or {}
    outer = temperature.get("outer_radius_mm")
    if model is not None and outer is not None:
        # A temperature profile whose outer radius is inside the part leaves
        # material beyond it held at the rim value; one beyond the part wastes
        # profile on nothing.
        findings.append(
            ConsistencyFinding(
                quantity="temperature.outer_radius_mm",
                stated=float(outer),
                implied=float(model.r_max_mm),
                relative_difference=round(
                    abs(float(outer) - float(model.r_max_mm))
                    / max(abs(float(model.r_max_mm)), 1e-9),
                    6,
                ),
                note=(
                    "the profile's outer radius against the measured outer "
                    "radius of the part"
                ),
            )
        )

    bore = temperature.get("bore_radius_mm")
    if model is not None and bore is not None and model.bore_radius_mm:
        findings.append(
            ConsistencyFinding(
                quantity="temperature.bore_radius_mm",
                stated=float(bore),
                implied=float(model.bore_radius_mm),
                relative_difference=round(
                    abs(float(bore) - float(model.bore_radius_mm))
                    / max(abs(float(model.bore_radius_mm)), 1e-9),
                    6,
                ),
                note=(
                    "the profile's bore radius against the measured bore of "
                    "the part"
                ),
            )
        )

    material_temperatures = [
        point.temperature_c for point in physics.material.points
    ]
    if material_temperatures:
        span = temperature_span(physics)
        if span is not None:
            low, high = span
            if low < min(material_temperatures) or high > max(
                material_temperatures
            ):
                findings.append(
                    ConsistencyFinding(
                        quantity="temperature range vs material data",
                        stated=f"{low:.1f}..{high:.1f} C",
                        implied=(
                            f"{min(material_temperatures):.1f}.."
                            f"{max(material_temperatures):.1f} C"
                        ),
                        relative_difference=None,
                        note=(
                            "the temperature field reaches outside the range "
                            "the material data covers, so the properties used "
                            "there are extrapolated"
                        ),
                    )
                )
    return findings


def temperature_span(physics: Physics) -> tuple[float, float] | None:
    """The coldest and hottest the field can be, from what it declares."""
    payload = physics.temperature.payload or {}
    model = physics.temperature.model
    if model == "isothermal":
        value = payload.get("uniform_c")
        return (float(value), float(value)) if value is not None else None
    if model == "radial_power_law":
        bore, rim = payload.get("bore_c"), payload.get("rim_c")
        if bore is None or rim is None:
            return None
        return (min(float(bore), float(rim)), max(float(bore), float(rim)))
    return None
