"""Render the solved stress on the solid it was solved on.

The scattered cloud and the r-z sections are both views *of* the answer; this
is the answer on the part. The volume mesh is turned into its boundary, the
nodal von Mises values are painted on it, and it is lit and photographed from
two angles - the whole solved sector, and the fir-tree rim where the load
enters - because one camera and one colour scale cannot show both the 1483 MPa
at the bore and the 115 MPa on the loaded flanks.

    python render_stress_3d_vtk.py <job-dir> <output.png> [--deformation-scale S]

Rendering happens offscreen: vtkRenderWindow with no interactor, saved to PNG,
so this works with no display attached.
"""
from __future__ import annotations

import argparse
import csv
import math
import pathlib

import vtk

# Turbo, the same map the matplotlib views use, so the two figures agree about
# what a colour means. VTK has no turbo of its own.
TURBO_STOPS = [
    (0.000, (0.18995, 0.07176, 0.23217)),
    (0.125, (0.27660, 0.42149, 0.89180)),
    (0.250, (0.12900, 0.71359, 0.87858)),
    (0.375, (0.22889, 0.88144, 0.64168)),
    (0.500, (0.52295, 0.96606, 0.33916)),
    (0.625, (0.79056, 0.92129, 0.20797)),
    (0.750, (0.96406, 0.73162, 0.15389)),
    (0.875, (0.94659, 0.41303, 0.08154)),
    (1.000, (0.47960, 0.01583, 0.01055)),
]

VTK_QUADRATIC_TETRA = 24


def read_mesh(path: pathlib.Path):
    """Nodes and SOLID187 elements from the deck's mesh file.

    ANSYS writes a ten-node tetrahedron on two lines: `EN` carries the
    element id and the first eight nodes, `EMORE` the last two. Its node order
    is corners then mid-edges in the same sequence VTK's quadratic tetrahedron
    uses, so the list transfers without a permutation - which is worth stating
    because getting it wrong produces a mesh that looks plausible and is not
    the one that was solved.
    """
    nodes: dict[int, tuple[float, float, float]] = {}
    elements: list[list[int]] = []
    pending: list[int] = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            parts = line.strip().split(",")
            if parts[0] == "N" and len(parts) >= 5:
                nodes[int(parts[1])] = (
                    float(parts[2]), float(parts[3]), float(parts[4])
                )
            elif parts[0] == "EN" and len(parts) >= 3:
                pending = [int(v) for v in parts[2:] if v]
            elif parts[0] == "EMORE" and pending:
                pending.extend(int(v) for v in parts[1:] if v)
                if len(pending) == 10:
                    elements.append(pending)
                pending = []
    return nodes, elements


def read_stress(path: pathlib.Path):
    """Nodal von Mises by node id, and the displacement vector beside it."""
    out: dict[int, tuple[float, float, float, float, float]] = {}
    with path.open(newline="", encoding="utf-8", errors="replace") as s:
        for row in csv.DictReader(s):
            try:
                out[int(float(row["nid"]))] = (
                    float(row["s_eqv"]),
                    float(row["ux"]), float(row["uy"]), float(row["uz"]),
                    float(row["u_sum"]) if "u_sum" in row else 0.0,
                )
            except (KeyError, TypeError, ValueError):
                continue
    return out


# Which corners each mid-side node sits between, in the order ANSYS and VTK
# both use: the four corners, then the six mid-edges of (0,1) (1,2) (2,0)
# (0,3) (1,3) (2,3).
MID_EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))


def solved(stress, nid) -> float | None:
    """The solved von Mises at a node, or None where none was stored.

    The deck writes a row for every node, and writes `0` in the rows the
    solver had no value for - SOLID187 keeps its results at the corner nodes
    only. A von Mises of exactly zero is a hydrostatic state, which a stress
    field does not contain, so zero here means "not sampled" and not "no
    stress": on D27 there are 216 117 such rows and `stress_sampling` in the
    metrics reports exactly 216 117 unsampled nodes. Reading them as zeros is
    what draws a dotted picture of a smooth part.
    """
    entry = stress.get(nid)
    if entry is None or entry[0] <= 0.0:
        return None
    return entry[0]


