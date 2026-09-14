"""Generic persistent-face-role inspection tools for the structural agent.

No turbine-disc, slot, pressure-flank, rotation-axis or temperature profile is
encoded here. The tools only expose facts about topology roles so an agent can
inspect candidates and make the structural decisions itself.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/engineering_tools/src"))
CACHE_ROOT = Path(__file__).resolve().parent / "cache"


def _debug(message: str):
    if os.environ.get("STRUCTURE_DEBUG"):
        print(message, file=sys.stderr, flush=True)

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (  # noqa: E402
    OcafDocumentSession,
)


def _surface_type_name(surface) -> str:
    from OCP.GeomAbs import (
        GeomAbs_BSplineSurface,
        GeomAbs_BezierSurface,
        GeomAbs_Cone,
        GeomAbs_Cylinder,
        GeomAbs_Plane,
        GeomAbs_Sphere,
        GeomAbs_Torus,
    )

    names = {
        GeomAbs_Plane: "plane",
        GeomAbs_Cylinder: "cylinder",
        GeomAbs_Cone: "cone",
        GeomAbs_Sphere: "sphere",
        GeomAbs_Torus: "torus",
        GeomAbs_BezierSurface: "bezier_surface",
        GeomAbs_BSplineSurface: "bspline_surface",
    }
    return names.get(surface.GetType(), "other")


def _axis_facts(axis):
    location = axis.Location()
    direction = axis.Direction()
    return {
        "origin_mm": [location.X(), location.Y(), location.Z()],
        "direction": [direction.X(), direction.Y(), direction.Z()],
    }


def face_facts(shape) -> dict:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepTools import BRepTools
    from OCP.Bnd import Bnd_Box
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopoDS import TopoDS

    if shape.ShapeType() != TopAbs_FACE:
        raise ValueError("role does not resolve to a face")

    face = TopoDS.Face_s(shape)
    _debug("face_facts: calculating area")
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    centroid = props.CentreOfMass()
    cx, cy, cz = centroid.X(), centroid.Y(), centroid.Z()
    r = math.hypot(cx, cy)
    theta = math.degrees(math.atan2(cy, cx))

    surface = BRepAdaptor_Surface(face)
    _debug("face_facts: calculating surface")
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    u = 0.5 * (u0 + u1)
    v = 0.5 * (v0 + v1)
    point = gp_Pnt()
    du = gp_Vec()
    dv = gp_Vec()
    surface.D1(u, v, point, du, dv)
    nx = du.Y() * dv.Z() - du.Z() * dv.Y()
    ny = du.Z() * dv.X() - du.X() * dv.Z()
    nz = du.X() * dv.Y() - du.Y() * dv.X()
    magnitude = math.sqrt(nx * nx + ny * ny + nz * nz)
    normal = None
    if magnitude > 1e-15:
        normal = [nx / magnitude, ny / magnitude, nz / magnitude]
        # The D1 cross product follows the surface parametrisation, not the
        # face orientation: a REVERSED face reports an inward-pointing normal.
        # Flip it so every reported normal points out of the solid, otherwise
        # any radial/tangential sign filter selects by parametrisation rather
        # than by geometry.
        if face.Orientation() == TopAbs_REVERSED:
            normal = [-value for value in normal]
        if abs(r) > 1e-12:
            radial = [cx / r, cy / r, 0.0]
            tangential = [-cy / r, cx / r, 0.0]
            normal_cyl = {
                "radial": sum(normal[i] * radial[i] for i in range(3)),
                "tangential": sum(normal[i] * tangential[i] for i in range(3)),
                "axial": normal[2],
            }
        else:
            normal_cyl = {"radial": None, "tangential": None, "axial": normal[2]}
    else:
        normal_cyl = None

    _debug("face_facts: bounding box")
    bnd = Bnd_Box()
    BRepBndLib.Add_s(face, bnd)
    xmin, ymin, zmin, xmax, ymax, zmax = bnd.Get()
    bbox = [xmin, ymin, zmin, xmax, ymax, zmax]

    _debug("face_facts: counting edges")
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(face, TopAbs_EDGE, edge_map)
    edge_count = edge_map.Extent()

    result = {
        "surface_type": _surface_type_name(surface),
        "area_mm2": float(props.Mass()),
        "centroid_mm": [cx, cy, cz],
        "centroid_cyl_mm_deg": [r, theta, cz],
        "normal_xyz": normal,
        "normal_cylindrical": normal_cyl,
        "uv_bounds": [u0, u1, v0, v1],
        "bbox_mm": bbox if bbox[0] != float("inf") else None,
        "edge_count": edge_count,
    }
    if surface.GetType() == GeomAbs_Plane:
        result["plane_axis"] = _axis_facts(surface.Plane().Axis())
    elif surface.GetType() == GeomAbs_Cylinder:
        result["cylinder_axis"] = _axis_facts(surface.Cylinder().Axis())
        result["cylinder_radius_mm"] = float(surface.Cylinder().Radius())
    elif surface.GetType() == GeomAbs_Cone:
        result["cone_axis"] = _axis_facts(surface.Cone().Axis())
        result["cone_semi_angle_deg"] = math.degrees(surface.Cone().SemiAngle())
    return result


def _role_entries(session):
    return [
        entry
        for entry in session.label_index.entries()
        if entry.retired_revision is None and entry.key.object_kind == "face_role"
    ]


def _cache_path(bundle: Path, namespace: str) -> Path:
    safe = namespace.replace(":", "_").replace("/", "_")
    return CACHE_ROOT / f"{bundle.name}__{safe}.jsonl"


def _load_namespace_cache(bundle: Path, namespace: str) -> dict[tuple[str, str], dict]:
    path = _cache_path(bundle, namespace)
    rows = {}
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "facts" in row:
            rows[(row["namespace"], row["key"])] = row["facts"]
    return rows


def build_namespace_cache(bundle: Path, namespace: str, limit: int | None = None):
    bundle = bundle.resolve()
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    path = _cache_path(bundle, namespace)
    done = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            done.add(row.get("key"))
    session = OcafDocumentSession.open(bundle / "design.xbf")
    try:
        entries = [
            entry
            for entry in _role_entries(session)
            if entry.key.namespace == namespace
            and entry.key.object_id not in done
        ]
        if limit is not None:
            entries = entries[:limit]
        with path.open("a", encoding="utf-8", newline="\n") as out:
            for index, entry in enumerate(entries, 1):
                row = {
                    "namespace": entry.key.namespace,
                    "key": entry.key.object_id,
                }
                try:
                    rows = resolve_role_facts(
                        session, entry.key.namespace, entry.key.object_id
                    )
                    row["facts"] = rows["facts"]
                except Exception as exc:
                    row["error"] = str(exc)
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                if index % 50 == 0:
                    _debug(
                        f"cache {namespace}: {index}/{len(entries)} "
                        f"last={entry.key.object_id}"
                    )
    finally:
        session.close()
    return path


def list_roles(session, namespace: str | None, limit: int):
    roles = [
        entry
        for entry in _role_entries(session)
        if namespace is None or entry.key.namespace == namespace
    ]
    return [
        {
            "namespace": entry.key.namespace,
            "key": entry.key.object_id,
            "label_path": list(entry.tag_path.tags),
        }
        for entry in roles[:limit]
    ]


def resolve_role_facts(session, namespace: str, key: str) -> dict:
    _debug(f"resolve_role: lookup {namespace}/{key}")
    entry = session.label_index.get_existing("face_role", namespace, key)
    if entry is None or entry.retired_revision is not None:
        raise KeyError(f"face role not found: {namespace}/{key}")
    role_label = entry.tag_path.resolve(session.main_label)
    _debug("resolve_role: role label resolved")
    feature_label = role_label.Father().Father()
    role_tag = role_label.Tag()
    _debug("resolve_role: reading shape")
    shape = session.get_current_role_result(feature_label, role_tag)
    _debug("resolve_role: shape read")
    if shape is None:
        raise RuntimeError(f"role has no current shape: {namespace}/{key}")
    return {
        "namespace": namespace,
        "key": key,
        "label_path": list(entry.tag_path.tags),
        "facts": face_facts(shape),
    }


class RoleCatalog:
    """Persistent-session catalog with lazy, cached geometric facts."""

    def __init__(self, bundle: Path):
        self.bundle = Path(bundle).resolve()
        self.session = OcafDocumentSession.open(self.bundle / "design.xbf")
        self._facts_cache: dict[tuple[str, str], dict] = {}
        self._namespace_cache: dict[str, dict[tuple[str, str], dict]] = {}
        self._cache_dir = Path(__file__).resolve().parent / "cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def close(self):
        self.session.close()

    def namespaces(self):
        counts = {}
        for entry in _role_entries(self.session):
            counts[entry.key.namespace] = counts.get(entry.key.namespace, 0) + 1
        return counts

    def list_roles(self, namespace=None, key_prefix=None, offset=0, limit=100):
        namespace_cache = {}
        if namespace is not None:
            if namespace not in self._namespace_cache:
                self._namespace_cache[namespace] = _load_namespace_cache(
                    self.bundle, namespace
                )
            namespace_cache = self._namespace_cache[namespace]
        result = []
        for entry in _role_entries(self.session):
            if namespace is not None and entry.key.namespace != namespace:
                continue
            if key_prefix is not None and not entry.key.object_id.startswith(
                key_prefix
            ):
                continue
            if offset > 0:
                offset -= 1
                continue
            item = {
                "namespace": entry.key.namespace,
                "key": entry.key.object_id,
            }
            cached = namespace_cache.get((entry.key.namespace, entry.key.object_id))
            if cached is not None:
                item["facts"] = cached
            result.append(item)
            if len(result) >= limit:
                break
        return result

    def facts(self, namespace: str, key: str):
        cache_key = (namespace, key)
        if cache_key in self._facts_cache:
            return self._facts_cache[cache_key]
        if namespace not in self._namespace_cache:
            self._namespace_cache[namespace] = _load_namespace_cache(
                self.bundle, namespace
            )
        if cache_key in self._namespace_cache[namespace]:
            facts = self._namespace_cache[namespace][cache_key]
            self._facts_cache[cache_key] = facts
            return facts
        safe_name = (
            str(self.bundle.name)
            + "__"
            + namespace.replace(":", "_").replace("/", "_")
            + "__"
            + key.replace(":", "_").replace("/", "_")
            + ".json"
        )
        cache_path = self._cache_dir / safe_name
        if cache_path.is_file():
            self._facts_cache[cache_key] = json.loads(
                cache_path.read_text(encoding="utf-8")
            )
            return self._facts_cache[cache_key]
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                str(self.bundle),
                "facts",
                "--namespace",
                namespace,
                "--key",
                key,
            ],
            capture_output=True,
            text=True,
            timeout=90,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"role fact worker failed ({result.returncode}): "
                + (result.stderr[-500:] or result.stdout[-500:])
            )
        payload = json.loads(result.stdout)
        facts = payload["facts"]
        cache_path.write_text(
            json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._facts_cache[cache_key] = facts
        return self._facts_cache[cache_key]

    def query(
        self,
        namespace=None,
        key_prefix=None,
        surface_type=None,
        area_min=None,
        area_max=None,
        radial_min=None,
        radial_max=None,
        theta_min=None,
        theta_max=None,
        z_min=None,
        z_max=None,
        normal_radial_min=None,
        normal_radial_max=None,
        normal_tangential_min=None,
        normal_tangential_max=None,
        normal_axial_min=None,
        normal_axial_max=None,
        limit=12,
        offset=0,
    ):
        matches = []
        namespace_cache = None
        if namespace is not None:
            if namespace not in self._namespace_cache:
                self._namespace_cache[namespace] = _load_namespace_cache(
                    self.bundle, namespace
                )
            namespace_cache = self._namespace_cache[namespace]
        if namespace_cache is not None:
            candidates = [
                {"namespace": namespace, "key": key}
                for namespace, key in namespace_cache
                if key_prefix is None or key.startswith(key_prefix)
            ][offset : offset + min(max(1, limit), 5000)]
        else:
            candidates = self.list_roles(
                namespace=namespace,
                key_prefix=key_prefix,
                offset=offset,
                limit=min(max(1, limit), 12),
            )
        for role in candidates:
            try:
                facts = self.facts(role["namespace"], role["key"])
            except Exception:
                continue
            if surface_type is not None and facts["surface_type"] != surface_type:
                continue
            area = facts["area_mm2"]
            r, theta, z = facts["centroid_cyl_mm_deg"]
            normal = facts.get("normal_cylindrical") or {}
            checks = [
                (area_min, area, lambda value, bound: value >= bound),
                (area_max, area, lambda value, bound: value <= bound),
                (radial_min, r, lambda value, bound: value >= bound),
                (radial_max, r, lambda value, bound: value <= bound),
                (theta_min, theta, lambda value, bound: value >= bound),
                (theta_max, theta, lambda value, bound: value <= bound),
                (z_min, z, lambda value, bound: value >= bound),
                (z_max, z, lambda value, bound: value <= bound),
                (
                    normal_radial_min,
                    normal.get("radial"),
                    lambda value, bound: value is not None and value >= bound,
                ),
                (
                    normal_radial_max,
                    normal.get("radial"),
                    lambda value, bound: value is not None and value <= bound,
                ),
                (
                    normal_tangential_min,
                    normal.get("tangential"),
                    lambda value, bound: value is not None and value >= bound,
                ),
                (
                    normal_tangential_max,
                    normal.get("tangential"),
                    lambda value, bound: value is not None and value <= bound,
                ),
                (
                    normal_axial_min,
                    normal.get("axial"),
                    lambda value, bound: value is not None and value >= bound,
                ),
                (
                    normal_axial_max,
                    normal.get("axial"),
                    lambda value, bound: value is not None and value <= bound,
                ),
            ]
            if all(
                bound is None or predicate(value, bound)
                for bound, value, predicate in checks
            ):
                matches.append(
                    {
                        "namespace": role["namespace"],
                        "key": role["key"],
                        "facts": facts,
                    }
                )
            if len(matches) >= limit:
                break
        return matches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list")
    list_parser.add_argument("--namespace")
    list_parser.add_argument("--limit", type=int, default=200)
    sub.add_parser("namespaces")

    facts_parser = sub.add_parser("facts")
    facts_parser.add_argument("--namespace", required=True)
    facts_parser.add_argument("--key", required=True)
    cache_parser = sub.add_parser("cache")
    cache_parser.add_argument("--namespace", required=True)
    cache_parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    if args.command == "cache":
        payload = {
            "cache": str(
                build_namespace_cache(args.bundle, args.namespace, args.limit)
            )
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    _debug("opening OCAF")
    session = OcafDocumentSession.open(args.bundle.resolve() / "design.xbf")
    _debug("OCAF opened")
    try:
        if args.command == "list":
            payload = list_roles(session, args.namespace, args.limit)
        elif args.command == "namespaces":
            counts = {}
            for entry in _role_entries(session):
                counts[entry.key.namespace] = counts.get(entry.key.namespace, 0) + 1
            payload = counts
        else:
            payload = resolve_role_facts(session, args.namespace, args.key)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        session.close()


if __name__ == "__main__":
    main()
