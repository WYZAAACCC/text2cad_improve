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
            step_creator.Commit()
            step_creator.Destroy()
            if not out_step_path.exists() or out_step_path.stat().st_size == 0:
                raise RuntimeError("STEP export produced empty or missing file: {}".format(out_step_path))
            files_created.append(str(out_step_path))
        except Exception as exc:
            return {
                "files_created": files_created,
                "metrics": {
                    "length_mm": length_mm,
                    "width_mm": width_mm,
                    "height_mm": height_mm,
                },
                "error": "STEP export failed: {}".format(exc),
            }

    return {
        "ok": True,
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
    step_creator.Commit()
    step_creator.Destroy()
    out_step_path = Path(out_step)
    if not out_step_path.exists() or out_step_path.stat().st_size == 0:
        return {
            "ok": False,
            "files_created": [],
            "metrics": {},
            "error": "STEP export produced empty or missing file: {}".format(out_step),
        }

    return {
        "ok": True,
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

    files_created = [str(out_p)]

    out_step = params.get("out_step")
    if out_step:
        out_step_path = Path(out_step)
        out_step_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            dex_mgr = NXOpen.DexManager(session)
            step_creator = dex_mgr.CreateStep214Creator()
            step_creator.ExportFrom = NXOpen.Step214CreatorExportFromOption.DisplayPart
            step_creator.OutputFile = str(out_step_path)
            step_creator.Commit()
            step_creator.Destroy()
            if not out_step_path.exists() or out_step_path.stat().st_size == 0:
                raise RuntimeError("STEP export produced empty or missing file: {}".format(out_step_path))
            files_created.append(str(out_step_path))
        except Exception as exc:
            return {
                "ok": False,
                "files_created": files_created,
                "metrics": {
                    "length_mm": length_mm, "width_mm": width_mm,
                    "height_mm": height_mm, "hole_dia_mm": hole_dia_mm,
                },
                "error": "STEP export failed: {}".format(exc),
            }

    return {
        "ok": True,
        "files_created": files_created,
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
    files_created = [out_prt]

    out_step = params.get("out_step")
    if out_step:
        try:
            out_step_path = Path(out_step)
            out_step_path.parent.mkdir(parents=True, exist_ok=True)
            dex_mgr = NXOpen.DexManager(session)
            step_creator = dex_mgr.CreateStep214Creator()
            step_creator.ExportFrom = NXOpen.Step214CreatorExportFromOption.DisplayPart
            step_creator.OutputFile = str(out_step_path)
            step_creator.Commit()
            step_creator.Destroy()
            if not out_step_path.exists() or out_step_path.stat().st_size == 0:
                raise RuntimeError("STEP export produced empty or missing file: {}".format(out_step_path))
            files_created.append(str(out_step_path))
        except Exception as exc:
            return {
                "ok": False,
                "files_created": files_created,
                "metrics": {"type": "l_bracket"},
                "error": "STEP export failed: {}".format(exc),
            }

    return {"ok": True, "files_created": files_created, "metrics": {"type": "l_bracket"}}


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
    files_created = [out_prt]

    out_step = params.get("out_step")
    if out_step:
        try:
            out_step_path = Path(out_step)
            out_step_path.parent.mkdir(parents=True, exist_ok=True)
            dex_mgr = NXOpen.DexManager(session)
            step_creator = dex_mgr.CreateStep214Creator()
            step_creator.ExportFrom = NXOpen.Step214CreatorExportFromOption.DisplayPart
            step_creator.OutputFile = str(out_step_path)
            step_creator.Commit()
            step_creator.Destroy()
            if not out_step_path.exists() or out_step_path.stat().st_size == 0:
                raise RuntimeError("STEP export produced empty or missing file: {}".format(out_step_path))
            files_created.append(str(out_step_path))
        except Exception as exc:
            return {
                "ok": False,
                "files_created": files_created,
                "metrics": {"type": "stepped_block"},
                "error": "STEP export failed: {}".format(exc),
            }

    return {"ok": True, "files_created": files_created, "metrics": {"type": "stepped_block"}}


def _save_part(work_part, out_prt):
    # type: (object, str) -> None
    from pathlib import Path
    p = Path(out_prt); p.parent.mkdir(parents=True, exist_ok=True)
    try: __import__("os").remove(str(p))
    except: pass
    work_part.SaveAs(str(p))


def import_step_as_prt(session, params):
    # type: (object, dict) -> dict
    """Import a canonical STEP file and save as native NX PRT.

    This is the canonical path for engineering primitives on NX.
    NEVER generate involute curves in NXOpen — only import STEP.
    """
    input_step = params["input_step"]
    out_prt = params["out_prt"]
    out_step = params.get("out_step")

    step_path = Path(input_step)
    if not step_path.exists() or step_path.stat().st_size == 0:
        return {
            "ok": False,
            "files_created": [],
            "metrics": {},
            "error": "Canonical STEP not found or empty: {}".format(input_step),
        }

    # NXOpen: import STEP via DexManager Importer
    work_part = session.Parts.Work
    if work_part is None:
        work_part = session.Parts.NewDisplay("Millimeters", NXOpen.Part.Units.Millimeters)

    try:
        dex_mgr = NXOpen.DexManager(session)
        importer = dex_mgr.CreateStep214Importer()
        importer.InputFile = str(step_path)
        importer.OutputFile = str(out_prt) if out_prt else None
        importer.Commit()
        importer.Destroy()
    except Exception as exc:
        return {
            "ok": False,
            "files_created": [],
            "metrics": {},
            "error": "NX STEP import failed: {}".format(exc),
        }

    out_prt_path = Path(out_prt)
    out_prt_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing file if any to avoid SaveAs conflict
    try:
        __import__("os").remove(str(out_prt_path))
    except Exception:
        pass

    work_part.SaveAs(str(out_prt_path))

    if not out_prt_path.exists() or out_prt_path.stat().st_size == 0:
        return {
            "ok": False,
            "files_created": [],
            "metrics": {},
            "error": "NX PRT was not created after STEP import: {}".format(out_prt),
        }

    files_created = [str(out_prt_path)]

    warnings = [
        "Native PRT created by importing canonical STEP; "
        "NX feature tree is not regenerated."
    ]

    return {
        "ok": True,
        "message": "NX PRT created by importing canonical STEP.",
        "files_created": files_created,
        "metrics": {
            "strategy": "cadquery_step_import",
            "source_step": str(input_step),
            "native_path": str(out_prt_path),
        },
        "warnings": warnings,
    }


ACTION_HANDLERS = {
    "create_block_part": create_block_part,
    "create_block_with_hole": create_block_with_hole,
    "create_l_bracket": create_l_bracket,
    "create_stepped_block": create_stepped_block,
    "export_step": export_step,
    "import_step_as_prt": import_step_as_prt,
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

        handler_ok = result_payload.get("ok")
        if handler_ok is None:
            handler_ok = False  # fail-closed: handler must explicitly return ok=True
        error_msg = result_payload.get("error")

        result = {
            "job_id": job_id,
            "ok": bool(handler_ok) and error_msg is None,
            "message": "NX job finished." if handler_ok else error_msg or "NX job reported failure.",
            "files_created": result_payload.get("files_created", []),
            "metrics": result_payload.get("metrics", {}),
            "error": error_msg,
        }
        if result["ok"]:
            write_result(DONE, job_id, result)
        else:
            write_result(FAILED, job_id, result)

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


# ── Heartbeat ──────────────────────────────────────────────────────────────


def write_heartbeat(session):
    # type: (object) -> None
    payload = {
        "time_epoch": time.time(),
        "time_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "nx_version": str(session.GetEnvironmentVariableValue("UGII_VERSION"))
        if hasattr(session, "GetEnvironmentVariableValue")
        else "12.0",
        "job_root": str(JOB_ROOT),
    }
    (RUNNING / "heartbeat.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


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

    last_heartbeat = 0.0
    HEARTBEAT_INTERVAL_S = 5.0

    try:
        while True:
            stop_file = JOB_ROOT / "STOP"
            if stop_file.exists():
                lw.WriteLine("SeekFlow NX Bridge stopped by STOP file.")
                break

            # Write heartbeat every 5 seconds
            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                try:
                    write_heartbeat(session)
                    last_heartbeat = time.time()
                except Exception:
                    pass

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
