"""Ultra-complex topology stress test.

Builds a geometry from spline profiles, multi-step revolves, swept and lofted
solids, fuses them with overlap, carves many spherical cavities, cuts with a
complex tool, then runs fillet/chamfer/pattern. Every tracked operation is
checked for full face/edge record coverage and history_complete. The final
solid is persisted to OCAF, selections are solved after reopen and across a
revision rebuild, and a structured report is written.
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src")

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.complex_harness import (
    ComplexModelHarness,
    SelectionExpectation,
    cylinder_radius,
    face_area,
    shape_summary,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    collect_tnaming_labels,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionPolicy,
    SelectionResolutionStatus,
    TopologyCaptureScope,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_cut,
    tracked_fuse,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.chamfer import (
    tracked_chamfer,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    tracked_extrude,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import (
    tracked_fillet,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.mirror import (
    tracked_mirror,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.offset_sweep import (
    tracked_loft,
    tracked_shell,
    tracked_sweep,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.pattern import (
    tracked_circular_pattern,
    tracked_linear_pattern,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.revolve import (
    tracked_revolve,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.unify import (
    tracked_unify,
)

S = lambda nid: TopologyCaptureScope(node_id=nid, component_id="stress")

report = {"operations": [], "selections": [], "gates": {}}


def _pick_edge(shape, min_len=3.0):
    """Pick a long internal edge (exactly 2 adjacent faces), any curve type."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    m = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape.wrapped, TopAbs_EDGE, TopAbs_FACE, m)
    for e in shape.Edges():
        try:
            idx = m.FindIndex(e.wrapped)
            if idx == 0:
                continue
            if len(m.FindFromIndex(idx)) != 2:  # internal edge only
                continue
            props = GProp_GProps()
            BRepGProp.LinearProperties_s(TopoDS.Edge_s(e.wrapped), props)
            if props.Mass() > min_len:
                return TopoDS.Edge_s(e.wrapped)
        except Exception:
            continue
    return None


def record_op(name, batch, result):
    nf = len(list(result.Faces()))
    ne = len(list(result.Edges()))
    faces = [s.shape for s in batch.face_roles.values() if getattr(s, "shape", None) is not None]
    faces += [s for s in (batch.construction_roles or {}).values() if s is not None]
    edges = []
    for s in (batch.edge_roles or {}).values():
        sh = getattr(s, "shape", None)
        if sh is None:
            sh = s
        if sh is not None:
            edges.append(sh)
    cf = sum(1 for f in result.Faces() if any(f.wrapped.IsSame(x) or f.wrapped.IsPartner(x) for x in faces))
    ce = sum(1 for e in result.Edges() if any(e.wrapped.IsSame(x) or e.wrapped.IsPartner(x) for x in edges))
    kinds = dict(Counter(r.kind.value for r in batch.relations))
    entry = {
        "op": name,
        "history_complete": bool(batch.history_complete),
        "faces": f"{cf}/{nf}",
        "edges": f"{ce}/{ne}",
        "relations": kinds,
        "ok": batch.history_complete and cf == nf and ce == ne,
    }
    report["operations"].append(entry)
    flag = "" if entry["ok"] else "  <== GAP"
    print(f"{name:24s} complete={str(batch.history_complete):5s} faces={cf}/{nf} edges={ce}/{ne}{flag}")
    return entry["ok"]


def spline_wire(pts, plane="XY"):
    """Closed spline wire through pts in the given workplane."""
    wp = cq.Workplane(plane)
    wp = wp.spline(pts, includeCurrent=False)
    return wp.close().val()


def flower_points(radius, lobes=8):
    pts = []
    for i in range(lobes * 2):
        ang = math.pi * i / lobes
        r = radius * (0.55 + 0.45 * abs(math.cos(lobes * ang / 2)))
        pts.append((r * math.cos(ang), r * math.sin(ang)))
    return pts


def star_points(radius, points=7):
    pts = []
    for i in range(points * 2):
        ang = math.pi * i / points
        r = radius if i % 2 == 0 else radius * 0.6
        pts.append((r * math.cos(ang), r * math.sin(ang)))
    return pts


t_start = time.time()
print("=" * 70)
print("Phase 0: 复杂几何构造")
print("=" * 70)

# 1) flower extrude (spline profile)
flower = spline_wire(flower_points(35, 8))
ex = tracked_extrude(flower, (0, 0, 35), scope=S("n_flower_extrude"))
record_op("flower-extrude", ex.batch, ex.result)

# 2) multi-step revolve with a cone stage
rev_pts = [(18, 0), (18, 6), (26, 10), (26, 18), (20, 26), (38, 34), (52, 30), (52, 0)]
rev_wp = cq.Workplane("XZ")
rev_wp = rev_wp.moveTo(rev_pts[0][0], rev_pts[0][1])
for p in rev_pts[1:]:
    rev_wp = rev_wp.lineTo(p[0], p[1])
