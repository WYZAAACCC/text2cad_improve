"""批量验证含榫槽族 pipeline（当前脚本）：build + 完整 pipeline + MCP gate。"""
import json, os, sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
# DEEPSEEK_API_KEY must be set in the environment.
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))
import main, param_templates
from design_families import DESIGN_FAMILIES, build_text

FAMILIES = ["D31", "D32"]

def run(fid):
    fam = DESIGN_FAMILIES[fid]
    f = fam.get("features") or {}
    params = {"category": fam["category"], "_tag": f"verify_{fid}",
              "od_mm": fam["od"], "bore_mm": fam["bore"], "thick_mm": fam["thick"],
              "hub_mm": fam["hub"], "rim_mm": fam["rim"],
              "slots": f.get("slots", 60), "teeth": f.get("teeth", 2), "R_mm": f.get("R", fam["od"]/2),
              "depth_mm": f.get("depth", 24), "throat_half_width_mm": f.get("throat", 4.0),
              "fr_mm": f.get("fr", 1.0), "form": fam.get("form", "standard"),
              "tfa_deg": 45.0, "ufa_deg": 75.0}
    _KEYMAP = {"pcd": "pcd_mm", "hdia": "hdia_mm", "gw": "gw_mm", "gd": "gd_mm",
               "lh_pcd": "lh_pcd_mm", "lh_hdia": "lh_hdia_mm",
               "cl_pcd": "cl_pcd_mm", "cl_hdia": "cl_hdia_mm", "cl_pcd2": "cl_pcd2_mm",
               "rs_depth": "rs_depth_mm", "rs_half_width": "rs_half_width_mm",
               "rim_arc_radius": "rim_arc_radius_mm", "cavity_width": "cavity_width_mm",
               "cavity_depth": "cavity_depth_mm"}
    for extra in ("holes","pcd","hdia","grooves","gw","gd","groove_type",
                  "rim_arc_radius","transition","lh_holes","lh_pcd","lh_hdia",
                  "cl_holes","cl_pcd","cl_hdia","cl_pcd2","rs_count","rs_depth","rs_half_width",
                  "cavity_width","cavity_depth"):
        if f.get(extra) is not None:
            params[_KEYMAP.get(extra, extra)] = f[extra]
    tid = f"verify_{fid}"
    doc = param_templates.build(params)
    out_dir = main.OUT_ROOT / tid
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "llm_raw.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.environ["TEMPLATE_L2"] = "1"
    text = build_text(fam)
    main._tasks[tid] = {"taskId": tid, "status": "pending", "progress": 0, "result": None, "error": None}
    main._run_pipeline(tid, text, force_route="generative_cad_ir")
    st = main._tasks[tid]
    log = out_dir / "pipeline_log.json"
    if log.exists():
        d = json.loads(log.read_text(encoding="utf-8"))
        s = d.get("stages") or {}
        mcp = s.get("mcp_gate")
        return fid, st.get("status"), mcp
    return fid, st.get("status"), d.get("error") if 'd' in dir() else None

def _already_done(fid: str) -> bool:
    return (main.OUT_ROOT / f"verify_{fid}" / "raw_fixed.json").exists()

def _exec_one(fid: str) -> tuple:
    try:
        fid, status, mcp = run(fid)
        mcp_str = mcp if mcp is not None else "no-log"
        print(f"[{fid}] status={status} mcp={mcp_str}", flush=True)
        return fid, status, mcp_str
    except Exception as e:
        print(f"[{fid}] EXC {type(e).__name__}: {str(e)[:120]}", flush=True)
        return fid, "exc", str(e)[:120]

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4, help="并发进程数（>1 用 mp.Pool）")
    args = ap.parse_args()

    pending = [f for f in FAMILIES if not _already_done(f)]
    print(f"18 族: 已跳过 {len(FAMILIES)-len(pending)}，待执行 {len(pending)}（并发 {args.workers}）", flush=True)
    if not pending:
        print("全部已完成")
    elif args.workers > 1 and len(pending) > 1:
        import multiprocessing as mp
        with mp.Pool(processes=args.workers) as pool:
            results = pool.map(_exec_one, pending)
        for fid, status, mcp in results:
            print(f"== {fid}: {status} {mcp}", flush=True)
    else:
        for fid in pending:
            _exec_one(fid)
