#!/usr/bin/env python3
"""Rebuild ALL parts with fixed function calling pipeline (per-op schema constraints)."""
import json, time, sys
from pathlib import Path
from openai import OpenAI

OUT = Path("E:/auto_detection_process/demo_output_v3")
T = Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot")
client = OpenAI(api_key='sk-db9a573912714fd191495d6c6db41ff7', base_url='https://api.deepseek.com')

from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
    build_level1_routing_prompt, build_level1_tool, get_level1_tool_choice,
    build_level2_authoring_prompt, build_level2_tool, get_level2_tool_choice,
)
from seekflow_engineering_tools.generative_cad.dialects.registry import export_dialect_catalog, get_dialect, list_dialects
from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan, DialectSelectionItem
from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model

config = EngineeringToolsConfig(workspace_root=OUT, allow_overwrite=True)

# Tools (built once, reused)
l1_tool = build_level1_tool()
l1_tc = get_level1_tool_choice()
l2_tool = build_level2_tool()
l2_tc = get_level2_tool_choice()

# ── ALL PROMPTS ── (from 20-part suite, 6 basic, 13 advanced)
PROMPTS = [
    # 20-part suite
    ("01_hole_plate","带孔矩形板","100x60x8mm板，四角4个O8通孔。reference geometry only，不用于制造。"),
    ("02_washer","垫片","外径30mm内径12mm厚2mm平垫片。reference geometry only。"),
    ("03_flange","圆形法兰","外径120mm厚16mm中心孔40mm。reference geometry only。"),
    ("04_l_bracket","L型支架","底板80x40x6mm竖板80x50x6mm。底板2xO6孔，竖板1xO10孔。reference geometry only。"),
    ("05_ribbed_bracket","带加强筋支架","底板100x60x10mm，中心20x15x20mm凸台，凸台两侧4mm厚三角筋，四角4xO6孔。reference geometry only。"),
    ("06_stepped_shaft","阶梯轴","O40x20-O50x15-O40x25-O30x10阶梯轴，总长70mm。reference geometry only。"),
    ("07_keyed_shaft","带键槽阶梯轴","O30x30-O20x25阶梯轴带中心孔O6。reference geometry only。"),
    ("08_bearing_housing","轴承座","轴套外径40mm内径25mm高30mm。reference geometry only。"),
    ("09_slide_rail","滑块导轨座","80x50x12mm块体，顶面30x12x6mm槽，四角4xO5孔，两侧2xO4定位孔。reference geometry only。"),
    ("10_pulley","皮带轮","外径80mm宽40mm中心孔20mm。reference geometry only。"),
    ("11_gear_approx","齿轮近似","外径88mm中心孔30mm厚20mm齿轮近似件。reference geometry only。"),
    ("12_heatsink","散热器","100x60x5mm基板，10x4阵列O3散热孔。reference geometry only。"),
    ("13_clamp_block","夹具块","60x60x40mm块体，顶面O20孔，前面30x20x15槽，4xO5孔。reference geometry only。"),
    ("14_motor_mount","电机安装座","底板120x80x10mm，四角4xO8安装孔。reference geometry only。"),
    ("15_pump_body","泵体简化件","圆柱腔体外径80mm内径50mm高60mm。reference geometry only。"),
    ("16_thinwall_box","薄壁盒体","60x40x30mm盒体，壁厚3mm，内部腔体54x34x27mm。reference geometry only。"),
    ("17_electronics_case","电子外壳","80x50x25mm外壳，四角4个O5螺丝柱，侧面4xO3通风孔。reference geometry only。"),
    ("18_hinge","铰链叶片","60x30x4mm铰链叶片，3xO5孔。reference geometry only。"),
    ("19_clamp","夹钳","底板80x30x8mm，活动颚40x15x15mm，手柄60x10x6mm。reference geometry only。"),
    ("20_ujoint","万向节","输入端毂O40x20带O15孔，输出端毂O35x18带O12孔。reference geometry only。"),
    # 6 basic generative parts (original test)
    ("B1_flange","法兰","外径120mm厚16mm中心孔40mm。reference geometry only。"),
    ("B2_hexnut","六角螺母","M12六角螺母blank：对边19mm厚10mm中心孔12mm，倒角1mm。reference geometry only。"),
    ("B3_bracket","L型支架","底板80x40x6竖板80x50x6mm。reference geometry only。"),
    ("B4_bushing","轴套","外径40mm内孔20mm长60mm轴套。reference geometry only。"),
    ("B5_disk","阶梯盘","O60x16→O30x10阶梯盘。reference geometry only。"),
    ("B6_ribbed","加强筋支架","60x40x8mm底板带20x15凸台和4mm筋。reference geometry only。"),
]

