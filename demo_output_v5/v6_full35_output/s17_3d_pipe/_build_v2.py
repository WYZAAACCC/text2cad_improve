import sys; sys.path.insert(0, r"E:/auto_detection_process/integrations/engineering_tools/src")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(canonical_json=Path(r"E:/auto_detection_process/demo_output_v5/v6_full35_output/s17_3d_pipe/canonical.json"),validation_seed_json=Path(r"E:/auto_detection_process/demo_output_v5/v6_full35_output/s17_3d_pipe/validation_bundle.json"),out_step=Path(r"E:/auto_detection_process/demo_output_v5/v6_full35_output/s17_3d_pipe/output_v2.step"),metadata_path=Path(r"E:/auto_detection_process/demo_output_v5/v6_full35_output/s17_3d_pipe/output_v2.metadata.json"))
print("BUILD_OK" if r.ok else f"BUILD_FAILED:{r.error}")
