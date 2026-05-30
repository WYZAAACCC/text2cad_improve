"""v0.7: run.py metadata consistency tests — validation_seed, raw path full proof."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "generative_cad"


class TestRunMetadataV07:
    def test_run_gcad_core_imports_validate_and_canonicalize_with_bundle(self):
        """Verify run.py imports validate_and_canonicalize_with_bundle, not the old function."""
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import run
        src = inspect.getsource(run)
        assert "validate_and_canonicalize_with_bundle" in src
        # Should not import the old non-bundle version
        assert "from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize\n" not in src

    def test_run_canonical_gcad_accepts_validation_seed(self):
        """Verify run_canonical_gcad accepts validation_seed parameter."""
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad
        sig = inspect.signature(run_canonical_gcad)
        assert "validation_seed" in sig.parameters

    def test_run_gcad_core_passes_bundle_to_canonical_runner(self):
        """Verify that run_gcad_core calls validate_and_canonicalize_with_bundle and passes validation_seed."""
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import run
        src = inspect.getsource(run.run_gcad_core)
        assert "validate_and_canonicalize_with_bundle" in src
        assert "validation_seed" in src
        assert "bundle.to_metadata_dict()" in src

    def test_run_canonical_gcad_uses_validation_seed_for_metadata(self):
        """Verify run_canonical_gcad merges validation_seed into metadata."""
        import inspect
        from seekflow_engineering_tools.generative_cad.pipeline import run
        src = inspect.getsource(run.run_canonical_gcad)
        assert "validation_seed" in src
        assert 'validation["runtime_postconditions"] = runtime_pc' in src
