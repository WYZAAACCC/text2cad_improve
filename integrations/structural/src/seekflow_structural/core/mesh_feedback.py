"""Real mesh measurements fed back to the meshing agent.

A refinement plan is a prediction. This module turns it into measurements the
agent cannot get any other way: how many elements it actually produced, how
much of the budget that used, how many badly shaped elements came out, where
the requested sizes actually landed, and - when asked - whether the answer
itself has stopped moving between two mesh levels.

Nothing here is an estimate. Every number comes from running the mesher, and
for the convergence check, from running the solve.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

# The mesher still lives in the application tree, shared with the non-agent
# path. Rather than count directory levels - which silently points at the wrong
# place the moment this file moves, and did - walk up until the mesher is
# actually there.
_MESH_SECTOR_RELATIVE = Path("app/text-to-cad/server/fea3d/mesh_sector.py")


def _find_mesh_sector() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _MESH_SECTOR_RELATIVE
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        f"could not find {_MESH_SECTOR_RELATIVE} in any parent of "
        f"{Path(__file__).resolve()}"
    )


MESH_SECTOR = _find_mesh_sector()


def _find_repo_root() -> Path:
    """The directory holding both trees this module still reaches into.

    Several stages are still driven by the standalone scripts under
    `_structural_experiment/`; they move into this package in a later step.
    Until then the root is found by looking for the trees rather than by
    counting parents, which is what broke when this file moved.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "_structural_experiment").is_dir() and (
            parent / "integrations/engineering_tools/src"
        ).is_dir():
            return parent
    raise RuntimeError(
        f"could not find the repository root above {Path(__file__).resolve()}"
    )


ROOT = _find_repo_root()


