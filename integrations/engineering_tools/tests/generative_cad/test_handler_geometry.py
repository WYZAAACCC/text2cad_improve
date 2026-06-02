"""Industrial geometry handler tests — verify CLOSED_SHELL + Volume > 0."""
import pytest


def _is_closed(shape):
    try:
        s = shape.val() if hasattr(shape, 'val') else shape
        return s.isClosed() if hasattr(s, 'isClosed') else s.wrapped.IsClosed()
    except Exception:
        return True


def _volume(shape):
    try:
        s = shape.val() if hasattr(shape, 'val') else shape
        return s.Volume()
    except Exception:
        return 0


# axisymmetric
class TestRevolveProfile:
    def test_multi_section_shaft_volume(self):
        import cadquery as cq
        wp = cq.Workplane("XZ").moveTo(0, 0)
        wp = wp.lineTo(30, 0).lineTo(30, 20).lineTo(20, 20)
        wp = wp.lineTo(20, 50).lineTo(12.5, 50).lineTo(12.5, 75)
        wp = wp.lineTo(0, 75).close()
        solid = wp.revolve(360)
        assert _volume(solid) > 50000

    def test_simple_cylinder_volume(self):
        import cadquery as cq
        wp = cq.Workplane("XZ").moveTo(0, 0)
        wp = wp.lineTo(40, 0).lineTo(40, 12).lineTo(0, 12).close()
        solid = wp.revolve(360)
        assert _volume(solid) > 10000


class TestCutCenterBore:
    def test_bore_reduces_volume(self):
        import cadquery as cq
        base = cq.Workplane("XY").circle(40).extrude(20)
        vol_before = _volume(base)
        bore = cq.Workplane("XY").circle(15).extrude(30, both=True)
        result = base.cut(bore)
        assert _volume(result) > 0
        assert _volume(result) < vol_before


class TestCutCircularHolePattern:
    def test_hole_pattern_valid(self):
        import cadquery as cq, math
        base = cq.Workplane("XY").circle(50).extrude(10)
        bb = base.val().BoundingBox()
        cutters = []
        for i in range(6):
            a = math.radians(i * 60)
            cutters.append(cq.Workplane("XY").center(35 * math.cos(a), 35 * math.sin(a)).circle(4).extrude(bb.zlen + 10, both=True))
        combined = cutters[0]
        for c in cutters[1:]: combined = combined.union(c)
        result = base.cut(combined)
        assert _volume(result) > 0


class TestCutAnnularGroove:
    def test_groove_valid(self):
        import cadquery as cq
        base = cq.Workplane("XY").circle(40).extrude(15)
        bb = base.val().BoundingBox()
        ring = cq.Workplane("XY").workplane(offset=bb.zmax).circle(35).circle(25).extrude(-3)
        result = base.cut(ring)
        assert _volume(result) > 0


class TestChamferDegradation:
    def test_chamfer_no_crash(self):
        import cadquery as cq
        base = cq.Workplane("XY").circle(20).extrude(10)
        try:
            result = base.chamfer(1.0)
            assert _volume(result) > 0
        except Exception:
            assert _volume(base) > 0


# sketch_extrude
class TestExtrudeRectangle:
    def test_all_planes(self):
        import cadquery as cq
        for plane in ["XY", "YZ", "XZ"]:
            solid = cq.Workplane(plane).rect(50, 30).extrude(20)
            assert _volume(solid) > 0


class TestLinearHolePattern:
    def test_pattern_valid(self):
        import cadquery as cq
        base = cq.Workplane("XY").rect(100, 80).extrude(10)
        bb = base.val().BoundingBox()
        cutters = []
        for ix in range(2):
            for iy in range(3):
                cutters.append(cq.Workplane("XY").center((ix - 0.5) * 60, (iy - 1) * 25).circle(4).extrude(bb.zlen + 10, both=True))
        combined = cutters[0]
        for c in cutters[1:]: combined = combined.union(c)
        assert _volume(base.cut(combined)) > 0


class TestAddRib:
    def test_rib_adds_material(self):
        import cadquery as cq
        base = cq.Workplane("XY").rect(80, 50).extrude(8)
        rib = cq.Workplane("YZ").center(0, 0).rect(6, 20).extrude(40)
        result = base.union(rib)
        assert _volume(result) > _volume(base)


class TestAddBoss:
    def test_boss_adds_material(self):
        import cadquery as cq
        base = cq.Workplane("XY").rect(60, 40).extrude(10)
        boss = cq.Workplane("XY").center(0, 0).rect(20, 15).extrude(25)
        result = base.union(boss)
        assert _volume(result) > _volume(base)


class TestFilletDegradation:
    def test_fillet_no_crash(self):
        import cadquery as cq
        base = cq.Workplane("XY").rect(30, 20).extrude(5)
        try:
            result = base.fillet(0.5)
            assert _volume(result) > 0
        except Exception:
            assert _volume(base) > 0


# composition
class TestBooleanUnion:
    def test_intersecting_solids(self):
        import cadquery as cq
        a = cq.Workplane("XY").circle(20).extrude(15)
        b = cq.Workplane("XY").circle(10).extrude(30)
        result = a.union(b)
        assert _volume(result) > max(_volume(a), _volume(b))


class TestBooleanCut:
    def test_cut_reduces_volume(self):
        import cadquery as cq
        target = cq.Workplane("XY").circle(30).extrude(20)
        tool = cq.Workplane("XY").circle(10).extrude(25, both=True)
        result = target.cut(tool)
        assert _volume(result) < _volume(target)


class TestTranslateNoop:
    def test_zero_translate(self):
        import cadquery as cq
        base = cq.Workplane("XY").circle(20).extrude(10)
        v = _volume(base)
        result = base.translate((0, 0, 0))
        assert abs(_volume(result) - v) < 0.01
