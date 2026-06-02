
import sys; sys.path.insert(0, r"E:\auto_detection_process\integrations\engineering_tools\src")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
result = run_canonical_gcad_from_files(
    canonical_json=r"E:/auto_detection_process/demo_output_v5/complex_flange/canonical_gcad.json",
    validation_seed_json=r"E:/auto_detection_process/demo_output_v5/complex_flange/validation_bundle.json",
    out_step=r"E:/auto_detection_process/demo_output_v5/complex_flange/output.step",
    metadata_path=r"E:/auto_detection_process/demo_output_v5/complex_flange/output.metadata.json",
)
if not result.ok:
    print(f"BUILD_FAILED: {result.error}")
    for w in (result.warnings or []): print(f"WARN: {w}")
    sys.exit(1)
print("BUILD_OK")
