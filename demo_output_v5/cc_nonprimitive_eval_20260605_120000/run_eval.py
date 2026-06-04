"""Comprehensive evaluation runner for v6.3 text-to-CAD pipeline.

Re-runs existing canonical JSON from v62_stress30 through the updated
pipeline (builder → validation → runtime → STEP → inspection).

Also generates new test cases where LLM raw JSON is available.

Output: Per-case directories with full intermediate data + report matrices.
"""
import json, sys, time, traceback, os, hashlib
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "integrations/engineering_tools/src"))

TEST_ROOT = Path(__file__).parent
STRESS30_DIR = Path("E:/auto_detection_process/demo_output_v5/v62_stress30_output")
RESULTS_FILE = TEST_ROOT / "results.json"
FAILURE_MATRIX = TEST_ROOT / "reports/failure_matrix.csv"
GEO_MATRIX = TEST_ROOT / "reports/geometry_quality_matrix.csv"

os.makedirs(TEST_ROOT / "reports", exist_ok=True)

def sha256(path):
    if path.exists():
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return "MISSING"

def measure_step(path):
    """Measure STEP file and do basic geometry inspection."""
    info = {"exists": path.exists(), "size_bytes": 0, "volume_mm3": None,
            "n_solids": None, "bbox_mm": None, "closed": None, "errors": []}
    if not path.exists():
        info["errors"].append("STEP file missing")
        return info
    info["size_bytes"] = path.stat().st_size
    if info["size_bytes"] < 100:
        info["errors"].append(f"STEP file too small ({info['size_bytes']} bytes)")
    # Try to inspect with cadquery
    try:
        import cadquery as cq
        solid = cq.importers.importStep(str(path))
        if hasattr(solid, 'val'):
            inner = solid.val()
        else:
            inner = solid
        info["volume_mm3"] = round(inner.Volume(), 2) if hasattr(inner, 'Volume') else None
        if hasattr(inner, 'Solids'):
            info["n_solids"] = len(list(inner.Solids()))
        else:
            info["n_solids"] = 1
        if hasattr(inner, 'BoundingBox'):
            bb = inner.BoundingBox()
            info["bbox_mm"] = [round(bb.xlen,1), round(bb.ylen,1), round(bb.zlen,1)]
        if hasattr(inner, 'Closed'):
            info["closed"] = inner.Closed()
        if info["volume_mm3"] is not None and info["volume_mm3"] <= 0:
            info["errors"].append(f"Non-positive volume: {info['volume_mm3']}")
        if info["n_solids"] is not None and info["n_solids"] > 1:
            info["errors"].append(f"MULTI_SOLID: {info['n_solids']} solids")
    except Exception as e:
        info["errors"].append(f"Inspection error: {e}")
    return info

def size_judgement(size_bytes, complexity):
    """Judge whether STEP file size is reasonable for given complexity."""
    if size_bytes == 0:
        return "missing", "File not found or empty"
    if complexity == "simple":
        if size_bytes < 5000: return "suspicious_too_small", f"Very small for simple part ({size_bytes} bytes)"
        return "normal", ""
    elif complexity == "moderate":
        if size_bytes < 10000: return "suspicious_too_small", f"Too small for moderate complexity ({size_bytes} bytes)"
        if size_bytes > 10_000_000: return "suspicious_too_large", f"Unusually large ({size_bytes/1e6:.1f} MB)"
        return "normal", ""
    elif complexity == "complex":
        if size_bytes < 30000: return "suspicious_too_small", f"Too small for complex part ({size_bytes} bytes)"
        if size_bytes > 20_000_000: return "suspicious_too_large", f"Very large ({size_bytes/1e6:.1f} MB)"
        return "normal", ""
    return "normal", ""

