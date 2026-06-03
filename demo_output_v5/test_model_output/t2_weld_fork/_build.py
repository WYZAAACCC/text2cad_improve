import sys; sys.path.insert(0, r'E:/auto_detection_process/integrations/engineering_tools/src')
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
can = Path(r'E:/auto_detection_process/demo_output_v5/test_model_output/t2_weld_fork/canonical.json')
val = Path(r'E:/auto_detection_process/demo_output_v5/test_model_output/t2_weld_fork/validation_bundle.json')
stp = Path(r'E:/auto_detection_process/demo_output_v5/test_model_output/t2_weld_fork/output.step')
met = Path(r'E:/auto_detection_process/demo_output_v5/test_model_output/t2_weld_fork/output.metadata.json')
r = run_canonical_gcad_from_files(canonical_json=can, validation_seed_json=val, out_step=stp, metadata_path=met)
if r.ok: print('BUILD_OK')
else: print(f'BUILD_FAILED: {r.error}')
