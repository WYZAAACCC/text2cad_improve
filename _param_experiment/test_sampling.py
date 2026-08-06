"""采样器约束纯函数单测（独立，不纳入主 tests/，可 pytest 或直接运行）。

验证 sampling_constraints.py 4+1 约束对已知参数的正确判定，以及 candidate_sampler
三区分类与参数范围。

运行:
  .conda/python.exe _param_experiment/test_sampling.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from sampling_constraints import (  # noqa: E402
    check_hole_bounds, check_hole_spacing, check_slot_pitch, check_slot_depth,
    check_groove_depth,
)


def _close(a, b, tol=1e-6):
    return abs(a - b) < tol


def test_hole_bounds():
    # od=500 rim=250, bore=120 bore_r=60
    r = check_hole_bounds(pcd_mm=180, hdia_mm=14, od_mm=500, bore_mm=120)
    assert r["ok"], f"正常孔应满足: {r}"
    # 越外边界
    r2 = check_hole_bounds(pcd_mm=240, hdia_mm=26, od_mm=500, bore_mm=120)
    assert not r2["outer_ok"], f"pcd 240+13+2=255>250 应越界: {r2}"
    assert not r2["ok"]
    # 交中心孔
    r3 = check_hole_bounds(pcd_mm=70, hdia_mm=20, od_mm=500, bore_mm=120)
    assert not r3["inner_ok"], f"70-10-2=58<60 应交中心孔: {r3}"
    # max_pcd = rim - hdia/2 - cb
    assert _close(r["max_pcd_mm"], 250 - 7 - 2), r["max_pcd_mm"]
    assert _close(r["min_pcd_mm"], 60 + 7 + 2), r["min_pcd_mm"]


def test_hole_spacing():
    # 正常：n=16 pcd=180 hdia=14
    r = check_hole_spacing(16, 180, 14)
    assert r["ok"], f"正常孔间距应满足: {r}"
    # 不足：n=36 pcd=80 hdia=26（pcd 下限+hdia 上限+n 上限）
    r2 = check_hole_spacing(36, 80, 26)
    assert not r2["ok"], f"2·80·sin(5°)−26 = 13.9−26 <0 应不足: {r2}"
    assert r2["ligament"] < 0


def test_slot_pitch():
    # 正常：slots=48 R=220 throat=4.0（ws=14.4, +4=18.4 < pitch 28.8）
    r = check_slot_pitch(48, 220, 4.0)
    assert r["ok"], f"正常节距应满足: {r}"
    # 不足：slots=96 R=200 throat=6.0（ws=21.6, +4=25.6 > pitch 13.09）
    r2 = check_slot_pitch(96, 200, 6.0)
    assert not r2["ok"], f"节距应不足: {r2}"


def test_slot_depth():
    r = check_slot_depth(depth_mm=24, rim_radial_mm=60)
    assert r["ok"]
    r2 = check_slot_depth(depth_mm=45, rim_radial_mm=40)
    assert not r2["ok"], f"45+3=48>40 应超轮缘: {r2}"


def test_groove_depth():
    r = check_groove_depth(gd_mm=10, rim_radial_mm=60)
    assert r["ok"]
    r2 = check_groove_depth(gd_mm=20, rim_radial_mm=15)
    assert not r2["ok"]


def test_sampler_zones_and_ranges():
    from candidate_sampler import _sample_family, RANGES
    from design_families import DESIGN_FAMILIES
    for fid, fam in DESIGN_FAMILIES.items():
        cands = _sample_family(fid, fam, 12)
        assert cands, f"{fid} 应有候选"
        zones = {c["zone"] for c in cands}
        assert "feasible" in zones, f"{fid} 缺 feasible"
        # 强约束类别（孔/榫槽/耦合/复杂轮缘）应有 infeasible（论文不可行样本集中于此）；
        # boundary 只保留真实 margin<阈值 的候选，不强制每族都有（避免虚假边界标签）
        if fam["category"] in ("hole", "slot", "coupled", "complex_rim"):
            assert "infeasible" in zones, f"{fid} 缺 infeasible"
        for c in cands:
            for k, (lo, hi) in RANGES.items():
                v = c["params"].get(k)
                if v is not None:
                    assert lo <= v <= hi, f"{c['task_id']} {k}={v} 越界 [{lo},{hi}]"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  PASS {t.__name__}")
    print(f"\n全部 {len(tests)} 项单测通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
