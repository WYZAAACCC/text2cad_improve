"""The intent the materialiser is handed, assembled from the case.

This is the boundary where the case becomes the deck's input, and it is the
place a value with two possible sources goes wrong. A parameter file may state
a rotation speed and no axis; the frame stage has measured one from the model.
Nothing wrote the measured one into the intent, so `axis_origin_mm` arrived as
`None` and the intent model refused it - on the first run that ever reached
the materialise stage, before any of the meshing or solving this chain exists
for had been tried.

The rest of the file pins the other half: a value the parameter file *does*
state is not overwritten by the measurement.
"""
from __future__ import annotations

import pytest

from seekflow_structural.case.model import (
    BundleRef,
    Case,
    DomainDecision,
    Frame,
    LoadBinding,
    MaterialBinding,
    MaterialPoint,
    ModelFacts,
    Physics,
    RotationBinding,
    TemperatureBinding,
    Vec3,
    Written,
)
from seekflow_structural.errors import StructuralError
from seekflow_structural.pipeline.materialize import intent_from_case

MEASURED = Written(by_stage="frame", kind="measured", source="test")
DECIDED = Written(by_stage="domain", kind="agent_decision", source="test")
GIVEN = Written(by_stage="assembly", kind="user_input", source="test")


def a_case(*, rotation: RotationBinding, frame: Frame | None = None) -> Case:
    return Case(
        case_id="c",
        bundle=BundleRef(path="E:/bundle", lineage_id="D",
                         revision_id="rev-1"),
        model=ModelFacts(
            bounds_min_mm=Vec3(x=-300.0, y=-300.0, z=-42.2),
            bounds_max_mm=Vec3(x=300.0, y=300.0, z=38.0),
            r_max_mm=300.0,
            has_rotation_axis=True,
            frame=frame,
            symmetry_planes=[],
            bore_radius_mm=60.0,
            written=MEASURED,
        ),
        domain=DomainDecision(
            sector_deg=18.0, theta_low_deg=2.0,
            symmetry_planes_used=["z0"], written=DECIDED,
        ),
        physics=Physics(
            rotation=rotation,
            temperature=TemperatureBinding(
                model="radial_power_law", reference_temperature_c=20.0,
                payload={
                    "model": "radial_power_law",
                    "reference_temperature_c": 20.0,
                    "bore_c": 500.0, "rim_c": 650.0,
                    "bore_radius_mm": 60.0, "outer_radius_mm": 300.0,
                    "exponent": 1.0,
                },
                source="test",
            ),
            material=MaterialBinding(
                name="m", poisson_ratio=0.3, density_t_mm3=8.24e-9,
                points=[
                    MaterialPoint(temperature_c=20.0, young_mpa=205000.0,
                                  alpha_per_c=1.18e-5, yield_mpa=1100.0),
                    MaterialPoint(temperature_c=650.0, young_mpa=165000.0,
                                  alpha_per_c=1.54e-5, yield_mpa=950.0),
                ],
                source="test",
            ),
            blade_load=LoadBinding(
                model="equivalent_total_force",
                total_force_n_per_slot=10000.0,
                direction_rule="flank_surface_normal",
                distribution="area_weighted_uniform_pressure",
                source="test",
            ),
            written=GIVEN,
        ),
    )


Z_FRAME = Frame(
    axis_origin_mm=Vec3(x=0.0, y=0.0, z=0.0),
    axis_direction=Vec3(x=0.0, y=0.0, z=1.0),
)


def intent_of(case, **kwargs):
    from pathlib import Path

    return intent_from_case(
        case, Path("E:/job/mesh/mesh.inp"),
        Path("E:/job/solve/selected_face_nodes.json"), **kwargs
    )


def test_an_axis_the_parameter_file_omits_is_taken_from_the_model():
    """The frame stage measures the axis; nothing was reading it."""
    case = a_case(
        rotation=RotationBinding(rpm=15000.0, source="test"),
        frame=Z_FRAME,
    )
    intent = intent_of(case)
    assert intent.rotation.axis_origin_mm == [0.0, 0.0, 0.0]
    assert intent.rotation.axis_direction == [0.0, 0.0, 1.0]
    assert intent.rotation.rpm == 15000.0


def test_an_axis_the_parameter_file_states_is_not_overwritten():
    case = a_case(
        rotation=RotationBinding(
            rpm=15000.0,
            axis_origin_mm=Vec3(x=1.0, y=2.0, z=3.0),
            axis_direction=Vec3(x=0.0, y=0.0, z=2.0),
            source="test",
        ),
        frame=Z_FRAME,
    )
    intent = intent_of(case)
    assert intent.rotation.axis_origin_mm == [1.0, 2.0, 3.0]
    # the direction is normalised by the intent model, not by this code
    assert intent.rotation.axis_direction == [0.0, 0.0, 1.0]


def test_a_stated_origin_survives_while_the_direction_comes_from_the_model():
    """The two halves are filled independently, because a file may give one."""
    case = a_case(
        rotation=RotationBinding(
            rpm=15000.0, axis_origin_mm=Vec3(x=1.0, y=2.0, z=3.0),
            source="test",
        ),
        frame=Z_FRAME,
    )
    intent = intent_of(case)
    assert intent.rotation.axis_origin_mm == [1.0, 2.0, 3.0]
    assert intent.rotation.axis_direction == [0.0, 0.0, 1.0]


def test_no_axis_anywhere_is_a_named_refusal():
    """Not a pydantic dump from three frames deeper.

    The model genuinely has no rotation axis to offer and the file did not
    state one, so there is no case to solve. It says which of the two is
    missing and why that matters rather than listing field types.
    """
    case = a_case(
        rotation=RotationBinding(rpm=15000.0, source="test"), frame=None,
    )
    with pytest.raises(StructuralError) as exc:
        intent_of(case)
    assert exc.value.diagnostic.code == "rotation_axis_unknown"
    assert exc.value.diagnostic.stage == "materialize"


def test_the_normalised_frame_puts_the_axis_at_the_deck_origin():
    """When the mesh was re-expressed, the axis is +Z by construction.

    The measured axis describes the model; the deck describes the normalised
    frame. Writing the measured one there would put the axis somewhere it is
    not.
    """
    case = a_case(
        rotation=RotationBinding(
            rpm=15000.0,
            axis_origin_mm=Vec3(x=1.0, y=2.0, z=3.0),
            axis_direction=Vec3(x=0.0, y=1.0, z=0.0),
            source="test",
        ),
        frame=Z_FRAME,
    )
    intent = intent_of(case, axis=(0.0, 0.0, 1.0))
    assert intent.rotation.axis_origin_mm == [0.0, 0.0, 0.0]
    assert intent.rotation.axis_direction == [0.0, 0.0, 1.0]
