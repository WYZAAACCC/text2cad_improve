"""mesh_sector.py — STEP → 分析域 (整周 或 环形扇区, 可选 z=0 半对称) → 二阶四面体网格 → APDL.

分析域由配置决定, 不由本模块决定:
  geometry.sector_deg   360 = 整周; 否则为环形扇区的角度
  geometry.theta_low_deg  扇区起始角 (整周时忽略)
  geometry.z_symmetry   是否在 z=0 处切半 (利用半对称)

"一定是循环扇区" 是错的: 叶片、非对称支架这类零件没有可用的旋转重复,
它们的正确分析域就是整周。哪一种, 由规划器判断, 本模块只负责造出来。

用法: python -m server.fea3d.mesh_sector --config server/fea3d/manual_config.json --job <jobdir> [--gui]
依赖: pip install gmsh
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import gmsh

# 项目根 (仓库根) = mesh_sector.py 的上上级的上上级
PROJECT_ROOT = Path(__file__).resolve().parents[4]  # 仓库根


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def case_frame_transform(origin, direction) -> dict:
    """The rigid transform taking `direction` to global +Z.

    Kept as a pure function so the Gmsh path and the structural package's
    `Normalisation` can be compared directly. The two must agree; if they do
    not, the mesh and the CAD facts are expressed in different frames and a
    partial solve can look plausible.
    """
    origin = [float(value) for value in origin]
    direction = _unit([float(value) for value in direction])
    cross = [
        direction[1] * 1.0 - direction[2] * 0.0,
        direction[2] * 0.0 - direction[0] * 1.0,
        direction[0] * 0.0 - direction[1] * 0.0,
    ]
    sine = math.sqrt(sum(value * value for value in cross))
    cosine = max(-1.0, min(1.0, direction[2]))
    if sine > 1e-15:
        axis = [value / sine for value in cross]
        angle = math.atan2(sine, cosine)
    elif cosine < 0.0:
        axis = [1.0, 0.0, 0.0]
        angle = math.pi
    else:
        axis = [0.0, 0.0, 1.0]
        angle = 0.0
    if angle:
        kx, ky, kz = axis
        k = [[0.0, -kz, ky], [kz, 0.0, -kx], [-ky, kx, 0.0]]
        k2 = [
            [sum(k[i][m] * k[m][j] for m in range(3)) for j in range(3)]
            for i in range(3)
        ]
        sin, cos = math.sin(angle), math.cos(angle)
        rotation = [
            [
                (1.0 if i == j else 0.0)
                + sin * k[i][j] + (1.0 - cos) * k2[i][j]
                for j in range(3)
            ]
            for i in range(3)
        ]
    else:
        rotation = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    rotated_origin = [
        sum(rotation[i][j] * origin[j] for j in range(3))
        for i in range(3)
    ]
    return {
        "axis": axis,
        "angle": angle,
        "rotation": rotation,
        "translation": [rotated_origin[0], rotated_origin[1], 0.0],
    }


def _apply_case_frame(dimtags, origin, direction) -> None:
    """Move imported geometry so the case axis is global +Z through origin."""
    transform = case_frame_transform(origin, direction)
    if (
        abs(transform["angle"]) < 1e-15
        and all(abs(value) < 1e-15 for value in transform["translation"])
    ):
        return
    if abs(transform["angle"]) >= 1e-15:
        axis = transform["axis"]
        gmsh.model.occ.rotate(
            dimtags, 0.0, 0.0, 0.0,
            axis[0], axis[1], axis[2], transform["angle"],
        )
    translation = transform["translation"]
    gmsh.model.occ.translate(
        dimtags, -translation[0], -translation[1], 0.0
    )
    gmsh.model.occ.synchronize()


def _squared(axis: str, centre: float) -> str:
    """`(x - c)^2`, written as a product because MathEval has no `^`.

    `x*x` appears in this file already, so multiplication is what the
    evaluator is known to accept; `^` is not used anywhere and is not worth
    being the first place to try.
    """
    return f"({axis} - {centre})*({axis} - {centre})"


def _distance_to(zone: dict) -> str:
    """A MathEval expression for the distance from anywhere to this region.

    Zero inside the region and growing outward, so the size is the target
    inside it and ramps back to the web over `ramp_mm` outside - which is
    what `_size_expression` does with whatever this returns.
    """
    kind = zone.get("kind") or "cylinder"
    if kind == "cylinder":
        radius = float(zone["r_center_mm"])
        return f"abs(sqrt(x*x+y*y) - {radius})"
    if kind == "sphere":
        centre = [float(v) for v in (zone.get("center_mm") or [])]
        if len(centre) != 3:
            raise ValueError(
                f"refinement zone {zone.get('name')}: a sphere needs "
                "center_mm with three components"
            )
        radius = float(zone.get("radius_mm") or 0.0)
        offset = " + ".join(
            _squared(axis, value) for axis, value in zip("xyz", centre)
        )
        # Inside the sphere the distance is zero, so the target size applies
        # throughout it and the ramp starts at its surface. The bare distance
        # from the centre would coarsen the size across the sphere's own
        # interior, which is not what a region of that size means.
        return f"max(0, sqrt({offset}) - {radius})"
    if kind == "box":
        low = [float(v) for v in (zone.get("min_mm") or [])]
        high = [float(v) for v in (zone.get("max_mm") or [])]
        if len(low) != 3 or len(high) != 3:
            raise ValueError(
                f"refinement zone {zone.get('name')}: a box needs min_mm and "
                "max_mm with three components each"
            )
        centre = [(a + b) / 2.0 for a, b in zip(low, high)]
        half = [(b - a) / 2.0 for a, b in zip(low, high)]
        # Chebyshev distance to the box: zero inside, and outside it grows by
        # the largest single-axis overshoot rather than the diagonal, so the
        # ramp means the same thing on every face of the box.
        axes = [
            f"(abs({axis} - {c}) - {h})"
            for axis, c, h in zip("xyz", centre, half)
        ]
        return f"max(0, max(max({axes[0]}, {axes[1]}), {axes[2]}))"
    raise ValueError(
        f"refinement zone {zone.get('name')}: {kind!r} is not a region this "
        "mesher can size on. It places resolution by distance - cylinder, "
        "sphere or box - and has no way to express anything else."
    )


def _size_expression(m: dict):
    """Build a gmsh MathEval size expression from the refinement zones.

    The global MeshSizeMax/Min alone cannot place resolution where the answer
    is decided: on a turbine disc the bore and the fir-tree slot region carry
    the peak stress and the load, while the web carries neither. Leaving
    sizing to curvature alone puts the fine elements wherever the smallest
    fillet happens to be.

    Each zone puts a target size at a place and ramps back to the web size
    away from it. The resulting field is the minimum over zones, so
    overlapping regions keep the finer of the two.

    The place is a `kind`: a `cylinder` is a band at a radius from the global
    Z axis (the original vocabulary, and the default when no kind is given so
    that every config written before this existed meshes identically), a
    `sphere` is everything within a radius of a point, and a `box` is
    everything inside an axis-aligned box. All three are distances, which is
    what MathEval can evaluate; anything that is not a distance - "near these
    faces", say - is refused by name rather than approximated, because a
    region silently reinterpreted as something else is a mesh that does not
    test what it was asked to test.

    Returns None when the config declares no refinement, preserving the
    original uniform-sizing behaviour.
    """
    refinement = m.get("refinement")
    if not refinement:
        return None
    web = float(refinement["web_size_mm"])
    terms = []
    for zone in refinement["zones"]:
        size = float(zone["size_mm"])
        ramp = float(zone["ramp_mm"])
        if ramp <= 0:
            raise ValueError(f"refinement zone {zone.get('name')} needs ramp_mm > 0")
        distance = _distance_to(zone)
        terms.append(
            "({size} + ({web} - {size}) * min(1, {distance} / {ramp}))".format(
                size=size, web=web, distance=distance, ramp=ramp
            )
        )
    expression = terms[0]
    for term in terms[1:]:
        expression = f"min({expression}, {term})"
    return expression


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
    sector = float(gcfg.get("sector_deg", 360.0))
    # 整周是一个正当答案, 不是退化情形: 没有可用旋转重复的零件 (叶片、非对称
    # 支架) 的正确分析域就是整周。域由规划器决定, 这里不假设扇区存在。
    full = sector >= 359.9
    z_sym = bool(gcfg.get("z_symmetry", True))
    theta_low = float(gcfg.get("theta_low_deg", 0.0))
    theta_high = theta_low + sector
    r_outer = float(gcfg["r_outer_mm"])
    z_half = float(gcfg["z_half_mm"])
    r_bore = float(gcfg.get("r_bore_mm", 0.0))
    m = cfg["mesh"]

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.model.add("disc_domain")

        # ---- 1. 导入 STEP (~15MB, 1-2 分钟) ----
        step_rel = cfg["step_file"]
        step_path = str(Path(step_rel) if Path(step_rel).is_absolute() else PROJECT_ROOT / step_rel)
        print(f"[mesh] importing STEP: {step_path}")
        disc = gmsh.model.occ.importShapes(step_path)
        vols = [t for d, t in disc if d == 3]
        assert len(vols) == 1, f"STEP 应含 1 个实体, 实得 {len(vols)}"
        frame = gcfg.get("frame") or {}
        if frame:
            _apply_case_frame(
                [(3, vol) for vol in vols],
                frame.get("axis_origin_mm") or [0.0, 0.0, 0.0],
                frame.get("axis_direction_mm") or [0.0, 0.0, 1.0],
            )
            print("[mesh] case frame applied: rotation axis -> global +Z")
        print(f"[mesh] STEP loaded, 实体数: {len(vols)}")

        # ---- 2. 分析域刀具 ----
        # 整周 -> 长方体; 环形扇区 -> 带角度范围的实心圆柱。
        # 两者都可选在 z=0 切断以利用半对称。
        #
        # 刀具必须完全罩住零件: 小于零件的刀具不报错, 它会静默截断, 而截断掉
        # 的材料看起来像"这个分析域本来就少一块", 不像配置写小了。所以以实测
        # 包围盒为准, 配置里的 r_outer/z_half 只当下限。
        # OCC-level bounding box: at this point the shape is imported but not
        # yet synchronised into the gmsh model, so a model-level query would
        # come back empty.
        bx0, by0, bz0, bx1, by1, bz1 = gmsh.model.occ.getBoundingBox(3, vols[0])
        reach = max(r_outer + 10.0, math.hypot(bx0, by0), math.hypot(bx1, by1))
        thickness = max(z_half + 2.0, abs(bz0), abs(bz1))
        if thickness > z_half + 2.0:
            print(
                "[mesh] 注意: 零件 z 跨 %.3f..%.3f 超出配置的 z_half_mm=%.3f, "
                "刀具已按实测尺寸放大到 %.3f" % (bz0, bz1, z_half, thickness)
            )
        if full:
            tool = gmsh.model.occ.addBox(
                -reach, -reach,
                0.0 if z_sym else -thickness,
                2.0 * reach, 2.0 * reach,
                thickness if z_sym else 2.0 * thickness,
            )
        else:
            tool = gmsh.model.occ.addCylinder(
                0, 0, 0.0 if z_sym else -thickness,
                0, 0, thickness if z_sym else 2.0 * thickness,
                reach,
                angle=math.radians(sector),
            )
            gmsh.model.occ.rotate(
                [(3, tool)], 0, 0, 0, 0, 0, 1, math.radians(theta_low)
            )
        out, _ = gmsh.model.occ.intersect([(3, vols[0])], [(3, tool)])
        gmsh.model.occ.synchronize()
        svols = [t for d, t in out if d == 3]
        assert len(svols) == 1, f"布尔交后应为 1 个实体, 实得 {len(svols)}"
        print(
            "[mesh] 分析域切割完成: 整周%s" % (" + z半对称" if z_sym else "")
            if full
            else "[mesh] 分析域切割完成: 扇区 %.4g° 起 %.4g°%s"
            % (sector, theta_low, " + z半对称" if z_sym else "")
        )

        # ---- 3. 边界面确定性分类: low(θ=low) / high(θ=high) / sym(z=0) ----
        def _cls(tag):
            n = _surf_normal(tag)
            cx, cy, cz = gmsh.model.occ.getCenterOfMass(2, tag)
            if abs(n[2]) > 0.999 and abs(cz) < 1e-3:
                return "sym"
            if full:
                return None
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
        if not full:
            if not (faces["low"] and faces["high"]):
                raise ValueError(
                    f"扇区 {sector}° (起 {theta_low}°) 上找不到切割边界面 — 这个"
                    "角度范围不构成一个周期域。换一个扇区角度, 或改用整周分析。"
                )
            assert len(faces["low"]) == len(faces["high"]), (
                f"low/high 面数不等: {len(faces['low'])} vs {len(faces['high'])}"
                " — 可能几何特征穿过了切割面, 调整 theta_low"
            )
        if z_sym:
            assert faces["sym"], "未识别出 z=0 对称面"

        # ---- 4. 周期配对 + setPeriodic (仅环形扇区需要) ----
        pairs = []
        if not full:
            rot = math.radians(sector)
            c_, s_ = math.cos(rot), math.sin(rot)
            affine = [c_, -s_, 0, 0, s_, c_, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
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
        # Curvature sizing stays enabled as a floor so small fillets keep being
        # resolved; the background field below only lowers the size further.
        expression = _size_expression(m)
        if expression is not None:
            field = gmsh.model.mesh.field.add("MathEval")
            gmsh.model.mesh.field.setString(field, "F", expression)
            gmsh.model.mesh.field.setAsBackgroundMesh(field)
            # Let the field alone decide the size: boundary- and point-based
            # sizing would smear the coarse web size into the refined bands.
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            print(f"[mesh] refinement field: {expression}")
        gmsh.model.mesh.generate(3)

        # 雅可比质量断言 (拦在免费阶段, 不让坏单元流到 ANSYS)
        etypes0, etags0, enodes0 = gmsh.model.mesh.getElements(3)
        all_etags = [int(t) for arr in etags0 for t in arr]
        quals = gmsh.model.mesh.getElementQualities(all_etags, "minSICN")
        min_q = min(quals)
        n_bad = sum(1 for q in quals if q <= 0)
        print(f"[mesh] 单元质量 minSICN: min={min_q:.4f}, 非正雅可比单元数={n_bad}")
        assert n_bad == 0, (
            f"{n_bad} 个单元雅可比非正 (minSICN={min_q:.4f}) — ANSYS 会拒收, 请调小 size_min_mm 重试"
        )

        # 按径向分带统计单元尺寸: 报告要能自证加密落到了该落的位置,
        # 而不只是"请求过加密"。孔缘与榫槽区是应力/载荷控制区。
        _tags, _coords, _ = gmsh.model.mesh.getNodes()
        _coord = {
            int(_tags[i]): (_coords[3 * i], _coords[3 * i + 1], _coords[3 * i + 2])
            for i in range(len(_tags))
        }
        _conn = enodes0[0]
        band_count = 5
        band_sizes: list[list[float]] = [[] for _ in range(band_count)]
        for j in range(len(all_etags)):
            corners = [_coord[int(_conn[10 * j + k])] for k in range(4)]
            cx = sum(c[0] for c in corners) / 4.0
            cy = sum(c[1] for c in corners) / 4.0
            radius = math.hypot(cx, cy)
            index = int((radius - r_bore) / (r_outer - r_bore) * band_count)
            index = min(max(index, 0), band_count - 1)
            edges = [
                math.dist(corners[a], corners[b])
                for a, b in ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
            ]
            band_sizes[index].append(sum(edges) / len(edges))
        size_profile = []
        for index, values in enumerate(band_sizes):
            lo = r_bore + (r_outer - r_bore) * index / band_count
            hi = r_bore + (r_outer - r_bore) * (index + 1) / band_count
            values_sorted = sorted(values)
            size_profile.append(
                {
                    "radius_min_mm": round(lo, 3),
                    "radius_max_mm": round(hi, 3),
                    "element_count": len(values),
                    "mean_size_mm": (
                        round(sum(values) / len(values), 4) if values else None
                    ),
                    "median_size_mm": (
                        round(values_sorted[len(values_sorted) // 2], 4)
                        if values
                        else None
                    ),
                }
            )
            print(
                "[mesh]   r=%6.1f-%6.1f  n=%6d  mean h=%s mm"
                % (lo, hi, len(values), size_profile[-1]["mean_size_mm"])
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
        n_sym = _count(lambda x, y, z: abs(z) < 1e-3)
        node_counts = {"sym_plane_z0": n_sym}
        checks = {"has_sym_nodes": True}
        if r_bore > 0:
            n_bore = _count(
                lambda x, y, z: abs(math.hypot(x, y) - r_bore) < 0.5
            )
            node_counts["bore_r%.0f" % r_bore] = n_bore
            checks["has_bore_nodes"] = n_bore > 0
        n_low = n_high = None
        if not full:
            n_low = _count(
                lambda x, y, z: abs(-math.sin(tl) * x + math.cos(tl) * y) < 1e-3
            )
            n_high = _count(
                lambda x, y, z: abs(-math.sin(th) * x + math.cos(th) * y) < 1e-3
            )
            node_counts["low_plane"] = n_low
            node_counts["high_plane"] = n_high
            checks["low_eq_high_nodes"] = n_low == n_high
        if z_sym:
            checks["has_sym_nodes"] = n_sym > 0
        else:
            node_counts.pop("sym_plane_z0")
            checks.pop("has_sym_nodes")

        report = {
            "nodes": len(ntags),
            "elements": len(eids),
            "element_type": "tet10/SOLID187",
            "frame_applied": bool(gcfg.get("frame")),
            "frame": gcfg.get("frame"),
            "domain": {
                "type": "full_360" if full else "cyclic_sector",
                "sector_deg": round(sector, 6),
                "theta_low_deg": None if full else round(theta_low, 6),
                "z_symmetry": z_sym,
            },
            "refinement_requested": m.get("refinement"),
            "quality": {
                "min_sicn": round(min_q, 6),
                "non_positive_jacobian_elements": n_bad,
                "elements_below_0p1_sicn": sum(1 for q in quals if q < 0.1),
                "elements_below_0p3_sicn": sum(1 for q in quals if q < 0.3),
            },
            "size_profile": size_profile,
            "boundary_faces": report_faces,
            "periodic_pairs": pairs,
            "node_counts": node_counts,
            "asserts": checks,
        }
        if not full:
            assert n_low == n_high, (
                f"周期边界节点数不匹配 {n_low} vs {n_high} — setPeriodic 失效"
            )
        if z_sym:
            assert n_sym > 0, "z=0 对称面上没有节点"
        # 中心孔只记录不断言: 并非每个零件都有 (叶片就没有)。"必须有孔" 是
        # "轮盘" 这条规则, 不是几何本身的性质。

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
