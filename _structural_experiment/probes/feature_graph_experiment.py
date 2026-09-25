"""Deterministic feature-dependency coverage across the D01-D32 corpus.

This probe never calls a model or a CAD kernel. It reads the generated
documents, builds the production dependency graph, and measures whether the
relations the feedback/revise harness relies on are actually present in every
design family.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

from seekflow_structural.tools import document as document_tools  # noqa: E402

KINDS = (
    "mirror_vertex_pair",
    "fillet_family",
    "pattern_instances",
    "profile_contour",
    "feature_bundle",
)


def _family(path: Path) -> str:
    return path.parent.name


def _measure(document: dict) -> dict:
    graph = document_tools.dependency_graph(document)
    groups = graph.get("joint_edit_groups") or []
    kinds = Counter(str(group.get("kind")) for group in groups)
    required = [group for group in groups if group.get("required")]
    optional = [group for group in groups if not group.get("required")]
    editable = document_tools.editable(document)
    covered = {
        kind: kinds.get(kind, 0)
        for kind in KINDS
    }
    return {
        "node_count": len(graph.get("nodes") or []),
        "edge_count": len(graph.get("edges") or []),
        "parameter_group_count": len(groups),
        "required_group_count": len(required),
        "optional_group_count": len(optional),
        "group_kinds": dict(kinds),
        "coverage": {kind: count > 0 for kind, count in covered.items()},
        "group_counts": covered,
        "editable_count": len(editable),
        "multi_parameter_group_count": sum(
            1 for group in groups if len(group.get("members") or []) > 1
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--document-root",
        type=Path,
        default=REPO / "_param_experiment" / "turbine_disc_dataset_D01-D32" / "data",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "_structural_experiment" / "output" / "feature_graph_metrics.json",
    )
    args = parser.parse_args()
    files = sorted(args.document_root.glob("D*/llm_raw.json"))
    rows = []
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        measured = _measure(document)
        rows.append({"family": _family(path), "path": str(path), **measured})
    covered_families = {
        kind: [row["family"] for row in rows if row["coverage"].get(kind)]
        for kind in KINDS
    }
    missing = {
        kind: [row["family"] for row in rows if not row["coverage"].get(kind)]
        for kind in KINDS
    }
    counts = [row["parameter_group_count"] for row in rows]
    report = {
        "schema_version": "feature_graph_experiment_v1",
        "families": len(rows),
        "coverage": {
            kind: {
                "present_families": len(covered_families[kind]),
                "fraction": round(len(covered_families[kind]) / len(rows), 6) if rows else None,
                "missing_families": missing[kind],
            }
            for kind in KINDS
        },
        "parameter_group_count": {
            "min": min(counts) if counts else None,
            "median": statistics.median(counts) if counts else None,
            "max": max(counts) if counts else None,
        },
        "group_kind_totals": dict(Counter(
            kind
            for row in rows
            for kind, count in row["group_counts"].items()
            for _ in range(count)
        )),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
