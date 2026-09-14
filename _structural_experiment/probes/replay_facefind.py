"""Replay the facefind trace's actions against the real bundle and print the
tool replies. The trace records what the agent did; only this shows what it
was told - which is where the answer has to be if it queried eleven times and
never used a filter."""
import json, pathlib, sys
sys.path.insert(0, "integrations/structural/src")
from seekflow_structural.agents import facefind
from seekflow_structural.tools import geometry

bundle = pathlib.Path("_cfd_experiment/input/lineage/D27")
trace = json.loads(pathlib.Path(
    "_structural_experiment/output/structural/jobs/d27-chain/agent/facefind.json"
).read_text(encoding="utf-8"))["trace"]

session = geometry.open_bundle(bundle)
state = facefind.FaceFinderState(session=session)
try:
    for i, entry in enumerate(trace):
        action = facefind.Action.model_validate(entry)
        try:
            payload = facefind.DISPATCH(action, state)
        except Exception as exc:
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        text = json.dumps(payload, ensure_ascii=False)
        print(f"--- call {i}: {entry.get('action')} ---")
        if entry.get("action") == "query_faces":
            res = payload.get("result", {})
            print("  ok:", payload.get("ok"), "matched:", res.get("matched"),
                  "total:", res.get("face_count_total"))
            print("  summary:", json.dumps(res.get("summary"), ensure_ascii=False))
            print("  first face:", json.dumps((res.get("faces") or [{}])[0], ensure_ascii=False))
            if payload.get("error"):
                print("  ERROR:", text[:600])
        else:
            print(" ", text[:500])
finally:
    close = getattr(session, "close", None)
    if close: close()
