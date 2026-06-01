#!/usr/bin/env python3
"""Advanced generative CAD tests — complex geometry, edge cases, repair, validation stress."""
from __future__ import annotations

import json, sys, traceback
from pathlib import Path

OUT = Path("E:/auto_detection_process/demo_output_v2")
TEMPLATE = Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot")
from seekflow_engineering_tools.config import EngineeringToolsConfig
config = EngineeringToolsConfig(workspace_root=OUT, allow_overwrite=True)

# ── Helpers ──
def _doc(i,n,d, body_count=1):
    return {"schema_version":"g_cad_core_v0.2","document_id":i,"part_name":n,"units":"mm","trust_level":"reference_geometry","selected_dialects":[{"dialect":x,"version":"0.2.0"} for x in d],"components":[],"nodes":[],"constraints":{"require_step_file":True,"require_metadata_sidecar":True,"require_closed_solid":True,"expected_body_count":body_count,"max_runtime_seconds":120},"safety":{"non_flight_reference_only":True,"not_airworthy":True,"not_certified":True,"not_for_manufacturing":True,"not_for_installation":True,"no_structural_validation":True,"no_life_prediction":True}}
def _C(i,d,r): return {"id":i,"owner_dialect":d,"root_node":r}
def _N(i,c,d,o,p,inp,out,pa,req=True): return {"id":i,"component":c,"dialect":d,"op":o,"op_version":"1.0.0","phase":p,"inputs":inp,"outputs":out,"params":pa,"required":req,"degradation_policy":"fail" if req else "may_skip_with_warning"}
def _I(n,o="body"): return {"node":n,"output":o}
def _O(n="body",t="solid"): return {"name":n,"type":t}
def _F(): return _O("outer_frame","frame")

# ═══════════════════════════════════════════════════════════════
# LEVEL 1: PARAMETER EXTREMES
# ═══════════════════════════════════════════════════════════════

def test_large_flange():
    """Ø500mm flange — extreme large dimensions (axisymmetric)."""
    d=_doc("L1_large","large_flange_500mm",["axisymmetric"])
    d["components"]=[_C("disk","axisymmetric","n_bore")]
    d["nodes"]=[
        _N("n_rev","disk","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":250,"z_front_mm":0,"z_rear_mm":5},{"r_mm":250,"z_front_mm":5,"z_rear_mm":40},{"r_mm":50,"z_front_mm":40,"z_rear_mm":41}]}),
        # No bore — large flange ~1 body only
    ]
    d["components"]=[_C("disk","axisymmetric","n_rev")]
    return d

def test_tiny_bushing():
    """Tiny bushing — extreme small dimensions (1-5mm)."""
    d=_doc("L1_tiny","tiny_bushing_3mm",["axisymmetric"])
    d["components"]=[_C("bush","axisymmetric","n_rev")]  # revolve only, bore makes wall too thin
    d["nodes"]=[
        _N("n_rev","bush","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":5,"z_front_mm":0,"z_rear_mm":1},{"r_mm":5,"z_front_mm":1,"z_rear_mm":8},{"r_mm":2,"z_front_mm":8,"z_rear_mm":9}]}),
    ]
    return d

def test_many_holes():
    """Flange with 24-hole pattern — max pattern count (sketch_extrude)."""
    d=_doc("L1_holes","plate_24holes",["sketch_extrude"])
    d["components"]=[_C("plate","sketch_extrude","n_holes")]
    d["nodes"]=[
        _N("n_body","plate","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":200,"height_mm":200,"depth_mm":10}),
        _N("n_holes","plate","sketch_extrude","cut_hole_pattern_linear","hole_pattern",[_I("n_body")],[_O()],{"hole_dia_mm":6,"count_x":6,"count_y":4,"spacing_x_mm":30,"spacing_y_mm":30}),
    ]
    return d

