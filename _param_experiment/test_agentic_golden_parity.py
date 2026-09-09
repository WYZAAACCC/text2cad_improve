"""Golden baseline for agentic parity tests.

These tests only validate that the deterministic template produces the
expected reference metrics. Later agent worker tests will compare against
these extracted metrics.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest

from agentic_golden import (
    build_golden_ir,
    circle_error,
    deterministic_profile_points,
    extract_metrics,
    points_match,
)


def _metrics(family_id: str):
    raw = build_golden_ir(family_id)
    return extract_metrics(raw)


def test_basic_disc_golden():
    m = _metrics("D01")
    assert len(m["disc_points"]) == 12
    assert m["slot_points"] == []
    assert m["feature_cutters"] == {}
    assert m["boolean_cuts"] == 0


def test_slot_disc_golden():
    m = _metrics("D19")
    assert len(m["slot_points"]) == 2 * (2 + 4 * 3 + 3)
    assert m["boolean_cuts"] == 1
    assert m["patterns"]


def test_hole_disc_golden():
    m = _metrics("D05")
    assert m["feature_cutters"]
    hole_pts = next(iter(m["feature_cutters"].values()))
    assert len(hole_pts) == 16
    assert circle_error(hole_pts, 14.0) <= 0.2
    assert m["boolean_cuts"] == 1


def test_groove_disc_golden():
    m = _metrics("D10")
    assert m["feature_cutters"]
    assert any(len(v) == 4 for v in m["feature_cutters"].values())
    assert m["boolean_cuts"] >= 2


def test_multi_groove_build_keeps_distinct_positions():
    m = _metrics("D11")
    grooves = {cid: v for cid, v in m["feature_cutters"].items()
               if str(cid).startswith("feat_groove_")}
    assert len(grooves) == 2
    z0 = sorted({p["y_mm"] for p in grooves["feat_groove_0"]})
    z1 = sorted({p["y_mm"] for p in grooves["feat_groove_1"]})
    assert z0 != z1


def test_rimslot_build_keeps_u_shape():
    m = _metrics("D12")
    pts = m["feature_cutters"].get("feat_rimslot", [])
    assert len(pts) == 5
    ys = {p["y_mm"] for p in pts}
    assert 0.0 in ys  # 槽底圆弧中点


def test_coupled_disc_golden():
    m = _metrics("D23")
    assert len(m["slot_points"]) > 0
    assert len(m["feature_cutters"]) >= 2
    assert m["boolean_cuts"] >= 2


def _placeholder_skeleton(raw):
    import copy
    skel = copy.deepcopy(raw)
    comps = {c["id"]: c for c in skel.get("components", [])}
    for node in skel.get("nodes", []):
        cid = node.get("component")
        if node.get("op") != "add_polyline":
            continue
        comp = comps.get(cid)
        kind = (comp or {}).get("kind_hint") or ""
        if any(k in kind for k in ("disc", "turbine_disc", "slot", "cutter")):
            continue
        node.setdefault("params", {})["points"] = [
            {"x_mm": 0, "y_mm": 0},
            {"x_mm": 1, "y_mm": 1},
        ]
        if any(k in str(cid) for k in ("groove", "cavity", "rimslot")):
            comp["kind_hint"] = "groove_cutter"
        else:
            comp["kind_hint"] = "hole_cutter"
    return skel


def _feature_profiles(raw):
    profiles = []
    comps = {c["id"]: c for c in raw.get("components", [])}
    for node in raw.get("nodes", []):
        cid = node.get("component")
        if node.get("op") != "add_polyline":
            continue
        comp = comps.get(cid)
        kind = (comp or {}).get("kind_hint") or ""
        if any(k in kind for k in ("disc", "turbine_disc", "slot", "cutter")):
            continue
        pts = [(p["x_mm"], p["y_mm"]) for p in node["params"]["points"]]
        if any(k in str(cid) for k in ("groove", "cavity", "rimslot")):
            params = {
                "inner_radius_mm": min(p[0] for p in pts),
                "outer_radius_mm": max(p[0] for p in pts),
                "z_base_mm": min(p[1] for p in pts),
                "depth_mm": max(p[1] for p in pts) - min(p[1] for p in pts),
            }
            profiles.append({"profile_id": f"{cid}_profile", "kind": "groove", "params": params})
        else:
            radius = sum((p[0] ** 2 + p[1] ** 2) ** 0.5 for p in pts) / len(pts)
            profiles.append({
                "profile_id": f"{cid}_profile",
                "kind": "hole",
                "params": {"center_x_mm": 0.0, "center_y_mm": 0.0, "diameter_mm": radius * 2},
            })
    return profiles


def _agentic_feature_raw(family_id):
    import sys as _sys
    from pathlib import Path as _Path
    server = _Path(__file__).resolve().parents[1] / "app" / "text-to-cad" / "server"
    if str(server) not in _sys.path:
        _sys.path.insert(0, str(server))
    import agentic_l2

    raw = build_golden_ir(family_id)
    skeleton = _placeholder_skeleton(raw)
    profiles = _feature_profiles(raw)
    points = {}
    for prof in profiles:
        kind = prof["kind"]
        params = prof["params"]
        points[prof["profile_id"]] = deterministic_profile_points(kind, params)
    return agentic_l2.assemble(skeleton, profiles, points)


@pytest.mark.parametrize("family_id", ["D05", "D10", "D23"])
def test_feature_worker_matches_golden(family_id):
    golden = extract_metrics(build_golden_ir(family_id))
    agent = extract_metrics(_agentic_feature_raw(family_id))

    assert golden["boolean_cuts"] == agent["boolean_cuts"]
    assert golden["patterns"] == agent["patterns"]
    assert golden["disc_points"] == agent["disc_points"]
    assert golden["slot_points"] == agent["slot_points"]

    assert set(golden["feature_cutters"]) == set(agent["feature_cutters"])
    for cid in golden["feature_cutters"]:
        assert points_match(
            golden["feature_cutters"][cid],
            agent["feature_cutters"][cid],
            tol=0.001,
        ), cid


class _MockToolResult:
    def __init__(self, arguments):
        self.arguments = arguments


def _mock_caller_for_golden(raw, plan):
    import re
    comps = {c["id"]: c for c in raw.get("components", [])}
    points = {}
    for node in raw.get("nodes", []):
        cid = node.get("component")
        if node.get("op") == "add_polyline":
            kind = comps.get(cid, {}).get("kind_hint") or ""
            profile_id = None
            if "disc" in kind or "turbine_disc" in kind:
                profile_id = "disc_polyline"
            elif "fir_tree" in kind or "slot" in kind:
                profile_id = "cutter_polyline"
            elif str(cid).startswith("feat_"):
                profile_id = f"{cid}_profile"
            if profile_id:
                points[profile_id] = node.get("params", {}).get("points", [])

    class MockCaller:
        def __init__(self):
            self.calls = 0

        def call_strict_tool(self, **kwargs):
            tool_name = kwargs.get("tool_name")
            if tool_name == "emit_design_plan":
                return _MockToolResult(plan)
            if tool_name == "emit_profile_points":
                user = kwargs.get("messages", [])[-1]["content"]
                match = re.search(r"\[([\w\-]+)\]", user)
                pid = match.group(1) if match else "disc_polyline"
                return _MockToolResult({"profile_id": pid, "points": points.get(pid, [])})
            raise AssertionError(f"unexpected tool: {tool_name}")

    return MockCaller()


@pytest.mark.parametrize("family_id", ["D01", "D05", "D10", "D19", "D23"])
def test_agentic_l2_mock_run_matches_golden(family_id, tmp_path):
    import sys as _sys
    from pathlib import Path as _Path
    server = _Path(__file__).resolve().parents[1] / "app" / "text-to-cad" / "server"
    if str(server) not in _sys.path:
        _sys.path.insert(0, str(server))
    import agentic_l2
    from agentic_golden import family_params
    import param_templates as pt

    params = family_params(family_id)
    raw = build_golden_ir(family_id)
    plan = pt.plan(params)
    caller = _mock_caller_for_golden(raw, plan)
    agent_raw = agentic_l2.run_agentic_l2(
        "test",
        None,
        caller=caller,
        llm_model_config=None,
        out_dir=tmp_path,
    )
    golden = extract_metrics(raw)
    agent = extract_metrics(agent_raw)
    assert golden["disc_points"] == agent["disc_points"]
    assert golden["slot_points"] == agent["slot_points"]
    assert golden["boolean_cuts"] == agent["boolean_cuts"]
    assert golden["patterns"] == agent["patterns"]
    for cid in golden["feature_cutters"]:
        assert points_match(
            golden["feature_cutters"][cid],
            agent["feature_cutters"][cid],
            tol=0.001,
        ), cid


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