def filled_stress(nodes, elements, stress):
    """A value at every node, interpolating the ones the solver did not store.

    Painting the unsampled nodes zero draws the mesh rather than the field: a
    regular dotting of solved and unsolved nodes that reads as texture on the
    part. What a post-processor does instead, and what is done here, is take a
    mid-side value as the mean of the two corners it lies between.

    The interpolated values are not results and are not presented as any:
    they are what the element's own shape functions imply between the nodes
    that were solved. Every number quoted from this figure is taken from a
    solved node.
    """
    total: dict[int, float] = {}
    count: dict[int, int] = {}
    for element in elements:
        for offset, (a, b) in enumerate(MID_EDGES):
            first, second = solved(stress, element[a]), solved(stress, element[b])
            if first is None or second is None:
                continue
            mid = element[4 + offset]
            total[mid] = total.get(mid, 0.0) + 0.5 * (first + second)
            count[mid] = count.get(mid, 0) + 1

    out: dict[int, float] = {}
    for nid in nodes:
        value = solved(stress, nid)
        if value is not None:
            out[nid] = value
        elif count.get(nid):
            out[nid] = total[nid] / count[nid]
        else:
            out[nid] = 0.0
    return out


def build_grid(nodes, elements, stress):
    values_by_node = filled_stress(nodes, elements, stress)
    points = vtk.vtkPoints()
    points.SetNumberOfPoints(len(nodes))
    order = sorted(nodes)
    index = {nid: i for i, nid in enumerate(order)}
    values = vtk.vtkDoubleArray()
    values.SetName("von Mises [MPa]")
    values.SetNumberOfComponents(1)
    values.SetNumberOfTuples(len(order))
    displacement = vtk.vtkDoubleArray()
    displacement.SetName("displacement [mm]")
    displacement.SetNumberOfComponents(3)

    for nid in order:
        x, y, z = nodes[nid]
        points.SetPoint(index[nid], x, y, z)
        entry = stress.get(nid)
        values.SetValue(index[nid], values_by_node[nid])
        displacement.InsertNextTuple3(
            entry[1] if entry else 0.0,
            entry[2] if entry else 0.0,
            entry[3] if entry else 0.0,
        )

    cells = vtk.vtkCellArray()
    for element in elements:
        cells.InsertNextCell(10)
        for nid in element:
            cells.InsertCellPoint(index.get(nid, 0))

    grid = vtk.vtkUnstructuredGrid()
    grid.SetPoints(points)
    grid.SetCells(VTK_QUADRATIC_TETRA, cells)
    grid.GetPointData().SetScalars(values)
    grid.GetPointData().AddArray(displacement)
    return grid


def turbo(vmin: float, vmax: float, bands: int = 14) -> vtk.vtkLookupTable:
    """A banded turbo table, which is how a stress plot is normally read.

    A continuous map of per-node values draws the mesh rather than the field:
    with 200 000 elements on the visible face, each node is a few pixels wide
    and the element-to-element variation of extrapolated nodal stresses reads
    as a woven texture. Bands are what the eye reads a level off, and they are
    what ANSYS draws by default for the same reason.
    """
    table = vtk.vtkLookupTable()
    table.SetNumberOfTableValues(bands)
    table.SetTableRange(vmin, vmax)
    for index in range(bands):
        position = index / max(bands - 1, 1)
        for stop in range(len(TURBO_STOPS) - 1):
            low, high = TURBO_STOPS[stop], TURBO_STOPS[stop + 1]
            if low[0] <= position <= high[0]:
                span = high[0] - low[0] or 1.0
                weight = (position - low[0]) / span
                rgb = tuple(
                    low[1][c] + weight * (high[1][c] - low[1][c])
                    for c in range(3)
                )
                break
        else:
            rgb = TURBO_STOPS[-1][1]
        table.SetTableValue(index, rgb[0], rgb[1], rgb[2], 1.0)
    table.Build()
    return table


def surface_of(grid, scale: float):
    """The boundary of the volume, optionally drawn at its displaced shape."""
    if scale:
        warp = vtk.vtkWarpVector()
        warp.SetInputData(grid)
        warp.SetInputArrayToProcess(
            0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS,
            "displacement [mm]",
        )
        warp.SetScaleFactor(scale)
        port = warp.GetOutputPort()
    else:
        producer = vtk.vtkTrivialProducer()
        producer.SetOutput(grid)
        port = producer.GetOutputPort()

    surface = vtk.vtkDataSetSurfaceFilter()
    surface.SetInputConnection(port)
    # Each quadratic triangle carries six nodes - three corners and three
    # mid-edges - and colouring per node draws the mid-edge values as dots,
    # which reads as texture on the part rather than as the field. Subdividing
    # into linear triangles keeps the same interpolated field and loses the
    # dotting.
    surface.SetNonlinearSubdivisionLevel(1)
    surface.Update()

    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(surface.GetOutput())
    normals.ConsistencyOn()
    normals.SplittingOff()
    normals.Update()
    return normals.GetOutput()


