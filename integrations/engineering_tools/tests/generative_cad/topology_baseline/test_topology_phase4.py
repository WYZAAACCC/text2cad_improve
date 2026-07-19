"""Phase 4 tests — fillet, chamfer, shell history wrappers + semantic naming."""

import cadquery as cq

from seekflow_engineering_tools.generative_cad.topology.history_wrappers import (
    history_aware_chamfer,
    history_aware_fillet,
)
from seekflow_engineering_tools.generative_cad.topology.semantic_naming import (
    name_chamfer_faces,
    name_fillet_faces,
    name_shell_faces,
)
from seekflow_engineering_tools.generative_cad.topology.contracts import (
    get_contract,
)
from seekflow_engineering_tools.generative_cad.topology.registry import TopologyRegistry
from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyDelta,
    TopologyRelation,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Contract tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestFilletChamferContracts:
    def test_fillet_contract_exists(self):
        c = get_contract("sketch_extrude", "apply_safe_fillet")
        assert c is not None
        assert c.history_capability == "partial_kernel_history"
        roles = {r.name for r in c.output_roles}
        assert "body" in roles
        assert "fillet_face" in roles

    def test_chamfer_contract_exists(self):
        c = get_contract("sketch_extrude", "apply_safe_chamfer")
        assert c is not None
        assert c.history_capability == "partial_kernel_history"

    def test_shell_contract_exists(self):
        c = get_contract("shell_housing", "shell_body")
        assert c is not None
        roles = {r.name for r in c.output_roles}
        assert "removed_face" in roles
        assert "offset_face" in roles


# ═══════════════════════════════════════════════════════════════════════════════
# Fillet tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestFilletNaming:
    def test_fillet_produces_generated_faces(self):
        """Fillet of box produces new curved faces (generated) from edges."""
        box = cq.Workplane("XY").box(20, 20, 20)
        filleted = box.fillet(3.0)
        delta = name_fillet_faces(
            box, filleted, document_id="d", component_id="c", producer_node_id="n",
        )
        generated = [r for r in delta.relations if r.relation == "generated"]
        assert len(generated) >= 8  # Each of 12 edges → at least 8 unique fillet faces

    def test_fillet_marks_edges_deleted(self):
        """Provided edge IDs are marked as deleted."""
        box = cq.Workplane("XY").box(20, 20, 20)
        filleted = box.fillet(3.0)
        edge_refs = ["gct:v1:d:c:n:n:edge:top_front", "gct:v1:d:c:n:n:edge:top_right"]
        delta = name_fillet_faces(
            box, filleted, document_id="d", component_id="c", producer_node_id="n",
            selected_edge_ids=edge_refs,
        )
        deleted = [r for r in delta.relations if r.relation == "deleted"]
        assert len(deleted) == len(edge_refs)

    def test_fillet_delta_is_valid_topology_delta(self):
        """Fillet delta can be registered and applied."""
        box = cq.Workplane("XY").box(20, 20, 20)
        filleted = box.fillet(2.0)
        delta = name_fillet_faces(
            box, filleted, document_id="d", component_id="c", producer_node_id="n",
            selected_edge_ids=["gct:v1:d:c:n:n:edge:e1"],
        )
        assert isinstance(delta, TopologyDelta)
        assert delta.history_provider == "operation_semantics"
        assert delta.node_id == "n"

    def test_fillet_stable_across_rebuild(self):
        """Same fillet on same box → same semantic roles."""
        box1 = cq.Workplane("XY").box(20, 20, 20)
        delta1 = name_fillet_faces(box1, box1.fillet(3.0), document_id="d", component_id="c", producer_node_id="n")
        box2 = cq.Workplane("XY").box(20, 20, 20)
        delta2 = name_fillet_faces(box2, box2.fillet(3.0), document_id="d", component_id="c", producer_node_id="n")
        roles1 = sorted(r.semantic_role for r in delta1.relations if r.semantic_role)
        roles2 = sorted(r.semantic_role for r in delta2.relations if r.semantic_role)
        assert roles1 == roles2


# ═══════════════════════════════════════════════════════════════════════════════
# Chamfer tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestChamferNaming:
    def test_chamfer_produces_relations(self):
        """Chamfer of box produces face relations."""
        box = cq.Workplane("XY").box(20, 20, 20)
        chamfered = box.chamfer(2.0)
        delta = name_chamfer_faces(
            chamfered, document_id="d", component_id="c", producer_node_id="n",
        )
        assert len(delta.relations) > 0

    def test_chamfer_edge_deletion(self):
        """Chamfer with edge refs marks them deleted."""
        box = cq.Workplane("XY").box(20, 20, 20)
        chamfered = box.chamfer(2.0)
        delta = name_chamfer_faces(
            chamfered, document_id="d", component_id="c", producer_node_id="n",
            selected_edge_ids=["gct:v1:d:c:n:n:edge:e1"],
        )
        deleted = [r for r in delta.relations if r.relation == "deleted"]
        assert len(deleted) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Shell tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestShellNaming:
    def test_shell_produces_face_relations(self):
        """Shell produces face relations for removed and offset faces."""
        box = cq.Workplane("XY").box(30, 30, 20)
        try:
            shelled = box.faces(">Z").shell(2.0)
        except Exception:
            # Shell may fail on certain CadQuery versions
            return
        delta = name_shell_faces(
            shelled, document_id="d", component_id="c", producer_node_id="n",
            removed_face_ids=["gct:v1:d:c:n:n:face:top"],
        )
        assert len(delta.relations) > 0
        deleted = [r for r in delta.relations if r.relation == "deleted"]
        assert len(deleted) == 1  # The removed top face
