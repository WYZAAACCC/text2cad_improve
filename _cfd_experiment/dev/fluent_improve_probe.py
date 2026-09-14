"""Run Fluent /mesh/repair-improve/improve-quality on an existing mesh.

Development-only probe for understanding whether Fluent's built-in mesh
improver can move a produced tetra mesh over a documented quality threshold.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local"))

from fluent_worker import _run_fluent  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("msh", type=Path)
    p.add_argument("output_dir", type=Path)
    p.add_argument("--passes", type=int, default=5)
    p.add_argument("--cpu", type=int, default=8)
    p.add_argument("--name", default="improve_quality")
    args = p.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    msh = args.msh.resolve()
    lines = ['/file/read-case "' + str(msh) + '"']
    lines.extend(["/mesh/repair-improve/improve-quality"] * args.passes)
    lines.append("/mesh/quality")
    lines.append("/mesh/check")
    lines.append(
        '/file/write-case "' + str(output_dir / (args.name + ".cas.gz")) + '"'
    )
    lines.append("/exit")
    log = _run_fluent(output_dir, args.name, lines, args.cpu)
    text = log.read_text(encoding="utf-8", errors="replace")
    print(text[-8000:])


if __name__ == "__main__":
    main()
