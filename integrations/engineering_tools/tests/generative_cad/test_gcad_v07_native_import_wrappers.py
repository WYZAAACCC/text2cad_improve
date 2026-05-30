"""v0.7: native import wrapper tests — monkeypatch-friendly module import, gate wiring."""


class TestNativeImportWrappers:
    def test_native_importers_module_is_importable(self):
        """Verify native_importers module exists and exports the expected functions."""
        from seekflow_engineering_tools.generative_cad import native_importers
        assert hasattr(native_importers, "import_step_to_solidworks")
        assert hasattr(native_importers, "import_step_to_nx")

    def test_tools_py_imports_module_not_functions(self):
        """tools.py should import native_importers as a module (monkeypatch-friendly)."""
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        # Module-level import should exist
        assert "from seekflow_engineering_tools.generative_cad import native_importers" in src
        # Direct function imports should NOT exist
        assert "from seekflow_engineering_tools.generative_cad.native_importers import" not in src

    def test_tools_py_calls_via_module_reference(self):
        """tools.py should call native_importers.import_step_to_solidworks (module ref, not local fn)."""
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        assert "native_importers.import_step_to_solidworks" in src
        assert "native_importers.import_step_to_nx" in src

    def test_monkeypatch_native_importers_is_possible(self, monkeypatch):
        """Verify that monkeypatching native_importers functions works."""
        from seekflow_engineering_tools.generative_cad import native_importers

        called = {"sw": False, "nx": False}

        def fake_sw(config, step, out):
            called["sw"] = True
            return {"ok": True, "files_created": [str(out)]}

        def fake_nx(config, job_root, step, out):
            called["nx"] = True
            return {"ok": True, "files_created": [str(out)]}

        monkeypatch.setattr(native_importers, "import_step_to_solidworks", fake_sw)
        monkeypatch.setattr(native_importers, "import_step_to_nx", fake_nx)

        # Call patched functions directly
        result_sw = native_importers.import_step_to_solidworks(None, "test.step", "out.sldprt")
        assert result_sw["ok"] is True
        assert called["sw"] is True

        result_nx = native_importers.import_step_to_nx(None, "/tmp", "test.step", "out.prt")
        assert result_nx["ok"] is True
        assert called["nx"] is True

    def test_import_gate_is_called_from_tool_wrappers(self):
        """Verify the SW/NX tool wrappers reference the import gate function."""
        import inspect
        from seekflow_engineering_tools.generative_cad import tools
        src = inspect.getsource(tools)
        assert "validate_generative_step_artifact_for_native_import" in src
        assert "import_gate" in src
