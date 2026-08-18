"""Report the available OCP/OCCT environment matrix."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from run_fixture import run_fixture


ROOT = Path(__file__).resolve().parents[7]
SRC_DIR = ROOT / "integrations" / "engineering_tools" / "src"


def discover_python_envs(root: Path) -> list[Path]:
    """Discover runnable Python interpreters with OCP from the repo."""
    candidates = [root / ".conda" / "python.exe"]
    p8 = root / "_p8_envs"
    if p8.is_dir():
        for env in sorted(p8.iterdir()):
            py = env / "Scripts" / "python.exe"
            if py.is_file():
                candidates.append(py)
    return [p for p in candidates if p.is_file()]


def python_ocp_version(python: Path) -> str | None:
    code = (
        "try:\n"
        " import OCP\n"
        " print(getattr(OCP, '__version__', 'unknown'))\n"
        "except Exception:\n"
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


_PYTHON_SMOKE_TEMPLATE = r"""
import json, os, sys, tempfile
sys.path.insert(0, r"{src}")

result = {{"ocp_version": None, "ok": False, "steps": {{}}, "errors": []}}

def step(name, fn):
    try:
        fn()
        result["steps"][name] = True
    except Exception as exc:
        result["steps"][name] = False
        result["errors"].append("{{}}: {{}}".format(name, exc))

try:
    import OCP
    result["ocp_version"] = getattr(OCP, "__version__", "unknown")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import OcafRepository

    holder = {{}}
    def create_and_write():
        box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), gp_Pnt(20, 20, 20)).Shape()
        holder["repo"] = OcafRepository.create()
        feat = holder["repo"].design_root_label.FindChild(2, True).FindChild(1001, True)
        from OCP.TNaming import TNaming_Builder
        TNaming_Builder(feat).Generated(box)

    step("create_and_write", create_and_write)
    repo = holder.get("repo")
    if repo is not None:
        tmp = tempfile.mkdtemp(prefix="ocp_core_")
        xbf = os.path.join(tmp, "core.xbf")
        step("save", lambda: repo.save_to(xbf))
        repo.close()
        step("reopen", lambda: OcafRepository.open(xbf))
    result["ok"] = all(result["steps"].values())
except Exception as exc:
    result["errors"].append(str(exc))

print(json.dumps(result, ensure_ascii=False))
"""


def python_core_smoke(python: Path, src_dir: Path) -> dict:
    """Run the pure-OCP OCAF core smoke under a target interpreter."""
    code = _PYTHON_SMOKE_TEMPLATE.format(src=str(src_dir))
    try:
        proc = subprocess.run(
            [str(python), "-c", code],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except Exception as exc:
        return {"ok": False, "errors": [f"subprocess failed: {exc}"]}
    raw = proc.stdout.strip()
    if not raw:
        return {
            "ok": False,
            "returncode": proc.returncode,
            "errors": ["no stdout from smoke"],
            "stderr": proc.stderr[-300:],
        }
    try:
        data = json.loads(raw.splitlines()[-1])
        data["returncode"] = proc.returncode
        return data
    except Exception as exc:
        return {
            "ok": False,
            "returncode": proc.returncode,
            "errors": [f"bad JSON: {exc}"],
            "stdout": raw[-300:],
        }


def main() -> None:
    report = {
        "occt_cpp": str(Path(r"D:\anaconda\envs\occt_cpp")),
        "python_envs": [],
        "fixtures": {},
    }

    for python in discover_python_envs(ROOT):
        report["python_envs"].append(
            {
                "path": str(python),
                "ocp_version": python_ocp_version(python),
                "core_smoke": python_core_smoke(python, SRC_DIR),
            }
        )

    for name in (
        "ocaf_smoke", "tnaming_smoke", "edge_lineage", "edge_boolean",
        "full_edge_boolean",
    ):
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
