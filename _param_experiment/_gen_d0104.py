# -*- coding: utf-8 -*-
"""生成 D01-D04 基础盘（basic 类，无特征）完整数据。"""
import sys, os, json
sys.path.insert(0, r'E:\text_to_cad_improve\auto_detection_process\_param_experiment')
sys.path.insert(0, r'E:\text_to_cad_improve\auto_detection_process\app\text-to-cad\server')
sys.path.insert(0, r'E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src')
os.environ['DEEPSEEK_API_KEY'] = open(r'E:\text_to_cad_improve\auto_detection_process\_archive\apikey.txt').read().strip()
import main, param_templates
from design_families import DESIGN_FAMILIES, build_text


def run_one(fid):
    fam = DESIGN_FAMILIES[fid]
    params = {'category': fam['category'], '_tag': f'verify_{fid}',
              'od_mm': fam['od'], 'bore_mm': fam['bore'], 'thick_mm': fam['thick'],
              'hub_mm': fam['hub'], 'rim_mm': fam['rim'], 'form': fam.get('form', 'standard')}
    # basic 类无 features，但 complex_rim 有 transition（D01-D04 无）
    tid = f'verify_{fid}'
    out_dir = main.OUT_ROOT / tid
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'llm_raw.json').write_text(
        json.dumps(param_templates.build(params), ensure_ascii=False, indent=2), encoding='utf-8')
    os.environ['TEMPLATE_L2'] = '1'
    main._tasks[tid] = {'taskId': tid, 'status': 'pending', 'progress': 0, 'result': None, 'error': None}
    main._run_pipeline(tid, build_text(fam), force_route='generative_cad_ir')
    d = json.loads((out_dir / 'pipeline_log.json').read_text(encoding='utf-8'))
    return fid, d.get('ok'), d.get('error')


if __name__ == '__main__':
    import multiprocessing as mp
    with mp.Pool(processes=4) as pool:
        for fid, ok, err in pool.map(run_one, ['D01', 'D02', 'D03', 'D04']):
            print(f'{fid}:', 'OK' if ok else 'FAIL ' + str(err)[:80], flush=True)
