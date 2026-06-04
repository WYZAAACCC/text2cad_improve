import sys; sys.path.insert(0, r'E:/auto_detection_process/integrations/engineering_tools/src')
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(canonical_json=Path(r'E:/auto_detection_process/demo_output_v5/v6_full35_output/s02_micro_bushing/canonical.json'),validation_seed_json=Path(r'E:/auto_detection_process/demo_output_v5/v6_full35_output/s02_micro_bushing/validation_bundle.json'),out_step=Path(r'E:/auto_detection_process/demo_output_v5/v6_full35_output/s02_micro_bushing/output.step'),metadata_path=Path(r'E:/auto_detection_process/demo_output_v5/v6_full35_output/s02_micro_bushing/output.metadata.json'))
if r.ok: print('BUILD_OK')
else: print(f'BUILD_FAILED: {r.error}')
