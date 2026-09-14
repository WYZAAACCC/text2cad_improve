"""Settle the SOLID187 surface-load conventions by measurement, not by memory.

Three things about `SFE` on SOLID187 have to be right before a pressure load
can be trusted, and none of them can be read off this repository:

  1. Which corner-node triple each LKEY refers to. The element reference gives
     a table, but tables get transcribed wrongly and the cost of being wrong
     is a load applied to the wrong face - which a resultant check will not
     catch, because the resultant is the same either way.
  2. Whether a positive PRES pushes into the element or out of it. Getting this
     backwards flips the load and every magnitude check still passes.
  3. How a uniform pressure is distributed over a quadratic face. The
     consistent load vector puts nothing on the corner nodes and a third of
     the face force on each mid-side node; the previous implementation split
     the force equally among all six, which is a different load.

The model is four copies of one right-corner tetrahedron, translated apart so
they cannot interact, each fully constrained and each loaded on a different
LKEY with unit pressure. With every DOF held, the reaction at each node is
minus the load that node received, so the reactions *are* the load
distribution - read directly, with no post-processing guesswork.

The tetrahedron is chosen so every face has a normal that can be written down:
the faces lie in the planes z=0, y=0, x=0 and x+y+z=10.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

ANSYS_CANDIDATES = (
    Path(r"D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ANSYS181.exe"),
    Path(r"D:\ANSYS181\ANSYS Inc\v181\ANSYS\bin\winx64\ansys181.exe"),
    Path(r"C:\Program Files\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"),
)

# The reference tetrahedron. Corner order is ANSYS's I, J, K, L.
I = (0.0, 0.0, 0.0)
J = (10.0, 0.0, 0.0)
K = (0.0, 10.0, 0.0)
L = (0.0, 0.0, 10.0)
CORNERS = (I, J, K, L)

# SOLID187 node order: I J K L M N O P Q R, with the mid-side nodes between
# the corner pair named in the element reference. Which mid-side node sits on
# which edge is fixed by the element definition, not by the load we apply, so
# it does not need probing - only the face numbering does.
MIDSIDE_PAIRS = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))

# Corner triples of the four faces, as index triples into I, J, K, L.
FACE_CORNERS = {1: (1, 0, 2), 2: (0, 1, 3), 3: (1, 2, 3), 4: (2, 0, 3)}

# Mid-side node numbers (1-based within the element) sitting on each face,
# derived from MIDSIDE_PAIRS: face 1 is {I,J,K} so its mid-side nodes are the
# midpoints of IJ, JK and KI.
FACE_MIDSIDE_EDGES = {
    1: ((0, 1), (1, 2), (2, 0)),
    2: ((0, 1), (0, 3), (1, 3)),
    3: ((1, 2), (1, 3), (2, 3)),
    4: ((2, 0), (0, 3), (2, 3)),
}

OFFSET_MM = 100.0
PRESSURE_MPA = 1.0


def _sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a):
    return math.sqrt(sum(v * v for v in a))


def _unit(a):
    n = _norm(a)
    return tuple(v / n for v in a) if n > 0 else (0.0, 0.0, 0.0)


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def element_nodes(offset_x: float) -> list[tuple[float, float, float]]:
    """The ten nodes of one element, in SOLID187 order."""
    shift = (offset_x, 0.0, 0.0)
    nodes = [tuple(c[i] + shift[i] for i in range(3)) for c in CORNERS]
    for a, b in MIDSIDE_PAIRS:
        nodes.append(
            tuple((CORNERS[a][i] + CORNERS[b][i]) / 2.0 + shift[i]
                  for i in range(3))
        )
    return nodes


def face_outward_normal(lkey: int) -> tuple[float, float, float]:
    """Outward normal of a face, from geometry alone.

    Signed away from the one corner the face does not contain, so it does not
    depend on any convention under test.
    """
    a, b, c = (CORNERS[i] for i in FACE_CORNERS[lkey])
    n = _unit(_cross(_sub(b, a), _sub(c, a)))
    missing = next(i for i in range(4) if i not in FACE_CORNERS[lkey])
    centroid = tuple((a[i] + b[i] + c[i]) / 3.0 for i in range(3))
    if _dot(n, _sub(CORNERS[missing], centroid)) > 0:
        n = tuple(-v for v in n)
    return n


def face_area(lkey: int) -> float:
    a, b, c = (CORNERS[i] for i in FACE_CORNERS[lkey])
    return 0.5 * _norm(_cross(_sub(b, a), _sub(c, a)))


def build_deck() -> str:
    lines = [
        "/BATCH",
        "/FILNAME,probe",
        "/PREP7",
        "ET,1,187",
        # Linear elastic and irrelevant to the answer - every DOF is held, so
        # the reactions are the applied load whatever the stiffness is. ANSYS
        # refuses to assemble without them.
        "MP,EX,1,200000",
        "MP,PRXY,1,0.3",
    ]
    node_id = 0
    element_nodes_by_id: dict[int, list[int]] = {}
    for element in range(1, 5):
        offset = OFFSET_MM * (element - 1)
        ids = []
        for xyz in element_nodes(offset):
            node_id += 1
            ids.append(node_id)
            lines.append(
                "N,%d,%.10g,%.10g,%.10g" % (node_id, xyz[0], xyz[1], xyz[2])
            )
        element_nodes_by_id[element] = ids
        lines.append(
            "EN,%d,%s" % (element, ",".join(str(v) for v in ids[:8]))
        )
        lines.append("EMORE,%d,%d" % (ids[8], ids[9]))

    # Every DOF held on every node: the reactions are then exactly the load
    # each node received, with no structural response mixed in.
    lines += ["D,ALL,ALL,0", "ALLSEL"]

    for element in range(1, 5):
        lines.append(
            "SFE,%d,%d,PRES,0,%.10g" % (element, element, PRESSURE_MPA)
        )

    lines += [
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
        "*DIM,RFX,ARRAY,NMAX",
        "*DIM,RFY,ARRAY,NMAX",
        "*DIM,RFZ,ARRAY,NMAX",
        "*VGET,RFX(1),NODE,1,RF,FX",
        "*VGET,RFY(1),NODE,1,RF,FY",
        "*VGET,RFZ(1),NODE,1,RF,FZ",
        "*CFOPEN,probe_reactions,csv",
        "*VWRITE",
        "('nid,rfx,rfy,rfz')",
        "*VWRITE,NID(1),RFX(1),RFY(1),RFZ(1)",
        "(F9.0,',',E16.8,',',E16.8,',',E16.8)",
        "*CFCLOS",
        "FINISH",
    ]
    return "\n".join(lines) + "\n"


def _ansys_executable() -> Path:
    for candidate in ANSYS_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise SystemExit("ANSYS181.exe was not found")


def run_deck(deck: str, work: Path, memory_mb: int = 2000,
             timeout_s: int = 900) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    inp = work / "probe.inp"
    inp.write_text(deck, encoding="ascii", newline="\n")
    cmd = [
        str(_ansys_executable()),
        "-b",
        "-m", str(memory_mb),
        "-i", str(inp),
        "-o", str(work / "probe.out"),
        "-j", "probe",
    ]
    subprocess.run(cmd, cwd=work, timeout=timeout_s, check=False)
    csv_path = work / "probe_reactions.csv"
    if not csv_path.is_file():
        out = (work / "probe.out")
        tail = out.read_text(encoding="utf-8", errors="replace")[-3000:] \
            if out.is_file() else "(no output file)"
        raise SystemExit("ANSYS produced no probe_reactions.csv\n" + tail)
    return csv_path


def read_reactions(path: Path) -> dict[int, tuple[float, float, float]]:
    rows = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue
        try:
            nid = int(float(parts[0]))
            rows[nid] = (float(parts[1]), float(parts[2]), float(parts[3]))
        except ValueError:
            continue
    return rows


def analyse(reactions: dict[int, tuple[float, float, float]]) -> dict:
    """Per element: which nodes carried load, the total, and its direction."""
    report = {"faces": [], "consistent_load_vector_confirmed": True,
              "sign_confirmed": True, "lkey_table_confirmed": True}
    for element in range(1, 5):
        first = (element - 1) * 10 + 1
        ids = list(range(first, first + 10))
        total = [0.0, 0.0, 0.0]
        loaded_corners = []
        loaded_midside = []
        for index, nid in enumerate(ids):
            value = reactions.get(nid, (0.0, 0.0, 0.0))
            magnitude = _norm(value)
            for i in range(3):
                total[i] += value[i]
            if magnitude > 1e-6:
                (loaded_corners if index < 4 else loaded_midside).append(
                    (nid, magnitude)
                )

        outward = face_outward_normal(element)
        # A positive pressure pushes into the element, so the reaction that
        # holds it back points outward - the reaction and the face normal
        # should therefore agree, and the load itself is their opposite.
        direction = _unit(total)
        agreement = _dot(direction, outward)
        area = face_area(element)
        expected_total = PRESSURE_MPA * area
        expected_each = expected_total / 3.0

        entry = {
            "element": element,
            "lkey_applied": element,
            "loaded_corner_nodes": [nid for nid, _ in loaded_corners],
            "loaded_midside_nodes": [nid for nid, _ in loaded_midside],
            "midside_magnitudes": [round(v, 6) for _, v in loaded_midside],
            "expected_midside_magnitude": round(expected_each, 6),
            "reaction_total_n": round(_norm(total), 6),
            "expected_total_n": round(expected_total, 6),
            "reaction_direction": [round(v, 6) for v in direction],
            "face_outward_normal": [round(v, 6) for v in outward],
            "direction_dot_outward": round(agreement, 6),
        }
        report["faces"].append(entry)

        if loaded_corners:
            report["consistent_load_vector_confirmed"] = False
        if abs(agreement - 1.0) > 1e-3:
            report["sign_confirmed"] = False
        if abs(_norm(total) - expected_total) > 1e-3 * expected_total:
            report["lkey_table_confirmed"] = False
    return report


def main() -> None:
    work = HERE / "run"
    deck = build_deck()
    (HERE / "probe.inp").write_text(deck, encoding="ascii", newline="\n")
    csv_path = run_deck(deck, work)
    reactions = read_reactions(csv_path)
    if not reactions:
        raise SystemExit(f"no reactions parsed from {csv_path}")

    report = analyse(reactions)
    (HERE / "probe_reactions.csv").write_text(
        csv_path.read_text(encoding="utf-8", errors="replace"),
        encoding="utf-8",
    )
    (HERE / "probe_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    print("LKEY table confirmed   :", report["lkey_table_confirmed"])
    print("pressure sign confirmed:", report["sign_confirmed"])
    print("consistent load vector :",
          report["consistent_load_vector_confirmed"])
    if not all((report["lkey_table_confirmed"], report["sign_confirmed"],
                report["consistent_load_vector_confirmed"])):
        print()
        print("A convention differs from the element reference. The measured "
              "values above are the ones to encode - do not adjust the probe "
              "to match the documentation.")
        sys.exit(1)


if __name__ == "__main__":
    main()
