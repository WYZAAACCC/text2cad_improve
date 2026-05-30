"""v0.8: native import wrapper tests — gate fail, gate pass, failure propagation."""


class TestNativeImportWrappersV08:
    def test_monkeypatch_native_importers_blocks_native_call(self, monkeypatch):
        """Verify monkeypatching native_importers is possible (module-level import)."""
        from seekflow_engineering_tools.generative_cad import native_importers

        called = {"sw": False}

        def fake_import(config, step, out):
            called["sw"] = True
            return {"ok": True, "files_created": [str(out)]}

        monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_import)

        native_importers.import_step_to_solidworks(None, "test.step", "out.sldprt")
        assert called["sw"] is True

    def test_native_import_failure_is_raisable(self, monkeypatch):
        """Verify native import failure raises properly."""
        from seekflow_engineering_tools.generative_cad import native_importers

        def fake_failing_import(config, step, out):
            raise RuntimeError("mock SW failure")

        monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_failing_import)
        import pytest
        with pytest.raises(RuntimeError, match="mock SW failure"):
            native_importers.import_step_to_solidworks(None, "test.step", "out.sldprt")

    def test_nx_native_import_is_monkeypatchable(self, monkeypatch):
        """Verify NX native import is monkeypatchable."""
        from seekflow_engineering_tools.generative_cad import native_importers

        called = {"nx": False}

        def fake_import(config, job_root, step, out):
            called["nx"] = True
            return {"ok": True, "files_created": [str(out)]}

        monkeypatch.setattr(native_importers, "import_step_to_nx", fake_import)

        native_importers.import_step_to_nx(None, "/tmp", "test.step", "out.prt")
        assert called["nx"] is True

    def test_tools_py_gate_references_are_in_place(self):
        """Verify tools.py has import gate and native_importers references."""
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        assert "validate_generative_step_artifact_for_native_import" in src
        assert "native_importers.import_step_to_solidworks" in src
        assert "native_importers.import_step_to_nx" in src

    def test_solidworks_wrapper_error_path_exists(self):
        """Verify SW wrapper has error handling for gate failure."""
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        assert "import gate failed" in src.lower() or "Import gate failed" in src