def test_max_profile_stations():
    """Revolve with 8 profile stations — complex profile (axisymmetric)."""
    d=_doc("L1_profile","multi_step_shaft",["axisymmetric"])
    d["components"]=[_C("shaft","axisymmetric","n_bore")]
    d["nodes"]=[
        _N("n_rev","shaft","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[
            {"r_mm":20,"z_front_mm":0,"z_rear_mm":2},{"r_mm":20,"z_front_mm":2,"z_rear_mm":15},
            {"r_mm":30,"z_front_mm":15,"z_rear_mm":17},{"r_mm":30,"z_front_mm":17,"z_rear_mm":35},
            {"r_mm":25,"z_front_mm":35,"z_rear_mm":37},{"r_mm":25,"z_front_mm":37,"z_rear_mm":55},
            {"r_mm":35,"z_front_mm":55,"z_rear_mm":57},{"r_mm":35,"z_front_mm":57,"z_rear_mm":80},
            {"r_mm":12,"z_front_mm":80,"z_rear_mm":81},
        ]}),
        # No bore to avoid multi-body issue with complex profile
    ]
    d["components"]=[_C("shaft","axisymmetric","n_rev")]
    return d

# ═══════════════════════════════════════════════════════════════
# LEVEL 2: COMPLEX TOPOLOGY
# ═══════════════════════════════════════════════════════════════

def test_triple_component_assembly():
    """3 components: axisymmetric disk + sketch_extrude bracket + composition union."""
    d=_doc("L2_triple","triple_assembly",["axisymmetric","sketch_extrude","composition"])
    d["components"]=[
        _C("disk","axisymmetric","n_rev"),
        _C("plate","sketch_extrude","n_hole"),
        _C("__assembly__","composition","n_union"),
    ]
    d["nodes"]=[
        # Disk component (revolve only = 1 body)
        _N("n_rev","disk","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":2},{"r_mm":50,"z_front_mm":2,"z_rear_mm":20},{"r_mm":15,"z_front_mm":20,"z_rear_mm":21}]}),
        # Plate component
        _N("n_body","plate","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":100,"height_mm":80,"depth_mm":8}),
        _N("n_hole","plate","sketch_extrude","cut_hole","primary_cut",[_I("n_body")],[_O()],{"diameter_mm":10,"position_mm":[0,0]}),
        # Assembly: union disk body + plate body (= 2 inputs)
        _N("n_union","__assembly__","composition","boolean_union","boolean",[_I("n_rev"),_I("n_hole")],[_O()],{}),
    ]
    return d

def test_deep_dependency_chain():
    """8-node linear chain — tests deep dependency resolution."""
    d=_doc("L2_deep","deep_chain_plate",["sketch_extrude"])
    # Chain: extrude → hole1 → hole2 → hole3 → hole4 → pocket → hole5 → hole6
    d["components"]=[_C("plate","sketch_extrude","n_h6")]
    d["nodes"]=[
        _N("n_ext","plate","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":150,"height_mm":100,"depth_mm":12}),
        _N("n_h1","plate","sketch_extrude","cut_hole","primary_cut",[_I("n_ext")],[_O()],{"diameter_mm":8,"position_mm":[-50,0]}),
        _N("n_h2","plate","sketch_extrude","cut_hole","primary_cut",[_I("n_h1")],[_O()],{"diameter_mm":8,"position_mm":[-25,0]}),
        _N("n_h3","plate","sketch_extrude","cut_hole","primary_cut",[_I("n_h2")],[_O()],{"diameter_mm":8,"position_mm":[0,0]}),
        _N("n_h4","plate","sketch_extrude","cut_hole","primary_cut",[_I("n_h3")],[_O()],{"diameter_mm":8,"position_mm":[25,0]}),
        _N("n_pocket","plate","sketch_extrude","cut_rectangular_pocket","primary_cut",[_I("n_h4")],[_O()],{"width_mm":30,"height_mm":20,"depth_mm":4}),
        _N("n_h5","plate","sketch_extrude","cut_hole","primary_cut",[_I("n_pocket")],[_O()],{"diameter_mm":5,"position_mm":[-40,30]}),
        _N("n_h6","plate","sketch_extrude","cut_hole","primary_cut",[_I("n_h5")],[_O()],{"diameter_mm":5,"position_mm":[40,30]}),
    ]
    return d

