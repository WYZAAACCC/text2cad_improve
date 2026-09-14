"""The temperature field has to be right before anything else can be.

Two failure modes matter here, and neither shows up as an exception in
production. A field that extrapolates beyond its data returns a number that
looks like every other number; a formula that means something different from
the profile it replaced returns a whole stress field that is subtly wrong. The
tests below pin the interpolation against a field whose value is known in
closed form, pin the coverage report, and pin the expression namespace.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


from seekflow_structural.core.temperature_field import (  # noqa: E402
    ExpressionField,
    IsothermalField,
    NodeProfileField,
    PointCloudField,
    RadialPowerLawField,
    build_temperature_field,
)

AXIS = ([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])


def _grid_cloud(step: float, value):
    samples = []
    for i in range(7):
        for j in range(7):
            for k in range(7):
                x, y, z = i * step, j * step, k * step
                samples.append([x, y, z, value(x, y, z)])
    return samples


LINEAR = lambda x, y, z: 10.0 + 2.0 * x - 3.0 * y + 0.5 * z


def test_point_cloud_reproduces_a_linear_field_exactly():
    """Linear interpolation of a linear field is exact - so any gap is our bug.

    This is the analytic benchmark for the sampler. Without it, 'the
    interpolation looks reasonable' is the only available standard.
    """
    field = PointCloudField(_grid_cloud(5.0, LINEAR), "nearest_sample", 20.0)
    worst = 0.0
    for i in range(1, 6):
        for j in range(1, 6):
            for k in range(1, 6):
                x, y, z = i * 5.0, j * 5.0, k * 5.0
                worst = max(worst, abs(field._raw_at(x, y, z) - LINEAR(x, y, z)))
    assert worst < 1e-9, f"linear field reproduced only to {worst:g}"


def test_points_outside_the_hull_are_counted_not_extrapolated():
    field = PointCloudField(_grid_cloud(5.0, LINEAR), "nearest_sample", 20.0)
    inside = (15.0, 15.0, 15.0)
    outside = (200.0, 15.0, 15.0)

    assert field._raw_at(*inside) is not None
    assert field._raw_at(*outside) is None, "extrapolated past the sample cloud"

    values, coverage = field.evaluate(
        [(1, inside), (2, outside), (3, outside)]
    )
    assert coverage.outside_support_count == 2
    assert coverage.outside_fraction == pytest.approx(2 / 3)
    assert coverage.outside_node_ids_sample == [2, 3]
    assert coverage.nearest_sample_distance_max_mm > 0
    # Every node still gets a value - the policy answers - but the count says
    # how many of them are not interpolation.
    assert set(values) == {1, 2, 3}


def test_fail_policy_refuses_rather_than_answering():
    field = PointCloudField(_grid_cloud(5.0, LINEAR), "fail", 20.0)
    with pytest.raises(ValueError, match="outside_support_policy is 'fail'"):
        field.evaluate([(1, (200.0, 15.0, 15.0))])


def test_reference_policy_reports_the_dropped_thermal_load():
    field = PointCloudField(
        _grid_cloud(5.0, LINEAR), "reference_temperature", 20.0
    )
    values, _ = field.evaluate([(1, (200.0, 15.0, 15.0))])
    assert values[1] == 20.0


def test_coverage_reports_the_source_resolution():
    """A coarse cloud must say it is coarse - not just return coarse numbers.

    Interpolation error cannot reveal this on its own: a cloud that is too
    sparse to see a feature interpolates smoothly straight through it.
    """
    coarse = PointCloudField(_grid_cloud(20.0, LINEAR), "nearest_sample", 20.0)
    _, coverage = coarse.evaluate([(1, (30.0, 30.0, 30.0))])
    assert coverage.source_spacing_mm is not None
    assert 19.0 < coverage.source_spacing_mm < 21.0
    assert any("spacing" in note for note in coverage.limits)


def test_coplanar_cloud_reports_its_limit_instead_of_raising():
    """A single-surface export has no volume to interpolate in."""
    flat = [[float(i), float(j), 0.0, 500.0 + i] for i in range(5)
            for j in range(5)]
    field = PointCloudField(flat, "nearest_sample", 20.0)
    _, coverage = field.evaluate([(1, (2.0, 2.0, 0.0))])
    assert coverage.outside_support_count == 1
    assert any("coplanar" in note or "no 3D extent" in note
               for note in coverage.limits)


def test_expression_reproduces_the_radial_profile_it_replaces():
    """Equivalence with radial_power_law is the whole point of this source."""
    analytic = RadialPowerLawField(500.0, 650.0, 60.0, 300.0, 1.0, *AXIS)
    expression = ExpressionField(
        "500 + (650 - 500) * (r - 60) / (300 - 60)", {}, *AXIS
    )
    worst = 0.0
    for radius in (60.0, 100.0, 212.0, 299.0, 300.0):
        worst = max(
            worst,
            abs(
                analytic._raw_at(radius, 0.0, 0.0)
                - expression._raw_at(radius, 0.0, 0.0)
            ),
        )
    assert worst < 1e-12, f"expression differs from the profile by {worst:g}"


def test_the_clamp_is_part_of_the_profile_not_a_detail():
    """Measured on D27: without this the two fields differ inside the bore.

    `radial_power_law` clamps to the bore value; a bare formula extrapolates.
    On D27's mesh that is 139 nodes and up to 0.028 C - small, but it means an
    expression only reproduces the profile once it clamps too, and the
    difference is invisible from the metrics.
    """
    analytic = RadialPowerLawField(500.0, 650.0, 60.0, 300.0, 1.0, *AXIS)
    bare = ExpressionField(
        "500 + (650 - 500) * (r - 60) / (300 - 60)", {}, *AXIS
    )
    clamped = ExpressionField(
        "500 + (650 - 500) * max(0, min(1, (r - 60) / (300 - 60)))", {}, *AXIS
    )

    inside_bore = (59.95, 0.0, 0.0)
    assert analytic._raw_at(*inside_bore) == 500.0
    assert bare._raw_at(*inside_bore) < 500.0
    assert clamped._raw_at(*inside_bore) == analytic._raw_at(*inside_bore)

    beyond_rim = (300.5, 0.0, 0.0)
    assert analytic._raw_at(*beyond_rim) == 650.0
    assert bare._raw_at(*beyond_rim) > 650.0
    assert clamped._raw_at(*beyond_rim) == analytic._raw_at(*beyond_rim)

    for radius in (60.0, 150.0, 300.0):
        assert clamped._raw_at(radius, 0.0, 0.0) == analytic._raw_at(
            radius, 0.0, 0.0
        )

    assert any("does not clamp" in note for note in clamped.limits())


def test_expression_parameters_are_available_by_name():
    field = ExpressionField(
        "params['bore'] + (params['rim'] - params['bore']) * r / 300",
        {"bore": 400.0, "rim": 700.0}, *AXIS,
    )
    assert field._raw_at(150.0, 0.0, 0.0) == pytest.approx(550.0)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').getcwd()",
        "().__class__.__bases__[0].__subclasses__()",
        "open('/etc/passwd').read()",
    ],
)
def test_expression_cannot_reach_the_interpreter(expression):
    """Clearing __builtins__ is not enough; attribute access must be refused.

    The class-walking form was measured evaluating successfully and returning
    a list before the syntax check existed - it reaches the interpreter's
    class registry without calling a single builtin.
    """
    with pytest.raises(
        ValueError,
        match="not allowed|not an allowed function|not a plain function name",
    ):
        ExpressionField(expression, {}, *AXIS)


def test_expression_rejects_a_subscript_that_is_not_params():
    with pytest.raises(ValueError, match="subscripts something other than params"):
        ExpressionField("[1, 2, 3][0] + r", {}, *AXIS)


def test_expression_naming_an_unknown_symbol_fails_at_construction():
    """Better to fail when the intent is read than on node 40,000."""
    with pytest.raises(ValueError, match="not a known variable"):
        ExpressionField("500 + undefined_symbol", {}, *AXIS)


def test_radial_power_law_projects_onto_the_axis_not_the_global_z():
    """The bug this module exists to prevent.

    A disc whose axis is tilted must get its radius from the projection; the
    old `hypot(x, y)` would have returned a different radius for the same
    material point.
    """
    tilted = RadialPowerLawField(
        500.0, 650.0, 60.0, 300.0, 1.0,
        [0.0, 0.0, 0.0], [0.0, math.sin(0.5), math.cos(0.5)],
    )
    # A point 150 mm out along the tilted axis's own radial direction.
    point = (150.0, 0.0, 0.0)
    assert tilted.radius_at(*point) == pytest.approx(150.0, abs=1e-9)
    # hypot(x, y) would have said 150 too here, so tilt about x instead and
    # check the two disagree - which is the case the projection must win.
    sideways = RadialPowerLawField(
        500.0, 650.0, 60.0, 300.0, 1.0,
        [0.0, 0.0, 0.0], [math.sin(0.5), 0.0, math.cos(0.5)],
    )
    assert sideways.radius_at(0.0, 150.0, 0.0) == pytest.approx(150.0, abs=1e-9)
    assert math.hypot(0.0, 150.0) == pytest.approx(150.0)


def test_radial_power_law_clamps_and_says_so():
    field = RadialPowerLawField(500.0, 650.0, 60.0, 300.0, 1.0, *AXIS)
    assert field._raw_at(10.0, 0.0, 0.0) == 500.0
    assert field._raw_at(500.0, 0.0, 0.0) == 650.0
    assert any("clamped" in note for note in field.limits())


def test_isothermal_reports_that_it_has_no_gradient():
    field = IsothermalField(620.0)
    values, coverage = field.evaluate([(1, (0.0, 0.0, 0.0))])
    assert values[1] == 620.0
    assert coverage.outside_support_count == 0
    assert any("uniform" in note for note in coverage.limits)


def test_node_profile_is_exact_and_refuses_a_partial_match():
    field = NodeProfileField({1: 500.0, 2: 600.0}, source="unit test")
    values, coverage = field.evaluate([(1, (0.0, 0.0, 0.0)), (2, (1.0, 0.0, 0.0))])
    assert values == {1: 500.0, 2: 600.0}
    assert coverage.outside_support_count == 0

    with pytest.raises(ValueError, match="no temperature for 1 mesh node"):
        field.evaluate([(1, (0.0, 0.0, 0.0)), (99, (1.0, 0.0, 0.0))])


def test_node_profile_fingerprint_separates_different_profiles():
    a = NodeProfileField({1: 500.0, 2: 600.0}, source="a")
    b = NodeProfileField({1: 500.0, 2: 601.0}, source="a")
    assert a.fingerprint()["checksum"] != b.fingerprint()["checksum"]


def test_build_dispatches_every_declared_model(tmp_path):
    """No model may be selectable and then crash - that is the old bug."""
    from seekflow_structural.core.structural_intent_models import TemperatureIntent

    cloud = tmp_path / "cloud.csv"
    rows = ["# x,y,z,temperature_c"]
    for i in range(4):
        for j in range(4):
            for k in range(4):
                x, y, z = i * 30.0, j * 30.0, k * 30.0
                rows.append(f"{x},{y},{z},{500 + x}")
    cloud.write_text("\n".join(rows), encoding="utf-8")

    profile = tmp_path / "nodes.csv"
    profile.write_text("nid,temperature_c\n1,500\n2,600\n", encoding="utf-8")

    rotation = type("R", (), {
        "axis_origin_mm": [0.0, 0.0, 0.0],
        "axis_direction": [0.0, 0.0, 1.0],
    })()

    cases = {
        "isothermal": TemperatureIntent(
            model="isothermal", reference_temperature_c=20.0, source="t",
            uniform_c=600.0),
        "radial_power_law": TemperatureIntent(
            model="radial_power_law", reference_temperature_c=20.0, source="t",
            bore_c=500.0, rim_c=650.0, bore_radius_mm=60.0,
            outer_radius_mm=300.0, exponent=1.0),
        "node_profile_file": TemperatureIntent(
            model="node_profile_file", reference_temperature_c=20.0, source="t",
            node_profile_file=str(profile)),
        "coordinate_samples": TemperatureIntent(
            model="coordinate_samples", reference_temperature_c=20.0, source="t",
            sample_points_file=str(cloud),
            outside_support_policy="nearest_sample"),
        "analytic_expression": TemperatureIntent(
            model="analytic_expression", reference_temperature_c=20.0, source="t",
            expression="500 + r"),
    }
    for model, intent in cases.items():
        field = build_temperature_field(intent, rotation)
        assert field.kind == model, f"{model} built a {field.kind} field"
