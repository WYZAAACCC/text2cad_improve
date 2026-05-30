"""v0.7: runtime postconditions enhanced tests — root output binding, final object lookup."""


class TestRuntimePostconditionsV07:
    def _make_canonical(self, CanonicalGcadDocument, CanonicalNode, CanonicalComponent):
        """Build a minimal canonical for testing."""
        return CanonicalGcadDocument(
            schema_version="g_cad_core_v0.2",
            canonical_version="canonical_gcad_v0.2",
            document_id="test",
            part_name="test",
            units="mm",
            trust_level="reference_geometry",
            raw_graph_hash="sha256:abc",
            canonical_graph_hash="sha256:def",
            selected_dialects=[],
            components=[
                CanonicalComponent(id="disk", owner_dialect="axisymmetric", root_node="n_body"),
            ],
            nodes=[
                CanonicalNode(
                    id="n_body", component="disk", dialect="axisymmetric",
                    op="revolve_profile", op_version="1.0.0", phase="base_solid",
                    inputs=[],
                    outputs=[{"name": "body", "type": "solid", "value_id": "solid:disk:n_body:body"}],
                    params={}, typed_params={},
                ),
            ],
            constraints={
                "require_step_file": True, "require_metadata_sidecar": True,
                "require_closed_solid": True, "expected_body_count": 1,
                "max_runtime_seconds": 120,
            },
            safety={
                "non_flight_reference_only": True, "not_airworthy": True,
                "not_certified": True, "not_for_manufacturing": True,
                "not_for_installation": True, "no_structural_validation": True,
                "no_life_prediction": True,
            },
        )

    def test_runtime_postconditions_pass_when_root_output_bound(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.runtime.postconditions import validate_runtime_postconditions
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalGcadDocument, CanonicalNode, CanonicalComponent,
        )
        from pathlib import Path

        canonical = self._make_canonical(CanonicalGcadDocument, CanonicalNode, CanonicalComponent)
        ctx = RuntimeContext(
            out_step=Path(tmp_path / "test.step"),
            metadata_path=Path(tmp_path / "test.json"),
            workspace_root=Path(tmp_path),
        )

        # Bind root output
        handle = SolidHandle(id="solid:disk:n_body:body", component_id="disk", producer_node="n_body")
        ctx.object_store.put_solid(handle, "fake_obj")
        ctx.bind_node_output("n_body", "body", "solid:disk:n_body:body")

        result = validate_runtime_postconditions(canonical, ctx, "solid:disk:n_body:body")
        assert result["ok"], f"Expected ok, got: {result['issues']}"

    def test_runtime_postconditions_reject_unbound_root_output(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.runtime.postconditions import validate_runtime_postconditions
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalGcadDocument, CanonicalNode, CanonicalComponent,
        )
        from pathlib import Path

        canonical = self._make_canonical(CanonicalGcadDocument, CanonicalNode, CanonicalComponent)
        ctx = RuntimeContext(
            out_step=Path(tmp_path / "test.step"),
            metadata_path=Path(tmp_path / "test.json"),
            workspace_root=Path(tmp_path),
        )

        # Register handle but do NOT bind node output
        handle = SolidHandle(id="solid:disk:n_body:body", component_id="disk", producer_node="n_body")
        ctx.object_store.put_solid(handle, "fake_obj")
        # ctx.bind_node_output("n_body", "body", ...) — NOT called

        result = validate_runtime_postconditions(canonical, ctx, "solid:disk:n_body:body")
        assert not result["ok"]
        assert any(i["code"] == "component_root_output_not_bound" for i in result["issues"])

    def test_runtime_postconditions_reject_missing_root_node(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.runtime.postconditions import validate_runtime_postconditions
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalGcadDocument, CanonicalNode, CanonicalComponent,
        )
        from pathlib import Path

        canonical = self._make_canonical(CanonicalGcadDocument, CanonicalNode, CanonicalComponent)
        canonical.components[0].root_node = "nonexistent"

        ctx = RuntimeContext(
            out_step=Path(tmp_path / "test.step"),
            metadata_path=Path(tmp_path / "test.json"),
            workspace_root=Path(tmp_path),
        )

        # Set up a valid final handle so we get past the final handle checks
        handle_id = "solid:disk:final:body"
        handle = SolidHandle(id=handle_id, component_id="disk", producer_node="final")
        ctx.object_store.put_solid(handle, "fake_obj")

        result = validate_runtime_postconditions(canonical, ctx, handle_id)
        assert not result["ok"]
        assert any(i["code"] == "component_root_node_not_found" for i in result["issues"])

    def test_runtime_postconditions_reject_final_object_not_retrievable(self, tmp_path):
        from seekflow_engineering_tools.generative_cad.runtime.postconditions import validate_runtime_postconditions
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalGcadDocument, CanonicalNode, CanonicalComponent,
        )
        from pathlib import Path

        canonical = self._make_canonical(CanonicalGcadDocument, CanonicalNode, CanonicalComponent)
        ctx = RuntimeContext(
            out_step=Path(tmp_path / "test.step"),
            metadata_path=Path(tmp_path / "test.json"),
            workspace_root=Path(tmp_path),
        )

        # Handle exists but object is not in store
        result = validate_runtime_postconditions(canonical, ctx, "nonexistent_handle")
        assert not result["ok"]
        assert any(
            i["code"] in ("final_handle_lookup_failed", "final_object_lookup_failed")
            for i in result["issues"]
        )
