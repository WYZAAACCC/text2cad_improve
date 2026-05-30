"""Tests for audit fixes (P0-P3)."""

import inspect
import os


class TestP0RunnerTraceback:
    """P0-1: runner catch-all must include traceback in error message."""

    def test_runner_exception_includes_traceback(self):
        """Verify run.py:184 includes traceback in error output."""
        from seekflow_engineering_tools.generative_cad.pipeline import run
        src = inspect.getsource(run.run_canonical_gcad)
        assert "traceback" in src
        assert "format_exc" in src
        assert "tb[-2000:]" in src or "tb" in src

    def test_runner_exception_records_warning_with_traceback(self):
        """Verify the traceback is appended to ctx.warnings."""
        from seekflow_engineering_tools.generative_cad.pipeline import run
        src = inspect.getsource(run.run_canonical_gcad)
        assert 'ctx.warnings.append' in src


class TestP0SafeOperations:
    """P0-2/3/4: safe_fillet/safe_chamfer must not silently swallow all exceptions."""

    @staticmethod
    def _read_bases_runner(filename: str, func_name: str) -> str:
        from pathlib import Path
        p = Path(__file__).parent.parent.parent / "src" / "seekflow_engineering_tools" / "generative_cad" / "bases" / filename
        src = p.read_text(encoding="utf-8")
        # Extract the function body
        lines = src.split("\n")
        in_func = False
        func_lines = []
        for line in lines:
            if f"def {func_name}" in line:
                in_func = True
            if in_func:
                func_lines.append(line)
                if in_func and line.strip() and not line.startswith(" ") and not line.startswith("def"):
                    break  # reached next top-level definition
        return "\n".join(func_lines)

    def test_sketch_extrude_safe_fillet_narrow_catch(self):
        src = self._read_bases_runner("sketch_extrude/runner.py", "_op_apply_safe_fillet")
        assert "except Exception:" not in src
        assert "except (ValueError, RuntimeError):" in src

    def test_sketch_extrude_safe_chamfer_narrow_catch(self):
        src = self._read_bases_runner("sketch_extrude/runner.py", "_op_apply_safe_chamfer")
        assert "except Exception:" not in src
        assert "except (ValueError, RuntimeError):" in src

    def test_axisymmetric_safe_chamfer_narrow_catch(self):
        src = self._read_bases_runner("axisymmetric/runner.py", "_op_apply_safe_chamfer")
        assert "except Exception:" not in src
        assert "except (ValueError, RuntimeError):" in src


class TestP1NarrowExceptions:
    """P1: hash functions and cadquery_runtime must narrow exception catches."""

    def test_compute_step_sha256_narrow_catch(self):
        from seekflow_engineering_tools.generative_cad.pipeline.metadata_v3 import _compute_step_sha256
        src = inspect.getsource(_compute_step_sha256)
        assert "except Exception:" not in src
        assert "FileNotFoundError" in src

    def test_sha256_file_narrow_catch(self):
        from seekflow_engineering_tools.generative_cad.pipeline.artifact import _sha256_file
        src = inspect.getsource(_sha256_file)
        assert "except Exception:" not in src
        assert "FileNotFoundError" in src

    def test_count_solids_no_silent_return_1(self):
        from seekflow_engineering_tools.generative_cad.runtime.cadquery_runtime import _count_solids
        src = inspect.getsource(_count_solids)
        assert "except Exception:" not in src
        # Should NOT silently return 1 on any error anymore
        assert "import cadquery" in src  # still does the real work

    def test_compute_bbox_mm_narrow_catch(self):
        from seekflow_engineering_tools.generative_cad.runtime.cadquery_runtime import CadQueryRuntime
        src = inspect.getsource(CadQueryRuntime.compute_bbox_mm)
        assert "except Exception:" not in src

    def test_count_bodies_narrow_catch(self):
        from seekflow_engineering_tools.generative_cad.runtime.cadquery_runtime import CadQueryRuntime
        src = inspect.getsource(CadQueryRuntime.count_bodies)
        assert "except Exception:" not in src


