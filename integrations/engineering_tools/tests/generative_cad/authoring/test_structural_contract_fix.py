"""Structural contract fixes: Point2D lists, schema-forbidden extras, op_version alignment."""

from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import (
    _fix_op_versions,
    _fix_point2d_lists,
    _remove_extra_params,
)
from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry


def _node(doc, node_id):
    return next(n for n in doc["nodes"] if n["id"] == node_id)


class TestFixPoint2dLists:
    def test_polyline_points_list_to_dict(self):
        doc = {"nodes": [
            {"id": "n1", "dialect": "sketch_profile", "op": "add_polyline",
             "op_version": "1.0.0", "params": {"points": [[0, 0], [1, 1]]}}
        ]}
        fixed = _fix_point2d_lists(doc, default_registry())
        assert _node(fixed, "n1")["params"]["points"] == [
            {"x_mm": 0, "y_mm": 0}, {"x_mm": 1, "y_mm": 1},
        ]

    def test_single_point2d_list_to_dict(self):
        doc = {"nodes": [
            {"id": "n1", "dialect": "sketch_profile", "op": "add_line_segment",
             "op_version": "1.0.0",
             "params": {"start": [0, 0], "end": [1, 2]}}
        ]}
        fixed = _fix_point2d_lists(doc, default_registry())
        params = _node(fixed, "n1")["params"]
        assert params["start"] == {"x_mm": 0, "y_mm": 0}
        assert params["end"] == {"x_mm": 1, "y_mm": 2}


class TestRemoveExtraParams:
    def test_schema_forbidden_extra_removed(self):
        doc = {"nodes": [
            {"id": "n1", "dialect": "sketch_profile", "op": "fillet_sketch",
             "op_version": "1.0.0",
             "params": {"radius_mm": 1.2, "fillet_radius_mm": 1.2}}
        ]}
        fixed = _remove_extra_params(doc, default_registry())
        params = _node(fixed, "n1")["params"]
        assert params == {"radius_mm": 1.2}


class TestFixOpVersions:
    def test_unparseable_op_version_aligned(self):
        doc = {"nodes": [
            {"id": "n1", "dialect": "sketch_profile", "op": "add_polyline",
             "op_version": "0.2.0", "params": {"points": []}}
        ]}
        fixed = _fix_op_versions(doc, default_registry())
        assert _node(fixed, "n1")["op_version"] == "1.0.0"

