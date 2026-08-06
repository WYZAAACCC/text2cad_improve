"""侧边栏 STEP 查看器（tkinter + matplotlib 3D）——快速打开/切换/核实 step 文件。

布局：
  左侧 工具条（打开文件夹 / 打开文件 / 回到采集库）+ 文件树（按目录层级）
  右侧 matplotlib 3D 视图（左键旋转 / 右键缩放 / 滚轮缩放）

操作：
  - "打开文件夹"：选择任意文件夹，递归收集其中 *.step 建树
  - "打开文件"：直接选择单个 .step
  - 点击树节点 → 右侧加载显示；键盘 n/p 或 ↑/↓ 上下切换、r 复位、q 退出
  - 默认加载采集库 collection/（族 → 组合 → step 三级）

说明：使用 matplotlib 3D（软件渲染，稳定显示），网格由 cadquery tessellate 生成。
用法:
  .conda/python.exe _param_experiment/view_steps_tk.py [collection根目录]
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

_HERE = Path(__file__).resolve().parent
DEFAULT_COLLECTION = _HERE / "output" / "collection"
ERROR_LOG = _HERE / "output" / "viewer_error.log"

# 状态栏显示的关键参数
_SUMMARY_KEYS = ("od_mm", "bore_mm", "thick_mm", "slots", "teeth", "holes", "pcd_mm",
                 "hdia_mm", "grooves", "gw_mm", "gd_mm", "lh_holes", "cl_holes",
                 "rs_count", "cavity_width_mm", "rim_arc_radius_mm", "R_mm",
                 "depth_mm", "throat_half_width_mm")


def _log_error(msg: str) -> None:
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n{msg}\n{'─' * 60}\n")
    except Exception:  # noqa: BLE001
        pass


def shape_to_polys(step_path: Path, tol: float = 0.5):
    """STEP → (三角面顶点索引多边形列表, 顶点tuple列表)。"""
    import cadquery as cq
    obj = cq.importers.importStep(str(step_path))
    shape = obj.val()
    verts_raw, faces = shape.tessellate(tol)
    verts = [(float(v.x), float(v.y), float(v.z)) for v in verts_raw]
    polys = [[verts[i] for i in tri] for tri in faces]
    return polys, verts


def _params_summary(path: Path) -> str:
    try:
        p = json.loads((path.parent / "params.json").read_text(encoding="utf-8"))
    except Exception:
        return ""
    return "  |  ".join(f"{k}={p[k]}" for k in _SUMMARY_KEYS if p.get(k) is not None)


class StepBrowser:
    def __init__(self, root: tk.Tk, base_dir: Path):
        self.root = root
        self.root.title("STEP 侧边栏查看器")
        self.root.geometry("1250x760")
        self.base_dir = Path(base_dir)
        self.steps: list[Path] = []
        self._idx = 0
        self._item_step: dict[str, Path] = {}
        self._node_keys: dict[str, str] = {}

        # ── 布局：左右分栏 ──
        paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True)

        # 左：工具条 + 文件树
        left = ttk.Frame(paned)
        bar = ttk.Frame(left)
        ttk.Button(bar, text="打开文件夹", command=self.open_folder).pack(side="left", padx=2, pady=2)
        ttk.Button(bar, text="打开文件", command=self.open_file).pack(side="left", padx=2, pady=2)
        ttk.Button(bar, text="采集库", command=lambda: self.load_folder(self.base_dir)).pack(side="left", padx=2, pady=2)
        self.path_lbl = ttk.Label(bar, text="", foreground="gray")
        self.path_lbl.pack(side="left", padx=6)
        bar.pack(fill="x")

        self.tree = ttk.Treeview(left, show="tree")
        self.tree.pack(fill="both", expand=True, padx=2, pady=2)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        paned.add(left, weight=1)

        # 右：matplotlib 3D
        right = ttk.Frame(paned)
        paned.add(right, weight=4)
        self._init_mpl(right)

        # 键盘导航
        root.bind("<Key-n>", lambda _e: self._jump(1))
        root.bind("<Key-p>", lambda _e: self._jump(-1))
        root.bind("<Key-r>", lambda _e: self._reset_view())
        root.bind("<Key-q>", lambda _e: root.destroy())
        root.bind("<Up>", lambda _e: self._jump(-1))
        root.bind("<Down>", lambda _e: self._jump(1))

        # 初始加载
        if base_dir.is_file() and base_dir.suffix.lower() == ".step":
            self._load_single(base_dir)
        elif base_dir.is_dir():
            self.load_folder(base_dir)

    # ── matplotlib 3D ──
    def _init_mpl(self, parent: ttk.Frame):
        self._fig = plt.Figure(figsize=(8, 6), dpi=100, facecolor="#f0f2f5")
        self._ax = self._fig.add_subplot(111, projection="3d")
        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(self._canvas, parent)
        toolbar.update()
        # 3D 鼠标交互（左键旋转 / 右键缩放 / 中键平移，mpl 内置）

    def _render_polys(self, polys, verts):
        self._ax.clear()
        self._ax.set_facecolor("#f0f2f5")
        self._ax.add_collection3d(Poly3DCollection(
            polys, facecolor="#7fa8d9", edgecolor="#5a7bb0", linewidth=0.1, alpha=0.92))
        xs = [p[0] for p in verts]
        ys = [p[1] for p in verts]
        zs = [p[2] for p in verts]
        self._ax.set_xlim(min(xs), max(xs))
        self._ax.set_ylim(min(ys), max(ys))
        self._ax.set_zlim(min(zs), max(zs))
        self._ax.set_box_aspect((1.0, 1.0, max(0.3, min(1.0, (max(zs) - min(zs)) / max((max(xs) - min(xs)), 1e-6)))))
        self._ax.set_xlabel("X"); self._ax.set_ylabel("Y"); self._ax.set_zlabel("Z")
        self._canvas.draw_idle()

    def _display_step(self, path: Path):
        try:
            polys, verts = shape_to_polys(path)
        except Exception as exc:  # noqa: BLE001
            _log_error(f"[加载失败] {path}\n{traceback.format_exc()}")
            self.root.title(f"[加载失败] {path.name}: {str(exc)[:80]}")
            messagebox.showerror("加载失败", f"{path.name}\n\n{str(exc)[:400]}")
            return
        self._render_polys(polys, verts)
        self.root.title(f"{path.parent.parent.name}/{path.parent.name} — STEP 侧边栏查看器")
        self.path_lbl.config(text=f"{path.parent.name}  {_params_summary(path)}")

    # ── 文件树 ──
    def load_folder(self, folder: Path):
        folder = Path(folder)
        if not folder.is_dir():
            return
        self.steps = sorted(folder.rglob("*.step"))
        self._item_step.clear()
        self._node_keys.clear()
        self.tree.delete(*self.tree.get_children())
        for s in self.steps:
            self._add_step_node(s, folder)
        self.path_lbl.config(text=f"共 {len(self.steps)} 个 STEP")
        if self.steps:
            self._display_step(self.steps[0])

    def _add_step_node(self, s: Path, folder: Path):
        rel = s.relative_to(folder)
        parts = rel.parts
        if len(parts) >= 2:
            grand = str(s.parent.parent)
            g = self._ensure_node(grand, s.parent.parent.name)
            parent = str(s.parent)
            p = self._ensure_node(parent, s.parent.name, g)
        else:
            parent = str(s.parent)
            p = self._ensure_node(parent, s.parent.name)
        item = self.tree.insert(p, "end", text=s.name, values=(str(s),))
        self._item_step[item] = s

    def _ensure_node(self, key: str, label: str, parent: str | None = None) -> str:
        if key in self._node_keys:
            return self._node_keys[key]
        node = self.tree.insert(parent or "", "end", text=label, open=True)
        self._node_keys[key] = node
        return node

    # ── 事件 ──
    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        step = self._item_step.get(sel[0])
        if step:
            self._idx = self.steps.index(step)
            self._display_step(step)

    def _jump(self, delta: int):
        if not self.steps:
            return
        self._idx = max(0, min(self._idx + delta, len(self.steps) - 1))
        s = self.steps[self._idx]
        self._display_step(s)
        for item, sp in self._item_step.items():
            if sp == s:
                self.tree.selection_set(item)
                self.tree.see(item)
                break

    def _reset_view(self):
        self._ax.set_xlim(self._ax.get_xlim()[::-1])  # 触发刷新占位
        self._canvas.draw_idle()

    def _load_single(self, path: Path):
        self.steps = [path]
        self._idx = 0
        self._display_step(path)

    def open_folder(self):
        d = filedialog.askdirectory(initialdir=str(self.base_dir), title="选择含 .step 的文件夹")
        if d:
            self.load_folder(Path(d))

    def open_file(self):
        f = filedialog.askopenfilename(
            initialdir=str(self.base_dir), title="选择 .step 文件",
            filetypes=[("STEP", "*.step *.stp"), ("所有文件", "*.*")])
        if f:
            self._load_single(Path(f))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(DEFAULT_COLLECTION),
                    help="collection 根目录、任意文件夹或单个 .step")
    args = ap.parse_args(argv)
    root = tk.Tk()

    def _report_callback_exc(exc_type, exc_val, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        _log_error(f"[回调异常]\n{msg}")
        messagebox.showerror("查看器错误", msg[-800:])

    root.report_callback_exception = _report_callback_exc
    StepBrowser(root, Path(args.path))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
