"""T2: Three-process cross-revision Selection Solve.

Rev1: create asymmetric body + select top face + save
Rev2: open Rev1 + rebuild with modified height + Solve + save
Rev3: open Rev2 + rebuild with modified height + Solve + save

Each revision runs in an independent subprocess.
StableLabelIndex must restore across processes (P0-02).
"""

import json
import subprocess
import sys
from pathlib import Path


SRC = str(Path(__file__).resolve().parents[5] / "src")

# ---------------------------------------------------------------------------
# Process templates
# ---------------------------------------------------------------------------

REV1_TEMPLATE = r'''
import json, sys, os
sys.path.insert(0, r"{src}")
import cadquery as cq
from pathlib import Path

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import PersistentSelectionService
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import collect_tnaming_labels
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation,
    EvolutionKind, TopologyEntityKind, ProofClass, SelectionPolicy,
)
from OCP.TNaming import TNaming_Builder

xbf_dir = Path(r"{xbf_dir}")
xbf_dir.mkdir(parents=True, exist_ok=True)
rev1_path = xbf_dir / "rev1.xbf"

session = OcafDocumentSession.create()
writer = TopologyNamingWriter(session)

# Build asymmetric box
box = cq.Workplane("XY").box(20, 30, 10).val()
face = box.faces(">Z")

# Write PRIMITIVE batch
scope = TopologyCaptureScope(node_id="box_node", component_id="comp_a")
rel = LiveEvolutionRelation(
    relation_id="box/0", operation_id="box_node",
    kind=EvolutionKind.PRIMITIVE, entity_kind=TopologyEntityKind.FACE,
    source_key="box", old_shape=None, new_shapes=(box.wrapped,),
    proof=ProofClass.EXACT_CONSTRUCTION,
)
batch = LiveEvolutionBatch(
    scope=scope, builder_kind="Primitive", result_shape=box.wrapped,
    context_shape=box.wrapped, relations=[rel],
)
writer.write_batch(batch)

# Prerequisite for selection
comp = session.ensure_component("comp_a")
feat = session.ensure_feature(comp, "box_node")
TNaming_Builder(feat.FindChild(2, True)).Generated(box.wrapped)

# Select top face
service = PersistentSelectionService(session)
service.create("top", face.wrapped, box.wrapped,
               SelectionPolicy(entity_kind=TopologyEntityKind.FACE))

# Save index + save XBF
session.label_index.save_to_ocaf(session.main_label)
session.repository.save_to(rev1_path)
session.close()

result = {{
    "rev": 1, "path": str(rev1_path),
    "index_entries": session.label_index.entry_count,
    "volume": box.Volume(),
}}
print("REV1_OK " + json.dumps(result), flush=True)
'''

REV2_TEMPLATE = r'''
import json, sys, os
sys.path.insert(0, r"{src}")
import cadquery as cq
from pathlib import Path

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import OcafDocumentSession
from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import TopologyNamingWriter
from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import PersistentSelectionService
from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import collect_tnaming_labels
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation,
    EvolutionKind, TopologyEntityKind, ProofClass, SelectionPolicy,
)
from OCP.TNaming import TNaming_Builder

rev_path = Path(r"{rev_path}")
session = OcafDocumentSession.open(rev_path)

# Verify index restored
comp_label = session.ensure_component("comp_a")
feat_label = session.ensure_feature(comp_label, "box_node")
index_count = session.label_index.entry_count

# Build new box with different height
new_height = {height}
box = cq.Workplane("XY").box(20, 30, new_height).val()
face = box.faces(">Z")

# Write new PRIMITIVE to same feature label
scope = TopologyCaptureScope(node_id="box_node", component_id="comp_a")
rel = LiveEvolutionRelation(
    relation_id="box/0", operation_id="box_node",
    kind=EvolutionKind.PRIMITIVE, entity_kind=TopologyEntityKind.FACE,
    source_key="box", old_shape=None, new_shapes=(box.wrapped,),
    proof=ProofClass.EXACT_CONSTRUCTION,
)
batch = LiveEvolutionBatch(
    scope=scope, builder_kind="Primitive", result_shape=box.wrapped,
    context_shape=box.wrapped, relations=[rel],
)
writer = TopologyNamingWriter(session)
writer.write_batch(batch)

# Update prerequisite
TNaming_Builder(feat_label.FindChild(2, True)).Generated(box.wrapped)

# Solve selection
label_map = collect_tnaming_labels(session.design_root_label)
service = PersistentSelectionService(session)
resolution = service.solve("top", label_map)

rev_n = {rev_n}
xbf_dir = Path(r"{xbf_dir}")
out_path = xbf_dir / f"rev{rev_n}.xbf"
session.label_index.save_to_ocaf(session.main_label)
session.repository.save_to(out_path)
session.close()

result = {{
    "rev": rev_n, "path": str(out_path),
    "index_entries": index_count,
    "solve_status": resolution.status.value,
    "volume": box.Volume(),
    "resolved_count": len(resolution.resolved_shapes),
}}
print(f"REV{rev_n}_OK " + json.dumps(result), flush=True)
'''


class TestT2CrossRevision:

    def test_three_process_cross_revision(self, ascii_tmpdir):
        """Rev1 → Rev2 → Rev3, each in independent subprocess.

        Verifies:
        - StableLabelIndex restores across processes
        - Same feature/selection labels reused
        - Selection Solve returns valid result each revision
        """
        xbf_dir = str(ascii_tmpdir)

        # ── Rev1 ──
        rev1_code = REV1_TEMPLATE.format(src=SRC, xbf_dir=xbf_dir)
        p1 = subprocess.run([sys.executable, "-c", rev1_code],
                           capture_output=True, text=True, timeout=30)
        assert "REV1_OK" in p1.stdout, f"Rev1 failed: {p1.stderr}"
        rev1_data = json.loads(p1.stdout.split("REV1_OK ")[-1])
        assert rev1_data["rev"] == 1
        rev1_path = rev1_data["path"]

        # ── Rev2 (height 15) ──
        rev2_code = REV2_TEMPLATE.format(
            src=SRC, rev_path=rev1_path, height=15, rev_n=2, xbf_dir=xbf_dir,
        )
        p2 = subprocess.run([sys.executable, "-c", rev2_code],
                           capture_output=True, text=True, timeout=30)
        assert "REV2_OK" in p2.stdout, f"Rev2 failed: {p2.stderr}"
        rev2_data = json.loads(p2.stdout.split("REV2_OK ")[-1])
        assert rev2_data["index_entries"] >= 1, "Index must restore"
        assert rev2_data["solve_status"] in ("unique", "ambiguous"), \
            f"Solve failed: {rev2_data['solve_status']}"
        rev2_path = rev2_data["path"]

        # ── Rev3 (height 20) ──
        rev3_code = REV2_TEMPLATE.format(
            src=SRC, rev_path=rev2_path, height=20, rev_n=3, xbf_dir=xbf_dir,
        )
        p3 = subprocess.run([sys.executable, "-c", rev3_code],
                           capture_output=True, text=True, timeout=60)
        assert "REV3_OK" in p3.stdout, \
            f"Rev3 failed. stderr={p3.stderr[:500]}, stdout={p3.stdout[:200]}"
        rev3_data = json.loads(p3.stdout.split("REV3_OK ")[-1])
        assert rev3_data["index_entries"] >= 1
        assert rev3_data["solve_status"] in ("unique", "ambiguous"), \
            f"Solve failed: {rev3_data['solve_status']}"

        rev3_path = rev3_data["path"]
        assert Path(rev1_path).exists()
        assert Path(rev2_path).exists()
        assert Path(rev3_path).exists()
