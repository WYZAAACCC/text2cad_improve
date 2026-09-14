"""Where the load actually lands, measured from the selected faces.

The meshing agent needs to know the radius of the load-bearing surface so it
can spend elements there. That radius used to be handed in from the command
line, and nothing tied it to the faces the selection stage actually chose - so
on D27 the mesh was refined at r=288 while the load sat at r=212, leaving the
loaded region on 9 mm elements.

The selection stage already knows the answer. This reads it back out of the
selection rather than asking anyone to restate it, which is the only way the
two can stay in step when either one changes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/engineering_tools/src"))
sys.path.insert(0, str(ROOT / "_structural_experiment"))


def measure(bundle: Path, face_intent: Path) -> dict:
    """Radial extent of the selected load faces, read from the real geometry."""
    from seekflow_structural.core.pattern_solids import (  # noqa: E402
        _load_solids,
        _open,
        _solid_facts,
    )
    from seekflow_structural.core.role_facts import face_facts  # noqa: E402

    intent = json.loads(Path(face_intent).read_text(encoding="utf-8"))
    final = intent["final"]
    if not final.get("accepted"):
        raise ValueError(f"{face_intent} does not contain an accepted selection")

    session = _open(Path(bundle).resolve())
    try:
        solids = _load_solids(session, final["feature"])
        solid = solids[final["solid_index"]]
        _, faces = _solid_facts(solid)
        indices = final["selected_face_indices"]
        if not indices:
            raise ValueError("selection is empty")
        rows = [face_facts(faces[index]) for index in indices]
    finally:
        try:
            session.close()
        except Exception:
            pass

    radii = [row["centroid_cyl_mm_deg"][0] for row in rows]
    areas = [row["area_mm2"] for row in rows]
    # Area-weighted, because the mean radius of a set of faces is the radius at
    # which the load actually acts; an unweighted mean over faces of different
    # sizes points somewhere the traction is not.
    total_area = sum(areas)
    weighted = (
        sum(radius * area for radius, area in zip(radii, areas)) / total_area
        if total_area
        else sum(radii) / len(radii)
    )
    return {
        "feature": final["feature"],
        "solid_index": final["solid_index"],
        "face_count": len(rows),
        "load_radius_mm": round(weighted, 4),
        "radius_min_mm": round(min(radii), 4),
        "radius_max_mm": round(max(radii), 4),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("face_intent", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = measure(args.bundle, args.face_intent)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
