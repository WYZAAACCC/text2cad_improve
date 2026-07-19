"""Deterministic semantic topology naming for primitive shapes.

Phase 1: box, cylinder.
Phase 2+: extrude, revolve, hole, boolean.

Uses geometry properties (surface type, normal direction, bbox extremes)
to assign stable semantic roles. Does NOT rely on B-Rep face enumeration
order — roles are determined by geometric analysis, not array position.
"""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyDelta,
    TopologyEntityRecord,
    TopologyRelation,
)


def name_box_faces(
    solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    w: float,
    h: float,
    d: float,
) -> TopologyDelta:
    """Semantically name the 6 faces of a box primitive.

    Method: classify each face by its dominant normal direction.
    The face whose outward normal is closest to +X is "x_max", etc.
    This is stable as long as the box dimensions remain positive — the
    normal direction is invariant under dimension changes.

    Returns:
        TopologyDelta with 6 primitive relations, one per face.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    faces = solid.faces().vals()
    relations: list[TopologyRelation] = []

    for i, face in enumerate(faces):
        try:
            normal = face.normalAt()
        except Exception:
            # Face inspection failed — assign fallback role
            relations.append(TopologyRelation(
                relation="primitive",
                result_entity_keys=[
                    _make_compact_id(document_id, component_id, producer_node_id,
                                     "face", f"box/fallback/{i}")
                ],
                semantic_role=f"box/fallback/{i}",
                evidence={"method": "fallback_enumerate", "entity_type": "face", "index": i},
            ))
            continue

        # Determine semantic role by dominant normal component
        nx, ny, nz = abs(normal.x), abs(normal.y), abs(normal.z)
        if nx > ny and nx > nz:
            role = "box/x_max" if normal.x > 0 else "box/x_min"
        elif ny > nx and ny > nz:
            role = "box/y_max" if normal.y > 0 else "box/y_min"
        else:
            role = "box/z_max" if normal.z > 0 else "box/z_min"

        relations.append(TopologyRelation(
            relation="primitive",
            result_entity_keys=[
                _make_compact_id(document_id, component_id, producer_node_id,
                                 "face", role)
            ],
            semantic_role=role,
            evidence={
                "method": "bbox_extreme_normal",
                "entity_type": "face",
                "normal": (
                    round(normal.x, 3),
                    round(normal.y, 3),
                    round(normal.z, 3),
                ),
            },
        ))

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[body_handle],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="1.0.0",
    )


def name_cylinder_faces(
    solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    dia: float,
    height: float,
) -> TopologyDelta:
    """Semantically name faces of a cylinder: lateral, cap_start, cap_end.

    Method:
      1. Classify by surface type: CYLINDER → lateral, PLANE → cap
      2. For planar caps, use Z position to distinguish start vs end.
         cap_start = negative Z (or lower Z for inverted orientation)
         cap_end   = positive Z (or higher Z)

    For a full 360° cylinder:
      - lateral: 1 face
      - cap_start: 1 face (Z-)
      - cap_end: 1 face (Z+)

    Returns:
        TopologyDelta with 3 (or fewer) primitive relations.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    faces = solid.faces().vals()
    relations: list[TopologyRelation] = []

    for i, face in enumerate(faces):
        try:
            center = face.Center()
            stype = face.geomType()
        except Exception:
            relations.append(TopologyRelation(
                relation="primitive",
                result_entity_keys=[
                    _make_compact_id(document_id, component_id, producer_node_id,
                                     "face", f"cylinder/face_{i}")
                ],
                semantic_role=f"cylinder/face_{i}",
                evidence={"method": "fallback_enumerate", "entity_type": "face", "index": i},
            ))
            continue

        if stype == "CYLINDER":
            role = "cylinder/lateral"
        elif stype == "PLANE":
            if center.z > 0:
                role = "cylinder/cap_end"
            else:
                role = "cylinder/cap_start"
        else:
            role = f"cylinder/face_{i}"

        relations.append(TopologyRelation(
            relation="primitive",
            result_entity_keys=[
                _make_compact_id(document_id, component_id, producer_node_id,
                                 "face", role)
            ],
            semantic_role=role,
            evidence={
                "method": "surface_type_plus_position",
                "surface_type": stype,
                "center_z": round(center.z, 3),
                "runtime_index": i,
            },
        ))

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[body_handle],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="1.0.0",
    )


