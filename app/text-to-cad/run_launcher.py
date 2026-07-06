"""
Text-to-CAD Launcher
Usage: python run_launcher.py
"""
import subprocess, webbrowser, time, sys, os, signal
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # app/text-to-cad/
PYTHON = r"E:\auto_detection_process\.conda\python.exe"
NPX = "npx.cmd" if sys.platform == "win32" else "npx"

def main():
    print("Text-to-CAD Launcher\n")

    # Kill old processes
    for port in [8080, 5173]:
        try:
            out = subprocess.check_output(f'netstat -ano | findstr :{port}', shell=True, text=True)
            for line in out.splitlines():
                parts = line.split()
                pid = parts[-1] if parts else ""
                if pid.isdigit():
                    try: subprocess.run(f'taskkill //F //PID {pid}', shell=True, capture_output=True)
                    except: pass
        except: pass
        time.sleep(1)

    # Backend
    print("[1/2] Backend  :8080")
    backend = subprocess.Popen([PYTHON, "-m", "uvicorn", "server.main:app", "--port", "8080"],
                               cwd=str(ROOT))

    # Frontend
    print("[2/2] Frontend :5173")
    frontend = subprocess.Popen([NPX, "vite", "--port", "5173"],
                                cwd=str(ROOT), shell=True)

    time.sleep(4)
    url = "http://localhost:5173"
    print(f"\nOpening {url} ...")
    webbrowser.open(url)

    print("Ctrl+C to stop\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        backend.terminate()
        frontend.terminate()

if __name__ == "__main__":
    main()
