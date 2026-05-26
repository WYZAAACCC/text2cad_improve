# nx_bridge_bootstrap.py
# ============================================================================
# This file is intended to run **inside Siemens NX 12.0+** as an NXOpen Python
# Journal.  Do NOT run it from a system terminal — it imports NXOpen, which
# is only available inside an NX session.
#
# Usage:
#   1. Open NX 12.0.
#   2. Developer tab → Journal → Play → select this file.
#   3. The bridge watches <NX_JOB_ROOT>/pending/ and processes jobs.
#   4. Create <NX_JOB_ROOT>/STOP (or close NX) to stop the bridge.
#
# Environment variables:
#   NX_JOB_ROOT   — root directory for job queue (default: see below)
#
# Python version: NX 12.0 = Python 3.6  → no __future__.annotations
# ============================================================================

import json
import os
import shutil
import time
import traceback
from pathlib import Path

try:
    import NXOpen
    import NXOpen.Features
except ImportError:
    NXOpen = None  # NX 12.0 journal runner auto-resolves this


# ── Configuration ──────────────────────────────────────────────────────────

JOB_ROOT = Path(
    os.environ.get(
        "NX_JOB_ROOT",
        str(Path.home() / "seekflow_workspace" / "nx_jobs"),
    )
)
PENDING = JOB_ROOT / "pending"
RUNNING = JOB_ROOT / "running"
DONE = JOB_ROOT / "done"
FAILED = JOB_ROOT / "failed"

POLL_INTERVAL_S = 1.0


# ── Helpers ────────────────────────────────────────────────────────────────


def ensure_dirs():
    # type: () -> None
    for d in [PENDING, RUNNING, DONE, FAILED]:
        d.mkdir(parents=True, exist_ok=True)


def write_result(directory, job_id, result):
    # type: (Path, str, dict) -> None
    out_path = directory / "{}.result.json".format(job_id)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Action handlers ────────────────────────────────────────────────────────


def create_block_part(session, params):
    # type: (object, dict) -> dict
    length_mm = float(params["length_mm"])
    width_mm = float(params["width_mm"])
    height_mm = float(params["height_mm"])
    out_prt = params["out_prt"]
    out_step = params.get("out_step")

    # Get or create the work part
    work_part = session.Parts.Work
    if work_part is None:
        work_part = session.Parts.NewDisplay(
            "Millimeters",
            NXOpen.Part.Units.Millimeters,
        )

    # NX 12.0: Create a block via BlockFeatureBuilder.
    # Reference: NXOpen SDK sample ColoredBlock.py
    #   → NXOpen.Features.Feature.Null (NOT Python None)
    #   → SetOriginAndLengths takes str params
    null_features_feature = NXOpen.Features.Feature.Null
    bfb = work_part.Features.CreateBlockFeatureBuilder(null_features_feature)
    origin = NXOpen.Point3d(0.0, 0.0, 0.0)
    bfb.SetOriginAndLengths(
        origin,
        str(length_mm), str(height_mm), str(width_mm),
    )
    feature1 = bfb.CommitFeature()
    bfb.Destroy()

    files_created = []  # type: list

    # Save .prt
    out_prt_path = Path(out_prt)
    out_prt_path.parent.mkdir(parents=True, exist_ok=True)
    work_part.SaveAs(str(out_prt_path))
    files_created.append(str(out_prt_path))

    # Export STEP if requested (NX 12.0: via DexManager)
    if out_step:
        out_step_path = Path(out_step)
        out_step_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            dex_mgr = NXOpen.DexManager(session)
            step_creator = dex_mgr.CreateStep214Creator()
            step_creator.ExportFrom = NXOpen.Step214CreatorExportFromOption.DisplayPart
            step_creator.OutputFile = str(out_step_path)
            step_creator.InputFile = str(out_step_path)
            step_creator.Commit()
            step_creator.Destroy()
            files_created.append(str(out_step_path))
        except Exception:
            pass  # STEP translator requires license/configuration

    return {
        "files_created": files_created,
        "metrics": {
            "length_mm": length_mm,
            "width_mm": width_mm,
            "height_mm": height_mm,
        },
    }


