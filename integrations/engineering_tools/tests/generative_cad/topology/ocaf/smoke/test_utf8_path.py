"""Smoke test: UTF-8 path encoding for OCAF documents.

Verifies §2.1 of the v3.0 implementation guide:
  - ext_utf8() constructs correct TCollection_ExtendedString
  - Chinese path SaveAs + Retrieve works
  - ASCII path SaveAs + Retrieve works
  - Same-process save + subprocess retrieve both work

Root cause #2 from diagnostic phase: TCollection_ExtendedString(str) without
isMultiByte=True silently corrupts non-ASCII paths. These tests lock in the fix.
"""

import json
import subprocess
import sys
from pathlib import Path

# Compute source directory relative to this test file.
# test file: .../engineering_tools/tests/generative_cad/topology/ocaf/smoke/test_utf8_path.py
# src dir:   .../engineering_tools/src/
_SRC_DIR = str(Path(__file__).resolve().parents[5] / "src")


class TestUtf8PathEncoding:
    """Verify ext_utf8() and path round-trip correctness."""

    def test_ext_utf8_constructs_ascii(self):
        """ext_utf8 with ASCII path produces valid TCollection_ExtendedString."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import ext_utf8

        result = ext_utf8("C:/tmp/test.xbf")
        assert result is not None
        # Verify it's usable: Length > 0
        assert result.Length() > 0

    def test_ext_utf8_constructs_chinese(self):
        """ext_utf8 with Chinese path produces valid TCollection_ExtendedString."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import ext_utf8

        result = ext_utf8("C:/tmp/测试文档.xbf")
        assert result is not None
        assert result.Length() > 0

    def test_ext_utf8_accepts_pathlib(self):
        """ext_utf8 accepts pathlib.Path."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import ext_utf8

        p = Path("C:/tmp/测试.xbf")
        result = ext_utf8(p)
        assert result.Length() > 0


class TestAsciiPathRoundTrip:
    """Save and retrieve with pure ASCII paths."""

    def test_save_and_retrieve_ascii(self, xbf_path_ascii):
        """Create document, save to ASCII path, retrieve and verify."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import (
            OcafRepository,
        )

        # Create and save
        repo = OcafRepository.create()
        repo.save_to(xbf_path_ascii)
        assert xbf_path_ascii.exists()
        assert xbf_path_ascii.stat().st_size > 100  # should have real content

        # Retrieve in same process (use separate repo instance to avoid session cache)
        repo2 = OcafRepository.open(xbf_path_ascii)
        assert repo2.design_root_label is not None
        assert not repo2.design_root_label.IsNull()

    def test_save_and_retrieve_subprocess(self, xbf_path_ascii):
        """Save to ASCII path, verify in independent subprocess."""
        from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import (
            OcafRepository,
        )

        repo = OcafRepository.create()
        repo.save_to(xbf_path_ascii)

        # Verify in subprocess
        code = f'''
import json
import sys
sys.path.insert(0, r"{_SRC_DIR}")

from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import OcafRepository

repo = OcafRepository.open(r"{xbf_path_ascii}")
# Verify DesignRoot
assert not repo.design_root_label.IsNull()
assert repo.design_root_label.Tag() == 100

# Verify structural children
for tag in [1, 2, 3, 4, 5, 6, 7]:
    child = repo.design_root_label.FindChild(tag, False)
    # Children created via OcafDocumentSession.create(); OcafRepository.create() doesn't auto-create them
    # Just verify we can search without crash

result = {{"status": "ok", "design_root_tag": repo.design_root_label.Tag()}}
print(json.dumps(result))
'''
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        assert result["status"] == "ok"
        assert result["design_root_tag"] == 100


class TestChinesePathRoundTrip:
    """Save and retrieve with Chinese character paths."""

    def test_save_and_retrieve_chinese_subprocess(self, xbf_path_chinese):
        """Save to Chinese path, verify in independent subprocess.

        This is the critical regression test for diagnostic root cause #2:
        TCollection_ExtendedString(str) without isMultiByte=True.
        """
        from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import (
            OcafRepository,
        )

        repo = OcafRepository.create()
        repo.save_to(xbf_path_chinese)
        assert xbf_path_chinese.exists()
        assert xbf_path_chinese.stat().st_size > 100

        # Verify in subprocess
        code = f'''
import json
import sys
sys.path.insert(0, r"{_SRC_DIR}")

from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import OcafRepository

repo = OcafRepository.open(r"{xbf_path_chinese}")
assert not repo.design_root_label.IsNull()
assert repo.design_root_label.Tag() == 100
result = {{"status": "ok", "tag": repo.design_root_label.Tag()}}
print(json.dumps(result))
'''
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        assert result["status"] == "ok"
        assert result["tag"] == 100
