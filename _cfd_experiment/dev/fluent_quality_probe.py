"""Parse a Gmsh MSH file and report Fluent-style orthogonal quality.

Fluent's orthogonal quality for a cell is the minimum over its faces of
dot(face area unit vector, vector from cell centroid to face centroid).
This probe computes that metric on the pre-conversion Gmsh tetra mesh so mesh
generation and mesh-conversion problems can be distinguished.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _tet_geometry(verts):
    p0, p1, p2, p3 = verts
    a = tuple(p1[i] - p0[i] for i in range(3))
    b = tuple(p2[i] - p0[i] for i in range(3))
    c = tuple(p3[i] - p0[i] for i in range(3))

    def dot(u, v):
        return sum(u[i] * v[i] for i in range(3))

    volume = abs(
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    ) / 6.0
    # Circumcenter relative to p0 solves 2*a.x=a.a, 2*b.x=b.b, 2*c.x=c.c.
    rhs = [dot(a, a) / 2.0, dot(b, b) / 2.0, dot(c, c) / 2.0]
    m = [
        [a[0], a[1], a[2]],
        [b[0], b[1], b[2]],
        [c[0], c[1], c[2]],
    ]
    det = (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )
    circumradius = None
    if abs(det) > 1e-300:
        x = [
            (
                rhs[0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (rhs[1] * m[2][2] - m[1][2] * rhs[2])
                + m[0][2] * (rhs[1] * m[2][1] - m[1][1] * rhs[2])
            )
            / det,
            (
                m[0][0] * (rhs[1] * m[2][2] - m[1][2] * rhs[2])
                - rhs[0] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * rhs[2] - rhs[1] * m[2][0])
            )
            / det,
            (
                m[0][0] * (m[1][1] * rhs[2] - rhs[1] * m[2][1])
                - m[0][1] * (m[1][0] * rhs[2] - rhs[1] * m[2][0])
                + rhs[0] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
            )
            / det,
        ]
        circumradius = math.sqrt(sum(x[i] * x[i] for i in range(3)))
    volume_regular = 1.0
    if circumradius is not None and circumradius > 1e-300:
        volume_regular = 16.0 * circumradius**3 / (3.0 * math.sqrt(3.0))
    equilateral_quality = (
        volume / volume_regular
        if circumradius is not None and volume_regular > 1e-300
        else 0.0
    )
    return volume, equilateral_quality


def _read_mesh(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    nodes = {}
    elements = {}
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "$Nodes":
            section = "nodes"
            continue
        if stripped == "$EndNodes":
            section = None
            continue
        if stripped == "$Elements":
            section = "elements"
            continue
        if stripped == "$EndElements":
            section = None
            continue
        if section == "nodes":
            parts = stripped.split()
            if len(parts) == 4 and parts[0].isdigit():
                nodes[int(parts[0])] = tuple(float(x) for x in parts[1:])
        elif section == "elements":
            parts = stripped.split()
            if len(parts) >= 5 and parts[0].isdigit() and int(parts[1]) == 4:
                ntags = int(parts[2])
                elements[int(parts[0])] = [
                    int(x) for x in parts[3 + ntags :]
                ]
    return nodes, elements


def _quality(verts):
    p = list(verts)
    cell = tuple(sum(x[i] for x in p) / 4 for i in range(3))
    q = []
    _, equilateral_quality = _tet_geometry(p)
    faces = [(0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)]
    for a, b, c in faces:
        u = (p[b][0] - p[a][0], p[b][1] - p[a][1], p[b][2] - p[a][2])
        v = (p[c][0] - p[a][0], p[c][1] - p[a][1], p[c][2] - p[a][2])
        normal = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        opp = next(i for i in (0, 1, 2, 3) if i not in (a, b, c))
        if sum(n * (p[opp][i] - p[a][i]) for i, n in enumerate(normal)) > 0:
            normal = tuple(-n for n in normal)
        magnitude = math.sqrt(sum(n * n for n in normal))
        if magnitude <= 0:
            continue
        unit = tuple(n / magnitude for n in normal)
        face = tuple(sum(p[idx][i] for idx in (a, b, c)) / 3 for i in range(3))
        d = tuple(face[i] - cell[i] for i in range(3))
        length = math.sqrt(sum(v * v for v in d))
        if length > 0:
            q.append(abs(sum(unit[i] * d[i] for i in range(3))) / length)
    orthogonality = min(q) if q else 1.0
    return min(orthogonality, equilateral_quality), orthogonality, equilateral_quality


def main():
    p = argparse.ArgumentParser()
    p.add_argument("msh", type=Path)
    p.add_argument("--worst", type=int, default=20)
    args = p.parse_args()
    nodes, elements = _read_mesh(args.msh)
    scored = []
    for eid, conn in elements.items():
        try:
            verts = [nodes[i] for i in conn]
        except KeyError:
            continue
        quality, orthogonality, equilateral_quality = _quality(verts)
        scored.append(
            (quality, orthogonality, equilateral_quality, verts, eid)
        )
    scored.sort(key=lambda row: row[0])
    worst = scored[: args.worst]
    report = {
        "mesh": str(args.msh),
        "tetra_count": len(scored),
        "min_orthogonal_quality": scored[0][0],
        "min_face_orthogonality": min(row[1] for row in scored),
        "min_equilateral_quality": min(row[2] for row in scored),
        "worst": [
            {
                "quality": q,
                "face_orthogonality": orthogonality,
                "equilateral_quality": equilateral_quality,
                "element_id": eid,
                "centroid_m": [
                    sum(v[i] for v in verts) / 4 for i in range(3)
                ],
            }
            for q, orthogonality, equilateral_quality, verts, eid in worst
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    out = args.msh.with_suffix(".quality.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
