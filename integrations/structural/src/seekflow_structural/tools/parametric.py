"""The two callables the loop drives, wired to the systems that already exist.

The loop was written with `generate` and `solve` as seams, so that it could be
tested without a CAD kernel or a solver and so that it would not have to know
how either works. This is the other side of those seams.

**Generation runs in a subprocess.** Three reasons, and the first is the one
that matters. The geometry stack can fault the process - this repository has
already recorded a 0xC0000005 out of resolving a role on a real document - and
a fault that ends a subprocess ends a revision, while the same fault in the
parent ends the loop and everything it has learned so far. The second is
`sys.path`: a revision's `scripts/` directory has to come first so that its
copy of the templates is the one imported, and putting that at the front of a
long-lived process is how a later revision ends up importing an earlier one's
copy. The third is that the subprocess's import graph dies with it, which
matters because `param_templates` pulls in the server package.

**The lineage is one revision per lineage.** `run_lineage_revisions` publishes
each revision into an immutable directory and refuses to write one twice, and
it numbers them by their position in the list it is given. So a second call
carrying both revisions would try to publish rev-000001 again and fail. A
revision that has to be added to an existing lineage needs that function to
grow an "append" mode, which is a change to the generation side and not this
package's to make. Until then each revision gets its own lineage - which
costs the thing persistent topology is for, that a face selection made in one
revision survives into the next, and that is named as a limit rather than
hidden.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from seekflow_structural.tools import workspace

# How long a single revision's generation may take. The OCAF write dominates
# and grows with the feature count; D27's took minutes, not seconds.
DEFAULT_GENERATE_TIMEOUT_S = 3600

# The driver, run as a subprocess with the revision's own copies first on the
# path. Written out rather than imported so that the only thing the child has
# in common with this package is the text below.
DRIVER = '''\
import json
import sys
from pathlib import Path

work = Path(sys.argv[1])
out_root = Path(sys.argv[2])
lineage = sys.argv[3]

sys.path.insert(0, str(work / "scripts"))
for extra in {extra_paths!r}:
    sys.path.insert(0, extra)

result_path = work / "output" / "generation.json"
result_path.parent.mkdir(parents=True, exist_ok=True)

def report(ok, **fields):
    result_path.write_text(
        json.dumps({{"ok": ok, **fields}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    raise SystemExit(0 if ok else 1)

try:
    import param_templates
    from seekflow_engineering_tools.generative_cad.validation.pipeline import (
        validate_and_canonicalize_with_bundle,
    )
    from seekflow_engineering_tools.generative_cad.pipeline.run import (
        run_lineage_revisions,
    )
except Exception as exc:
    report(False, stage="import", error=f"{{type(exc).__name__}}: {{exc}}")

if Path(param_templates.__file__).resolve() != (work / "scripts" / "param_templates.py").resolve():
    report(
        False, stage="import",
        error=(
            "the templates imported are "
            f"{{param_templates.__file__}}, not this revision's copy. The "
            "revision would be built by code it does not own."
        ),
    )

params = json.loads((work / "params.json").read_text(encoding="utf-8"))

# The design is the document. `params.json` is how the first revision asked
# the template layer for one; every revision after that edits the document
# itself, because the document is where the geometry is. It carries
# thirty-one operations with their own parameters - the fir-tree cutter alone
# has seven `fillet_sketch` nodes with a radius each - and the template's
# parameter dict names none of them.
document_path = work / "document.json"
if document_path.is_file():
    raw = json.loads(document_path.read_text(encoding="utf-8"))
    built_from = "document"
else:
    try:
        raw = param_templates.build(params)
    except Exception as exc:
        report(False, stage="build", error=f"{{type(exc).__name__}}: {{exc}}")
    document_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    built_from = "template"

try:
    canonical, validation, bundle = validate_and_canonicalize_with_bundle(raw)
except Exception as exc:
    report(False, stage="validate", error=f"{{type(exc).__name__}}: {{exc}}")

if canonical is None or not validation.ok:
    report(
        False, stage="validate",
        issues=[issue.message for issue in validation.issues],
    )

try:
    results = run_lineage_revisions(
        lineage_id=lineage,
        output_root=out_root,
        revisions=[{{"canonical": canonical,
                    "validation_seed": bundle.to_metadata_dict()}}],
    )
except Exception as exc:
    report(False, stage="lineage", error=f"{{type(exc).__name__}}: {{exc}}")

first = results[0] if results else None
if first is None or not first.ok:
    report(False, stage="lineage", error=str(getattr(first, "error", "no result")))

# The bundle the structural chain reads needs a fourth file the generation
# side does not write. `history.json` binds the two artifacts by hash and
# records what the reopened document's stable-label inventory holds. It is
# written here rather than synthesised from the parameters, because the number
# in it is counted from the XBF that was actually produced - reopening the
# document and reading the index is the same thing every other tool in this
# repository does to produce this file, and it is a claim that can be checked
# afterwards by anyone holding the same XBF.
#
# What it is not is evidence of a live topology capture. The CFD side has a
# separate writer for that, and it refuses to run without the capture session
# itself - deliberately, so that the proof cannot be manufactured after the
# fact. Nothing here claims to be that proof, and the provenance says so.
import hashlib  # noqa: E402

from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (  # noqa: E402
    OcafDocumentSession,
)

revision_id = "rev-000001"
revision_dir = out_root / "lineage" / lineage / "revisions" / revision_id
xbf = revision_dir / "design.xbf"
step = revision_dir / "model.step"

try:
    session = OcafDocumentSession.open(xbf)
    try:
        inventory = [
            entry for entry in session.label_index.entries()
            if entry.retired_revision is None
        ]
        ocaf_revision = session.revision_number
    finally:
        session.close()
except Exception as exc:
    report(False, stage="history", error=f"{{type(exc).__name__}}: {{exc}}")

if not inventory:
    report(
        False, stage="history",
        error=(
            f"{{xbf}} reopened with an empty stable-label inventory. The "
            "document carries no persistent naming, so nothing downstream "
            "could ask which face came from where."
        ),
    )


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# The document travels with the model it produced. A reader of the bundle -
# the feedback agent, most of all - has to be able to see what a change could
# be made to, and the document is where that is. Leaving it in the workspace
# would put the editable surface in a directory the agent reading the results
# has no reason to know about.
import shutil  # noqa: E402

shutil.copyfile(document_path, revision_dir / "document.json")

(revision_dir / "history.json").write_text(
    json.dumps({{
        "schema_version": "cfd_history_v1",
        "lineage_id": lineage,
        "revision_id": revision_id,
        "geometry_hash": _sha256(step),
        "topology_hash": _sha256(xbf),
        "history_complete": True,
        "ocaf_label_count": len(inventory),
        "ocaf_revision": ocaf_revision,
        "provenance": (
            "iteration loop: XBF reopened after generation and its "
            "stable-label inventory counted. This records what the document "
            "carries, and is not evidence of a live capture session - the CFD "
            "side has its own writer for that and does not accept it from here."
        ),
    }}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

report(True, lineage=lineage, ocaf_label_count=len(inventory),
       built_from=built_from)
'''


def find_repo_root(start: Path | None = None) -> Path:
    """The repository root, found by the marker the tests also use."""
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        if (parent / "_param_experiment").is_dir():
            return parent
    raise FileNotFoundError(
        f"could not find the repository root above {here}; it is the directory "
        "holding _param_experiment"
    )


def extra_paths(repo_root: Path) -> list[str]:
    """What the driver's child needs on its path besides the revision's copy."""
    return [
        str(repo_root / "integrations" / "engineering_tools" / "src"),
        str(repo_root / "app" / "text-to-cad" / "server"),
    ]


def generate_bundle(
    space: workspace.Workspace,
    *,
    repo_root: Path,
    lineage: str | None = None,
    timeout_s: int = DEFAULT_GENERATE_TIMEOUT_S,
    python: str | None = None,
) -> Path:
    """Build one revision's STEP and XBF, and return the bundle directory.

    The bundle is the directory `BundleRef` points at: the published revision
    holding `design.xbf`, `model.step` and `metadata.json`. The structural
    chain reads the first two.
    """
    lineage = lineage or f"{space.lineage}-{space.revision}"
    # Written into the revision's own directory so the child's text is an
    # artifact of the revision like everything else it produced.
    driver_path = space.root / "generate_bundle.py"
    driver_path.write_text(
        DRIVER.format(extra_paths=extra_paths(repo_root)), encoding="utf-8"
    )

    before = space.master_fingerprint()
    completed = subprocess.run(
        [python or sys.executable, str(driver_path), str(space.root),
         str(space.root / "lineage"), lineage],
        capture_output=True, text=True, timeout=timeout_s,
        cwd=str(space.root),
    )

    # Checked here as well as after the revision's own writes, because the
    # child is a separate process and this is the only moment its effect on
    # the master can be attributed to it.
    space.masters = before
    space.verify_master_untouched()

    result_path = space.output / "generation.json"
    payload = {}
    if result_path.is_file():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    if completed.returncode != 0 or not payload.get("ok"):
        raise GenerationFailed(
            f"revision {space.revision} did not generate: "
            + str(payload.get("error") or payload.get("issues")
                  or completed.stderr[-2000:] or "no reason reported")
        )

    bundle = (space.root / "lineage" / "lineage" / lineage / "revisions"
              / "rev-000001")
    if not (bundle / "design.xbf").is_file():
        raise GenerationFailed(
            f"generation reported success but {bundle} holds no design.xbf"
        )
    return bundle


class GenerationFailed(RuntimeError):
    """A revision could not be built, with the stage and the reason."""


def solve_bundle(
    bundle: Path,
    space: workspace.Workspace,
    *,
    job_id: str,
    output_root: Path,
    brief_path: Path | None = None,
    params_path: Path | None = None,
    api_key_file: Path | None = None,
    ansys_exe: Path | None = None,
    allow_unconfirmed: bool = True,
    domain: dict | None = None,
    mesh_plan: dict | None = None,
    face_selection: dict | None = None,
) -> dict:
    """Run the structural chain over one bundle and read back what it reported.

    Returns the metrics and the verification verdicts, in the shape the
    feedback stage and the loop's scoring both expect - the nested metrics as
    the run wrote them, and the verdicts as a name-to-verdict map so that
    reading a quantity and knowing whether it may be quoted is one lookup.

    `domain`, `mesh_plan` and `face_selection` are the three decisions that
    define the *experiment* as opposed to the design, and passing them is how
    two revisions are made comparable. They are the case.json blocks of an
    earlier run, handed straight back in.

    Without them each revision decides for itself, and the difference between
    two revisions stops being attributable to the design. Measured on the
    first two-revision run that completed: rev-1 loaded the fir-tree tooth
    flanks over 4,373 mm2 and rev-2 loaded the slot walls over 12,009 mm2, with
    the applied resultant reversed - so the 26% fall in peak stress between
    them was a change of load case as much as a change of geometry, and the
    loop recorded it as a rule about the hole.
    """
    from seekflow_structural.cli import main as cli_main

    argv = [
        "run", "--bundle", str(bundle), "--job", job_id,
        "--output", str(output_root),
    ]
    for flag, payload, name in (
        ("--domain", domain, "domain.json"),
        ("--mesh-plan", mesh_plan, "mesh_plan.json"),
        ("--face-selection", face_selection, "face_selection.json"),
    ):
        if payload is None:
            continue
        # Written into the revision's own directory, so what a revision was
        # held to is an artifact of that revision rather than a value that
        # existed only in the caller's memory.
        path = space.root / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        argv += [flag, str(path)]
    if params_path is not None:
        argv += ["--params", str(params_path)]
    if brief_path is not None:
        argv += ["--brief", str(brief_path)]
    if api_key_file is not None:
        argv += ["--api-key-file", str(api_key_file)]
    if ansys_exe is not None:
        argv += ["--ansys-exe", str(ansys_exe)]
    if allow_unconfirmed:
        argv += ["--allow-unconfirmed"]
    cli_main(argv)

    # `JobStore` lays a job out at `<output_root>/jobs/<job_id>`, so the job
    # directory is one level below the output root the CLI was given. Reading
    # it as `<output_root>/<job_id>` finds nothing, and finding nothing used
    # to be reported as a run that never reached post-processing - on a run
    # that had finished successfully and written every artifact.
    job = Path(output_root) / "jobs" / job_id
    metrics_path = job / "solve" / "structural_metrics.json"
    if not metrics_path.is_file():
        raise SolveFailed(
            f"the run for {job_id} finished without a structural_metrics.json; "
            "it did not reach the post-processing stage"
        )
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    verdicts: dict[str, str] = {}
    verification_path = job / "verification.json"
    if verification_path.is_file():
        for entry in json.loads(
            verification_path.read_text(encoding="utf-8")
        ).get("verdicts", []):
            verdicts[str(entry.get("quantity"))] = str(entry.get("verdict"))

    return {"metrics": metrics, "verdicts": verdicts, "job": str(job)}


class SolveFailed(RuntimeError):
    """The structural chain did not produce a result for this bundle."""