def export_step(session, params):
    # type: (object, dict) -> dict
    input_prt = params["input_prt"]
    out_step = params["out_step"]

    work_part = session.Parts.OpenBase(input_prt)

    dex_mgr = NXOpen.DexManager(session)
    step_creator = dex_mgr.CreateStep214Creator()
    step_creator.ExportFrom = NXOpen.Step214CreatorExportFromOption.DisplayPart
    step_creator.OutputFile = out_step
    step_creator.InputFile = out_step
    step_creator.Commit()
    step_creator.Destroy()

    return {
        "files_created": [out_step],
        "metrics": {},
    }


# ── Action registry ───────────────────────────────────────────────────────

def create_block_with_hole(session, params):
    # type: (object, dict) -> dict
    """Create a block with a through-hole via boolean subtract."""

    length_mm = float(params["length_mm"])
    width_mm = float(params["width_mm"])
    height_mm = float(params["height_mm"])
    hole_dia_mm = float(params.get("hole_dia_mm", 16))
    hole_x = float(params.get("hole_x", length_mm / 2.0))
    hole_z = float(params.get("hole_z", width_mm / 2.0))
    out_prt = params["out_prt"]

    work_part = session.Parts.Work
    if work_part is None:
        work_part = session.Parts.NewDisplay(
            "Millimeters", NXOpen.Part.Units.Millimeters,
        )

    # Create block
    null_ft = NXOpen.Features.Feature.Null
    bfb = work_part.Features.CreateBlockFeatureBuilder(null_ft)
    bfb.SetOriginAndLengths(
        NXOpen.Point3d(0.0, 0.0, 0.0),
        str(length_mm), str(height_mm), str(width_mm),
    )
    target = bfb.CommitFeature()
    bfb.Destroy()

    # Create cylinder tool (hole along Y axis, through the block)
    # Block is: X=[0,length], Y=[0,height], Z=[0,width]
    # Hole center at (hole_x, height_mm/2, hole_z), axis along Y
    cfb = work_part.Features.CreateCylinderBuilder(null_ft)
    cfb.Origin = NXOpen.Point3d(hole_x, -1.0, hole_z)
    cfb.Direction = NXOpen.Vector3d(0.0, 1.0, 0.0)
    cfb.Diameter.RightHandSide = str(hole_dia_mm)
    cfb.Height.RightHandSide = str(height_mm + 2.0)
    tool = cfb.CommitFeature()
    cfb.Destroy()

    # Boolean subtract
    tb = target.GetBodies()
    cb = tool.GetBodies()
    work_part.Features.CreateSubtractFeature(tb[0], False, cb, False, False)

    # Save
    from pathlib import Path
    out_p = Path(out_prt)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    work_part.SaveAs(str(out_p))

    return {
        "files_created": [str(out_p)],
        "metrics": {
            "length_mm": length_mm, "width_mm": width_mm,
            "height_mm": height_mm, "hole_dia_mm": hole_dia_mm,
        },
    }


def create_l_bracket(session, params):
    # type: (object, dict) -> dict
    """L-bracket: two perpendicular blocks united."""
    base_l = float(params.get("base_length", 100))
    base_w = float(params.get("base_width", 60))
    base_t = float(params.get("thickness", 15))
    leg_h = float(params.get("leg_height", 60))
    out_prt = params["out_prt"]

    work_part = session.Parts.Work
    if work_part is None:
        work_part = session.Parts.NewDisplay("Millimeters", NXOpen.Part.Units.Millimeters)
    nf = NXOpen.Features.Feature.Null

    bfb = work_part.Features.CreateBlockFeatureBuilder(nf)
    bfb.SetOriginAndLengths(NXOpen.Point3d(0.0,0.0,0.0), str(base_l), str(base_t), str(base_w))
    base = bfb.CommitFeature(); bfb.Destroy()

    bfb2 = work_part.Features.CreateBlockFeatureBuilder(nf)
    bfb2.SetOriginAndLengths(NXOpen.Point3d(0.0,0.0,0.0), str(base_t), str(leg_h), str(base_w))
    leg = bfb2.CommitFeature(); bfb2.Destroy()

    work_part.Features.CreateUniteFeature(
        base.GetBodies()[0], False, [leg.GetBodies()[0]], False, False)

    _save_part(work_part, out_prt)
    return {"files_created": [out_prt], "metrics": {"type": "l_bracket"}}


