"""Batch SolidWorks import for v6 test STEP files."""
import sys, os, time, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "integrations" / "engineering_tools" / "src"))

OUT = Path(__file__).parent / "v51_full35_output"
SW_OUT = OUT / "solidworks"
SW_OUT.mkdir(parents=True, exist_ok=True)

results = []
for case_dir in sorted(OUT.iterdir()):
    if not case_dir.is_dir(): continue
    case_id = case_dir.name
    step_file = case_dir / "output.step"
    if not step_file.exists():
        results.append({"id": case_id, "ok": False, "msg": "no STEP file"})
        continue

    sldprt_file = SW_OUT / f"{case_id}.SLDPRT"
    if sldprt_file.exists():
        results.append({"id": case_id, "ok": True, "msg": "already exists", "size": sldprt_file.stat().st_size})
        continue

    try:
        from seekflow_engineering_tools.generative_cad.native_importers import import_step_to_solidworks
        from seekflow_engineering_tools.config import EngineeringToolsConfig
        config = EngineeringToolsConfig(workspace_root=OUT)
        result = import_step_to_solidworks(config, step_file, sldprt_file)
        if result.get("ok"):
            sz = sldprt_file.stat().st_size if sldprt_file.exists() else 0
            results.append({"id": case_id, "ok": True, "size": sz})
            print(f"  {case_id}: OK ({sz}B)")
        else:
            results.append({"id": case_id, "ok": False, "msg": str(result)})
            print(f"  {case_id}: FAIL - {result}")
    except Exception as e:
        results.append({"id": case_id, "ok": False, "msg": str(e)})
        print(f"  {case_id}: ERROR - {e}")

(SW_OUT / "import_results.json").write_text(json.dumps(results, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
ok_count = sum(1 for r in results if r.get("ok"))
print(f"\nSolidWorks Import: {ok_count}/{len(results)}")
