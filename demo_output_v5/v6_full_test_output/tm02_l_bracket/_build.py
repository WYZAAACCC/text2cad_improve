import sys, json; sys.path.insert(0, r'E:/auto_detection_process/integrations/engineering_tools/src')
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(canonical_json=Path(r'E:/auto_detection_process/demo_output_v5/v6_full_test_output/tm02_l_bracket/canonical.json'),validation_seed_json=Path(r'E:/auto_detection_process/demo_output_v5/v6_full_test_output/tm02_l_bracket/validation_bundle.json'),out_step=Path(r'E:/auto_detection_process/demo_output_v5/v6_full_test_output/tm02_l_bracket/output.step'),metadata_path=Path(r'E:/auto_detection_process/demo_output_v5/v6_full_test_output/tm02_l_bracket/output.metadata.json'))
log = {'ok': r.ok, 'warnings': r.warnings, 'degraded': r.degraded_features}
Path(r'E:/auto_detection_process/demo_output_v5/v6_full_test_output/tm02_l_bracket/runtime_log.json').write_text(json.dumps(log, default=str, indent=2), encoding='utf-8')
if r.ok: print('BUILD_OK')
else: print(f'BUILD_FAILED: {r.error}')
