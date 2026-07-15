"""post3d.py — 解析 nodal_stress_3d.csv, 计算权威指标/安全系数, 生成前端数据.

导出文件（前端消费）:
  stress_field_3d.bin   — 二进制应力点云 (x,y,z,svm,sr,sh,sa,sf)，每节点 8×f32
  sector_surface.json   — 扇区边界三角面 + 每顶点应力值

用法: python -m server.fea3d.post3d --config server.fea3d.manual_config.json --job <jobdir>
"""
from __future__ import annotations
import csv, json, math, re, struct
from pathlib import Path
from collections import defaultdict


def _zone_name(r: float, cfg: dict) -> str:
    """按几何半径分区."""
    g = cfg["geometry"]
    rb = float(g["r_bore_mm"])
    ro = float(g["r_outer_mm"])
    if r < rb + 5:
        return "bore"
    if r < 120:
        return "hub"
    if r < 215:
        return "web"
    return "rim"


def _yield_interp(temp: float, yield_tbl: dict[str, float]) -> float:
    """温度→屈服强度线性插值. yield_tbl: {"20":1100, "300":1050, ...}"""
    pairs = sorted((float(k), float(v)) for k, v in yield_tbl.items())
    if temp <= pairs[0][0]:
        return pairs[0][1]
    if temp >= pairs[-1][0]:
        return pairs[-1][1]
    for i in range(len(pairs) - 1):
        t0, y0 = pairs[i]
        t1, y1 = pairs[i + 1]
        if t0 <= temp <= t1:
            return y0 + (y1 - y0) * (temp - t0) / (t1 - t0)
    return pairs[-1][1]


