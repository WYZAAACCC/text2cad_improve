"""Phase 2: DimExpr evaluation tests.

Tests verify:
- const: literal → float
- ref: RefPath → ShapeFacts value
- arithmetic: add, sub, mul, div, min, max
- abs, clamp
- recursion guard
- div by zero → ValueError
- invalid DimExpr → ValueError
- unknown ref → None

No OCP/CadQuery needed — pure data tests.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from seekflow_engineering_tools.generative_cad.ir.expr import (
    DimExpr,
    RefPath,
    DimOp,
)
from seekflow_engineering_tools.generative_cad.analysis.expr_eval import (
    evaluate_dim_expr,
    resolve_typed_params_dim_exprs,
)
from seekflow_engineering_tools.generative_cad.analysis.facts import (
    FactStore,
    NumericFact,
    ShapeFacts,
    BBoxFacts,
)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_store():
    """Create a FactStore with a revolve_profile-like fact for testing."""
    store = FactStore()
    facts = ShapeFacts(
        value_id="solid:c1:n1:body",
        value_type="solid",
        component_id="c1",
        producer_node="n1",
        radius_max_mm=NumericFact(value=50.0, confidence="exact", source_node="n1"),
        radius_min_mm=NumericFact(value=20.0, confidence="exact", source_node="n1"),
        length_z_mm=NumericFact(value=30.0, confidence="exact", source_node="n1"),
        volume_mm3=NumericFact(value=78540.0, confidence="exact", source_node="n1"),
        bbox=BBoxFacts(
            xlen_mm=NumericFact(value=100.0, confidence="exact"),
            ylen_mm=NumericFact(value=100.0, confidence="exact"),
            zlen_mm=NumericFact(value=30.0, confidence="exact"),
            xmin_mm=NumericFact(value=-50.0, confidence="exact"),
            xmax_mm=NumericFact(value=50.0, confidence="exact"),
            ymin_mm=NumericFact(value=-50.0, confidence="exact"),
            ymax_mm=NumericFact(value=50.0, confidence="exact"),
            zmin_mm=NumericFact(value=0.0, confidence="exact"),
            zmax_mm=NumericFact(value=30.0, confidence="exact"),
        ),
        extra={"center_bore_radius_mm": 15.0},
    )
    store.bind("n1", "body", facts)
    return store


# ═══════════════════════════════════════════════════════════════
# const
# ═══════════════════════════════════════════════════════════════

class TestDimExprConst:
    def test_literal_int(self):
        assert evaluate_dim_expr(42, None) == 42.0

    def test_literal_float(self):
        assert evaluate_dim_expr(3.14, None) == 3.14

    def test_dim_expr_const_int(self):
        d = DimExpr(op="const", args=[100])
        assert evaluate_dim_expr(d.model_dump(), None) == 100.0

    def test_dim_expr_const_float(self):
        d = DimExpr(op="const", args=[12.5])
        assert evaluate_dim_expr(d.model_dump(), None) == 12.5

    def test_nan_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            evaluate_dim_expr(float("nan"), None)

    def test_inf_raises(self):
        with pytest.raises(ValueError, match="infinity"):
            evaluate_dim_expr(float("inf"), None)


# ═══════════════════════════════════════════════════════════════
# ref
# ═══════════════════════════════════════════════════════════════

class TestDimExprRef:
    def test_ref_radius_max(self):
        store = _make_store()
        d = DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", output="body", path=["radius_max_mm"]).model_dump()])
        result = evaluate_dim_expr(d.model_dump(), store)
        assert result == 50.0

    def test_ref_radius_min(self):
        store = _make_store()
        d = DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", output="body", path=["radius_min_mm"]).model_dump()])
        assert evaluate_dim_expr(d.model_dump(), store) == 20.0

    def test_ref_bbox_xlen(self):
        store = _make_store()
        d = DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", output="body", path=["bbox", "xlen_mm"]).model_dump()])
        assert evaluate_dim_expr(d.model_dump(), store) == 100.0

    def test_ref_bbox_zlen(self):
        store = _make_store()
        d = DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", output="body", path=["bbox", "zlen_mm"]).model_dump()])
        assert evaluate_dim_expr(d.model_dump(), store) == 30.0

    def test_ref_extra_center_bore(self):
        store = _make_store()
        d = DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", output="body", path=["extra", "center_bore_radius_mm"]).model_dump()])
        assert evaluate_dim_expr(d.model_dump(), store) == 15.0

    def test_ref_unknown_node(self):
        store = _make_store()
        d = DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n999", output="body", path=["radius_max_mm"]).model_dump()])
        assert evaluate_dim_expr(d.model_dump(), store) is None

    def test_ref_unknown_property_returns_none(self):
        """RefPath to a valid node but a property that doesn't exist in facts (e.g. extra key that was never set)."""
        store = _make_store()
        d = DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", output="body", path=["extra", "nonexistent_key"]).model_dump()])
        assert evaluate_dim_expr(d.model_dump(), store) is None

    def test_ref_component(self):
        store = _make_store()
        d = DimExpr(op="ref", args=[RefPath(root_kind="component", root_id="c1", output="body", path=["radius_max_mm"]).model_dump()])
        assert evaluate_dim_expr(d.model_dump(), store) == 50.0

    def test_ref_invalid_dict_raises_validation_error(self):
        """An invalid RefPath dict raises ValidationError at DimExpr construction, not at eval time."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            DimExpr(op="ref", args=[{"not": "a ref"}])


# ═══════════════════════════════════════════════════════════════
# arithmetic
# ═══════════════════════════════════════════════════════════════

class TestDimExprArithmetic:
    def test_add(self):
        d = DimExpr(op="add", args=[10, 20, 30])
        assert evaluate_dim_expr(d.model_dump(), None) == 60.0

    def test_sub(self):
        d = DimExpr(op="sub", args=[100, 30, 5])
        assert evaluate_dim_expr(d.model_dump(), None) == 65.0

    def test_mul(self):
        d = DimExpr(op="mul", args=[2, 3, 4])
        assert evaluate_dim_expr(d.model_dump(), None) == 24.0

    def test_div(self):
        d = DimExpr(op="div", args=[100, 2, 5])
        assert evaluate_dim_expr(d.model_dump(), None) == 10.0

    def test_div_by_zero(self):
        d = DimExpr(op="div", args=[100, 0])
        with pytest.raises(ValueError, match="near-zero"):
            evaluate_dim_expr(d.model_dump(), None)

    def test_min(self):
        d = DimExpr(op="min", args=[5, 10, 3, 8])
        assert evaluate_dim_expr(d.model_dump(), None) == 3.0

    def test_max(self):
        d = DimExpr(op="max", args=[5, 10, 3, 8])
        assert evaluate_dim_expr(d.model_dump(), None) == 10.0

    def test_abs(self):
        d = DimExpr(op="abs", args=[-42])
        assert evaluate_dim_expr(d.model_dump(), None) == 42.0

    def test_clamp(self):
        d = DimExpr(op="clamp", args=[150, 0, 100])
        assert evaluate_dim_expr(d.model_dump(), None) == 100.0

    def test_clamp_below(self):
        d = DimExpr(op="clamp", args=[-10, 0, 100])
        assert evaluate_dim_expr(d.model_dump(), None) == 0.0

    def test_unknown_ref_in_chain_returns_none(self):
        """If any ref in an expression chain is unknown, result is None."""
        store = _make_store()
        # (radius_max of n1) + (radius_max of n999) → None
        d = DimExpr(op="add", args=[
            DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", path=["radius_max_mm"]).model_dump()]).model_dump(),
            DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n999", path=["radius_max_mm"]).model_dump()]).model_dump(),
        ])
        assert evaluate_dim_expr(d.model_dump(), store) is None

    def test_empty_path_returns_none(self):
        store = _make_store()
        d = DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", output="body", path=[]).model_dump()])
        assert evaluate_dim_expr(d.model_dump(), store) is None


# ═══════════════════════════════════════════════════════════════
# Nested expressions with ref
# ═══════════════════════════════════════════════════════════════

class TestDimExprNested:
    def test_pcd_from_radius_minus_margin(self):
        """PCD = outer_diameter - 2*margin"""
        store = _make_store()
        # radius_max * 2 - 2*1.0 = 100 - 2 = 98
        d = DimExpr(op="sub", args=[
            DimExpr(op="mul", args=[
                DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", path=["radius_max_mm"]).model_dump()]).model_dump(),
                2,
            ]).model_dump(),
            2.0,
        ])
        assert evaluate_dim_expr(d.model_dump(), store) == 98.0

    def test_bore_within_outer(self):
        """center_bore_dia = outer_radius * 0.6"""
        store = _make_store()
        d = DimExpr(op="mul", args=[
            DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", path=["radius_max_mm"]).model_dump()]).model_dump(),
            0.6,
        ])
        assert evaluate_dim_expr(d.model_dump(), store) == 30.0

    def test_hole_pcd_from_extra(self):
        """PCD = center_bore_radius * 2 + clearance"""
        store = _make_store()
        d = DimExpr(op="add", args=[
            DimExpr(op="mul", args=[
                DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", path=["extra", "center_bore_radius_mm"]).model_dump()]).model_dump(),
                2,
            ]).model_dump(),
            10.0,
        ])
        assert evaluate_dim_expr(d.model_dump(), store) == 40.0


# ═══════════════════════════════════════════════════════════════
# Recursion guard
# ═══════════════════════════════════════════════════════════════

class TestDimExprRecursion:
    def test_recursion_limit(self):
        """Deeply nested expression should raise ValueError."""
        # Build a chain of add(add(add(...))) beyond MAX_RECURSION_DEPTH
        inner = DimExpr(op="const", args=[1])
        d = inner
        for _ in range(20):
            d = DimExpr(op="add", args=[d.model_dump(), 0])
        with pytest.raises(ValueError, match="recursion"):
            evaluate_dim_expr(d.model_dump(), None)


# ═══════════════════════════════════════════════════════════════
# resolve_typed_params_dim_exprs
# ═══════════════════════════════════════════════════════════════

class TestResolveTypedParams:
    def test_resolves_dim_expr_in_params(self):
        store = _make_store()
        params = {
            "diameter_mm": DimExpr(op="mul", args=[
                DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", path=["radius_max_mm"]).model_dump()]).model_dump(),
                0.6,
            ]).model_dump(),
            "depth_mm": 10,
            "label": "test",
        }
        resolved = resolve_typed_params_dim_exprs(params, store)
        assert resolved["diameter_mm"] == 30.0
        assert resolved["depth_mm"] == 10
        assert resolved["label"] == "test"

    def test_unknown_ref_kept_as_is(self):
        store = _make_store()
        params = {
            "diameter_mm": DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n999", path=["radius_max_mm"]).model_dump()]).model_dump(),
        }
        resolved = resolve_typed_params_dim_exprs(params, store)
        # Unknown ref remains as dict (unresolved)
        assert isinstance(resolved["diameter_mm"], dict)

    def test_non_dim_expr_dict_preserved(self):
        params = {"profile_stations": [{"r_mm": 50, "z_front_mm": 0}]}
        resolved = resolve_typed_params_dim_exprs(params, None)
        assert resolved == params

    def test_nested_list_with_dim_expr(self):
        store = _make_store()
        params = {
            "holes": [
                {"dia": DimExpr(op="ref", args=[RefPath(root_kind="node", root_id="n1", path=["radius_max_mm"]).model_dump()]).model_dump()},
                10,
            ]
        }
        resolved = resolve_typed_params_dim_exprs(params, store)
        assert resolved["holes"][0]["dia"] == 50.0
        assert resolved["holes"][1] == 10
