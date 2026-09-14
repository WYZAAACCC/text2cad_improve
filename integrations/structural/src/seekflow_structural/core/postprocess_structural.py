"""Post-process the isolated structural solve without a geometry template."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from seekflow_structural.core.structural_intent_models import StructuralIntent
from seekflow_structural.core.temperature_field import build_temperature_field, summary_block


def _read_csv(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            try:
                if int(float(row["sel"].strip())) != 1:
                    continue
                parsed = {key: float(value.strip()) for key, value in row.items()}
                parsed["nid"] = int(parsed["nid"])
                parsed["r"] = math.hypot(parsed["x"], parsed["y"])
                parsed["u_sum"] = math.sqrt(
                    parsed["ux"] ** 2
                    + parsed["uy"] ** 2
                    + parsed["uz"] ** 2
                )
                rows.append(parsed)
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def _interp_yield(temperature_c: float, intent: StructuralIntent) -> float:
    if intent.material is None:
        raise ValueError("material intent is required")
    points = sorted(
        (
            point.temperature_c,
            point.yield_mpa,
        )
        for point in intent.material.points
    )
    if temperature_c <= points[0][0]:
        return points[0][1]
    if temperature_c >= points[-1][0]:
        return points[-1][1]
    for index in range(len(points) - 1):
        low_t, low_y = points[index]
        high_t, high_y = points[index + 1]
        if low_t <= temperature_c <= high_t:
            fraction = (temperature_c - low_t) / (high_t - low_t)
            return low_y + fraction * (high_y - low_y)
    return points[-1][1]


def _read_mesh_coordinates(path: Path) -> dict[int, tuple[float, float, float]]:
    """Node coordinates as the deck saw them.

    The results CSV carries the same nodes, but rounded, and for a sampled
    field the rounding is enough to change the answer. The mesh is the
    authority on where a node is.
    """
    if not path.is_file():
        return {}
    coordinates: dict[int, tuple[float, float, float]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("N,"):
            continue
        parts = line.strip().split(",")
        if len(parts) != 5:
            continue
        try:
            coordinates[int(parts[1])] = (
                float(parts[2]), float(parts[3]), float(parts[4])
            )
        except ValueError:
            continue
    return coordinates


def _read_node_temperature(path: Path) -> dict[int, float]:
    """The per-node values the deck actually emitted."""
    if not path.is_file():
        return {}
    values: dict[int, float] = {}
    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        for row in csv.DictReader(stream):
            try:
                values[int(float(row["nid"]))] = float(row["temperature_c"])
            except (KeyError, TypeError, ValueError):
                continue
    return values


def _node_temperatures(
    nodes: list[dict],
    intent: StructuralIntent,
    job_dir: Path,
) -> tuple[dict[int, float], dict]:
    """Temperature at every result node, and how the two sources compare.

    The deck's own table is authoritative, because it is what the solver was
    given; the safety factor has to be computed against that and not against a
    fresh evaluation that might disagree. But a fresh evaluation is exactly
    what makes the disagreement visible, so it is done as well and the largest
    difference is reported.

    Both evaluations are done at the coordinates in `mesh.inp`, not at the
    coordinates in the results CSV. The CSV rounds to five decimals, which is
    enough to move a node across a cell boundary in a point-cloud field - the
    comparison would then disagree for a reason that has nothing to do with
    the field. Reading the mesh puts both sides on the same numbers, so any
    difference that remains is a real one.
    """
    field = build_temperature_field(
        intent.temperature, intent.rotation, source_root=job_dir
    )
    mesh_nodes = _read_mesh_coordinates(job_dir / "mesh.inp")
    points = [
        (
            node["nid"],
            mesh_nodes.get(
                node["nid"], (node["x"], node["y"], node["z"])
            ),
        )
        for node in nodes
    ]
    reevaluated, coverage = field.evaluate(points)

    deck_table = _read_node_temperature(job_dir / "node_temperature.csv")
    provenance: dict = {"field": summary_block(field, coverage)}
    if not deck_table:
        provenance.update(
            {
                "source": "reevaluated",
                "compared_node_count": 0,
                "max_abs_delta_c": None,
                "note": (
                    "node_temperature.csv was not found, so the temperature "
                    "used here was recomputed and never checked against the "
                    "one the solver ran with"
                ),
            }
        )
        return reevaluated, provenance

    missing = [nid for nid in reevaluated if nid not in deck_table]
    if missing:
        raise RuntimeError(
            f"node_temperature.csv has no value for {len(missing)} result "
            f"node(s), first: {missing[:5]}. The deck and the results are from "
            "different meshes, or the table was truncated."
        )
    deltas = [abs(deck_table[nid] - reevaluated[nid]) for nid in reevaluated]
    worst = max(deltas) if deltas else 0.0
    provenance.update(
        {
            "source": "deck_table",
            "compared_node_count": len(deltas),
            "max_abs_delta_c": round(worst, 9),
            # A measurement, not a gate: the reader decides what a given
            # disagreement means for this field.
            "agree_within_0p01_c": worst <= 0.01,
        }
    )
    return {nid: deck_table[nid] for nid in reevaluated}, provenance


def _summarise_emission(load_audit: dict) -> dict:
    """How the load was applied, without the per-element detail.

    The audit keeps every loaded element face so the emission can be checked
    against the deck; a metrics file wants the summary, not eight hundred rows.
    """
    emission = load_audit.get("emission")
    if not emission:
        return {
            "mechanism": "nodal_force",
            "distribution": load_audit.get("distribution"),
        }
    return {
        key: value
        for key, value in emission.items()
        if key != "element_faces"
    }


def _load_selected_nodes(selection_path: Path) -> set[int]:
    payload = json.loads(selection_path.read_text(encoding="utf-8"))
    return {int(value) for value in payload.get("union_node_ids", [])}


def postprocess(
    intent: StructuralIntent,
    job_dir: Path,
    selected_face_nodes: Path,
    load_audit_path: Path,
) -> dict:
    nodes = _read_csv(job_dir / "nodal_stress_3d.csv")
    if not nodes:
        raise RuntimeError("ANSYS result CSV contains no valid nodes")
    selected_nodes = _load_selected_nodes(selected_face_nodes)
    load_audit = json.loads(load_audit_path.read_text(encoding="utf-8"))

    temperatures, temperature_provenance = _node_temperatures(
        nodes, intent, job_dir
    )
    for node in nodes:
        node["temperature_c"] = temperatures[node["nid"]]
        node["yield_mpa"] = _interp_yield(node["temperature_c"], intent)
        node["safety_factor"] = (
            node["yield_mpa"] / node["s_eqv"]
            if node["s_eqv"] > 1e-12
            else float("inf")
        )

    stress_nodes = [node for node in nodes if node["s_eqv"] > 0]
    if not stress_nodes:
        raise RuntimeError("ANSYS result contains no defined nodal stresses")
    max_displacement = max(nodes, key=lambda row: row["u_sum"])
    max_stress = max(stress_nodes, key=lambda row: row["s_eqv"])
    min_sf = min(stress_nodes, key=lambda row: row["safety_factor"])
    load_nodes = [
        node
        for node in stress_nodes
        if node["nid"] in selected_nodes
    ]
    if not load_nodes:
        raise RuntimeError("no Agent-selected load-surface nodes in results")
    max_load_stress = max(load_nodes, key=lambda row: row["s_eqv"])

    radius_min = min(node["r"] for node in nodes)
    radius_max = max(node["r"] for node in nodes)
    band_count = 4
    bands = []
    for index in range(band_count):
        low = radius_min + (radius_max - radius_min) * index / band_count
        high = radius_min + (radius_max - radius_min) * (index + 1) / band_count
        members = [
            node
            for node in stress_nodes
            if low <= node["r"] <= high
            or (index == band_count - 1 and math.isclose(node["r"], high))
        ]
        bands.append(
            {
                "band": f"R{index + 1}",
                "radius_min_mm": low,
                "radius_max_mm": high,
                "node_count": len(members),
                "max_von_mises_mpa": (
                    round(max(node["s_eqv"] for node in members), 6)
                    if members
                    else None
                ),
                "min_safety_factor": (
                    round(min(node["safety_factor"] for node in members), 6)
                    if members
                    else None
                ),
            }
        )

    # Axial symmetry audit. The deck applies D,ALL,UZ,0 on the z=0 plane, but
    # ANSYS drops that constraint on any node that is a slave in the CPCYC
    # cyclic coupling and logs one warning per node. It still holds because the
    # matching master node on the other sector face carries the constraint --
    # but that is an emergent property of the master/slave pairing, not
    # something the deck guarantees. Verify it every run instead of assuming.
    axial_tol_mm = 1e-4
    symmetry_nodes = [node for node in nodes if abs(node["z"]) <= 1e-6]
    if not symmetry_nodes:
        raise RuntimeError(
            "result contains no z=0 nodes; axial symmetry cannot be verified"
        )
    max_axial_drift = max(abs(node["uz"]) for node in symmetry_nodes)
    if max_axial_drift > axial_tol_mm:
        raise RuntimeError(
            "axial symmetry violated: max |UZ| on z=0 is "
            f"{max_axial_drift:.6g} mm (tolerance {axial_tol_mm} mm). ANSYS "
            "removes D,ALL,UZ,0 from CPCYC slave nodes; check that the cyclic "
            "coupling still carries the constraint."
        )

    summary_path = job_dir / "result_summary.txt"
    ansys_summary = (
        summary_path.read_text(encoding="utf-8", errors="replace")
        if summary_path.is_file()
        else ""
    )
    metrics = {
        "schema_version": "structural_metrics_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": intent.case_id,
        "status": intent.status,
        "node_count": len(nodes),
        "stress_result_node_count": len(stress_nodes),
        "selected_load_mesh_node_count": len(selected_nodes),
        "selected_load_stress_node_count": len(load_nodes),
        "rotation_rpm": intent.rotation.rpm,
        "temperature_c": {
            "min": round(min(node["temperature_c"] for node in nodes), 6),
            "max": round(max(node["temperature_c"] for node in nodes), 6),
        },
        # Where the temperature came from, and how far a second, independent
        # evaluation of the same field disagreed with it. The safety factor is
        # computed against the deck's values; this is what says whether that
        # choice matters.
        "temperature_provenance": temperature_provenance,
        # ANSYS writes results at corner nodes only for SOLID187 - mid-side
        # values are interpolated in POST1 and cannot be retrieved. Every
        # stress figure below is therefore a corner-node quantity, which is
        # worth stating because a load applied to a quadratic face lands on
        # the mid-side nodes and is invisible here.
        "stress_sampling": {
            "sampled": "corner nodes only",
            "stress_node_count": len(stress_nodes),
            "mesh_node_count": len(nodes),
            "unsampled_node_count": len(nodes) - len(stress_nodes),
            "limitation": (
                "SOLID187 results are stored at corner nodes only; mid-side "
                "stress is not retrievable from the result file"
            ),
        },
        "displacement": {
            "max_mm": round(max_displacement["u_sum"], 8),
            "node": max_displacement["nid"],
            "radius_mm": round(max_displacement["r"], 6),
            "z_mm": round(max_displacement["z"], 6),
        },
        "axial_symmetry": {
            "node_count": len(symmetry_nodes),
            "max_abs_uz_mm": round(max_axial_drift, 10),
            "tolerance_mm": axial_tol_mm,
        },
        "stress": {
            "max_von_mises_mpa": round(max_stress["s_eqv"], 6),
            "max_node": max_stress["nid"],
            "max_radius_mm": round(max_stress["r"], 6),
            "max_z_mm": round(max_stress["z"], 6),
            "max_load_surface_von_mises_mpa": round(
                max_load_stress["s_eqv"], 6
            ),
            "max_load_surface_node": max_load_stress["nid"],
            "min_safety_factor": round(min_sf["safety_factor"], 6),
            "min_safety_factor_node": min_sf["nid"],
            "min_safety_factor_radius_mm": round(min_sf["r"], 6),
        },
        "radial_bands": bands,
        "load_audit": {
            "target_force_n_per_slot": load_audit[
                "target_force_n_per_slot"
            ],
            "applied_resultant_n": load_audit["applied_resultant_n"],
            "resultant_relative_error": load_audit[
                "resultant_relative_error"
            ],
            "applied_twist_moment_about_axis_nmm": load_audit[
                "applied_twist_moment_about_axis_nmm"
            ],
            # How the load reached the material, and - on the pressure path -
            # how much of the selected CAD faces the mesh actually covers. The
            # resultant above is an identity when a pressure is used, so the
            # area accounting is what carries the diagnostic weight.
            "emission": _summarise_emission(load_audit),
            "limits": load_audit.get("limits", []),
        },
        "ansys_summary": ansys_summary,
        "scientific_status": (
            "synthetic_or_unconfirmed_pipeline_validation"
            if intent.status != "ready"
            else "confirmed_case"
        ),
    }
    (job_dir / "structural_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report_lines = [
        "# Structural FEA Result",
        "",
        f"- Case: `{intent.case_id}`",
        f"- Scientific status: `{metrics['scientific_status']}`",
        f"- Nodes: `{metrics['node_count']}`",
        f"- Max displacement: `{metrics['displacement']['max_mm']}` mm",
        f"- Max von Mises: `{metrics['stress']['max_von_mises_mpa']}` MPa",
        "- Max load-surface von Mises: "
        f"`{metrics['stress']['max_load_surface_von_mises_mpa']}` MPa",
        f"- Minimum safety factor: `{metrics['stress']['min_safety_factor']}`",
        f"- Applied resultant: `{load_audit['applied_resultant_n']}` N",
        "- Resultant relative error: "
        f"`{load_audit['resultant_relative_error']}`",
        "- Applied twist moment about axis: "
        f"`{load_audit['applied_twist_moment_about_axis_nmm']}` N*mm",
        f"- Temperature field: `{temperature_provenance['field']['kind']}`",
        "- Temperature source for the safety factor: "
        f"`{temperature_provenance['source']}` (re-evaluation differs by at "
        f"most `{temperature_provenance['max_abs_delta_c']}` C over "
        f"`{temperature_provenance['compared_node_count']}` nodes)",
        f"- Stress sampled at: `{metrics['stress_sampling']['sampled']}` "
        f"(`{metrics['stress_sampling']['stress_node_count']}` of "
        f"`{metrics['stress_sampling']['mesh_node_count']}` nodes)",
        "",
    ]
    for note in temperature_provenance["field"].get("limits", []):
        report_lines.append(f"- Temperature field limit: {note}")
    coverage = temperature_provenance["field"].get("coverage", {})
    if coverage.get("outside_support_count"):
        report_lines.append(
            "- Temperature field had no support at "
            f"`{coverage['outside_support_count']}` nodes "
            f"(`{coverage['outside_fraction']}` of the mesh went to the "
            f"`{coverage['policy']}` policy, nearest sample up to "
            f"`{coverage['nearest_sample_distance_max_mm']}` mm away)"
        )
    report_lines += [
        f"- Stress sampling limit: {metrics['stress_sampling']['limitation']}",
        "",
        "This result is not a certified design analysis. Use it only under the "
        "scientific status and source manifest recorded in the intent.",
    ]
    (job_dir / "structural_report.md").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("intent", type=Path)
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("selected_face_nodes", type=Path)
    parser.add_argument("load_audit", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.intent.read_text(encoding="utf-8"))
    intent = StructuralIntent.model_validate(payload["final"]["intent"])
    metrics = postprocess(
        intent,
        args.job_dir.resolve(),
        args.selected_face_nodes.resolve(),
        args.load_audit.resolve(),
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
