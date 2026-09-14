"""The CAD-face to element-face bridge, and the table it depends on.

Two things here are easy to get wrong in ways no downstream number reveals.
`EMORE` looks like it carries an element id and does not, so a parser that
reads it naively produces a connectivity that is wrong for most elements and
right for a few. And the SOLID187 face numbering is a convention that has to
come from measurement - a wrong `LKEY` puts the load on a neighbouring face
with exactly the same resultant.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


from conftest import PROBES  # noqa: E402

from seekflow_structural.core.element_face_map import (  # noqa: E402
    SOLID187_FACE_LKEY,
    build,
    read_mesh,
)

PROBE = PROBES / "solid187_face_probe" / "probe_report.json"

# The reference tetrahedron used by the probe, and by the tests below.
I = (0.0, 0.0, 0.0)
J = (10.0, 0.0, 0.0)
K = (0.0, 10.0, 0.0)
L = (0.0, 0.0, 10.0)
CORNERS = (I, J, K, L)
MIDSIDE_PAIRS = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))

# Corner-node index triples, matching element_face_map's internal ordering.
FACE_TRIPLES = ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))


def write_mesh(path: Path, elements: list[tuple[float, float, float]]) -> None:
    """One tetrahedron per offset, each numbered contiguously as APDL does."""
    lines = ["/NOPR"]
    node_id = 0
    connectivity = []
    for offset in elements:
        ids = []
        points = [tuple(c[i] + offset[i] for i in range(3)) for c in CORNERS]
        for a, b in MIDSIDE_PAIRS:
            points.append(
                tuple((CORNERS[a][i] + CORNERS[b][i]) / 2.0 + offset[i]
                      for i in range(3))
            )
        for xyz in points:
            node_id += 1
            ids.append(node_id)
            lines.append("N,%d,%.10g,%.10g,%.10g" % (node_id, *xyz))
        connectivity.append(ids)
        lines.append("EN,%d,%s" % (len(connectivity),
                                   ",".join(str(v) for v in ids[:8])))
        # The two extra node ids, which the reader must treat positionally.
        lines.append("EMORE,%d,%d" % (ids[8], ids[9]))
    lines += ["TYPE,1", "MAT,1", "/GOPR"]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def test_emore_is_read_as_two_more_node_ids():
    """The trap: EMORE's fields are node ids, not an element id and a node id.

    Read the wrong way, element 2 would pick up a node belonging to element 1
    and its connectivity would be wrong without any error being raised.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mesh.inp"
        write_mesh(path, [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)])
        nodes, elements = read_mesh(path)

    assert len(nodes) == 20
    assert sorted(elements) == [1, 2]
    assert len(elements[1]) == 10, "a SOLID187 has ten nodes"
    assert len(elements[2]) == 10
    # Element 2's nodes are 11..20, not 9 and 10.
    assert elements[2] == list(range(11, 21))
    assert elements[1] == list(range(1, 11))


def test_lkey_table_is_the_one_the_probe_measured():
    """Changing the table without re-running the probe must fail here.

    The probe loaded one LKEY per element on a known tetrahedron and read back
    which nodes carried the load. The mid-side nodes it found identify the
    face, and so tie the constant to evidence rather than to a document.
    """
    report = json.loads(PROBE.read_text(encoding="utf-8"))
    assert report["lkey_table_confirmed"] is True
    assert report["sign_confirmed"] is True
    assert report["consistent_load_vector_confirmed"] is True

    # Invert the production table rather than restating it, so this test
    # actually checks the constant the code uses.
    triple_by_lkey = {
        lkey: tuple(sorted(triple))
        for triple, lkey in SOLID187_FACE_LKEY.items()
    }

    for entry in report["faces"]:
        element = entry["element"]
        triple = triple_by_lkey[element]
        expected = {
            5 + index
            for index, (a, b) in enumerate(MIDSIDE_PAIRS)
            if a in triple and b in triple
        }
        observed = {
            node - (element - 1) * 10 for node in entry["loaded_midside_nodes"]
        }
        assert observed == expected, (
            f"LKEY {element} loaded mid-side nodes {sorted(observed)}, but the "
            f"table says face {triple} whose mid-side nodes are "
            f"{sorted(expected)}"
        )
        assert entry["loaded_corner_nodes"] == [], (
            "a uniform pressure on a quadratic face must put nothing on the "
            "corner nodes"
        )
        assert entry["direction_dot_outward"] == pytest.approx(1.0, abs=1e-6), (
            "a positive pressure must push into the element"
        )


def _selection(face_index, node_ids, normal, area):
    return {
        "per_face": {
            str(face_index): {
                "node_ids": list(node_ids),
                "normal_xyz": list(normal),
                "area_mm2": area,
            }
        }
    }


