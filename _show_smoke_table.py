"""Print per-task volume/surface errors for a smoke summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                "_main_experiment/output/smoke_light_40/summary.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    print("Task | Level | OK | Vol% | Surf%")
    for r in sorted(data["records"], key=lambda x: x["task"]):
        vol = "" if r.get("vol") is None else f"{r['vol']:.4f}"
        surf = "" if r.get("surf") is None else f"{r['surf']:.4f}"
        print(f"{r['task']} | {r.get('level')} | {r['ok']} | {vol} | {surf}")


if __name__ == "__main__":
    main()
