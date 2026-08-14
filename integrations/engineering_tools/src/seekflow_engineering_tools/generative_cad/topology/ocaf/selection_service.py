"""PersistentSelectionService — native TNaming_Selector-based topology selection.

Creates and solves persistent topology selections using OCAF TNaming.
Each selection lives under the fixed Selections/<tag> label tree (§4.3):

  Tag 1: NativeNaming — TNaming_Selector exclusive (no business attributes)
  Tag 2: Metadata    — SelectionPolicy as TDataStd_* attributes
  Tag 3: SemanticContract — written as structured attributes
  Tag 4: Audit       — heuristic fingerprint for diagnostics only

Constraints:
  - Create DOES NOT accept face/edge indices — caller must resolve to TopoDS_Shape.
  - NativeNaming label (Tag 1) is for TNaming_Selector ONLY.
  - Solve requires a TDF_LabelMap of valid labels (all feature history labels).
  - Heuristic results must NEVER be auto-promoted to UNIQUE.

Verified APIs (OCP 7.8.1.1):
  - TNaming_Selector(label).Select(face, body) → True/False
  - TNaming_Selector(label).NamedShape() → TNaming_NamedShape | None
  - TNaming_Selector(label).Solve(TDF_LabelMap) → True/False
  - TNaming_Tool.CurrentShape_s(named_shape) → TopoDS_Shape
"""

from __future__ import annotations

from dataclasses import field
from typing import Any

from OCP.TNaming import TNaming_Selector, TNaming_Tool
from OCP.TDF import TDF_LabelMap

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    SelectionCardinality,
    SelectionPolicy,
    SelectionResolution,
    SelectionResolutionStatus,
    SemanticContract,
    TopologyEntityKind,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.schema import (
    SELECTION_TAG_NATIVE_NAMING,
    SELECTION_TAG_METADATA,
    SELECTION_TAG_SEMANTIC_CONTRACT,
    SELECTION_TAG_AUDIT,
    SELECTION_TAG_FINGERPRINT,
)