def add_view(renderer, polydata, vmin, vmax, title):
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(polydata)
    mapper.SetScalarModeToUsePointData()
    mapper.SetLookupTable(turbo(vmin, vmax))
    mapper.SetScalarRange(vmin, vmax)
    mapper.ScalarVisibilityOn()

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetInterpolationToPhong()
    actor.GetProperty().SetSpecular(0.12)
    actor.GetProperty().SetSpecularPower(28)
    renderer.AddActor(actor)

    bar = vtk.vtkScalarBarActor()
    bar.SetLookupTable(mapper.GetLookupTable())
    bar.SetTitle(title)
    bar.SetNumberOfLabels(7)
    bar.SetWidth(0.055)
    bar.SetHeight(0.62)
    bar.GetTitleTextProperty().SetFontSize(15)
    bar.GetLabelTextProperty().SetFontSize(13)
    renderer.AddActor2D(bar)
    return actor


def aim(renderer, camera_position, focal_point):
    camera = renderer.GetActiveCamera()
    camera.SetPosition(*camera_position)
    camera.SetFocalPoint(*focal_point)
    camera.SetViewUp(0.0, 0.0, 1.0)
    camera.ParallelProjectionOn()
    renderer.ResetCamera()
    camera.Zoom(1.25)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    parser.add_argument(
        "--zoom-vmax", type=float, default=800.0,
        help=(
            "top of the colour scale on the rim view. It has to clear the "
            "strongest feature in the rim or it hides it: at 0-220 the "
            "fir-tree root concentration at 774 MPa and the 205 MPa just "
            "outside it are the same saturated red"
        ),
    )
    parser.add_argument(
        "--deformation-scale", type=float, default=0.0,
        help=(
            "multiply the displacements before drawing. 0 draws the "
            "undeformed shape; 1 is the true displaced one, which is the "
            "right choice for comparing with a measurement and the wrong one "
            "for reading a stress field off a geometry you know"
        ),
    )
    args = parser.parse_args()

    job = args.job.resolve()
    solve = job / "solve"
    nodes, elements = read_mesh(job / "mesh" / "mesh.inp")
    stress = read_stress(solve / "nodal_stress_3d.csv")
    grid = build_grid(nodes, elements, stress)
    polydata = surface_of(grid, args.deformation_scale)

    # Quoted from solved nodes only. A peak taken over the rows the solver
    # left empty would be a peak of the mesh.
    values = [v for v in (solved(stress, nid) for nid in nodes) if v]
    values.sort()
    peak = values[-1]
    rim_peak = max(
        (
            v for nid in nodes
            if math.hypot(nodes[nid][0], nodes[nid][1]) >= 270.0
            for v in [solved(stress, nid)] if v
        ),
        default=0.0,
    )

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(3200, 1500)

    centre = (170.0, 55.0, 19.0)
    radius = 900.0
    elevation = math.radians(30.0)
    azimuth = math.radians(18.0)
    direction = (
        math.cos(azimuth) * math.cos(elevation),
        math.sin(azimuth) * math.cos(elevation),
        math.sin(elevation),
    )
    left = vtk.vtkRenderer()
    left.SetViewport(0.0, 0.0, 0.5, 1.0)
    left.SetBackground(1.0, 1.0, 1.0)
    window.AddRenderer(left)
    add_view(left, polydata, 0.0, peak, "von Mises [MPa]  -  full range")
    aim(
        left,
        tuple(centre[i] + radius * direction[i] for i in range(3)),
        centre,
    )

    zoom_centre = (284.0, 92.0, 19.0)
    right = vtk.vtkRenderer()
    right.SetViewport(0.5, 0.0, 1.0, 1.0)
    right.SetBackground(1.0, 1.0, 1.0)
    window.AddRenderer(right)
    add_view(
        right, polydata, 0.0, args.zoom_vmax,
        f"von Mises [MPa]  -  0 to {args.zoom_vmax:.0f}",
    )
    aim(
        right,
        tuple(zoom_centre[i] + 300.0 * direction[i] for i in range(3)),
        zoom_centre,
    )

    window.Render()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(args.output.resolve()))
    window_to_image = vtk.vtkWindowToImageFilter()
    window_to_image.SetInput(window)
    window_to_image.SetScale(1)
    writer.SetInputConnection(window_to_image.GetOutputPort())
    writer.Write()
    print(args.output.resolve())
    print(f"peak {peak:.1f} MPa | fir-tree (r>=270) peak {rim_peak:.1f} MPa | "
          f"{len(nodes)} nodes, {len(elements)} elements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
