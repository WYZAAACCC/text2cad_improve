"""Build a two-revision D19 lineage with a topology-preserving perturbation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STRUCTURAL_ROOT = Path(__file__).resolve().parents[1]
if str(STRUCTURAL_ROOT) not in sys.path:
    sys.path.insert(0, str(STRUCTURAL_ROOT))

from seekflow_engineering_tools.generative_cad.ir.canonical import (  # noqa: E402
    CanonicalGcadDocument,
)
from seekflow_engineering_tools.generative_cad.pipeline.run import (  # noqa: E402
    run_lineage_revisions,
)


def perturb_cutter_width(
    canonical: CanonicalGcadDocument,
    scale_y: float,
) -> CanonicalGcadDocument:
    data = canonical.model_dump(mode="json")
    changed = 0
    for node in data["nodes"]:
        if node["id"] not in {"n_polyline_cutter"}:
            continue
        for key in ("params", "typed_params"):
            points = node.get(key, {}).get("points")
            if points is None:
                continue
            for point in points:
                point["y_mm"] = float(point["y_mm"]) * scale_y
                changed += 1
    if changed == 0:
        raise RuntimeError("cutter polyline points were not found")
    return CanonicalGcadDocument.model_validate(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_bundle", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--lineage", default="D19_cross_revision")
    parser.add_argument("--scale-y", type=float, default=1.02)
    args = parser.parse_args()

    source = args.source_bundle.resolve()
    canonical = CanonicalGcadDocument.model_validate(
        json.loads((source / "canonical_ir.json").read_text(encoding="utf-8"))
    )
    validation_seed = json.loads(
        (source / "validation_seed.json").read_text(encoding="utf-8")
    )
    revised = perturb_cutter_width(canonical, args.scale_y)
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "canonical_rev2.json").write_text(
        json.dumps(revised.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    results = run_lineage_revisions(
        lineage_id=args.lineage,
        output_root=output_root,
        revisions=[
            {
                "canonical": canonical,
                "validation_seed": validation_seed,
            },
            {
                "canonical": revised,
                "validation_seed": validation_seed,
            },
        ],
    )
    summary = {
        "lineage_id": args.lineage,
        "output_root": str(output_root),
        "scale_y": args.scale_y,
        "results": [
            {
                "ok": result.ok,
                "error": result.error,
                "step": str(result.step_path) if result.step_path else None,
                "metadata": str(result.metadata_path)
                if result.metadata_path
                else None,
            }
            for result in results
        ],
    }
    (output_root / "revision_build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not all(result.ok for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
