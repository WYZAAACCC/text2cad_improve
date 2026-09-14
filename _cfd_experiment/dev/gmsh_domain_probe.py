"""Minimal probe: import a generated STEP and mesh an outer fluid volume.

This is a development probe only. It does not yet produce CFD typed evidence.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import gmsh


def main() -> int:
    step = Path(
        r"E:\text_to_cad_improve\auto_detection_process"
        r"\_cfd_experiment\input\lineage\D01\model.step"
    )
    out_msh = Path(__file__).resolve().parent / "D01_outer.msh"
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.model.occ.synchronize()
        solids = gmsh.model.occ.importShapes(str(step), highestDimOnly=True)
        print("imported", solids)
        tool_vols = [(d, t) for d, t in solids if d == 3]
        if not tool_vols:
            print("no 3d volume imported")
            return 2
        outer = gmsh.model.occ.addCylinder(
            0, 0, -1500, 0, 0, 3000, 1500, tag=100
        )
        cut, mapping = gmsh.model.occ.cut(
            [(3, outer)], tool_vols, removeObject=False, removeTool=True
        )
        print("cut", cut)
        gmsh.model.occ.synchronize()
        vols = gmsh.model.getEntities(3)
        print("fluid volumes", vols)
        gmsh.option.setNumber("Mesh.MeshSizeMax", 100.0)
        gmsh.option.setNumber("Mesh.MeshSizeMin", 20.0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
        start = time.perf_counter()
        gmsh.model.mesh.generate(3)
        print("mesh seconds", round(time.perf_counter() - start, 1))
        etypes, etags, nodes = gmsh.model.mesh.getElements(3)
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        cell_count = sum(len(t) for t in etags)
        print("nodes", len(node_tags), "cells", cell_count)
        gmsh.write(str(out_msh))
        print("wrote", out_msh)
        return 0
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    raise SystemExit(main())
