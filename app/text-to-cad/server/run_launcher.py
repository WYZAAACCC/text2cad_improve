"""
Text-to-CAD Launcher — starts backend, frontend, and opens browser.
Usage: python server/run_launcher.py
"""
import subprocess, webbrowser, time, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = r"E:\auto_detection_process\.conda\python.exe"

def main():
    print("=" * 50)
    print("  Text-to-CAD Launcher")
    print("=" * 50)

    # 1. Backend (FastAPI)
    print("\n[1/3] Starting backend (port 8080)...")
    backend = subprocess.Popen(
        [PYTHON, "-m", "uvicorn", "server.main:app", "--port", "8080", "--reload"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    # 2. Frontend (Vite)
    print("[2/3] Starting frontend (port 5173)...")
    # Find Node.js
    node_dir = None
    for p in os.environ.get("PATH", "").split(os.pathsep):
        np = Path(p) / "node.exe"
        if np.exists():
            node_dir = p
            break
    # Fallback: use npx.cmd on Windows, npx otherwise
    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
    frontend = subprocess.Popen(
        [npx_cmd, "vite", "--port", "5173"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        shell=(sys.platform == "win32"),
    )

    # 3. Wait for both, then open browser
    print("[3/3] Waiting for servers...")
    time.sleep(4)

    url = "http://localhost:5173"
    print(f"\n  Opening {url}")
    webbrowser.open(url)

    print("\n  Backend : http://localhost:8080")
    print("  Frontend: http://localhost:5173")
    print("  Press Ctrl+C to stop both servers.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        backend.terminate()
        frontend.terminate()
        sys.exit(0)


if __name__ == "__main__":
    main()