def test_a_face_on_the_plane_is_assigned():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mesh.inp"
        write_mesh(path, [(0.0, 0.0, 0.0)])
        nodes, elements = read_mesh(path)

    # Face {I, J, K} lies in z = 0 with outward normal (0, 0, -1).
    selection = _selection(1, [1, 2, 3], [0.0, 0.0, -1.0], 50.0)
    mapping = build(nodes, elements, selection)

    faces = mapping.faces[1]
    assert len(faces) == 1
    face = faces[0]
    assert face.lkey == 1, "face {I,J,K} is LKEY 1"
    assert face.corner_nodes == (1, 2, 3)
    assert face.area_mm2 == pytest.approx(50.0)
    assert face.outward_normal == pytest.approx((0.0, 0.0, -1.0))
    assert mapping.ambiguous_by_face.get(1, 0) == 0


def test_a_coplanar_but_mis_oriented_face_is_rejected():
    """The normal test is what stops a neighbouring face being loaded too.

    Without it, a selected face's plane would also capture an element face
    that lies in the same plane but belongs to a different CAD face.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mesh.inp"
        write_mesh(path, [(0.0, 0.0, 0.0)])
        nodes, elements = read_mesh(path)

    # Same node set, but the OCC normal points into the solid instead of out.
    selection = _selection(1, [1, 2, 3], [0.0, 0.0, 1.0], 50.0)
    mapping = build(nodes, elements, selection)
    assert mapping.faces[1] == []
    assert mapping.rejected_by_normal_by_face.get(1, 0) == 1
    assert any("produced no element face" in note for note in mapping.limits)


def test_a_face_shared_by_two_selections_is_counted_not_guessed():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mesh.inp"
        write_mesh(path, [(0.0, 0.0, 0.0)])
        nodes, elements = read_mesh(path)

    selection = {
        "per_face": {
            "1": {"node_ids": [1, 2, 3], "normal_xyz": [0.0, 0.0, -1.0],
                  "area_mm2": 50.0},
            "2": {"node_ids": [1, 2, 3], "normal_xyz": [0.0, 0.0, -1.0],
                  "area_mm2": 50.0},
        }
    }
    mapping = build(nodes, elements, selection)
    assert mapping.faces[1] == []
    assert mapping.faces[2] == []
    assert mapping.ambiguous_by_face == {1: 1, 2: 1}
    assert any("cannot be told" in note for note in mapping.limits)


def test_the_four_faces_of_one_tet_all_map_to_their_own_lkey():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mesh.inp"
        write_mesh(path, [(0.0, 0.0, 0.0)])
        nodes, elements = read_mesh(path)

    expected = {
        1: ((1, 2, 3), (0.0, 0.0, -1.0)),
        2: ((1, 2, 4), (0.0, -1.0, 0.0)),
        3: ((2, 3, 4), (1.0, 1.0, 1.0)),
        4: ((3, 1, 4), (-1.0, 0.0, 0.0)),
    }
    selection = {"per_face": {}}
    for lkey, (nodes_of_face, normal) in expected.items():
        selection["per_face"][str(lkey)] = {
            "node_ids": list(nodes_of_face),
            "normal_xyz": list(normal),
            "area_mm2": 50.0,
        }
    mapping = build(nodes, elements, selection)
    for lkey in expected:
        assert len(mapping.faces[lkey]) == 1, f"LKEY {lkey} mapped nothing"
        assert mapping.faces[lkey][0].lkey == lkey


def test_the_audit_reports_coverage_rather_than_assuming_it():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mesh.inp"
        write_mesh(path, [(0.0, 0.0, 0.0)])
        nodes, elements = read_mesh(path)

    # Claim a much larger CAD face than the mesh covers, as happens when the
    # analysis domain clips a selected face - the honest reading is the
    # fraction, not a pass/fail.
    selection = _selection(1, [1, 2, 3], [0.0, 0.0, -1.0], 200.0)
    mapping = build(nodes, elements, selection)
    audit = mapping.to_audit()
    assert audit["mapped_area_total_mm2"] == pytest.approx(50.0)
    assert audit["occ_area_total_mm2"] == pytest.approx(200.0)
    assert audit["mapped_area_fraction"] == pytest.approx(0.25)
    assert audit["uncovered_area_mm2"] == pytest.approx(150.0)
    # Only accepted faces are stored, and acceptance requires agreement, so
    # this reads +1 by construction. It is here to show the audit carries the
    # number rather than to discover anything on this input.
    assert audit["normal_agreement_min"] == pytest.approx(1.0)


def test_runtime_error_guard_is_absent_but_empty_faces_are_reported():
    """An empty mapping must never be loadable.

    The node path raises "maps to zero mesh nodes"; the element-face path has
    to be at least as loud, because an empty set would otherwise integrate to
    a resultant of zero while the audit still claimed the target.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mesh.inp"
        write_mesh(path, [(0.0, 0.0, 0.0)])
        nodes, elements = read_mesh(path)

    selection = _selection(7, [999], [0.0, 0.0, -1.0], 10.0)
    mapping = build(nodes, elements, selection)
    assert mapping.faces[7] == []
    assert mapping.mapped_area_total_mm2() == 0.0
    assert any("produced no element face" in note for note in mapping.limits)
