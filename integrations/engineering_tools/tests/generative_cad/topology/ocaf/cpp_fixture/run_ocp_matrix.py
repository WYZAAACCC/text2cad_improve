"""Report the available OCP/OCCT environment matrix."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from run_fixture import run_fixture


ROOT = Path(__file__).resolve().parents[7]
PYTHON_CANDIDATES = [
    ROOT / ".conda" / "python.exe",
    Path(r"D:\anaconda\envs\occt_cpp\python.exe"),
]


def python_ocp_version(python: Path) -> str | None:
    code = (
        "import sys;"
        "sys.path.insert(0, r'E:\\text_to_cad_improve\\auto_detection_process\\integrations\\engineering_tools\\src');"
        "try:\n"
        " import OCP\n"
        " print(getattr(OCP, '__version__', 'unknown'))\n"
        "except Exception as e:\n"
        " print('NO_OCP')"
    )
    try:
        proc = subprocess.run(
            [str(python), "-c", code],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None
    except Exception:
        return None


def main() -> None:
    report = {
        "occt_cpp": str(Path(r"D:\anaconda\envs\occt_cpp")),
        "python_envs": [],
        "fixtures": {},
    }

    for python in PYTHON_CANDIDATES:
        if python.exists():
            report["python_envs"].append(
                {
                    "path": str(python),
                    "ocp_version": python_ocp_version(python),
                }
            )

    for name in ("ocaf_smoke", "tnaming_smoke", "edge_lineage", "edge_boolean"):
        try:
            proc = run_fixture(name)
            report["fixtures"][name] = {
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        except Exception as exc:
            report["fixtures"][name] = {"error": str(exc)}

    out = Path(__file__).with_name("ocp_matrix_report.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
