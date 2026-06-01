#!/usr/bin/env python3
"""All 6 parts through generative CAD path. Corrected params, no chamfer on axisymmetric."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path("E:/auto_detection_process/demo_output_v2")
TEMPLATE = Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot")
from seekflow_engineering_tools.config import EngineeringToolsConfig
config = EngineeringToolsConfig(workspace_root=OUT, allow_overwrite=True)

def _doc(i, n, d):
    return {"schema_version":"g_cad_core_v0.2","document_id":i,"part_name":n,"units":"mm","trust_level":"reference_geometry","selected_dialects":[{"dialect":x,"version":"0.2.0"} for x in d],"components":[],"nodes":[],"constraints":{"require_step_file":True,"require_metadata_sidecar":True,"require_closed_solid":True,"expected_body_count":1,"max_runtime_seconds":120},"safety":{"non_flight_reference_only":True,"not_airworthy":True,"not_certified":True,"not_for_manufacturing":True,"not_for_installation":True,"no_structural_validation":True,"no_life_prediction":True}}
def _C(i,d,r): return {"id":i,"owner_dialect":d,"root_node":r}
def _N(i,c,d,o,p,inp,out,pa,req=True): return {"id":i,"component":c,"dialect":d,"op":o,"op_version":"1.0.0","phase":p,"inputs":inp,"outputs":out,"params":pa,"required":req,"degradation_policy":"fail" if req else "may_skip_with_warning"}
def _I(n,o="body"): return {"node":n,"output":o}
def _O(n="body",t="solid"): return {"name":n,"type":t}
def _F(): return _O("outer_frame","frame")

# ═══ Part 1: Axisymmetric Flange (revolve+bore only, 1 body guaranteed) ═══
def p1():
    d=_doc("f1","axisymmetric_flange",["axisymmetric"])
    d["components"]=[_C("disk","axisymmetric","n_bore")]
    d["nodes"]=[
        _N("n_revolve","disk","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":60,"z_front_mm":0,"z_rear_mm":2},{"r_mm":60,"z_front_mm":2,"z_rear_mm":16},{"r_mm":20,"z_front_mm":16,"z_rear_mm":17}]}),
        _N("n_bore","disk","axisymmetric","cut_center_bore","primary_cut",[_I("n_revolve")],[_O()],{"diameter_mm":40}),
    ]
    return d

# ═══ Part 2: Hex Nut (sketch_extrude: extrude+hole+chamfer) ═══
def p2():
    d=_doc("h1","hex_nut_m12",["sketch_extrude"])
    d["components"]=[_C("nut","sketch_extrude","n_chamfer")]
    d["nodes"]=[
        _N("n_body","nut","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":19,"height_mm":17,"depth_mm":10}),
        _N("n_hole","nut","sketch_extrude","cut_hole","primary_cut",[_I("n_body")],[_O()],{"diameter_mm":12,"position_mm":[0,0]}),
        _N("n_chamfer","nut","sketch_extrude","apply_safe_chamfer","edge_treatment",[_I("n_hole")],[_O()],{"distance_mm":1.0}),
    ]
    return d

# ═══ Part 3: L-Bracket (sketch_extrude×2 + composition, no fillet on thin plates) ═══
def p3():
    d=_doc("b1","l_bracket",["sketch_extrude","composition"])
    d["components"]=[_C("base","sketch_extrude","n_base_hole2"),_C("vert","sketch_extrude","n_vert_hole"),_C("__assembly__","composition","n_union")]
    d["nodes"]=[
        _N("n_base_extrude","base","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":80,"height_mm":40,"depth_mm":6}),
        _N("n_base_hole1","base","sketch_extrude","cut_hole","primary_cut",[_I("n_base_extrude")],[_O()],{"diameter_mm":6,"position_mm":[-20,0]}),
        _N("n_base_hole2","base","sketch_extrude","cut_hole","primary_cut",[_I("n_base_hole1")],[_O()],{"diameter_mm":6,"position_mm":[20,0]}),
        _N("n_vert_extrude","vert","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":80,"height_mm":50,"depth_mm":6}),
        _N("n_vert_hole","vert","sketch_extrude","cut_hole","primary_cut",[_I("n_vert_extrude")],[_O()],{"diameter_mm":10,"position_mm":[0,20]}),
        _N("n_translate","__assembly__","composition","translate_solid","transform",[_I("n_vert_hole")],[_O()],{"vector_mm":[0,0,6]}),
        _N("n_union","__assembly__","composition","boolean_union","boolean",[_I("n_base_hole2"),_I("n_translate")],[_O()],{}),
    ]
    return d

# ═══ Part 4: Simple Bushing (axisymmetric, 2-station profile) ═══
def p4():
    d=_doc("bf1","simple_bushing",["axisymmetric"])
    d["components"]=[_C("bushing","axisymmetric","n_bore")]
    d["nodes"]=[
        _N("n_rev","bushing","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":40,"z_front_mm":0,"z_rear_mm":5},{"r_mm":40,"z_front_mm":5,"z_rear_mm":50},{"r_mm":15,"z_front_mm":50,"z_rear_mm":51}]}),
        _N("n_bore","bushing","axisymmetric","cut_center_bore","primary_cut",[_I("n_rev")],[_O()],{"diameter_mm":25}),
    ]
    return d

# ═══ Part 5: Stepped Disk (axisymmetric, revolve only, guaranteed 1 body) ═══
def p5():
    d=_doc("sh1","stepped_disk",["axisymmetric"])
    d["components"]=[_C("disk","axisymmetric","n_rev")]
    d["nodes"]=[
        _N("n_rev","disk","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":30,"z_front_mm":0,"z_rear_mm":2},{"r_mm":30,"z_front_mm":2,"z_rear_mm":10},{"r_mm":50,"z_front_mm":10,"z_rear_mm":12},{"r_mm":50,"z_front_mm":12,"z_rear_mm":30},{"r_mm":15,"z_front_mm":30,"z_rear_mm":31}]}),
    ]
    return d

# ═══ Part 6: Ribbed Bracket (sketch_extrude with holes+boss+rib) ═══
def p6():
    d=_doc("rb1","ribbed_bracket",["sketch_extrude"])
    d["components"]=[_C("bracket","sketch_extrude","n_rib")]
    d["nodes"]=[
        _N("n_body","bracket","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":60,"height_mm":40,"depth_mm":8}),
        _N("n_hole1","bracket","sketch_extrude","cut_hole","primary_cut",[_I("n_body")],[_O()],{"diameter_mm":8,"position_mm":[-18,0]}),
        _N("n_hole2","bracket","sketch_extrude","cut_hole","primary_cut",[_I("n_hole1")],[_O()],{"diameter_mm":8,"position_mm":[18,0]}),
        _N("n_boss","bracket","sketch_extrude","add_rectangular_boss","boss_rib",[_I("n_hole2")],[_O()],{"width_mm":20,"height_mm":15,"depth_mm":20,"position_mm":[0,0]}),
        _N("n_rib","bracket","sketch_extrude","add_rib","boss_rib",[_I("n_boss")],[_O()],{"thickness_mm":4,"height_mm":15,"length_mm":30,"position_mm":[0,20]}),
    ]
    return d

# ═══ Build & Export ═══
PARTS = [
    ("axisymmetric_flange", p1()),
    ("hex_nut_m12_generative", p2()),
    ("l_bracket_generative", p3()),
    ("simple_bushing", p4()),
    ("stepped_disk", p5()),
    ("ribbed_bracket", p6()),
]

results = {}
print("=" * 60)
print("Generative CAD — All 6 Parts")
print("=" * 60)

for case_id, raw_gcad in PARTS:
    print(f"\n--- {case_id} ---")
    case_dir = OUT / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "raw_gcad.json").write_text(json.dumps(raw_gcad, indent=2, ensure_ascii=False), encoding="utf-8")

    from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model
    out_step = case_dir / "output.step"
    result = build_generative_cad_model(spec=raw_gcad, config=config, out_step=str(out_step), inspect=True, strict_inspection=False)
    ok = result.get("ok", False)
    error = result.get("error", "")
    r = {"ok": ok, "step": None, "sldprt": None, "error": error[:300] if error else None}

    if ok and out_step.exists():
        r["step"] = str(out_step); r["step_size"] = out_step.stat().st_size
        print(f"  STEP: {r['step_size']} bytes")
        try:
            from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
            out_sldprt = case_dir / f"{case_id}.SLDPRT"
            sw = SolidWorksClient(visible=True, part_template=TEMPLATE).connect()
            ok_sw = sw.import_step_as_part(step_path=out_step, out_sldprt=out_sldprt)
            sw.close_all(); sw.close()
            if ok_sw and out_sldprt.exists():
                r["sldprt"] = str(out_sldprt); r["sldprt_size"] = out_sldprt.stat().st_size
                print(f"  SLDPRT: {r['sldprt_size']} bytes")
            else:
                print(f"  SLDPRT: import failed")
        except Exception as e:
            print(f"  SW ERROR: {e}")
    else:
        print(f"  BUILD FAILED: {error[:250] if error else 'unknown'}")

    results[case_id] = r
    (case_dir / "summary.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")

print("\n" + "=" * 60)
print("FINAL REPORT")
print("=" * 60)
for cid, r in results.items():
    s = "OK" if r["ok"] else "FAIL"
    si = f"STEP={r.get('step_size','?')}B" if r.get("step") else "NO STEP"
    swi = f"SLDPRT={r.get('sldprt_size','?')}B" if r.get("sldprt") else "NO SLDPRT"
    print(f"  [{s}] {cid}: {si}, {swi}")
(OUT / "report_generative.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nReport: {OUT / 'report_generative.json'}")