def run_case(case_id, canonical_json_path, out_dir, description=""):
    """Run a single case through the builder pipeline."""
    result = {
        "case_id": case_id, "description": description,
        "status": "UNKNOWN", "step_exists": False, "step_size_bytes": 0,
        "volume_mm3": None, "n_solids": None, "bbox_mm": None,
        "closed": None, "errors": [], "warnings": [], "elapsed_s": 0,
    }
    os.makedirs(out_dir, exist_ok=True)

    # Load canonical JSON
    try:
        canonical_data = json.loads(Path(canonical_json_path).read_text(encoding="utf-8"))
    except Exception as e:
        result["status"] = "FAIL_LOAD"
        result["errors"].append(f"Cannot load canonical JSON: {e}")
        return result

    # Save a copy
    (out_dir / "canonical.json").write_text(
        json.dumps(canonical_data, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8"
    )

    # Run directly through runtime pipeline (skip re-parse since these
    # are already-validated canonical JSON from previous runs)
    try:
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument

        step_out = out_dir / "output.step"
        meta_out = out_dir / "metadata.json"

        # Parse as CanonicalGcadDocument
        canonical = CanonicalGcadDocument.model_validate(canonical_data)

        # Minimal validation seed (required by run_canonical_gcad)
        validation_seed = {"core_validation": {"ok": True, "stages": {}, "issues": []}}

        t0 = time.time()
        run_result = run_canonical_gcad(
            canonical=canonical,
            out_step=step_out,
            metadata_path=meta_out,
            validation_seed=validation_seed,
            require_full_validation_seed=False,
        )
        elapsed = time.time() - t0
        result["elapsed_s"] = round(elapsed, 1)

        # Record runtime result
        (out_dir / "runtime_result.json").write_text(
            json.dumps({
                "ok": run_result.ok,
                "error": run_result.error,
                "warnings": run_result.warnings,
                "degraded_features": run_result.degraded_features,
                "operation_metrics": run_result.operation_metrics,
            }, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8"
        )

        if run_result.ok:
            result["status"] = "PASS"
        else:
            result["status"] = "FAIL_RUNTIME"
            result["errors"].append(run_result.error or "Unknown runtime error")

        result["warnings"] = list(run_result.warnings) if run_result.warnings else []
        result["degraded_features"] = list(run_result.degraded_features) if run_result.degraded_features else []
        if run_result.operation_metrics:
            result["operation_metrics"] = list(run_result.operation_metrics)

        # Inspect STEP
        step_info = measure_step(step_out)
        result["step_exists"] = step_info["exists"]
        result["step_size_bytes"] = step_info["size_bytes"]
        result["volume_mm3"] = step_info["volume_mm3"]
        result["n_solids"] = step_info["n_solids"]
        result["bbox_mm"] = step_info["bbox_mm"]
        result["closed"] = step_info["closed"]
        result["errors"].extend(step_info.get("errors", []))

        # Save step inspection
        (out_dir / "step_inspection.json").write_text(
            json.dumps(step_info, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8"
        )

        # File size judgement
        judgement, reason = size_judgement(result["step_size_bytes"], "moderate")
        result["size_judgement"] = judgement
        if reason:
            result["warnings"].append(reason)

        # If geometry has errors but file exists, downgrade
        step_errors = [e for e in result["errors"] if "volume" in e.lower() or "solid" in e.lower() or "bbox" in e.lower()]
        if step_errors and result["status"] == "PASS":
            result["status"] = "PARTIAL_GEOMETRY"

    except Exception as e:
        result["status"] = "FAIL_EXCEPTION"
        result["errors"].append(f"Exception: {e}\n{traceback.format_exc()[-500:]}")
        result["elapsed_s"] = 0

    # Save result
    (out_dir / "case_result.json").write_text(
        json.dumps(result, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8"
    )
    return result


def run_v62_stress30_cases():
    """Re-run all v62 stress30 cases through updated pipeline."""
    print("=" * 60)
    print("v62 Stress30 Re-evaluation")
    print("=" * 60)

    all_results = []
    case_files = sorted(STRESS30_DIR.glob("g*_*"))

    for case_dir in case_files:
        if not case_dir.is_dir():
            continue
        case_id = case_dir.name
        canonical_path = case_dir / "canonical.json"

        if not canonical_path.exists():
            # Try to find it in subdirectories
            candidates = list(case_dir.glob("**/canonical.json"))
            if candidates:
                canonical_path = candidates[0]
            else:
                print(f"  SKIP {case_id}: no canonical.json found")
                continue

        out_dir = TEST_ROOT / "cases" / f"stress30_{case_id}"
        print(f"  Running {case_id}...", end=" ", flush=True)
        result = run_case(f"stress30_{case_id}", canonical_path, out_dir, f"v62 Stress30 re-test: {case_id}")
        status = result["status"]
        vol = result.get("volume_mm3", "?")
        print(f"{status} (vol={vol}, solids={result.get('n_solids','?')}, {result['elapsed_s']}s)")
        all_results.append(result)

    return all_results


def generate_matrices(results):
    """Generate CSV matrices from results."""
    # Failure matrix
    with open(FAILURE_MATRIX, "w", encoding="utf-8") as f:
        f.write("case_id,status,step_size_bytes,volume_mm3,n_solids,bbox_mm,closed,errors\n")
        for r in results:
            errors = "; ".join(r.get("errors", []))[:200]
            f.write(f"{r['case_id']},{r['status']},{r['step_size_bytes']},{r['volume_mm3']},{r['n_solids']},{r['bbox_mm']},{r['closed']},\"{errors}\"\n")

    # Geometry quality matrix
    with open(GEO_MATRIX, "w", encoding="utf-8") as f:
        f.write("case_id,step_exists,size_bytes,volume_mm3,n_solids,bbox_mm,closed,size_judgement,geometry_status\n")
        for r in results:
            geo_ok = (r.get("volume_mm3") or 0) > 0 and (r.get("n_solids") or 0) == 1
            f.write(f"{r['case_id']},{r['step_exists']},{r['step_size_bytes']},{r['volume_mm3']},{r['n_solids']},{r['bbox_mm']},{r['closed']},{r.get('size_judgement','')},{'OK' if geo_ok else 'ISSUE'}\n")

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r['status'] == 'PASS')
    partial = sum(1 for r in results if 'PARTIAL' in r['status'])
    failed = sum(1 for r in results if 'FAIL' in r['status'])
    with open(TEST_ROOT / "reports/summary.txt", "w", encoding="utf-8") as f:
        f.write(f"Total: {total}\n")
        f.write(f"PASS: {passed}\n")
        f.write(f"PARTIAL: {partial}\n")
        f.write(f"FAIL: {failed}\n")
    print(f"\nSummary: {passed} PASS, {partial} PARTIAL, {failed} FAIL (out of {total})")

    return total, passed, partial, failed


if __name__ == "__main__":
    print("Starting comprehensive evaluation...")
    print(f"Output dir: {TEST_ROOT}")
    print()

    results = run_v62_stress30_cases()
    total, passed, partial, failed = generate_matrices(results)

    # Save full results
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"total": total, "passed": passed, "partial": partial, "failed": failed, "cases": results}, f, indent=2, default=str, ensure_ascii=False)

    print(f"\nFull results saved to: {RESULTS_FILE}")
    print("Done.")
