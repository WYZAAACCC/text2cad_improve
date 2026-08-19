"""Complex-model persistence harness for OCAF topology naming.

Provides a run monitor (capture / write / solve / verify stages) plus oracle
checkers so complex multi-operation chains can be verified end to end. Every
selection gets an explicit expectation; a failed predicate fails the test and
appears in the monitor report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def shape_summary(shape: Any) -> dict:
    """Return a JSON-friendly geometric summary of a face/edge shape."""
    summary: dict[str, Any] = {
        "type": None, "area": None, "radius": None, "length": None,
        "centroid": None, "surface": None,
    }
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    try:
        face = TopoDS.Face_s(shape)
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        c = props.CentreOfMass()
        summary["type"] = "face"
        summary["area"] = round(float(props.Mass()), 4)
        summary["centroid"] = (
            round(float(c.X()), 3), round(float(c.Y()), 3), round(float(c.Z()), 3),
        )
        adaptor = BRepAdaptor_Surface(face)
        stype = int(adaptor.GetType())
        summary["surface"] = {
            0: "Plane", 1: "Cylinder", 2: "Cone", 3: "Sphere",
            4: "Torus", 5: "Bezier", 6: "BSpline", 7: "Revolution",
        }.get(stype, "Other")
        if stype == 1:  # Cylinder
            summary["radius"] = round(float(adaptor.Cylinder().Radius()), 4)
        elif stype == 2:  # Cone
            summary["radius"] = round(float(adaptor.Cone().RefRadius()), 4)
    except Exception:
        pass
    try:
        edge = TopoDS.Edge_s(shape)
        props = GProp_GProps()
        BRepGProp.LinearProperties_s(edge, props)
        summary["type"] = "edge"
        summary["length"] = round(float(props.Mass()), 4)
    except Exception:
        pass
    return summary


def face_area(shape: Any) -> float | None:
    return shape_summary(shape).get("area")


def cylinder_radius(shape: Any) -> float | None:
    return shape_summary(shape).get("radius")


def edge_length(shape: Any) -> float | None:
    return shape_summary(shape).get("length")


def _centroid(shape: Any) -> tuple[float, float, float] | None:
    return shape_summary(shape).get("centroid")


# ---------------------------------------------------------------------------
# Oracle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionExpectation:
    """Objective expectation for one selection solve."""

    selection_id: str
    status: str | None = None                 # unique / set / deleted / unresolved ...
    count: int | None = None
    radius_range: tuple[float, float] | None = None
    area_range: tuple[float, float] | None = None
    length_range: tuple[float, float] | None = None
    centroid_near: tuple[tuple[float, float, float], float] | None = None
    same_as: Any | None = None          # resolved shape must be this TShape identity
    distinct_from: tuple[Any, ...] = ()  # resolved shape must differ from these
    label: str = ""


def check_expectation(expectation: SelectionExpectation, resolution) -> tuple[bool, str]:
    """Return (ok, detail) for one selection against its expectation."""
    status = resolution.status.value
    if expectation.status is not None and status != expectation.status:
        return False, f"status={status} expected={expectation.status}"
    if expectation.count is not None and len(resolution.resolved_shapes) != expectation.count:
        return (
            False,
            f"count={len(resolution.resolved_shapes)} expected={expectation.count}",
        )
    for shape in resolution.resolved_shapes:
        if expectation.radius_range is not None:
            r = cylinder_radius(shape)
            if r is None or not (expectation.radius_range[0] <= r <= expectation.radius_range[1]):
                return False, f"radius={r} expected={expectation.radius_range}"
        if expectation.area_range is not None:
            a = face_area(shape)
            if a is None or not (expectation.area_range[0] <= a <= expectation.area_range[1]):
                return False, f"area={a} expected={expectation.area_range}"
        if expectation.length_range is not None:
            ln = edge_length(shape)
            if ln is None or not (expectation.length_range[0] <= ln <= expectation.length_range[1]):
                return False, f"length={ln} expected={expectation.length_range}"
        if expectation.centroid_near is not None:
            target, tol = expectation.centroid_near
            c = _centroid(shape)
            if c is None:
                return False, "centroid unavailable"
            dist = sum((a - b) ** 2 for a, b in zip(c, target)) ** 0.5
            if dist > tol:
                return False, f"centroid dist={dist:.3f} tol={tol}"
        if expectation.same_as is not None:
            try:
                if not (shape.IsSame(expectation.same_as) or shape.IsPartner(expectation.same_as)):
                    return False, "resolved shape is not the expected TShape identity"
            except Exception:
                return False, "identity comparison failed"
        for ref in expectation.distinct_from:
            try:
                if shape.IsSame(ref) or shape.IsPartner(ref):
                    return False, "resolved shape collides with a distinct candidate"
            except Exception:
                continue
    return True, "ok"


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


class TopologyRunMonitor:
    """Records capture / write / solve / verify stats for one complex run."""

    def __init__(self, run_id: str = ""):
        self.run_id = run_id
        self.capture: list[dict] = []
        self.write: list[dict] = []
        self.solves: list[dict] = []
        self.checks: list[dict] = []
        self.verify: dict = {}

    def record_capture(self, batch) -> None:
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            EvolutionKind,
        )

        kinds: dict[str, int] = {}
        for rel in batch.relations:
            kinds[rel.kind.value] = kinds.get(rel.kind.value, 0) + 1
        self.capture.append({
            "node_id": batch.scope.node_id,
            "component_id": batch.scope.component_id,
            "builder_kind": batch.builder_kind,
            "relations": len(batch.relations),
            "relation_kinds": kinds,
            "face_roles": len(getattr(batch, "face_roles", {}) or {}),
            "edge_roles": len(getattr(batch, "edge_roles", {}) or {}),
            "construction_roles": len(getattr(batch, "construction_roles", {}) or {}),
            "history_complete": bool(batch.history_complete),
        })

    def record_write(self, feature_id: str, written: int, audits: int) -> None:
        self.write.append({
            "feature_id": feature_id,
            "tnaming_writes": written,
            "json_audits": audits,
        })

    def record_solve(self, selection_id: str, resolution) -> None:
        self.solves.append({
            "selection_id": selection_id,
            "status": resolution.status.value,
            "resolved_count": len(resolution.resolved_shapes),
            "detail": resolution.detail,
            "shapes": [shape_summary(s) for s in resolution.resolved_shapes],
        })

    def record_verify(self, result) -> None:
        self.verify = {
            "ok": bool(getattr(result, "ok", False)),
            "selection_ok_count": getattr(result, "selection_ok_count", None),
            "tnaming_label_count": getattr(result, "tnaming_label_count", None),
            "errors": getattr(result, "errors", []),
        }

    def record_check(self, selection_id: str, ok: bool, detail: str) -> None:
        self.checks.append({
            "selection_id": selection_id,
            "ok": ok,
            "detail": detail,
        })

    def report(self) -> dict:
        return {
            "run_id": self.run_id,
            "capture": self.capture,
            "write": self.write,
            "solve": self.solves,
            "verify": self.verify,
            "checks": self.checks,
            "passed": all(c["ok"] for c in self.checks),
        }


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class ComplexModelHarness:
    """Build a multi-op chain, persist it, and solve with oracle checks."""

    def __init__(self, component_id: str = "part"):
        self.component_id = component_id
        self.monitor = TopologyRunMonitor(run_id=component_id)
        self.session: Any = None
        self.writer: Any = None
        self.comp_label: Any = None
        self._svc: Any = None

    # -- session lifecycle --------------------------------------------------

    def new_session(self, revision: int = 1) -> Any:
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
            TopologyNamingWriter,
        )

        self.session = OcafDocumentSession.create(revision_number=revision)
        self.writer = TopologyNamingWriter(self.session)
        self.comp_label = self.session.ensure_component(self.component_id)
        self._svc = None
        return self.session

    def open_session(self, path) -> Any:
        from seekflow_engineering_tools.generative_cad.topology.ocaf.document import (
            OcafDocumentSession,
        )
        from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
            TopologyNamingWriter,
        )

        self.session = OcafDocumentSession.open(path)
        self.writer = TopologyNamingWriter(self.session)
        self.comp_label = self.session.ensure_component(self.component_id)
        self._svc = None
        return self.session

    # -- capture / write ----------------------------------------------------

    def write_feature(
        self, feature_id: str, batch, previous_result: Any = None,
    ) -> Any:
        feat_label = self.session.ensure_feature(
            self.comp_label, feature_id, component_id=self.component_id,
        )
        self.monitor.record_capture(batch)
        written = self.writer.write_batch(batch, previous_result=previous_result)
        from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
            EvolutionKind,
            TopologyEntityKind,
        )

        audits = sum(
            1 for r in batch.relations
            if r.entity_kind in (TopologyEntityKind.FACE, TopologyEntityKind.EDGE)
            and r.kind in (EvolutionKind.GENERATED, EvolutionKind.MODIFIED)
        )
        self.monitor.record_write(feature_id, written, audits)
        return feat_label

    def save(self, path) -> None:
        self.session.label_index.save_to_ocaf(self.session.main_label)
        self.session.repository.save_to(path)
        self.session.close()
        self.session = None

    # -- selection ----------------------------------------------------------

    def ensure_service(self) -> Any:
        """Return the shared PersistentSelectionService for this session."""
        if self._svc is None:
            from seekflow_engineering_tools.generative_cad.topology.ocaf.selection_service import (
                PersistentSelectionService,
            )

            self._svc = PersistentSelectionService(self.session)
        return self._svc

    def create_selection(
        self, selection_id: str, selected_shape: Any, context_shape: Any,
        policy: Any = None,
    ) -> Any:
        svc = self.ensure_service()
        svc.create(selection_id, selected_shape, context_shape, policy)
        return svc

    def solve_and_check(
        self, expectations: list[SelectionExpectation],
        label_map: Any = None, *,
        deleted_shapes: tuple[Any, ...] = (),
        svc: Any = None,
    ) -> list[tuple[SelectionExpectation, bool, str]]:
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
            collect_tnaming_labels,
        )

        if svc is None:
            svc = self.ensure_service()
        if label_map is None and self.session is not None:
            label_map = collect_tnaming_labels(self.session.design_root_label)
        outcomes = []
        for expectation in expectations:
            resolution = svc.solve(
                expectation.selection_id, label_map,
                deleted_shapes=deleted_shapes,
            )
            self.monitor.record_solve(expectation.selection_id, resolution)
            ok, detail = check_expectation(expectation, resolution)
            self.monitor.record_check(expectation.selection_id, ok, detail)
            outcomes.append((expectation, ok, detail))
        return outcomes

    def verify(self, path) -> None:
        from seekflow_engineering_tools.generative_cad.topology.ocaf.verify_worker import (
            verify_xbf,
        )

        result = verify_xbf(path)
        self.monitor.record_verify(result)

    def write_monitor_report(self, path) -> None:
        import json

        Path(path).write_text(
            json.dumps(self.monitor.report(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