def create_stepped_block(session, params):
    # type: (object, dict) -> dict
    """Stepped block: large base + smaller upper block united."""
    base_l = float(params.get("base_length", 80))
    base_w = float(params.get("base_width", 80))
    base_h = float(params.get("base_height", 20))
    top_l = float(params.get("top_length", 60))
    top_w = float(params.get("top_width", 60))
    top_h = float(params.get("top_height", 30))
    out_prt = params["out_prt"]

    work_part = session.Parts.Work
    if work_part is None:
        work_part = session.Parts.NewDisplay("Millimeters", NXOpen.Part.Units.Millimeters)
    nf = NXOpen.Features.Feature.Null

    bfb = work_part.Features.CreateBlockFeatureBuilder(nf)
    bfb.SetOriginAndLengths(NXOpen.Point3d(0.0,0.0,0.0), str(base_l), str(base_h), str(base_w))
    b1 = bfb.CommitFeature(); bfb.Destroy()

    bfb2 = work_part.Features.CreateBlockFeatureBuilder(nf)
    bfb2.SetOriginAndLengths(
        NXOpen.Point3d(float((base_l-top_l)/2.0), float(base_h), float((base_w-top_w)/2.0)),
        str(top_l), str(top_h), str(top_w))
    b2 = bfb2.CommitFeature(); bfb2.Destroy()

    work_part.Features.CreateUniteFeature(
        b1.GetBodies()[0], False, [b2.GetBodies()[0]], False, False)

    _save_part(work_part, out_prt)
    return {"files_created": [out_prt], "metrics": {"type": "stepped_block"}}


def _save_part(work_part, out_prt):
    # type: (object, str) -> None
    from pathlib import Path
    p = Path(out_prt); p.parent.mkdir(parents=True, exist_ok=True)
    try: __import__("os").remove(str(p))
    except: pass
    work_part.SaveAs(str(p))


ACTION_HANDLERS = {
    "create_block_part": create_block_part,
    "create_block_with_hole": create_block_with_hole,
    "create_l_bracket": create_l_bracket,
    "create_stepped_block": create_stepped_block,
    "export_step": export_step,
}


# ── Job processor ─────────────────────────────────────────────────────────


def process_one_job(session, job_file):
    # type: (object, Path) -> None
    basename = job_file.name
    running_file = RUNNING / basename

    shutil.move(str(job_file), str(running_file))

    with open(str(running_file), "r", encoding="utf-8") as fh:
        job = json.load(fh)

    job_id = job["job_id"]
    action = job["action"]
    params = job.get("params", {})

    try:
        if action not in ACTION_HANDLERS:
            raise ValueError("Unknown NX action: {}".format(action))

        result_payload = ACTION_HANDLERS[action](session, params)

        result = {
            "job_id": job_id,
            "ok": True,
            "message": "NX job finished.",
            "files_created": result_payload.get("files_created", []),
            "metrics": result_payload.get("metrics", {}),
            "error": None,
        }
        write_result(DONE, job_id, result)

    except Exception as exc:
        result = {
            "job_id": job_id,
            "ok": False,
            "message": "NX job failed.",
            "files_created": [],
            "metrics": {},
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_result(FAILED, job_id, result)

    finally:
        try:
            os.remove(str(running_file))
        except OSError:
            pass


# ── Main loop ─────────────────────────────────────────────────────────────


def main():
    # type: () -> None
    if NXOpen is None:
        raise RuntimeError(
            "NXOpen is not available. This script must run inside NX as a Journal."
        )

    ensure_dirs()

    session = NXOpen.Session.GetSession()
    lw = session.ListingWindow
    lw.Open()
    lw.WriteLine("SeekFlow NX Bridge started (NX 12.0).")
    lw.WriteLine("Watching: {}".format(JOB_ROOT))

    try:
        while True:
            stop_file = JOB_ROOT / "STOP"
            if stop_file.exists():
                lw.WriteLine("SeekFlow NX Bridge stopped by STOP file.")
                break

            jobs = sorted(
                [f for f in PENDING.iterdir() if f.suffix == ".json"],
                key=lambda p: p.stat().st_ctime,
            )

            for job_file in jobs:
                lw.WriteLine("Processing NX job: {}".format(job_file.name))
                process_one_job(session, job_file)

            time.sleep(POLL_INTERVAL_S)

    except KeyboardInterrupt:
        lw.WriteLine("SeekFlow NX Bridge stopped by user.")

    lw.WriteLine("SeekFlow NX Bridge exited.")


if __name__ == "__main__":
    main()
