"""Geometry A/B regression: tracked ops vs CadQuery native ops."""

import cadquery as cq
from OCP.TopoDS import TopoDS

from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    tracked_cut, tracked_fuse, tracked_common,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import tracked_extrude
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.revolve import tracked_revolve
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.fillet import tracked_fillet
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.chamfer import tracked_chamfer
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.unify import tracked_unify
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.mirror import tracked_mirror
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.pattern import (
    tracked_circular_pattern,
    tracked_linear_pattern,
)


class TestBooleanAB:

    def test_cut_volume_matches(self):
        box = cq.Workplane("XY").box(20, 20, 10).val()
        tool = cq.Workplane("XY").transformed(offset=(5, 5, -1)).box(10, 10, 12).val()
        tracked = tracked_cut(box, tool)
        native = box.cut(tool)
        assert abs(tracked.result.Volume() - native.Volume()) < 0.01

    def test_fuse_volume_matches(self):
        box = cq.Workplane("XY").box(20, 20, 10).val()
        tool = cq.Workplane("XY").transformed(offset=(5, 5, 0)).box(10, 10, 10).val()
        tracked = tracked_fuse(box, tool)
        native = box.fuse(tool)
        assert abs(tracked.result.Volume() - native.Volume()) < 0.01

    def test_common_volume_matches(self):
        box = cq.Workplane("XY").box(20, 20, 10).val()
        tool = cq.Workplane("XY").transformed(offset=(5, 5, 0)).box(10, 10, 10).val()
        tracked = tracked_common(box, tool)
        native = box.intersect(tool)
        assert abs(tracked.result.Volume() - native.Volume()) < 0.01


class TestExtrudeAB:

    def test_extrude_volume_matches(self):
        """Tracked extrude produces valid non-zero volume."""
        profile = cq.Workplane("XY").rect(10, 10).extrude(1).faces(">Z").val()
        tracked = tracked_extrude(profile, (0, 0, 20))
        assert tracked.result.Volume() > 0


class TestRevolveAB:

    def test_revolve_volume_matches(self):
        """Tracked revolve produces valid geometry."""
        profile = cq.Workplane("XZ").rect(10, 20).val()
        result = tracked_revolve(profile, (0, 0, 0), (0, 1, 0), 180)
        assert result.result.Volume() > 0


class TestFilletAB:

    def test_fillet_volume_matches(self):
        box = cq.Workplane("XY").box(20, 20, 10).val()
        edges = list(box.edges())
        edge = TopoDS.Edge_s(edges[0].wrapped)
        tracked = tracked_fillet(box, [edge], radius=2.0)
        assert tracked.result.Volume() < box.Volume()


class TestChamferAB:

    def test_chamfer_volume_matches(self):
        box = cq.Workplane("XY").box(20, 20, 10).val()
        edges = list(box.edges())
        edge = TopoDS.Edge_s(edges[0].wrapped)
        tracked = tracked_chamfer(box, [edge], distance=2.0)
        assert tracked.result.Volume() < box.Volume()


class TestUnifyAB:

    def test_unify_face_count(self):
        box = cq.Workplane("XY").box(20, 20, 10).val()
        tracked = tracked_unify(box)
        # Box with no coplanar faces: result is same
        assert abs(tracked.result.Volume() - box.Volume()) < 0.01


class TestMirrorAB:

    def test_mirror_volume_matches(self):
        box = cq.Workplane("XY").box(20, 10, 5).val()
        tracked = tracked_mirror(box, origin=(0, 0, 0), normal=(1, 0, 0))
        assert abs(tracked.result.Volume() - box.Volume()) < 0.01


class TestLinearPatternAB:

    def test_pattern_volume(self):
        box = cq.Workplane("XY").box(20, 10, 5).val()
        tracked = tracked_linear_pattern(box, direction=(1, 0, 0), count=3, spacing=30)
        assert tracked.result.Volume() > box.Volume() * 2  # non-overlapping


class TestCircularPatternAB:

    def test_single_fuse_matches_native_union(self):
        box = cq.Workplane("XY").box(10, 10, 5).val()
        count = 8
        radius = 30

        native = None
        for i in range(count):
            angle = i * 360.0 / count
            import math
            radians = math.radians(angle)
            x = radius * math.cos(radians)
            y = radius * math.sin(radians)
            copy = box.rotate((0, 0, 0), (0, 0, 1), angle).translate((x, y, 0))
            native = copy if native is None else native.fuse(copy)

        tracked = tracked_circular_pattern(
            box, (0, 0, 0), (0, 0, 1), count, radius_mm=radius,
        )

        assert abs(tracked.result.Volume() - native.Volume()) < 0.01
        assert len(tracked.result.Faces()) == len(native.Faces())
        assert len(tracked.result.Edges()) == len(native.Edges())

    def test_overlapping_instances_fall_back_to_sequential_union(self):
        import math

        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.BOPAlgo import BOPAlgo_BOP, BOPAlgo_FUSE
        from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

        box = cq.Workplane("XY").box(10, 10, 5).val()
        count = 8
        radius = 5

        instances = [box.wrapped]
        for i in range(1, count):
            angle = i * 360.0 / count
            radians = math.radians(angle)
            x = radius * math.cos(radians)
            y = radius * math.sin(radians)
            rotation = gp_Trsf()
            rotation.SetRotation(
                gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)),
                radians,
            )
            transform = gp_Trsf()
            transform.SetTranslation(gp_Vec(x, y, 0))
            transform.Multiply(rotation)
            builder = BRepBuilderAPI_Transform(box.wrapped, transform)
            builder.Build()
            instances.append(builder.Shape())

        legacy = instances[0]
        for instance in instances[1:]:
            fuse = BOPAlgo_BOP()
            fuse.SetOperation(BOPAlgo_FUSE)
            fuse.AddArgument(legacy)
            fuse.AddTool(instance)
            fuse.Perform()
            legacy = fuse.Shape()
        legacy = cq.Shape.cast(legacy)

        tracked = tracked_circular_pattern(
            box, (0, 0, 0), (0, 0, 1), count, radius_mm=radius,
        )

        assert abs(tracked.result.Volume() - legacy.Volume()) < 0.01
        assert len(tracked.result.Faces()) == len(legacy.Faces())
        assert len(tracked.result.Edges()) == len(legacy.Edges())
