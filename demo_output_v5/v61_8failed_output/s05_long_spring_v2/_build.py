import sys; sys.path.insert(0, r"E:/integrations/engineering_tools/src")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
r = run_canonical_gcad_from_files(canonical_json=Path(r"v61_8failed_output/s05_long_spring_v2/canonical.json"),validation_seed_json=Path(r"v61_8failed_output/s05_long_spring_v2/validation_bundle.json"),out_step=Path(r"v61_8failed_output/s05_long_spring_v2/output.step"),metadata_path=Path(r"v61_8failed_output/s05_long_spring_v2/output.metadata.json"))
print("BUILD_OK" if r.ok else f"BUILD_FAILED:{r.error}")
