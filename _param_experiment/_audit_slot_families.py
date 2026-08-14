# -*- coding: utf-8 -*-
"""审计所有含榫槽族：depth 与 rim_radial 比、fr_limit、节距、槽口。"""
import sys, math
sys.path.insert(0, r'E:\text_to_cad_improve\auto_detection_process\_param_experiment')
import param_templates as pt
from sampling_constraints import _axisym_radii, check_slot_pitch
from design_families import DESIGN_FAMILIES

CATS = ("slot", "coupled", "complex_rim")
print(f"{'族':>5} {'form':>9} {'od':>4} {'teeth':>5} {'mouth':>5} {'depth':>5} {'rim_rad':>7} {'d/rim':>5} {'fr_lim':>6} {'节距':>5} {'槽口':>5} {'OK'}")
for fid, fam in DESIGN_FAMILIES.items():
    if fam.get("category") not in CATS:
        continue
    f = fam.get("features") or {}
    if "slots" not in f:
        continue
    od = fam["od"]; bore = fam["bore"]; form = fam.get("form", "standard")
    teeth = int(f.get("teeth", 2)); slots = int(f.get("slots", 60))
    depth = f.get("depth", 24.0); mouth = f.get("throat", 4.0); fr = f.get("fr", 1.0)
    R = f.get("R", od / 2.0)
    r = _axisym_radii(od, bore, form)
    rim_rad = r["rim_r"] - r["rim_junc"]
    ratio = depth / rim_rad if rim_rad else 0
    fl = pt.slot_fillet_fr_limit(teeth, depth, mouth, 45.0, 75.0)
    pitch = 2 * math.pi * R / slots
    ok = "OK" if 0.55 <= ratio <= 0.85 and fl >= 0.7 and 2 * mouth < pitch else "!!"
    print(f"{fid:>5} {form:>9} {od:>4} {teeth:>5} {mouth:>5} {depth:>5} {rim_rad:>7.1f} {ratio:>5.2f} {fl:>6.2f} {pitch:>5.1f} {2*mouth:>5} {ok}")
