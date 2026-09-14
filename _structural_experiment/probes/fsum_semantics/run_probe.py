"""What does FSUM actually sum?

The deck's existing self-check reports `MODEL_FSUM_N` as if it were the applied
load. On D27 it reads about 480 kN radial while the blade load is 10 kN - so it
is dominated by something else, and it is not obvious what. Before a surface
pressure load can be reported honestly, `FSUM` has to be pinned down:

  * does it sum *applied* loads only, or does it include reactions?
  * does it see a surface pressure, or only nodal forces and body loads?

Three runs answer both. Each is one linear tetrahedron, whose face areas and
normals are known exactly, so the applied load is a number we can write down.

  A  all DOF held, load by SFE            -> what FSUM reports for a pressure
  B  all DOF held, load by nodal F        -> does FSUM see nodal forces
  C  statically determinate (3-2-1), SFE  -> if FSUM excludes reactions it
                                             equals the applied load; if it
                                             includes them, everything cancels

Run C is the decisive one: reactions and applied loads are equal and opposite,
so a sum that includes both must come out near zero.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent

ANSYS_CANDIDATES = (
    Path(r"D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ANSYS181.exe"),
    Path(r"D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"),
    Path(r"C:\Program Files\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"),
)

I = (0.0, 0.0, 0.0)
J = (10.0, 0.0, 0.0)
K = (0.0, 10.0, 0.0)
L = (0.0, 0.0, 10.0)
CORNERS = (I, J, K, L)
MIDSIDE_PAIRS = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))

PRESSURE_MPA = 1.0
# Face 1 is {I, J, K} - the right triangle in z = 0 with legs of 10 mm.
FACE_1_AREA = 0.5 * 10.0 * 10.0
FACE_1_OUTWARD = (0.0, 0.0, -1.0)
# A positive pressure pushes into the element, i.e. along -outward.
APPLIED_VECTOR = tuple(-v * PRESSURE_MPA * FACE_1_AREA for v in FACE_1_OUTWARD)


def nodes() -> list[tuple[float, float, float]]:
    out = list(CORNERS)
    for a, b in MIDSIDE_PAIRS:
        out.append(
            tuple((CORNERS[a][i] + CORNERS[b][i]) / 2.0 for i in range(3))
        )
    return out


def _header() -> list[str]:
    return [
        "/BATCH",
        "/PREP7",
        "ET,1,187",
        "MP,EX,1,200000",
        "MP,PRXY,1,0.3",
    ]


def _mesh_lines() -> list[str]:
    lines = []
    for index, xyz in enumerate(nodes(), start=1):
        lines.append("N,%d,%.10g,%.10g,%.10g" % (index, xyz[0], xyz[1], xyz[2]))
    lines.append("EN,1,1,2,3,4,5,6,7,8")
    lines.append("EMORE,9,10")
    return lines


TAIL = [
    "/SOLU",
    "ANTYPE,STATIC",
    "EQSLV,SPARSE",
    "SOLVE",
    "FINISH",
    "/POST1",
    "SET,LAST",
    "CSYS,0",
    "FSUM",
    "*GET,FXSUM,FSUM,0,ITEM,FX",
    "*GET,FYSUM,FSUM,0,ITEM,FY",
    "*GET,FZSUM,FSUM,0,ITEM,FZ",
    "*GET,NMAX,NODE,0,NUM,MAX",
    "*DIM,RFX,ARRAY,NMAX",
    "*DIM,RFY,ARRAY,NMAX",
    "*DIM,RFZ,ARRAY,NMAX",
    "*VGET,RFX(1),NODE,1,RF,FX",
    "*VGET,RFY(1),NODE,1,RF,FY",
    "*VGET,RFZ(1),NODE,1,RF,FZ",
    "*VSCFUN,SXR,SUM,RFX",
    "*VSCFUN,SYR,SUM,RFY",
    "*VSCFUN,SZR,SUM,RFZ",
    "*CFOPEN,fsum_probe,txt",
    "*VWRITE,FXSUM,FYSUM,FZSUM",
    "('FSUM_N = ',3E16.8)",
    "*VWRITE,SXR,SYR,SZR",
    "('REACTION_SUM_N = ',3E16.8)",
    "*CFCLOS",
    "FINISH",
]


def deck(configuration: str) -> str:
    lines = _header()
    if configuration == "A":
        lines += _mesh_lines()
        lines += ["D,ALL,ALL,0", "ALLSEL"]
        lines += ["SFE,1,1,PRES,0,%.10g" % PRESSURE_MPA]
    elif configuration == "B":
        lines += _mesh_lines()
        lines += ["D,ALL,ALL,0", "ALLSEL"]
        # Same resultant as the pressure, applied to the same face's nodes -
        # spread the same way the surface pressure would be, so the two runs
        # differ only in how the load is represented.
        for node, share in ((5, 1 / 3), (6, 1 / 3), (7, 1 / 3)):
            force = APPLIED_VECTOR[2] * share
            lines.append("F,%d,FZ,%.10g" % (node, force))
    elif configuration == "C":
        lines += _mesh_lines()
        # 3-2-1: node 1 fully, node 2 in y and z, node 3 in z. Exactly six
        # constraints, so every reaction is determined and the sum of all
        # reactions must cancel the applied load.
        lines += [
            "D,1,ALL,0",
            "D,2,UY,0", "D,2,UZ,0",
            "D,3,UZ,0",
            "ALLSEL",
        ]
        lines += ["SFE,1,1,PRES,0,%.10g" % PRESSURE_MPA]
    else:
        raise ValueError(configuration)
    return "\n".join(lines + TAIL) + "\n"


def _ansys_executable() -> Path:
    for candidate in ANSYS_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise SystemExit("ANSYS181.exe was not found")


def run(configuration: str) -> dict:
    work = HERE / f"run_{configuration}"
    work.mkdir(parents=True, exist_ok=True)
    inp = work / "probe.inp"
    inp.write_text(deck(configuration), encoding="ascii", newline="\n")
    subprocess.run(
        [
            str(_ansys_executable()), "-b", "-m", "1500",
            "-i", str(inp), "-o", str(work / "probe.out"),
            "-j", "probe",
        ],
        cwd=work, timeout=600, check=False,
    )
    summary = work / "fsum_probe.txt"
    if not summary.is_file():
        tail = (work / "probe.out").read_text(
            encoding="utf-8", errors="replace"
        )[-1500:]
        raise SystemExit(f"config {configuration} produced no output\n{tail}")

    fsum = reaction = None
    for line in summary.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("FSUM_N"):
            fsum = [float(v) for v in line.split("=")[1].split()]
        elif line.startswith("REACTION_SUM_N"):
            reaction = [float(v) for v in line.split("=")[1].split()]
    return {
        "configuration": configuration,
        "fsum_n": fsum,
        "reaction_sum_n": reaction,
        "fsum_magnitude_n": round(math.dist(fsum, (0, 0, 0)), 6) if fsum else None,
        "reaction_magnitude_n": (
            round(math.dist(reaction, (0, 0, 0)), 6) if reaction else None
        ),
    }


def main() -> None:
    applied = round(math.dist(APPLIED_VECTOR, (0, 0, 0)), 6)
    report = {
        "applied_load_n": applied,
        "applied_vector_n": list(APPLIED_VECTOR),
        "runs": [run(c) for c in ("A", "B", "C")],
    }
    (HERE / "fsum_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    print("applied load magnitude: %.6f N" % applied)
    for entry in report["runs"]:
        print(
            "  config %s: |FSUM| = %.6f   |sum of RF| = %.6f"
            % (entry["configuration"], entry["fsum_magnitude_n"] or 0.0,
               entry["reaction_magnitude_n"] or 0.0)
        )


if __name__ == "__main__":
    main()
