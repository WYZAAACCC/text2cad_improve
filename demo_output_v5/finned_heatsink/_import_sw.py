
import sys; sys.path.insert(0, r"E:\auto_detection_process\integrations\engineering_tools\src")
from pathlib import Path
from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
step = Path(r"E:/auto_detection_process/demo_output_v5/finned_heatsink/output.step")
sldprt = Path(r"E:/auto_detection_process/demo_output_v5/finned_heatsink/output.SLDPRT")
client = SolidWorksClient(visible=False).connect()
ok = client.import_step_as_part(step, sldprt)
client.close()
print(f"SW_OK" if ok and sldprt.exists() else "SW_FAIL")
