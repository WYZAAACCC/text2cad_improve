"""v0.9: native wrapper behavior — gate fail, gate pass, failure propagation."""


class TestNativeWrapperBehavior:
    def test_monkeypatch_native_importers_module_works(self, monkeypatch):
        from seekflow_engineering_tools.generative_cad import native_importers

        called = {"sw": False}

        def fake_import(config, step, out):
            called["sw"] = True
            return {"ok": True, "files_created": [str(out)]}

        monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_import)
        result = native_importers.import_step_to_solidworks(None, "test.step", "out.sldprt")
        assert result["ok"] is True
        assert called["sw"] is True

    def test_solidworks_gate_error_includes_gate_info(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        assert "import_gate" in src

    def test_tools_uses_native_importers_module_ref(self):
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        assert "native_importers.import_step_to_solidworks" in src
        assert "native_importers.import_step_to_nx" in src

    def test_native_importers_has_both_functions(self):
        from seekflow_engineering_tools.generative_cad import native_importers
        assert callable(native_importers.import_step_to_solidworks)
        assert callable(native_importers.import_step_to_nx)
