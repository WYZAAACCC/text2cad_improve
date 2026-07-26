"""T6: Construction Roles stability — start_cap/end_cap across parameter changes (v5.0 §11)."""

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import tracked_extrude
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import TopologyCaptureScope


class TestT6ConstructionRoles:

    def test_extrude_roles_present_for_different_heights(self):
        """start_cap/end_cap are present at multiple extrude heights."""
        for height in [10, 20, 50]:
            profile = cq.Workplane("XY").rect(10, 10).val()
            result = tracked_extrude(profile, (0, 0, height),
                                     scope=TopologyCaptureScope(node_id=f"h{height}"))
            roles = result.batch.construction_roles
            assert "start_cap" in roles, f"start_cap missing at height={height}"
            assert "end_cap" in roles, f"end_cap missing at height={height}"
            assert roles["start_cap"] is not None
            assert roles["end_cap"] is not None

    def test_different_heights_produce_different_caps(self):
        """start_cap/end_cap shapes change with height."""
        r1 = tracked_extrude(
            cq.Workplane("XY").rect(10, 10).val(), (0, 0, 10),
            scope=TopologyCaptureScope(node_id="h10"))
        r2 = tracked_extrude(
            cq.Workplane("XY").rect(10, 10).val(), (0, 0, 50),
            scope=TopologyCaptureScope(node_id="h50"))

        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps

        for key in ("start_cap", "end_cap"):
            s1 = r1.batch.construction_roles[key]
            s2 = r2.batch.construction_roles[key]
            # Caps should be different shapes (different positions)
            p1 = GProp_GProps(); p2 = GProp_GProps()
            BRepGProp.SurfaceProperties_s(s1, p1)
            BRepGProp.SurfaceProperties_s(s2, p2)
            c1 = p1.CentreOfMass(); c2 = p2.CentreOfMass()
            # At least Z coordinates differ for end_cap
            if key == "end_cap":
                assert abs(c1.Z() - c2.Z()) > 1.0, \
                    f"{key} Z should differ: {c1.Z():.1f} vs {c2.Z():.1f}"

    def test_extrude_roles_use_semantic_names(self):
        """Roles use 'start_cap'/'end_cap' (not 'first_shape'/'last_shape')."""
        profile = cq.Workplane("XY").rect(10, 10).val()
        result = tracked_extrude(profile, (0, 0, 20),
                                 scope=TopologyCaptureScope(node_id="semantic"))
        roles = result.batch.construction_roles
        assert "start_cap" in roles
        assert "end_cap" in roles
        # Semantic names only (v5.0 T6 requirement)
        assert "first_shape" not in roles
        assert "last_shape" not in roles
