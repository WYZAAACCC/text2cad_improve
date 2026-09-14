"""Gmsh mesh-variant probe for the D01 outer-domain case.

This is a development-only harness. It uses the same trusted domain
construction code as the local worker, meshes one variant, writes Gmsh/MSH and
UNV artifacts, and prints quality summary plus the centroids of the worst
cells so a quality failure can be investigated instead of tuned blindly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations/cfd/src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local"))

from seekflow_cfd.models import SimulationSpec  # noqa: E402

from fluent_worker import (  # noqa: E402
    FE_EXE,
    FLUENT_EXE,
    _build_fluid_model,
    _run_fluent,
    _run_process,
)


def _flat_tags(groups: Iterable[list[int]]) -> list[int]:
    tags = []
    seen = set()
    for group in groups:
        for tag in group:
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def _mesh_variant(spec_path: Path, input_root: Path, output_dir: Path, args):
    import gmsh

    spec = SimulationSpec.model_validate(
        json.loads(spec_path.read_text(encoding="utf-8"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    gmsh.initialize()
    try:
        domain = _build_fluid_model(spec, str(input_root))
        volume_tags = [tag for _, tag in domain.volume_tags]
        gmsh.model.addPhysicalGroup(3, volume_tags, tag=-1, name="fluid")
        for b in spec.boundary_specs:
            gmsh.model.addPhysicalGroup(
                2, domain.tags_by_key[b.surface.key], tag=-1, name=b.name
            )
        if args.distance_field:
            distance = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(
                distance,
                "FacesList",
                _flat_tags(
                    domain.tags_by_key[r.surface.key]
                    for r in spec.mesh_strategy.refinements
                ),
            )
            threshold = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(threshold, "InField", distance)
            gmsh.model.mesh.field.setNumber(
                threshold, "SizeMin", args.size_min
            )
            gmsh.model.mesh.field.setNumber(
                threshold, "SizeMax", args.size_max
            )
            gmsh.model.mesh.field.setNumber(
                threshold, "DistMin", args.dist_min
            )
            gmsh.model.mesh.field.setNumber(
                threshold, "DistMax", args.dist_max
            )
            gmsh.model.mesh.field.setAsBackgroundMesh(threshold)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        else:
            for refinement in spec.mesh_strategy.refinements:
                tags = domain.tags_by_key[refinement.surface.key]
                gmsh.model.mesh.setSize(
                    [(2, tag) for tag in tags], refinement.size_m
                )

        gmsh.option.setNumber("Mesh.Algorithm3D", args.algorithm3d)
        gmsh.option.setNumber("Mesh.MeshSizeMax", spec.mesh_strategy.global_size_m)
        gmsh.option.setNumber(
            "Mesh.MeshSizeMin",
            min(
                spec.mesh_strategy.global_size_m,
                max(1e-5, spec.mesh_strategy.global_size_m * 0.2),
            ),
        )
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", args.curvature)
        gmsh.option.setNumber("Mesh.Optimize", int(args.optimize))
        gmsh.option.setNumber("Mesh.OptimizeNetgen", int(args.optimize_netgen))
        if args.optimize3d != 0:
            gmsh.option.setNumber("Mesh.Optimize3D", 1)
        gmsh.option.setNumber("Mesh.Smoothing", args.smoothing)
        gmsh.model.mesh.generate(3)

        # Gmsh quality metrics are reported before export so conversion issues
        # stay distinguishable from generated-element issues.
        type4_tags, type4_nodes = gmsh.model.mesh.getElementsByType(4)
        quality = gmsh.model.mesh.getElementQualities(type4_tags, "minSICN")
        order = sorted(range(len(quality)), key=lambda i: quality[i])[:args.worst]
        nodes = gmsh.model.mesh.getNodes()
        coords = nodes[1]
        conn = list(type4_nodes)
        n_per_elem = 4
        centroids = []
        for idx in order:
            verts = [conn[idx * n_per_elem + k] - 1 for k in range(n_per_elem)]
            cx = sum(coords[3 * v] for v in verts) / n_per_elem
            cy = sum(coords[3 * v + 1] for v in verts) / n_per_elem
            cz = sum(coords[3 * v + 2] for v in verts) / n_per_elem
            centroids.append([cx, cy, cz])
        stats = {
            "spec_hash": spec.spec_hash,
            "tetra_count": len(type4_tags),
            "min_gmsh_minSICN": min(quality),
            "mean_gmsh_minSICN": sum(quality) / len(quality),
            "worst_centroid_m": centroids,
            "algorithm3d": args.algorithm3d,
            "smoothing": args.smoothing,
            "optimize": bool(args.optimize),
            "optimize_netgen": bool(args.optimize_netgen),
            "optimize3d": bool(args.optimize3d),
            "curvature": args.curvature,
        }
        (output_dir / "gmsh_quality.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.write(str(output_dir / "fluid_domain.gmsh.msh"))
        gmsh.write(str(output_dir / "fluid_domain.unv"))
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    finally:
        gmsh.finalize()

    if args.fluent_check:
        _run_process(
            output_dir,
            "fe2ram.out",
            [
                str(FE_EXE),
                "-d3",
                "-tIDEAS",
                "-zGROUP",
                "-oRAMPANT",
                str(output_dir / "fluid_domain.unv"),
                str(output_dir / "fluid_domain.fluent.msh"),
            ],
        )
        log = _run_fluent(
            output_dir,
            "fluent_check",
            [
                '/file/read-case "'
                + str(output_dir / "fluid_domain.fluent.msh")
                + '"',
                "/mesh/quality",
                "/mesh/check",
                "/exit",
            ],
            8,
        )
        text = log.read_text(encoding="utf-8", errors="replace")
        print(text[-5000:])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("spec", type=Path)
    p.add_argument("input_root", type=Path)
    p.add_argument("output_dir", type=Path)
    p.add_argument("--algorithm3d", type=int, default=4)
    p.add_argument("--curvature", type=int, default=10)
    p.add_argument("--smoothing", type=int, default=0)
    p.add_argument("--optimize", type=int, default=1)
    p.add_argument("--optimize-netgen", type=int, default=1)
    p.add_argument("--optimize3d", type=int, default=0)
    p.add_argument("--worst", type=int, default=10)
    p.add_argument("--fluent-check", action="store_true")
    p.add_argument("--distance-field", action="store_true")
    p.add_argument("--size-min", type=float, default=0.005)
    p.add_argument("--size-max", type=float, default=0.06)
    p.add_argument("--dist-min", type=float, default=0.001)
    p.add_argument("--dist-max", type=float, default=0.2)
    args = p.parse_args()
    _mesh_variant(
        args.spec.resolve(),
        args.input_root.resolve(),
        args.output_dir.resolve(),
        args,
    )


if __name__ == "__main__":
    main()
