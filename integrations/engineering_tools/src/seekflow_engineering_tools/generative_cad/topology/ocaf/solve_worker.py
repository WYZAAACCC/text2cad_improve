"""Subprocess Selection Solve — v6.0 §9.7.

Runs TNaming_Selector.Solve() in an isolated subprocess with enhanced output
including entity properties (area, centroid, surface_type, normal).
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[5])

_WORKER_SCRIPT = r'''
import json, sys
sys.path.insert(0, r"{src}")
from pathlib import Path

xbf_path = Path(r"{xbf_path}")
selection_id = "{selection_id}"

result = {{
    "ok": False,
    "selection_id": selection_id,
    "status": "unresolved",
    "resolved_count": 0,
    "entities": [],
    "native_crash": False,
    "errors": [],
}}

try:
    from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
        OcafDocumentSession,
    )
    from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
        PersistentSelectionService,
    )
    from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
        collect_tnaming_labels,
    )
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopoDS import TopoDS

    session = OcafDocumentSession.open(xbf_path)
    label_map = collect_tnaming_labels(session.design_root_label)
    service = PersistentSelectionService(session)
    resolution = service.solve(selection_id, label_map)

    result["status"] = resolution.status.value
    result["resolved_count"] = len(resolution.resolved_shapes)

    # v6.0 §9.7: extract entity properties for each resolved shape
    _SURFACE_NAMES = {{0:"Plane",1:"Cylinder",2:"Cone",3:"Sphere",4:"Torus",
                       5:"Bezier",6:"BSpline",7:"Revolution",8:"Extrusion",9:"Offset",10:"Other"}}
    for shape in resolution.resolved_shapes:
        entity = {{"shape_type":None,"area":0.0,"centroid":[0,0,0],"surface_type":None,"normal":None}}
        try:
            face = TopoDS.Face_s(shape)
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            entity["area"] = round(props.Mass(), 4)
            c = props.CentreOfMass()
            entity["centroid"] = [round(c.X(),4), round(c.Y(),4), round(c.Z(),4)]
            adaptor = BRepAdaptor_Surface(face)
            stype = adaptor.GetType()
            entity["surface_type"] = _SURFACE_NAMES.get(stype, "Other")
            entity["shape_type"] = "FACE"
            if stype == 0:  # Plane
                plane = adaptor.Plane()
                d = plane.Position().Direction()
                entity["normal"] = [round(d.X(),4), round(d.Y(),4), round(d.Z(),4)]
        except Exception:
            pass
        result["entities"].append(entity)

    result["ok"] = True
    session.close()

except Exception as e:
    result["errors"].append(str(e)[:500])
    result["ok"] = False

print(json.dumps(result), flush=True)
'''


@dataclass(frozen=True)
class SolveWorkerResult:
    """Structured result of subprocess Selection Solve with entity details."""
    ok: bool
    selection_id: str
    status: str = "unresolved"
    resolved_count: int = 0
    entities: list[dict] = field(default_factory=list)
    native_crash: bool = False
    errors: list[str] = field(default_factory=list)
    raw_stdout: str = ""
    raw_stderr: str = ""


def solve_in_subprocess(
    xbf_path: Path, selection_id: str, *, timeout: int = 30,
) -> SolveWorkerResult:
    """Execute TNaming_Selector.Solve() in an isolated subprocess.

    Returns enhanced SolveWorkerResult with entity properties (v6.0 §9.7).
    """
    p = Path(xbf_path).resolve()
    if not p.exists():
        return SolveWorkerResult(
            ok=False, selection_id=selection_id,
            errors=[f"XBF not found: {p}"],
        )

    code = _WORKER_SCRIPT.format(src=SRC, xbf_path=str(p), selection_id=selection_id)

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return SolveWorkerResult(ok=False, selection_id=selection_id,
                                 errors=["Subprocess timed out"])

    raw_stdout = proc.stdout.strip()
    raw_stderr = proc.stderr.strip()

    try:
        data = json.loads(raw_stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return SolveWorkerResult(
            ok=False, selection_id=selection_id,
            errors=[f"No valid JSON (returncode={proc.returncode})"],
            native_crash=proc.returncode != 0,
            raw_stdout=raw_stdout[:500], raw_stderr=raw_stderr[:500],
        )

    return SolveWorkerResult(
        ok=data.get("ok", False),
        selection_id=data.get("selection_id", selection_id),
        status=data.get("status", "unresolved"),
        resolved_count=data.get("resolved_count", 0),
        entities=data.get("entities", []),
        native_crash=data.get("native_crash", False),
        errors=data.get("errors", []),
        raw_stdout=raw_stdout, raw_stderr=raw_stderr,
    )
