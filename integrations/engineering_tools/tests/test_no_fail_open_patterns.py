"""Static regression test — forbid fail-open patterns in source code."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "seekflow_engineering_tools"
DEMO = ROOT / "demo_full_chain.py"


def _read_src_files():
    for path in [DEMO, *SRC.rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        yield path, text


def test_no_validation_get_ok_true():
    forbidden = [
        'validation.get("ok", True)',
        "validation.get('ok', True)",
        'mechanical_validation.get("ok", True)',
        "mechanical_validation.get('ok', True)",
        'mech_val.get("ok", True)',
        "mech_val.get('ok', True)",
        'mv_result.get("ok", True)',
        "mv_result.get('ok', True)",
        'result_payload.get("ok", True)',
        "result_payload.get('ok', True)",
    ]
    for path, text in _read_src_files():
        for pat in forbidden:
            assert pat not in text, f"FAIL-OPEN PATTERN: {pat} found in {path}"


def test_demo_does_not_promote_build_ok_to_overall_ok():
    text = DEMO.read_text(encoding="utf-8")
    assert 'if build_result.get("ok"):' not in text, \
        "demo must not promote build.ok to overall_ok without stage aggregation"
    assert '_finalize_case_report' in text, \
        "demo must use _finalize_case_report for overall_ok determination"


def test_no_tempfile_mktemp():
    for path, text in _read_src_files():
        assert "tempfile.mktemp" not in text, f"tempfile.mktemp found in {path}"


def test_no_registry_importerror_pass():
    reg = SRC / "geometry_primitives" / "registry.py"
    text = reg.read_text(encoding="utf-8")
    assert "except ImportError:\n        pass" not in text, \
        "registry.py must not silently swallow ImportError (fail-closed)"


def test_no_registry_except_importerror_pass_oneline():
    for path, text in _read_src_files():
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped == "except ImportError: pass" or stripped == "except ImportError:pass":
                assert False, f"FAIL-OPEN: 'except ImportError: pass' found in {path}"


def test_no_except_pass_with_importerror():
    """Catch patterns like `except (ImportError, ...):\n    pass`."""
    import re
    for path, text in _read_src_files():
        pattern = r'except\s+(?:\(?\s*ImportError[\s,)]+).*:\s*\n\s+pass'
        matches = re.findall(pattern, text)
        assert not matches, f"FAIL-OPEN: 'except ImportError ... pass' found in {path}"
