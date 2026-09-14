"""Tools a planning agent uses to choose an analysis domain.

Choosing the domain - the whole part, a cyclic sector, a half, a quarter with
two planes of symmetry - is a decision about the part, not about the solver.
These are the measurements that decision rests on: what a candidate domain
would actually contain if it were cut, and how that compares with the whole.

Nothing here decides. Each call reports a measurement and leaves the judgement
to the caller.

The decisive measurement is the volume ratio. Cutting a genuine repeat unit
out of an N-fold part leaves exactly 1/N of the material. Cutting a wedge that
does not respect the part's structure removes whatever happened to fall
outside it, so the ratio misses 1/N - and the mesh that follows is a mesh of a
part that was never handed in. Because it compares masses rather than face
topology, the test is indifferent to what the part is: a blade, a bracket and
a disc are all judged the same way.
"""
from __future__ import annotations

import math
from pathlib import Path


def _unit(vector):
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return [0.0, 0.0, 0.0]
    return [value / norm for value in vector]


class DomainPreviewer:
    """Holds the part open so a candidate domain can be cut and measured.

    Importing the STEP is the expensive part (a large disc takes one to two
    minutes), so it happens once and each candidate is cut from a copy. The
    agent can then try as many domains as it needs without paying that cost
    again.
    """

    def __init__(self, step_path: Path, r_outer_mm: float, z_half_mm: float):
        import gmsh

        self.gmsh = gmsh
        self.r_outer_mm = float(r_outer_mm)
        self.z_half_mm = float(z_half_mm)
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("domain_preview")
        imported = gmsh.model.occ.importShapes(str(step_path))
        volumes = [tag for dim, tag in imported if dim == 3]
        if not volumes:
            raise ValueError(f"{step_path} contains no solid")
        gmsh.model.occ.synchronize()
        self.source = volumes[0]
        self.full_volume = float(gmsh.model.occ.getMass(3, self.source))
        self.full_area = self._surface_area()
        # The cutting tool has to clear the part. A tool smaller than the part
        # does not fail - it quietly truncates, and the shortfall then shows up
        # as a volume error that reads like a property of the domain instead of
        # a mistake in the cut. Measured extents win over whatever was passed
        # in, so the caller's numbers are a floor rather than the truth.
        x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(-1, -1)
        self.r_outer_mm = max(
            self.r_outer_mm, math.hypot(x0, y0), math.hypot(x1, y1)
        )
        self.z_half_mm = max(self.z_half_mm, abs(z0), abs(z1))

    def _surface_area(self) -> float:
        return sum(
            float(self.gmsh.model.occ.getMass(2, tag))
            for dim, tag in self.gmsh.model.getEntities(2)
            if dim == 2
        )

    def close(self) -> None:
        try:
            self.gmsh.finalize()
        except Exception:
            pass

    def geometry_summary(self) -> dict:
        """Overall size and mass, measured from the part that was opened.

        The radial extent comes from the faces, not from the bounding box. A
        box only bounds the part: its corners sit at radius*sqrt(2) from the
        axis and are nowhere near the material, so a disc of outer radius 300
        reports 424 - and, because every corner of a symmetric box is the same
        distance out, a minimum and a maximum that are equal. Reporting that
        pair as r_min and r_max told the agent the part was a shell of zero
        thickness. The faces give the real answer, and an axisymmetric face
        gives it exactly, from the circles bounding it.
        """
        gmsh = self.gmsh
        _, _, z0, _, _, z1 = gmsh.model.getBoundingBox(-1, -1)
        faces = self.faces()
        return {
            "r_min_mm": round(min(face["r_lo"] for face in faces), 4),
            "r_max_mm": round(max(face["r_hi"] for face in faces), 4),
            "z_min_mm": round(z0, 4),
            "z_max_mm": round(z1, 4),
            "z_half_mm": round(max(abs(z0), abs(z1)), 4),
            "total_volume_mm3": round(self.full_volume, 3),
            "total_surface_area_mm2": round(self.full_area, 3),
            "face_count": len(faces),
        }

    def faces(self) -> list[dict]:
        """Per-face facts, in the shape mesh_profile's analysis functions take.

        Axisymmetric faces are flagged here because their centroid is a poor
        description of them: a surface of revolution sits all the way around
        the axis, and any measure that treats it as living at one azimuth is
        wrong about it.
        """
        if getattr(self, "_faces", None) is not None:
            return self._faces
        gmsh = self.gmsh
        collected = []
        for dim, tag in gmsh.model.getEntities(2):
            if dim != 2:
                continue
            cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, tag)
            shortest = None
            full_revolution = False
            circles: list[float] = []
            for bdim, btag in gmsh.model.getBoundary([(2, tag)], combined=False):
                if bdim != 1:
                    continue
                length = float(gmsh.model.occ.getMass(1, abs(btag)))
                if shortest is None or length < shortest:
                    shortest = length
                bx0, by0, _, bx1, by1, _ = gmsh.model.getBoundingBox(1, abs(btag))
                scale = max(bx1, by1, 1e-6)
                if (
                    bx1 > 0
                    and abs(bx0 + bx1) < 1e-4 * scale
                    and abs(by0 + by1) < 1e-4 * scale
                    and abs((bx1 - bx0) - (by1 - by0)) < 1e-4 * scale
                ):
                    full_revolution = True
                    # A boundary circle's radius, read exactly off its bounding
                    # box. Needed because a surface of revolution has its
                    # centroid on the axis, so its own `r` says nothing about
                    # how far out it reaches.
                    circles.append(0.5 * (bx1 - bx0))
            radius = math.hypot(cx, cy)
            collected.append(
                {
                    "r": radius,
                    "theta": math.degrees(math.atan2(cy, cx)) % 360.0,
                    "z": cz,
                    "area": float(gmsh.model.occ.getMass(2, tag)),
                    "shortest_edge_mm": shortest,
                    "full_revolution": full_revolution,
                    # Radial interval this face actually occupies. For an
                    # ordinary face the centroid is the only sample available;
                    # for a surface of revolution the bounding circles give the
                    # exact inner and outer radius.
                    "r_lo": min(circles) if circles else radius,
                    "r_hi": max(circles) if circles else radius,
                }
            )
        self._faces = collected
        return collected

    def _cut_plane_faces(self, sector, full, theta_low, theta_high, z_sym):
        """Count faces lying in each cut plane, and the face areas on them."""
        gmsh = self.gmsh
        counts = {"low": 0, "high": 0, "sym": 0}
        areas = {"low": 0.0, "high": 0.0, "sym": 0.0}
        for dim, tag in gmsh.model.getEntities(2):
            if dim != 2:
                continue
            cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, tag)
            uv = gmsh.model.getParametrization(2, tag, [cx, cy, cz])
            normal = _unit(list(gmsh.model.getNormal(tag, uv)[0:3]))
            if z_sym and abs(normal[2]) > 0.999 and abs(cz) < 1e-3:
                counts["sym"] += 1
                areas["sym"] += float(gmsh.model.occ.getMass(2, tag))
                continue
            if full:
                continue
            theta_c = math.degrees(math.atan2(cy, cx))
            for name, theta in (("low", theta_low), ("high", theta_high)):
                t = math.radians(theta)
                alignment = abs(-math.sin(t) * normal[0] + math.cos(t) * normal[1])
                if alignment > 0.999 and abs(theta_c - theta) < 0.3:
                    counts[name] += 1
                    areas[name] += float(gmsh.model.occ.getMass(2, tag))
        return counts, areas

    def preview(
        self,
        sector_deg: float,
        theta_low_deg: float = 0.0,
        z_symmetry: bool = True,
    ) -> dict:
        """Cut the candidate domain and report what actually came out."""
        gmsh = self.gmsh
        sector = float(sector_deg)
        full = sector >= 359.9
        theta_low = float(theta_low_deg)
        theta_high = theta_low + sector
        reach = self.r_outer_mm + 10.0
        thickness = self.z_half_mm + 2.0

        made = []
        try:
            body = gmsh.model.occ.copy([(3, self.source)])[0][1]
            if full:
                tool = gmsh.model.occ.addBox(
                    -reach,
                    -reach,
                    0.0 if z_symmetry else -thickness,
                    2.0 * reach,
                    2.0 * reach,
                    thickness if z_symmetry else 2.0 * thickness,
                )
            else:
                tool = gmsh.model.occ.addCylinder(
                    0,
                    0,
                    0.0 if z_symmetry else -thickness,
                    0,
                    0,
                    thickness if z_symmetry else 2.0 * thickness,
                    reach,
                    angle=math.radians(sector),
                )
                gmsh.model.occ.rotate(
                    [(3, tool)], 0, 0, 0, 0, 0, 1, math.radians(theta_low)
                )
            out, _ = gmsh.model.occ.intersect([(3, body)], [(3, tool)])
            gmsh.model.occ.synchronize()
            solids = [tag for dim, tag in out if dim == 3]
            if len(solids) != 1:
                return {
                    "domain": {
                        "sector_deg": sector,
                        "theta_low_deg": None if full else theta_low,
                        "z_symmetry": z_symmetry,
                    },
                    "error": (
                        f"cut produced {len(solids)} solids instead of 1 - this "
                        "domain does not carve a single connected piece out of "
                        "the part"
                    ),
                }
            made = [(3, tag) for tag in solids]

            volume = float(gmsh.model.occ.getMass(3, solids[0]))
            area = self._surface_area()
            counts, areas = self._cut_plane_faces(
                sector, full, theta_low, theta_high, z_symmetry
            )

            expected = (
                (sector / 360.0) * (0.5 if z_symmetry else 1.0)
            )
            volume_ratio = volume / self.full_volume if self.full_volume else 0.0
            area_ratio = area / self.full_area if self.full_area else 0.0
            volume_error = (
                (volume_ratio - expected) / expected * 100.0 if expected else 0.0
            )
            # How far the requested piece is from being a repeat unit. Small
            # means the cut respects the part's structure; large means material
            # was removed that the full part would have kept, so this domain
            # models something other than the part.
            return {
                "domain": {
                    "sector_deg": round(sector, 6),
                    "theta_low_deg": None if full else round(theta_low, 6),
                    "z_symmetry": z_symmetry,
                    "type": "full_360" if full else "cyclic_sector",
                },
                "solids": len(solids),
                "volume_mm3": round(volume, 3),
                "volume_ratio_of_whole": round(volume_ratio, 6),
                "expected_ratio_if_repeat_unit": round(expected, 6),
                "volume_error_percent": round(volume_error, 4),
                "surface_area_mm2": round(area, 3),
                "surface_area_ratio_of_whole": round(area_ratio, 6),
                "face_count": sum(
                    1 for dim, _ in gmsh.model.getEntities(2) if dim == 2
                ),
                "cut_plane_faces": counts,
                "cut_plane_area_mm2": {k: round(v, 3) for k, v in areas.items()},
            }
        finally:
            if made:
                try:
                    gmsh.model.occ.remove(made, recursive=True)
                    gmsh.model.occ.synchronize()
                except Exception:
                    pass
            self.volume_after_cleanup = None
