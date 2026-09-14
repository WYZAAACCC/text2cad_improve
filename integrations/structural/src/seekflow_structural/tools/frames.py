"""Moving a model so the axis it is analysed about becomes the deck's +Z.

The deck writes `CSYS,1` and `NROTAT`, which are cylindrical about global Z,
and the cyclic coupling is expressed as a rotation about Z. Rather than
generalise every one of those to an arbitrary axis, the model is rotated once,
at ingest, so the axis the agent chose *is* global Z. Linear elastostatics is
invariant under a rigid transform: the answer is the same, with displacement
and stress carried along by the same rotation.

The transform is a rotation taking the axis direction to +Z, followed by a
translation with only components perpendicular to it. That second restriction
is what preserves distance from the axis - and therefore every radius in the
rest of the package, from the bore to the load radius to the band edges.

If the axis is already +Z the rotation is the identity and the translation is
zero, so a part that needs no normalisation is not touched at all. That is not
a nicety: it means the change is a no-op on everything that already ran, and
the regression test can assert the deck is byte-identical.
"""
from __future__ import annotations

import math

Matrix = list[list[float]]

IDENTITY: Matrix = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

# How close to +Z the direction has to be for the rotation to be skipped. The
# deck's own tolerances are 1e-10, so anything under that is already exact.
_ALIGNED_TOL = 1e-12


def _norm(v) -> float:
    return math.sqrt(sum(x * x for x in v))


def _unit(v):
    length = _norm(v)
    if length <= 0:
        raise ValueError("cannot normalise a zero vector")
    return [x / length for x in v]


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def matmul(matrix: Matrix, v):
    return [
        sum(matrix[i][j] * v[j] for j in range(3)) for i in range(3)
    ]


def matmul_matrix(a: Matrix, b: Matrix) -> Matrix:
    return [
        [sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
        for i in range(3)
    ]


def rotation_to_z(direction) -> Matrix:
    """The rotation taking `direction` to +Z, by Rodrigues' formula.

    Written out rather than delegated because the result has to be exactly the
    identity when the direction is already +Z - an identity built from
    trig of a zero angle is identity up to rounding, and the no-op regression
    compares decks byte for byte.
    """
    d = _unit(direction)
    if abs(d[0]) < _ALIGNED_TOL and abs(d[1]) < _ALIGNED_TOL and d[2] > 0:
        return [row[:] for row in IDENTITY]

    axis = _cross(d, [0.0, 0.0, 1.0])
    s = _norm(axis)
    c = _dot(d, [0.0, 0.0, 1.0])
    if s < _ALIGNED_TOL:
        # antiparallel: a half turn about any perpendicular axis
        return [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]
    k = [x / s for x in axis]
    kx, ky, kz = k
    K = [
        [0.0, -kz, ky],
        [kz, 0.0, -kx],
        [-ky, kx, 0.0],
    ]
    K2 = matmul_matrix(K, K)
    angle = math.atan2(s, c)
    sin, cos = math.sin(angle), math.cos(angle)
    return [
        [
            IDENTITY[i][j] + sin * K[i][j] + (1.0 - cos) * K2[i][j]
            for j in range(3)
        ]
        for i in range(3)
    ]


class Normalisation:
    """The rigid transform from the part's frame to the deck's frame."""

    def __init__(self, axis_origin, axis_direction):
        self.rotation = rotation_to_z(axis_direction)
        rotated_origin = matmul(self.rotation, list(axis_origin))
        # Only the perpendicular part is removed, so the axis lands on the Z
        # axis while every distance from it is left alone.
        self.translation = [rotated_origin[0], rotated_origin[1], 0.0]

    @property
    def is_identity(self) -> bool:
        return all(
            abs(self.rotation[i][j] - IDENTITY[i][j]) < 1e-15
            for i in range(3) for j in range(3)
        ) and all(abs(v) < 1e-15 for v in self.translation)

    def point(self, x, y, z):
        rotated = matmul(self.rotation, [x, y, z])
        return (
            rotated[0] - self.translation[0],
            rotated[1] - self.translation[1],
            rotated[2] - self.translation[2],
        )

    def direction(self, x, y, z):
        """A vector, which rotates but does not translate."""
        return tuple(matmul(self.rotation, [x, y, z]))

    def moment(self, x, y, z):
        """A moment, which is a pseudovector - it rotates like a direction.

        Named separately from `direction` because the two being the same
        function is a coincidence of pure rotations, and a reader who later
        adds a reflection needs to see the place where that stops being true.
        """
        return self.direction(x, y, z)

    def as_matrix(self) -> Matrix:
        return [row[:] for row in self.rotation]

    def to_dict(self) -> dict:
        return {
            "rotation": self.rotation,
            "translation": self.translation,
            "is_identity": self.is_identity,
        }


def distance_from_axis(point, axis_origin, axis_direction) -> float:
    """How far a point is from an axis - preserved by normalisation."""
    d = _unit(axis_direction)
    rel = [point[i] - axis_origin[i] for i in range(3)]
    axial = _dot(rel, d)
    radial = [rel[i] - axial * d[i] for i in range(3)]
    return _norm(radial)


def normalise_mesh(mesh_inp, mesh_out, normalisation: Normalisation) -> int:
    """Rewrite a mesh's node coordinates through the transform.

    The elements are left exactly as they are: a rigid transform does not
    change which nodes an element connects, only where they are.
    """
    moved = 0
    lines = []
    for line in mesh_inp.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        if line.startswith("N,"):
            parts = line.split(",")
            if len(parts) == 5:
                try:
                    x, y, z = (float(v) for v in parts[2:5])
                except ValueError:
                    lines.append(line)
                    continue
                nx, ny, nz = normalisation.point(x, y, z)
                lines.append(
                    "N,%s,%.10g,%.10g,%.10g" % (parts[1], nx, ny, nz)
                )
                moved += 1
                continue
        lines.append(line)
    mesh_out.write_text("\n".join(lines) + "\n", encoding="ascii")
    return moved
