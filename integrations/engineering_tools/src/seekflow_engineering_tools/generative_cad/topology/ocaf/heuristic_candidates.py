"""HeuristicCandidateFinder — geometry fingerprint-based candidate search.

DOWNGRADED from former "FaceSelector" (PR-4). This module is NO LONGER the
authoritative source for topology identity. It provides diagnostic candidates
only — must never be used for automatic CAE binding.

Uses geometric fingerprints (area, centroid, surface type) to find candidate
faces that are SIMILAR to a previously fingerprinted face. Results are always
marked ProofClass.HEURISTIC_CANDIDATE.

Valid uses (only):
  - Diagnose why a native TNaming Solve failed
  - Migrate old models without native history
  - Provide human-confirmable candidates
  - Test oracle (compare heuristic vs native results)

Forbidden:
  - Auto-rebinding required CAE selections
  - Claiming low-distance candidates as UNIQUE identity
  - Bypassing CAE gate
  - Writing EXACT_KERNEL_HISTORY proof
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
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    try:
        adaptor = BRepAdaptor_Surface(face_wrapped)
        return _SURFACE_TYPE_NAMES.get(adaptor.GetType(), "Other")
    except Exception:
        return "Other"


def _face_properties(face) -> dict:
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


# ── Models ─────────────────────────────────────────────────────────────────


class HeuristicStatus(str, Enum):
    CANDIDATES_FOUND = "candidates_found"
    NO_CANDIDATES = "no_candidates"
    # NOTE: there is NO "UNIQUE" status — heuristic results are NEVER authoritative


@dataclass(frozen=True)
class HeuristicCandidate:
    """A candidate match with score and evidence. Not an identity."""
    face_index: int
    fingerprint: "GeometryFingerprint"
    score: float                      # distance (lower = better)
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GeometryFingerprint:
    """Geometry-based face signature. For diagnostics only."""
    area_mm2: float
    centroid: tuple[float, float, float]
    surface_type: str

    def distance(self, other: GeometryFingerprint) -> float:
        if self.surface_type != other.surface_type:
            return 1000.0
        smaller = min(self.area_mm2, other.area_mm2)
        larger = max(self.area_mm2, other.area_mm2)
        if smaller < 1e-6:
            area_diff = 100.0 if larger > 1e-6 else 0.0
        else:
            area_diff = abs(larger / smaller - 1.0)
        dx = self.centroid[0] - other.centroid[0]
        dy = self.centroid[1] - other.centroid[1]
        dz = self.centroid[2] - other.centroid[2]
        centroid_dist = (dx * dx + dy * dy + dz * dz) ** 0.5
        return area_diff * 3.0 + centroid_dist * 0.5


@dataclass
class HeuristicResult:
    """Result of heuristic candidate search. Never claims uniqueness."""
    status: HeuristicStatus
    candidates: list[HeuristicCandidate] = field(default_factory=list)
    detail: str = ""


# ── Finder ─────────────────────────────────────────────────────────────────


class HeuristicCandidateFinder:
    """Finds candidate faces using geometric fingerprints.

    Results are ALWAYS marked as HEURISTIC_CANDIDATE proof level.
    Never use for automatic CAE binding.

    Usage:
        finder = HeuristicCandidateFinder()
        fp = finder.fingerprint_from_face(body, target_face, "load_zone")
        # ... later ...
        result = finder.find(body, fp)
        for c in result.candidates:
            print(f"Face {c.face_index}: score={c.score:.3f}")
    """

    def __init__(self, match_threshold: float = 2.0):
        self.match_threshold = match_threshold

    def fingerprint_from_face(
        self,
        body_shape: Any,
        face_shape: Any,       # ★ TopoDS_Shape — NOT face index
        pid: str,
    ) -> GeometryFingerprint:
        """Create a fingerprint from an actual face shape.

        Does NOT accept face index — caller must resolve to TopoDS_Shape first.
        """
        props = _face_properties(face_shape)
        return GeometryFingerprint(
            area_mm2=props["area"],
            centroid=props["centroid"],
            surface_type=props["surface_type"],
        )

    def find(
        self,
        body_shape: Any,
        fingerprint: GeometryFingerprint,
    ) -> HeuristicResult:
        """Search a body for faces matching the fingerprint.

        Returns candidates sorted by score (best first).
        Does NOT declare any result as unique.
        """
        faces = list(body_shape.Faces())
        if not faces:
            return HeuristicResult(
                status=HeuristicStatus.NO_CANDIDATES,
                detail="Body has no faces",
            )

        candidates: list[HeuristicCandidate] = []

        for i, face in enumerate(faces):
            props = _face_properties(face.wrapped)
            fp = GeometryFingerprint(
                area_mm2=props["area"],
                centroid=props["centroid"],
                surface_type=props["surface_type"],
            )
            dist = fingerprint.distance(fp)
            if dist < self.match_threshold:
                candidates.append(HeuristicCandidate(
                    face_index=i,
                    fingerprint=fp,
                    score=dist,
                    evidence=props,
                ))

        candidates.sort(key=lambda c: c.score)

        if candidates:
            return HeuristicResult(
                status=HeuristicStatus.CANDIDATES_FOUND,
                candidates=candidates,
                detail=f"Found {len(candidates)} candidates",
            )
        else:
            return HeuristicResult(
                status=HeuristicStatus.NO_CANDIDATES,
                detail="No faces within match threshold",
            )
