import sys; sys.path.insert(0, r"E:/auto_detection_process/integrations/engineering_tools/src")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(
    canonical_json=r"E:/auto_detection_process/demo_output_v5/complex_final/engine_mount/canonical.json",
    validation_seed_json=r"E:/auto_detection_process/demo_output_v5/complex_final/engine_mount/bundle.json",
    out_step=r"E:/auto_detection_process/demo_output_v5/complex_final/engine_mount/output.step",
    metadata_path=r"E:/auto_detection_process/demo_output_v5/complex_final/engine_mount/output.metadata.json")
if r.ok: print("BUILD_OK")
else: print(f"BUILD_FAILED: {r.error}")