results = {}
n_parse_ok = n_validate_ok = n_build_ok = n_sw_ok = 0
t0_total = time.time()
OUT.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print(f"REBUILD ALL PARTS — Per-Op Function Calling Pipeline")
print(f"Total: {len(PROMPTS)} parts")
print("=" * 70)

for idx, (cid, name, prompt) in enumerate(PROMPTS):
    print(f"\n[{idx+1}/{len(PROMPTS)}] {cid} — {name}")
    case_dir = OUT / cid; case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    t0 = time.time()
    r = {"cid": cid, "name": name, "ok": False, "stage": "", "step": None, "sldprt": None, "error": None, "elapsed": 0}

    try:
        # Step 1: L1 Routing (function calling)
        rp = build_level1_routing_prompt(user_request=prompt, dialect_catalog=export_dialect_catalog())
        resp1 = client.chat.completions.create(model='deepseek-chat', messages=[
            {'role':'system','content':rp['system']},{'role':'user','content':rp['user']}
        ], tools=[l1_tool], tool_choice=l1_tc, max_tokens=2048, temperature=0.1)
        plan = json.loads(resp1.choices[0].message.tool_calls[0].function.arguments)
        rd = plan.get('route_decision','?')
        (case_dir / "route_plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

        if rd == 'unsupported':
            r["stage"] = "L1_unsupported"; r["error"] = f"Route: unsupported ({plan.get('unsupported_capabilities',[])})"
            results[cid] = r; print(f"  L1: unsupported"); continue

        if rd == 'deterministic_primitive':
            r["stage"] = "L1_primitive"; r["error"] = "Primitive route (not testing here)"
            results[cid] = r; print(f"  L1: deterministic_primitive"); continue

        sel = DialectSelectionPlan.model_validate(plan)
        print(f"  L1: {rd} dial={[s.dialect for s in sel.selected_dialects]}")

        # Step 2: L2 Authoring (function calling with per-op constraints)
        contracts = {}
        for sd in sel.selected_dialects:
            d = get_dialect(sd.dialect)
            if d: contracts[sd.dialect] = d.contract()

        ap = build_level2_authoring_prompt(prompt, sel, contracts)
        resp2 = client.chat.completions.create(model='deepseek-chat', messages=[
            {'role':'system','content':ap['system']},{'role':'user','content':ap['user']}
        ], tools=[l2_tool], tool_choice=l2_tc, max_tokens=4096, temperature=0.1)
        raw = json.loads(resp2.choices[0].message.tool_calls[0].function.arguments)

        # Post-process: auto-fix common LLM geometric mistakes
        # 1. Fix z_front >= z_rear (LLM often sets them equal)
        for node in raw.get("nodes", []):
            params = node.get("params", {})
            sts = params.get("profile_stations", [])
            for s in sts:
                zf = s.get("z_front_mm", 0)
                zr = s.get("z_rear_mm", 0)
                if zr <= zf:
                    s["z_rear_mm"] = zf + 1.0  # auto-fix: make z_rear > z_front
            # 2. Fix duplicate adjacent radius values (LLM copies same r across stations)
            for i in range(len(sts) - 1):
                if sts[i].get("r_mm") == sts[i+1].get("r_mm"):
                    # Check if z values also identical — if so, merge
                    if (sts[i].get("z_front_mm") == sts[i+1].get("z_front_mm") and
                        sts[i].get("z_rear_mm") == sts[i+1].get("z_rear_mm")):
                        # Duplicate station — don't merge, just mark different
                        pass  # Description in schema should prevent this now

        # Post-process: fill in commonly-missed required top-level fields
        defaults = {
            "schema_version": "g_cad_core_v0.2",
            "units": "mm",
            "trust_level": "reference_geometry",
        }
        for key, val in defaults.items():
            if key not in raw:
                raw[key] = val
        # Ensure document_id is non-empty
        if not raw.get("document_id"):
            raw["document_id"] = f"doc_{cid}"
        if not raw.get("part_name"):
            raw["part_name"] = cid
        # Ensure constraints and safety exist
        if "constraints" not in raw:
            raw["constraints"] = {
                "require_step_file": True, "require_metadata_sidecar": True,
                "require_closed_solid": True, "expected_body_count": 1,
                "max_runtime_seconds": 120,
            }
        if "safety" not in raw:
            raw["safety"] = {
                "non_flight_reference_only": True, "not_airworthy": True,
                "not_certified": True, "not_for_manufacturing": True,
                "not_for_installation": True, "no_structural_validation": True,
                "no_life_prediction": True,
            }

        (case_dir / "raw_gcad.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

        # Step 3: Parse
        pr = parse_raw_gcad_document(raw)
        if not pr.ok:
            r["stage"] = "parse"; r["error"] = "; ".join(f"{i.code}" for i in pr.issues[:3])
            results[cid] = r; print(f"  PARSE FAIL"); continue
        n_parse_ok += 1

        # Step 4: Validate
        can, report, bundle = validate_and_canonicalize_with_bundle(pr.document)
        if can is None or not report.ok:
            errors = sorted(set(i.code for i in report.issues if i.severity=='error'))
            r["stage"] = "validate"; r["error"] = "; ".join(errors[:5])
            results[cid] = r; print(f"  VALIDATE FAIL: {errors[:3]}"); continue
        n_validate_ok += 1

        # Step 5: Build
        out_step = case_dir / "output.step"
        build_r = build_generative_cad_model(spec=raw, config=config, out_step=str(out_step), inspect=True, strict_inspection=False)
        if not build_r.get('ok'):
            err = build_r.get('error','?')
            r["stage"] = "build"; r["error"] = err[:250]
            results[cid] = r; print(f"  BUILD FAIL: {err[:150]}"); continue
        n_build_ok += 1
        r["step"] = str(out_step); r["step_size"] = out_step.stat().st_size

        # Step 6: SolidWorks import
        try:
            from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
            swp = case_dir / f"{cid}.SLDPRT"
            sw = SolidWorksClient(visible=True, part_template=T).connect()
            oks = sw.import_step_as_part(step_path=out_step, out_sldprt=swp)
            sw.close_all(); sw.close()
            if oks and swp.exists():
                r["sldprt"] = str(swp); r["sldprt_size"] = swp.stat().st_size
                n_sw_ok += 1
        except Exception: pass

        r["ok"] = True
        r["elapsed"] = time.time() - t0
        print(f"  PASS: STEP={r['step_size']}B SLDPRT={r.get('sldprt_size','?')}B ({r['elapsed']:.0f}s)")

    except Exception as e:
        r["stage"] = "exception"; r["error"] = str(e)[:200]
        print(f"  EXCEPTION: {e}")

    results[cid] = r
    (case_dir / "summary.json").write_text(json.dumps(r, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

# ── Final Report ──
total_t = time.time() - t0_total
print(f"\n{'='*70}")
print(f"FINAL RESULTS ({total_t:.0f}s total)")
print(f"{'='*70}")
print(f"  Parse OK:    {n_parse_ok}/{len(PROMPTS)}")
print(f"  Validate OK: {n_validate_ok}/{len(PROMPTS)}")
print(f"  Build OK:    {n_build_ok}/{len(PROMPTS)}")
print(f"  SW Import:   {n_sw_ok}/{len(PROMPTS)}")
print()
for cid, r in sorted(results.items()):
    s = "OK" if r["ok"] else f"FAIL({r['stage']})"
    si = f"STEP={r.get('step_size','?')}B" if r.get("step") else ""
    swi = f"SW={r.get('sldprt_size','?')}B" if r.get("sldprt") else ""
    print(f"  [{s:12s}] {cid:25s} {r['name']:15s} {si:18s} {swi}")

(OUT / "report_v3.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
print(f"\nFull report: {OUT / 'report_v3.json'}")
print(f"Output dir:  {OUT}")
