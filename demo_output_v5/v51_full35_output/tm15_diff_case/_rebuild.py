import sys; sys.path.insert(0, r"E:/auto_detection_process/integrations/engineering_tools/src")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
val_path = Path(r"E:/auto_detection_process/demo_output_v5/v51_full35_output/tm15_diff_case/validation_bundle.json") if Path(r"E:/auto_detection_process/demo_output_v5/v51_full35_output/tm15_diff_case/validation_bundle.json").exists() else Path(".")
r = run_canonical_gcad_from_files(canonical_json=Path(r"E:/auto_detection_process/demo_output_v5/v51_full35_output/tm15_diff_case/canonical.json"),validation_seed_json=val_path,out_step=Path(r"E:/auto_detection_process/demo_output_v5/v51_full35_output/tm15_diff_case/output_fixed.step"),metadata_path=Path(r"E:/auto_detection_process/demo_output_v5/v51_full35_output/tm15_diff_case/output_fixed.metadata.json"))
if r.ok: print("BUILD_OK")
else: print(f"BUILD_FAILED: {str(r.error)[:300]}")
