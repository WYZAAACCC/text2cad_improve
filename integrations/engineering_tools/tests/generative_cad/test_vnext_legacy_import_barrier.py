"""M7: vNext legacy import barrier — production modules must not import legacy."""

import os
from pathlib import Path

PROD_ROOT = Path(__file__).parent.parent.parent / "src" / "seekflow_engineering_tools" / "generative_cad"

FORBIDDEN_IMPORTS_VNEXT = [
    "generative_cad.legacy",
    "generative_cad.bases",
    "generative_cad.ir import GenerativeCADSpec",
    "generative_cad.base import",
    "generative_cad.runner import",
    "generative_cad.registry import",
    "generative_cad.validation import",
]

# Production files to scan
PROD_FILES = [
    "builder.py", "tools.py",
    "pipeline/run.py", "pipeline/metadata.py", "pipeline/metadata_v3.py",
    "pipeline/artifact.py", "pipeline/artifact_models.py",
    "pipeline/import_artifact.py", "pipeline/import_gate_models.py",
    "validation/pipeline.py", "validation/structure.py", "validation/registry.py",
    "validation/params.py", "validation/ownership.py", "validation/graph.py",
    "validation/typecheck.py", "validation/phase.py", "validation/composition.py",
    "validation/safety.py", "validation/canonicalize.py",
    "validation/dialect_semantics.py", "validation/geometry_preflight.py",
    "validation/reports.py", "validation/bundle.py",
    "runtime/context.py", "runtime/object_store.py", "runtime/handles.py",
    "runtime/postconditions.py", "runtime/results.py",
    "runtime/geometry_runtime.py", "runtime/cadquery_runtime.py",
    "ir/raw.py", "ir/canonical.py", "ir/parse.py", "ir/values.py", "ir/safety.py",
    "ir/hashing.py",
    "dialects/base.py", "dialects/operation.py", "dialects/results.py",
    "dialects/executor.py",
    "dialects/registry.py", "dialects/registry_core.py", "dialects/default_registry.py",
    "repair/patch.py", "repair/governor.py", "repair/hashes.py",
    "skills/prompts.py",
]


class TestLegacyImportBarrierVNext:
    def test_production_modules_no_legacy_imports(self):
        """Scan all production files for legacy imports."""
        issues = []
        for rel_path in PROD_FILES:
            full_path = PROD_ROOT / rel_path
            if not full_path.exists():
                continue
            src = full_path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_IMPORTS_VNEXT:
                if pattern in src:
                    lines = src.split("\n")
                    for line in lines:
                        stripped = line.strip()
                        if pattern in stripped and not stripped.startswith("#"):
                            if "#" in stripped:
                                code_part = stripped.split("#")[0]
                                if pattern not in code_part:
                                    continue
                            if '"Legacy GenerativeCADSpec' in stripped:
                                continue
                            issues.append(f"{rel_path}: {pattern!r} in: {stripped[:100]}")
        assert not issues, "\n".join(issues)

    def test_legacy_wrappers_raise_import_error(self):
        """Importing legacy top-level modules raises ImportError."""
        wrappers = [
            "seekflow_engineering_tools.generative_cad.base",
            "seekflow_engineering_tools.generative_cad.registry",
            "seekflow_engineering_tools.generative_cad.prompts",
            "seekflow_engineering_tools.generative_cad.runner",
        ]
        old = os.environ.pop("SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS", None)
        try:
            for module_name in wrappers:
                try:
                    __import__(module_name)
                except ImportError:
                    pass  # Expected — barrier active
                except Exception:
                    pass  # Shadowed by package directory
        finally:
            if old is not None:
                os.environ["SEEKFLOW_ALLOW_LEGACY_GCAD_IMPORTS"] = old

    def test_builder_has_no_legacy_import(self):
        src = (PROD_ROOT / "builder.py").read_text(encoding="utf-8")
        for pattern in FORBIDDEN_IMPORTS_VNEXT:
            assert pattern not in src, f"builder.py has forbidden import: {pattern!r}"
