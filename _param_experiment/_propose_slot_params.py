# -*- coding: utf-8 -*-
"""为含榫槽族生成建议参数：depth≈0.65×rim_radial、mouth 按 teeth、节距/圆角验证。"""
import sys, math
sys.path.insert(0, r'E:\text_to_cad_improve\auto_detection_process\_param_experiment')
import param_templates as pt
from sampling_constraints import _axisym_radii
from design_families import DESIGN_FAMILIES

CATS = ("slot", "coupled", "complex_rim")
# mouth 按 teeth（v6 等比例风格）：t2=8, t3=6, t4=7
MOUTH = {2: 8.0, 3: 6.0, 4: 7.0}

for fid, fam in DESIGN_FAMILIES.items():
    if fam.get("category") not in CATS:
        continue
    f = fam.get("features") or {}
    if "slots" not in f:
        continue
    od = fam["od"]; bore = fam["bore"]; form = fam.get("form", "standard")
    teeth = int(f.get("teeth", 2)); R = f.get("R", od / 2.0)
    r = _axisym_radii(od, bore, form)
    rim_rad = r["rim_r"] - r["rim_junc"]
    depth = round(0.6 * rim_rad, 1)
    mouth = MOUTH[teeth]
    # slots：节距 ≥ 槽口+3（槽间材料）
    slots = int(f.get("slots", 60))
    while 2 * math.pi * R / slots < 2 * mouth + 3:
        slots -= 4
    # fr_limit
    fl = pt.slot_fillet_fr_limit(teeth, depth, mouth, 45.0, 75.0)
    fr = round(min(f.get("fr", 1.0), fl), 2)
    print(f"'{fid}': {{'slots': {slots}, 'depth': {depth}, 'throat': {mouth}, 'fr': {fr}}}  # teeth={teeth} rim={rim_rad:.0f} d/rim={depth/rim_rad:.2f} fl={fl:.2f}")
