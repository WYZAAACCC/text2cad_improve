#!/usr/bin/env python3
"""Quick LLM->STEP test for all 26 parts (no SolidWorks import)."""
import json, time
from pathlib import Path
from openai import OpenAI
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.generative_cad.skills.orchestrator import *
from seekflow_engineering_tools.generative_cad.dialects.registry import export_dialect_catalog, get_dialect
from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan
from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model

OUT = Path('E:/auto_detection_process/demo_output_v3')
config = EngineeringToolsConfig(workspace_root=OUT, allow_overwrite=True)
client = OpenAI(api_key='sk-db9a573912714fd191495d6c6db41ff7', base_url='https://api.deepseek.com')

l1_tool = build_level1_tool(); l1_tc = get_level1_tool_choice()
l2_tool = build_level2_tool(); l2_tc = get_level2_tool_choice()

PROMPTS = [
    ('01_hole_plate','带孔矩形板','100x60x8mm板四角4个O8通孔。reference geometry only。'),
    ('02_washer','垫片','外径30mm内径12mm厚2mm平垫片。reference geometry only。'),
    ('03_flange','法兰','外径120mm厚16mm中心孔40mm。reference geometry only。'),
    ('04_l_bracket','L型支架','底板80x40x6mm竖板80x50x6mm。底板2xO6孔竖板O10孔。reference geometry only。'),
    ('05_ribbed_bracket','加强筋支架','底板100x60x10mm中心20x15x20凸台凸台两侧4mm筋四角4xO6孔。reference geometry only。'),
    ('06_stepped_shaft','阶梯轴','O40x20-O50x15-O40x25-O30x10阶梯轴总长70mm。reference geometry only。'),
    ('07_keyed_shaft','键槽轴','O30x30-O20x25阶梯轴中心孔O6。reference geometry only。'),
    ('08_bearing_housing','轴承座','轴套外径40mm内径25mm高30mm。reference geometry only。'),
    ('09_slide_rail','滑块座','80x50x12mm块体顶面30x12x6槽四角4xO5孔两侧2xO4定位孔。reference geometry only。'),
    ('10_pulley','皮带轮','外径80mm宽40mm中心孔20mm。reference geometry only。'),
    ('11_gear_approx','齿轮近似','外径88mm中心孔30mm厚20mm。reference geometry only。'),
    ('12_heatsink','散热器','100x60x5mm基板10x4阵列O3散热孔。reference geometry only。'),
    ('13_clamp_block','夹具块','60x60x40mm块体顶面O20孔前面30x20x15槽4xO5孔。reference geometry only。'),
    ('14_motor_mount','电机座','底板120x80x10mm四角4xO8安装孔。reference geometry only。'),
    ('15_pump_body','泵体','圆柱腔体外径80mm内径50mm高60mm。reference geometry only。'),
    ('16_thinwall_box','薄壁盒','60x40x30mm盒体壁厚3mm内部腔体54x34x27mm。reference geometry only。'),
    ('17_electronics_case','电子外壳','80x50x25mm外壳四角4个O5螺丝柱侧面4xO3通风孔。reference geometry only。'),
    ('18_hinge','铰链叶片','60x30x4mm铰链叶片3xO5孔。reference geometry only。'),
    ('19_clamp','夹钳','底板80x30x8mm活动颚40x15x15mm手柄60x10x6mm。reference geometry only。'),
    ('20_ujoint','万向节','输入毂O40x20带O15孔输出毂O35x18带O12孔。reference geometry only。'),
    ('B1_flange','法兰B','外径120mm厚16mm中心孔40mm。reference geometry only。'),
    ('B2_hexnut','六角螺母','M12六角螺母对边19mm厚10mm中心孔12mm倒角1mm。reference geometry only。'),
    ('B3_bracket','L支架B','底板80x40x6竖板80x50x6mm。reference geometry only。'),
    ('B4_bushing','轴套','外径40mm内孔20mm长60mm。reference geometry only。'),
    ('B5_disk','阶梯盘','O60x16-O30x10阶梯盘。reference geometry only。'),
    ('B6_ribbed','筋支架','60x40x8mm底板20x15凸台4mm筋。reference geometry only。'),
]

results = {}
print(f'Testing {len(PROMPTS)} parts...')
t0 = time.time()

