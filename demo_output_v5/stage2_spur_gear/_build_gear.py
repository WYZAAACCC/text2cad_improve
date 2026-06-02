
import sys, json
sys.path.insert(0, r"E:\auto_detection_process\integrations\engineering_tools\src")

from pathlib import Path
from seekflow_engineering_tools.config import EngineeringToolsConfig
from seekflow_engineering_tools.ir.cad import CADPartSpec
from seekflow_engineering_tools.cadquery_backend.builder import build_cadquery_from_cad_ir

spec_json = json.loads(Path(r"E:/auto_detection_process/demo_output_v5/stage2_spur_gear/cad_part_spec.json").read_text())
spec = CADPartSpec.model_validate(spec_json)
config = EngineeringToolsConfig(workspace_root=Path(r"E:/auto_detection_process/demo_output_v5/stage2_spur_gear"), allow_overwrite=True)
result = build_cadquery_from_cad_ir(spec, config, Path(r"E:/auto_detection_process/demo_output_v5/stage2_spur_gear/output.step"))
print(f"BUILD_OK: {result.get('ok')}")
if not result.get('ok'):
    print(f"ERROR: {result.get('error')}")
