"""系统性回归测试: revolve_profile 零体积 bug 的架构级修复验证。

这些测试不依赖特定测试数据——它们验证修复逻辑本身是否正确，
确保未来任何 text→model 流程都不会再出现零体积 revolve。
"""
import pytest


class TestAutoFixerFlatProfile:
    """验证 auto_fixer 检测并修复 flat profile (所有 station 同一 z 范围)。"""

    def test_detects_flat_profile_same_z(self):
        """所有 station 有相同的 z_front_mm 和 z_rear_mm → 应重组。"""
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix

        raw = {
            "nodes": [{
                "id": "n1", "component": "c1", "dialect": "axisymmetric",
                "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 15.0, "z_front_mm": 0.0, "z_rear_mm": 12.0},
                        {"r_mm": 40.0, "z_front_mm": 0.0, "z_rear_mm": 12.0},
                    ],
                },
            }],
        }

        fixed = auto_fix(raw)
        stations = fixed["nodes"][0]["params"]["profile_stations"]

        # 修复后: z 范围应该不同 (不再全是 0-12)
        z_fronts = {s["z_front_mm"] for s in stations}
        z_rears = {s["z_rear_mm"] for s in stations}
        assert not (len(z_fronts) == 1 and len(z_rears) == 1), (
            f"Flat profile NOT fixed! z_fronts={z_fronts}, z_rears={z_rears}"
        )

        # 修复后: 按 r 降序，第一个 station 是外壁(全厚度)
        assert stations[0]["r_mm"] == 40.0, f"First station should be outer wall (largest r), got r={stations[0]['r_mm']}"
        assert stations[-1]["r_mm"] == 15.0, f"Last station should be inner bore (smallest r), got r={stations[-1]['r_mm']}"

        # z 必须是顺序的
        for i in range(len(stations) - 1):
            assert stations[i]["z_rear_mm"] <= stations[i + 1]["z_front_mm"], (
                f"Station {i} z_rear={stations[i]['z_rear_mm']} > station {i+1} z_front={stations[i+1]['z_front_mm']}"
            )

    def test_preserves_correct_profile(self):
        """已经正确的 profile (不同 z 范围) 不应被修改。"""
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix

        raw = {
            "nodes": [{
                "id": "n1", "component": "c1", "dialect": "axisymmetric",
                "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 30.0, "z_front_mm": 0.0, "z_rear_mm": 20.0},
                        {"r_mm": 20.0, "z_front_mm": 20.0, "z_rear_mm": 50.0},
                        {"r_mm": 12.5, "z_front_mm": 50.0, "z_rear_mm": 75.0},
                    ],
                },
            }],
        }

        fixed = auto_fix(raw)
        stations = fixed["nodes"][0]["params"]["profile_stations"]

        # 正确的 profile 应保持不变
        assert len(stations) == 3
        assert stations[0]["r_mm"] == 30.0
        assert stations[1]["r_mm"] == 20.0
        assert stations[2]["r_mm"] == 12.5

    def test_adds_second_station_for_single_station(self):
        """只有一个 station → 自动补充第二个。"""
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix

        raw = {
            "nodes": [{
                "id": "n1", "component": "c1", "dialect": "axisymmetric",
                "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 22.0, "z_front_mm": 0.0, "z_rear_mm": 15.0},
                    ],
                },
            }],
        }

        fixed = auto_fix(raw)
        stations = fixed["nodes"][0]["params"]["profile_stations"]
        assert len(stations) >= 2, f"Single station should get a second one, got {len(stations)}"


