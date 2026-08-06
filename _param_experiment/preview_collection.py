"""每族 1 个代表盘预览：执行完整流程 + 渲染 PNG（用户快速查看能否用）。

- 对 32 族各取第一个 feasible 候选，完整执行（模板确定性）
- 产物收集到 collection/<family>/preview/，渲染 PNG 到 preview_png/<family>.png

用法:
  .conda/python.exe _param_experiment/preview_collection.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

import run_batch  # noqa: E402
from design_families import DESIGN_FAMILIES  # noqa: E402

COLLECTION = _HERE / "output" / "collection"
PREVIEW_PNG = _HERE / "output" / "preview_png"


def render_png(step: Path, out_png: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from view_steps_tk import shape_to_polys
    polys, verts = shape_to_polys(step, 0.6)
    fig = plt.figure(figsize=(5, 4.2))
    ax = fig.add_subplot(111, projection="3d")
    ax.add_collection3d(Poly3DCollection(polys, facecolor="#7fa8d9", edgecolor="none", alpha=0.92))
    xs = [p[0] for p in verts]; ys = [p[1] for p in verts]; zs = [p[2] for p in verts]
    ax.set_xlim(min(xs), max(xs)); ax.set_ylim(min(ys), max(ys)); ax.set_zlim(min(zs), max(zs))
    ax.set_box_aspect((1, 1, max(0.3, min(1.0, (max(zs) - min(zs)) / max((max(xs) - min(xs)), 1e-6)))))
    ax.axis("off")
    plt.savefig(out_png, dpi=90, bbox_inches="tight")
    plt.close()


def main() -> int:
    cands = json.loads((_HERE / "output" / "datasets" / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    # 每族取第一个候选（candidate_sampler 已把族名义完整特征放第一位）；
    # 族名义若不可行则回退第一个非 infeasible。此前只取第一个 feasible → 只展示最简变体。
    first: dict[str, dict] = {}
    for c in cands:
        first.setdefault(c["family"], c)
    by_fam: dict[str, dict] = {}
    for fid in sorted(DESIGN_FAMILIES):
        c = first.get(fid)
        if c and c["zone"] == "infeasible":
            c = next((x for x in cands if x["family"] == fid and x["zone"] != "infeasible"), None)
        by_fam[fid] = c
    PREVIEW_PNG.mkdir(parents=True, exist_ok=True)
    results = []
    for fid in sorted(DESIGN_FAMILIES):
        c = by_fam.get(fid)
        if not c:
            print(f"[{fid}] 无可行候选")
            continue
        tid = f"preview_{fid}"
        # 断点续跑：collection/<族>/preview 已产出则跳过
        if (COLLECTION / fid / "preview" / "output.step").exists():
            results.append((fid, "skipped", "-"))
            print(f"[{fid}] skipped")
            continue
        c2 = dict(c)
        c2["task_id"] = tid
        try:
            status = run_batch._run_one(c2, use_template=True)
        except Exception as exc:  # noqa: BLE001
            status = f"exc:{str(exc)[:80]}"
        out_dir = run_batch.OUTPUT / tid
        step = out_dir / "output.step"
        if status == "completed" and step.exists():
            dst_dir = COLLECTION / fid / "preview"
            dst_dir.mkdir(parents=True, exist_ok=True)
            for name in ("output.step", "output.brep", "raw_fixed.json", "canonical_ir.json",
                         "validation_report.json", "request.json", "pipeline_log.json"):
                src = out_dir / name
                if src.exists():
                    import shutil
                    shutil.copy2(src, dst_dir / name)
            (dst_dir / "params.json").write_text(
                json.dumps(c2["params"], ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                render_png(step, PREVIEW_PNG / f"{fid}.png")
                img = "PNG-OK"
            except Exception as exc:  # noqa: BLE001
                img = f"PNG-ERR:{str(exc)[:40]}"
            results.append((fid, status, img))
            print(f"[{fid}] {status} {img}")
        else:
            results.append((fid, status, "-"))
            print(f"[{fid}] {status} 无step")
    ok = sum(1 for _, s, _ in results if s == "completed")
    print(f"\n成功 {ok}/32，PNG 在 {PREVIEW_PNG}/，STEP 在 collection/<族>/preview/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
