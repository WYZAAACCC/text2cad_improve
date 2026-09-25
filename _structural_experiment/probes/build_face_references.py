"""Build deterministic face-set references from the measured load family.

This is a benchmark-oracle probe, not a replacement for the face-finding
agent. It uses the same `flank_surface_normal` measurement gate the agent
receives, records the measured strong family, and writes the result in the
existing face-intent shape so a frozen sweep can be scored exactly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

from seekflow_structural.agents import facefind  # noqa: E402
from seekflow_structural.tools import geometry  # noqa: E402

# These two families already have manually verified frozen references. They
# must not be replaced by the provisional one-period fallback.
VERIFIED = {
    "D19": (
        REPO / "_structural_experiment" / "output" / "D19_final_face_intent_v3.json",
        {"theta_low_deg": 3.0, "theta_high_deg": 9.0},
    ),
    "D27": (
        REPO / "_structural_experiment" / "input" / "D27_face_submission_correct24.json",
        {"theta_low_deg": 9.0, "theta_high_deg": 27.0},
    ),
}


def _document(bundle: Path, family: str) -> dict:
    candidates = [
        REPO / "_param_experiment" / "turbine_disc_dataset_D01-D32"
        / "data" / family / "llm_raw.json",
        bundle / "llm_raw.json",
        bundle / "canonical_ir.json",
    ]
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"no document JSON for {family}")


def _feature_and_sector(document: dict) -> tuple[str, int, dict]:
    nodes = document.get("nodes") or []
    cutters = [
        str(node.get("id"))
        for node in nodes
        if node.get("op") == "boolean_cut"
        and any(
            "cutter" in str(entry.get("node") or "").lower()
            or "slot" in str(entry.get("node") or "").lower()
            for entry in node.get("inputs") or []
        )
    ]
    feature = cutters[-1] if cutters else ""
    if not feature:
        revolves = [str(n.get("id")) for n in nodes if n.get("op") == "revolve_profile"]
        if not revolves:
            raise ValueError("document has no boolean cut or revolve feature")
        feature = revolves[-1]
    patterns = []
    for node in nodes:
        if node.get("op") != "circular_pattern_component":
            continue
        count = (node.get("params") or {}).get("count")
        if isinstance(count, (int, float)) and count > 1:
            patterns.append(int(count))
    if not patterns:
        raise ValueError("document has no circular pattern count")
    count = patterns[-1]
    sector = {"theta_low_deg": 0.0, "theta_high_deg": 360.0 / count}
    return feature, 0, sector


def _candidate_indices(rows: list[dict], sector: dict) -> list[int]:
    """The same measurable candidate family the face-finding gate receives."""
    low = float(sector["theta_low_deg"])
    high = float(sector["theta_high_deg"])
    while high <= low:
        high += 360.0
    out = []
    for index, row in enumerate(rows):
        if str(row.get("surface_type") or "") != "plane":
            continue
        theta = float((row.get("centroid_cyl_mm_deg") or [0.0, 0.0, 0.0])[1])
        while theta < low:
            theta += 360.0
        if theta > high:
            continue
        radial = (row.get("normal_cylindrical") or {}).get("radial")
        if radial is None or -float(radial) < 0.2:
            # A face with a nearly tangential normal is not a bearing flank;
            # the production gate measures a gap before it uses this fallback,
            # so the fallback must not turn numerical noise into a face.
            continue
        out.append(index)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--lineage-root", type=Path,
        default=REPO / "_cfd_experiment" / "input" / "lineage",
    )
    parser.add_argument("--families", nargs="*", default=[])
    parser.add_argument(
        "--output-root", type=Path,
        default=REPO / "_structural_experiment" / "input" / "face_refs_multi",
    )
    args = parser.parse_args()
    families = args.families or sorted(
        path.name for path in args.lineage_root.iterdir()
        if path.is_dir() and path.name.startswith("D") and path.name[1:].isdigit()
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    failed = []
    for family in families:
        bundle = args.lineage_root / family
        try:
            if family in VERIFIED:
                reference, sector = VERIFIED[family]
                payload = json.loads(reference.read_text(encoding="utf-8"))
                final = payload.get("final") or payload
                payload = {
                    "final": {
                        "accepted": True,
                        "feature": final.get("feature"),
                        "solid_index": int(final.get("solid_index") or 0),
                        "selected_face_indices": [
                            int(value) for value in final.get("selected_face_indices") or []
                        ],
                    },
                    "reference_kind": "verified",
                    "family": family,
                    "feature": final.get("feature"),
                    "solid_index": int(final.get("solid_index") or 0),
                    "sector": sector,
                }
                (args.output_root / f"{family}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"{family}: {len(payload['final']['selected_face_indices'])} verified faces")
                continue
            document = _document(bundle, family)
            feature, solid_index, sector = _feature_and_sector(document)
            session = geometry.open_bundle(bundle)
            try:
                rows = geometry.face_rows(session, feature, solid_index)
            finally:
                close = getattr(session, "close", None)
                if close is not None:
                    close()
            state = facefind.FaceFinderState(
                session=None, bundle=bundle, sector=sector,
                require_planar=True,
                load_direction_rule="flank_surface_normal",
            )
            report = facefind._alignment_family_report(rows, [], state)
            strong = ((report.get("strong_family") or {}).get("face_indices") or [])
            used_fallback = not bool(strong)
            if not strong:
                # D19 is the measured counterexample: its valid eight-face
                # family has a small radial gap and the production gate
                # correctly declines to call the separation significant. The
                # benchmark still needs a frozen oracle for that case, so it
                # records the same planar, outward-opposing candidates the gate
                # measured rather than inventing a threshold.
                strong = _candidate_indices(rows, sector)
            if len(strong) < 2:
                failed.append({"family": family, "reason": report.get("separation")})
                continue
            payload = {
                "final": {
                    "accepted": True,
                    "feature": feature,
                    "solid_index": solid_index,
                    "selected_face_indices": strong,
                    "selection_method": (
                        "measured_candidate_fallback"
                        if used_fallback else "measured_strong_load_family"
                    ),
                    "criterion": {"intent": "deterministic benchmark oracle"},
                },
                "reference_kind": (
                    "measured_candidate_fallback"
                    if used_fallback else "measured_strong_load_family"
                ),
                "family": family,
                "feature": feature,
                "solid_index": solid_index,
                "sector": sector,
                "separation": report.get("separation"),
            }
            (args.output_root / f"{family}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"{family}: {len(strong)} faces from {feature}")
        except Exception as exc:  # noqa: BLE001
            failed.append({"family": family, "reason": f"{type(exc).__name__}: {exc}"})
            print(f"{family}: FAILED {type(exc).__name__}: {exc}")
    (args.output_root / "_failed.json").write_text(
        json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
