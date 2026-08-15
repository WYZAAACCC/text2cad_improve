"""G7: delete fingerprint is richer than (area, centroid)."""

import pytest


class TestDeleteFingerprint:
    def test_fingerprint_is_rich_dict(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
        )

        box = cq.Workplane("XY").box(20, 20, 10).val()
        face = list(box.Faces())[0]
        fp = PersistentSelectionService._shape_fingerprint(face.wrapped)

        assert isinstance(fp, dict)
        for key in ("area", "centroid", "surface_type", "perimeter"):
            assert key in fp

    def test_fingerprint_distinguishes_same_area_faces(self):
        pytest.importorskip("cadquery")
        import cadquery as cq
        from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
            PersistentSelectionService,
        )

        # A cube has six 100-area faces. Distinct orientation must yield a
        # distinct fingerprint even when area matches.
        cube = cq.Workplane("XY").box(10, 10, 10).val()
        faces = list(cube.Faces())
        plus_x = [f for f in faces if abs(f.Center().x - 5.0) < 1e-6][0]
        plus_y = [f for f in faces if abs(f.Center().y - 5.0) < 1e-6][0]

        fp_x = PersistentSelectionService._shape_fingerprint(plus_x.wrapped)
        fp_y = PersistentSelectionService._shape_fingerprint(plus_y.wrapped)

        assert fp_x["area"] == fp_y["area"]
        assert fp_x != fp_y
