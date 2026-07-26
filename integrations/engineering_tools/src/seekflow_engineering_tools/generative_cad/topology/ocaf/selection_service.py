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

        # Get native label
        native_label = self._get_native_label(selection_id)
        sel_label = self._session.ensure_selection(selection_id)

        # Recover policy
        policy = self._read_policy(sel_label)

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

        # Get resolved NamedShape
        named_shape = selector.NamedShape()
        if named_shape is None:
            return SelectionResolution(
                status=SelectionResolutionStatus.UNRESOLVED,
                selection_id=selection_id,
                detail="NamedShape is None after Solve",
            )

        # Get current TopoDS_Shape
        current = TNaming_Tool.CurrentShape_s(named_shape)
        if current is None:
            return SelectionResolution(
                status=SelectionResolutionStatus.DELETED if (policy and policy.allow_deleted)
                else SelectionResolutionStatus.UNRESOLVED,
                selection_id=selection_id,
                detail="CurrentShape is None",
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
        # Count entities
        entity_count = self._count_entities(current_shape)

        # Read semantic contract
        contract = self._read_contract(sel_label)

        # Check semantics
        semantic_errors: list[str] = []
        if contract is not None:
            semantic_errors = validate_semantics([current_shape], contract)

        base = dict(selection_id=selection_id, resolved_shapes=(current_shape,))

        if semantic_errors:
            return SelectionResolution(
                status=SelectionResolutionStatus.INVALID_SEMANTICS,
                detail="; ".join(semantic_errors),
                **base,
            )

        # P1-04: explode compound into individual entities
        exploded = explode_entities(current_shape,
            policy.entity_kind if policy else TopologyEntityKind.FACE)
        entity_count = len(exploded)

        base = dict(selection_id=selection_id, resolved_shapes=exploded)

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

    def _get_native_label(self, selection_id: str):
        """Get the NativeNaming label (Tag 1) for a selection."""
        sel_label = self._session.ensure_selection(selection_id)
        return sel_label.FindChild(SELECTION_TAG_NATIVE_NAMING, False)

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
        """Read SelectionPolicy from Tag 2."""
        # OCP 7.8.1.1 limitation: TDataStd_AsciiString has no safe Get_s().
        # Policy reading is best-effort; default policy applies if unreadable.
        return None

    def _read_contract(self, sel_label) -> SemanticContract | None:
        """Read SemanticContract from Tag 3."""
        return None


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


def _get_normal(shape: Any) -> tuple[float, float, float] | None:
    """Get approximate normal for a planar face."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    try:
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(shape, props)
        return None  # Simplified: skip normal extraction for now
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

    return tuple(entities)
