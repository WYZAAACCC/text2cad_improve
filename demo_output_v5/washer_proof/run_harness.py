
import json, sys
from pathlib import Path
sys.path.insert(0, r"E:\auto_detection_process\integrations\engineering_tools\src")

from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files

result = run_canonical_gcad_from_files(
    canonical_json=r"E:/auto_detection_process/demo_output_v5/washer_proof/canonical_gcad.json",
    validation_seed_json=r"E:/auto_detection_process/demo_output_v5/washer_proof/validation_bundle.json",
    out_step=r"E:/auto_detection_process/demo_output_v5/washer_proof/output.step",
    metadata_path=r"E:/auto_detection_process/demo_output_v5/washer_proof/output.metadata.json",
)
if not result.ok:
    print(f"BUILD FAILED: {result.error}", file=sys.stderr)
    sys.exit(1)
print(f"STEP: {result.step_path}")
print(f"Metadata: {result.metadata_path}")