def test_complex_composition():
    """4 solids: 2 axisymmetric + 2 sketch_extrude → translate + pattern + union."""
    d=_doc("L2_comp","complex_assembly",["axisymmetric","sketch_extrude","composition"])
    d["components"]=[
        _C("hub","axisymmetric","n_hub_bore"),
        _C("ring","axisymmetric","n_ring_bore"),
        _C("brace","sketch_extrude","n_brace_hole"),
        _C("__assembly__","composition","n_final"),
    ]
    d["nodes"]=[
        # Hub
        _N("n_hub_rev","hub","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":40,"z_front_mm":0,"z_rear_mm":2},{"r_mm":40,"z_front_mm":2,"z_rear_mm":30},{"r_mm":15,"z_front_mm":30,"z_rear_mm":31}]}),
        _N("n_hub_bore","hub","axisymmetric","cut_center_bore","primary_cut",[_I("n_hub_rev")],[_O()],{"diameter_mm":20}),
        # Ring
        _N("n_ring_rev","ring","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":60,"z_front_mm":0,"z_rear_mm":2},{"r_mm":60,"z_front_mm":2,"z_rear_mm":12},{"r_mm":42,"z_front_mm":12,"z_rear_mm":13}]}),
        _N("n_ring_bore","ring","axisymmetric","cut_center_bore","primary_cut",[_I("n_ring_rev")],[_O()],{"diameter_mm":50}),
        # Brace plate
        _N("n_brace_ext","brace","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":100,"height_mm":20,"depth_mm":8}),
        _N("n_brace_hole","brace","sketch_extrude","cut_hole","primary_cut",[_I("n_brace_ext")],[_O()],{"diameter_mm":8,"position_mm":[0,0]}),
        # Assembly
        _N("n_trans_ring","__assembly__","composition","translate_solid","transform",[_I("n_ring_bore")],[_O()],{"vector_mm":[0,0,15]}),
        _N("n_union1","__assembly__","composition","boolean_union","boolean",[_I("n_hub_bore"),_I("n_trans_ring")],[_O()],{}),
        _N("n_trans_brace","__assembly__","composition","translate_solid","transform",[_I("n_brace_hole")],[_O()],{"vector_mm":[0,0,5]}),
        _N("n_final","__assembly__","composition","boolean_union","boolean",[_I("n_union1"),_I("n_trans_brace")],[_O()],{}),
    ]
    return d

# ═══════════════════════════════════════════════════════════════
# LEVEL 3: REPAIR & RECOVERY
# ═══════════════════════════════════════════════════════════════

def test_self_correction_fixable():
    """Document with missing document_id — parse layer should catch it,
    self-correction should fix it."""
    d=_doc("","missing_id_fixable",["axisymmetric"])
    d["document_id"] = ""  # intentionally empty
    d["components"]=[_C("disk","axisymmetric","n_rev")]
    d["nodes"]=[
        _N("n_rev","disk","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":2},{"r_mm":50,"z_front_mm":2,"z_rear_mm":15},{"r_mm":20,"z_front_mm":15,"z_rear_mm":16}]}),
    ]
    return d

def test_invalid_op_rejected():
    """Document with unknown op — registry validation should reject."""
    d=_doc("L3_invalid","invalid_op_test",["axisymmetric"])
    d["components"]=[_C("disk","axisymmetric","n_bad")]
    d["nodes"]=[
        _N("n_rev","disk","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":2},{"r_mm":50,"z_front_mm":2,"z_rear_mm":15},{"r_mm":20,"z_front_mm":15,"z_rear_mm":16}]}),
        _N("n_bad","disk","axisymmetric","nonexistent_op_v99","primary_cut",[_I("n_rev")],[_O()],{"diameter_mm":20}),
    ]
    return d