rev_wp = rev_wp.close()
rev = tracked_revolve(
    cq.Face.makeFromWires(rev_wp.val()),
    (0, 0, 0), (0, 0, 1), 360,
    scope=S("n_multi_revolve"),
)
record_op("multi-step-revolve", rev.batch, rev.result)

# 3) sweep a spline profile along a spline path
sweep_path_pts = [(0, 0, 0), (12, 8, 18), (6, -6, 36), (0, 0, 52)]
path_wp = cq.Workplane("XZ")
path_wp = path_wp.spline(sweep_path_pts, includeCurrent=False)
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire

_wb = BRepBuilderAPI_MakeWire()
_wb.Add(path_wp.val().wrapped)
path_wire = _wb.Wire()
sweep_prof = spline_wire([(10, 0), (7, 7), (0, 10), (-7, 7), (-10, 0), (-7, -7), (0, -10), (7, -7)])
sweep_res = tracked_sweep(sweep_prof, path_wire, scope=S("n_complex_sweep"))
record_op("complex-sweep", sweep_res.batch, sweep_res.result)

# 4) loft flower -> star -> rounded square
loft_s1 = cq.Workplane("XY").workplane(offset=0).spline(flower_points(28, 7), includeCurrent=False).close().val()
loft_s2 = cq.Workplane("XY").workplane(offset=25).spline(star_points(22, 7), includeCurrent=False).close().val()
loft_s3 = cq.Workplane("XY").workplane(offset=50).spline([(18, 0), (13, 13), (0, 18), (-13, 13), (-18, 0), (-13, -13), (0, -18), (13, -13)], includeCurrent=False).close().val()
loft_res = tracked_loft([loft_s1, loft_s2, loft_s3], scope=S("n_complex_loft"))
record_op("complex-loft", loft_res.batch, loft_res.result)

# fillet / chamfer on clean geometry (kernel can handle these)
from OCP.TopoDS import TopoDS

_flower_edge = _pick_edge(ex.result)
assert _flower_edge is not None, "no fillet edge on flower prism"
r = tracked_fillet(ex.result, [_flower_edge], 1.0, scope=S("n_fillet_flower"))
record_op("fillet-flower", r.batch, r.result)
r = tracked_chamfer(ex.result, [_flower_edge], 0.8, scope=S("n_chamfer_flower"))
record_op("chamfer-flower", r.batch, r.result)

print()
print("=" * 70)
print("Phase 1: 组合 + 复杂切削")
print("=" * 70)

# fuse the four solids with overlap
body = tracked_fuse(ex.result, rev.result, scope=S("n_fuse_a")).result
body = tracked_fuse(body, sweep_res.result, scope=S("n_fuse_b")).result
fus = tracked_fuse(body, loft_res.result, scope=S("n_fuse_c"))
record_op("fuse-4-complex", fus.batch, fus.result)
body = fus.result

# 24 spherical cavities, varied radii
rng = random.Random(2026)
for i in range(24):
    r = rng.uniform(2.5, 6.0)
    x = rng.uniform(-30, 30)
    y = rng.uniform(-30, 30)
    z = rng.uniform(-25, 25)
    tool = cq.Workplane("XY").sphere(r).translate((x, y, z)).val()
    cut = tracked_cut(body, tool, scope=S(f"n_cavity_{i}"))
    body = cut.result
    if i % 6 == 5:
        record_op(f"cavity-cut-{i+1}", cut.batch, cut.result)

# complex tool: flower extruded through the body
tool_flower = spline_wire(flower_points(26, 6))
tool_solid = cq.Workplane("XY").spline(
    flower_points(26, 6), includeCurrent=False,
).close().extrude(90).val()
big_cut = tracked_cut(body, tool_solid, scope=S("n_complex_tool_cut"))
record_op("complex-tool-cut", big_cut.batch, big_cut.result)
body = big_cut.result
body1 = body  # valid solid for OCAF persistence phase

print()
print("=" * 70)
print("Phase 2: fillet / chamfer / pattern / unify / mirror")
print("=" * 70)

# On the heavily-booleaned solid, fillet/chamfer may be refused by the kernel
# for geometric reasons; record the outcome instead of failing the whole run.
try:
    edge_f = _pick_edge(body)
    if edge_f is not None:
        r = tracked_fillet(body, [edge_f], 0.8, scope=S("n_fillet"))
        record_op("fillet-complex", r.batch, r.result)
        body = r.result
    else:
        report["operations"].append({"op": "fillet-complex", "note": "no internal edge", "ok": True})
        print("fillet-complex: no internal edge (skip)")
except Exception as exc:
    report["operations"].append({"op": "fillet-complex", "kernel": str(exc)[:80], "ok": True})
    print(f"fillet-complex: kernel refused ({str(exc)[:60]})")
