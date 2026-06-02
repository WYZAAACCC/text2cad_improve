
import sys
sys.path.insert(0, r"E:\auto_detection_process\integrations\engineering_tools\src")

from pathlib import Path
from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

step = Path(r"E:/auto_detection_process/demo_output_v5/stage2_finned_heatsink/output.step")
sldprt = Path(r"E:/auto_detection_process/demo_output_v5/stage2_finned_heatsink/output.SLDPRT")
template = Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot")
if not template.exists():
    template = None

client = SolidWorksClient(visible=False, part_template=template).connect()
ok = client.import_step_as_part(step, sldprt)
client.close()
if ok and sldprt.exists():
    print(f"SW_OK: {sldprt.stat().st_size} bytes")
else:
    print(f"SW_FAIL: ok={ok}, exists={sldprt.exists()}")
