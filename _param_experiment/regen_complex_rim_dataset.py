"""Regenerate D29-D32 complex rim dataset artifacts with the fixed transition.

The script reuses the existing template pipeline and writes the resulting
artifacts directly into turbine_disc_dataset_D01-D32/data/<family>.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_SERVER = _ROOT / "app" / "text-to-cad" / "server"
_SRC = _ROOT / "integrations" / "engineering_tools" / "src"
for path in (_HERE, _SERVER, _SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

_DATASET_ROOT = _HERE / "turbine_disc_dataset_D01-D32" / "data"
_FAMILIES = ("D29", "D30", "D31", "D32")


def _copy_artifacts(out_dir: Path, dst_dir: Path) -> list[str]:
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in sorted(out_dir.iterdir()):
        if not src.is_file():
            continue
        shutil.copy2(src, dst_dir / src.name)
        copied.append(src.name)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--families", default=",".join(_FAMILIES))
    args = parser.parse_args()
    import main
    import param_templates
    from design_families import DESIGN_FAMILIES, build_text
    from agentic_golden import family_params

    old_out_root = main.OUT_ROOT
    temp_root = Path(tempfile.mkdtemp(prefix="d2932_regen_"))
    main.OUT_ROOT = temp_root
    os.environ["TEMPLATE_L2"] = "1"

    try:
        for fid in tuple(f.strip() for f in args.families.split(",") if f.strip()):
            fam = DESIGN_FAMILIES[fid]
            params = family_params(fid)
            task_id = f"regen_{fid}"
            out_dir = temp_root / task_id
            out_dir.mkdir(parents=True, exist_ok=True)

            raw = param_templates.build(params)
            (out_dir / "llm_raw.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            main._tasks[task_id] = {
                "taskId": task_id,
                "status": "pending",
                "progress": 0,
                "result": None,
                "error": None,
            }
            main._run_pipeline(
                task_id,
                build_text(fam),
                force_route="generative_cad_ir",
            )
            status = main._tasks[task_id].get("status", "?")
            if status != "completed":
                error = main._tasks[task_id].get("error")
                print(f"[{fid}] FAILED status={status} error={error}")
                continue

            dst = _DATASET_ROOT / fid
            copied = _copy_artifacts(out_dir, dst)
            (dst / "family_ref.json").write_text(
                json.dumps({"family_id": fid, "category": fam["category"],
                            "split": fam.get("split"), "zone": "feasible"},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            copied.append("family_ref.json")
            print(f"[{fid}] OK artifacts={len(copied)}")
    finally:
        main.OUT_ROOT = old_out_root

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
