
"""Fixed G-CAD runner harness — auto-generated, no LLM CAD code."""
import sys
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files

result = run_canonical_gcad_from_files(
    canonical_json=r"E:/auto_detection_process/demo_output_v4/.generative_cad_graphs/gcad_fe6a54340b1d.json",
    validation_seed_json=r"E:/auto_detection_process/demo_output_v4/.generative_cad_graphs/gcad_fe6a54340b1d.validation.json",
    out_step=r"E:/auto_detection_process/demo_output_v4/14_motor_mount/output.step",
    metadata_path=r"E:/auto_detection_process/demo_output_v4/14_motor_mount/output.metadata.json",
)
if not result.ok:
    print(f"BUILD FAILED: {result.error}", file=sys.stderr)
    sys.exit(1)
print(f"STEP exported: {result.step_path}")
print(f"Metadata written: {result.metadata_path}")
for w in result.warnings:
    print(f"CQ_WARNING: {w}")
