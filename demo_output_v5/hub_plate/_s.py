import sys; sys.path.insert(0, r"E:/auto_detection_process/integrations/engineering_tools/src")
from pathlib import Path
from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
c = SolidWorksClient(visible=False).connect()
ok = c.import_step_as_part(Path(r"E:/auto_detection_process/demo_output_v5/hub_plate/output.step"), Path(r"E:/auto_detection_process/demo_output_v5/hub_plate/output.SLDPRT"))
c.close()
print("SW_OK" if ok else "SW_FAIL")