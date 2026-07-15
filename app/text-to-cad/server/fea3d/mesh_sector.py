"""mesh_sector.py — 涡轮盘 STEP → 6°x半轴 循环对称扇区 → 周期二阶四面体网格 → APDL 网格文件.

用法: python -m server.fea3d.mesh_sector --config server/fea3d/manual_config.json --job <jobdir> [--gui]
依赖: pip install gmsh
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path
import gmsh

# 项目根 (仓库根) = mesh_sector.py 的上上级的上上级
PROJECT_ROOT = Path(__file__).resolve().parents[4]  # 仓库根


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def _surf_normal(tag: int):
    """取面质心处的单位法向 (平面面质心必在面上; 对曲面 getParametrization 取最近点)。"""
    cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, tag)
    uv = gmsh.model.getParametrization(2, tag, [cx, cy, cz])
    n = gmsh.model.getNormal(tag, uv)
    return _unit(list(n[0:3]))


def build(cfg: dict, job_dir: Path, gui: bool = False) -> dict:
    """执行网格生成, 返回 mesh_report dict.

    cfg: manual_config.json 的内容
    job_dir: 作业目录 (mesh.inp, mesh_report.json 输出到此)
    gui: True 则打开 gmsh 图形界面供人工目检
    """
    gcfg = cfg["geometry"]
    theta_low = float(gcfg["theta_low_deg"])
    sector = float(gcfg["sector_deg"])
    theta_high = theta_low + sector
    r_outer = float(gcfg["r_outer_mm"])
    z_half = float(gcfg["z_half_mm"])
    r_bore = float(gcfg["r_bore_mm"])
    m = cfg["mesh"]

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.model.add("disc_sector")

        # ---- 1. 导入整盘 STEP (~15MB, 1-2 分钟) ----
        step_rel = cfg["step_file"]
        step_path = str(Path(step_rel) if Path(step_rel).is_absolute() else PROJECT_ROOT / step_rel)
        print(f"[mesh] importing STEP: {step_path}")
        disc = gmsh.model.occ.importShapes(step_path)
        vols = [t for d, t in disc if d == 3]
        assert len(vols) == 1, f"STEP 应含 1 个实体, 实得 {len(vols)}"
        print(f"[mesh] STEP loaded, 实体数: {len(vols)}")

        # ---- 2. 扇区刀具 = 带角度范围的实心圆柱 (z从0起 => 同时完成 z=0 半对称切割) ----
        tool = gmsh.model.occ.addCylinder(
            0, 0, 0, 0, 0, z_half + 2.0,
            r_outer + 10.0,
            angle=math.radians(sector),
        )
        gmsh.model.occ.rotate([(3, tool)], 0, 0, 0, 0, 0, 1, math.radians(theta_low))
        out, _ = gmsh.model.occ.intersect([(3, vols[0])], [(3, tool)])
        gmsh.model.occ.synchronize()
        svols = [t for d, t in out if d == 3]
        assert len(svols) == 1, f"布尔交后应为 1 个实体, 实得 {len(svols)}"
        print(f"[mesh] 扇区切割完成, 实体数: {len(svols)}")

        # ---- 3. 边界面确定性分类: low(θ=low) / high(θ=high) / sym(z=0) ----
        def _cls(tag):
            n = _surf_normal(tag)
            cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, tag)
            if abs(n[2]) > 0.999 and abs(cz) < 1e-3:
                return "sym"
            for name, th in (("low", theta_low), ("high", theta_high)):
                tl = math.radians(th)
                dot = abs(-math.sin(tl) * n[0] + math.cos(tl) * n[1])
                thc = math.degrees(math.atan2(cy, cx))
                if dot > 0.999 and abs(thc - th) < 0.3:
                    return name
            return None

        faces: dict[str, list[int]] = {"low": [], "high": [], "sym": []}
        report_faces = []
        for _, tag in gmsh.model.getEntities(2):
            c = _cls(tag)
            cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, tag)
            area = gmsh.model.occ.getMass(2, tag)
            report_faces.append({
                "tag": tag, "class": c,
                "area_mm2": round(area, 2),
                "centroid": [round(cx, 3), round(cy, 3), round(cz, 3)],
            })
            if c:
                faces[c].append(tag)

        print(f"[mesh] 边界面分类: low={len(faces['low'])} high={len(faces['high'])} sym={len(faces['sym'])}")

        # 硬断言
        assert faces["low"] and faces["high"], "未识别出切割边界面"
        assert len(faces["low"]) == len(faces["high"]), (
            f"low/high 面数不等: {len(faces['low'])} vs {len(faces['high'])}"
            " — 可能槽穿过了切割面, 调整 theta_low"
        )
        assert faces["sym"], "未识别出 z=0 对称面"

        # ---- 4. 周期配对 + setPeriodic ----
        rot = math.radians(sector)
        c_, s_ = math.cos(rot), math.sin(rot)
        affine = [c_, -s_, 0, 0, s_, c_, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        pairs = []
        for lt in faces["low"]:
            lx, ly, lz = gmsh.model.occ.getCenterOfMass(2, lt)
            rx, ry = c_ * lx - s_ * ly, s_ * lx + c_ * ly
            best, dmin = None, 1e9
            for ht in faces["high"]:
                hx, hy, hz = gmsh.model.occ.getCenterOfMass(2, ht)
                d = math.dist((rx, ry, lz), (hx, hy, hz))
                if d < dmin:
                    best, dmin = ht, d
            assert dmin < 0.5, (
                f"低边界面 {lt} 旋转后无匹配高边界面 (最近距离 {dmin:.3f} mm)"
            )
            pairs.append({"low": lt, "high": best, "pair_dist_mm": round(dmin, 4)})
            gmsh.model.mesh.setPeriodic(2, [best], [lt], affine)

        print(f"[mesh] 周期配对完成: {len(pairs)} 对, 最大距离={max(p['pair_dist_mm'] for p in pairs):.4f}mm")

        # ---- 5. 网格参数 ----
        gmsh.option.setNumber("Mesh.MeshSizeMax", float(m["size_max_mm"]))
        gmsh.option.setNumber("Mesh.MeshSizeMin", float(m["size_min_mm"]))
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", float(m["curvature_pts"]))
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        # 中节点放直边中点 (不向曲面投影): 保证 tet10 雅可比恒正,
        # 否则 ANSYS 会因圆角处高阶节点畸变拒收单元 (EN element shape error)
        gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)
        gmsh.model.mesh.generate(3)

        # 雅可比质量断言 (拦在免费阶段, 不让坏单元流到 ANSYS)
        etypes0, etags0, _ = gmsh.model.mesh.getElements(3)
        all_etags = [int(t) for arr in etags0 for t in arr]
        quals = gmsh.model.mesh.getElementQualities(all_etags, "minSICN")
        min_q = min(quals)
        n_bad = sum(1 for q in quals if q <= 0)
        print(f"[mesh] 单元质量 minSICN: min={min_q:.4f}, 非正雅可比单元数={n_bad}")
        assert n_bad == 0, (
            f"{n_bad} 个单元雅可比非正 (minSICN={min_q:.4f}) — ANSYS 会拒收, 请调小 size_min_mm 重试"
        )

        if gui:
            gmsh.fltk.run()

        # ---- 6. 导出 APDL 网格文件 (N/EN/EMORE) ----
        ntags, ncoords, _ = gmsh.model.mesh.getNodes()
        etypes, etags, enodes = gmsh.model.mesh.getElements(3)

        # 确认纯 tet10
        assert list(etypes) == [11], f"应为纯 tet10 (type 11), 实得 {list(etypes)}"
        conn, eids = enodes[0], etags[0]

        # gmsh tet10 -> ANSYS SOLID187 节点映射:
        # gmsh: v0 v1 v2 v3 | e01 e12 e02 e03 e23 e13
        # ANSYS: I  J  K  L  | M(IJ) N(JK) O(KI) P(IL) Q(JL) R(KL)
        # => ANSYS 第 9、10 节点 = gmsh 第 10、9 → 交换最后两个
        PERM = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]

        mesh_inp = job_dir / "mesh.inp"
        print(f"[mesh] 导出网格: {len(ntags)} 节点, {len(eids)} 单元 → {mesh_inp}")
        with open(mesh_inp, "w", newline="\n") as f:
            f.write("/NOPR\n")
            for i, tag in enumerate(ntags):
                x = ncoords[3 * i]
                y = ncoords[3 * i + 1]
                z = ncoords[3 * i + 2]
                f.write(f"N,{int(tag)},{x:.10g},{y:.10g},{z:.10g}\n")
            f.write("TYPE,1\nMAT,1\n")
            for j, eid in enumerate(eids):
                ns = [int(conn[10 * j + k]) for k in PERM]
                f.write(
                    "EN,%d,%d,%d,%d,%d,%d,%d,%d,%d\n" % (
                        int(eid), ns[0], ns[1], ns[2], ns[3],
                        ns[4], ns[5], ns[6], ns[7],
                    )
                )
                f.write("EMORE,%d,%d\n" % (ns[8], ns[9]))
            f.write("/GOPR\n")

        # ---- 7. mesh_report.json ----
        def _count(pred):
            return sum(
                1 for i in range(len(ntags))
                if pred(ncoords[3 * i], ncoords[3 * i + 1], ncoords[3 * i + 2])
            )

        tl, th = math.radians(theta_low), math.radians(theta_high)
        n_low = _count(lambda x, y, z: abs(-math.sin(tl) * x + math.cos(tl) * y) < 1e-3)
        n_high = _count(lambda x, y, z: abs(-math.sin(th) * x + math.cos(th) * y) < 1e-3)
        n_sym = _count(lambda x, y, z: abs(z) < 1e-3)
        n_bore = _count(lambda x, y, z: abs(math.hypot(x, y) - r_bore) < 0.5)
        report = {
            "nodes": len(ntags),
            "elements": len(eids),
            "element_type": "tet10/SOLID187",
            "boundary_faces": report_faces,
            "periodic_pairs": pairs,
            "node_counts": {
                "low_plane": n_low,
                "high_plane": n_high,
                "sym_plane_z0": n_sym,
                "bore_r%.0f" % r_bore: n_bore,
            },
            "asserts": {
                "low_eq_high_nodes": n_low == n_high,
                "has_sym_nodes": n_sym > 0,
                "has_bore_nodes": n_bore > 0,
            },
        }
        assert n_low == n_high, (
            f"周期边界节点数不匹配 {n_low} vs {n_high} — setPeriodic 失效"
        )
        assert n_sym > 0 and n_bore > 0

        (job_dir / "mesh_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        print(f"[mesh] report 已写入 {job_dir / 'mesh_report.json'}")
        return report
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--gui", action="store_true")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    job_dir = Path(args.job)
    job_dir.mkdir(parents=True, exist_ok=True)
    build(cfg, job_dir, gui=args.gui)
