"""History-aware geometry operation wrappers — capture OCCT shape evolution.

Each wrapper:
  1. Creates the OCCT builder (BRepPrimAPI_MakePrism, MakeRevol, etc.)
  2. Records input sub-shapes BEFORE execution
  3. Performs the operation
  4. Queries Generated/Modified/IsDeleted for each recorded input
  5. Returns HistoryAwareShapeResult with full KernelHistorySnapshot

Phase 2: extrude, revolve wrappers.
Phase 3: boolean, fillet, chamfer wrappers.

All OCP imports are lazy (function-local) for environments without OCP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict


# ═══════════════════════════════════════════════════════════════════════════════
# Capability probe (cached at module level)
# ═══════════════════════════════════════════════════════════════════════════════

CAPABILITY_MANIFEST: dict[str, str] = {}


def _probe_capabilities() -> dict[str, str]:
    """Lazy capability probe. Result cached in CAPABILITY_MANIFEST."""
    if CAPABILITY_MANIFEST:
        return CAPABILITY_MANIFEST

    caps: dict[str, str] = {}

    # Check OCP.BRepPrimAPI (extrude, revolve)
    try:
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
        _ = BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
        caps["extrude"] = "full"
        caps["revolve"] = "full"
    except ImportError:
        caps["extrude"] = "unavailable"
        caps["revolve"] = "unavailable"

    # Check OCP.BRepAlgoAPI (boolean)
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut
        _ = BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut
        caps["boolean"] = "full"
    except ImportError:
        caps["boolean"] = "unavailable"

    # Check OCP.BRepFilletAPI (fillet, chamfer)
    try:
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet, BRepFilletAPI_MakeChamfer
        _ = BRepFilletAPI_MakeFillet, BRepFilletAPI_MakeChamfer
        caps["fillet"] = "partial"
        caps["chamfer"] = "partial"
    except ImportError:
        caps["fillet"] = "unavailable"
        caps["chamfer"] = "unavailable"

    # Check OCP.BRepOffsetAPI (shell)
    try:
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
        _ = BRepOffsetAPI_MakeThickSolid
        caps["shell"] = "partial"
    except ImportError:
        caps["shell"] = "unavailable"

    # Check OCP.BRepBuilderAPI (loft)
    try:
        from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
        _ = BRepOffsetAPI_ThruSections
        caps["loft"] = "partial"
    except ImportError:
        caps["loft"] = "unavailable"

    # Check CadQuery version
    try:
        import cadquery as cq
        caps["cadquery_version"] = getattr(cq, "__version__", "unknown")
    except ImportError:
        caps["cadquery_version"] = "unavailable"

    # Check OCCT version
    try:
        from OCP.Standard import Standard_Version
        caps["occt_version"] = Standard_Version
    except ImportError:
        caps["occt_version"] = "unavailable"

    CAPABILITY_MANIFEST.update(caps)
    return CAPABILITY_MANIFEST


# ═══════════════════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════════════════


class KernelHistorySnapshot(BaseModel):
    """Recorded shape evolution from one OCCT operation.

    Maps old entity identifiers to new entity indices.
    entity identifiers are CadQuery object hashes (runtime only, not persisted).
    """

    model_config = ConfigDict(extra="forbid")

    generated: dict[str, list[int]] = {}
    modified: dict[str, list[int]] = {}
    deleted: list[str] = []


@dataclass
class HistoryAwareShapeResult:
    """Result of a history-aware geometry operation.

    Attributes:
        result_shape: The resulting CadQuery shape after the operation.
        history: Kernel history snapshot (None if history unavailable).
        metrics: Operation metrics (elapsed time, etc.).
    """

    result_shape: Any
    history: KernelHistorySnapshot | None = None
    metrics: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Kernel history adapter
# ═══════════════════════════════════════════════════════════════════════════════


class KernelHistoryAdapter:
    """Adapter for OCCT BRepBuilderAPI_MakeShape history API.

    Usage:
        maker = BRepPrimAPI_MakePrism(profile, vec)
        maker.Build()
        adapter = KernelHistoryAdapter(maker)
        for old_face in input_faces:
            new_indices = adapter.generated(old_face)
    """

    def __init__(self, maker: Any) -> None:
        self._maker = maker

    def generated(self, source_shape: Any) -> list[int]:
        """Get indices of shapes generated from source_shape.

        For extrude: profile edges → generated side faces.
        """
        try:
            result = self._maker.Generated(source_shape)
            if result is None:
                return []
            # OCCT returns TopTools_ListOfShape
            count = result.Size() if hasattr(result, "Size") else 0
            return list(range(count))
        except Exception:
            return []

    def generated_shapes(self, source_shape: Any) -> list[Any]:
        """Get actual generated shapes (not just indices)."""
        try:
            result = self._maker.Generated(source_shape)
            if result is None:
                return []
            return list(result)
        except Exception:
            return []

    def modified(self, source_shape: Any) -> list[int]:
        """Get indices of shapes modified from source_shape.

        For boolean: argument faces → modified faces in result.
        """
        try:
            result = self._maker.Modified(source_shape)
            if result is None:
                return []
            count = result.Size() if hasattr(result, "Size") else 0
            return list(range(count))
        except Exception:
            return []

    def modified_shapes(self, source_shape: Any) -> list[Any]:
        """Get actual modified shapes (not just indices)."""
        try:
            result = self._maker.Modified(source_shape)
            if result is None:
                return []
            return list(result)
        except Exception:
            return []

    def is_deleted(self, source_shape: Any) -> bool:
        """Check if source_shape was consumed/deleted by the operation."""
        try:
            return bool(self._maker.IsDeleted(source_shape))
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# History-aware operation wrappers
# ═══════════════════════════════════════════════════════════════════════════════


def history_aware_extrude(
    profile_shape: Any,
    extrude_vec: Any,
    *,
    input_faces: list[Any] | None = None,
    input_edges: list[Any] | None = None,
) -> HistoryAwareShapeResult | None:
    """Extrude with OCCT history capture.

    Uses BRepPrimAPI_MakePrism to create the extrusion, then queries
    Generated/Modified for each input sub-shape.

    Args:
        profile_shape: The 2D profile to extrude (TopoDS_Face or TopoDS_Wire).
        extrude_vec: gp_Vec defining extrusion direction and distance.
        input_faces: Faces of the profile (for cap detection).
        input_edges: Edges of the profile (for side face detection).

    Returns:
        HistoryAwareShapeResult with result_shape and KernelHistorySnapshot,
        or None if OCP is unavailable.
    """
    try:
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    except ImportError:
        return None

    try:
        maker = BRepPrimAPI_MakePrism(profile_shape, extrude_vec)
        maker.Build()

        if not maker.IsDone():
            return None

        result = maker.Shape()
        adapter = KernelHistoryAdapter(maker)

        # Record history
        history = KernelHistorySnapshot()

        # Track generated shapes from edges → side faces
        if input_edges:
            for i, edge in enumerate(input_edges):
                indices = adapter.generated(edge)
                if indices:
                    history.generated[f"edge_{i}"] = indices

        # Track generated shapes from faces → end caps
        if input_faces:
            for i, face in enumerate(input_faces):
                if adapter.is_deleted(face):
                    history.deleted.append(f"face_{i}")
                else:
                    indices = adapter.modified(face)
                    if indices:
                        history.modified[f"face_{i}"] = indices

        return HistoryAwareShapeResult(
            result_shape=result,
            history=history,
            metrics={"builder": "BRepPrimAPI_MakePrism", "is_done": True},
        )
    except Exception:
        return None


def history_aware_revolve(
    profile_shape: Any,
    axis: Any,
    angle_deg: float,
    *,
    input_edges: list[Any] | None = None,
) -> HistoryAwareShapeResult | None:
    """Revolve with OCCT history capture.

    Uses BRepPrimAPI_MakeRevol to create the revolution.

    Args:
        profile_shape: The 2D profile to revolve.
        axis: gp_Ax1 defining the revolution axis.
        angle_deg: Revolution angle in degrees (360 = full revolve).
        input_edges: Profile edges (for revolved face tracking).

    Returns:
        HistoryAwareShapeResult or None if OCP unavailable.
    """
    try:
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
    except ImportError:
        return None

    try:
        angle_rad = angle_deg * 3.141592653589793 / 180.0
        maker = BRepPrimAPI_MakeRevol(profile_shape, axis, angle_rad)
        maker.Build()

        if not maker.IsDone():
            return None

        result = maker.Shape()
        adapter = KernelHistoryAdapter(maker)

        history = KernelHistorySnapshot()

        if input_edges:
            for i, edge in enumerate(input_edges):
                indices = adapter.generated(edge)
                if indices:
                    history.generated[f"edge_{i}"] = indices

        return HistoryAwareShapeResult(
            result_shape=result,
            history=history,
            metrics={
                "builder": "BRepPrimAPI_MakeRevol",
                "angle_deg": angle_deg,
                "is_done": True,
            },
        )
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# History-aware boolean operations (Phase 3)
# ═══════════════════════════════════════════════════════════════════════════════


def history_aware_boolean_fuse(
    arg_shape: Any,
    tool_shape: Any,
    *,
    input_arg_faces: list[Any] | None = None,
    input_tool_faces: list[Any] | None = None,
    tolerance: float | None = None,
) -> HistoryAwareShapeResult | None:
    """OCCT boolean fuse (union) with full history capture.

    Steps:
      1. Create BRepAlgoAPI_Fuse(arg, tool)
      2. Call SetToFillHistory(True) BEFORE Build()
      3. Build() and verify IsDone()
      4. For each input_arg_face: query Modified() → modified argument faces
      5. For each input_tool_face: query Modified() → modified tool faces
      6. Return HistoryAwareShapeResult with KernelHistorySnapshot

    Args:
        arg_shape: First argument shape (TopoDS_Shape).
        tool_shape: Second argument shape (TopoDS_Shape).
        input_arg_faces: Faces from the argument body (for modification tracking).
        input_tool_faces: Faces from the tool body (for modification tracking).
        tolerance: Optional fuzzy tolerance for coincidence detection.

    Returns:
        HistoryAwareShapeResult or None if OCP unavailable or operation fails.
    """
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    except ImportError:
        return None

    try:
        maker = BRepAlgoAPI_Fuse(arg_shape, tool_shape)

        # Enable history tracking BEFORE Build()
        if hasattr(maker, "SetToFillHistory"):
            maker.SetToFillHistory(True)

        if tolerance is not None and hasattr(maker, "SetFuzzyValue"):
            maker.SetFuzzyValue(tolerance)

        maker.Build()

        if not maker.IsDone():
            return None

        result = maker.Shape()
        adapter = KernelHistoryAdapter(maker)

        history = KernelHistorySnapshot()

        # Track argument face modifications
        if input_arg_faces:
            for i, face in enumerate(input_arg_faces):
                key = f"arg_face_{i}"
                if adapter.is_deleted(face):
                    history.deleted.append(key)
                else:
                    indices = adapter.modified(face)
                    if indices:
                        history.modified[key] = indices

        # Track tool face modifications
        if input_tool_faces:
            for i, face in enumerate(input_tool_faces):
                key = f"tool_face_{i}"
                if adapter.is_deleted(face):
                    history.deleted.append(key)
                else:
                    indices = adapter.modified(face)
                    if indices:
                        history.modified[key] = indices

        return HistoryAwareShapeResult(
            result_shape=result,
            history=history,
            metrics={
                "builder": "BRepAlgoAPI_Fuse",
                "is_done": True,
                "arg_faces": len(input_arg_faces) if input_arg_faces else 0,
                "tool_faces": len(input_tool_faces) if input_tool_faces else 0,
            },
        )
    except Exception:
        return None


def history_aware_boolean_cut(
    target_shape: Any,
    tool_shape: Any,
    *,
    input_target_faces: list[Any] | None = None,
    input_tool_faces: list[Any] | None = None,
) -> HistoryAwareShapeResult | None:
    """OCCT boolean cut with full history capture.

    Steps:
      1. Create BRepAlgoAPI_Cut(target, tool)
      2. Call SetToFillHistory(True) BEFORE Build()
      3. Build() and verify IsDone()
      4. For each input_target_face: query Modified() (face with hole cut into it)
      5. For each input_tool_face: query IsDeleted() (tool consumed by cut)
      6. Query Generated() for intersection edges (hole rims)

    Key mapping for hole operations:
      - tool lateral face → IsDeleted = True (consumed, becomes hole wall)
      - tool cap face → IsDeleted = True (consumed)
      - target face at intersection → Modified (now has a hole in it)

    Args:
        target_shape: The body being cut (TopoDS_Shape).
        tool_shape: The cutting tool (TopoDS_Shape).
        input_target_faces: Faces from the target body (for modification tracking).
        input_tool_faces: Faces from the tool body (for deletion tracking).

    Returns:
        HistoryAwareShapeResult or None if OCP unavailable or operation fails.
    """
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    except ImportError:
        return None

    try:
        maker = BRepAlgoAPI_Cut(target_shape, tool_shape)

        # Enable history tracking BEFORE Build()
        if hasattr(maker, "SetToFillHistory"):
            maker.SetToFillHistory(True)

        maker.Build()

        if not maker.IsDone():
            return None

        result = maker.Shape()
        adapter = KernelHistoryAdapter(maker)

        history = KernelHistorySnapshot()

        # Track target face modifications (faces with holes cut into them)
        if input_target_faces:
            for i, face in enumerate(input_target_faces):
                key = f"target_face_{i}"
                if adapter.is_deleted(face):
                    history.deleted.append(key)
                else:
                    indices = adapter.modified(face)
                    if indices:
                        history.modified[key] = indices
                    # Also track generated intersection edges on this face
                    gen_indices = adapter.generated(face)
                    if gen_indices:
                        history.generated[key] = gen_indices

        # Track tool face deletions (tool body is consumed by the cut)
        if input_tool_faces:
            for i, face in enumerate(input_tool_faces):
                key = f"tool_face_{i}"
                if adapter.is_deleted(face):
                    history.deleted.append(key)
                else:
                    # Tool faces may become part of the result (intersection faces)
                    indices = adapter.generated(face)
                    if indices:
                        history.generated[key] = indices

        return HistoryAwareShapeResult(
            result_shape=result,
            history=history,
            metrics={
                "builder": "BRepAlgoAPI_Cut",
                "is_done": True,
                "target_faces": len(input_target_faces) if input_target_faces else 0,
                "tool_faces": len(input_tool_faces) if input_tool_faces else 0,
                "deleted_faces": len(history.deleted),
            },
        )
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# History-aware fillet / chamfer / shell operations (Phase 4)
# ═══════════════════════════════════════════════════════════════════════════════


def history_aware_fillet(
    shape: Any,
    edges_with_radii: list[tuple[Any, float]],
    *,
    input_faces: list[Any] | None = None,
) -> HistoryAwareShapeResult | None:
    """OCCT fillet with per-edge history capture.

    For each filleted edge: IsDeleted()→True, Generated()→new fillet face.
    For each adjacent face: Modified()→face changed by fillet.
    """
    try:
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    except ImportError:
        return None
    try:
        maker = BRepFilletAPI_MakeFillet(shape)
        for edge, radius in edges_with_radii:
            maker.Add(float(radius), edge)
        maker.Build()
        if not maker.IsDone():
            return None
        result = maker.Shape()
        adapter = KernelHistoryAdapter(maker)
        history = KernelHistorySnapshot()
        for i, (edge, _radius) in enumerate(edges_with_radii):
            key = f"edge_{i}"
            if adapter.is_deleted(edge):
                history.deleted.append(key)
            gen = adapter.generated(edge)
            if gen:
                history.generated[key] = gen
        if input_faces:
            for i, face in enumerate(input_faces):
                key = f"face_{i}"
                if not adapter.is_deleted(face):
                    mod = adapter.modified(face)
                    if mod:
                        history.modified[key] = mod
        return HistoryAwareShapeResult(
            result_shape=result, history=history,
            metrics={"builder": "BRepFilletAPI_MakeFillet", "is_done": True,
                     "edge_count": len(edges_with_radii), "deleted_edges": len(history.deleted)},
        )
    except Exception:
        return None


def history_aware_chamfer(
    shape: Any,
    edges_with_distances: list[tuple[Any, float]],
    *,
    input_faces: list[Any] | None = None,
) -> HistoryAwareShapeResult | None:
    """OCCT chamfer with per-edge history capture."""
    try:
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer
    except ImportError:
        return None
    try:
        maker = BRepFilletAPI_MakeChamfer(shape)
        for edge, distance in edges_with_distances:
            maker.Add(float(distance), edge)
        maker.Build()
        if not maker.IsDone():
            return None
        result = maker.Shape()
        adapter = KernelHistoryAdapter(maker)
        history = KernelHistorySnapshot()
        for i, (edge, _dist) in enumerate(edges_with_distances):
            key = f"edge_{i}"
            if adapter.is_deleted(edge):
                history.deleted.append(key)
            gen = adapter.generated(edge)
            if gen:
                history.generated[key] = gen
        if input_faces:
            for i, face in enumerate(input_faces):
                key = f"face_{i}"
                if not adapter.is_deleted(face):
                    mod = adapter.modified(face)
                    if mod:
                        history.modified[key] = mod
        return HistoryAwareShapeResult(
            result_shape=result, history=history,
            metrics={"builder": "BRepFilletAPI_MakeChamfer", "is_done": True,
                     "edge_count": len(edges_with_distances)},
        )
    except Exception:
        return None


def history_aware_shell(
    shape: Any,
    faces_to_remove: list[Any],
    thickness: float,
    *,
    input_faces: list[Any] | None = None,
) -> HistoryAwareShapeResult | None:
    """OCCT shell (hollow) with history capture.

    Uses BRepOffsetAPI_MakeThickSolid. Removed faces→deleted, remaining→modified.
    """
    try:
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
        from OCP.TopTools import TopTools_ListOfShape
    except ImportError:
        return None
    try:
        face_list = TopTools_ListOfShape()
        for face in faces_to_remove:
            face_list.Append(face)
        maker = BRepOffsetAPI_MakeThickSolid()
        maker.MakeThickSolidBySimple(shape, face_list, float(thickness), 1.0e-6)
        maker.Build()
        if not maker.IsDone():
            return None
        result = maker.Shape()
        adapter = KernelHistoryAdapter(maker)
        history = KernelHistorySnapshot()
        for i, face in enumerate(faces_to_remove):
            key = f"removed_face_{i}"
            if adapter.is_deleted(face):
                history.deleted.append(key)
        if input_faces:
            for i, face in enumerate(input_faces):
                key = f"face_{i}"
                if key not in history.deleted and not adapter.is_deleted(face):
                    mod = adapter.modified(face)
                    if mod:
                        history.modified[key] = mod
        return HistoryAwareShapeResult(
            result_shape=result, history=history,
            metrics={"builder": "BRepOffsetAPI_MakeThickSolid", "is_done": True,
                     "removed_faces": len(faces_to_remove), "thickness_mm": thickness},
        )
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# History-aware loft / sweep operations (Phase 5)
# ═══════════════════════════════════════════════════════════════════════════════


def history_aware_loft(
    profiles: list[Any],
    *,
    ruled: bool = False,
    input_edges: list[Any] | None = None,
) -> HistoryAwareShapeResult | None:
    """OCCT loft (ThruSections) with history capture.

    Uses BRepOffsetAPI_ThruSections to create a lofted solid through
    multiple cross-section profiles.

    Args:
        profiles: List of TopoDS_Wire/Face profiles (ordered start→end).
        ruled: If True, use ruled surfaces between sections.
        input_edges: Profile edges for tracking generated faces.

    Returns:
        HistoryAwareShapeResult or None if OCP unavailable.
    """
    try:
        from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    except ImportError:
        return None
    try:
        maker = BRepOffsetAPI_ThruSections(True)  # isSolid=True
        maker.SetRuled(ruled)
        for profile in profiles:
            maker.AddWire(profile) if hasattr(maker, 'AddWire') else maker.AddShape(profile)
        maker.Build()
        if not maker.IsDone():
            return None
        result = maker.Shape()
        adapter = KernelHistoryAdapter(maker)
        history = KernelHistorySnapshot()
        if input_edges:
            for i, edge in enumerate(input_edges):
                gen = adapter.generated(edge)
                if gen:
                    history.generated[f"edge_{i}"] = gen
        return HistoryAwareShapeResult(
            result_shape=result, history=history,
            metrics={"builder": "BRepOffsetAPI_ThruSections", "is_done": True,
                     "profile_count": len(profiles), "ruled": ruled},
        )
    except Exception:
        return None


def history_aware_sweep(
    path_wire: Any,
    profile_shape: Any,
    *,
    input_edges: list[Any] | None = None,
) -> HistoryAwareShapeResult | None:
    """OCCT sweep (MakePipe) with history capture.

    Uses BRepOffsetAPI_MakePipe to sweep a profile along a path.

    Args:
        path_wire: TopoDS_Wire defining the sweep path.
        profile_shape: TopoDS_Shape (face/wire) to sweep.
        input_edges: Profile edges for tracking generated side faces.

    Returns:
        HistoryAwareShapeResult or None if OCP unavailable.
    """
    try:
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
    except ImportError:
        return None
    try:
        maker = BRepOffsetAPI_MakePipe(path_wire, profile_shape)
        maker.Build()
        if not maker.IsDone():
            return None
        result = maker.Shape()
        adapter = KernelHistoryAdapter(maker)
        history = KernelHistorySnapshot()
        if input_edges:
            for i, edge in enumerate(input_edges):
                gen = adapter.generated(edge)
                if gen:
                    history.generated[f"edge_{i}"] = gen
        return HistoryAwareShapeResult(
            result_shape=result, history=history,
            metrics={"builder": "BRepOffsetAPI_MakePipe", "is_done": True},
        )
    except Exception:
        return None
