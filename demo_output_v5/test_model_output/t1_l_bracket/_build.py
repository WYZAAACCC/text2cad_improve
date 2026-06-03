import sys; sys.path.insert(0, r"E:/auto_detection_process/integrations/engineering_tools/src")
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
can_path = Path(r"E:/auto_detection_process/demo_output_v5/test_model_output/t1_l_bracket/canonical.json")
val_path = Path(r"E:/auto_detection_process/demo_output_v5/test_model_output/t1_l_bracket/validation_bundle.json")
step_path = Path(r"E:/auto_detection_process/demo_output_v5/test_model_output/t1_l_bracket/output.step")
meta_path = Path(r"E:/auto_detection_process/demo_output_v5/test_model_output/t1_l_bracket/output.metadata.json")
r = run_canonical_gcad_from_files(
    canonical_json=can_path, validation_seed_json=val_path,
    out_step=step_path, metadata_path=meta_path)
if r.ok:
    print("BUILD_OK")
    for m in (r.operation_metrics or []):
        print(f"OP:{m.get('node_id','?')}/{m.get('op','?')}:{m.get('status','?')}")
    for d in (r.degraded_features or []):
        print(f"DEGRADED:{d.get('node_id','?')}/{d.get('op','?')}:{d.get('reason','?')}")
else:
    print(f"BUILD_FAILED: {r.error}")
    for w in (r.warnings or []):
        print(f"WARN: {w[:200]}")