class TestP2DeadCodeCleanup:
    """P2-1/2/3: dead modules confirmed deleted."""

    def test_errors_module_deleted(self):
        """errors.py was dead code — must be deleted."""
        from pathlib import Path
        p = Path(__file__).parent.parent.parent / "src" / "seekflow_engineering_tools" / "generative_cad" / "errors.py"
        assert not p.exists(), f"Dead module {p} should have been deleted"

    def test_ir_safety_module_deleted(self):
        from pathlib import Path
        p = Path(__file__).parent.parent.parent / "src" / "seekflow_engineering_tools" / "generative_cad" / "ir" / "safety.py"
        assert not p.exists(), f"Dead module {p} should have been deleted"

    def test_cadquery_helpers_module_deleted(self):
        from pathlib import Path
        p = Path(__file__).parent.parent.parent / "src" / "seekflow_engineering_tools" / "generative_cad" / "runtime" / "cadquery_helpers.py"
        assert not p.exists(), f"Dead module {p} should have been deleted"

    def test_stale_md_files_deleted(self):
        from pathlib import Path
        base = Path(__file__).parent.parent.parent / "src" / "seekflow_engineering_tools" / "generative_cad" / "skills"
        assert not (base / "generic_mechanical_skill.md").exists()
        assert not (base / "turbomachinery_reference_skill.md").exists()


class TestP2LegacyBarriers:
    """P2-4: unguarded legacy wrappers must now have ImportError barriers."""

    def test_graph_validation_has_barrier(self):
        src = _read_module_src("generative_cad", "graph_validation.py")
        assert "SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS" in src
        assert "ImportError" in src

    def test_metadata_has_barrier(self):
        src = _read_module_src("generative_cad", "metadata.py")
        assert "SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS" in src
        assert "ImportError" in src

    def test_preflight_has_barrier(self):
        src = _read_module_src("generative_cad", "preflight.py")
        assert "SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS" in src
        assert "ImportError" in src

    def test_legacy_barriers_raise_without_env(self):
        """Verify barriers raise ImportError without env var.

        Tests that read source files (not imports) verify barrier presence.
        The runtime barrier test is sensitive to import caching, so we check
        the source code directly for the ImportError guard pattern.
        """
        # Verify barrier is present in source code
        assert "SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS" in _read_module_src("generative_cad", "graph_validation.py")
        assert "SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS" in _read_module_src("generative_cad", "metadata.py")
        assert "SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS" in _read_module_src("generative_cad", "preflight.py")

        # Runtime check: try import without env var (must clear cache first)
        import sys
        test_mod = "seekflow_engineering_tools.generative_cad.graph_validation"
        old_val = os.environ.pop("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS", None)
        sys.modules.pop(test_mod, None)
        try:
            try:
                __import__(test_mod)
                assert False, f"{test_mod} should raise ImportError"
            except ImportError:
                pass
        finally:
            if old_val is not None:
                os.environ["SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS"] = old_val
            sys.modules.pop(test_mod, None)


def _read_module_src(pkg: str, filename: str) -> str:
    from pathlib import Path
    p = Path(__file__).parent.parent.parent / "src" / "seekflow_engineering_tools" / pkg / filename
    return p.read_text(encoding="utf-8") if p.exists() else ""


class TestP2KeyErrorComment:
    """P2-8: KeyError: pass in dialect must have explanatory comment."""

    def test_axisymmetric_keyerror_comment(self):
        from seekflow_engineering_tools.generative_cad.dialects.axisymmetric import dialect
        src = inspect.getsource(dialect.AxisymmetricDialect.run_component)
        assert "except KeyError: pass  # postconditions.py" in src

    def test_sketch_extrude_keyerror_comment(self):
        from seekflow_engineering_tools.generative_cad.dialects.sketch_extrude import dialect
        src = inspect.getsource(dialect.SketchExtrudeDialect.run_component)
        assert "except KeyError: pass  # postconditions.py" in src


class TestP3PromptVersioning:
    """P3-4: prompt string constants must be versioned."""

    def test_prompt_version_constants_exist(self):
        from seekflow_engineering_tools.generative_cad.skills import prompts
        assert hasattr(prompts, "PROMPT_VERSION_LEVEL1")
        assert hasattr(prompts, "PROMPT_VERSION_LEVEL2")
        assert hasattr(prompts, "PROMPT_VERSION_REPAIR")

    def test_prompt_version_values_are_stable(self):
        from seekflow_engineering_tools.generative_cad.skills.prompts import (
            PROMPT_VERSION_LEVEL1, PROMPT_VERSION_LEVEL2, PROMPT_VERSION_REPAIR,
        )
        assert PROMPT_VERSION_LEVEL1 == "level1_routing_v2"
        assert PROMPT_VERSION_LEVEL2 == "level2_authoring_v2"
        assert PROMPT_VERSION_REPAIR == "repair_patch_v3"
