"""Can the sandbox's child process reach the geometry stack?

The whole point of the sandbox is that the agent can write code to answer a
question its fixed tools cannot - and the questions worth asking are about the
part, so the child has to be able to open the bundle.

`ProcessSandbox` runs the child with a *minimal* environment (PATH and HOME
only, plus whatever the caller passes), deliberately, so nothing in the parent
environment leaks in. That is the right default and it is also the thing that
could make the sandbox useless: if the child cannot import the package or reach
OCP, it can only compute on data handed to it.

This measures which of those is true, rather than assuming.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from seekflow.sandbox import ProcessSandbox  # noqa: E402

CHILD = """
import sys
print("python:", sys.executable)
print("sys.path[0:3]:", sys.path[:3])
for name in ("seekflow_structural", "seekflow_engineering_tools"):
    try:
        module = __import__(name)
        print(f"{name}: OK {getattr(module, '__file__', '?')}")
    except Exception as exc:
        print(f"{name}: FAIL {type(exc).__name__}: {exc}")
try:
    from OCP.TopoDS import TopoDS  # noqa: F401
    print("OCP: OK")
except Exception as exc:
    print(f"OCP: FAIL {type(exc).__name__}: {exc}")
print("cwd reachable:", __import__("os").getcwd())
"""


def main() -> int:
    sandbox = ProcessSandbox()
    for label, env in (
        ("minimal env, as ProcessSandbox builds it", None),
        ("with PYTHONPATH pointing at the package src",
         {"PYTHONPATH": str(REPO / "integrations" / "structural" / "src")}),
    ):
        result = sandbox.execute(CHILD, timeout=180, env=env)
        print(f"=== {label} ===")
        print(f"ok={result.ok} elapsed_ms={result.elapsed_ms}")
        print(result.stdout)
        if result.stderr:
            print("stderr:", result.stderr[:600])
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
