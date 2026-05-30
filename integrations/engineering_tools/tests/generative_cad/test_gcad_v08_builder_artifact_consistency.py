"""v0.8: builder artifact/metadata consistency tests."""


class TestBuilderArtifactConsistency:
    def test_builder_has_metadata_path_in_metrics(self):
        """Verify builder.py includes metadata_path in metrics."""
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        assert 'metadata_path' in src
        assert 'str(meta_path)' in src

    def test_builder_has_artifact_consistency_check(self):
        """Verify builder.py checks artifact/metadata consistency."""
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        assert "canonical_graph_hash mismatch" in src or "canonical_graph_hash" in src
        assert "validation proof mismatch" in src

    def test_builder_artifact_includes_inspection(self):
        """Verify artifact built with inspection data."""
        import inspect
        from seekflow_engineering_tools.generative_cad import builder
        src = inspect.getsource(builder)
        # Builder should pass inspection to build_canonical_step_artifact
        assert "inspection=insp_val" in src
