"""A revision's own copy of the generation scripts, and proof the master is intact.

The parametric templates are the engine that turns a parameter set into a
document. Every design family in the dataset was built by them, and the
dataset's value depends on them meaning the same thing tomorrow as they meant
when it was built. So the loop never writes to them.

What it writes to is a copy. Each revision gets a directory holding its own
copy of the templates, a `generate.py` that can rebuild the design, and the
design itself.

The design is the document. The first revision is *asked* for one through
`params.json`, which is the template layer's vocabulary - about a dozen scalar
dimensions. What comes back is a CAD document: thirty-one operations, each
with its own parameters, and every one of those is where a change can be made.
So `document.json` is what a revision is built from and what the feedback loop
edits, and a change is applied to it rather than described to a generator
again. Regenerating a part from a description produces a *different* part, and
a loop that compared two of those would be comparing two unrelated models
instead of one design with one thing changed.

A change that cannot be expressed as a value at all - a different transition
curve, a different filleting rule - is a change to the copy of the template,
which is why the copy is there rather than the loop importing the master
directly. That path is only live while a revision has no document, because the
generator calls the template layer only then; `agents/revise.py` refuses it
otherwise rather than recording a change nothing would read.

The master being untouched is not left to the agent's good behaviour. The
hashes of the master files are taken when the workspace is made and checked
again after it has been written to, so a run that reached back into the master
fails at the end of the step that did it rather than silently changing what
every later revision is built from.

One thing this does not do: it does not make the master read-only on disk.
Nothing here can stop another process writing to it, and a person editing a
template deliberately is doing something this package has no business
preventing. What it can do is notice.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# The modules that make up the generation engine. Copied per revision and
# hashed against the master. A module added to the master later is picked up
# by `discover_masters` rather than having to be listed here.
MASTER_FILES = (
    "param_templates.py",
    "design_families.py",
    "fir_tree_parametric.py",
    "fir_tree_slot2d.py",
    "sampling_constraints.py",
)

GENERATE_TEMPLATE = '''\
# -*- coding: utf-8 -*-
"""{lineage} revision {revision} - the design.

Written by the iteration loop. `PARAMS` is how this revision was *asked* for a
design. From the revision that has one onward the design is `document.json`
beside this file, and that is what the revision is built from - the feedback
loop edits it rather than describing the part again, because a part
regenerated from a description is a different part, and the comparison against
the previous revision would be between two unrelated models.

