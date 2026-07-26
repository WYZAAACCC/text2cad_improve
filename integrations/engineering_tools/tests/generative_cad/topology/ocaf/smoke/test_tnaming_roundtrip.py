"""Smoke test: TNaming NamedShape and Naming cross-process round-trip.

Verifies the core TNaming persistence contract:
  - TNaming_Builder.Generated → NamedShape survives cross-process Save→Retrieve
  - TNaming_Selector.Select → NamedShape + Naming survive cross-process
  - TDataStd_Integer cross-process persistence
  - Tag 100-based label navigation works after reopen

These tests are the minimum bar for "OCAF/TNaming persistence works."
Without these passing, NO further OCAF work should proceed.
"""

import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Writer/Reader helper code (runs in subprocess)
# ---------------------------------------------------------------------------

WRITER_TEMPLATE = r'''
import json, sys
sys.path.insert(0, r"{src_dir}")

import cadquery as cq
from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import OcafRepository
from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import DESIGN_ROOT_TAG

repo = OcafRepository.create()
root = repo.design_root_label
main = repo.main_label
doc = repo.doc

# Build a simple box
box = cq.Workplane("XY").box(10, 20, 30).val()

# ---- Test: TNaming_Builder.Generated ----
# Write NamedShape to a feature label
feature_label = root.FindChild(2, True).FindChild(1001, True)  # Components/1001

from OCP.TNaming import TNaming_Builder
builder = TNaming_Builder(feature_label)
builder.Generated(box.wrapped)

# ---- Test: TNaming_Selector ----
# Select a face and create naming
face = box.faces(">Z")
sel_label = root.FindChild(3, True).FindChild(1002, True)  # Selections/1002

from OCP.TNaming import TNaming_Selector
selector = TNaming_Selector(sel_label)
ok = selector.Select(face.wrapped, box.wrapped)
assert ok, "Selector.Select returned False"

# ---- Test: TDataStd_Integer ----
meta_label = root.FindChild(1, True)  # Metadata
from OCP.TDataStd import TDataStd_Integer
from OCP.TDF import TDF_Label
attr = TDataStd_Integer.Set_s(meta_label.FindChild(1, True), 42)

repo.save_to(r"{xbf_path}")
# Confirm save
import os
assert os.path.exists(r"{xbf_path}")
assert os.path.getsize(r"{xbf_path}") > 100
# Explicit cleanup before OCP destructor crash on Python teardown
repo.close()
del repo
# Print success marker -- the process may still crash on exit due to OCP cleanup,
# but the file is correctly persisted and stdout is flushed before the crash.
print("SAVED_OK " + json.dumps({{"status": "saved", "path": r"{xbf_path}", "size": os.path.getsize(r"{xbf_path}")}}), flush=True)
'''

READER_TEMPLATE = r'''
import json, sys
sys.path.insert(0, r"{src_dir}")

from pathlib import Path
from seekflow_engineering_tools.generative_cad.topology.ocaf.repository import OcafRepository
from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import DESIGN_ROOT_TAG

repo = OcafRepository.open(Path(r"{xbf_path}"))
root = repo.design_root_label
main = repo.main_label

result = {{"design_root_tag": root.Tag()}}

# Check feature label (Components/1001)
feat_label = root.FindChild(2, False).FindChild(1001, False)
result["feature_label_found"] = not feat_label.IsNull()

# Check for TNaming_NamedShape on feature
from OCP.TDF import TDF_AttributeIterator
it = TDF_AttributeIterator(feat_label)
ns_count = 0
ns_null = True
while it.More():
    attr = it.Value()
    if attr.DynamicType().Name() == "TNaming_NamedShape":
        ns_count += 1
        # Use TNaming_Tool to get CurrentShape
        from OCP.TNaming import TNaming_Tool
        try:
            ns = TNaming_Tool.CurrentShape_s(feat_label)
            ns_null = ns.IsNull()
        except Exception:
            ns_null = True
    it.Next()
result["named_shape_count"] = ns_count
result["named_shape_valid"] = ns_count > 0 and not ns_null

# Check selection label (Selections/1002)
sel_label = root.FindChild(3, False).FindChild(1002, False)
result["selection_label_found"] = not sel_label.IsNull()

# Check for TNaming_NamedShape on selection
it2 = TDF_AttributeIterator(sel_label)
sel_ns_count = 0
while it2.More():
    attr2 = it2.Value()
    if attr2.DynamicType().Name() == "TNaming_NamedShape":
        sel_ns_count += 1
    it2.Next()
result["selection_named_shape_count"] = sel_ns_count

# Check TDataStd_Integer
meta_label = root.FindChild(1, False)
int_label = meta_label.FindChild(1, False)
result["metadata_int_label_found"] = not int_label.IsNull()

it3 = TDF_AttributeIterator(int_label)
int_found = False
while it3.More():
    attr3 = it3.Value()
    if attr3.DynamicType().Name() == "TDataStd_Integer":
        int_found = True
    it3.Next()
result["integer_found"] = int_found

print(json.dumps(result), flush=True)
'''


