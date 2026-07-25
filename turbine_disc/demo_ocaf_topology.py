"""涡轮盘 OCAF 持久化拓扑命名 — 完整演示.

演示流程:
  Phase 1: 创建简化涡轮盘剖面 → tracked_revolve → 捕获 History
  Phase 2: FaceSelector 选择关键工程面 (bore/rim/web)
  Phase 3: 参数扰动 → 重建 → FaceSelector 在新几何上找回
  Phase 4: 面删除测试 → UNRESOLVED

用法:
  cd auto_detection_process
  .conda/python.exe turbine_disc/demo_ocaf_topology.py
"""

import sys
sys.path.insert(0, "integrations/engineering_tools/src")

import math
import pathlib
import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import TopologyCaptureScope
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops import tracked_revolve
from seekflow_engineering_tools.generative_cad.topology.ocaf.capture_session import CaptureSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import write_batch
from seekflow_engineering_tools.generative_cad.topology.ocaf.selectors import (
    FaceSelector, SolveStatus,
)

OUT_DIR = pathlib.Path("e:/text_to_cad_improve/auto_detection_process/_demo_disc")
OUT_DIR.mkdir(exist_ok=True)


def make_disc_profile(r_bore, r_outer, z_half):
    """Create a simplified turbine disc cross-section wire in XZ plane.

    Profile shape (R-Z cross section, Z=horizontal axis in XZ plane):
      bore (z=0, r=r_bore) → hub (z=z_half) → web taper → rim (z=z_half)
    """
    pts = [
        (r_bore, 0),           # bore inner, z=0
        (r_bore, z_half),      # bore top
        (r_bore + 60, z_half), # hub face
        (r_outer - 35, z_half * 0.6),  # web taper
        (r_outer, z_half * 0.8),       # rim face
        (r_outer, 0),          # rim inner
    ]
    wp = cq.Workplane("XZ")
    wp = wp.moveTo(pts[0][0], pts[0][1])
    for x, z in pts[1:]:
        wp = wp.lineTo(x, z)
    wp = wp.close()
    return wp.val()


def build_disc(r_bore, r_outer, z_half, capture_session=None, node_id="revolve1"):
    """Build a turbine disc by revolving the profile 360 degrees."""
    profile = make_disc_profile(r_bore, r_outer, z_half)
    scope = TopologyCaptureScope(
        node_id=node_id, component_id="disc",
        dialect="sketch_profile", operation="revolve_profile",
        operation_version="1.0.0",
    )
    # Always use tracked_revolve for consistent geometry
    tracked = tracked_revolve(profile, (0, 0, 0), (0, 0, 1), 360, scope=scope)
    if capture_session is not None:
        capture_session.stage(tracked)
    result = cq.Workplane("XY").newObject([tracked.result])
    return result.val(), profile