`scripts/` beside this file is a copy of the master parametric templates taken
when this revision was opened. The master is never written to - see
`tools/workspace.py`. Those templates produced the document; once the document
exists the generator reads it and does not call them again.

  python generate.py <out_dir>   ->  <out_dir>/llm_raw.json
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
sys.path.insert(0, str(HERE.parents[3] / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(HERE.parents[3] / "integrations" / "engineering_tools" / "src"))

import param_templates  # noqa: E402

PARAMS = {params}

DOCUMENT = HERE / "document.json"


def build():
    """The design this revision is built from.

    The document, when there is one - which is every revision from the second
    on. `PARAMS` is only the recipe the first revision used to ask for one, and
    carrying it forward would rebuild the part the document already describes.
    """
    if DOCUMENT.is_file():
        return json.loads(DOCUMENT.read_text(encoding="utf-8"))
    return param_templates.build(PARAMS)


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    document = build()
    (out / "llm_raw.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "params.json").write_text(
        json.dumps(PARAMS, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return document


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "output")
'''


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _keyed_by_id(items) -> bool:
    """Whether a list is a set of named things rather than a sequence."""
    return (
        isinstance(items, list) and bool(items)
        and all(isinstance(item, dict) and "id" in item for item in items)
        and len({item["id"] for item in items}) == len(items)
    )


def diff(before, after, path: str = "", out: list[dict] | None = None) -> list[dict]:
    """Every leaf that differs between two documents, as `path/old/new`.

    Written generally rather than around the paths a change is expected to
    take, because the point of it is to catch the change that went somewhere
    unexpected - or nowhere. A diff that only looked where `set_scalar` writes
    would report nothing for a revision that wrote to `params.json` instead,
    which is the failure it exists to find.

    The document's `nodes` is a list, but it is a list of *named* operations
    and not a sequence, so it is walked by `id` and reads
    `/nodes/disc_poly/params/radius_mm`. Reaching the same parameter by
    position - `/nodes/0/params/radius_mm` - would be a path that means
    something different the moment an operation is added above it, and the
    point of recording this is that a person can act on it afterwards.
    """
    if out is None:
        out = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{key}"
            if key not in before:
                out.append({"path": child, "old_value": None,
                            "new_value": after[key]})
            elif key not in after:
                out.append({"path": child, "old_value": before[key],
                            "new_value": None})
            else:
                diff(before[key], after[key], child, out)
    elif isinstance(before, list) and isinstance(after, list):
        if _keyed_by_id(before) and _keyed_by_id(after):
            was = {item["id"]: item for item in before}
            now = {item["id"]: item for item in after}
            for key in sorted(set(was) | set(now), key=str):
                child = f"{path}/{key}"
                if key not in was:
                    out.append({"path": child, "old_value": None,
                                "new_value": now[key]})
                elif key not in now:
                    out.append({"path": child, "old_value": was[key],
                                "new_value": None})
                else:
                    diff(was[key], now[key], child, out)
        elif len(before) != len(after):
            # A list that changed length is one change, not a run of them: a
            # profile with a vertex added is a different contour, and reporting
            # it as "vertex 4 moved" would describe the wrong edit.
            out.append({"path": path, "old_value": before, "new_value": after})
        else:
            for index, (was, now) in enumerate(zip(before, after)):
                diff(was, now, f"{path}/{index}", out)
    elif before != after:
        out.append({"path": path, "old_value": before, "new_value": after})
    return out


class MasterChanged(RuntimeError):
    """The master templates are not what they were when the workspace opened."""


@dataclass
class Workspace:
    """One revision's copy of the generation scripts, and the design in it."""

    root: Path
    master_dir: Path
    lineage: str
    revision: str
    masters: dict[str, str] = field(default_factory=dict)
    limits: list[str] = field(default_factory=list)

    @property
    def scripts(self) -> Path:
        return self.root / "scripts"

    @property
    def generate(self) -> Path:
        return self.root / "generate.py"

    @property
    def params_path(self) -> Path:
        return self.root / "params.json"

    @property
    def document_path(self) -> Path:
        """The design itself: the CAD document, not the recipe for it.

        `params.json` is what the template layer was asked for; this is what it
        produced, and it is the thing with the geometry in it. The distinction
        cost a run. The generator's parameters name a dozen scalar dimensions;
        the document it builds holds thirty-one operations, each with its own
        parameters - the fir-tree cutter alone carries seven `fillet_sketch`
        nodes with a radius each, and none of those radii exists as a
        parameter the template layer accepts. A change aimed at the document
        can reach every one of them, which is why the document is the design
        here and the parameters are only how the first revision was asked for.
        """
        return self.root / "document.json"

    @property
    def document_base_path(self) -> Path:
        """The document as this revision received it, before any change.

        Kept so that what a revision did to the design is a diff between two
        files rather than a claim in a log. A revision's design is the previous
        revision's document with a change applied to it, and the only way to
        tell an applied change from a reported one is to have the document it
        started from.
        """
        return self.root / "document.base.json"

    def document(self) -> dict | None:
        if not self.document_path.is_file():
            return None
        return json.loads(self.document_path.read_text(encoding="utf-8"))

    def write_document(self, document: dict) -> None:
        self.document_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def document_base(self) -> dict | None:
        if not self.document_base_path.is_file():
            return None
        return json.loads(self.document_base_path.read_text(encoding="utf-8"))

    def write_document_base(self, document: dict) -> None:
        self.document_base_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def document_edits(self) -> list[dict]:
        """What this revision changed about the document it was handed.

        The diff, not the record of the change. A revision that reported a
        change and wrote nothing to the document shows an empty diff, and that
        is the one thing the loop must not mistake for a revision that made a
        change - the next revision would be built from the same geometry while
        the record said otherwise.

        The paths are JSON-pointer style, the same shape `set_scalar` returns
        and the generator's own repair kernel accepts.
        """
        before = self.document_base()
        after = self.document()
        if before is None or after is None:
            return []
        return diff(before, after)

    @property
    def output(self) -> Path:
        return self.root / "output"

    # --- opening ---------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        master_dir: Path,
        root: Path,
        lineage: str,
        revision: str,
        params: dict,
        document: dict | None = None,
    ) -> "Workspace":
        """Copy the master templates in and write this revision's design.

        `document` is the design carried over from the revision before. It is
        passed in rather than rebuilt because the change that produced it was
        made to the document, not to the parameters - a revision built from
        the parameters instead would be the previous design again, and the
        loop would compare two runs of the same geometry and call the
        difference an effect of a change it had thrown away.
        """
        master_dir = Path(master_dir)
        root = Path(root)
        if not master_dir.is_dir():
            raise FileNotFoundError(
                f"the master template directory {master_dir} does not exist"
            )
        # A workspace inside the master tree is one careless `rm -r` away from
        # taking the master with it, and the copies it holds would be picked up
        # as master modules by anything that globs the directory. Refused
        # rather than allowed with a warning: this is the one arrangement the
        # isolation exists to prevent, and it is cheap to rule out.
        resolved_root = root.resolve()
        resolved_master = master_dir.resolve()
        if resolved_root == resolved_master or resolved_master in resolved_root.parents:
            raise ValueError(
                f"the workspace {resolved_root} would sit inside the master "
                f"directory {resolved_master}. The master is read-only to this "
                "loop; put the revision somewhere else."
            )
        (root / "scripts").mkdir(parents=True, exist_ok=True)

        copied = {}
        for name in MASTER_FILES:
            source = master_dir / name
            if not source.is_file():
                continue
            shutil.copyfile(source, root / "scripts" / name)
            copied[name] = sha256_file(source)

        workspace = cls(
            root=root, master_dir=master_dir, lineage=lineage,
            revision=revision, masters=copied,
        )
        if not copied:
            raise FileNotFoundError(
                f"none of the master templates were found in {master_dir}; "
                "expected one of " + ", ".join(MASTER_FILES)
            )
        workspace.write_params(params)
        if document is not None:
            workspace.write_document(document)
            # The same document, kept as the revision's starting point. Every
            # revision after the first is this one plus a change, so "what did
            # this revision do" is only answerable against what it was given.
            workspace.write_document_base(document)
        workspace.save_manifest()
        return workspace

    @classmethod
    def open(cls, root: Path) -> "Workspace":
        """Reopen a workspace from its manifest."""
        root = Path(root)
        manifest = json.loads(
            (root / "workspace.json").read_text(encoding="utf-8")
        )
        return cls(
            root=root,
            master_dir=Path(manifest["master_dir"]),
            lineage=manifest["lineage"],
            revision=manifest["revision"],
            masters=manifest.get("masters", {}),
        )

    def save_manifest(self) -> None:
        (self.root / "workspace.json").write_text(
            json.dumps({
                "schema_version": "structural_workspace_v1",
                "lineage": self.lineage,
                "revision": self.revision,
                "master_dir": str(self.master_dir),
                "master_sha256": self.masters,
                "limits": self.limits,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # --- the design ------------------------------------------------------

    def params(self) -> dict:
        return json.loads(self.params_path.read_text(encoding="utf-8"))

    def write_params(self, params: dict) -> None:
        """Write the design into `generate.py` and beside it as data.

        Both, because they are read by different things: the generator imports
        the one and the loop compares the other. Keeping one and generating the
        other was the alternative and it loses the property that matters here -
        that a person can open this revision's directory and read the design
        without running anything.
        """
        self.params_path.write_text(
            json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.generate.write_text(
            GENERATE_TEMPLATE.format(
                lineage=self.lineage, revision=self.revision,
                params=json.dumps(params, ensure_ascii=False, indent=4),
            ),
            encoding="utf-8",
        )

    def set(self, parameter: str, value) -> dict:
        """Change one parameter of this revision's design."""
        params = self.params()
        params[parameter] = value
        self.write_params(params)
        return params

    # --- the guard -------------------------------------------------------

    def master_fingerprint(self) -> dict[str, str]:
        return {
            name: sha256_file(self.master_dir / name)
            for name in self.masters
            if (self.master_dir / name).is_file()
        }

    def verify_master_untouched(self) -> None:
        """Fail if the master templates changed since this workspace opened.

        Called after anything that writes, and not only at the end: a run that
        has already written to the master has already invalidated every other
        revision built from it, and the sooner that is known the less is built
        on top of it.
        """
        now = self.master_fingerprint()
        missing = [name for name in self.masters if name not in now]
        if missing:
            raise MasterChanged(
                "the master template(s) " + ", ".join(sorted(missing))
                + f" are gone from {self.master_dir}. This workspace was "
                "opened against them and cannot say what its copy was a copy of."
            )
        changed = [
            name for name, digest in self.masters.items()
            if now.get(name) != digest
        ]
        if changed:
            raise MasterChanged(
                "the master template(s) " + ", ".join(sorted(changed))
                + " changed while this revision was open. The master is not "
                "the loop's to write to - every dataset built from it is "
                "described by what it said when the dataset was built. Restore "
                "it from version control before continuing."
            )

    def verify_copy_is_master(self) -> None:
        """Check this revision's copy still matches the master it came from.

        Run before the copy is modified, so a change is always a deliberate
        change from a known starting point rather than one accumulated on top
        of a copy that had already drifted.
        """
        for name, digest in self.masters.items():
            copy = self.scripts / name
            if not copy.is_file():
                raise MasterChanged(
                    f"this workspace's copy of {name} is missing from "
                    f"{self.scripts}"
                )
            if sha256_file(copy) != digest:
                raise MasterChanged(
                    f"this workspace's copy of {name} differs from the "
                    "master. The copy is this revision's to change, but a "
                    "change has to start from the master's text - restore the "
                    "copy before modifying it."
                )

    def changed_files(self) -> list[str]:
        """Which of this revision's copies differ from the master."""
        out = []
        for name, digest in self.masters.items():
            copy = self.scripts / name
            if not copy.is_file() or sha256_file(copy) != digest:
                out.append(name)
        return sorted(out)


def discover_masters(master_dir: Path) -> list[str]:
    """Every generation module in the master directory, not just the listed ones.

    Used to report what a master directory holds, so a workspace opened
    against a directory with an extra module says so rather than quietly
    copying five of six.
    """
    master_dir = Path(master_dir)
    listed = set(MASTER_FILES)
    return sorted(
        path.name for path in master_dir.glob("*.py")
        if path.name in listed or path.stem.startswith(
            ("param_", "fir_tree", "sampling_", "design_")
        )
    )