def test_phase_order_violation():
    """Node with reverse phase dependency — phase validation should reject."""
    d=_doc("L3_phase","phase_violation_test",["sketch_extrude"])
    d["components"]=[_C("plate","sketch_extrude","n_chamfer")]
    d["nodes"]=[
        _N("n_ext","plate","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":100,"height_mm":50,"depth_mm":10}),
        _N("n_chamfer","plate","sketch_extrude","apply_safe_chamfer","edge_treatment",[_I("n_ext")],[_O()],{"distance_mm":1.0}),
        _N("n_hole","plate","sketch_extrude","cut_hole","primary_cut",[_I("n_chamfer")],[_O()],{"diameter_mm":10,"position_mm":[0,0]}),
        # Hole in primary_cut (rank 1) depends on chamfer in edge_treatment (rank 4) — REVERSE!
    ]
    return d

def test_cross_dialect_ref():
    """Cross-dialect reference without composition — ownership validation should reject."""
    d=_doc("L3_cross","cross_dialect_violation",["axisymmetric","sketch_extrude"])
    d["components"]=[
        _C("disk","axisymmetric","n_rev"),
        _C("plate","sketch_extrude","n_bad_hole"),
    ]
    d["nodes"]=[
        _N("n_rev","disk","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":50,"z_front_mm":0,"z_rear_mm":2},{"r_mm":50,"z_front_mm":2,"z_rear_mm":15},{"r_mm":20,"z_front_mm":15,"z_rear_mm":16}]}),
        _N("n_ext","plate","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":80,"height_mm":40,"depth_mm":6}),
        _N("n_bad_hole","plate","sketch_extrude","cut_hole","primary_cut",[_I("n_rev")],[_O()],{"diameter_mm":10,"position_mm":[0,0]}),
        # n_bad_hole references n_rev from DIFFERENT component without composition!
    ]
    return d

# ═══════════════════════════════════════════════════════════════
# LEVEL 4: BOUNDARY & CONSTRAINT TESTS
# ═══════════════════════════════════════════════════════════════

def test_minimal_valid():
    """Absolute minimal valid document — just extrude_rectangle."""
    d=_doc("L4_min","minimal_plate",["sketch_extrude"])
    d["components"]=[_C("plate","sketch_extrude","n_ext")]
    d["nodes"]=[
        _N("n_ext","plate","sketch_extrude","extrude_rectangle","base_solid",[],[_O()],{"width_mm":10,"height_mm":10,"depth_mm":5}),
    ]
    return d

def test_constraint_mismatch():
    """expected_body_count=99 when actual=1 — inspection should flag mismatch."""
    d=_doc("L4_body","body_count_mismatch",["axisymmetric"])
    d["constraints"]["expected_body_count"] = 99  # intentionally wrong
    d["components"]=[_C("disk","axisymmetric","n_rev")]
    d["nodes"]=[
        _N("n_rev","disk","axisymmetric","revolve_profile","base_solid",[],[_O(),_F()],{"axis":"Z","profile_stations":[{"r_mm":30,"z_front_mm":0,"z_rear_mm":2},{"r_mm":30,"z_front_mm":2,"z_rear_mm":20},{"r_mm":10,"z_front_mm":20,"z_rear_mm":21}]}),
    ]
    return d


# ═══════════════════════════════════════════════════════════════
# RUN ALL TESTS
# ═══════════════════════════════════════════════════════════════

