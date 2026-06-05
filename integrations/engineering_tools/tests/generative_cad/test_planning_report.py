"""Phase 3: PlanningReport tests.

Tests verify:
- Hole pattern batching opportunity (count >= 8)
- Large pattern risk warning (count >= 120)
- Many destructive ops warning (>= 32 cuts_material ops)
- Edge treatment too early warning
- Planner integration with CompilerModule
- PlanningReport appears in metadata

All tests are pure data tests — no OCP/CadQuery needed.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from seekflow_engineering_tools.generative_cad.ir.canonical import (
    CanonicalComponent,
    CanonicalGcadDocument,
    CanonicalNode,
    CanonicalSelectedDialect,
    CanonicalValueDecl,
)
from seekflow_engineering_tools.generative_cad.ir.raw import RawConstraints, RawSafety
from seekflow_engineering_tools.generative_cad.planning.planner import PlannerPass
from seekflow_engineering_tools.generative_cad.planning.planning_report import PlanningIssue
from seekflow_engineering_tools.generative_cad.compiler.module import CompilerModule
from seekflow_engineering_tools.generative_cad.compiler.pass_manager import build_compiler_module


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_node(id, op, dialect="axisymmetric", component="c1", phase="base_solid",
               inputs=None, outputs=None, params=None, operation_effects=None):
    return CanonicalNode(
        id=id, component=component, dialect=dialect, op=op,
        op_version="1.0.0", phase=phase,
        inputs=inputs or [],
        outputs=outputs or [CanonicalValueDecl(name="body", type="solid", value_id=f"solid:{component}:{id}:body")],
        params=params or {},
        typed_params=params or {},
        operation_effects=operation_effects or [],
    )


def _make_canonical(nodes, components=None):
    return CanonicalGcadDocument(
        document_id="test", part_name="test",
        selected_dialects=[CanonicalSelectedDialect(dialect="axisymmetric", version="0.2.0", contract_hash="sha256:test")],
        components=components or [CanonicalComponent(id="c1", owner_dialect="axisymmetric", root_node=nodes[-1].id)],
        nodes=nodes,
        constraints=RawConstraints(require_step_file=True, require_metadata_sidecar=True, require_closed_solid=True, expected_body_count=1),
        safety=RawSafety(non_flight_reference_only=True, not_airworthy=True, not_certified=True, not_for_manufacturing=True, not_for_installation=True, no_structural_validation=True, no_life_prediction=True),
        canonical_graph_hash="sha256:test",
    )


# ═══════════════════════════════════════════════════════════════
# Planner rule tests
# ═══════════════════════════════════════════════════════════════

class TestPlannerPatternBatching:
    def test_small_pattern_no_report(self):
        """count=4: no planning issue."""
        node = _make_node("n1", "cut_circular_hole_pattern", phase="pattern_cut",
            params={"count": 4, "pcd_mm": 60, "hole_dia_mm": 10},
        )
        canonical = _make_canonical([node])
        module = CompilerModule(canonical=canonical)
        planner = PlannerPass()
        module = planner.run(module)
        assert module.planning_report is not None
        report = module.planning_report
        assert len(report.get("issues", [])) == 0

    def test_medium_pattern_batching_opportunity(self):
        """count=32: batching opportunity."""
        node = _make_node("n1", "cut_circular_hole_pattern", phase="pattern_cut",
            params={"count": 32, "pcd_mm": 100, "hole_dia_mm": 8},
        )
        canonical = _make_canonical([node])
        module = CompilerModule(canonical=canonical)
        planner = PlannerPass()
        module = planner.run(module)
        report = module.planning_report
        issues = report.get("issues", [])
        codes = [i["code"] for i in issues]
        assert "hole_pattern_should_batch" in codes

    def test_large_pattern_warning(self):
        """count=200: large pattern risk warning (subsumes batching opportunity)."""
        node = _make_node("n1", "cut_circular_hole_pattern", phase="pattern_cut",
            params={"count": 200, "pcd_mm": 200, "hole_dia_mm": 5},
        )
        canonical = _make_canonical([node])
        module = CompilerModule(canonical=canonical)
        planner = PlannerPass()
        module = planner.run(module)
        report = module.planning_report
        codes = [i["code"] for i in report.get("issues", [])]
        # large_pattern_risk is the dominant warning; batch opportunity is subsumed
        assert "large_pattern_risk" in codes

    def test_linear_pattern_batching(self):
        """10x10=100 grid: batching opportunity."""
        node = _make_node("n1", "cut_hole_pattern_linear", phase="hole_pattern",
            dialect="sketch_extrude",
            params={"count_x": 10, "count_y": 10, "spacing_x_mm": 10, "spacing_y_mm": 10, "hole_dia_mm": 5},
        )
        canonical = _make_canonical([node])
        module = CompilerModule(canonical=canonical)
        planner = PlannerPass()
        module = planner.run(module)
        codes = [i["code"] for i in module.planning_report.get("issues", [])]
        assert "hole_pattern_should_batch" in codes

    def test_rim_slot_pattern_batching(self):
        """count=48: batching opportunity."""
        node = _make_node("n1", "cut_rim_slot_pattern", phase="rim_detail",
            params={"count": 48, "slot_depth_mm": 5, "slot_profile": {"stations": [{"depth_mm": 5, "half_width_mm": 3}, {"depth_mm": 5, "half_width_mm": 3}]}},
        )
        canonical = _make_canonical([node])
        module = CompilerModule(canonical=canonical)
        planner = PlannerPass()
        module = planner.run(module)
        codes = [i["code"] for i in module.planning_report.get("issues", [])]
        assert "hole_pattern_should_batch" in codes


class TestPlannerDestructiveOps:
    def test_few_ops_no_warning(self):
        """3 destructive ops: no warning."""
        nodes = [
            _make_node("n1", "cut_center_bore", phase="primary_cut",
                params={"diameter_mm": 30},
                operation_effects=["cuts_material"]),
            _make_node("n2", "cut_annular_groove", phase="annular_detail",
                params={"side": "front", "inner_dia_mm": 50, "outer_dia_mm": 70, "depth_mm": 3},
                operation_effects=["cuts_material"]),
            _make_node("n3", "cut_circular_hole_pattern", phase="pattern_cut",
                params={"count": 6, "pcd_mm": 80, "hole_dia_mm": 10},
                operation_effects=["cuts_material"]),
        ]
        canonical = _make_canonical(nodes)
        module = CompilerModule(canonical=canonical)
        planner = PlannerPass()
        module = planner.run(module)
        codes = [i["code"] for i in module.planning_report.get("issues", [])]
        # Only pattern-related codes expected (count=6 < 8 so no pattern issue either)
        assert "many_destructive_ops" not in codes

    def test_many_destructive_ops_warning(self):
        """33 destructive ops: warning."""
        nodes = []
        for i in range(33):
            nodes.append(_make_node(
                f"n{i}", "cut_hole", phase="primary_cut",
                dialect="sketch_extrude",
                params={"diameter_mm": 5, "position_mm": [i * 2, 0]},
                operation_effects=["cuts_material"],
            ))
        # Single component
        canonical = _make_canonical(
            nodes,
            components=[CanonicalComponent(id="c1", owner_dialect="sketch_extrude", root_node=f"n{32}")],
        )
        module = CompilerModule(canonical=canonical)
        planner = PlannerPass()
        module = planner.run(module)
        codes = [i["code"] for i in module.planning_report.get("issues", [])]
        assert "many_destructive_ops" in codes


class TestPlannerEdgeTreatment:
    def test_edge_treatment_last_no_warning(self):
        """Chamfer is the last operation: no warning."""
        nodes = [
            _make_node("n1", "extrude_rectangle", dialect="sketch_extrude", phase="base_solid",
                params={"width_mm": 100, "height_mm": 80, "depth_mm": 20},
                operation_effects=["creates_solid"]),
            _make_node("n2", "cut_hole", dialect="sketch_extrude", phase="primary_cut",
                params={"diameter_mm": 10, "position_mm": [0, 0]},
                operation_effects=["cuts_material"]),
            _make_node("n3", "apply_safe_chamfer", dialect="sketch_extrude", phase="edge_treatment",
                params={"distance_mm": 2},
                operation_effects=["modifies_solid"]),
        ]
        canonical = _make_canonical(
            nodes,
            components=[CanonicalComponent(id="c1", owner_dialect="sketch_extrude", root_node="n3")],
        )
        module = CompilerModule(canonical=canonical)
        planner = PlannerPass()
        module = planner.run(module)
        codes = [i["code"] for i in module.planning_report.get("issues", [])]
        assert "edge_treatment_too_early" not in codes

    def test_edge_treatment_before_destructive_warning(self):
        """Chamfer before a destructive op: warning."""
        nodes = [
            _make_node("n1", "extrude_rectangle", dialect="sketch_extrude", phase="base_solid",
                params={"width_mm": 100, "height_mm": 80, "depth_mm": 20},
                operation_effects=["creates_solid"]),
            _make_node("n2", "apply_safe_fillet", dialect="sketch_extrude", phase="edge_treatment",
                params={"radius_mm": 5},
                operation_effects=["modifies_solid"]),
            _make_node("n3", "cut_rectangular_pocket", dialect="sketch_extrude", phase="primary_cut",
                params={"width_mm": 50, "height_mm": 40, "depth_mm": 10},
                operation_effects=["cuts_material"]),
        ]
        canonical = _make_canonical(
            nodes,
            components=[CanonicalComponent(id="c1", owner_dialect="sketch_extrude", root_node="n3")],
        )
        module = CompilerModule(canonical=canonical)
        planner = PlannerPass()
        module = planner.run(module)
        codes = [i["code"] for i in module.planning_report.get("issues", [])]
        assert "edge_treatment_too_early" in codes


class TestPlannerIntegration:
    def test_full_pipeline_produces_planning_report(self):
        """build_compiler_module runs PlannerPass and produces report."""
        nodes = [
            _make_node("n1", "revolve_profile", phase="base_solid",
                params={"profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}]},
                operation_effects=["creates_solid"]),
            _make_node("n2", "cut_circular_hole_pattern", phase="pattern_cut",
                params={"count": 36, "pcd_mm": 80, "hole_dia_mm": 8},
                operation_effects=["cuts_material"]),
        ]
        canonical = _make_canonical(nodes)
        os.environ["SEEKFLOW_GCAD_ENABLE_MIDDLE_END"] = "1"
        module = build_compiler_module(canonical)
        assert module.planning_report is not None
        report = module.planning_report
        assert len(report.get("optimization_opportunities", [])) >= 1
        # Check both passes ran
        assert "fact_propagation" in module.enabled_passes
        assert "planning" in module.enabled_passes

    def test_disabled_skips_planner(self):
        """When middle-end disabled, no planning report."""
        nodes = [
            _make_node("n1", "revolve_profile", phase="base_solid",
                params={"profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}]},
                operation_effects=["creates_solid"]),
        ]
        canonical = _make_canonical(nodes)
        os.environ["SEEKFLOW_GCAD_ENABLE_MIDDLE_END"] = "0"
        module = build_compiler_module(canonical)
        assert module.planning_report == {} or module.planning_report is None
        assert "planning" not in module.enabled_passes