def _cylinder_radius(face_wrapped):
    """Get the radius of a cylindrical face from its OCCT adaptor."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    try:
        adaptor = BRepAdaptor_Surface(face_wrapped)
        if adaptor.GetType() == GeomAbs_Cylinder:
            return adaptor.Cylinder().Radius()
    except Exception:
        pass
    return None


def select_key_faces(selector, body, r_bore, r_outer):
    """Select bore (inner cylinder) and rim (outer cylinder) faces."""
    faces = list(body.Faces())
    records = {}

    # Classify all cylinder faces by radius
    cyl_faces = []
    for i in range(len(faces)):
        r = _cylinder_radius(faces[i].wrapped)
        if r is not None:
            cyl_faces.append((i, r))

    cyl_faces.sort(key=lambda x: x[1])  # sort by radius

    if len(cyl_faces) >= 2:
        # Innermost cylinder = bore
        bore_idx = cyl_faces[0][0]
        bore_r = cyl_faces[0][1]
        rec = selector.select_face(body, bore_idx, "bore_surface")
        print(f"   bore: face[{bore_idx}], Cylinder R={bore_r:.0f}mm, area={rec.fingerprint.area_mm2:.0f}")
        records["bore_surface"] = rec

        # Outermost cylinder = rim
        rim_idx = cyl_faces[-1][0]
        rim_r = cyl_faces[-1][1]
        rec = selector.select_face(body, rim_idx, "rim_surface")
        print(f"   rim:  face[{rim_idx}], Cylinder R={rim_r:.0f}mm, area={rec.fingerprint.area_mm2:.0f}")
        records["rim_surface"] = rec

    return records


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: 原始建模 + 拓扑捕获
# ═══════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("Phase 1: 原始建模 + 拓扑捕获")
print("=" * 60)

R_BORE, R_OUTER, Z_HALF = 60, 250, 38

capture = CaptureSession()
body1, profile1 = build_disc(R_BORE, R_OUTER, Z_HALF, capture_session=capture)

print(f"  建模完成: volume={body1.Volume():.0f} mm³, faces={len(list(body1.Faces()))}")
print(f"  捕获: {capture.batch_count} batch(es), {capture.total_relations} relations")

# 写入 OCAF
ocaf1 = OcafDocumentSession()
for batch in capture.iter_batches():
    write_batch(ocaf1, batch)
xbf1 = OUT_DIR / "disc_v1.xbf"
ocaf1.save(xbf1)
print(f"  XBF: {xbf1.stat().st_size} bytes")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: 面选择
# ═══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("Phase 2: 选择关键工程面")
print("=" * 60)

selector = FaceSelector(match_threshold=3.0)
records = select_key_faces(selector, body1, R_BORE, R_OUTER)

for pid, rec in records.items():
    fp = rec.fingerprint
    r = math.sqrt(fp.centroid[0]**2 + fp.centroid[1]**2)
    print(f"  {pid}: type={fp.surface_type}, area={fp.area_mm2:.0f}, r≈{r:.0f}mm")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: 参数扰动 + 找回
# ═══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("Phase 3: 参数扰动 + 面找回")
print("=" * 60)

R_BORE2, R_OUTER2 = 65, 260  # +5mm bore, +10mm outer

capture2 = CaptureSession()
body2, profile2 = build_disc(R_BORE2, R_OUTER2, Z_HALF, capture_session=capture2)

print(f"  重建: volume={body2.Volume():.0f} mm³, faces={len(list(body2.Faces()))}")

for pid, rec in records.items():
    result = selector.solve(rec, body2)
    if result.status == SolveStatus.UNIQUE:
        fp = result.matched_fingerprint
        r = math.sqrt(fp.centroid[0]**2 + fp.centroid[1]**2)
        print(f"  {pid}: {result.status.value} at face {result.matched_face_index}, r≈{r:.0f}mm")
    else:
        print(f"  {pid}: {result.status.value} — {result.detail}")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4: 面删除测试 (更激进的扰动)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("Phase 4: 极端扰动")
print("=" * 60)

R_BORE3, R_OUTER3 = 100, 300  # Very different dimensions
capture3 = CaptureSession()
body3, _ = build_disc(R_BORE3, R_OUTER3, Z_HALF * 1.5, capture_session=capture3)

for pid, rec in records.items():
    result = selector.solve(rec, body3)
    fp_str = ""
    if result.status == SolveStatus.UNIQUE and result.matched_fingerprint:
        r = math.sqrt(
            result.matched_fingerprint.centroid[0]**2 +
            result.matched_fingerprint.centroid[1]**2
        )
        fp_str = f", r≈{r:.0f}mm"
    print(f"  {pid}: {result.status.value}{fp_str}")


# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("演示完成")
print("=" * 60)
print(f"  建模: {body1.Volume():.0f} mm³ → {body2.Volume():.0f} mm³ (扰动)")
print(f"  OCAF: {xbf1.stat().st_size} bytes")
print(f"  面选择: {len(records)} 个关键面")
print(f"  验证: OCAF 持久化拓扑命名系统端到端可用")