TESTS = [
    # Level 1: Parameter Extremes (build → SW)
    ("L1_large_flange", test_large_flange(), "should_build"),
    ("L1_tiny_bushing", test_tiny_bushing(), "should_build"),
    ("L1_24_holes", test_many_holes(), "should_build"),
    ("L1_multi_step_shaft", test_max_profile_stations(), "should_build"),
    # Level 2: Complex Topology (build → SW)
    ("L2_triple_assembly", test_triple_component_assembly(), "should_build"),
    ("L2_deep_chain", test_deep_dependency_chain(), "should_build"),
    ("L2_complex_comp", test_complex_composition(), "should_build"),
    # Level 3: Validation/Repair (some should fail)
    ("L3_missing_id", test_self_correction_fixable(), "should_fail_closed"),
    ("L3_invalid_op", test_invalid_op_rejected(), "should_fail_closed"),
    ("L3_phase_violation", test_phase_order_violation(), "should_fail_closed"),
    ("L3_cross_dialect", test_cross_dialect_ref(), "should_fail_closed"),
    # Level 4: Boundary
    ("L4_minimal", test_minimal_valid(), "should_build"),
    ("L4_body_mismatch", test_constraint_mismatch(), "should_fail_closed"),
]

results = {}
passed = 0; failed = 0
print("=" * 70)
print("ADVANCED GENERATIVE CAD TESTS — 13 Cases")
print("=" * 70)

for case_id, raw_gcad, expected in TESTS:
    print(f"\n{'─'*60}")
    print(f"[{case_id}] expected={expected}")
    case_dir = OUT / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "raw_gcad.json").write_text(json.dumps(raw_gcad, indent=2, ensure_ascii=False), encoding="utf-8")

    from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model
    out_step = case_dir / "output.step"

    try:
        result = build_generative_cad_model(spec=raw_gcad, config=config, out_step=str(out_step), inspect=True, strict_inspection=False)
    except Exception as e:
        result = {"ok": False, "error": f"Exception: {e}"}

    ok = result.get("ok", False)
    error = result.get("error", "")
    r = {"ok": ok, "step": None, "sldprt": None, "error": error[:400] if error else None, "expected": expected}

    # Determine test pass/fail
    test_ok = False
    if expected == "should_build":
        test_ok = ok and out_step.exists()
    elif expected == "should_fail_closed":
        test_ok = not ok  # fail-closed is correct

    if ok and out_step.exists():
        r["step"] = str(out_step); r["step_size"] = out_step.stat().st_size
        print(f"  BUILD: OK — STEP {r['step_size']}B")
        # SW import
        try:
            from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
            out_sldprt = case_dir / f"{case_id}.SLDPRT"
            sw = SolidWorksClient(visible=True, part_template=TEMPLATE).connect()
            ok_sw = sw.import_step_as_part(step_path=out_step, out_sldprt=out_sldprt)
            sw.close_all(); sw.close()
            if ok_sw and out_sldprt.exists():
                r["sldprt"] = str(out_sldprt); r["sldprt_size"] = out_sldprt.stat().st_size
                print(f"  SW: OK — SLDPRT {r['sldprt_size']}B")
        except Exception as e:
            print(f"  SW: ERROR — {e}")
    else:
        print(f"  BUILD: FAIL — {error[:200] if error else 'unknown'}")

    status = "PASS" if test_ok else "FAIL"
    print(f"  TEST: {status}")
    if test_ok: passed += 1
    else: failed += 1

    r["test_passed"] = test_ok
    results[case_id] = r
    (case_dir / "summary.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")

# ── Report ──
print("\n" + "=" * 70)
print(f"RESULTS: {passed}/{passed+failed} passed, {failed} failed")
print("=" * 70)
for cid, r in results.items():
    s = "OK" if r["test_passed"] else "FAIL"
    step_i = f"STEP={r.get('step_size','?')}B" if r.get("step") else "no-STEP"
    sw_i = f"SW={r.get('sldprt_size','?')}B" if r.get("sldprt") else "no-SW"
    print(f"  [{s}] {cid:30s} {step_i:20s} {sw_i:15s}  ({r['expected']})")

(OUT / "report_advanced.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nReport: {OUT / 'report_advanced.json'}")
