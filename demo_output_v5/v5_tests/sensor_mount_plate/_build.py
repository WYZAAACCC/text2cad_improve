import sys; sys.path.insert(0, r"E:/auto_detection_process/integrations/engineering_tools/src")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(
    canonical_json=r"E:/auto_detection_process/demo_output_v5/v5_tests/sensor_mount_plate/canonical.json",
    validation_seed_json=r"E:/auto_detection_process/demo_output_v5/v5_tests/sensor_mount_plate/validation_bundle.json",
    out_step=r"E:/auto_detection_process/demo_output_v5/v5_tests/sensor_mount_plate/output.step",
    metadata_path=r"E:/auto_detection_process/demo_output_v5/v5_tests/sensor_mount_plate/output.metadata.json")
if r.ok:
    print("BUILD_OK")
else:
    print(f"BUILD_FAILED: {r.error}")
    for w in (r.warnings or []): print(f"WARN: {w[:300]}")
    for d in (r.degraded_features or []): print(f"DEGRADED: {d}")