def name_sphere_faces(
    solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
) -> TopologyDelta:
    """Semantically name the face(s) of a sphere primitive.

    A sphere has a single face: the outer spherical surface.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    relations = [
        TopologyRelation(
            relation="primitive",
            result_entity_keys=[
                _make_compact_id(document_id, component_id, producer_node_id,
                                 "face", "sphere/outer_surface")
            ],
            semantic_role="sphere/outer_surface",
            evidence={"method": "primitive_type", "primitive": "sphere"},
        ),
    ]

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[body_handle],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="1.0.0",
    )


def build_entity_records_from_delta(
    delta: TopologyDelta,
    document_id: str,
) -> list[TopologyEntityRecord]:
    """Build TopologyEntityRecord list from a semantic naming TopologyDelta.

    Call this after the delta is produced, then register each record
    into the TopologyRegistry BEFORE calling apply_delta().

    Args:
        delta: The semantic naming delta from name_box_faces etc.
        document_id: Matches CanonicalGcadDocument.document_id.

    Returns:
        List of TopologyEntityRecord ready for registry.register_entity().
    """
    records: list[TopologyEntityRecord] = []
    for relation in delta.relations:
        # Determine status from relation type
        if relation.relation == "deleted":
            entity_status = "deleted"
        elif relation.relation in ("merged", "split"):
            entity_status = "active"  # still resolvable but via set
        else:
            entity_status = "active"

        # Handle both result_entity_keys AND source_ids
        keys_to_register = list(relation.result_entity_keys)
        # For deleted/split relations, also register source entities
        if relation.relation in ("deleted", "split", "modified"):
            keys_to_register.extend(relation.source_ids)

        for key in keys_to_register:
            # Derive entity type from relation metadata (v2 keys are opaque hashes,
            # cannot be round-tripped like v1 colon-delimited format)
            entity_type_str = _infer_entity_type(
                relation.semantic_role, relation.evidence,
            )

            records.append(TopologyEntityRecord(
                persistent_id=key,
                entity_type=entity_type_str,  # type: ignore[arg-type]
                component_id=delta.component_id,
                owner_body_handle_id=(
                    delta.result_body_handle_ids[0]
                    if delta.result_body_handle_ids
                    else ""
                ),
                producer_node_id=delta.node_id,
                semantic_role=relation.semantic_role or "unknown",
                generation=0,
                status=entity_status,  # type: ignore[arg-type]
                resolution_method="primitive_semantic",
                confidence=1.0,
                evidence=[relation.evidence] if relation.evidence else [],
            ))
    return records


# ── Internal helpers ──


def _infer_entity_type(
    semantic_role: str | None,
    evidence: dict,
) -> str:
    """Derive entity type from relation evidence.

    V3: entity_type is recorded in relation.evidence by each name_* function.
    No longer guesses from semantic_role string patterns.
    Default: 'face'.
    """
    # Primary: from evidence (V3: all name_* functions set this)
    if evidence:
        ev_type = evidence.get("entity_type", "")
        if ev_type:
            return ev_type
    # Fallback: check explicit type prefix in semantic_role (legacy compat)
    if semantic_role and "/" in semantic_role:
        prefix = semantic_role.split("/")[0].lower()
        if prefix in ("edge", "face", "solid", "shell", "wire", "vertex"):
            return prefix
    return "face"


def _make_compact_id(
    document_id: str,
    component_id: str,
    producer_node_id: str,
    entity_type: str,
    semantic_role: str,
) -> str:
    """Create a v2 PersistentTopoId authoritative key string.

    Uses PersistentTopoIdV2.to_key() which produces a content-hash-based
    key (gct2_<base64url sha256>) — no truncation, no colon-encoding issues.
    """
    from seekflow_engineering_tools.generative_cad.topology.ids import (
        PersistentTopoIdV2,
    )
    pid = PersistentTopoIdV2(
        document_id=document_id,
        component_id=component_id,
        lineage_root_node_id=producer_node_id,
        producer_node_id=producer_node_id,
        entity_type=entity_type,  # type: ignore[arg-type]
        semantic_role=semantic_role,
    )
    return pid.to_key()


# ═══════════════════════════════════════════════════════════════════════════════
# Extrude face naming (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════════


def name_extrude_faces(
    solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    extrude_plane: str = "XY",
    direction: str = "+",
) -> TopologyDelta:
    """Semantically name faces of an extruded solid.

    Classifies faces into:
      - end_cap_positive: planar face at the +extrude direction extreme
      - end_cap_negative: planar face at the -extrude direction extreme
      - side_face_N: lateral faces (one per profile edge, indexed by enumeration)

    Method:
      1. Group faces by surface type (PLANE vs other)
      2. Planar faces: classify by normal direction vs extrude axis
         - If normal aligns with extrude axis: it's a cap
         - If normal is perpendicular: it's a side face
      3. For caps: use position along extrude axis to distinguish +/- end

    Args:
        solid: CadQuery solid result from extrusion.
        document_id: Canonical document ID.
        component_id: Component ID.
        producer_node_id: Node that produced this solid.
        extrude_plane: "XY", "YZ", or "XZ" — the sketch plane.
        direction: "+" or "-" — the extrude direction relative to plane normal.

    Returns:
        TopologyDelta with semantic face relations.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"

    # Determine extrude axis from plane
    plane_axes = {"XY": "Z", "YZ": "X", "XZ": "Y"}
    extrude_axis = plane_axes.get(extrude_plane, "Z")

    faces = solid.faces().vals()
    relations: list[TopologyRelation] = []
    side_count = 0

    for i, face in enumerate(faces):
        try:
            stype = face.geomType()
            center = face.Center()
            normal = face.normalAt()
        except Exception:
            relations.append(_make_fallback_relation(
                document_id, component_id, producer_node_id, "face", f"extrude/face_{i}", i,
            ))
            continue

        if stype == "PLANE":
            # Determine if cap or side by comparing normal with extrude axis
            axis_components = {
                "X": abs(normal.x), "Y": abs(normal.y), "Z": abs(normal.z),
            }
            axis_normal = axis_components.get(extrude_axis, 0)

            if axis_normal > 0.9:
                # Cap face — normal is parallel to extrude axis
                axis_position = {"X": center.x, "Y": center.y, "Z": center.z}[extrude_axis]
                if (direction == "+" and axis_position > 0) or (direction == "-" and axis_position < 0):
                    role = "extrude/end_cap_positive"
                else:
                    role = "extrude/end_cap_negative"
            else:
                # Side face — normal is perpendicular to extrude axis
                role = f"extrude/side_face_{side_count}"
                side_count += 1
        else:
            role = f"extrude/side_face_{side_count}"
            side_count += 1

        relations.append(TopologyRelation(
            relation="primitive",
            result_entity_keys=[
                _make_compact_id(document_id, component_id, producer_node_id, "face", role)
            ],
            semantic_role=role,
            evidence={
                "method": "extrude_face_classification",
                "surface_type": stype,
                "extrude_plane": extrude_plane,
                "extrude_axis": extrude_axis,
                "direction": direction,
                "runtime_index": i,
            },
        ))

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[body_handle],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="2.0.0",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Revolve face naming (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════════


def name_revolve_faces(
    solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    angle_deg: float = 360.0,
    axis: str = "Z",
) -> TopologyDelta:
    """Semantically name faces of a revolved solid.

    Classifies faces into:
      - revolve/lateral: faces with cylindrical/conical/spherical/toroidal surfaces
      - revolve/cap_start: planar face at revolution start (only if angle < 360)
      - revolve/cap_end: planar face at revolution end (only if angle < 360)

    Method:
      1. Planar faces → potential caps (only present for partial revolves)
      2. Non-planar faces → lateral (revolved from profile edges)
      3. For caps, use angular position to distinguish start vs end

    For full 360° revolves, there are typically no planar cap faces — all
    faces are cylindrical/conical surface-of-revolution types.

    Args:
        solid: CadQuery solid result from revolution.
        document_id: Canonical document ID.
        component_id: Component ID.
        producer_node_id: Node that produced this solid.
        angle_deg: Revolution angle in degrees (360 = full revolve).
        axis: Revolution axis ("X", "Y", or "Z").

    Returns:
        TopologyDelta with semantic face relations.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    full_revolve = abs(angle_deg - 360.0) < 0.01

    faces = solid.faces().vals()
    relations: list[TopologyRelation] = []
    lateral_count = 0

    for i, face in enumerate(faces):
        try:
            stype = face.geomType()
            center = face.Center()
        except Exception:
            relations.append(_make_fallback_relation(
                document_id, component_id, producer_node_id, "face", f"revolve/face_{i}", i,
            ))
            continue

        if stype == "PLANE" and not full_revolve:
            # Cap face — only exists for partial revolves
            # Determine start vs end by angular position
            axis_position = {"X": center.y, "Y": center.z, "Z": center.x}[axis]
            if axis_position >= 0:
                role = "revolve/cap_end"
            else:
                role = "revolve/cap_start"
        else:
            # Surface-of-revolution face (CYLINDER, CONE, SPHERE, TORUS, etc.)
            role = f"revolve/lateral_{lateral_count}"
            lateral_count += 1

        relations.append(TopologyRelation(
            relation="primitive",
            result_entity_keys=[
                _make_compact_id(document_id, component_id, producer_node_id, "face", role)
            ],
            semantic_role=role,
            evidence={
                "method": "revolve_face_classification",
                "surface_type": stype,
                "full_revolve": full_revolve,
                "angle_deg": angle_deg,
                "axis": axis,
                "runtime_index": i,
            },
        ))

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[body_handle],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="2.0.0",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Hole / Cut face naming (Phase 3)
# ═══════════════════════════════════════════════════════════════════════════════


def name_hole_faces(
    tool_solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    tool_node_id: str | None = None,
    is_through_hole: bool = True,
) -> TopologyDelta:
    """Name faces produced by a hole/cut operation by analyzing the tool body.

    The tool body (typically a cylinder for circular holes) has faces that
    map to hole semantics:
      - tool/lateral (CYLINDER face) → hole_wall in the result
      - tool/cap_start (PLANE face, Z-) → entry_rim (circular edge) in the result
      - tool/cap_end (PLANE face, Z+) → exit_rim (circular edge) in the result
      - All tool faces → marked as DELETED (consumed by the boolean cut)

    For blind holes: exit_rim is marked as zero_or_one (may be absent).

    Args:
        tool_solid: The cutter solid (e.g., cylinder) BEFORE the cut.
        document_id: Canonical document ID.
        component_id: Component ID.
        producer_node_id: Node that produced the hole.
        tool_node_id: Optional distinct node ID for the tool body.
                      If None, uses producer_node_id.
        is_through_hole: True if the hole goes all the way through.

    Returns:
        TopologyDelta with hole face relations and tool face deletions.
    """
    tool_nid = tool_node_id or producer_node_id
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    relations: list[TopologyRelation] = []

    # Step 1: Name the tool body faces
    faces = tool_solid.faces().vals()
    tool_lateral_key: str | None = None
    tool_cap_start_key: str | None = None
    tool_cap_end_key: str | None = None
    lateral_idx = 0  # Index for duplicate lateral faces (hollow tubes)

    for i, face in enumerate(faces):
        try:
            stype = face.geomType()
            center = face.Center()
        except Exception:
            continue

        if stype == "CYLINDER":
            # Handle duplicate lateral faces (inner + outer for hollow cutters)
            if tool_lateral_key is not None:
                lateral_idx += 1
                role = f"hole_tool/lateral_{lateral_idx}"
            else:
                role = "hole_tool/lateral"
            key = _make_compact_id(document_id, component_id, tool_nid, "face", role)
            if tool_lateral_key is None:
                tool_lateral_key = key
            relations.append(TopologyRelation(
                relation="deleted",
                source_ids=[key],
                semantic_role=role,
                evidence={"method": "hole_tool_naming", "surface_type": stype, "runtime_index": i},
            ))
        elif stype == "PLANE":
            if center.z > 0:
                role = "hole_tool/cap_end"
                key = _make_compact_id(document_id, component_id, tool_nid, "face", role)
                tool_cap_end_key = key
            else:
                role = "hole_tool/cap_start"
                key = _make_compact_id(document_id, component_id, tool_nid, "face", role)
                tool_cap_start_key = key
            relations.append(TopologyRelation(
                relation="deleted",
                source_ids=[key],
                semantic_role=role,
                evidence={"method": "hole_tool_naming", "surface_type": stype, "runtime_index": i},
            ))

    # Step 2: Map tool faces → hole semantics
    if tool_lateral_key:
        hole_wall_id = _make_compact_id(document_id, component_id, producer_node_id, "face", "hole/wall")
        relations.append(TopologyRelation(
            relation="generated",
            source_ids=[tool_lateral_key],
            result_entity_keys=[hole_wall_id],
            semantic_role="hole/wall",
            evidence={"method": "tool_to_hole_mapping", "source": "tool/lateral", "target": "hole/wall"},
        ))

    if tool_cap_start_key:
        entry_rim_id = _make_compact_id(document_id, component_id, producer_node_id, "edge", "hole/entry_rim")
        relations.append(TopologyRelation(
            relation="generated",
            source_ids=[tool_cap_start_key],
            result_entity_keys=[entry_rim_id],
            semantic_role="hole/entry_rim",
            evidence={"method": "tool_to_hole_mapping", "source": "tool/cap_start", "target": "hole/entry_rim"},
        ))

    if tool_cap_end_key and is_through_hole:
        exit_rim_id = _make_compact_id(document_id, component_id, producer_node_id, "edge", "hole/exit_rim")
        relations.append(TopologyRelation(
            relation="generated",
            source_ids=[tool_cap_end_key],
            result_entity_keys=[exit_rim_id],
            semantic_role="hole/exit_rim",
            evidence={"method": "tool_to_hole_mapping", "source": "tool/cap_end", "target": "hole/exit_rim"},
        ))

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[body_handle],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="3.0.0",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Fillet / Chamfer / Shell face naming (Phase 4)
# ═══════════════════════════════════════════════════════════════════════════════


def name_fillet_faces(
    original_solid: Any,
    result_solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    selected_edge_ids: list[str] | None = None,
) -> TopologyDelta:
    """Name faces produced by a fillet operation.

    Method:
      1. Classify result faces by surface type:
         - CYLINDER/SPHERE/TORUS → new fillet face (from old edge)
         - PLANE → potentially modified adjacent face
      2. Mark filleted edges as deleted
      3. Map: old_edge_id → fillet_face_from/<edge_id>

    For Cylindrical fillet faces (constant radius along an edge):
      role = "fillet/face_from/<edge_id>"

    Args:
        original_solid: The solid BEFORE fillet (for face comparison).
        result_solid: The solid AFTER fillet.
        document_id: Canonical document ID.
        component_id: Component ID.
        producer_node_id: Node that produced the fillet.
        selected_edge_ids: Optional persistent IDs of the filleted edges.
                           If None, edges are identified by index only.

    Returns:
        TopologyDelta with fillet face relations and edge deletions.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    relations: list[TopologyRelation] = []

    # Mark selected edges as deleted
    edge_ids = selected_edge_ids or []
    for eid in edge_ids:
        relations.append(TopologyRelation(
            relation="deleted",
            source_ids=[eid],
            semantic_role="fillet/deleted_edge",
            evidence={"method": "fillet_edge_deletion"},
        ))

    # Classify result faces
    faces = result_solid.faces().vals()
    fillet_idx = 0
    adjacent_idx = 0

    for i, face in enumerate(faces):
        try:
            stype = face.geomType()
        except Exception:
            relations.append(_make_fallback_relation(
                document_id, component_id, producer_node_id, "face", f"fillet/face_{i}", i,
            ))
            continue

        if stype in ("CYLINDER", "SPHERE", "TORUS"):
            # New fillet face
            if edge_ids and fillet_idx < len(edge_ids):
                role = f"fillet/face_from/{edge_ids[fillet_idx]}"
            else:
                role = f"fillet/face_{fillet_idx}"
            fillet_idx += 1
            relations.append(TopologyRelation(
                relation="generated",
                result_entity_keys=[
                    _make_compact_id(document_id, component_id, producer_node_id, "face", role)
                ],
                semantic_role=role,
                evidence={"method": "fillet_face_classification", "surface_type": stype,
                         "runtime_index": i},
            ))
        elif stype == "PLANE":
            # Potentially modified adjacent face
            role = f"fillet/adjacent_face_{adjacent_idx}"
            adjacent_idx += 1
            relations.append(TopologyRelation(
                relation="modified",
                result_entity_keys=[
                    _make_compact_id(document_id, component_id, producer_node_id, "face", role)
                ],
                semantic_role=role,
                evidence={"method": "fillet_adjacent_face", "surface_type": stype,
                         "runtime_index": i},
            ))

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[body_handle],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="4.0.0",
    )