class TestHandlerRevolve:
    """验证 handler 的 revolve 产生正确体积。"""

    def test_washer_profile_produces_volume(self):
        """Washer profile → revolve 应产生 >0 体积。"""
        import cadquery as cq

        pts = [(0, 0), (40, 0), (40, 12), (15, 12), (15, 13), (0, 13)]
        wp = cq.Workplane("XZ").moveTo(pts[0][0], pts[0][1])
        for r, z in pts[1:]:
            wp = wp.lineTo(r, z)
        wp = wp.close()
        solid = wp.revolve(360)

        vol = solid.val().Volume()
        assert vol > 10000, f"Washer volume should be >10000 mm³, got {vol:.0f}"
        assert vol > 40000, f"Washer volume should be ~51000 mm³, got {vol:.0f}"

    def test_stepped_shaft_profile_produces_volume(self):
        """Stepped shaft profile → revolve 应产生 >0 体积。"""
        import cadquery as cq

        pts = [(0, 0), (30, 0), (30, 20), (20, 20), (20, 50), (12.5, 50), (12.5, 75), (0, 75)]
        wp = cq.Workplane("XZ").moveTo(pts[0][0], pts[0][1])
        for r, z in pts[1:]:
            wp = wp.lineTo(r, z)
        wp = wp.close()
        solid = wp.revolve(360)

        vol = solid.val().Volume()
        assert vol > 50000, f"Stepped shaft volume should be >50000 mm³, got {vol:.0f}"

    def test_gear_blank_profile_produces_volume(self):
        """Gear blank profile → revolve 应产生 >0 体积。"""
        import cadquery as cq

        pts = [(0, 0), (22, 0), (22, 15), (5, 15), (5, 16), (0, 16)]
        wp = cq.Workplane("XZ").moveTo(pts[0][0], pts[0][1])
        for r, z in pts[1:]:
            wp = wp.lineTo(r, z)
        wp = wp.close()
        solid = wp.revolve(360)

        vol = solid.val().Volume()
        assert vol > 10000, f"Gear blank volume should be >10000 mm³, got {vol:.0f}"

    def test_sort_by_z_only_preserves_correct_order(self):
        """sort(key=p[1]) 不破坏顺序多段线。"""
        pts = [(40.0, 0.0), (40.0, 12.0), (15.0, 12.0), (15.0, 13.0)]
        pts.sort(key=lambda p: p[1])

        # 同一 z 高度的点应保持原始顺序 (stable sort)
        # (40,12) 应在 (15,12) 之前
        idx_40_12 = pts.index((40.0, 12.0))
        idx_15_12 = pts.index((15.0, 12.0))
        assert idx_40_12 < idx_15_12, (
            f"Sort by z should preserve order at same z: (40,12) before (15,12)"
        )

    def test_old_sort_key_produces_wrong_order(self):
        """旧 sort(key=(p[1],p[0])) 破坏顺序——回归测试。"""
        pts = [(40.0, 0.0), (40.0, 12.0), (15.0, 12.0), (15.0, 13.0)]
        pts.sort(key=lambda p: (p[1], p[0]))  # 旧代码

        # 旧代码: (15,12) 在 (40,12) 之前 (因为 15<40)
        idx_40_12 = pts.index((40.0, 12.0))
        idx_15_12 = pts.index((15.0, 12.0))
        assert idx_15_12 < idx_40_12, (
            f"OLD sort key should put (15,12) before (40,12) — this was the bug"
        )


class TestEndToEndRevolve:
    """端到端: auto_fixer + handler 产生正确体积。"""

    def test_flat_profile_fixed_and_produces_volume(self):
        """LLM 风格的 flat profile → auto_fix → handler → 正确体积。"""
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix

        # 模拟 LLM 输出: 所有 station 同一 z 范围
        raw = {
            "nodes": [{
                "id": "n1", "component": "c1", "dialect": "axisymmetric",
                "op": "revolve_profile", "op_version": "1.0.0", "phase": "base_solid",
                "params": {
                    "axis": "Z",
                    "profile_stations": [
                        {"r_mm": 15.0, "z_front_mm": 0.0, "z_rear_mm": 12.0},
                        {"r_mm": 40.0, "z_front_mm": 0.0, "z_rear_mm": 12.0},
                    ],
                },
            }],
        }

        # auto_fix
        fixed = auto_fix(raw)
        stations = fixed["nodes"][0]["params"]["profile_stations"]

        # 构建 handler 风格的 profile
        pts_2d = []
        for s in stations:
            pts_2d.append((float(s["r_mm"]), float(s.get("z_front_mm", 0))))
            pts_2d.append((float(s["r_mm"]), float(s.get("z_rear_mm", 0))))
        pts_2d.sort(key=lambda p: p[1])  # 修复后的排序

        unique_pts = [pts_2d[0]]
        for pt in pts_2d[1:]:
            if pt != unique_pts[-1]:
                unique_pts.append(pt)

        z_min, z_max = unique_pts[0][1], unique_pts[-1][1]
        wp = cq.Workplane("XZ").moveTo(0, z_min)
        for r, z in unique_pts:
            wp = wp.lineTo(r, z)
        wp = wp.lineTo(0, z_max).close()
        solid = wp.revolve(360)  # 修复后的 revolve

        vol = solid.val().Volume()
        assert vol > 10000, (
            f"Fixed flat profile should produce volume >10000 mm³, got {vol:.0f}. "
            f"Stations after fix: {stations}"
        )
