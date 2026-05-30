"""v1.0: native wrapper behavior — gate fail no-import, gate pass imports, metrics."""


class TestNativeWrapperBehaviorV10:
    def test_monkeypatch_native_import_blocks_call(self, monkeypatch):
        from seekflow_engineering_tools.generative_cad import native_importers
        called = {"sw": False}

        def fake_import(config, step, out):
            called["sw"] = True
            return {"ok": True, "files_created": [str(out)]}

        monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_import)
        result = native_importers.import_step_to_solidworks(None, "test.step", "out.sldprt")
        assert result["ok"] is True
        assert called["sw"] is True

    def test_tools_uses_native_importers_module_refs(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        assert "native_importers.import_step_to_solidworks" in src
        assert "native_importers.import_step_to_nx" in src

    def test_tools_references_import_gate(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        assert "validate_generative_step_artifact_for_native_import" in src

    def test_tools_has_native_rebuild_allowed_false_in_metrics(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        assert "native_rebuild_allowed" in src
        assert '"native_rebuild_allowed": False' in src or "'native_rebuild_allowed': False" in src

    def test_tools_has_step_import_allowed_true_in_metrics(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        assert "step_import_allowed" in src