for idx, (cid, name, prompt) in enumerate(PROMPTS):
    t1 = time.time()
    case_dir = OUT / cid; case_dir.mkdir(parents=True, exist_ok=True)
    r = {'cid': cid, 'name': name, 'ok': False, 'stage': '', 'error': None}

    try:
        rp = build_level1_routing_prompt(user_request=prompt, dialect_catalog=export_dialect_catalog())
        resp1 = client.chat.completions.create(model='deepseek-chat', messages=[
            {'role':'system','content':rp['system']},{'role':'user','content':rp['user']}
        ], tools=[l1_tool], tool_choice=l1_tc, max_tokens=2048, temperature=0.1)
        plan = json.loads(resp1.choices[0].message.tool_calls[0].function.arguments)
        rd = plan.get('route_decision','?')
        if rd != 'generative_cad_ir':
            r['stage'] = f'L1_{rd}'; results[cid] = r; print(f'  [{idx+1:2d}] {cid}: {rd}'); continue

        sel = DialectSelectionPlan.model_validate(plan)
        contracts = {}
        for sd in sel.selected_dialects:
            d = get_dialect(sd.dialect)
            if d: contracts[sd.dialect] = d.contract()
        ap = build_level2_authoring_prompt(prompt, sel, contracts)
        resp2 = client.chat.completions.create(model='deepseek-chat', messages=[
            {'role':'system','content':ap['system']},{'role':'user','content':ap['user']}
        ], tools=[l2_tool], tool_choice=l2_tc, max_tokens=4096, temperature=0.1)
        raw = json.loads(resp2.choices[0].message.tool_calls[0].function.arguments)

        for k, v in {'schema_version':'g_cad_core_v0.2','units':'mm','trust_level':'reference_geometry'}.items():
            if k not in raw: raw[k] = v
        if not raw.get('document_id'): raw['document_id'] = f'doc_{cid}'
        if not raw.get('part_name'): raw['part_name'] = cid
        for n in raw.get('nodes',[]):
            for s in n.get('params',{}).get('profile_stations',[]):
                if s.get('z_rear_mm',0) <= s.get('z_front_mm',0):
                    s['z_rear_mm'] = s['z_front_mm'] + 1.0

        pr = parse_raw_gcad_document(raw)
        if not pr.ok:
            r['stage'] = 'parse'; r['error'] = '; '.join(i.code for i in pr.issues[:3])
            results[cid] = r; print(f'  [{idx+1:2d}] {cid}: PARSE FAIL'); continue

        can, report, bundle = validate_and_canonicalize_with_bundle(pr.document)
        if can is None or not report.ok:
            errors = sorted(set(i.code for i in report.issues if i.severity=='error'))
            r['stage'] = 'validate'; r['error'] = '; '.join(errors[:4])
            results[cid] = r; print(f'  [{idx+1:2d}] {cid}: VAL FAIL ({errors[:2]})'); continue

        out_step = case_dir / 'output.step'
        br = build_generative_cad_model(spec=raw, config=config, out_step=str(out_step), inspect=True, strict_inspection=False)
        if not br.get('ok'):
            r['stage'] = 'build'; r['error'] = br.get('error','?')[:200]
            results[cid] = r; print(f'  [{idx+1:2d}] {cid}: BUILD FAIL'); continue

        r['ok'] = True; r['step_size'] = out_step.stat().st_size
        print(f'  [{idx+1:2d}] {cid}: PASS STEP={r["step_size"]}B ({time.time()-t1:.0f}s)')

    except Exception as e:
        r['stage'] = 'exception'; r['error'] = str(e)[:150]
        results[cid] = r; print(f'  [{idx+1:2d}] {cid}: EXC {e}')

    results[cid] = r

n = sum(1 for r in results.values() if r['ok'])
print(f'\n{"="*60}')
print(f'RESULTS: {n}/{len(PROMPTS)} OK ({time.time()-t0:.0f}s)')
print(f'{"="*60}')
for cid, r in sorted(results.items()):
    s = 'OK' if r['ok'] else f'FAIL({r["stage"]})'
    print(f'  [{s:15s}] {cid:25s} {r.get("error","")[:80]}')
(OUT / 'report_v3_final.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'\nReport: {OUT / "report_v3_final.json"}')
