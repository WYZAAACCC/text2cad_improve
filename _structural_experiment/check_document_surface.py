"""Does a feedback change actually reach the geometry the next revision gets?

Run against D27's real document - the one a revision is built from - rather
than a fixture, because the failure this checks for is a property of the real
design: the harness offers eighteen "free" variables and the document contains
none of them.

    .conda\\python.exe _structural_experiment\\check_document_surface.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "integrations" / "structural" / "src"))

# The runs were moved off the working disk; see _store.py.
from _store import loop_test  # noqa: E402

from seekflow_structural.agents import revise                      # noqa: E402
from seekflow_structural.errors import StructuralError             # noqa: E402
from seekflow_structural.tools import design_variables, document as dt  # noqa: E402
from seekflow_structural.tools import knowledge, workspace         # noqa: E402

MASTER = REPO / "_param_experiment" / "turbine_disc_dataset_D01-D32" / "scripts"
# The runs were moved off the working disk; see _store.py.
REAL_DOCUMENT = (loop_test() / "live7" / "revisions" / "rev-000001"
                 / "document.json")
ROOT = loop_test() / "surface_check"


class Call:
    def __init__(self, **fields):
        for name, default in (
            ("parameter", ""), ("value", None), ("script", ""), ("content", ""),
            ("applied", []), ("skipped", []), ("finding_id", ""),
            ("rationale", ""), ("questions", []),
        ):
            setattr(self, name, fields.pop(name, default))
        for name, value in fields.items():
            setattr(self, name, value)


def rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def main() -> int:
    document = json.loads(REAL_DOCUMENT.read_text(encoding="utf-8"))
    print(f"document: {REAL_DOCUMENT}")
    print(f"  {len(document['nodes'])} operations, "
          f"{len(dt.editable(document))} settable names")

    # 1. The two vocabularies, measured against the document that is built.
    rule("1. what the harness offers vs what the document holds")
    free = design_variables.free_variables()
    in_document = [name for name in free if dt.resolve(document, name)]
    print(f"  free_variables():            {len(free)}")
    print(f"  ...present in the document:  {len(in_document)}")
    print(f"  document operation params:   {len(dt.editable(document))}")

    if ROOT.exists():
        import shutil
        shutil.rmtree(ROOT)

    finding = {
        "id": "F1", "mechanism": "concentration",
        "feature": "lightening hole at r=208",
        "change": {"parameter": "feat_holes_poly.points[4].y_mm",
                   "relative_change": 1 / 6},
    }

    def fresh_state():
        space = workspace.Workspace.create(
            master_dir=MASTER, root=ROOT, lineage="D27", revision="rev-000004",
            params={}, document=json.loads(json.dumps(document)),
        )
        return revise.ReviseState(
            workspace=space, findings=[finding],
            base=knowledge.KnowledgeBase.load(ROOT / "none.json"),
        )

    # 2. A template parameter, after a document exists.
    rule("2. a free variable, on a revision that has a document")
    state = fresh_state()
    try:
        revise._set_parameter(
            Call(parameter="rim_half_thickness_mm", value=27.0, finding_id="F1"),
            state,
        )
        print("  ACCEPTED - and nothing would have changed")
    except StructuralError as exc:
        print(f"  refused: {exc.diagnostic.code}")
        print(f"  {exc.diagnostic.message.split('. ')[0]}.")
    print(f"  document edits after the refusal: "
          f"{len(state.workspace.document_edits())}")

    # 3. What the old path did: written, logged, and read by nothing.
    rule("3. the same change written the old way")
    state = fresh_state()
    before = state.workspace.document()
    state.workspace.set("rim_half_thickness_mm", 27.0)
    state.applied.append({
        "finding": "F1", "parameter": "rim_half_thickness_mm",
        "before": 30.0, "after": 27.0,
        "patch": {"path": "/params/rim_half_thickness_mm",
                  "old_value": 30.0, "new_value": 27.0},
    })
    print(f"  params.json changed:        "
          f"{state.workspace.params().get('rim_half_thickness_mm')}")
    print(f"  document changed:           "
          f"{state.workspace.document() != before}")
    print(f"  document edits recorded:    "
          f"{len(state.workspace.document_edits())}")
    try:
        revise._submit_revision(Call(applied=["F1"], skipped=[]), state)
        print("  submit: ACCEPTED - the loop would build the same geometry")
    except StructuralError as exc:
        print(f"  submit refused: {exc.diagnostic.code}")

    # 4. A change aimed at the document.
    rule("4. the change that reached the geometry last time (rev-4)")
    state = fresh_state()
    entry = dt.editable(state.workspace.document())[
        "feat_holes_poly.points[4].y_mm"
    ]
    print(f"  before: {entry['current_value']} "
          f"(at r={entry.get('at_r_mm')}, spans {entry.get('spans_r_mm')})")
    revise._set_parameter(
        Call(parameter="feat_holes_poly.points[4].y_mm", value=7.0,
             finding_id="F1"),
        state,
    )
    revise._submit_revision(Call(applied=["F1"], skipped=[]), state)
    edits = state.workspace.document_edits()
    print(f"  after:  "
          f"{dt.editable(state.workspace.document())['feat_holes_poly.points[4].y_mm']['current_value']}")
    print(f"  accepted; {len(edits)} edit(s) recorded:")
    for edit in edits:
        print(f"    {edit['path']}: {edit['old_value']} -> {edit['new_value']}")

    # 5. The files the next revision is built from.
    rule("5. what the next revision starts from")
    for name in ("document.json", "document.base.json", "params.json"):
        path = state.workspace.root / name
        print(f"  {name:22} {'present' if path.is_file() else 'absent'}")
    print("\n  generate_bundle reads document.json when it is there, and calls"
          "\n  param_templates.build only when it is not. No model is asked to"
          "\n  produce a design again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