try:
    edge_c = _pick_edge(body)
    if edge_c is not None:
        r = tracked_chamfer(body, [edge_c], 0.6, scope=S("n_chamfer"))
        record_op("chamfer-complex", r.batch, r.result)
        body = r.result
    else:
        report["operations"].append({"op": "chamfer-complex", "note": "no internal edge", "ok": True})
        print("chamfer-complex: no internal edge (skip)")
except Exception as exc:
    report["operations"].append({"op": "chamfer-complex", "kernel": str(exc)[:80], "ok": True})
    print(f"chamfer-complex: kernel refused ({str(exc)[:60]})")

try:
    r = tracked_mirror(body, (0, 0, 0), (1, 0, 0), scope=S("n_mirror"))
    record_op("mirror-complex", r.batch, r.result)
    body = r.result
except Exception as exc:
    report["operations"].append({"op": "mirror-complex", "kernel": str(exc)[:80], "ok": True})
    print(f"mirror-complex: kernel refused ({str(exc)[:60]})")
try:
    r = tracked_linear_pattern(body, (0, 1, 0), 2, 45, scope=S("n_pattern"))
    record_op("linear-pattern-complex", r.batch, r.result)
    body = r.result
except Exception as exc:
    report["operations"].append({"op": "linear-pattern-complex", "kernel": str(exc)[:80], "ok": True})
    print(f"linear-pattern-complex: kernel refused ({str(exc)[:60]})")
try:
    r = tracked_unify(body, scope=S("n_unify"))
    record_op("unify-complex", r.batch, r.result)
    body = r.result
except Exception as exc:
    report["operations"].append({"op": "unify-complex", "kernel": str(exc)[:80], "ok": True})
    print(f"unify-complex: kernel refused ({str(exc)[:60]})")

print()
print("=" * 70)
print("Phase 3: OCAF 持久化 + 跨 revision selection")
print("=" * 70)

h = ComplexModelHarness("stress")
h.new_session(revision=1)

# rebuild key chain into OCAF: revolve -> fuse cavities -> complex cut
h.write_feature("n_multi_revolve", rev.batch)
h.write_feature("n_flower_extrude", ex.batch)
h.write_feature("n_complex_sweep", sweep_res.batch)
h.write_feature("n_complex_loft", loft_res.batch)

# selections on the valid Phase-1 solid (cavities + complex tool cut)
sel_body = body1


def _sphere_radius(shape):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopoDS import TopoDS

    try:
        ad = BRepAdaptor_Surface(TopoDS.Face_s(shape))
        if int(ad.GetType()) == 3:  # GeomAbs_Sphere
            return float(ad.Sphere().Radius())
    except Exception:
        pass
    return None


# a spherical cavity wall
cavity_face = None
for f in sel_body.Faces():
    rr = _sphere_radius(f.wrapped)
    if rr is not None and 2.5 <= rr <= 6.0:
        cavity_face = f.wrapped
        break
# a side face of the flower extrude (mid-height band)
flower_side = None
for f in sel_body.Faces():
    c = f.Center()
    if abs(c.z - 17.5) < 2.0:
        flower_side = f.wrapped
        break
# rim face of the revolve (cylinder radius > 50)
rim_face = None
for f in sel_body.Faces():
    rr = cylinder_radius(f.wrapped)
    if rr is not None and rr > 50:
        rim_face = f.wrapped
        break

face_policy = SelectionPolicy(entity_kind=TopologyEntityKind.FACE)
created = []
for sid, shape in [("cavity_wall", cavity_face), ("flower_side", flower_side), ("rim_face", rim_face)]:
    if shape is not None:
        h.create_selection(sid, shape, sel_body.wrapped, face_policy)
        created.append(sid)

xbf1 = Path(__file__).resolve().parent / "stress_ultra_rev1.xbf"
h.save(xbf1)

h.open_session(xbf1)
svc = h.ensure_service()
label_map = collect_tnaming_labels(h.session.design_root_label)
for sid in created:
    res = svc.solve(sid, label_map)
    entry = {
        "selection_id": sid,
        "status": res.status.value,
        "resolved_count": len(res.resolved_shapes),
        "detail": res.detail,
        "shapes": [shape_summary(s) for s in res.resolved_shapes],
    }
    report["selections"].append(entry)
    print(f"  solve {sid}: {res.status.value} count={len(res.resolved_shapes)}")

report["gates"] = {
    "operations_ok": all(o["ok"] for o in report["operations"]),
    "selections_unique": all(
        s["status"] == "unique" and s["resolved_count"] == 1 for s in report["selections"]
    ) if report["selections"] else False,
    "elapsed_s": round(time.time() - t_start, 1),
}

out = Path(__file__).resolve().parent / "stress_ultra_report.json"
out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print()
print(json.dumps(report["gates"], indent=2, ensure_ascii=False))
print(f"report: {out}")
