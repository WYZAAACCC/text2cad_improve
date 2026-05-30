"""P2: GeometryRuntime ABI tests."""


class TestGeometryRuntimeABI:
    def test_geometry_runtime_protocol_exists(self):
        from seekflow_engineering_tools.generative_cad.runtime.geometry_runtime import GeometryRuntime
        from typing import Protocol
        assert issubclass(GeometryRuntime, Protocol)

    def test_cadquery_runtime_is_runtime_checkable(self):
        from seekflow_engineering_tools.generative_cad.runtime.cadquery_runtime import CadQueryRuntime
        from seekflow_engineering_tools.generative_cad.runtime.geometry_runtime import GeometryRuntime
        assert isinstance(CadQueryRuntime(), GeometryRuntime)

    def test_runtime_context_owns_geometry_runtime(self):
        from pathlib import Path
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        ctx = RuntimeContext(
            out_step=Path("/tmp/out.step"),
            metadata_path=Path("/tmp/out.metadata.json"),
            workspace_root=Path("/tmp"),
        )
        assert hasattr(ctx, "geometry_runtime")
        assert ctx.geometry_runtime_name == "cadquery"

    def test_runtime_context_defaults_to_cadquery_runtime(self):
        from pathlib import Path
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        from seekflow_engineering_tools.generative_cad.runtime.cadquery_runtime import CadQueryRuntime
        ctx = RuntimeContext(
            out_step=Path("/tmp/out.step"),
            metadata_path=Path("/tmp/out.metadata.json"),
            workspace_root=Path("/tmp"),
        )
        assert isinstance(ctx.geometry_runtime, CadQueryRuntime)

    def test_mock_runtime_usable(self):
        from pathlib import Path
        from seekflow_engineering_tools.generative_cad.runtime.geometry_runtime import GeometryRuntime

        class MockRuntime:
            runtime_id = "mock"
            runtime_version = "mock_v1"
            export_calls: list = []

            def export_step(self, solid_obj, out_step):
                self.export_calls.append((solid_obj, out_step))
                out_step.write_text("MOCK STEP")

            def inspect_solid(self, solid_obj):
                return {"mock": True}

            def validate_closed_solid(self, solid_obj):
                return {"ok": True}

            def compute_bbox_mm(self, solid_obj):
                return [1.0, 2.0, 3.0]

            def count_bodies(self, solid_obj):
                return 1

        runtime = MockRuntime()
        assert isinstance(runtime, GeometryRuntime)
        assert runtime.runtime_id == "mock"

    def test_runner_uses_geometry_runtime_export_step(self):
        """Verify _export_final_solid calls ctx.geometry_runtime.export_step."""
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import run
        src = inspect.getsource(run._export_final_solid)
        assert "geometry_runtime.export_step" in src
        assert "import cadquery" not in src

    def test_metadata_records_runtime_info(self):
        """Metadata records geometry_runtime from ctx."""
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import metadata
        src = inspect.getsource(metadata.build_generative_metadata)
        assert "geometry_runtime_name" in src or "geometry_runtime" in src

    def test_cadquery_runtime_has_required_id(self):
        from seekflow_engineering_tools.generative_cad.runtime.cadquery_runtime import CadQueryRuntime
        rt = CadQueryRuntime()
        assert rt.runtime_id == "cadquery"
        assert rt.runtime_version == "cadquery_runtime_v1"
