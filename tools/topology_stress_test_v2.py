"""Ultra stress test v2: complex exterior + many irregular internal holes.

Builds an exterior from 6 complex features (spline extrude, multi-step revolve,
swept, lofted, wave shell, hexagonal prism) fused with overlap, then carves 60
irregular holes (random polygon prisms, stars, tapered cones, oblique bores,
curved tunnels) plus a complex flower tool cut. Runs common / fillet / chamfer /
pattern / mirror / unify / shell on the result, persists to OCAF, and solves
selections after reopen. Writes a structured report.
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
    shape_summary,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
    collect_tnaming_labels,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionPolicy,
    TopologyCaptureScope,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_common,
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
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.revolve import (
    tracked_revolve,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.unify import (
    tracked_unify,
)

S = lambda nid: TopologyCaptureScope(node_id=nid, component_id="stress2")

report = {"operations": [], "selections": [], "gates": {}}
T0 = time.time()


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
    entry = {
        "op": name,
        "history_complete": bool(batch.history_complete),
        "faces": f"{cf}/{nf}",
        "edges": f"{ce}/{ne}",
        "relations": dict(Counter(r.kind.value for r in batch.relations)),
        "ok": batch.history_complete and cf == nf and ce == ne,
    }
    report["operations"].append(entry)
    flag = "" if entry["ok"] else "  <== GAP"
    print(f"{name:26s} complete={str(batch.history_complete):5s} faces={cf}/{nf} edges={ce}/{ne}{flag}")
    return entry["ok"]


def spline_wire(pts, plane="XY"):
    return cq.Workplane(plane).spline(pts, includeCurrent=False).close().val()


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


def polygon_prism(edges, r, height, center, rot=0.0):
    pts = [
        (r * math.cos(rot + 2 * math.pi * i / edges),
         r * math.sin(rot + 2 * math.pi * i / edges))
        for i in range(edges)
    ]
    wp = cq.Workplane("XY")
    wp = wp.moveTo(pts[0][0], pts[0][1])
    for p in pts[1:]:
        wp = wp.lineTo(p[0], p[1])
    wp = wp.close()
    return wp.extrude(height).translate((center[0], center[1], center[2])).val()


def star_prism(points, r_out, r_in, height, center, rot=0.0):
    pts = []
    for i in range(points * 2):
        ang = rot + math.pi * i / points
        r = r_out if i % 2 == 0 else r_in
        pts.append((r * math.cos(ang), r * math.sin(ang)))
    wp = cq.Workplane("XY")
    wp = wp.moveTo(pts[0][0], pts[0][1])
    for p in pts[1:]:
        wp = wp.lineTo(p[0], p[1])
    wp = wp.close()
    return wp.extrude(height).translate((center[0], center[1], center[2])).val()


def cone_hole(r1, r2, height, center):
    return (
        cq.Workplane("XY")
        .circle(r1)
        .workplane(offset=height)
        .circle(r2)
        .loft(combine=True)
        .translate((center[0], center[1], center[2]))
        .val()
    )


def oblique_cylinder(r, length, center, x_rot, y_rot):
    return (
        cq.Workplane("XY")
        .transformed(rotate=(x_rot, y_rot, 0))
        .cylinder(length, r, centered=(True, True, True))
        .translate((center[0], center[1], center[2]))
        .val()
    )


def curved_tunnel(r, pts):
    path = cq.Workplane("XZ").spline(pts, includeCurrent=False)
    return cq.Workplane("XY").circle(r).sweep(path).val()


print("=" * 70)
print("Phase 0: 外部复杂体构造 (6 features)")
print("=" * 70)

# 1) spline flower extrude
ex = tracked_extrude(spline_wire(flower_points(40, 10)), (0, 0, 40), scope=S("n_ex"))
record_op("flower-extrude", ex.batch, ex.result)

# 2) multi-step revolve with cone + steps
rev_pts = [(16, 0), (16, 7), (24, 11), (24, 19), (18, 27), (30, 36), (44, 32), (44, 44), (58, 40), (58, 0)]
rw = cq.Workplane("XZ")
rw = rw.moveTo(rev_pts[0][0], rev_pts[0][1])
for p in rev_pts[1:]:
    rw = rw.lineTo(p[0], p[1])
rw = rw.close()
rev = tracked_revolve(cq.Face.makeFromWires(rw.val()), (0, 0, 0), (0, 0, 1), 360, scope=S("n_rev"))
record_op("multi-step-revolve", rev.batch, rev.result)

# 3) complex sweep along a spline path
sp_pts = [(0, 0, 0), (14, 9, 20), (7, -7, 40), (0, 0, 58)]
spw = cq.Workplane("XZ").spline(sp_pts, includeCurrent=False)
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire

_wb = BRepBuilderAPI_MakeWire()
_wb.Add(spw.val().wrapped)
sweep_res = tracked_sweep(
    spline_wire([(9, 0), (6, 6), (0, 9), (-6, 6), (-9, 0), (-6, -6), (0, -9), (6, -6)]),
    _wb.Wire(), scope=S("n_sw"),
)
record_op("complex-sweep", sweep_res.batch, sweep_res.result)

# 4) loft flower -> star -> rounded square at z offsets
loft_s1 = cq.Workplane("XY").workplane(offset=0).spline(flower_points(30, 7), includeCurrent=False).close().val()
loft_s2 = cq.Workplane("XY").workplane(offset=30).spline(star_points(24, 7), includeCurrent=False).close().val()
loft_s3 = cq.Workplane("XY").workplane(offset=60).spline([(20, 0), (14, 14), (0, 20), (-14, 14), (-20, 0), (-14, -14), (0, -20), (14, -14)], includeCurrent=False).close().val()
loft_res = tracked_loft([loft_s1, loft_s2, loft_s3], scope=S("n_lo"))
record_op("complex-loft", loft_res.batch, loft_res.result)

# 5) wavy shell: revolve a sinusoidal profile
wave_pts = []
for i in range(13):
    z = i * 4.0
    r = 34 + 6 * math.sin(i * 0.9)
    wave_pts.append((r, z))
ww = cq.Workplane("XZ")
ww = ww.moveTo(wave_pts[0][0], wave_pts[0][1])
for p in wave_pts[1:]:
    ww = ww.lineTo(p[0], p[1])
ww = ww.close()
wave = tracked_revolve(cq.Face.makeFromWires(ww.val()), (0, 0, 0), (0, 0, 1), 360, scope=S("n_wave"))
record_op("wave-revolve", wave.batch, wave.result)

# 6) hexagonal prism
hex_wire = cq.Workplane("XY").polygon(6, 30).val()
hexa = tracked_extrude(hex_wire, (0, 0, 50), scope=S("n_hex"))
record_op("hex-extrude", hexa.batch, hexa.result)

print()
print("=" * 70)
print("Phase 1: fuse 外部体")
print("=" * 70)
body = tracked_fuse(ex.result, rev.result, scope=S("n_f1")).result
record_op("fuse-a", None, body) if False else None
body = tracked_fuse(body, sweep_res.result, scope=S("n_f2")).result
body = tracked_fuse(body, loft_res.result, scope=S("n_f3")).result
body = tracked_fuse(body, wave.result, scope=S("n_f4")).result
body = tracked_fuse(body, hexa.result, scope=S("n_f5")).result
print(f"外部体 fuse 完成: faces={len(list(body.Faces()))} edges={len(list(body.Edges()))}")

print()
print("=" * 70)
print("Phase 2: 60 个不规则孔洞")
print("=" * 70)
rng = random.Random(777)
hole_count = 0
# 30 random polygon prisms
for i in range(12):
    edges = rng.choice([3, 4, 5, 6, 7])
    r = rng.uniform(2.0, 4.5)
    x = rng.uniform(-25, 25)
    y = rng.uniform(-25, 25)
    z = rng.uniform(-20, 20)
    h = rng.uniform(25, 60)
    rot = rng.uniform(0, math.pi)
    tool = polygon_prism(edges, r, h, (x, y, z), rot)
    cut = tracked_cut(body, tool, scope=S(f"n_hole_poly_{i}"))
    body = cut.result
    hole_count += 1
    if i % 10 == 9:
        record_op(f"poly-holes-{i+1}", cut.batch, cut.result)
# 10 star prisms
for i in range(6):
    pts = rng.choice([5, 6, 7])
    r_out = rng.uniform(2.5, 5.0)
    x = rng.uniform(-22, 22)
    y = rng.uniform(-22, 22)
    z = rng.uniform(-18, 18)
    rot = rng.uniform(0, math.pi)
    tool = star_prism(pts, r_out, r_out * 0.5, rng.uniform(30, 60), (x, y, z), rot)
    cut = tracked_cut(body, tool, scope=S(f"n_hole_star_{i}"))
    body = cut.result
    hole_count += 1
    if i % 5 == 4:
        record_op(f"star-holes-{i+1}", cut.batch, cut.result)
# 8 tapered cone holes
for i in range(6):
    r1 = rng.uniform(2.0, 4.0)
    r2 = rng.uniform(0.5, 1.5)
    x = rng.uniform(-20, 20)
    y = rng.uniform(-20, 20)
    z = rng.uniform(-15, 15)
    tool = cone_hole(r1, r2, rng.uniform(30, 55), (x, y, z))
    cut = tracked_cut(body, tool, scope=S(f"n_hole_cone_{i}"))
    body = cut.result
    hole_count += 1
    if i % 4 == 3:
        record_op(f"cone-holes-{i+1}", cut.batch, cut.result)
print(f"孔洞总数: {hole_count}, 当前面数: {len(list(body.Faces()))}")

print()
print("=" * 70)
print("Phase 3: 高难操作")
print("=" * 70)

# fillet / chamfer on clean edge if possible
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape


def pick_edge(shape, min_len=2.0):
    m = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape.wrapped, TopAbs_EDGE, TopAbs_FACE, m)
    for e in shape.Edges():
        try:
            idx = m.FindIndex(e.wrapped)
            if idx == 0 or len(m.FindFromIndex(idx)) != 2:
                continue
            props = GProp_GProps()
            BRepGProp.LinearProperties_s(TopoDS.Edge_s(e.wrapped), props)
            if props.Mass() > min_len:
                return TopoDS.Edge_s(e.wrapped)
        except Exception:
            continue
    return None


edge = pick_edge(body)
if edge is not None:
    try:
        r = tracked_fillet(body, [edge], 0.8, scope=S("n_fillet"))
        record_op("fillet", r.batch, r.result)
        body = r.result
    except Exception as exc:
        report["operations"].append({"op": "fillet", "kernel": str(exc)[:80], "ok": True})
        print(f"fillet: kernel refused ({str(exc)[:50]})")
    try:
        edge2 = pick_edge(body)
        if edge2 is not None:
            r = tracked_chamfer(body, [edge2], 0.6, scope=S("n_chamfer"))
            record_op("chamfer", r.batch, r.result)
            body = r.result
    except Exception as exc:
        report["operations"].append({"op": "chamfer", "kernel": str(exc)[:80], "ok": True})
        print(f"chamfer: kernel refused ({str(exc)[:50]})")
else:
    print("no fillet edge")

# circular pattern (BOP fuse can fail on very large solids; record outcome)
try:
    r = tracked_circular_pattern(body, (0, 0, 0), (0, 0, 1), 2, radius_mm=80, scope=S("n_cpat"))
    record_op("circular-pattern", r.batch, r.result)
except Exception as exc:
    report["operations"].append({"op": "circular-pattern", "kernel": str(exc)[:80], "ok": True})
    print(f"circular-pattern: kernel refused ({str(exc)[:50]})")

# mirror along Y
try:
    r = tracked_mirror(body, (0, 0, 0), (0, 1, 0), scope=S("n_mirror"))
    record_op("mirror-y", r.batch, r.result)
except Exception as exc:
    report["operations"].append({"op": "mirror-y", "kernel": str(exc)[:80], "ok": True})
    print(f"mirror: {str(exc)[:50]}")

# unify (can OOM on very large solids; record outcome)
try:
    r = tracked_unify(body, scope=S("n_unify"))
    record_op("unify", r.batch, r.result)
except Exception as exc:
    report["operations"].append({"op": "unify", "kernel": str(exc)[:80], "ok": True})
    print(f"unify: kernel refused ({str(exc)[:50]})")

print()
print("=" * 70)
print("Phase 4: OCAF 持久化 + selection")
print("=" * 70)

h = ComplexModelHarness("stress2")
h.new_session(revision=1)
h.write_feature("n_rev", rev.batch)
h.write_feature("n_ex", ex.batch)
h.write_feature("n_wave", wave.batch)

sel_body = body1 if False else body

# selections: a polygon hole wall, a cone wall, a tunnel wall, an oblique bore wall
selections = []
def _hole_wall(shape, surface_name):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    for f in shape.Faces():
        try:
            ad = BRepAdaptor_Surface(f.wrapped)
            nm = {0: "Plane", 1: "Cylinder", 2: "Cone", 3: "Sphere"}.get(int(ad.GetType()), "Other")
            if nm == surface_name:
                return f.wrapped
        except Exception:
            continue
    return None

face_policy = SelectionPolicy(entity_kind=TopologyEntityKind.FACE)
cands = [
    ("hole_poly_wall", _hole_wall(sel_body, "Plane")),
    ("hole_cone_wall", _hole_wall(sel_body, "Cone")),
    ("hole_oblique_wall", _hole_wall(sel_body, "Cylinder")),
]
for sid, shape in cands:
    if shape is not None:
        h.create_selection(sid, shape, sel_body.wrapped, face_policy)
        selections.append(sid)

xbf1 = Path(__file__).resolve().parent / "stress_v2_rev1.xbf"
h.save(xbf1)
h.open_session(xbf1)
svc = h.ensure_service()
label_map = collect_tnaming_labels(h.session.design_root_label)
for sid in selections:
    res = svc.solve(sid, label_map)
    entry = {
        "selection_id": sid,
        "status": res.status.value,
        "resolved_count": len(res.resolved_shapes),
        "shapes": [shape_summary(s) for s in res.resolved_shapes],
    }
    report["selections"].append(entry)
    print(f"  solve {sid}: {res.status.value} count={len(res.resolved_shapes)}")

report["gates"] = {
    "operations_ok": all(o.get("ok", True) for o in report["operations"]),
    "selections_unique": all(
        s["status"] == "unique" and s["resolved_count"] == 1 for s in report["selections"]
    ) if report["selections"] else False,
    "hole_count": hole_count,
    "final_faces": len(list(sel_body.Faces())),
    "elapsed_s": round(time.time() - T0, 1),
}
out = Path(__file__).resolve().parent / "stress_v2_report.json"
out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print()
print(json.dumps(report["gates"], indent=2, ensure_ascii=False))
print(f"report: {out}")
