"""Phase 0: can provenance separate the two radial bands?

The question that decided whether the provenance route was worth building.

The agent's answer (586 faces) is a strict superset of the verified reference
(6 faces). The extra 472 sit at r 280-300 while the reference sits at
r 211.3-213.8, and no measured geometric property separates them: same surface
type, same edge count, same z, overlapping normal ranges, both perfectly
mirrored about their slot centreline.

Provenance was the one dimension left. This reads the built index and reports
what it found.

Verdict: it separates them, and by source *kind* rather than by which cutter
face - the reference band descends from the disc (`target_face_N/carry`, the
face carried through the cut unchanged) and the outer band from the cutter
(`tool_face_N/modified`, the face the cut produced). Two different origins,
not two members of one family.

Two things to carry forward with that, both recorded below:

  - Coverage is thin. Of the inner band's 114 faces only 6 have any role
    record at all, and those 6 are exactly the reference. Provenance names the
    reference set precisely and does not characterise the band.
  - Reaching it needed the carry recovery, and the recovery needed its
    hardcoded `--previous-feature n_disc_revolve` replaced with the feature
    that actually fed the final cut (`n_bool_groove_0`, 322 faces against the
    revolve's 15). With the hardcoded name the recovery recovered 8 of 18 and
    reported "carry match count 0", which reads as a geometry mismatch rather
    than as looking at the wrong feature.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "_structural_experiment" / "work" / "D27_face_evolution.sqlite"
OUT = Path(__file__).with_name("d27_provenance_separation.json")

FACES = "rev-000001:solid:0:face:{}"
REFERENCE_INDICES = [9, 10, 11, 12, 13, 15]


def face_id(index: int) -> str:
    return FACES.format(index)


def band(connection, lo: float, hi: float) -> list[int]:
    rows = connection.execute(
        """
        SELECT face_index FROM canonical_faces
        WHERE surface_type = 'plane' AND normal_radial <= -0.5
          AND radius_mm BETWEEN ? AND ?
        ORDER BY face_index
        """,
        (lo, hi),
    ).fetchall()
    return [row[0] for row in rows]


def origins(connection, indices: list[int]) -> dict:
    """Every role row that resolves to any of these faces.

    Both resolved and unresolved rows are counted, because "this face has no
    provenance" and "this face's provenance failed to resolve" are different
    findings and the report should not merge them.
    """
    marks = ",".join("?" * len(indices))
    ids = [face_id(i) for i in indices]
    resolved = connection.execute(
        f"""
        SELECT resolved_face_id, source_key, relation_kind FROM face_roles
        WHERE resolution_status = 'resolved' AND resolved_face_id IN ({marks})
        """,
        ids,
    ).fetchall()
    present = connection.execute(
        f"""
        SELECT COUNT(DISTINCT resolved_face_id) FROM face_roles
        WHERE resolved_face_id IN ({marks})
        """,
        ids,
    ).fetchone()[0]

    per_face: dict[str, list] = {}
    sources: Counter = Counter()
    kinds: Counter = Counter()
    for resolved_id, source_key, kind in resolved:
        index = int(str(resolved_id).rsplit(":", 1)[1])
        per_face.setdefault(str(index), []).append(f"{source_key}|{kind}")
        if source_key:
            sources[source_key] += 1
        if kind:
            kinds[kind] += 1
    return {
        "face_count": len(indices),
        "faces_with_any_role_row": present,
        "faces_resolved": len(per_face),
        "sources": dict(sorted(sources.items())),
        "relation_kinds": dict(sorted(kinds.items())),
        "per_face": {k: sorted(v) for k, v in sorted(per_face.items())},
    }


def main() -> int:
    if not DB.exists():
        print(f"index not built: {DB}")
        return 2
    connection = sqlite3.connect(DB)
    try:
        inner = band(connection, 200.0, 235.0)
        outer = band(connection, 270.0, 300.0)
        ref = origins(connection, REFERENCE_INDICES)
        inn = origins(connection, inner)
        out = origins(connection, outer)

        def tool(set_):
            return {s for s in set_ if s.startswith("tool_face_")}

        def target(set_):
            return {s for s in set_ if s.startswith("target_face_")}

        ref_src, inn_src, out_src = (
            set(ref["sources"]), set(inn["sources"]), set(out["sources"])
        )
        overlap = inn_src & out_src
        separates = bool(ref_src) and not overlap

        print(f"reference 6 : {ref['faces_resolved']} resolved, "
              f"kinds={ref['relation_kinds']}")
        for index in REFERENCE_INDICES:
            print(f"    face {index:5d} -> {ref['per_face'].get(str(index), [])}")
        print(f"inner band  : {len(inner)} faces, "
              f"{inn['faces_with_any_role_row']} with any role, "
              f"{inn['faces_resolved']} resolved, kinds={inn['relation_kinds']}")
        print(f"outer band  : {len(outer)} faces, "
              f"{out['faces_with_any_role_row']} with any role, "
              f"{out['faces_resolved']} resolved, kinds={out['relation_kinds']}")
        print()
        print(f"inner sources : {sorted(inn_src)[:8]}")
        print(f"outer sources : {sorted(out_src)[:6]} ... "
              f"({len(out_src)} total)")
        print(f"inner ∩ outer : {sorted(overlap) if overlap else 'EMPTY (disjoint)'}")
        print()
        print(f"inner sources are all target_face_*: "
              f"{inn_src == target(inn_src) and bool(inn_src)}")
        print(f"outer sources are all tool_face_*  : "
              f"{out_src == tool(out_src) and bool(out_src)}")

        verdict = {
            "reference": ref,
            "inner_band": inn,
            "outer_band": out,
            "inner_source_count": len(inn_src),
            "outer_source_count": len(out_src),
            "inner_sources_are_target_carry": inn_src == target(inn_src)
            and bool(inn_src),
            "outer_sources_are_tool_modified": out_src == tool(out_src)
            and bool(out_src),
            "inner_intersects_outer": bool(overlap),
            "separable_by_provenance": separates,
            "verdict": (
                "provenance_separates_the_bands"
                if separates
                else "provenance_does_not_separate_the_bands"
            ),
        }
        OUT.write_text(
            json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print()
        print(f"VERDICT: {verdict['verdict']}")
        print(f"written: {OUT}")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