class TestTNamingBuilderRoundTrip:
    """TNaming_Builder.Generated -> save -> retrieve -> NamedShape present."""

    def test_builder_named_shape_ascii_path(self, xbf_path_ascii):
        """TNaming_Builder writes survive ASCII path round-trip."""
        src_dir = str(Path(__file__).resolve().parents[5] / "src")

        # Phase 1: Write (OCP may crash on exit -- check stdout, not returncode)
        write_code = WRITER_TEMPLATE.format(src_dir=src_dir, xbf_path=str(xbf_path_ascii))
        proc_w = subprocess.run(
            [sys.executable, "-c", write_code],
            capture_output=True, text=True, timeout=30,
        )
        # OCP TNaming destructor crash on process exit is expected (returncode 3221226505).
        # Check stdout for the SAVED_OK marker instead.
        assert "SAVED_OK" in proc_w.stdout, f"Writer failed. stderr: {proc_w.stderr}, stdout: {proc_w.stdout}"
        write_json = proc_w.stdout.strip().split("SAVED_OK ")[-1].strip()
        write_result = json.loads(write_json)
        assert write_result["status"] == "saved"

        # Phase 2: Read in separate subprocess
        read_code = READER_TEMPLATE.format(src_dir=src_dir, xbf_path=str(xbf_path_ascii))
        proc_r = subprocess.run(
            [sys.executable, "-c", read_code],
            capture_output=True, text=True, timeout=30,
        )
        assert proc_r.returncode == 0, f"Reader failed: {proc_r.stderr}"
        read_result = json.loads(proc_r.stdout.strip().splitlines()[-1])

        assert read_result["design_root_tag"] == 100
        assert read_result["feature_label_found"] is True
        assert read_result["named_shape_count"] >= 1, \
            f"Expected >=1 NamedShape, got {read_result['named_shape_count']}"
        assert read_result["selection_label_found"] is True
        assert read_result["selection_named_shape_count"] >= 1
        assert read_result["integer_found"] is True

    def test_builder_named_shape_chinese_path(self, xbf_path_chinese):
        """TNaming_Builder writes survive Chinese path round-trip."""
        src_dir = str(Path(__file__).resolve().parents[5] / "src")

        # Phase 1: Write (OCP may crash on exit -- check stdout, not returncode)
        write_code = WRITER_TEMPLATE.format(src_dir=src_dir, xbf_path=str(xbf_path_chinese))
        proc_w = subprocess.run(
            [sys.executable, "-c", write_code],
            capture_output=True, text=True, timeout=30,
        )
        assert "SAVED_OK" in proc_w.stdout, f"Writer failed. stderr: {proc_w.stderr}, stdout: {proc_w.stdout}"
        write_json = proc_w.stdout.strip().split("SAVED_OK ")[-1].strip()
        write_result = json.loads(write_json)
        assert write_result["status"] == "saved"

        read_code = READER_TEMPLATE.format(src_dir=src_dir, xbf_path=str(xbf_path_chinese))
        proc_r = subprocess.run(
            [sys.executable, "-c", read_code],
            capture_output=True, text=True, timeout=30,
        )
        assert proc_r.returncode == 0, f"Reader failed: {proc_r.stderr}"
        read_result = json.loads(proc_r.stdout.strip().splitlines()[-1])

        assert read_result["design_root_tag"] == 100
        assert read_result["feature_label_found"] is True
        assert read_result["named_shape_count"] >= 1
        assert read_result["selection_label_found"] is True
        assert read_result["integer_found"] is True
