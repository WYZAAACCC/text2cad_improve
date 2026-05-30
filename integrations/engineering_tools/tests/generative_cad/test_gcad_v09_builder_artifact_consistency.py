"""v0.9: builder artifact consistency — extended checks for paths, flags, dialects."""


class TestBuilderArtifactConsistencyV09:
    def test_builder_checks_native_rebuild_allowed(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        assert "native_rebuild_allowed" in src

    def test_builder_checks_step_import_allowed(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        assert "step_import_allowed" in src

    def test_builder_checks_step_path(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        assert "step_path mismatch" in src or 'artifact.get("step_path")' in src

    def test_builder_checks_metadata_path(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        assert "metadata_path mismatch" in src or 'artifact.get("metadata_path")' in src

    def test_builder_checks_selected_dialects(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        assert "selected_dialects mismatch" in src or "artifact_dialects" in src
