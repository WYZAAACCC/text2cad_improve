import sys; sys.path.insert(0, r"E:/auto_detection_process/integrations/engineering_tools/src")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(
    canonical_json=r"E:/auto_detection_process/demo_output_v5/spur_gear/canonical_gcad.json",
    validation_seed_json=r"E:/auto_detection_process/demo_output_v5/spur_gear/validation_bundle.json",
    out_step=r"E:/auto_detection_process/demo_output_v5/spur_gear/output.step",
    metadata_path=r"E:/auto_detection_process/demo_output_v5/spur_gear/output.metadata.json")
if not r.ok: print(f"BUILD_FAILED: {r.error}"); import sys; sys.exit(1)
print("BUILD_OK")