import sys; sys.path.insert(0, r'E:/auto_detection_process/integrations/engineering_tools/src')
from pathlib import Path
from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad_from_files
can = Path(r'E:/auto_detection_process/demo_output_v5/stress20_output/s15_multi_port_valve_block/canonical.json')
val = Path(r'E:/auto_detection_process/demo_output_v5/stress20_output/s15_multi_port_valve_block/validation_bundle.json')
stp = Path(r'E:/auto_detection_process/demo_output_v5/stress20_output/s15_multi_port_valve_block/output.step')
met = Path(r'E:/auto_detection_process/demo_output_v5/stress20_output/s15_multi_port_valve_block/output.metadata.json')
r = run_canonical_gcad_from_files(canonical_json=can, validation_seed_json=val, out_step=stp, metadata_path=met)
if r.ok:
    print('BUILD_OK')
    for m in (r.operation_metrics or []):
        print('OP:' + str(m.get('node_id','?')) + '/' + str(m.get('op','?')) + ':' + str(m.get('status','?')))
    for d in (r.degraded_features or []):
        print('DEGRADED:' + str(d.get('node_id','?')) + '/' + str(d.get('op','?')) + ':' + str(d.get('reason','?'))[:200])
else:
    print('BUILD_FAILED: ' + str(r.error)[:500])
    for w in (r.warnings or []): print('WARN:' + str(w)[:200])
