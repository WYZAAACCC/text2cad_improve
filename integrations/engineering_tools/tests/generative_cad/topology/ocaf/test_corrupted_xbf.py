"""v6.0 PR-8: Corrupted XBF hardening tests (v6.0 §11.3).

All corrupt file handling must NOT crash — subprocess isolation is key.
"""

import struct

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.verify_worker import verify_xbf


class TestCorruptedXbf:

    def test_empty_file(self, ascii_tmpdir):
        """Empty file → verify returns not-ok, no crash."""
        p = ascii_tmpdir / "empty.xbf"
        p.write_bytes(b"")
        result = verify_xbf(p)
        assert not result.ok

    def test_random_garbage(self, ascii_tmpdir):
        """Random bytes → verify returns not-ok, no crash."""
        import os
        p = ascii_tmpdir / "random.xbf"
        p.write_bytes(os.urandom(256))
        result = verify_xbf(p)
        assert not result.ok

    def test_truncated_valid_header(self, ascii_tmpdir):
        """8-byte valid XBF header only → verify returns not-ok."""
        session = OcafDocumentSession.create()
        session.ensure_component("test")
        tmp = session.save_temp()
        session.close()

        full = tmp.read_bytes()
        truncated = full[:16]  # just header
        p = ascii_tmpdir / "truncated.xbf"
        p.write_bytes(truncated)
        result = verify_xbf(p)
        assert not result.ok
        try:
            tmp.unlink()
        except Exception:
            pass

    def test_too_small(self, ascii_tmpdir):
        """File smaller than 8 bytes → rejected early."""
        p = ascii_tmpdir / "tiny.xbf"
        p.write_bytes(b"\x00\x01\x02")
        result = verify_xbf(p)
        assert not result.ok

    def test_valid_xbf_after_corrupt(self, ascii_tmpdir):
        """Valid XBF after a corrupt one → verify returns ok."""
        session = OcafDocumentSession.create()
        session.ensure_component("test_comp")
        session.label_index.save_to_ocaf(session.main_label)
        valid_path = ascii_tmpdir / "valid.xbf"
        session.repository.save_to(valid_path)
        session.close()

        # Verify corrupt first
        corrupt = ascii_tmpdir / "corrupt.xbf"
        corrupt.write_bytes(b"\x00" * 128)
        assert not verify_xbf(corrupt).ok

        # Verify valid after corrupt (no cross-contamination)
        result = verify_xbf(valid_path)
        assert result.ok
        assert result.design_root_present
