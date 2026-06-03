"""Batch SolidWorks import for all successfully built STEP files in v51_full35_output."""
import subprocess, time
from pathlib import Path

CONDA = r"E:\auto_detection_process\.conda\python.exe"
OUT = Path(r"E:\auto_detection_process\demo_output_v5\v51_full35_output")

# Find all STEP files
cases = []
for cdir in sorted(OUT.iterdir()):
    if not cdir.is_dir():
        continue
    step = cdir / "output.step"
    sldprt = cdir / "output.SLDPRT"
    if step.exists() and step.stat().st_size > 0:
        cases.append((cdir.name, step, sldprt))

print(f"Found {len(cases)} STEP files to import\n")

ok_count = 0
for i, (name, step, sldprt) in enumerate(cases):
    bscript = f'''import sys
sys.path.insert(0, r"E:\\auto_detection_process\\integrations\\engineering_tools\\src")
from pathlib import Path
from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient

TEMPLATE = Path(r"C:\\ProgramData\\SOLIDWORKS\\SOLIDWORKS 2025\\templates\\gb_part.prtdot")
step_path = Path(r"{step.as_posix()}")
sldprt_path = Path(r"{sldprt.as_posix()}")

try:
    client = SolidWorksClient(visible=False, part_template=TEMPLATE)
    client.connect()
    ok = client.import_step_as_part(step_path, sldprt_path)
    client.close()
    if ok and sldprt_path.exists():
        print(f"OK: {{sldprt_path.stat().st_size}} bytes")
    else:
        print("FAIL: import_step returned False or file missing")
except Exception as e:
    print(f"ERROR: {{str(e)[:200]}}")
'''
    bp = OUT / f"_sw_import_{name}.py"
    bp.write_text(bscript, encoding="utf-8")

    print(f"[{i+1:02d}/{len(cases)}] {name:30s} ... ", end="", flush=True)
    try:
        r = subprocess.run([CONDA, str(bp)], capture_output=True, text=True, timeout=60, cwd=str(OUT))
        output = r.stdout.strip()
        if "OK:" in output:
            sz = output.split("OK:")[1].strip().split()[0]
            print(f"SW={int(sz)//1024}KB")
            ok_count += 1
        else:
            print(f"FAIL: {output[:80]}")
            # Mark for retry
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
    except Exception as e:
        print(f"ERR: {e}")

    # Clean up temp script
    bp.unlink(missing_ok=True)
    time.sleep(1)  # Small delay between SW calls

print(f"\n=== {ok_count}/{len(cases)} SolidWorks imports successful ===")
