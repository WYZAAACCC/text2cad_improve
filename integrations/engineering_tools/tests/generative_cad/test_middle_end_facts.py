"""Phase 1: ShapeFacts tests for axisymmetric + composition fact rules.

Tests verify:
- revolve_profile produces correct radius/bbox/faces
- cut_center_bore propagates facts + adds inner_cylindrical face
- cut_circular_hole_pattern detects feasibility violations
- cut_annular_groove detects feasibility violations
- boolean_cut detects disjoint/containment warnings
- middle-end disable path works
- canonical_graph_hash is not affected

No OCP/CadQuery required — all tests are pure data tests.
"""

import os
from pathlib import Path
import sys

import pytest

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from seekflow_engineering_tools.generative_cad.ir.canonical import (
    CanonicalComponent,
    CanonicalGcadDocument,
    CanonicalNode,
    CanonicalSelectedDialect,
    CanonicalValueDecl,
    CanonicalValueRef,
)
from seekflow_engineering_tools.generative_cad.ir.raw import RawConstraints, RawSafety
from seekflow_engineering_tools.generative_cad.analysis.facts import (
    FactStore,
    NumericFact,
    ShapeFacts,
)
from seekflow_engineering_tools.generative_cad.analysis.fact_rules import (
    rule_revolve_profile,
    rule_cut_center_bore,
    rule_cut_circular_hole_pattern,
    rule_cut_annular_groove,
    rule_translate_solid,
    rule_boolean_union,
    rule_boolean_cut,
    FACT_RULES,
)
from seekflow_engineering_tools.generative_cad.compiler.pass_manager import (
    build_compiler_module,
)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_node(id, op, dialect="axisymmetric", component="c1", phase="base_solid",
               inputs=None, outputs=None, params=None, typed_params=None):
    return CanonicalNode(
        id=id, component=component, dialect=dialect, op=op,
        op_version="1.0.0", phase=phase,
        inputs=inputs or [],
        outputs=outputs or [CanonicalValueDecl(name="body", type="solid", value_id=f"solid:{component}:{id}:body")],
        params=params or {},
        typed_params=typed_params or (params or {}),
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
# revolve_profile
# ═══════════════════════════════════════════════════════════════

class TestRevolveProfileFacts:
    def test_single_station_cylinder(self):
        node = _make_node("n1", "revolve_profile", params={
            "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
        })
        facts = rule_revolve_profile(node, "c1")
        assert facts.radius_max_mm.value == 50.0
        assert facts.radius_min_mm.value == 50.0
        assert facts.bbox.xlen_mm.value == 100.0
        assert facts.bbox.ylen_mm.value == 100.0
        assert facts.bbox.zlen_mm.value == 20.0
        assert "closed_candidate" in facts.traits
        assert "axisymmetric" in facts.traits
        assert "z_axis" in facts.traits

    def test_multi_station_stepped_shaft(self):
        node = _make_node("n1", "revolve_profile", params={
            "profile_stations": [
                {"r_mm": 30, "z_front_mm": 0, "z_rear_mm": 10},
                {"r_mm": 50, "z_front_mm": 10, "z_rear_mm": 30},
                {"r_mm": 20, "z_front_mm": 30, "z_rear_mm": 50},
            ],
        })
        facts = rule_revolve_profile(node, "c1")
        assert facts.radius_max_mm.value == 50.0
        assert facts.radius_min_mm.value == 20.0
        assert facts.bbox.zlen_mm.value == 50.0  # 0 to 50

    def test_faces_generated(self):
        node = _make_node("n1", "revolve_profile", params={
            "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
        })
        facts = rule_revolve_profile(node, "c1")
        assert "top" in facts.faces
        assert "bottom" in facts.faces
        assert "outer_cylindrical" in facts.faces
        assert facts.faces["top"].surface_type == "plane"
        assert facts.faces["outer_cylindrical"].surface_type == "cylinder"

    def test_empty_stations(self):
        node = _make_node("n1", "revolve_profile", params={"profile_stations": []})
        facts = rule_revolve_profile(node, "c1")
        assert "no profile stations" in facts.notes[0]
        assert facts.radius_max_mm.value is None

    def test_invalid_radii(self):
        node = _make_node("n1", "revolve_profile", params={
            "profile_stations": [{"r_mm": -5, "z_front_mm": 0, "z_rear_mm": 10}],
        })
        facts = rule_revolve_profile(node, "c1")
        assert facts.radius_max_mm.value is None


# ═══════════════════════════════════════════════════════════════
# cut_center_bore
# ═══════════════════════════════════════════════════════════════

class TestCutCenterBoreFacts:
    def test_bore_propagates_facts(self):
        n1 = _make_node("n1", "revolve_profile", params={
            "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
        })
        n2 = _make_node("n2", "cut_center_bore", phase="primary_cut",
            inputs=[CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid")],
            params={"diameter_mm": 40},
        )
        store = FactStore()
        facts_n1 = rule_revolve_profile(n1, "c1")
        store.bind("n1", "body", facts_n1)

        facts_n2 = rule_cut_center_bore(n2, "c1", store)
        assert facts_n2.radius_max_mm.value == 50.0
        assert facts_n2.extra["center_bore_radius_mm"] == 20.0
        assert "inner_cylindrical" in facts_n2.faces
        assert facts_n2.derived_from == [facts_n1.value_id]

    def test_bore_gt_outer_radius_error(self):
        n1 = _make_node("n1", "revolve_profile", params={
            "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
        })
        n2 = _make_node("n2", "cut_center_bore", phase="primary_cut",
            inputs=[CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid")],
            params={"diameter_mm": 110},
        )
        store = FactStore()
        store.bind("n1", "body", rule_revolve_profile(n1, "c1"))

        facts_n2 = rule_cut_center_bore(n2, "c1", store)
        error_notes = [n for n in facts_n2.notes if "FEASIBILITY ERROR" in n]
        assert len(error_notes) == 1
        assert "geometrically impossible" in error_notes[0]

    def test_bore_within_margin_warning(self):
        n1 = _make_node("n1", "revolve_profile", params={
            "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
        })
        n2 = _make_node("n2", "cut_center_bore", phase="primary_cut",
            inputs=[CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid")],
            params={"diameter_mm": 99},  # bore_r=49.5, wall=0.5 < margin=1.0
        )
        store = FactStore()
        store.bind("n1", "body", rule_revolve_profile(n1, "c1"))

        facts_n2 = rule_cut_center_bore(n2, "c1", store)
        warn_notes = [n for n in facts_n2.notes if "FEASIBILITY WARNING" in n]
        assert len(warn_notes) == 1
        assert "0.5mm" in warn_notes[0]


# ═══════════════════════════════════════════════════════════════
# cut_circular_hole_pattern
# ═══════════════════════════════════════════════════════════════

class TestCutCircularHolePatternFacts:
    def test_hole_pattern_valid(self):
        n1 = _make_node("n1", "revolve_profile", params={
            "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
        })
        n2 = _make_node("n2", "cut_center_bore", phase="primary_cut",
            inputs=[CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid")],
            params={"diameter_mm": 30},
        )
        n3 = _make_node("n3", "cut_circular_hole_pattern", phase="pattern_cut",
            inputs=[CanonicalValueRef(producer_node="n2", output="body", resolved_type="solid")],
            params={"count": 6, "pcd_mm": 60, "hole_dia_mm": 10},
        )
        store = FactStore()
        store.bind("n1", "body", rule_revolve_profile(n1, "c1"))
        store.bind("n2", "body", rule_cut_center_bore(n2, "c1", store))

        facts_n3 = rule_cut_circular_hole_pattern(n3, "c1", store)
        error_notes = [n for n in facts_n3.notes if "FEASIBILITY ERROR" in n]
        assert len(error_notes) == 0  # pcd/2=30, hole_r=5 → inner=25 > bore_r(15)+1=16, outer=35 < 50-1=49

    def test_hole_intersects_bore_error(self):
        n1 = _make_node("n1", "revolve_profile", params={
            "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
        })
        n2 = _make_node("n2", "cut_center_bore", phase="primary_cut",
            inputs=[CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid")],
            params={"diameter_mm": 80},  # bore r=40
        )
        n3 = _make_node("n3", "cut_circular_hole_pattern", phase="pattern_cut",
            inputs=[CanonicalValueRef(producer_node="n2", output="body", resolved_type="solid")],
            params={"count": 6, "pcd_mm": 80, "hole_dia_mm": 10},  # PCD=80 → inner=40-5=35 < bore_r(40)+1=41
        )
        store = FactStore()
        store.bind("n1", "body", rule_revolve_profile(n1, "c1"))
        store.bind("n2", "body", rule_cut_center_bore(n2, "c1", store))

        facts_n3 = rule_cut_circular_hole_pattern(n3, "c1", store)
        error_notes = [n for n in facts_n3.notes if "FEASIBILITY ERROR" in n]
        assert len(error_notes) == 1
        assert "intersect" in error_notes[0].lower() or "bore radius" in error_notes[0].lower()

    def test_hole_outside_profile_error(self):
        n1 = _make_node("n1", "revolve_profile", params={
            "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
        })
        n2 = _make_node("n2", "cut_circular_hole_pattern", phase="pattern_cut",
            inputs=[CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid")],
            params={"count": 6, "pcd_mm": 90, "hole_dia_mm": 10},  # pcd/2+hole_r=45+5=50 >= 50-margin=49
        )
        store = FactStore()
        store.bind("n1", "body", rule_revolve_profile(n1, "c1"))

        facts_n2 = rule_cut_circular_hole_pattern(n2, "c1", store)
        error_notes = [n for n in facts_n2.notes if "FEASIBILITY ERROR" in n]
        assert len(error_notes) == 1


# ═══════════════════════════════════════════════════════════════
# cut_annular_groove
# ═══════════════════════════════════════════════════════════════

class TestCutAnnularGrooveFacts:
    def test_groove_outside_profile_error(self):
        n1 = _make_node("n1", "revolve_profile", params={
            "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
        })
        n2 = _make_node("n2", "cut_annular_groove", phase="annular_detail",
            inputs=[CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid")],
            params={"side": "front", "inner_dia_mm": 80, "outer_dia_mm": 100, "depth_mm": 3},
        )
        store = FactStore()
        store.bind("n1", "body", rule_revolve_profile(n1, "c1"))

        facts_n2 = rule_cut_annular_groove(n2, "c1", store)
        error_notes = [n for n in facts_n2.notes if "FEASIBILITY ERROR" in n]
        assert len(error_notes) == 1  # outer_r=50 >= 50-margin=49


# ═══════════════════════════════════════════════════════════════
# boolean_cut
# ═══════════════════════════════════════════════════════════════

class TestBooleanCutFacts:
    def test_cut_propagates_target_facts(self):
        n1 = _make_node("n1", "revolve_profile", dialect="axisymmetric", params={
            "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
        })
        n2 = _make_node("n2", "revolve_profile", dialect="axisymmetric", params={
            "profile_stations": [{"r_mm": 30, "z_front_mm": 0, "z_rear_mm": 10}],
        })
        n3 = _make_node("n3", "boolean_cut", dialect="composition", phase="boolean",
            inputs=[
                CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid"),
                CanonicalValueRef(producer_node="n2", output="body", resolved_type="solid"),
            ],
        )
        store = FactStore()
        store.bind("n1", "body", rule_revolve_profile(n1, "c1"))
        store.bind("n2", "body", rule_revolve_profile(n2, "c2"))

        facts_n3 = rule_boolean_cut(n3, "c_assembly", store)
        assert "modified_by_boolean_cut" in facts_n3.traits
        assert facts_n3.radius_max_mm.value == 50.0  # from target n1

    def test_disjoint_bbox_warns(self):
        n1 = _make_node("n1", "revolve_profile", dialect="axisymmetric", params={
            "profile_stations": [{"r_mm": 10, "z_front_mm": 0, "z_rear_mm": 5}],
        })
        n2 = _make_node("n2", "revolve_profile", dialect="axisymmetric", params={
            "profile_stations": [{"r_mm": 10, "z_front_mm": 100, "z_rear_mm": 105}],  # z at 100, far from n1
        })
        n3 = _make_node("n3", "boolean_cut", dialect="composition", phase="boolean",
            inputs=[
                CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid"),
                CanonicalValueRef(producer_node="n2", output="body", resolved_type="solid"),
            ],
        )
        store = FactStore()
        store.bind("n1", "body", rule_revolve_profile(n1, "c1"))
        store.bind("n2", "body", rule_revolve_profile(n2, "c2"))

        facts_n3 = rule_boolean_cut(n3, "c_assembly", store)
        warn_notes = [n for n in facts_n3.notes if "WARNING" in n]
        assert len(warn_notes) >= 1
        assert any("no-op" in n for n in warn_notes)


# ═══════════════════════════════════════════════════════════════
# Middle-end pipeline integration
# ═══════════════════════════════════════════════════════════════

class TestMiddleEndIntegration:
    def test_enabled_produces_facts(self):
        canonical = _make_canonical([
            _make_node("n1", "revolve_profile", params={
                "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
            }),
        ])
        os.environ["SEEKFLOW_GCAD_ENABLE_MIDDLE_END"] = "1"
        module = build_compiler_module(canonical)
        assert module.facts is not None
        facts = module.facts.get_node_output("n1", "body")
        assert facts is not None
        assert facts.radius_max_mm.value == 50.0

    def test_disabled_skips_facts(self):
        canonical = _make_canonical([
            _make_node("n1", "revolve_profile", params={
                "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
            }),
        ])
        os.environ["SEEKFLOW_GCAD_ENABLE_MIDDLE_END"] = "0"
        module = build_compiler_module(canonical)
        assert module.facts is None
        assert any("middle_end_disabled" in d["code"] for d in module.diagnostics)

    def test_feasibility_error_makes_module_not_ok(self):
        canonical = _make_canonical([
            _make_node("n1", "revolve_profile", params={
                "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
            }),
            _make_node("n2", "cut_center_bore", phase="primary_cut",
                inputs=[CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid")],
                params={"diameter_mm": 110},
            ),
        ])
        os.environ["SEEKFLOW_GCAD_ENABLE_MIDDLE_END"] = "1"
        module = build_compiler_module(canonical)
        assert module.ok is False
        assert any(
            d["severity"] == "error" and "FEASIBILITY" in d["message"]
            for d in module.diagnostics
        )

    def test_valid_case_module_ok(self):
        canonical = _make_canonical([
            _make_node("n1", "revolve_profile", params={
                "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
            }),
            _make_node("n2", "cut_center_bore", phase="primary_cut",
                inputs=[CanonicalValueRef(producer_node="n1", output="body", resolved_type="solid")],
                params={"diameter_mm": 30},
            ),
            _make_node("n3", "cut_circular_hole_pattern", phase="pattern_cut",
                inputs=[CanonicalValueRef(producer_node="n2", output="body", resolved_type="solid")],
                params={"count": 6, "pcd_mm": 60, "hole_dia_mm": 10},
            ),
        ])
        os.environ["SEEKFLOW_GCAD_ENABLE_MIDDLE_END"] = "1"
        module = build_compiler_module(canonical)
        assert module.ok is True
        assert module.facts is not None
        # All three nodes should have facts
        assert module.facts.get_node_output("n1", "body") is not None
        assert module.facts.get_node_output("n2", "body") is not None
        assert module.facts.get_node_output("n3", "body") is not None

    def test_canonical_graph_hash_not_affected(self):
        """Verify middle-end does not modify CanonicalGcadDocument."""
        canonical = _make_canonical([
            _make_node("n1", "revolve_profile", params={
                "profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}],
            }),
        ])
        original_hash = canonical.canonical_graph_hash
        os.environ["SEEKFLOW_GCAD_ENABLE_MIDDLE_END"] = "1"
        _module = build_compiler_module(canonical)
        assert canonical.canonical_graph_hash == original_hash
        # Node params should be untouched
        assert canonical.nodes[0].params == {"profile_stations": [{"r_mm": 50, "z_front_mm": 0, "z_rear_mm": 20}]}