def _load_mesh_sector():
    spec = importlib.util.spec_from_file_location("mesh_sector", MESH_SECTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["mesh_sector"] = module
    spec.loader.exec_module(module)
    return module


def build_mesh(config: dict, job_dir: Path) -> dict:
    """Generate the mesh for a config and return its report."""
    mesh_sector = _load_mesh_sector()
    job_dir.mkdir(parents=True, exist_ok=True)
    return mesh_sector.build(config, job_dir)


def measure(config: dict, job_dir: Path, budget: int) -> dict:
    """Mesh a proposal and report what it actually cost.

    This is the feedback the agent plans against: an over-budget or
    poor-quality mesh is a fact about the proposal, not a judgement about it.
    """
    report = build_mesh(config, job_dir)
    quality = report.get("quality") or {}
    elements = report["elements"]
    profile = report.get("size_profile") or []
    requested = (config.get("mesh") or {}).get("refinement") or {}

    # Where the requested sizes actually landed, so the agent can see whether a
    # zone was diluted by a ramp or by the global size bounds.
    achieved = []
    for band in profile:
        achieved.append(
            {
                "radius_min_mm": band["radius_min_mm"],
                "radius_max_mm": band["radius_max_mm"],
                "element_count": band["element_count"],
                "achieved_mean_size_mm": band["mean_size_mm"],
            }
        )

    return {
        "elements": elements,
        "nodes": report["nodes"],
        "element_budget": budget,
        "elements_over_budget_by": max(0, elements - budget),
        "budget_used_fraction": round(elements / budget, 4) if budget else None,
        "quality": {
            "min_sicn": quality.get("min_sicn"),
            "non_positive_jacobian_elements": quality.get(
                "non_positive_jacobian_elements"
            ),
            "elements_below_0p1_sicn": quality.get("elements_below_0p1_sicn"),
            "elements_below_0p3_sicn": quality.get("elements_below_0p3_sicn"),
        },
        "requested_refinement": requested,
        "achieved_size_profile": achieved,
        "periodic_pairs": report.get("periodic_pairs"),
        "mesh_inp": str((job_dir / "mesh.inp").resolve()),
        "mesh_report": str((job_dir / "mesh_report.json").resolve()),
    }


def _key_metrics(manifest: dict) -> dict:
    metrics = manifest["metrics"]
    return {
        "max_von_mises_mpa": metrics["stress"]["max_von_mises_mpa"],
        "max_von_mises_radius_mm": metrics["stress"]["max_radius_mm"],
        "max_load_surface_von_mises_mpa": metrics["stress"][
            "max_load_surface_von_mises_mpa"
        ],
        "max_displacement_mm": metrics["displacement"]["max_mm"],
        "min_safety_factor": metrics["stress"]["min_safety_factor"],
    }


def _solve(config: dict, job_dir: Path, case: dict) -> dict:
    """Run the structural chain on an already-meshed job directory."""
    sys.path.insert(0, str(ROOT / "_structural_experiment"))
    sys.path.insert(0, str(ROOT / "integrations/engineering_tools/src"))

    import subprocess

    selection = job_dir / "selected_face_nodes.json"
    if not selection.is_file():
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "_structural_experiment/map_solid_faces.py"),
                str(Path(case["bundle"]).resolve()),
                str(Path(case["face_intent"]).resolve()),
                str((job_dir / "mesh.inp").resolve()),
                str(selection.resolve()),
            ],
            check=True,
            capture_output=True,
        )

    template = json.loads(Path(case["intent_template"]).read_text(encoding="utf-8"))
    intent = template["final"]["intent"]
    intent["mesh_inp"] = str((job_dir / "mesh.inp").resolve())
    intent["selected_face_nodes"] = str(selection.resolve())
    intent_path = job_dir / "intent.json"
    intent_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest_path = job_dir / "run_manifest.json"
    if manifest_path.is_file():
        manifest_path.unlink()
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "_structural_experiment/run_structural.py"),
            str(intent_path),
            str((job_dir / "mesh.inp").resolve()),
            str(selection.resolve()),
            str(Path(case["mesh_config"]).resolve()),
            str(job_dir.resolve()),
            "--allow-unconfirmed-reference",
            "--memory-mb",
            str(case.get("memory_mb", 6000)),
            "--timeout-s",
            str(case.get("timeout_s", 3600)),
        ],
        check=True,
        capture_output=True,
    )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def convergence_check(
    config: dict, case: dict, base_dir: Path, factor: float = 0.7
) -> dict:
    """Mesh and solve at two levels, then report whether the answer moved.

    Two meshes and two solves is expensive, so the agent is expected to call
    this once, on the plan it intends to submit. The relative change between
    the levels is the only honest evidence that a quoted number is converged.
    """
    coarse_dir = base_dir / "convergence_coarse"
    fine_dir = base_dir / "convergence_fine"

    _write_config(config, coarse_dir)
    coarse = measure(config, coarse_dir, case.get("element_budget", 150000))
    case_coarse = dict(case)
    case_coarse["mesh_config"] = str((coarse_dir / "mesh_config.json").resolve())
    manifest_coarse = _solve(config, coarse_dir, case_coarse)

    fine_config = json.loads(json.dumps(config))
    fine_config["mesh"]["refinement"]["web_size_mm"] *= factor
    for zone in fine_config["mesh"]["refinement"]["zones"]:
        zone["size_mm"] *= factor
        zone["ramp_mm"] *= factor
    _write_config(fine_config, fine_dir)
    fine = measure(fine_config, fine_dir, case.get("element_budget", 150000))
    case_fine = dict(case)
    case_fine["mesh_config"] = str((fine_dir / "mesh_config.json").resolve())
    manifest_fine = _solve(fine_config, fine_dir, case_fine)

    first = _key_metrics(manifest_coarse)
    second = _key_metrics(manifest_fine)

    changes = {}
    converged = {}
    for key, value in first.items():
        if value:
            delta = (second[key] - value) / abs(value) * 100.0
        else:
            delta = 0.0
        changes[key] = round(delta, 4)
        # A quantity that moves less than 2% between a mesh and a 30% finer mesh
        # is treated as settled; the global fields usually land well under 1%
        # while a node-sampled extremum at a stress riser does not.
        converged[key] = abs(delta) <= 2.0

    return {
        "coarse": {"elements": coarse["elements"], "metrics": first},
        "fine": {"elements": fine["elements"], "metrics": second},
        "relative_change_percent": changes,
        "converged_within_2_percent": converged,
        "all_converged": all(converged.values()),
    }


def _write_config(config: dict, job_dir: Path) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "mesh_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
