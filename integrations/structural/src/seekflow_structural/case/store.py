"""Reading, writing and invalidating the case.

The case is rewritten at every stage boundary, and the hash of each version is
recorded against the stage that produced it. That record is what makes a
resume honest: if a rerun changes the domain, every stage that consumed the
domain is invalidated by comparison rather than by a flag someone has to
remember to set.
"""
from __future__ import annotations

from pathlib import Path

from seekflow_structural.case.model import Case
from seekflow_structural.errors import StructuralError
from seekflow_structural.runtime.store import JobStore, now
from seekflow_structural.serialize import digest

CASE_FILE = "case.json"
STATE_FILE = "state.json"


class CaseStore:
    def __init__(self, job: JobStore):
        self.job = job

    def load(self) -> Case | None:
        if not self.job.exists(CASE_FILE):
            return None
        return Case.model_validate(self.job.read(CASE_FILE))

    def state(self) -> dict:
        return self.job.read(STATE_FILE) if self.job.exists(STATE_FILE) else {}

    def save(self, stage: str, case: Case, **state) -> str:
        """Persist the case and record what this stage produced.

        Returns the case digest, which is also what a later resume compares
        against to decide whether this stage's output is still usable.
        """
        digest_value = digest(case)
        self.job.write(CASE_FILE, case.model_dump(mode="json"))

        current = self.state()
        hashes = dict(current.get("stage_hashes", {}))
        hashes[stage] = digest_value
        current.update(state)
        current.update(
            {
                "stage": stage,
                "stage_hashes": hashes,
                # Recorded here rather than by each caller, because a resume
                # that cannot tell whether it is continuing the same model
                # will cheerfully carry on against a different one - and that
                # is the expensive mistake this field exists to prevent.
                "bundle_hash": digest(case.bundle.model_dump(mode="json")),
                "updated_at_utc": now(),
            }
        )
        self.job.write(STATE_FILE, current)
        return digest_value

    def unchanged_since(self, stage: str, case: Case) -> bool:
        """True when this stage already ran and nothing above it has moved."""
        recorded = self.state().get("stage_hashes", {}).get(stage)
        return recorded is not None and recorded == digest(case)

    def require(self, *groups: str) -> None:
        """Assert the named field groups are present before a stage runs.

        A stage that needs the domain should say so here rather than fail
        somewhere deep with an attribute error, and it should fail as a
        rejection - nothing irreversible has happened yet.
        """
        case = self.load()
        if case is None:
            raise StructuralError(
                "no_case", "No case has been written yet", "case"
            )
        missing = [name for name in groups if getattr(case, name) is None]
        if missing:
            raise StructuralError(
                "case_incomplete",
                f"case is missing {', '.join(missing)}; "
                "an earlier stage did not run or did not finish",
                "case",
            )


def resolve_case_path(job_path: Path) -> Path:
    return job_path / CASE_FILE
