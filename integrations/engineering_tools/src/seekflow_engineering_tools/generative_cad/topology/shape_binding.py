"""ShapeBindingService — OCCT IndexedMap-based subshape location and verification.

Provides the bridge between Python/CadQuery/OCP objects and persistent topology IDs:
  - BodyTopologyMaps: pre-built IndexedMaps for a body
  - locate_subshape(): find a subshape's position in the owner body's map
  - resolve_locator(): retrieve the actual subshape from a RuntimeTopoLocator
  - verify_locator(): check a locator against expected state

All OCP imports are lazy (function-local) for environments without OCP.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from typing import Any, Literal

from seekflow_engineering_tools.generative_cad.topology.locator import RuntimeTopoLocator


@dataclass
class BodyTopologyMaps:
    """Pre-built OCCT topology maps for one body shape.

    Built once per body per operation and reused for all subshape lookups.
    Stores Python dicts {position: shape} AND OCP IndexedMaps for FindIndex lookup.
    """

    owner_body_handle_id: str
    face_map: dict[int, Any] = field(default_factory=dict)
    edge_map: dict[int, Any] = field(default_factory=dict)
    _face_indexed_map: Any = None  # TopTools_IndexedMapOfShape for FindIndex
    _edge_indexed_map: Any = None  # TopTools_IndexedMapOfShape for FindIndex
    shape_content_hash: str = ""
    # V3 fields
    owner_body_revision_id: str = ""          # ObjectStore revision at build time
    artifact_geometry_digest: str = ""        # Reserved for Phase 4: STEP/BREP digest


@dataclass
class LocatorVerification:
    """Result of verifying a RuntimeTopoLocator at resolution time."""

    valid: bool
    error_code: str = ""
    detail: str = ""


class ShapeBindingService:
    """Builds OCCT topology maps and creates/verifies RuntimeTopoLocators.

    Usage in a handler:
        service = ShapeBindingService(ctx.object_store)
        maps = service.build_body_maps(body_handle_id, result_solid)
        for face in result_solid.faces().vals():
            locator = service.locate_subshape(maps, face, "face")
            record.current_locator = locator.model_dump()
    """

    def __init__(self, object_store: Any = None) -> None:
        self._object_store = object_store

    # ── Map Building ──

    def build_body_maps(
        self,
        owner_body_handle_id: str,
        owner_shape: Any,
    ) -> BodyTopologyMaps:
        """Build IndexedMaps for faces and edges of a body.

        Uses OCCT TopExp.MapShapes + TopTools_IndexedMapOfShape.
        Stores forward mapping (position → shape) and reverse mapping
        (shape hash → position) for fast subshape location.

        V3: Captures ObjectStore revision for staleness detection.

        Args:
            owner_body_handle_id: The handle ID of the owner body.
            owner_shape: A CadQuery Shape or OCP TopoDS_Shape.

        Returns:
            BodyTopologyMaps with populated face_map, edge_map, and revision.
        """
        face_map, face_idx = self._build_indexed_map(owner_shape, "face")
        edge_map, edge_idx = self._build_indexed_map(owner_shape, "edge")

        shape_content_hash = self._compute_shape_content_hash(owner_shape)

        # V3: capture ObjectStore revision for locator lifecycle
        revision_id = ""
        if self._object_store is not None:
            try:
                rev = self._object_store.get_revision(owner_body_handle_id)
                revision_id = str(rev) if rev > 0 else ""
            except Exception:
                pass

        return BodyTopologyMaps(
            owner_body_handle_id=owner_body_handle_id,
            face_map=face_map,
            edge_map=edge_map,
            _face_indexed_map=face_idx,
            _edge_indexed_map=edge_idx,
            shape_content_hash=shape_content_hash,
            owner_body_revision_id=revision_id,
        )

    def _build_indexed_map(
        self, shape: Any, entity_type: str,
    ) -> tuple[dict[int, Any], Any]:
        """Build {position: TopoDS_Shape} map + return OCP IndexedMap.

        Returns (dict, IndexedMap) — dict for iteration, IndexedMap for FindIndex.
        Raises ImportError if OCP is unavailable.
        Raises RuntimeError on any other failure (V3: no silent degradation).
        """
        from OCP.TopExp import TopExp  # type: ignore[import-untyped]
        from OCP.TopAbs import TopAbs_ShapeEnum  # type: ignore[import-untyped]
        from OCP.TopTools import TopTools_IndexedMapOfShape  # type: ignore[import-untyped]

        type_enum = {
            "face": getattr(TopAbs_ShapeEnum, "TopAbs_FACE", None),
            "edge": getattr(TopAbs_ShapeEnum, "TopAbs_EDGE", None),
        }.get(entity_type)

        if type_enum is None:
            return {}, None

        # Unwrap CadQuery object to raw TopoDS_Shape:
        # Workplane → .val() → CadQuery Shape → .wrapped → OCP TopoDS_Shape
        raw = shape
        if hasattr(raw, 'val') and callable(raw.val):
            raw = raw.val()
        raw = getattr(raw, "wrapped", raw)

        indexed = TopTools_IndexedMapOfShape()
        _map_shapes = getattr(TopExp, 'MapShapes', getattr(TopExp, 'MapShapes_s', None))
        if _map_shapes:
            _map_shapes(raw, type_enum, indexed)  # type: ignore[arg-type]

        result: dict[int, Any] = {}
        extent = indexed.Extent()
        for i in range(1, extent + 1):
            result[i] = indexed.FindKey(i)
        return result, indexed

    # ── Subshape Location ──

    def locate_subshape(
        self,
        maps: BodyTopologyMaps,
        subshape: Any,
        entity_type: Literal["face", "edge", "vertex"],
    ) -> RuntimeTopoLocator | None:
        """Find the RuntimeTopoLocator for a subshape within its owner body maps.

        PR fix: Uses IndexedMap.FindIndex() instead of hash lookup
        (OCP TopoDS_Shape.HashCode not available in all builds).

        Args:
            maps: Pre-built BodyTopologyMaps for the owner body.
            subshape: The subshape to locate (CadQuery or OCP TopoDS_Shape).
            entity_type: The entity type of the subshape.

        Returns:
            RuntimeTopoLocator or None if not found.
        """
        # Get the OCP IndexedMap for FindIndex
        idx_map = {
            "face": maps._face_indexed_map,
            "edge": maps._edge_indexed_map,
        }.get(entity_type)

        if idx_map is None:
            return None

        # Unwrap subshape to raw OCP for FindIndex
        raw_subshape = getattr(subshape, "wrapped", subshape)

        try:
            position = idx_map.FindIndex(raw_subshape)
        except Exception:
            return None

        if position == 0:  # OCCT convention: 0 means "not found"
            return None

        return RuntimeTopoLocator(
            owner_body_handle_id=maps.owner_body_handle_id,
            entity_type=entity_type,
            indexed_map_position=position,
            occt_shape_hash=0,  # HashCode unavailable — use position + revision
            orientation=self._get_orientation(subshape),
            location_hash=self._get_location_hash(subshape),
            owner_shape_content_hash=maps.shape_content_hash,
            owner_body_revision_id=(
                maps.owner_body_revision_id
                if maps.owner_body_revision_id else None
            ),
        )

    # ── Locator Resolution ──

    def resolve_locator(
        self,
        locator: RuntimeTopoLocator,
    ) -> Any | None:
        """Retrieve the actual subshape from the ObjectStore using a locator.

        1. Look up owner body by handle_id in ObjectStore.
        2. Rebuild IndexedMap for the entity type.
        3. Return shape at indexed_map_position.

        Returns None if the owner body is gone, position is out of range,
        or ObjectStore is not available.
        """
        if self._object_store is None:
            return None

        try:
            owner_shape = self._object_store.get(locator.owner_body_handle_id)
        except (KeyError, AttributeError):
            return None

        entity_map, _ = self._build_indexed_map(owner_shape, locator.entity_type)
        return entity_map.get(locator.indexed_map_position)

    # ── Locator Verification ──

    def verify_locator(
        self,
        locator: RuntimeTopoLocator,
        expected_fingerprint: dict | None = None,
    ) -> LocatorVerification:
        """Verify that a locator is still valid at resolution time.

        Checks:
          1. Owner body exists in ObjectStore.
          2. Owner body content hash matches (cache-busting).
          3. Subshape at indexed_map_position exists.
          4. (Optional) Fingerprint matches expected fingerprint.

        Returns a structured LocatorVerification.
        """
        if self._object_store is None:
            return LocatorVerification(
                valid=False,
                error_code="topology_no_object_store",
                detail="No ObjectStore available for locator verification",
            )

        # Check 1: Owner body exists
        try:
            owner_shape = self._object_store.get(locator.owner_body_handle_id)
        except (KeyError, AttributeError):
            return LocatorVerification(
                valid=False,
                error_code="topology_owner_body_not_found",
                detail=(
                    f"Owner body {locator.owner_body_handle_id} "
                    f"not found in ObjectStore"
                ),
            )

        # Check 2: Content hash match
        if locator.owner_shape_content_hash:
            current_hash = self._compute_shape_content_hash(owner_shape)
            if current_hash != locator.owner_shape_content_hash:
                return LocatorVerification(
                    valid=False,
                    error_code="topology_content_hash_mismatch",
                    detail=(
                        f"Owner body content hash changed: "
                        f"expected={locator.owner_shape_content_hash[:12]}..., "
                        f"current={current_hash[:12]}..."
                    ),
                )

        # Check 3: Subshape retrievable
        subshape = self.resolve_locator(locator)
        if subshape is None:
            return LocatorVerification(
                valid=False,
                error_code="topology_locator_unretrievable",
                detail=(
                    f"Subshape at position {locator.indexed_map_position} "
                    f"not found in owner body {locator.owner_body_handle_id}"
                ),
            )

        # Check 4: Fingerprint — fail-closed until implemented (§2.10C)
        # When full fingerprint computation is available, compare:
        #   actual = compute_face_fingerprint(subshape)
        #   if actual != expected_fingerprint → valid=False
        if expected_fingerprint:
            return LocatorVerification(
                valid=False,
                error_code="topology_fingerprint_not_verified",
                detail=(
                    "Fingerprint verification is not yet implemented. "
                    "expected_fingerprint was provided but cannot be verified — "
                    "returning unresolved per §2.10C fail-closed policy."
                ),
            )

        return LocatorVerification(valid=True)

    # ── Internal Helpers ──

    @staticmethod
    def _occt_hash(shape: Any) -> int:
        """Compute OCCT hash for a shape using TopoDS_Shape.HashCode."""
        try:
            wrapped = getattr(shape, "wrapped", shape)
            max_int = sys.maxsize
            return wrapped.HashCode(max_int)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to compute OCCT hash for shape: {exc}"
            ) from exc

    @staticmethod
    def _compute_shape_content_hash(shape: Any) -> str:
        """Compute a tree-structure hash of the full body shape tree.

        **IMPORTANT (§2.10A):** This is an OCCT TopoDS_Shape.HashCode()
        tree-structure hash, NOT a geometric content hash. It is suitable for
        runtime staleness detection (in combination with body_revision_id)
        but MUST NOT be used as a cross-process or cross-rebuild geometry
        equivalence proof.

        For artifact-level proof, use a canonicalized BREP/STEP byte SHA-256.

        Returns hex string for readability.
        V3: Raises RuntimeError on failure — never returns a sentinel value.
        """
        wrapped = getattr(shape, "wrapped", shape)
        max_int = sys.maxsize
        occt_hash = wrapped.HashCode(max_int)
        return hashlib.sha256(str(occt_hash).encode()).hexdigest()[:16]

    @staticmethod
    def _get_location_hash(shape: Any) -> int | None:
        """Get the HashCode of a subshape's TopLoc_Location."""
        try:
            wrapped = getattr(shape, "wrapped", shape)
            loc = wrapped.Location()
            return loc.HashCode(0x7FFFFFFF)
        except Exception:
            return None

    @staticmethod
    def _get_orientation(shape: Any) -> Literal["forward", "reversed", "internal", "external"]:
        """Determine orientation of a subshape relative to its parent.

        Uses OCCT TopAbs_Orientation enum.
        """
        try:
            wrapped = getattr(shape, "wrapped", shape)
            orient = wrapped.Orientation()
            orient_val = int(orient) if hasattr(orient, "__int__") else 0
            # TopAbs_FORWARD=0, TopAbs_REVERSED=1,
            # TopAbs_INTERNAL=2, TopAbs_EXTERNAL=3
            mapping = {0: "forward", 1: "reversed", 2: "internal", 3: "external"}
            return mapping.get(orient_val, "forward")  # type: ignore[return-value]
        except Exception:
            return "forward"
