"""run3d.py — 涡轮盘三维 FEA 流水线 CLI 入口.

子命令:
  prepare   阶段1: gmsh 网格生成 (免费, ~2min)
  confirm   阶段2: 人工确认, 写 .confirmed 标记 (必须)
  solve     阶段3: ANSYS 批处理求解 (耗算力, ~1-3min)
  post      阶段4: 后处理 CSV→metrics (免费)
  full      一键 prepare→(提示 confirm)→solve→post

用法:
  python -m server.fea3d.run3d prepare --config server/fea3d/manual_config.json [--gui]
  python -m server.fea3d.run3d confirm  --config server/fea3d/manual_config.json --job <jobdir>
  python -m server.fea3d.run3d solve    --config server/fea3d/manual_config.json --job <jobdir>
  python -m server.fea3d.run3d post     --config server/fea3d/manual_config.json --job <jobdir>
  python -m server.fea3d.run3d full     --config server/fea3d/manual_config.json [--gui]
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, sys, time
from pathlib import Path

# Windows GBK 控制台打印 ✓/→ 等符号不再抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


# 项目根 = server/fea3d/ 的上两级的上级 ... 直接解决
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # server/
OUT_ROOT = PROJECT_ROOT / "output" / "fea3d_jobs"


def _hash_config(cfg: dict) -> str:
    return hashlib.sha256(
        json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def _ansys_exe(cfg: dict) -> Path:
    p = Path(cfg["solver"]["ansys_exe"])
    if not p.exists():
        raise FileNotFoundError(f"ANSYS 不存在: {p}")
    return p


def cmd_prepare(args):
    """阶段1: gmsh 网格生成."""
    from server.fea3d.mesh_sector import build as build_mesh

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    # 自动生成 jobname
    if not args.job:
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.job = f"disc3d_{ts}"

    job_dir = OUT_ROOT / args.job
    job_dir.mkdir(parents=True, exist_ok=True)
    cfg["_job_dir"] = str(job_dir)
    cfg["_config_hash"] = _hash_config(cfg)

    print(f"[run3d] 阶段1 prepare → {job_dir}")
    report = build_mesh(cfg, job_dir, gui=args.gui)

    # 验证断言
    a = report.get("asserts", {})
    if all(a.get(k, False) for k in ("low_eq_high_nodes", "has_sym_nodes", "has_bore_nodes")):
        print("[run3d] [OK] 所有断言通过, 网格准备完成")
        print(f"[run3d] → 请检查 {job_dir / 'mesh_report.json'} 中的边界面分类和配对距离")
        print(f"[run3d] → 确认 config 参数后运行:")
        print(f"  python -m server.fea3d.run3d confirm --config {args.config} --job {args.job}")
        print(f"  或 (推荐首次) 用 --gui 目检扇区几何和网格")
    else:
        print("[run3d] ✗ 断言失败:", a)
        sys.exit(1)


def cmd_confirm(args):
    """阶段2: 人工确认, 写入 .confirmed 标记."""
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    job_dir = OUT_ROOT / args.job

    if not job_dir.exists():
        raise FileNotFoundError(f"作业目录不存在: {job_dir} — 先运行 prepare")
    if not (job_dir / "mesh.inp").exists():
        raise FileNotFoundError(f"mesh.inp 不存在 — 先运行 prepare")

    # 打印 report 摘要
    report_path = job_dir / "mesh_report.json"
    if report_path.exists():
        r = json.loads(report_path.read_text(encoding="utf-8"))
        print(f"[run3d] 网格: {r['nodes']} 节点, {r['elements']} 单元")
        print(f"[run3d] 边界面: low={r['node_counts']['low_plane']} high={r['node_counts']['high_plane']} sym={r['node_counts']['sym_plane_z0']}")
        for p in r.get("periodic_pairs", []):
            print(f"  配对: low={p['low']} ↔ high={p['high']} dist={p['pair_dist_mm']:.3f}mm")

    # 几何比对
    g = cfg["geometry"]
    print(f"[run3d] 几何: bore={g['r_bore_mm']}mm outer={g['r_outer_mm']}mm z_half={g['z_half_mm']}mm slots={g['n_slots']}")
    print(f"[run3d] 载荷: rpm={cfg['load']['rpm']} T_bore={cfg['load']['t_bore_c']}°C T_rim={cfg['load']['t_rim_c']}°C")

    cfg_hash = _hash_config(cfg)
    confirmed = {"hash": cfg_hash, "confirmed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "config_file": str(Path(args.config).resolve())}
    (job_dir / ".confirmed").write_text(json.dumps(confirmed), encoding="utf-8")
    print(f"[run3d] ✓ 已确认 (hash={cfg_hash})")
    print(f"[run3d] → 运行: python -m server.fea3d.run3d solve --config {args.config} --job {args.job}")


def cmd_solve(args):
    """阶段3: 渲染 solve.inp + 调 ANSYS 求解."""
    from server.fea3d.apdl_template_3d import render as render_apdl

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    job_dir = OUT_ROOT / args.job

    # 校验确认标记
    confirm_file = job_dir / ".confirmed"
    if not confirm_file.exists():
        print("[run3d] ✗ 未确认! 请先运行 confirm 子命令", file=sys.stderr)
        sys.exit(1)
    confirmed = json.loads(confirm_file.read_text(encoding="utf-8"))
    cfg_hash = _hash_config(cfg)
    if confirmed["hash"] != cfg_hash:
        print(f"[run3d] ✗ config 已变更 (确认时={confirmed['hash']} 当前={cfg_hash})", file=sys.stderr)
        print("[run3d] → 请重新运行 confirm", file=sys.stderr)
        sys.exit(1)

    # 渲染 solve.inp
    solve_inp = render_apdl(cfg, job_dir)

    # 调 ANSYS
    ansys = _ansys_exe(cfg)
    sol = cfg["solver"]
    np_val = int(sol.get("np", 2))
    mem_mb = int(sol.get("memory_mb", 3000))
    timeout_s = int(sol.get("timeout_s", 1800))

    cmd = [
        str(ansys), "-b",
        "-np", str(np_val),
        "-m", str(mem_mb),
        "-i", str(solve_inp.name),
        "-o", "solve.out",
        "-j", "turbine3d",
    ]
    print(f"[run3d] 阶段3 solve: {' '.join(cmd)}")
    print(f"[run3d] cwd={job_dir}")

    try:
        result = subprocess.run(
            cmd, cwd=str(job_dir),
            capture_output=True, text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        print(f"[run3d] ✗ ANSYS 超时 ({timeout_s}s)", file=sys.stderr)
        sys.exit(1)

    out_file = job_dir / "solve.out"
    out_text = ""
    if out_file.exists():
        out_text = out_file.read_text(encoding="utf-8", errors="replace")

    has_error = "*** ERROR ***" in out_text or result.returncode != 0
    tail_stderr = result.stderr[-3000:] if result.stderr else ""

    if has_error:
        # 提取第一条 ERROR
        for line in out_text.splitlines():
            if "*** ERROR ***" in line:
                print(f"[run3d] ANSYS ERROR: {line.strip()}", file=sys.stderr)
                break
        if tail_stderr:
            print(f"[run3d] stderr 尾部:\n{tail_stderr}", file=sys.stderr)
        print(f"[run3d] 完整输出: {out_file}", file=sys.stderr)
        print("[run3d] ✗ solve 失败 (但输出文件仍可能部分可用)", file=sys.stderr)
        sys.exit(1)

    print("[run3d] ✓ solve 完成")
    print(f"[run3d] → 运行: python -m server.fea3d.run3d post --config {args.config} --job {args.job}")


def cmd_post(args):
    """阶段4: 后处理."""
    from server.fea3d.post3d import post as do_post

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    job_dir = OUT_ROOT / args.job

    metrics = do_post(cfg, job_dir)

    print(f"[run3d] 全场 max VM = {metrics['global']['max_von_mises_mpa']:.1f} MPa "
          f"({metrics['global']['max_vm_zone']}, r={metrics['global']['max_vm_location_r_mm']:.1f}mm)")
    print(f"[run3d] 全场 min SF = {metrics['global']['min_safety_factor']:.4f} "
          f"({metrics['global']['min_sf_zone']})")
    for zname, zi in metrics.get("zones", {}).items():
        if zi.get("node_count", 0) > 0:
            print(f"  [{zname}] max VM={zi['max_vm_mpa']:.1f} min SF={zi['min_sf']:.4f}")

    # 量级自查
    vm = metrics["global"]["max_von_mises_mpa"]
    if vm < 300 or vm > 1500:
        print(f"[run3d] ⚠ max VM={vm:.0f} MPa 偏离预期范围 [300,1500], 请检查!")
    else:
        print("[run3d] ✓ max VM 在预期范围 [300,1500] 内")

    # 检查结果文件是否存在
    csv_path = job_dir / "nodal_stress_3d.csv"
    if csv_path.exists():
        size_kb = csv_path.stat().st_size / 1024
        print(f"[run3d] nodal_stress_3d.csv = {size_kb:.0f} KB")


def cmd_full(args):
    """一键: prepare → (提示 confirm) → solve → post."""
    if not args.gui:
        # prepare
        print("=" * 50)
        print("[run3d] 阶段1: prepare")
        cmd_prepare(args)
        print()

    # 检查是否已确认
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    job_dir = OUT_ROOT / args.job
    confirm_file = job_dir / ".confirmed"
    if not confirm_file.exists():
        print("=" * 50)
        print("[run3d] 阶段2: 请先人工审阅 mesh_report.json, 确认无误后运行 confirm")
        if args.gui:
            print("[run3d] --gui 模式: 请先运行 prepare --gui 目检网格, 再 confirm")
        return

    # solve
    print("=" * 50)
    print("[run3d] 阶段3: solve")
    cmd_solve(args)
    print()

    # post
    print("=" * 50)
    print("[run3d] 阶段4: post")
    cmd_post(args)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="涡轮盘 3D FEA 流水线")
    sp = ap.add_subparsers(dest="cmd")

    for name in ("prepare", "confirm", "solve", "post", "full"):
        p = sp.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--job", default=None)
        if name in ("prepare", "full"):
            p.add_argument("--gui", action="store_true")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        sys.exit(1)

    if not args.job:
        ts = time.strftime("%Y%m%d_%H%M%S")
        args.job = f"disc3d_{ts}"

    {"prepare": cmd_prepare, "confirm": cmd_confirm, "solve": cmd_solve,
     "post": cmd_post, "full": cmd_full}[args.cmd](args)
