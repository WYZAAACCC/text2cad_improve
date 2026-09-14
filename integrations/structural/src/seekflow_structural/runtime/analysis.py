"""Running a script the agent wrote, so it can answer what the tools cannot.

There is a shape to the problems this exists for. An agent is given a fixed
set of measurements, and every so often the question it needs answered is not
one of them - "is this radius one cluster or two" has no filter that answers
it, and a summary that reports a median will hide the second cluster rather
than reveal it. A person in that position writes three lines and looks. The
agent should be able to do the same.

What it runs in is `seekflow.sandbox.ProcessSandbox`: a subprocess, a timeout,
a working directory in the temp area, and an environment built from nothing
rather than inherited. Two things follow, and both matter more than the
isolation:

  - The child is a real subprocess, so a native crash in the geometry kernel
    ends the script rather than the run. Resolving a role on a real document
    can fault the process (0xC0000005), which is exactly the failure this
    turns from "the job died" into "that analysis failed".
  - The environment is a closed dict. On Windows that is not free: the
    geometry stack needs `SystemRoot` to initialise Winsock and `TEMP` to
    place win32com's generated cache, and without them it fails with errors
    (`WinError 10106`, a missing `gen_py`) that read like missing software
    rather than a missing environment variable. They are named in WINDOWS_ENV
    so the next person does not have to find them again.

This is a capability boundary, not a security boundary. ProcessSandbox applies
no memory or processor limit on Windows and its timeout terminates the direct
child only. It is used here for code a model wrote to answer a question about
the user's own part, on the user's own machine. Anything less trusted needs
ContainerSandbox or a job object; neither is configured here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# The geometry stack will not import without these. Measured, not guessed: with
# only SystemRoot, win32com looks for its generated cache in C:\Windows\gen_py
# and fails; with TEMP as well, the bundle opens and the faces measure.
WINDOWS_ENV = ("SystemRoot", "windir", "TEMP", "TMP")

DEFAULT_TIMEOUT_S = 240.0
# Starting the interpreter and importing the geometry stack is most of a
# sandbox call's cost - about twenty seconds before the script has run a line.
MAX_TIMEOUT_S = 900.0

# ProcessSandbox truncates stdout to this before the caller sees it, so a
# larger limit here would be a limit that never applies. Named rather than
# inlined because it is a property of the sandbox, not of this module, and a
# reader comparing the two numbers should find this explanation rather than a
# discrepancy.
SANDBOX_STDOUT_CAP = 4000


@dataclass
class AnalysisResult:
    ok: bool
    stdout: str
    stderr: str
    error: str
    elapsed_ms: int


def sandbox_environment(package_src: Path) -> dict:
    """The environment a child gets: a closed dict, plus what Windows needs.

    `PATH` and `HOME` are added by ProcessSandbox itself. Nothing is inherited
    from this process, so no credential in it can reach a script the agent
    wrote - which is the point of building the dict here rather than copying
    os.environ wholesale.
    """
    env = {
        name: os.environ[name]
        for name in WINDOWS_ENV
        if name in os.environ
    }
    env["PYTHONPATH"] = str(package_src)
    return env


def package_src() -> Path:
    """The directory `seekflow_structural` is importable from."""
    return Path(__file__).resolve().parents[2]


def run_analysis(
    code: str,
    *,
    payload: dict,
    workdir: Path,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> AnalysisResult:
    """Run one script against one document of measurements.

    `payload` becomes the file `sandbox_kit.context()` reads, so what the
    script can see is decided here and is the same thing the agent already
    had. The script's own text is written beside it for the audit trail.
    """
    from seekflow.sandbox import ProcessSandbox

    # Absolute, because the child does not share this process's working
    # directory - ProcessSandbox puts it in the temp area - so a relative path
    # handed to it points somewhere else entirely and the script fails opening
    # a file that is sitting right there.
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    input_path = workdir / "input.json"
    input_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    environment = sandbox_environment(package_src())
    environment["SEEKFLOW_SANDBOX_INPUT"] = str(input_path)

    timeout = max(1.0, min(float(timeout_s), MAX_TIMEOUT_S))
    result = ProcessSandbox().execute(code, timeout=timeout, env=environment)
    return AnalysisResult(
        ok=bool(result.ok),
        stdout=str(result.stdout or ""),
        stderr=str(result.stderr or ""),
        error=str(result.error or ""),
        elapsed_ms=int(result.elapsed_ms or 0),
    )


__all__ = [
    "AnalysisResult",
    "DEFAULT_TIMEOUT_S",
    "MAX_TIMEOUT_S",
    "SANDBOX_STDOUT_CAP",
    "WINDOWS_ENV",
    "package_src",
    "run_analysis",
    "sandbox_environment",
]
