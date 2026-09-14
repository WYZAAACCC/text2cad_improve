"""Does a uniform pressure produce a uniform stress?

A block pushed on one face with a uniform pressure, held by rollers on the
other three, has an exact solution that does not depend on the mesh at all:
sigma_xx = -p everywhere, sigma_yy = sigma_zz = 0. That is the constant-stress
patch test, and it is the one experiment that separates a consistent load
vector from an inconsistent one.

It is the experiment the load change needs, because the two schemes differ
*only* in how the face force is spread over the face's nodes:

  * equal force at every node of the face - the implementation being replaced -
    puts a share on the corner nodes, which the element shape functions say
    should carry none, so the stress is not uniform and moves with the mesh;
  * SFE lets ANSYS build the consistent load vector, and the stress is uniform
    to solver precision however the mesh is arranged.

The mesh here is deliberately unstructured and irregular, because a patch test
on a regular mesh can pass by symmetry for reasons that have nothing to do with
the load vector.

The SFE lines are produced by element_face_map, the same code the production
path uses, so what is under test is the emission logic and not a copy of it.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "_structural_experiment"))

from seekflow_structural.core.element_face_map import build as build_face_map  # noqa: E402

ANSYS_CANDIDATES = (
    Path(r"D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ANSYS181.exe"),
    Path(r"D:\ANSYS181\ANSYS Inc\v181\ANSYS\bin\winx64\ansys181.exe"),
    Path(r"C:\Program Files\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"),
)

# The gmsh tet10 ordering differs from SOLID187's in the last two nodes.
PERM = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]

SIZE_MM = (40.0, 30.0, 20.0)
PRESSURE_MPA = 10.0
YOUNG_MPA = 200000.0
POISSON = 0.3


def mesh_block(work: Path, element_size: float):
    """An irregular tet mesh of a box, plus the boundary face node sets."""
    import gmsh

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("patch")
        gmsh.model.occ.addBox(0.0, 0.0, 0.0, *SIZE_MM)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", element_size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", element_size * 0.4)
        # Second order, so the element is a SOLID187; and second-order
        # *linear*, which keeps the six-node faces flat - that is what makes a
        # corner triangle's area the whole face's area, and therefore what
        # makes the mapped area the pressure is divided by correct.
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)
        gmsh.model.mesh.generate(3)

        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        points = {
            int(node_tags[i]): (
                coords[3 * i], coords[3 * i + 1], coords[3 * i + 2]
            )
            for i in range(len(node_tags))
        }
        element_types, _, element_nodes = gmsh.model.mesh.getElements(3)
        if list(element_types) != [11]:
            raise SystemExit(f"expected pure tet10, got {list(element_types)}")
        connectivity = [
            [int(v) for v in element_nodes[0][10 * i: 10 * i + 10]]
            for i in range(len(element_nodes[0]) // 10)
        ]
    finally:
        gmsh.finalize()

    lines = ["/NOPR"]
    for tag, xyz in sorted(points.items()):
        lines.append("N,%d,%.10g,%.10g,%.10g" % (tag, *xyz))
    lines += ["TYPE,1", "MAT,1"]
    for index, conn in enumerate(connectivity, start=1):
        ordered = [conn[i] for i in PERM]
        lines.append("EN,%d,%s" % (index, ",".join(str(v) for v in ordered[:8])))
        lines.append("EMORE,%d,%d" % (ordered[8], ordered[9]))
    lines.append("/GOPR")
    mesh_path = work / "mesh.inp"
    mesh_path.write_text("\n".join(lines) + "\n", encoding="ascii")

    # The loaded face is x = Lx, whose outward normal is +x.
    loaded = [
        tag for tag, xyz in points.items()
        if abs(xyz[0] - SIZE_MM[0]) < 1e-6
    ]
    return mesh_path, points, loaded


def selection_payload(loaded_nodes) -> dict:
    return {
        "union_node_ids": list(loaded_nodes),
        "per_face": {
            "1": {
                "node_ids": list(loaded_nodes),
                "normal_xyz": [1.0, 0.0, 0.0],
                "area_mm2": SIZE_MM[1] * SIZE_MM[2],
            }
        },
    }


def load_table(selection: dict, mesh_path: Path, work: Path) -> dict:
    from seekflow_structural.core.element_face_map import read_mesh

    nodes, elements = read_mesh(mesh_path)
    mapping = build_face_map(nodes, elements, selection)
    area = mapping.mapped_area_total_mm2()
    if area <= 0:
        raise SystemExit("the loaded face mapped to no element face")
    pressure = PRESSURE_MPA

    lines = []
    for faces in mapping.faces.values():
        for face in faces:
            lines.append(
                "SFE,%d,%d,PRES,0,%.10g" % (face.elem, face.lkey, pressure)
            )
    # The same face, loaded the old way: the face's force split equally among
    # its nodes. Both decks are otherwise identical, so the comparison isolates
    # the load vector.
    nodal = []
    force_magnitude = PRESSURE_MPA * area
    per_node = force_magnitude / len(selection["union_node_ids"])
    for node in selection["union_node_ids"]:
        # Negative: the pressure pushes the block in -x, and the two decks have
        # to differ only in how the face force is spread, not in which way it
        # points. Getting this wrong made the nodal run look far worse than it
        # is, and in the opposite direction.
        nodal.append("F,%d,FX,%.10g" % (node, -per_node))

    (work / "load_sfe.inp").write_text(
        "\n".join(lines) + "\n", encoding="ascii"
    )
    (work / "load_nodal.inp").write_text(
        "\n".join(nodal) + "\n", encoding="ascii"
    )
    return {
        "mapped_area_mm2": area,
        "pressure_mpa": pressure,
        "element_face_count": mapping.element_face_count(),
        "loaded_node_count": len(selection["union_node_ids"]),
    }


def deck(work: Path, load_file: str) -> str:
    return "\n".join([
        "/BATCH",
        "/FILNAME,patch",
        "/PREP7",
        "ET,1,187",
        f"MP,EX,1,{YOUNG_MPA}",
        f"MP,PRXY,1,{POISSON}",
        "/INPUT,mesh.inp",
        # Rollers on the three far faces: the block is free to contract
        # sideways, so the state of stress is uniaxial.
        "NSEL,S,LOC,X,0",
        "D,ALL,UX,0",
        "NSEL,S,LOC,Y,0",
        "D,ALL,UY,0",
        "NSEL,S,LOC,Z,0",
        "D,ALL,UZ,0",
        "ALLSEL",
        f"/INPUT,{load_file}",
        "/SOLU",
        "ANTYPE,STATIC",
        "EQSLV,SPARSE",
        "SOLVE",
        "FINISH",
        "/POST1",
        "SET,LAST",
        "CSYS,0",
        "*GET,NMAX,NODE,0,NUM,MAX",
        "*DIM,NID,ARRAY,NMAX",
        "*VFILL,NID(1),RAMP,1,1",
        "*DIM,SX,ARRAY,NMAX",
        "*DIM,SY,ARRAY,NMAX",
        "*DIM,SZ,ARRAY,NMAX",
        "*VGET,SX(1),NODE,1,S,X",
        "*VGET,SY(1),NODE,1,S,Y",
        "*VGET,SZ(1),NODE,1,S,Z",
        "*CFOPEN,patch_stress,csv",
        "*VWRITE",
        "('nid,sx,sy,sz')",
        "*VWRITE,NID(1),SX(1),SY(1),SZ(1)",
        "(F9.0,',',E16.8,',',E16.8,',',E16.8)",
        "*CFCLOS",
        "FINISH",
    ]) + "\n"


def _ansys() -> Path:
    for candidate in ANSYS_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise SystemExit("ANSYS181.exe was not found")


def run(work: Path, load_file: str) -> dict:
    inp = work / "patch.inp"
    inp.write_text(deck(work, load_file), encoding="ascii", newline="\n")
    subprocess.run(
        [str(_ansys()), "-b", "-m", "2000", "-i", str(inp),
         "-o", str(work / "patch.out"), "-j", "patch"],
        cwd=work, timeout=900, check=False,
    )
    csv_path = work / "patch_stress.csv"
    if not csv_path.is_file():
        tail = (work / "patch.out").read_text(
            encoding="utf-8", errors="replace"
        )[-2000:]
        raise SystemExit(f"{load_file} produced no stress output\n{tail}")

    sx, sy, sz = [], [], []
    for line in csv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue
        try:
            values = [float(p) for p in parts[1:]]
        except ValueError:
            continue
        # Zero-stress nodes are excluded: ANSYS writes 0 for nodes with no
        # result, and those would flatter any uniformity measure.
        if all(abs(v) < 1e-9 for v in values):
            continue
        sx.append(values[0])
        sy.append(values[1])
        sz.append(values[2])
    if not sx:
        raise SystemExit(f"{load_file} produced no non-zero stresses")

    return {
        "node_count": len(sx),
        "sigma_xx_mean": sum(sx) / len(sx),
        "sigma_xx_min": min(sx),
        "sigma_xx_max": max(sx),
        "sigma_yy_mean": sum(sy) / len(sy),
        "sigma_zz_mean": sum(sz) / len(sz),
        "max_abs_sigma_yy": max(abs(v) for v in sy),
        "max_abs_sigma_zz": max(abs(v) for v in sz),
        # The patch test statistic: how far the worst node is from the exact
        # answer, as a fraction of the applied pressure.
        "worst_error_fraction": max(
            abs(v + PRESSURE_MPA) for v in sx
        ) / PRESSURE_MPA,
    }


def main() -> None:
    work = HERE / "run"
    work.mkdir(parents=True, exist_ok=True)
    mesh_path, _points, loaded = mesh_block(work, element_size=7.0)
    selection = selection_payload(loaded)
    (work / "selection.json").write_text(
        json.dumps(selection), encoding="utf-8"
    )
    info = load_table(selection, mesh_path, work)

    report = {"model": info, "pressure_mpa": PRESSURE_MPA}
    for name, load_file in (
        ("surface_pressure", "load_sfe.inp"),
        ("nodal_force", "load_nodal.inp"),
    ):
        report[name] = run(work, load_file)

    (HERE / "patch_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    print("exact solution: sigma_xx = %.3f MPa, sigma_yy = sigma_zz = 0"
          % -PRESSURE_MPA)
    for name in ("surface_pressure", "nodal_force"):
        entry = report[name]
        print(
            "  %-18s sigma_xx %8.4f .. %8.4f   worst |sxx+p|/p = %.5f   "
            "max|syy| = %.4f"
            % (name, entry["sigma_xx_min"], entry["sigma_xx_max"],
               entry["worst_error_fraction"], entry["max_abs_sigma_yy"])
        )


if __name__ == "__main__":
    main()