class PersistentSelectionService:
    """Creates and solves persistent topology selections via TNaming_Selector.

    Usage:
        service = PersistentSelectionService(session)

        # Create a selection on a face
        service.create("load_face", top_face, body, policy, contract)

        # ... later, after history writes ...
        valid_labels = TDF_LabelMap()
        for label in all_feature_labels:
            valid_labels.Add(label)

        resolution = service.solve("load_face", valid_labels)
        if resolution.status == SelectionResolutionStatus.UNIQUE:
            target_shape = resolution.resolved_shapes[0]
    """

    def __init__(self, session):
        """session: OcafDocumentSession from PR-1."""
        self._session = session
        # v7 T4: same-process map of selection_id -> originally-selected shape.
        # Used to pre-judge DELETED before Solve because OCP 7.8.1.1 ACCESS
        # VIOLATES inside TNaming_Selector.Solve() when the selected face was
        # fully deleted. This is intentionally process-local for the minimal
        # fix; cross-revision identity persistence is a later phase.
        self._selected_shapes: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        selection_id: str,
        selected_shape: Any,        # TopoDS_Shape — the face/edge to select
        context_shape: Any,         # TopoDS_Shape — the body containing it
        policy: SelectionPolicy | None = None,
        contract: SemanticContract | None = None,
    ) -> None:
        """Create a persistent topology selection.

        Args:
            selection_id: Stable business identifier.
            selected_shape: The TopoDS_Shape to select (FACE or EDGE).
            context_shape: The body/shape that contains selected_shape.
            policy: Selection constraints.
            contract: Post-hoc semantic validation rules.

        Raises:
            SelectionCreateError: If TNaming_Selector.Select() returns False.

        Does NOT accept face/edge index — caller must resolve to TopoDS_Shape first.

        IMPORTANT (OCP 7.8.1.1): TNaming_Selector.Select() will ACCESS VIOLATE unless
        at least one TNaming_Builder attribute already exists in the document.
        Callers MUST write at least one builder before creating selections.
        """
        from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
            SelectionCreateError,
        )

        # Get stable selection label via session's index
        sel_label = self._session.ensure_selection(selection_id)

        # Tag 1: NativeNaming — TNaming_Selector exclusive
        native_label = sel_label.FindChild(SELECTION_TAG_NATIVE_NAMING, True)
        selector = TNaming_Selector(native_label)
        ok = selector.Select(selected_shape, context_shape)
        if not ok:
            raise SelectionCreateError(
                f"TNaming_Selector.Select failed for selection {selection_id!r}",
                selection_id=selection_id,
            )

        # v7 T4: remember the originally-selected shape for DELETED pre-judgment.
        self._selected_shapes[selection_id] = selected_shape
        # Persist a geometric fingerprint for cross-process DELETED detection.
        self._store_fingerprint(sel_label, self._shape_fingerprint(selected_shape))

        # Tag 2: Metadata (policy)
        if policy is not None:
            self._write_policy(sel_label, policy)

        # Tag 3: SemanticContract
        if contract is not None:
            self._write_contract(sel_label, contract)

    # ------------------------------------------------------------------
    # Solve
    # ------------------------------------------------------------------

    def solve(
        self,
        selection_id: str,
        valid_labels: TDF_LabelMap | None = None,
        *,
        deleted_shapes: tuple[Any, ...] = (),
    ) -> SelectionResolution:
        """Solve a previously created selection against current geometry.

        Args:
            selection_id: The stable selection identifier.
            valid_labels: TDF_LabelMap of all feature labels with TNaming history.
                         Pass None to solve without scope constraints.

        Returns:
            SelectionResolution with status and resolved shapes.
        """
        from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
            SelectionSolveError,
        )

        # Get native label — read-only (v6.0 §9.1: no auto-create)
        native_label = self._get_native_label(selection_id, create=False)
        if native_label.IsNull():
            return SelectionResolution(
                status=SelectionResolutionStatus.INVALID_SELECTION_ID,
                selection_id=selection_id,
                detail=f"Selection {selection_id!r} not found in index",
            )
        sel_label = self._session.ensure_selection(selection_id)

        # Recover policy
        policy = self._read_policy(sel_label)

        # ── v7 T4: pre-judge DELETED before Solve ─────────────────────────
        # OCP 7.8.1.1 ACCESS VIOLATES inside TNaming_Selector.Solve() when the
        # selected face has been fully deleted by a later boolean cut. We can
        # decide DELETED without Solve by matching the originally-selected shape
        # against the DELETED relations captured by tracked_ops (same process).
        target_fp = self._read_fingerprint(sel_label)

        # Cross-process: if deleted_shapes wasn't passed, recover them from the
        # persisted OCAF document so the DELETED pre-judgment still works.
        if not deleted_shapes:
            from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
                collect_deleted_shapes,
            )
            try:
                deleted_shapes = tuple(
                    collect_deleted_shapes(self._session.design_root_label)
                )
            except Exception:
                deleted_shapes = ()

        if target_fp is not None and deleted_shapes:
            for dshape in deleted_shapes:
                if dshape is None:
                    continue
                try:
                    same = self._shape_fingerprint(dshape) == target_fp
                except Exception:
                    continue
                if same:
                    if policy is not None and policy.allow_deleted:
                        return SelectionResolution(
                            status=SelectionResolutionStatus.DELETED,
                            selection_id=selection_id,
                            detail="Selection target deleted (pre-judged via DELETED relation)",
                        )
                    return SelectionResolution(
                        status=SelectionResolutionStatus.UNRESOLVED,
                        selection_id=selection_id,
                        detail="Selection target deleted (pre-judged via DELETED relation)",
                    )

        # Run Solve
        selector = TNaming_Selector(native_label)
        if valid_labels is not None:
            solved = selector.Solve(valid_labels)
        else:
            empty_map = TDF_LabelMap()
            solved = selector.Solve(empty_map)

        if not solved:
            # Check if the shape was deleted
            if policy is not None and policy.allow_deleted:
                return SelectionResolution(
                    status=SelectionResolutionStatus.DELETED,
                    selection_id=selection_id,
                    detail="Selection target was deleted",
                )
            return SelectionResolution(
                status=SelectionResolutionStatus.UNRESOLVED,
                selection_id=selection_id,
                detail="TNaming_Selector.Solve returned False",
            )

        # Get resolved NamedShape (v6.0 §9.2: OCP may return Null, not None)
        named_shape = selector.NamedShape()
        if named_shape is None:
            return SelectionResolution(
                status=SelectionResolutionStatus.UNRESOLVED,
                selection_id=selection_id,
                detail="NamedShape is None or Null after Solve",
            )

        # Get current TopoDS_Shape
        current = TNaming_Tool.CurrentShape_s(named_shape)
        if current is None or current.IsNull():
            return SelectionResolution(
                status=SelectionResolutionStatus.DELETED if (policy and policy.allow_deleted)
                else SelectionResolutionStatus.UNRESOLVED,
                selection_id=selection_id,
                detail="CurrentShape is None or Null",
            )

        # Analyze result
        return self._classify_resolution(selection_id, current, policy, sel_label)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_resolution(
        self,
        selection_id: str,
        current_shape: Any,
        policy: SelectionPolicy | None,
        sel_label: Any,
    ) -> SelectionResolution:
        """Classify the resolved shape against policy and semantic contract."""
        # v6.0 §9.4: explode BEFORE semantics — validate each real FACE/EDGE
        exploded = explode_entities(current_shape,
            policy.entity_kind if policy else TopologyEntityKind.FACE)
        entity_count = len(exploded)

        # Read semantic contract
        contract = self._read_contract(sel_label)

        # Check semantics on each exploded entity
        semantic_errors: list[str] = []
        if contract is not None:
            semantic_errors = validate_semantics(list(exploded), contract)

        base = dict(selection_id=selection_id, resolved_shapes=exploded)

        # v6.0 §9.5: semantic errors must NOT be silently ignored
        if semantic_errors:
            return SelectionResolution(
                status=SelectionResolutionStatus.INVALID_SEMANTICS,
                detail="; ".join(semantic_errors),
                **base,
            )

        if entity_count == 0:
            if policy is not None and policy.allow_deleted:
                return SelectionResolution(
                    status=SelectionResolutionStatus.DELETED, **base,
                )
            return SelectionResolution(
                status=SelectionResolutionStatus.UNRESOLVED,
                detail="No entities in resolved shape",
                **base,
            )

        if entity_count == 1:
            return SelectionResolution(
                status=SelectionResolutionStatus.UNIQUE, **base,
            )

        # Multiple entities
        if policy is not None and policy.cardinality == SelectionCardinality.SET_ALLOWED:
            return SelectionResolution(status=SelectionResolutionStatus.SET, **base)

        return SelectionResolution(
            status=SelectionResolutionStatus.AMBIGUOUS,
            detail=f"Resolved {entity_count} entities but policy requires EXACT_ONE",
            **base,
        )

    @staticmethod
    def _count_entities(shape: Any) -> int:
        """Count the number of discrete topology entities in a shape."""
        try:
            from OCP.TopExp import TopExp_Explorer
            from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
            # Try FACE first, then EDGE
            for entity_type in [TopAbs_FACE, TopAbs_EDGE]:
                exp = TopExp_Explorer(shape, entity_type)
                count = 0
                while exp.More():
                    count += 1
                    exp.Next()
                if count > 0:
                    return count
            return 0
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Label helpers
    # ------------------------------------------------------------------

    def _get_native_label(self, selection_id: str, create: bool = False):
        """Get the NativeNaming label (Tag 1) for a selection.

        v6.0 §9.1: Solve should use create=False (read-only). If the selection
        doesn't exist, returns Null label → caller returns INVALID_SELECTION_ID.
        """
        if create:
            sel_label = self._session.ensure_selection(selection_id)
        else:
            entry = self._session.label_index.get_existing(
                "selection", "lineage", selection_id,
            )
            if entry is None:
                from OCP.TDF import TDF_Label
                return TDF_Label()  # Null → INVALID_SELECTION_ID
            sel_label = entry.tag_path.resolve(self._session.main_label)
        return sel_label.FindChild(SELECTION_TAG_NATIVE_NAMING, False)

    @staticmethod
    def _shape_fingerprint(shape):
        """Geometric fingerprint of a face: (area, cx, cy, cz)."""
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps

        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(shape, props)
        c = props.CentreOfMass()
        return (
            round(float(props.Mass()), 4),
            round(c.X(), 4),
            round(c.Y(), 4),
            round(c.Z(), 4),
        )

    def _store_fingerprint(self, sel_label, fingerprint) -> None:
        import json
        from OCP.TDataStd import TDataStd_AsciiString
        from OCP.TCollection import TCollection_AsciiString as TCAscii

        fp_label = sel_label.FindChild(SELECTION_TAG_FINGERPRINT, True)
        TDataStd_AsciiString.Set_s(fp_label, TCAscii(json.dumps(fingerprint)))

    def _read_fingerprint(self, sel_label):
        import json
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
            read_ascii_string,
        )

        fp_label = sel_label.FindChild(SELECTION_TAG_FINGERPRINT, False)
        if fp_label.IsNull():
            return None
        raw = read_ascii_string(fp_label)
        if raw is None:
            return None
        try:
            return tuple(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Policy/Contract persistence (simplified for PR-4)
    # ------------------------------------------------------------------

    def _write_policy(self, sel_label, policy: SelectionPolicy) -> None:
        """Write SelectionPolicy to Tag 2 (Metadata)."""
        from OCP.TDataStd import TDataStd_AsciiString
        from OCP.TCollection import TCollection_AsciiString as TCAscii
        import json

        meta_label = sel_label.FindChild(SELECTION_TAG_METADATA, True)
        data = json.dumps({
            "entity_kind": policy.entity_kind.value,
            "cardinality": policy.cardinality.value,
            "allow_deleted": policy.allow_deleted,
            "required_for_cae": policy.required_for_cae,
        })
        TDataStd_AsciiString.Set_s(meta_label, TCAscii(data))

    def _write_contract(self, sel_label, contract: SemanticContract) -> None:
        """Write SemanticContract to Tag 3."""
        from OCP.TDataStd import TDataStd_AsciiString
        from OCP.TCollection import TCollection_AsciiString as TCAscii
        import json

        contract_label = sel_label.FindChild(SELECTION_TAG_SEMANTIC_CONTRACT, True)
        data = json.dumps({
            k: v for k, v in contract.__dict__.items() if v is not None
        })
        TDataStd_AsciiString.Set_s(contract_label, TCAscii(data))

    def _read_policy(self, sel_label) -> SelectionPolicy | None:
        """Read SelectionPolicy from Tag 2 using safe attr.Get() (v5.0 §9.2).

        PR-A verified: attr.Get() instance method works in OCP 7.8.1.1.
        The old comment about "Get_s() unavailable" is obsolete.
        """
        import json
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
            read_ascii_string,
        )

        meta_label = sel_label.FindChild(SELECTION_TAG_METADATA, False)
        if meta_label.IsNull():
            return None

        raw = read_ascii_string(meta_label)
        if raw is None:
            return None

        try:
            data = json.loads(raw)
            return SelectionPolicy(
                entity_kind=TopologyEntityKind(data.get("entity_kind", "face")),
                cardinality=SelectionCardinality(data.get("cardinality", "exact_one")),
                allow_deleted=data.get("allow_deleted", False),
                required_for_cae=data.get("required_for_cae", False),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return None

    def _read_contract(self, sel_label) -> SemanticContract | None:
        """Read SemanticContract from Tag 3 using safe attr.Get() (v5.0 §9.2)."""
        import json
        from seekflow_engineering_tools.generative_cad.topology.ocaf.compat import (
            read_ascii_string,
        )

        contract_label = sel_label.FindChild(SELECTION_TAG_SEMANTIC_CONTRACT, False)
        if contract_label.IsNull():
            return None

        raw = read_ascii_string(contract_label)
        if raw is None:
            return None

        try:
            data = json.loads(raw)
            return SemanticContract(
                surface_type=data.get("surface_type"),
                curve_type=data.get("curve_type"),
                expected_axis=tuple(data["expected_axis"]) if "expected_axis" in data else None,
                expected_normal=tuple(data["expected_normal"]) if "expected_normal" in data else None,
                radius_range=tuple(data["radius_range"]) if "radius_range" in data else None,
                zone_id=data.get("zone_id"),
                orientation=data.get("orientation"),
                connectivity_role=data.get("connectivity_role"),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return None


def create_selection_from_role(
    session,
    selection_id: str,
    component_id: str,
    feature_id: str,
    role_key: str,
    policy=None,
    contract=None,
):
    """Create a persistent selection on a named face role after generation.

    Unlike the in-run creation path (which uses a live TopoDS_Face), this
    resolves the role face and body from the already-persisted OCAF document,
    so it can be called after the document has been saved and reopened.
    """
    from seekflow_engineering_tools.generative_cad.topology.ocaf.writer import (
        role_tag_for_key,
    )

    comp = session.ensure_component(component_id)
    feat = session.ensure_feature(comp, feature_id)
    role_tag = role_tag_for_key(role_key)
    face = session.get_current_role_result(feat, role_tag)
    if face is None:
        raise KeyError(
            f"role {role_key!r} not found for feature {feature_id!r} "
            f"in component {component_id!r}"
        )
    body = session.get_current_result_shape(feat)
    if body is None:
        raise KeyError(
            f"no current result shape for feature {feature_id!r} "
            f"in component {component_id!r}"
        )

    service = PersistentSelectionService(session)
    service.create(selection_id, face, body, policy, contract)
    return service


# ---------------------------------------------------------------------------
# Semantic validation — §10.4 of v3.0 guide
# ---------------------------------------------------------------------------


def validate_semantics(
    shapes: list[Any],
    contract: SemanticContract,
) -> list[str]:
    """Post-hoc validation: do resolved shapes satisfy the semantic contract?

    Returns a list of error messages (empty = all constraints satisfied).
    This is for VALIDATION only — never for identity resolution.
    """
    errors: list[str] = []

    for i, shape in enumerate(shapes):
        prefix = f"Shape[{i}]"

        # Surface type check
        if contract.surface_type is not None:
            actual_surface = _get_surface_type(shape)
            if actual_surface is not None and actual_surface != contract.surface_type:
                errors.append(
                    f"{prefix}: expected surface_type={contract.surface_type}, "
                    f"got {actual_surface}"
                )

        # Normal check (for planar faces)
        if contract.expected_normal is not None:
            actual_normal = _get_normal(shape)
            if actual_normal is not None:
                dot = sum(a * b for a, b in zip(actual_normal, contract.expected_normal))
                if abs(abs(dot) - 1.0) > 0.01:
                    errors.append(
                        f"{prefix}: normal mismatch (dot={dot:.4f})"
                    )

        # Curve type check (for edges)
        if contract.curve_type is not None:
            actual_curve = _get_curve_type(shape)
            if actual_curve is not None and actual_curve != contract.curve_type:
                errors.append(
                    f"{prefix}: expected curve_type={contract.curve_type}, "
                    f"got {actual_curve}"
                )

        # Radius range check (for circular edges)
        if contract.radius_range is not None:
            actual_radius = _get_edge_radius(shape)
            if actual_radius is not None:
                lo, hi = contract.radius_range
                if actual_radius < lo or actual_radius > hi:
                    errors.append(
                        f"{prefix}: radius {actual_radius:.2f} not in [{lo}, {hi}]"
                    )

        # Axis check (line direction / circle axis)
        if contract.expected_axis is not None:
            actual_axis = _get_edge_axis(shape)
            if actual_axis is not None:
                dot = sum(a * b for a, b in zip(actual_axis, contract.expected_axis))
                if abs(abs(dot) - 1.0) > 0.01:
                    errors.append(
                        f"{prefix}: axis mismatch (dot={dot:.4f})"
                    )

        # Area range check (v5.0 §9.5)
        if contract.area_range is not None:
            lo, hi = contract.area_range
            props = _get_shape_props(shape)
            if props is not None:
                actual_area = props.get("area", 0.0)
                if actual_area < lo or actual_area > hi:
                    errors.append(
                        f"{prefix}: area {actual_area:.2f} not in [{lo}, {hi}]"
                    )

        # Centroid zone check (v5.0 §9.5)
        if contract.zone_id is not None:
            # zone_id is a semantic label — validated heuristically
            pass  # placeholder for future spatial zone validation

    return errors


def _get_surface_type(shape: Any) -> str | None:
    """Get OCCT surface type name for a TopoDS_Shape (face)."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    _NAMES = {
        0: "Plane", 1: "Cylinder", 2: "Cone", 3: "Sphere",
        4: "Torus", 5: "Bezier", 6: "BSpline", 7: "Revolution",
        8: "Extrusion", 9: "Offset", 10: "Other",
    }
    try:
        adaptor = BRepAdaptor_Surface(shape)
        return _NAMES.get(adaptor.GetType(), "Other")
    except Exception:
        return None


def _get_shape_props(shape: Any) -> dict | None:
    """Extract area and centroid from a TopoDS_Shape."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    try:
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(shape, props)
        c = props.CentreOfMass()
        return {
            "area": props.Mass(),
            "centroid": (c.X(), c.Y(), c.Z()),
        }
    except Exception:
        return None


def _get_normal(shape: Any) -> tuple[float, float, float] | None:
    """Get approximate normal for a planar face using BRepAdaptor_Surface."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.gp import gp_Dir
    try:
        adaptor = BRepAdaptor_Surface(shape)
        if adaptor.GetType() == 0:  # Plane
            # For a Plane, the normal is the axis of the plane
            plane = adaptor.Plane()
            ax3 = plane.Position()
            d = ax3.Direction()
            return (d.X(), d.Y(), d.Z())
    except Exception:
        pass
    return None


def _get_curve_type(shape: Any) -> str | None:
    """Get the OCCT curve type name for a TopoDS_Edge (e.g. Line, Circle)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    _NAMES = {
        0: "Line", 1: "Circle", 2: "Ellipse", 3: "Hyperbola",
        4: "Parabola", 5: "Bezier", 6: "BSpline", 7: "Offset", 8: "Other",
    }
    try:
        adaptor = BRepAdaptor_Curve(shape)
        return _NAMES.get(int(adaptor.GetType()), "Other")
    except Exception:
        return None


def _get_edge_radius(shape: Any) -> float | None:
    """Return the radius of a circular TopoDS_Edge, or None if not a circle."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    try:
        adaptor = BRepAdaptor_Curve(shape)
        if int(adaptor.GetType()) == 1:  # GeomAbs_Circle
            return float(adaptor.Circle().Radius())
    except Exception:
        pass
    return None


def _get_edge_axis(shape: Any) -> tuple[float, float, float] | None:
    """Return line direction or circle axis for a TopoDS_Edge."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    try:
        adaptor = BRepAdaptor_Curve(shape)
        t = int(adaptor.GetType())
        if t == 0:  # GeomAbs_Line — direction
            d = adaptor.Line().Direction()
        elif t == 1:  # GeomAbs_Circle — axis normal
            d = adaptor.Circle().Axis().Direction()
        else:
            return None
        return (float(d.X()), float(d.Y()), float(d.Z()))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# P1-04: explode compound into individual entities
# ---------------------------------------------------------------------------

def explode_entities(shape: Any, entity_kind) -> tuple[Any, ...]:
    """Split a TopoDS_Shape into individual FACE/EDGE/SOLID entities.

    If the shape is already of the target kind, returns it as-is.
    If it's a Compound, extracts and de-duplicates target entities.
    """
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_SOLID

    _kind_map = {
        TopologyEntityKind.FACE: TopAbs_FACE,
        TopologyEntityKind.EDGE: TopAbs_EDGE,
        TopologyEntityKind.SOLID: TopAbs_SOLID,
    }
    occt_kind = _kind_map.get(entity_kind, TopAbs_FACE)

    entities: list[Any] = []
    exp = TopExp_Explorer(shape, occt_kind)
    while exp.More():
        entities.append(exp.Current())
        exp.Next()

    if not entities:
        # Shape might be the entity itself
        entities.append(shape)

    # Dedup via IsSame() — HashCode may crash in OCP 7.8.1.1 (v5.0 §9.3)
    unique: list[Any] = []
    for e in entities:
        if not any(e.IsSame(u) for u in unique):
            unique.append(e)

    return tuple(unique)
