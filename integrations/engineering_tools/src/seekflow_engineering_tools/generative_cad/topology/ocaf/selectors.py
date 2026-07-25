"""FaceSelector — geometry fingerprint-based face identification.

Uses OCAF NamedShape for body-level persistence + geometric fingerprints
(area, centroid, surface type, normal) for face-level matching.

Why fingerprints instead of TNaming_Selector:
  OCP 7.8.1.1's TNaming_Selector.Select() returns True but IsIdentified_s()
  always returns 0 — the selection is never truly persisted. Geometric
  fingerprints are more robust across OCCT versions and survive small
  parameter perturbations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Surface type mapping ──────────────────────────────────────────────────

_SURFACE_TYPE_NAMES: dict[int, str] = {
    0: "Plane", 1: "Cylinder", 2: "Cone", 3: "Sphere",
    4: "Torus", 5: "Bezier", 6: "BSpline", 7: "Revolution",
    8: "Extrusion", 9: "Offset", 10: "Other",
}


def _surface_type_name(face_wrapped) -> str:
    """Get OCCT surface type name for a face."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    try:
        adaptor = BRepAdaptor_Surface(face_wrapped)
        return _SURFACE_TYPE_NAMES.get(adaptor.GetType(), "Other")
    except Exception:
        return "Other"


def _face_properties(face) -> dict:
    """Extract basic face properties: area, centroid, surface type."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    try:
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        c = props.CentreOfMass()
        return {
            "area": float(props.Mass()),
            "centroid": (float(c.X()), float(c.Y()), float(c.Z())),
            "surface_type": _surface_type_name(face),
        }
    except Exception:
        return {"area": 0.0, "centroid": (0.0, 0.0, 0.0), "surface_type": "Other"}


# ── Fingerprint model ─────────────────────────────────────────────────────


class SolveStatus(str, Enum):
    UNIQUE = "unique"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class FaceFingerprint:
    """Geometry-based face identity. Survives parameter perturbations."""
    area_mm2: float
    centroid: tuple[float, float, float]
    surface_type: str

    def distance(self, other: FaceFingerprint) -> float:
        """Weighted distance metric. Lower = better match.

        Weights: surface type mismatch = 1000 (hard penalty),
                 area ratio difference, centroid distance.
        """
        # Surface type mismatch is a hard penalty
        if self.surface_type != other.surface_type:
            return 1000.0

        # Area ratio: how much the area changed relative to the smaller face
        smaller = min(self.area_mm2, other.area_mm2)
        larger = max(self.area_mm2, other.area_mm2)
        if smaller < 1e-6:
            area_diff = 100.0 if larger > 1e-6 else 0.0
        else:
            area_diff = abs(larger / smaller - 1.0)

        # Centroid distance (Euclidean, mm)
        dx = self.centroid[0] - other.centroid[0]
        dy = self.centroid[1] - other.centroid[1]
        dz = self.centroid[2] - other.centroid[2]
        centroid_dist = (dx * dx + dy * dy + dz * dz) ** 0.5

        # Normalized: area_diff weighted to tolerate ~65% area change,
        # centroid_dist weighted for mm-level position matching
        return area_diff * 3.0 + centroid_dist * 0.5

    def is_match(self, other: FaceFingerprint, threshold: float = 2.0) -> bool:
        """Return True if fingerprints match within threshold."""
        return self.distance(other) < threshold


@dataclass
class FaceSelectionRecord:
    """Stored face selection — fingerprint + OCAF body reference."""
    pid: str
    fingerprint: FaceFingerprint
    body_label_entry: str = ""


@dataclass
class SolveResult:
    """Result of solving a face selection against a body."""
    status: SolveStatus
    matched_face_index: int = -1
    matched_fingerprint: FaceFingerprint | None = None
    candidates: list[tuple[int, FaceFingerprint, float]] = field(default_factory=list)
    detail: str = ""


# ── Selector ──────────────────────────────────────────────────────────────


class FaceSelector:
    """Creates and solves geometric fingerprint-based face selections.

    Usage:
        selector = FaceSelector()
        record = selector.select_face(body_shape, face_index=3, pid="load_face")
        # ... save record.fingerprint to OCAF sidecar or JSON ...
        # ... later, on the same or similar body ...
        result = selector.solve(record, body_shape)
        if result.status == SolveStatus.UNIQUE:
            target_face = body_shape.Faces()[result.matched_face_index]
    """

    def __init__(self, match_threshold: float = 2.0):
        self.match_threshold = match_threshold

    def select_face(
        self,
        body_shape: Any,
        face_index: int,
        pid: str,
    ) -> FaceSelectionRecord:
        """Create a FaceFingerprint for a specific face.

        Args:
            body_shape: CadQuery Shape containing the face.
            face_index: 0-based index of the target face.
            pid: Human-readable persistent ID.
        """
        faces = list(body_shape.Faces())
        if face_index < 0 or face_index >= len(faces):
            raise ValueError(
                f"Face index {face_index} out of range (0-{len(faces) - 1})"
            )

        target = faces[face_index]
        props = _face_properties(target.wrapped)
        fingerprint = FaceFingerprint(
            area_mm2=props["area"],
            centroid=props["centroid"],
            surface_type=props["surface_type"],
        )
        return FaceSelectionRecord(pid=pid, fingerprint=fingerprint)

    def solve(
        self,
        record: FaceSelectionRecord,
        body_shape: Any,
    ) -> SolveResult:
        """Find the best-matching face for a stored fingerprint.

        Args:
            record: Previously created FaceSelectionRecord.
            body_shape: CadQuery Shape to search in.
        """
        faces = list(body_shape.Faces())
        if not faces:
            return SolveResult(status=SolveStatus.UNRESOLVED,
                             detail="Body has no faces")

        candidates: list[tuple[int, FaceFingerprint, float]] = []

        for i, face in enumerate(faces):
            props = _face_properties(face.wrapped)
            fp = FaceFingerprint(
                area_mm2=props["area"],
                centroid=props["centroid"],
                surface_type=props["surface_type"],
            )
            dist = record.fingerprint.distance(fp)
            candidates.append((i, fp, dist))

        # Sort by distance (best match first)
        candidates.sort(key=lambda c: c[2])

        best = candidates[0]
        if best[2] < self.match_threshold:
            # Check for ambiguity: is the second-best also close?
            if len(candidates) > 1 and candidates[1][2] < self.match_threshold:
                ratio = best[2] / max(candidates[1][2], 1e-9)
                if ratio > 0.5:  # second is comparable
                    return SolveResult(
                        status=SolveStatus.AMBIGUOUS,
                        candidates=candidates[:3],
                        detail=f"Face {best[0]} dist={best[2]:.3f} vs "
                               f"face {candidates[1][0]} dist={candidates[1][2]:.3f}",
                    )
            return SolveResult(
                status=SolveStatus.UNIQUE,
                matched_face_index=best[0],
                matched_fingerprint=best[1],
                detail=f"Face {best[0]}, dist={best[2]:.4f}",
            )
        else:
            return SolveResult(
                status=SolveStatus.UNRESOLVED,
                candidates=candidates[:3],
                detail=f"Best match dist={best[2]:.3f} exceeds threshold "
                       f"{self.match_threshold}",
            )