def post(cfg: dict, job_dir: Path) -> dict:
    """后处理主入口, 返回 metrics dict."""
    ld = cfg["load"]
    gcfg = cfg["geometry"]
    rb = float(gcfg["r_bore_mm"])
    ro = float(gcfg["r_outer_mm"])
    tb = float(ld["t_bore_c"])
    tr = float(ld["t_rim_c"])
    texp = float(ld["t_exponent"])
    yield_tbl = cfg["material"]["yield_mpa_vs_t"]

    csv_path = job_dir / "nodal_stress_3d.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 {csv_path} —— solve 阶段失败或未运行?")

    # ---- 读 CSV ----
    nodes = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        # ANSYS *VWRITE 输出为 F 格式 (带小数点填充, 如 "  1." "  250.03")
        def _f(s):
            return float(s.strip())
        def _i(s):
            return int(float(s.strip()))
        for row in reader:
            sel = _i(row["sel"])
            if sel != 1:
                continue
            x = _f(row["x"]); y = _f(row["y"]); z = _f(row["z"])
            r = math.hypot(x, y)
            nodes.append({
                "nid": _i(row["nid"]),
                "x": x, "y": y, "z": z, "r": r,
                "s_radial": _f(row["s_radial"]),
                "s_hoop": _f(row["s_hoop"]),
                "s_axial": _f(row["s_axial"]),
                "s_eqv": _f(row["s_eqv"]),
                "s1": _f(row["s1"]),
                "s3": _f(row["s3"]),
            })

    if not nodes:
        raise RuntimeError("nodal_stress_3d.csv 无有效节点 (sel!=1)")

    print(f"[post] 读入 {len(nodes)} 个有效节点")

    # ---- 重建 T(r) + 屈服 + 安全系数 ----
    for nd in nodes:
        r = nd["r"]
        t_node = tb + (tr - tb) * ((r - rb) / (ro - rb)) ** texp if ro > rb else tb
        nd["temp"] = t_node
        yield_mpa = _yield_interp(t_node, yield_tbl)
        nd["yield_mpa"] = yield_mpa
        nd["sf"] = yield_mpa / nd["s_eqv"] if nd["s_eqv"] > 0 else float("inf")

    # ---- 总体指标 ----
    max_vm = max(nodes, key=lambda nd: nd["s_eqv"])
    min_sf = min(nodes, key=lambda nd: nd["sf"])
    max_radial = max(nodes, key=lambda nd: nd["s_radial"])
    max_hoop = max(nodes, key=lambda nd: nd["s_hoop"])

    # ---- 分区指标 ----
    zones = {}
    for zname in ["bore", "hub", "web", "rim"]:
        znodes = [n for n in nodes if _zone_name(n["r"], cfg) == zname]
        if znodes:
            zones[zname] = {
                "node_count": len(znodes),
                "max_vm_mpa": round(max(n["s_eqv"] for n in znodes), 1),
                "min_sf": round(min(n["sf"] for n in znodes), 4),
                "max_hoop_mpa": round(max(n["s_hoop"] for n in znodes), 1),
                "max_radial_mpa": round(max(n["s_radial"] for n in znodes), 1),
            }
        else:
            zones[zname] = {"node_count": 0}

    metrics = {
        "model": "turbine_disc_3d_cyclic",
        "sector": f"{gcfg['sector_deg']}° x z∈[0,{gcfg['z_half_mm']}]mm (1/120 full disc)",
        "global": {
            "max_von_mises_mpa": round(max_vm["s_eqv"], 1),
            "max_vm_node": max_vm["nid"],
            "max_vm_location_r_mm": round(max_vm["r"], 2),
            "max_vm_location_z_mm": round(max_vm["z"], 2),
            "max_vm_zone": _zone_name(max_vm["r"], cfg),
            "max_radial_mpa": round(max_radial["s_radial"], 1),
            "max_hoop_mpa": round(max_hoop["s_hoop"], 1),
            "min_safety_factor": round(min_sf["sf"], 4),
            "min_sf_node": min_sf["nid"],
            "min_sf_location_r_mm": round(min_sf["r"], 2),
            "min_sf_zone": _zone_name(min_sf["r"], cfg),
        },
        "zones": zones,
    }

    # ---- 写 metrics.json ----
    (job_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    # ---- 追加 result_summary.txt ----
    rs_path = job_dir / "result_summary.txt"
    rs_lines = []
    if rs_path.exists():
        rs_lines = rs_path.read_text(encoding="utf-8").strip().splitlines()

    rs_lines.append("")
    rs_lines.append("=== Python 后处理权威指标 ===")
    rs_lines.append(f"MAX_VON_MISES = {metrics['global']['max_von_mises_mpa']:.1f} MPa")
    rs_lines.append(f"MAX_VM_LOCATION = r={metrics['global']['max_vm_location_r_mm']:.2f}mm z={metrics['global']['max_vm_location_z_mm']:.2f}mm ({metrics['global']['max_vm_zone']})")
    rs_lines.append(f"MAX_RADIAL = {metrics['global']['max_radial_mpa']:.1f} MPa")
    rs_lines.append(f"MAX_HOOP = {metrics['global']['max_hoop_mpa']:.1f} MPa")
    rs_lines.append(f"MIN_SAFETY_FACTOR = {metrics['global']['min_safety_factor']:.4f} ({metrics['global']['min_sf_zone']})")
    for zname, zinfo in zones.items():
        if zinfo.get("node_count", 0) > 0:
            rs_lines.append(f"ZONE_{zname.upper()}_MAX_VM = {zinfo['max_vm_mpa']:.1f} MPa")
            rs_lines.append(f"ZONE_{zname.upper()}_MIN_SF = {zinfo['min_sf']:.4f}")

    rs_path.write_text("\n".join(rs_lines), encoding="utf-8")
    print(f"[post] 指标已写入 {metrics['global']}")

    # ---- 导出前端数据 ----
    _export_stress_field_bin(job_dir, nodes)
    _export_sector_surface(job_dir, nodes, cfg)
    _export_stress_field_surface_bin(job_dir, nodes)  # Worker 用表面节点做查找

    return metrics


# ---- 前端数据导出 ----

def _export_stress_field_surface_bin(job_dir: Path, nodes: list[dict]) -> None:
    """从 sector_surface.json 提取表面节点应力, 写入 stress_field_surface.bin.
    Worker 用此文件做最近邻, 而非全体积节点——防STL表面顶点跨槽腔误匹配. """
    sp = job_dir / "sector_surface.json"
    if not sp.exists():
        print("[post] sector_surface.json 不存在, 跳过 surface bin 导出")
        return

    surf = json.loads(sp.read_text(encoding="utf-8"))
    positions = surf["positions"]  # [x0,y0,z0, x1,y1,z1, ...]
    fields = surf["fields"]
    by_nid = {nd["nid"]: nd for nd in nodes}
    n_surf = len(positions) // 3

    # 重建每表面节点的应力 (nid → stress)
    # positions 按 surf_ids 顺序, 与原始 mesh.inp 中的 id 对应
    # 但从 JSON 丢失了 nid... 重建策略: 用 (x,y,z) 匹配
    # 更简单: 直接在 mesh.inp 解析时保留 nid, 但这里先做 fallback:
    # 既然 surface 节点是 positions 里的坐标, 我们用 3D 匹配回 node 数据
    # 代价 O(n_surf × log(n_total)), 可接受

    # 建 nodes 的 (x,y,z)→stress 映射 (四舍五入到 0.01mm 去重)
    node_map: dict[tuple[int, int, int], dict] = {}
    for nd in nodes:
        key = (round(nd["x"], 2), round(nd["y"], 2), round(nd["z"], 2))
        node_map[key] = nd

    body = bytearray(16 + n_surf * 8 * 4)
    MAGIC = 0x33534653  # "SFS3" (Stress Field Surface 3D)
    struct.pack_into("<4I", body, 0, MAGIC, n_surf, 8, 0)
    off = 16
    missing = 0
    for i in range(n_surf):
        x = positions[i * 3]
        y = positions[i * 3 + 1]
        z = positions[i * 3 + 2]
        key = (round(x, 2), round(y, 2), round(z, 2))
        nd = node_map.get(key)
        if nd is None:
            # 网格细化产生的额外表面节点 → 用 fields 中的预计算值
            s_vm = fields["s_vm"][i] if i < len(fields["s_vm"]) else 0.0
            s_r = fields["s_r"][i] if i < len(fields["s_r"]) else 0.0
            s_hoop = fields["s_hoop"][i] if i < len(fields["s_hoop"]) else 0.0
            s_axial = fields["s_axial"][i] if i < len(fields["s_axial"]) else 0.0
            sf = fields["sf"][i] if i < len(fields["sf"]) else 1.0
            missing += 1
        else:
            s_vm = nd["s_eqv"]
            s_r = nd["s_radial"]
            s_hoop = nd["s_hoop"]
            s_axial = nd["s_axial"]
            sf = nd["sf"]
        struct.pack_into("<8f", body, off,
                         float(x), float(y), float(z),
                         float(s_vm), float(s_r), float(s_hoop), float(s_axial), float(sf))
        off += 32
    bin_path = job_dir / "stress_field_surface.bin"
    bin_path.write_bytes(body)
    print(f"[post] stress_field_surface.bin: {n_surf} 表面节点, {len(body)/1024:.0f} KB (unmatched={missing}) → {bin_path}")


def _export_stress_field_bin(job_dir: Path, nodes: list[dict]) -> None:
    """导出 stress_field_3d.bin: header(4xu32) + nodeCount*8*f32 little-endian."""
    MAGIC = 0x33444653  # "SFD3"
    n = len(nodes)
    body = bytearray(16 + n * 8 * 4)
    struct.pack_into("<4I", body, 0, MAGIC, n, 8, 0)
    off = 16
    for nd in nodes:
        struct.pack_into("<8f", body, off,
                         float(nd["x"]), float(nd["y"]), float(nd["z"]),
                         float(nd["s_eqv"]), float(nd["s_radial"]),
                         float(nd["s_hoop"]), float(nd["s_axial"]),
                         float(nd["sf"]))
        off += 32  # 8 × 4 bytes
    bin_path = job_dir / "stress_field_3d.bin"
    bin_path.write_bytes(body)
    print(f"[post] stress_field_3d.bin: {n} 节点, {len(body)/1024:.0f} KB → {bin_path}")


def _export_sector_surface(job_dir: Path, nodes: list[dict], cfg: dict) -> None:
    """从 mesh.inp 提取扇区边界三角面, 写入 sector_surface.json."""
    mesh_inp = job_dir / "mesh.inp"
    if not mesh_inp.exists():
        print("[post] mesh.inp 不存在, 跳过 sector_surface 导出")
        return

    text = mesh_inp.read_text(encoding="utf-8")
    # 解析元素: EN,id,n1,n2,n3,n4,n5,n6,n7,n8
    tets: dict[int, list[int]] = {}
    # 4 corner node index only
    for m in re.finditer(r"EN\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)",
                         text):
        eid = int(m.group(1))
        tets[eid] = [int(m.group(g)) for g in range(2, 6)]  # n1..n4

    if not tets:
        print("[post] mesh.inp 中未找到 EN 元素行")
        return

    # 统计每个三角面的出现次数
    face_count: dict[tuple[int, ...], int] = defaultdict(int)
    for corners in tets.values():
        n1, n2, n3, n4 = corners
        for fi in ((n1, n2, n3), (n1, n2, n4), (n1, n3, n4), (n2, n3, n4)):
            face_count[tuple(sorted(fi))] += 1

    # 出现1次的面 = 边界三角面
    boundary = [face for face, cnt in face_count.items() if cnt == 1]
    # 收集表面节点
    surf_ids = sorted(set(n for face in boundary for n in face))
    id_to_idx = {nid: i for i, nid in enumerate(surf_ids)}

    # 每表面节点的应力值 (从 nodes 列表按 nid 索引, 缺失则 NaN)
    by_nid = {nd["nid"]: nd for nd in nodes}
    n_surf = len(surf_ids)
    fields = {k: [0.0] * n_surf for k in ("s_vm", "s_r", "s_hoop", "s_axial", "sf")}
    positions = [0.0] * (n_surf * 3)
    for idx, nid in enumerate(surf_ids):
        p = by_nid.get(nid, {"x": 0, "y": 0, "z": 0})
        positions[idx * 3] = p["x"]
        positions[idx * 3 + 1] = p["y"]
        positions[idx * 3 + 2] = p["z"]
        fields["s_vm"][idx] = p.get("s_eqv", 0)
        fields["s_r"][idx] = p.get("s_radial", 0)
        fields["s_hoop"][idx] = p.get("s_hoop", 0)
        fields["s_axial"][idx] = p.get("s_axial", 0)
        fields["sf"][idx] = p.get("sf", 1.0)

    indices = [id_to_idx[n] for face in boundary for n in face]

    gcfg = cfg["geometry"]
    vmin_vmax = {}
    for k, arr in fields.items():
        finite = [v for v in arr if math.isfinite(v)]
        vmin_vmax[k] = {"min": min(finite) if finite else 0, "max": max(finite) if finite else 0}

    out = {
        "meta": {
            "job": job_dir.name,
            "sector_deg": float(gcfg["sector_deg"]),
            "theta_low_deg": float(gcfg["theta_low_deg"]),
            "z_half": float(gcfg["z_half_mm"]),
            "n_sectors": int(gcfg["n_slots"]),
            "ranges": vmin_vmax,
        },
        "positions": positions,
        "indices": indices,
        "fields": fields,
    }
    sp = job_dir / "sector_surface.json"
    sp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    kb = sp.stat().st_size / 1024
    print(f"[post] sector_surface.json: {n_surf} 表面节点, {len(boundary)} 三角面, {kb:.0f} KB → {sp}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--job", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    job_dir = Path(args.job)
    post(cfg, job_dir)
