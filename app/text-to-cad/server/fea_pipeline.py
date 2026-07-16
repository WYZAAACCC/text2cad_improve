"""FEA pipeline — template listing, execution, region definitions, LLM interaction."""
from __future__ import annotations

import json
import sys
import threading
import time as _time
import traceback
import uuid
from pathlib import Path

_BACKEND_SRC = Path(__file__).resolve().parents[3] / "integrations" / "engineering_tools" / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))


# ── Template listing ────────────────────────────────────────────────────────

def list_fea_templates() -> list[dict]:
    """Return all available ANSYS template schemas."""
    from seekflow_engineering_tools.ansys.apdl_templates import list_templates
    from seekflow_engineering_tools.ansys.template_registry import ANSYS_TEMPLATE_SCHEMAS

    result = []
    for name in sorted(list_templates()):
        schema = ANSYS_TEMPLATE_SCHEMAS.get(name, {})
        result.append({
            "name": name,
            "analysis_type": schema.get("analysis_type", "unknown"),
            "units": schema.get("units", ""),
            "parameters": schema.get("parameters", {}),
            "metrics": schema.get("metrics", []),
        })
    return result


# ── Direct execution ────────────────────────────────────────────────────────

def execute_fea_template(
    template_name: str,
    parameters: dict,
    jobname: str,
    task_store: dict,
    task_id: str,
    lock: threading.Lock | None = None,
    ansys_exe: Path | None = None,
    workspace_root: Path | None = None,
    default_timeout_s: int = 600,
) -> None:
    """Run an ANSYS APDL template in a background thread.

    Updates *task_store[task_id]* as the job progresses.
    When *lock* is provided, all writes to *task_store* are guarded.
    """
    def _update(updates: dict) -> None:
        if lock:
            with lock:
                task_store[task_id].update(updates)
        else:
            task_store[task_id].update(updates)

    _update({"task_id": task_id, "status": "processing", "progress": 10,
             "result": None, "error": None})

    try:
        from seekflow_engineering_tools.ansys.template_registry import (
            ANSYS_TEMPLATE_SCHEMAS,
            validate_template_parameters,
        )
        from seekflow_engineering_tools.ansys.apdl_templates import render_template
        from seekflow_engineering_tools.ansys.apdl_runner import AnsysAPDLRunner
        from seekflow_engineering_tools.ansys.parsers import parse_result_summary
        from seekflow_engineering_tools.common.validation import sanitise_jobname

        # ── Validate parameters ──
        schema = ANSYS_TEMPLATE_SCHEMAS.get(template_name)
        if schema is None:
            _update({
                "status": "failed", "progress": 0,
                "error": f"Unknown template: {template_name}. Available: {list(ANSYS_TEMPLATE_SCHEMAS.keys())}",
            })
            return

        try:
            validated = validate_template_parameters(template_name, parameters)
        except (ValueError, KeyError, TypeError) as exc:
            _update({
                "status": "failed", "progress": 0,
                "error": f"Parameter validation failed: {exc}",
            })
            return

        _update({"progress": 30})

        # ── Enrich with geometry estimated from latest CAD metadata ──
        if template_name == "turbine_disc_rotational_thermal":
            geo_params = _estimate_disc_geometry_from_metadata()
            if geo_params:
                # Only fill in geometry params that the user didn't explicitly set
                for k, v in geo_params.items():
                    if k not in parameters:
                        validated[k] = v

        # ── Generate APDL ──
        try:
            apdl_text = render_template(template_name, **validated)
        except Exception as exc:
            _update({
                "status": "failed", "progress": 0,
                "error": f"APDL generation failed: {exc}",
            })
            return

        # ── Setup workspace ──
        safe_jobname = sanitise_jobname(jobname) or f"fea_{task_id[:8]}"
        if workspace_root is None:
            workspace_root = Path(__file__).resolve().parent / "output" / "fea_jobs"
        job_dir = workspace_root / safe_jobname
        job_dir.mkdir(parents=True, exist_ok=True)

        inp_path = job_dir / f"{safe_jobname}.inp"
        inp_path.write_text(apdl_text, encoding="utf-8")

        _update({"progress": 50})

        # ── Resolve ANSYS executable ──
        if ansys_exe is None:
            import os
            env_exe = os.environ.get("ANSYS181_EXE", "")
            if env_exe:
                ansys_exe = Path(env_exe)
            else:
                # Try default locations
                candidates = [
                    Path(r"D:\ANSYS181\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"),
                    Path(r"C:\Program Files\ANSYS Inc\v181\ansys\bin\winx64\ansys181.exe"),
                ]
                for c in candidates:
                    if c.exists():
                        ansys_exe = c
                        break

        if ansys_exe is None or not ansys_exe.exists():
            _update({
                "status": "failed", "progress": 0,
                "error": "ANSYS executable not found. Set ANSYS181_EXE env var.",
            })
            return

        # ── Run ANSYS ──
        _update({"progress": 60})
        runner = AnsysAPDLRunner(
            ansys_exe=ansys_exe,
            workspace_root=workspace_root,
            default_timeout_s=default_timeout_s,
        )
        run_result = runner.run_apdl_file(
            input_file=inp_path,
            job_dir=job_dir,
            jobname=safe_jobname,
            timeout_s=default_timeout_s,
        )

        _update({"progress": 85})

        # ── Parse results ──
        warnings_list: list[str] = []
        if run_result.get("has_warning"):
            warnings_list.append("ANSYS output contains WARNING messages.")

        metrics: dict = {}
        summary_path = job_dir / "result_summary.txt"
        if summary_path.exists():
            metrics = parse_result_summary(summary_path)
            # Also try parsing the .out file for additional metrics
            from seekflow_engineering_tools.ansys.parsers import parse_result_summary as prs2
            out_metrics = prs2(Path(run_result["output_file"]))
            for k, v in out_metrics.items():
                if k not in metrics:
                    metrics[k] = v

        # ── Parse stress field ──
        stress_field = None
        nodal_path = job_dir / "nodal_stress.csv"
        if nodal_path.exists():
            from seekflow_engineering_tools.ansys.parsers import parse_nodal_stress
            sf = parse_nodal_stress(nodal_path)
            if sf:
                stress_field = sf[:5000]  # limit to 5000 points

        # ── Build result ──
        has_error = run_result.get("has_error", False)
        ok = (not has_error)

        if has_error:
            error_msg = "ANSYS reported errors."
            out_tail = run_result.get("out_tail", "")
            if out_tail:
                # Extract the first meaningful error line
                for line in out_tail.split("\n"):
                    if "*** ERROR ***" in line:
                        error_msg = f"ANSYS error: {line.strip()}"
                        break

            _update({
                "status": "completed", "progress": 100,
                "result": {
                    "task_id": task_id,
                    "ok": False,
                    "template_name": template_name,
                    "elapsed_s": run_result.get("elapsed_s", 0),
                    "message": "FEA failed. See error for details.",
                    "metrics": metrics,
                    "warnings": warnings_list,
                    "files_created": [str(inp_path), run_result.get("output_file", "")],
                    "log_path": run_result.get("output_file", ""),
                    "error": error_msg,
                },
            })
            return

        _update({
            "status": "completed", "progress": 100,
            "result": {
                "task_id": task_id,
                "ok": ok,
                "template_name": template_name,
                "elapsed_s": run_result.get("elapsed_s", 0),
                "message": "FEA completed successfully.",
                "metrics": metrics,
                "warnings": warnings_list,
                "files_created": [str(inp_path), run_result.get("output_file", ""),
                                  str(summary_path) if summary_path.exists() else ""],
                "log_path": run_result.get("output_file", ""),
                "error": None,
                "stress_field": stress_field,
            },
        })

    except Exception as exc:
        tb = traceback.format_exc()
        _update({
            "status": "failed", "progress": 0,
            "error": f"{exc}\n{tb[-2000:]}",
        })


