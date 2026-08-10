"""交互 3D STEP 查看器（VTK 版）——逐个核实采集的 step 文件。

- 左键拖动 = 旋转，滚轮 = 缩放，中键拖动 = 平移，右键 = 缩放
- 左侧树：族（D01-D32）→ 参数组合；点击组合 → 右侧加载 output.step
- 底部状态栏显示当前 step 路径 + 参数摘要

用法:
  python view_steps_vtk.py [collection根目录 | 单个step]
  默认 collection = _param_experiment/output/collection

说明：VTK 渲染用三角形网格近似（cadquery tessellate 0.4mm），对核实形状/尺寸/特征足够。
     如需 OCC 原生 NURBS 渲染，需修复 PyQt5 后使用 view_steps.py。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cadquery as cq
import vtk

_HERE = Path(__file__).resolve().parent
DEFAULT_COLLECTION = _HERE / "output" / "collection"


def step_to_polydata(step_path: Path, tol: float = 0.4) -> vtk.vtkPolyData:
    """STEP → vtkPolyData（tessellate 三角网格 + 法线计算）。"""
    obj = cq.importers.importStep(str(step_path))
    shape = obj.val()
    verts, faces = shape.tessellate(tol)
    points = vtk.vtkPoints()
    points.SetNumberOfPoints(len(verts))
    for i, v in enumerate(verts):
        points.SetPoint(i, float(v.x), float(v.y), float(v.z))
    polys = vtk.vtkCellArray()
    for tri in faces:
        polys.InsertNextCell(3)
        for idx in tri:
            polys.InsertCellPoint(int(idx))
    pd = vtk.vtkPolyData()
    pd.SetPoints(points)
    pd.SetPolys(polys)
    # 法线（光照）
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(pd)
    normals.ComputePointNormalsOn()
    normals.ConsistencyOn()
    normals.Update()
    return normals.GetOutput()


def make_actor(pd: vtk.vtkPolyData) -> vtk.vtkActor:
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(pd)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(0.55, 0.68, 0.85)
    actor.GetProperty().SetSpecular(0.2)
    actor.GetProperty().SetSpecularPower(30)
    return actor


class StepViewer:
    """VTK 独立窗口交互查看器（左键旋转 / 滚轮缩放 / 中键平移 / 右键缩放）。

    GUI 模式键盘导航：n=下一个  p=上一个  q=退出  r=复位视角
    """

    def __init__(self, base_dir: Path, steps: list | None = None):
        self.ren = vtk.vtkRenderer()
        self.ren.SetBackground(0.94, 0.95, 0.98)
        self.rw = vtk.vtkRenderWindow()
        self.rw.AddRenderer(self.ren)
        self.rw.SetSize(900, 680)
        self.iren = vtk.vtkRenderWindowInteractor()
        self.iren.SetRenderWindow(self.rw)
        style = vtk.vtkInteractorStyleTrackballCamera()
        self.iren.SetInteractorStyle(style)
        self._current_actor = None
        self.base_dir = Path(base_dir)
        self.steps = steps or []
        self._idx = 0
        self.iren.AddObserver("KeyPressEvent", self._on_key)

    def show(self, step_path: Path):
        try:
            pd = step_to_polydata(step_path)
            actor = make_actor(pd)
        except Exception as exc:  # noqa: BLE001
            print(f"[加载失败] {step_path}: {str(exc)[:120]}")
            return
        if self._current_actor is not None:
            self.ren.RemoveActor(self._current_actor)
        self.ren.AddActor(actor)
        self._current_actor = actor
        self.ren.ResetCamera()
        self.rw.Render()
        self.rw.SetWindowName(f"{step_path.parent.parent.name}/{step_path.parent.name}")
        print(f"[{self._idx + 1}/{len(self.steps) or '?'}] {step_path.parent.name}  "
              f"{_params_summary(step_path)}")

    def _on_key(self, _obj, _ev):
        key = self.iren.GetKeySym()
        if key == "n":
            self._jump(1)
        elif key == "p":
            self._jump(-1)
        elif key == "r":
            self.ren.ResetCamera()
            self.rw.Render()
        elif key in ("q", "Escape"):
            self.rw.Finalize()
            self.iren.TerminateApp()

    def _jump(self, delta: int):
        if not self.steps:
            return
        self._idx = max(0, min(self._idx + delta, len(self.steps) - 1))
        self.show(self.steps[self._idx])

    def run(self):
        self.rw.Render()
        self.iren.Initialize()
        if self.steps:
            self.show(self.steps[0])
        self.iren.Start()


def _params_summary(path: Path) -> str:
    try:
        p = json.loads((path.parent / "params.json").read_text(encoding="utf-8"))
    except Exception:
        return ""
    keys = ("od_mm", "bore_mm", "thick_mm", "slots", "teeth", "holes", "pcd_mm",
            "hdia_mm", "grooves", "gw_mm", "gd_mm", "lh_holes", "cl_holes",
            "rs_count", "cavity_width_mm", "rim_arc_radius_mm", "R_mm",
            "depth_mm", "throat_half_width_mm")
    return "  |  ".join(f"{k}={p[k]}" for k in keys if p.get(k) is not None)


def _cli_loop(viewer: StepViewer, base_dir: Path):
    """命令行顺序浏览：回车下一个 / 输入序号跳转 / q 退出。"""
    steps = []
    if base_dir.is_file() and base_dir.suffix.lower() == ".step":
        steps = [base_dir]
    else:
        steps = sorted(base_dir.glob("*/c*/output.step"))
    if not steps:
        print("未找到 step 文件")
        return
    print(f"共 {len(steps)} 个 step，回车=下一个，输入 n=跳转序号，q=退出")
    idx = 0
    while True:
        print(f"[{idx + 1}/{len(steps)}] {steps[idx].parent.name}  "
              f"{_params_summary(steps[idx])}")
        viewer.show(steps[idx])
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if line in ("q", "Q", "quit"):
            break
        if line.isdigit():
            idx = int(line) - 1
        else:
            idx += 1
        idx = max(0, min(idx, len(steps) - 1))


def _collect_steps(base_dir: Path) -> list:
    if base_dir.is_file() and base_dir.suffix.lower() == ".step":
        return [base_dir]
    return sorted(base_dir.glob("*/c*/output.step"))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(DEFAULT_COLLECTION),
                    help="collection 根目录或单个 .step 文件")
    ap.add_argument("--gui", action="store_true",
                    help="VTK 交互窗口模式（n/p 翻页，鼠标旋转缩放）；默认 CLI 顺序浏览")
    args = ap.parse_args(argv)
    base = Path(args.path)
    if args.gui:
        steps = _collect_steps(base)
        viewer = StepViewer(base, steps)
        viewer.run()
    else:
        viewer = StepViewer(base)
        _cli_loop(viewer, base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
