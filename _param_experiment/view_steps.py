"""交互 3D STEP 查看器（pythonOCC AIS + PyQt5）——逐个核实采集的 step 文件。

- 左键拖动 = 旋转，滚轮 = 缩放，中键拖动 = 平移
- 左侧树：族（D01-D32）→ 参数组合；点击组合 → 右侧加载对应 output.step
- 底部状态栏显示当前 step 路径 + 参数摘要（params.json）

用法:
  python view_steps.py [collection根目录]
  默认 collection = _param_experiment/output/collection
  也可直接传单个 step 路径查看。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QSplitter, QLabel, QStatusBar,
)

_HERE = Path(__file__).resolve().parent
DEFAULT_COLLECTION = _HERE / "output" / "collection"


def read_step(path: Path):
    """STEPControl_Reader 读 STEP → TopoDS_Shape。"""
    from OCP.STEPControl import STEPControl_Reader
    r = STEPControl_Reader()
    r.ReadFile(str(path))
    r.TransferRoots()
    return r.OneShape()


def _params_summary(path: Path) -> str:
    """组合目录 params.json → 一行参数摘要（供状态栏显示）。"""
    try:
        p = json.loads((path.parent / "params.json").read_text(encoding="utf-8"))
    except Exception:
        return ""
    keys = ("od_mm", "bore_mm", "thick_mm", "slots", "teeth", "holes", "pcd_mm",
            "hdia_mm", "grooves", "gw_mm", "gd_mm", "lh_holes", "cl_holes",
            "rs_count", "cavity_width_mm", "rim_arc_radius_mm", "R_mm",
            "depth_mm", "throat_half_width_mm")
    parts = [f"{k}={p[k]}" for k in keys if p.get(k) is not None]
    return "  |  ".join(parts)


class OCCView(QWidget):
    """OCP AIS 3D 视图（左键旋转 / 滚轮缩放 / 中键平移）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        from OCP.AIS import AIS_InteractiveContext
        from OCP.V3d import V3d_Viewer, V3d_XposYposZpos
        from OCP.OpenGl_GraphicDriver import OpenGl_GraphicDriver
        from OCP.Aspect import Aspect_DisplayConnection
        self._conn = Aspect_DisplayConnection()
        self._driver = OpenGl_GraphicDriver(self._conn)
        self._viewer = V3d_Viewer(self._driver)
        self._context = AIS_InteractiveContext(self._viewer)
        self._view = self._viewer.CreateView()
        self._view.SetWindow(int(self.winId()))
        self._view.SetBackgroundColor(0.93, 0.93, 0.95)
        self._view.SetProj(V3d_XposYposZpos)
        self._rot = None
        self._pan = None
        self._ais_displayed = None

    def show_step(self, path: Path):
        shape = read_step(path)
        from OCP.AIS import AIS_Shape
        if self._ais_displayed is not None:
            self._context.Remove(self._ais_displayed, True)
        ais = AIS_Shape(shape)
        self._context.Display(ais, True)
        self._ais_displayed = ais
        self._view.FitAll()
        self._view.ZFitAll()

    # ── 交互 ──
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._rot = (e.pos().x(), e.pos().y())
            self._view.StartRotation(e.pos().x(), e.pos().y())
        elif e.button() == Qt.MiddleButton:
            self._pan = (e.pos().x(), e.pos().y())

    def mouseMoveEvent(self, e):
        if self._rot is not None and e.buttons() & Qt.LeftButton:
            self._view.Rotation(e.pos().x(), e.pos().y())
        elif self._pan is not None and e.buttons() & Qt.MiddleButton:
            dx = e.pos().x() - self._pan[0]
            dy = e.pos().y() - self._pan[1]
            self._view.Pan(int(dx), int(-dy))
            self._pan = (e.pos().x(), e.pos().y())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._rot is not None:
            self._view.EndRotation()
            self._rot = None
        elif e.button() == Qt.MiddleButton:
            self._pan = None

    def wheelEvent(self, e):
        if e.angleDelta().y() > 0:
            self._view.SetZoom(1.1)
        else:
            self._view.SetZoom(0.9)

    def resizeEvent(self, e):
        self._view.MustBeResized()


class MainWindow(QMainWindow):
    def __init__(self, base_dir: Path):
        super().__init__()
        self.setWindowTitle("STEP 查看器 — 32 族采集核实")
        self.resize(1100, 720)
        self.base_dir = Path(base_dir)
        self.occ = OCCView()
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.addWidget(QLabel("就绪"))

        # 左侧树：族 → 组合
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("族 / 参数组合")
        self.tree.setMinimumWidth(300)
        self.tree.itemClicked.connect(self._on_item)
        self._build_tree()

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.occ)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

    def _build_tree(self):
        if self.base_dir.is_file():  # 直接给单个 step
            self._load_single(self.base_dir)
            return
        if not self.base_dir.is_dir():
            self.status.showMessage(f"目录不存在: {self.base_dir}", 8000)
            return
        fam_count = 0
        for fam_dir in sorted(self.base_dir.iterdir()):
            if not fam_dir.is_dir():
                continue
            # 只显示含 output.step 的组合
            combos = sorted(p for p in fam_dir.iterdir()
                            if p.is_dir() and (p / "output.step").exists())
            if not combos:
                continue
            fam_node = QTreeWidgetItem([f"{fam_dir.name}  ({len(combos)})"])
            for combo in combos:
                child = QTreeWidgetItem([combo.name])
                child.setData(0, Qt.UserRole, str(combo / "output.step"))
                fam_node.addChild(child)
            self.tree.addTopLevelItem(fam_node)
            fam_count += 1
        self.status.showMessage(f"{fam_count} 族加载完成，点击左侧组合查看")

    def _load_single(self, step_path: Path):
        self.occ.show_step(step_path)
        self.setWindowTitle(f"STEP — {step_path}")
        self.status.showMessage(str(step_path))

    def _on_item(self, item: QTreeWidgetItem, _col: int):
        step = item.data(0, Qt.UserRole)
        if not step:
            return
        step_path = Path(step)
        try:
            self.occ.show_step(step_path)
        except Exception as exc:  # noqa: BLE001
            self.status.showMessage(f"加载失败: {str(exc)[:120]}", 6000)
            return
        summary = _params_summary(step_path)
        self.setWindowTitle(f"STEP — {step_path.parent.name}")
        self.status.showMessage(f"{step_path.parent.parent.name} / {step_path.parent.name}  "
                                f"{summary}", 15000)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(DEFAULT_COLLECTION),
                    help="collection 根目录或单个 .step 文件")
    args = ap.parse_args(argv)
    app = QApplication(sys.argv)
    win = MainWindow(args.path)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