# ── Geometry estimation from CAD metadata ──────────────────────────────────

def _estimate_disc_geometry_from_metadata(out_root: Path | None = None) -> dict:
    """Estimate turbine disc geometry parameters from latest CAD metadata.

    Reads bbox from the newest output.metadata.json and derives
    approximate bore/hub/web/rim dimensions using standard ratios.
    Returns an empty dict when no metadata is available (template
    defaults apply).
    """
    import json as _json

    if out_root is None:
        out_root = Path(__file__).resolve().parent / "output"

    if not out_root.exists():
        return {}

    candidates = sorted(
        out_root.glob("*/output.metadata.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for meta_path in candidates:
        try:
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
            gp = meta.get("validation", {}).get("geometry_postcheck", {})
            bbox = gp.get("bbox_mm")
            if bbox and len(bbox) >= 3 and all(d > 0 for d in bbox):
                rim_r = bbox[0] / 2.0
                thickness = bbox[2]
                half_z = thickness / 2.0
                return {
                    "bore_r_mm": round(rim_r * 0.24, 1),
                    "hub_r_mm": round(rim_r * 0.48, 1),
                    "web_r1_mm": round(rim_r * 0.48, 1),
                    "web_r2_mm": round(rim_r * 0.86, 1),
                    "rim_r_mm": round(rim_r, 1),
                    "hub_half_z_mm": round(half_z, 1),
                    "web_half_z1_mm": round(half_z * 0.58, 1),
                    "web_half_z2_mm": round(half_z * 0.39, 1),
                    "rim_half_z_mm": round(half_z * 0.79, 1),
                }
        except Exception:
            continue
    return {}


# ── Region definitions ──────────────────────────────────────────────────────

def compute_disc_regions(metadata: dict) -> list[dict]:
    """Compute named geometric regions from turbine disc metadata.

    The disc is axisymmetric about Z, so every face is defined by (R, Z) bounds.
    """
    regions = []

    # Extract key dimensions from metadata or use defaults
    gp = metadata.get("validation", {}).get("geometry_postcheck", {})
    bbox = gp.get("bbox_mm", [500, 500, 76])
    disc_diameter = bbox[0]      # 500
    disc_thickness = bbox[2]     # 76
    half_z = disc_thickness / 2  # 38

    # Bore face (cylindrical, R=60, Z∈[-38, 38])
    regions.append({
        "region_id": "bore_face",
        "region_type": "cylindrical",
        "label_cn": "中心孔面 (Bore, R=60mm)",
        "label_en": "Bore Face",
        "r_mm": 60.0, "r_tolerance": 2.0,
        "z_min": -half_z, "z_max": half_z,
        "color": "#00ff88",
    })

    # Rim face (cylindrical, R=250, Z∈[-30, 30])
    regions.append({
        "region_id": "rim_face",
        "region_type": "cylindrical",
        "label_cn": "轮缘面 (Rim, R=250mm)",
        "label_en": "Rim Face",
        "r_mm": 250.0, "r_tolerance": 2.0,
        "z_min": -30.0, "z_max": 30.0,
        "color": "#ff8800",
    })

    # Hub front face (planar, Z=+38, R∈[60,120])
    regions.append({
        "region_id": "hub_front_face",
        "region_type": "planar",
        "label_cn": "轮毂前端面 (Hub Front, Z=+38mm)",
        "label_en": "Hub Front Face",
        "z_mm": half_z,
        "r_min": 60.0, "r_max": 120.0,
        "color": "#4488ff",
    })

    # Hub rear face (planar, Z=-38, R∈[60,120])
    regions.append({
        "region_id": "hub_rear_face",
        "region_type": "planar",
        "label_cn": "轮毂后端面 (Hub Rear, Z=-38mm)",
        "label_en": "Hub Rear Face",
        "z_mm": -half_z,
        "r_min": 60.0, "r_max": 120.0,
        "color": "#8844ff",
    })

    # Web surface (conical) — both +Z and -Z sides
    regions.append({
        "region_id": "web_top_surface",
        "region_type": "conical",
        "label_cn": "腹板上表面 (Web Top, Z>0)",
        "label_en": "Web Top Surface",
        "r_min": 120.0, "r_max": 215.0,
        "z_min": 15.0, "z_max": 22.0,
        "color": "#ff44aa",
    })
    regions.append({
        "region_id": "web_bottom_surface",
        "region_type": "conical",
        "label_cn": "腹板下表面 (Web Bottom, Z<0)",
        "label_en": "Web Bottom Surface",
        "r_min": 120.0, "r_max": 215.0,
        "z_min": -22.0, "z_max": -15.0,
        "color": "#ff44aa",
    })

    # Rotation axis (always Z-axis for this disc)
    regions.append({
        "region_id": "rotation_axis",
        "region_type": "axis",
        "label_cn": "旋转轴 (Z轴, 自动识别)",
        "label_en": "Rotation Axis (Z)",
        "origin": [0.0, 0.0, 0.0],
        "direction": [0.0, 0.0, 1.0],
        "color": "#ff0000",
    })

    # Midplane (Z=0, symmetry plane)
    regions.append({
        "region_id": "midplane",
        "region_type": "plane",
        "label_cn": "中面 (Z=0, 对称面)",
        "label_en": "Midplane (Z=0)",
        "normal": [0.0, 0.0, 1.0],
        "origin": [0.0, 0.0, 0.0],
        "color": "#00aaff",
    })

    return regions