def name_chamfer_faces(
    result_solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    selected_edge_ids: list[str] | None = None,
) -> TopologyDelta:
    """Name faces produced by a chamfer operation.

    Chamfer faces are PLANE (flat bevel faces, unlike fillet's curved faces).
    Classification: chamfer faces are new faces with small area near the
    original edge — identified as PLANE faces with area smaller than typical
    structural faces.

    Args:
        result_solid: The solid AFTER chamfer.
        document_id, component_id, producer_node_id: Standard identifiers.
        selected_edge_ids: Optional persistent IDs of chamfered edges.

    Returns:
        TopologyDelta with chamfer face relations.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    relations: list[TopologyRelation] = []

    edge_ids = selected_edge_ids or []
    for eid in edge_ids:
        relations.append(TopologyRelation(
            relation="deleted", source_ids=[eid],
            semantic_role="chamfer/deleted_edge",
        ))

    faces = result_solid.faces().vals()
    chamfer_idx = 0
    for i, face in enumerate(faces):
        try:
            stype = face.geomType()
            area = face.Area()
        except Exception:
            continue

        if stype == "PLANE" and area < 100:  # heuristic: chamfer faces are small
            if edge_ids and chamfer_idx < len(edge_ids):
                role = f"chamfer/face_from/{edge_ids[chamfer_idx]}"
            else:
                role = f"chamfer/face_{chamfer_idx}"
            chamfer_idx += 1
            relations.append(TopologyRelation(
                relation="generated",
                result_entity_keys=[
                    _make_compact_id(document_id, component_id, producer_node_id, "face", role)
                ],
                semantic_role=role,
                evidence={"method": "chamfer_face_classification", "surface_type": stype,
                         "area": round(area, 3), "runtime_index": i},
            ))

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[body_handle],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="4.0.0",
    )


def name_shell_faces(
    result_solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    removed_face_ids: list[str] | None = None,
) -> TopologyDelta:
    """Name faces produced by a shell (hollow) operation.

    Removed faces → deleted.
    Remaining faces → offset (modified from original).
    New interior faces → generated (inner walls).

    Args:
        result_solid: The solid AFTER shelling.
        document_id, component_id, producer_node_id: Standard identifiers.
        removed_face_ids: Persistent IDs of faces removed for the opening.

    Returns:
        TopologyDelta with shell face relations.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    relations: list[TopologyRelation] = []

    face_ids = removed_face_ids or []
    for fid in face_ids:
        relations.append(TopologyRelation(
            relation="deleted", source_ids=[fid],
            semantic_role="shell/removed_face",
        ))

    faces = result_solid.faces().vals()
    for i, face in enumerate(faces):
        try:
            stype = face.geomType()
        except Exception:
            continue

        role = f"shell/face_{i}" if stype != "PLANE" else f"shell/wall_face_{i}"
        relations.append(TopologyRelation(
            relation="modified",
            result_entity_keys=[
                _make_compact_id(document_id, component_id, producer_node_id, "face", role)
            ],
            semantic_role=role,
            evidence={"method": "shell_face", "surface_type": stype, "runtime_index": i},
        ))

    return TopologyDelta(
        node_id=producer_node_id,
        component_id=component_id,
        result_body_handle_ids=[body_handle],
        relations=relations,
        history_provider="operation_semantics",
        history_provider_version="4.0.0",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Loft / Sweep face naming (Phase 5)
# ═══════════════════════════════════════════════════════════════════════════════


def name_loft_faces(
    solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
    section_count: int = 2,
) -> TopologyDelta:
    """Name faces of a lofted solid by section order.

    Method:
      - PLANE faces at extreme Z → loft/cap_start, loft/cap_end
      - Other faces → loft/lateral_N (transition faces between sections)

    Args:
        solid: CadQuery solid result from loft.
        document_id, component_id, producer_node_id: Standard identifiers.
        section_count: Number of cross-sections in the loft.

    Returns:
        TopologyDelta with loft face relations.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    faces = solid.faces().vals()
    relations: list[TopologyRelation] = []
    lateral_idx = 0

    for i, face in enumerate(faces):
        try:
            stype = face.geomType()
            center = face.Center()
        except Exception:
            relations.append(_make_fallback_relation(
                document_id, component_id, producer_node_id, "face", f"loft/face_{i}", i,
            ))
            continue

        if stype == "PLANE":
            if center.z > 0:
                role = "loft/cap_end"
            else:
                role = "loft/cap_start"
        else:
            role = f"loft/lateral_{lateral_idx}"
            lateral_idx += 1

        relations.append(TopologyRelation(
            relation="primitive",
            result_entity_keys=[
                _make_compact_id(document_id, component_id, producer_node_id, "face", role)
            ],
            semantic_role=role,
            evidence={"method": "loft_face_classification", "surface_type": stype,
                     "section_count": section_count, "runtime_index": i},
        ))

    return TopologyDelta(
        node_id=producer_node_id, component_id=component_id,
        result_body_handle_ids=[body_handle], relations=relations,
        history_provider="operation_semantics", history_provider_version="5.0.0",
    )


def name_sweep_faces(
    solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
) -> TopologyDelta:
    """Name faces of a swept solid.

    Method:
      - PLANE faces → sweep/cap_start, sweep/cap_end
      - Other faces → sweep/lateral_N (faces along the sweep path)

    Args:
        solid: CadQuery solid result from sweep.
        document_id, component_id, producer_node_id: Standard identifiers.

    Returns:
        TopologyDelta with sweep face relations.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    faces = solid.faces().vals()
    relations: list[TopologyRelation] = []
    lateral_idx = 0

    for i, face in enumerate(faces):
        try:
            stype = face.geomType()
        except Exception:
            relations.append(_make_fallback_relation(
                document_id, component_id, producer_node_id, "face", f"sweep/face_{i}", i,
            ))
            continue

        if stype == "PLANE":
            role = "sweep/cap_end" if lateral_idx > 0 else "sweep/cap_start"
        else:
            role = f"sweep/lateral_{lateral_idx}"
            lateral_idx += 1

        relations.append(TopologyRelation(
            relation="primitive",
            result_entity_keys=[
                _make_compact_id(document_id, component_id, producer_node_id, "face", role)
            ],
            semantic_role=role,
            evidence={"method": "sweep_face_classification", "surface_type": stype, "runtime_index": i},
        ))

    return TopologyDelta(
        node_id=producer_node_id, component_id=component_id,
        result_body_handle_ids=[body_handle], relations=relations,
        history_provider="operation_semantics", history_provider_version="5.0.0",
    )


def extract_sketch_element_ids(
    nodes: list[Any],
) -> dict[str, str]:
    """Extract sketch element_id → semantic_role mapping from canonical nodes.

    Iterates over nodes looking for sketch element params with element_id set.
    Returns {element_id: semantic_role} dict for all elements with IDs.

    Used by extrude/revolve/loft/sweep naming to map side faces back to
    specific sketch edges via their stable element_id.

    Args:
        nodes: List of CanonicalNode objects (from one component).

    Returns:
        Dict mapping element_id → semantic_role (or element_id if no role).
    """
    element_map: dict[str, str] = {}
    for node in nodes:
        params = getattr(node, "typed_params", None) or getattr(node, "params", {})
        eid = params.get("element_id") if isinstance(params, dict) else None
        if eid:
            role = params.get("semantic_role") if isinstance(params, dict) else None
            element_map[str(eid)] = str(role) if role else str(eid)
    return element_map


def name_boolean_faces(
    solid: Any,
    *,
    document_id: str,
    component_id: str,
    producer_node_id: str,
) -> TopologyDelta:
    """Name faces of a boolean result solid by surface type.

    Boolean results (union/cut/intersect) contain a mix of:
      - Modified faces from input bodies
      - Generated intersection faces

    Without OCP history, faces are classified by geometric surface type.
    This provides stable type-based identity for each face.

    Args:
        solid: CadQuery solid result from boolean operation.
        document_id, component_id, producer_node_id: Standard identifiers.

    Returns:
        TopologyDelta with boolean face relations.
    """
    body_handle = f"solid:{component_id}:{producer_node_id}:body"
    faces = solid.faces().vals()
    relations: list[TopologyRelation] = []
    type_counts: dict[str, int] = {}

    for i, face in enumerate(faces):
        try:
            stype = face.geomType()
        except Exception:
            relations.append(_make_fallback_relation(
                document_id, component_id, producer_node_id, "face", f"boolean/face_{i}", i,
            ))
            continue

        idx = type_counts.get(stype, 0)
        type_counts[stype] = idx + 1
        role = f"boolean/face_{stype}_{idx}"

        relations.append(TopologyRelation(
            relation="modified",
            result_entity_keys=[
                _make_compact_id(document_id, component_id, producer_node_id, "face", role)
            ],
            semantic_role=role,
            evidence={"method": "boolean_face_classification", "surface_type": stype,
                     "runtime_index": i},
        ))

    return TopologyDelta(
        node_id=producer_node_id, component_id=component_id,
        result_body_handle_ids=[body_handle], relations=relations,
        history_provider="operation_semantics", history_provider_version="5.0.0",
    )


def _make_fallback_relation(
    document_id: str,
    component_id: str,
    producer_node_id: str,
    entity_type: str,
    fallback_role: str,
    runtime_index: int,
) -> TopologyRelation:
    """Create a fallback topology relation when face inspection fails."""
    return TopologyRelation(
        relation="primitive",
        result_entity_keys=[
            _make_compact_id(document_id, component_id, producer_node_id, entity_type, fallback_role)
        ],
        semantic_role=fallback_role,
        evidence={"method": "fallback_enumerate", "index": runtime_index},
    )
