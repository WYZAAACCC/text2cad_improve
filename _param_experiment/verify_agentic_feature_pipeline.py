"""Verify that agentic feature workers keep parity with deterministic golden IR.

Runs mock Agent A + B/C + Feature Workers, then executes the generated IR
through the real CAD pipeline and DiskCAD-MCP quality gate.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_SERVER = _ROOT / "app" / "text-to-cad" / "server"
_SRC = _ROOT / "integrations" / "engineering_tools" / "src"
for path in (_HERE, _SERVER, _SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agentic_golden import family_params  # noqa: E402
import param_templates as pt  # noqa: E402


class _ToolResult:
    def __init__(self, arguments):
        self.arguments = arguments


class _MockCaller:
    def __init__(self, plan, raw):
        self.plan = plan
        self.points = self._points(raw)

    def _points(self, raw):
        comps = {c["id"]: c for c in raw.get("components", [])}
        out = {}
        for node in raw.get("nodes", []):
            if node.get("op") != "add_polyline":
                continue
            cid = node.get("component")
            kh = comps.get(cid, {}).get("kind_hint") or ""
            pid = None
            if "disc" in kh or "turbine_disc" in kh:
                pid = "disc_polyline"
            elif "fir_tree" in kh or "slot" in kh:
                pid = "cutter_polyline"
            elif str(cid).startswith("feat_"):
                pid = f"{cid}_profile"
            if pid:
                out[pid] = node.get("params", {}).get("points", [])
        return out

    def call_strict_tool(self, **kwargs):
        tool_name = kwargs.get("tool_name")
        if tool_name == "emit_design_plan":
            return _ToolResult(self.plan)
        if tool_name == "emit_profile_points":
            user = kwargs.get("messages", [])[-1]["content"]
            match = re.search(r"\[([\w\-]+)\]", user)
            pid = match.group(1) if match else "disc_polyline"
            return _ToolResult({"profile_id": pid, "points": self.points.get(pid, [])})
        raise AssertionError(f"unexpected tool: {tool_name}")


def main() -> int:
    import agentic_l2
    from seekflow_engineering_tools.generative_cad.pipeline.run import run_gcad_core
    from mcp_tools import generate_quality_report

    subset = [
        "check_solid_validity",
        "check_degenerate_geometry",
        "validate_slot_step_roundtrip",
        "check_slot_pitch_and_ligament",
        "check_adjacent_feature_clearance",
        "validate_slot_pattern_periodicity",
    ]
    ok = True
    for fid in ("D05", "D10", "D23"):
        root = Path(tempfile.mkdtemp(prefix=f"agentic_{fid}_"))
        params = family_params(fid)
        raw = pt.build(params)
        plan = pt.plan(params)
        caller = _MockCaller(plan, raw)
        agent = agentic_l2.run_agentic_l2(
            "test",
            None,
            caller=caller,
            llm_model_config=None,
            out_dir=root,
        )
        run_dir = root / "run"
        run_dir.mkdir()
        (run_dir / "raw_fixed.json").write_text(
            json.dumps(agent, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result = run_gcad_core(
            agent,
            out_step=run_dir / "output.step",
            metadata_path=run_dir / "output.metadata.json",
        )
        if not result.ok:
            print(f"{fid} PIPELINE FAIL {getattr(result, 'error', None)}")
            ok = False
            continue
        gate = generate_quality_report({"base_dir": str(run_dir), "tool_subset": subset})
        print(f"{fid} PIPELINE OK MCP={gate.get('ok')} failed={gate.get('failed_checks')}")
        if not gate.get("ok"):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
