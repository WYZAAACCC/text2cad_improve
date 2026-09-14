"""The mesher's refinement field, and the shapes it can be asked for.

The field is a gmsh `MathEval` expression, so a region has to be something
that evaluates to a distance. Three shapes are: a cylinder about the axis, a
sphere about a point, and a box. Each returns zero inside itself and grows
outward, which is what makes the target size apply throughout the region and
ramp back to the web size outside it.

The cylinder form is the one that existed before the others and is checked
character for character: every config written earlier omits `kind`, and the
whole point of defaulting to it is that those mesh identically.

These build a real gmsh model and mesh it, because an expression that parses
is not the same as one gmsh can evaluate, and the difference is only visible
when it runs.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MESH_SECTOR = REPO / "app/text-to-cad/server/fea3d/mesh_sector.py"


def _module():
    spec = importlib.util.spec_from_file_location("mesh_sector", MESH_SECTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def field_for(zone: dict, web: float = 4.0) -> str:
    return _module()._size_expression(
        {"refinement": {"web_size_mm": web, "zones": [zone]}}
    )


# --- the expression --------------------------------------------------------

def test_a_zone_without_a_kind_is_still_the_annulus_it_always_was():
    """Character for character, because configs written before `kind`
    existed have to mesh exactly as they did."""
    zone = {"name": "rim", "size_mm": 1.0, "ramp_mm": 20.0,
            "r_center_mm": 288.5}
    assert field_for(zone) == (
        "(1.0 + (4.0 - 1.0) * min(1, abs(sqrt(x*x+y*y) - 288.5) / 20.0))"
    )


def test_a_sphere_is_zero_inside_and_grows_outside():
    """`max(0, d - radius)`, so the target size covers the sphere's interior.

    The bare distance from the centre would coarsen the size across the
    middle of the region, which is not what a region of that size means.
    """
    field = field_for({"name": "s", "kind": "sphere", "size_mm": 1.0,
                       "ramp_mm": 5.0, "center_mm": [1.0, 2.0, 3.0],
                       "radius_mm": 0.5})
    assert "max(0, sqrt(" in field
    assert "- 0.5)" in field


def test_a_box_is_zero_inside_and_grows_outside():
    field = field_for({"name": "b", "kind": "box", "size_mm": 1.0,
                       "ramp_mm": 5.0, "min_mm": [0.0, 0.0, 0.0],
                       "max_mm": [2.0, 4.0, 6.0]})
    assert "max(0," in field
    assert "abs(x - 1.0)" in field


def test_a_shape_that_is_not_a_distance_is_refused_by_name():
    with pytest.raises(ValueError) as exc:
        field_for({"name": "near", "kind": "faces", "size_mm": 1.0,
                   "ramp_mm": 5.0})
    assert "faces" in str(exc.value)
    assert "distance" in str(exc.value)


def test_a_sphere_without_a_centre_says_so():
    with pytest.raises(ValueError) as exc:
        field_for({"name": "s", "kind": "sphere", "size_mm": 1.0,
                   "ramp_mm": 5.0, "radius_mm": 1.0})
    assert "center_mm" in str(exc.value)


def test_a_zero_ramp_is_refused_wherever_it_appears():
    with pytest.raises(ValueError):
        field_for({"name": "x", "size_mm": 1.0, "ramp_mm": 0.0,
                   "r_center_mm": 10.0})


# --- and that gmsh can actually mesh with them -----------------------------

def _mesh_with(expression: str):
    gmsh = pytest.importorskip("gmsh")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("t")
        gmsh.model.occ.addBox(0, -5, -5, 5, 10, 10)
        gmsh.model.occ.synchronize()
        field = gmsh.model.mesh.field.add("MathEval")
        gmsh.model.mesh.field.setString(field, "F", expression)
        gmsh.model.mesh.field.setAsBackgroundMesh(field)
        gmsh.model.mesh.generate(3)
        types, tags, _ = gmsh.model.mesh.getElements(3)
        elements = [int(t) for arr in tags for t in arr]
        assert elements, "no elements were produced"
        return len(elements)
    finally:
        gmsh.finalize()


@pytest.mark.parametrize("zone", [
    {"name": "cyl", "kind": "cylinder", "size_mm": 1.0, "ramp_mm": 0.5,
     "r_center_mm": 2.0},
    {"name": "sph", "kind": "sphere", "size_mm": 1.0, "ramp_mm": 0.5,
     "center_mm": [2.0, 0.0, 0.0], "radius_mm": 0.5},
    {"name": "box", "kind": "box", "size_mm": 1.0, "ramp_mm": 0.5,
     "min_mm": [1.0, -1.0, -1.0], "max_mm": [3.0, 1.0, 1.0]},
    {"name": "legacy", "size_mm": 1.0, "ramp_mm": 0.5, "r_center_mm": 2.0},
])
def test_gmsh_meshes_a_box_with_each_kind(zone):
    assert _mesh_with(field_for(zone)) > 100
