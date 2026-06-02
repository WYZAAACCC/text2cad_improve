import sys; sys.path.insert(0, r"E:/auto_detection_process/integrations/engineering_tools/src")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(
    canonical_json=r"E:/auto_detection_process/demo_output_v5/fix_3/fix_helix/round1/canonical.json",
    validation_seed_json=r"E:/auto_detection_process/demo_output_v5/fix_3/fix_helix/round1/bundle.json",
    out_step=r"E:/auto_detection_process/demo_output_v5/fix_3/fix_helix/round1/output.step",
    metadata_path=r"E:/auto_detection_process/demo_output_v5/fix_3/fix_helix/round1/output.metadata.json")
print("BUILD_OK" if r.ok else f"BUILD_FAILED: {r.error}")
