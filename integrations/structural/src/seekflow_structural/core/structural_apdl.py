"""Materialize a neutral structural intent into audited APDL input."""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

from seekflow_structural.core import element_face_map
from seekflow_structural.core.element_face_map import read_mesh
from seekflow_structural.core.structural_intent_models import StructuralIntent
from seekflow_structural.core.temperature_field import build_temperature_field, summary_block


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _norm(a: list[float]) -> float:
    return math.sqrt(_dot(a, a))


def _contiguous_runs(values: list[int]) -> list[tuple[int, int]]:
    """Collapse a sorted id list into the ranges ESEL can name."""
    runs: list[tuple[int, int]] = []
    for value in values:
        if runs and value == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], value)
        else:
            runs.append((value, value))
    return runs


def _resolve_total_force(load, rotation) -> float:
    """The force one sector's load surface carries, whichever way it is given."""
    total_force = load.total_force_n_per_slot
    if load.model == "mass_centroid_rpm":
        omega = rotation.omega_rad_s
        total_force = (
            float(load.effective_mass_kg)
            * float(load.center_of_mass_radius_mm)
            / 1000.0
            * omega
            * omega
            * int(load.blades_per_slot)
        )
    total_force = float(total_force)
    if total_force <= 0:
        raise ValueError("resolved blade force must be positive")
    return total_force


def emission_mode(intent: StructuralIntent) -> str:
    """Which way this intent's load reaches the material.

    A bearing surface transmits its load normal to itself, so it is a pressure
    and `SFE` states it directly, with the sign handled by ANSYS. The radial
    rule is not a surface traction at all - it is a distributed radial pull, a
    different physical idealisation - so it stays on nodal forces rather than
    being forced into a pressure it is not. That is a limit of what a pressure
    can express, not a check on the agent.
    """
    load = intent.blade_load
    if load is None:
        raise ValueError("blade_load intent is required")
    if load.direction_rule == "flank_surface_normal":
        if load.distribution == "area_weighted_uniform_pressure":
            return "surface_pressure"
        return "nodal_force"
    if load.direction_rule == "radial_outward_from_rotation_axis":
        if load.distribution == "area_weighted_uniform_pressure":
            raise ValueError(
                "a uniform pressure cannot express "
                "radial_outward_from_rotation_axis: pressure acts along the "
                "face normal, and that rule pushes every node straight out "
                "from the axis regardless of how the flank is inclined. Use "
                "flank_surface_normal for a bearing load, or "
                "area_weighted_equal_nodes for a radial one."
            )
        return "nodal_force"
    raise ValueError(f"unsupported direction rule {load.direction_rule!r}")


def _read_nodes(mesh_inp: Path) -> dict[int, list[float]]:
    nodes: dict[int, list[float]] = {}
    for line in mesh_inp.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("N,"):
            continue
        parts = line.strip().split(",")
        if len(parts) != 5:
            continue
        nodes[int(parts[1])] = [float(value) for value in parts[2:5]]
    return nodes


def _build_force_rows(
    intent: StructuralIntent,
    selected_face_nodes: Path,
    nodes: dict[int, list[float]],
    mesh_inp: Path | None = None,
) -> tuple[list[tuple[int, list[float]]], dict]:
    """Build the load, by whichever mechanism the intent asks for.

    The nodal path is kept alongside the surface-pressure one deliberately: it
    is the control the new path is measured against, and a change in the
    global answer is only interpretable next to the answer it replaced.
    """
    if emission_mode(intent) == "surface_pressure":
        if mesh_inp is None:
            raise ValueError(
                "a surface pressure load needs the mesh, to find which "
                "element faces lie on the selected CAD faces"
            )
        return _build_surface_pressure_load(
            intent, selected_face_nodes, nodes, mesh_inp
        )
    return _build_nodal_force_load(intent, selected_face_nodes, nodes)


def _build_surface_pressure_load(
    intent: StructuralIntent,
    selected_face_nodes: Path,
    nodes: dict[int, list[float]],
    mesh_inp: Path,
) -> tuple[list[tuple[int, list[float]]], dict]:
    """Apply the blade load as a uniform pressure on the selected faces.

    This is what the load always was. The direction rule takes the inward face
    normal and the force is already proportional to area, which together are
    the definition of a uniform pressure - it was simply being delivered as
    point forces at nodes instead. `SFE` with a positive PRES pushes into the
    element, so the sign needs no arithmetic of its own and the load is immune
    to the normal-orientation mistakes the nodal path has to guard against.

    Returns no nodal rows: ANSYS builds the consistent load vector from the
    element shape functions, which is the point.
    """
    selection = json.loads(selected_face_nodes.read_text(encoding="utf-8"))
    load = intent.blade_load
    rotation = intent.rotation
    if load is None or rotation is None:
        raise ValueError("rotation and blade_load intents are required")

    total_force = _resolve_total_force(load, rotation)
    mesh_nodes, elements = read_mesh(mesh_inp)
    if not mesh_nodes or not elements:
        raise ValueError(f"{mesh_inp} contains no usable mesh")

    mapping = element_face_map.build(mesh_nodes, elements, selection)
    mapped_area = mapping.mapped_area_total_mm2()
    if mapped_area <= 0:
        raise ValueError(
            "the selected faces produced no element face to press on; "
            "refine the mesh, or re-run the face-to-node mapping - a curved "
            "selected face maps to nothing because the mapping is planar-only"
        )

    # The faces of a fir-tree slot do not all point the same way, so the
    # resultant is the vector sum of area times normal - not the sum of the
    # areas. Dividing the target by the area alone therefore under-applies the
    # load: on D27 the two differ by 21%, which is invisible in the pressure
    # itself and only shows up as a resultant that misses its target.
    applied_direction = [0.0, 0.0, 0.0]
    for faces in mapping.faces.values():
        for face in faces:
            for index in range(3):
                applied_direction[index] -= (
                    face.area_mm2 * face.outward_normal[index]
                )
    direction_magnitude = _norm(applied_direction)
    if direction_magnitude <= 0:
        raise ValueError(
            "the selected faces cancel each other out: their area-weighted "
            "normals sum to zero, so no single uniform pressure on them can "
            "produce a resultant along the intended direction"
        )
    pressure_mpa = total_force / direction_magnitude

    origin = rotation.axis_origin_mm
    axis = rotation.axis_direction
    resultant = [0.0, 0.0, 0.0]
    moment = [0.0, 0.0, 0.0]
    element_faces = []
    force_by_face = {}
    for face_index, faces in mapping.faces.items():
        face_vector = [0.0, 0.0, 0.0]
        for face in faces:
            # A positive pressure pushes into the element, so the force on the
            # material runs opposite to the outward normal.
            magnitude = pressure_mpa * face.area_mm2
            force = [-magnitude * value for value in face.outward_normal]
            for index in range(3):
                resultant[index] += force[index]
                face_vector[index] += force[index]
            rel = [
                face.centroid_mm[index] - origin[index] for index in range(3)
            ]
            moment[0] += rel[1] * force[2] - rel[2] * force[1]
            moment[1] += rel[2] * force[0] - rel[0] * force[2]
            moment[2] += rel[0] * force[1] - rel[1] * force[0]
            element_faces.append(
                {
                    "elem": face.elem,
                    "lkey": face.lkey,
                    "area_mm2": round(face.area_mm2, 8),
                }
            )
        force_by_face[face_index] = {
            "allocated_force_n": pressure_mpa * mapping.mapped_area_mm2(
                face_index
            ),
            "element_face_count": len(faces),
            "vector_n": face_vector,
        }

    # Which way the pressure on this selection pushes, as a fraction of the
    # resultant: +1 straight out from the axis, -1 straight in, 0 a set that
    # cancels. It is a property of the selection's geometry, and nothing about
    # the magnitude of the applied force would say so - a load of ten thousand
    # newtons pulling a disc outward and one pushing it inward are the same
    # number.
    #
    # It is measured and recorded, not enforced. This used to raise, which
    # made writing the deck conditional on the harness agreeing with the face
    # selection - a hard-coded idea of what a load face is, decided three
    # stages after the selection was made and after the most expensive work in
    # the chain had already been spent. The judgement belongs in the
    # verification stage, which compares this same quantity and reports what
    # it contradicts; a stage that refuses to write the deck is a stage that
    # has taken the reader's job.
    mean_radial = [0.0, 0.0, 0.0]
    for faces in mapping.faces.values():
        for face in faces:
            rel = [
                face.centroid_mm[index] - origin[index] for index in range(3)
            ]
            axial = _dot(rel, axis)
            for index in range(3):
                mean_radial[index] += (
                    rel[index] - axial * axis[index]
                ) * pressure_mpa * face.area_mm2
    mean_norm = _norm(mean_radial)
    resultant_norm = _norm(resultant)
    pressure_radial_fraction = None
    if mean_norm > 0 and resultant_norm > 0:
        pressure_radial_fraction = round(
            _dot(resultant, [v / mean_norm for v in mean_radial])
            / resultant_norm,
            6,
        )

    twist_moment = _dot(moment, axis)
    audit = {
        "schema_version": "structural_load_audit_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": intent.case_id,
        "source": load.source,
        "model": load.model,
        "direction_rule": load.direction_rule,
        "distribution": load.distribution,
        "target_force_n_per_slot": total_force,
        "applied_node_count": 0,
        "applied_resultant_n": resultant,
        "applied_resultant_magnitude_n": _norm(resultant),
        # Which way the *resultant* of the applied pressure points, as a
        # fraction of its own length: +1 straight out from the axis, -1
        # straight in. Read by a person; nothing here refuses to write a deck
        # over it.
        #
        # Named for the resultant rather than for "the pressure direction",
        # because the assembly stage reports a different number for the same
        # selection - the area-weighted *mean* direction of the selected
        # faces. On D27's wrong selection those were -0.373 and -1.0: both
        # say inward, and they are not the same quantity. A set that partly
        # cancels has a mean direction between its faces and a resultant
        # along whatever is left over.
        "resultant_radial_fraction": pressure_radial_fraction,
        "resultant_relative_error": abs(_norm(resultant) - total_force)
        / total_force,
        "applied_moment_vector_about_origin_nmm": moment,
        "applied_twist_moment_about_axis_nmm": twist_moment,
        "force_by_face": force_by_face,
        "coordinate_system": (
            "global cartesian; pressure acts along the element face normal"
        ),
        "emission": {
            "mechanism": "surface_pressure",
            "ansys_command": "SFE,elem,lkey,PRES,0,p",
            "pressure_mpa": round(pressure_mpa, 8),
            # The area the pressure is actually divided by, next to the plain
            # sum of the areas. They differ wherever the selected faces do not
            # share a normal, and the pressure is set from the former.
            "resultant_direction_mm2": round(direction_magnitude, 4),
            "area_sum_mm2": round(mapped_area, 4),
            "element_faces": element_faces,
            "loaded_element_count": len({f["elem"] for f in element_faces}),
            "loaded_node_count": len(
                {n for face in mapping.faces.values() for f in face
                 for n in f.corner_nodes}
            ),
            **mapping.to_audit(),
        },
        "area_accounting_by_face": mapping.per_face_audit(),
        # Kept first because it is the one thing a reader is most likely to
        # misread: `applied_resultant_n` above is an identity. The pressure is
        # *defined* as target over mapped area, so the integral returns the
        # target by construction and its near-zero relative error is not
        # evidence of anything. The evidence is the area accounting.
        "limits": [
            "applied_resultant_n is an identity by construction: the pressure "
            "is defined from target_force_n_per_slot, so integrating it "
            "returns the target. resultant_relative_error therefore carries no "
            "diagnostic power on this path. Read the area accounting "
            "(mapped_area_total_mm2 against occ_area_total_mm2, and "
            "resultant_direction_mm2 against area_sum_mm2) and the ANSYS-side "
            "load-surface sum instead",
            *mapping.limits,
        ],
    }
    return [], audit


def _build_nodal_force_load(
    intent: StructuralIntent,
    selected_face_nodes: Path,
    nodes: dict[int, list[float]],
) -> tuple[list[tuple[int, list[float]]], dict]:
    selection = json.loads(selected_face_nodes.read_text(encoding="utf-8"))
    load = intent.blade_load
    rotation = intent.rotation
    if load is None or rotation is None:
        raise ValueError("rotation and blade_load intents are required")

    total_force = _resolve_total_force(load, rotation)
    if load.direction_rule not in {
        "radial_outward_from_rotation_axis",
        "flank_surface_normal",
    }:
        raise ValueError("unsupported direction rule")
    if load.distribution != "area_weighted_equal_nodes":
        raise ValueError(
            f"unsupported load distribution {load.distribution!r} for the "
            "nodal force path"
        )

    face_rows = list(selection["per_face"].items())
    total_area = sum(float(row["area_mm2"]) for _, row in face_rows)
    if total_area <= 0:
        raise ValueError("selected faces have zero total area")

    vectors: dict[int, list[float]] = {}
    force_by_face = {}
    origin = rotation.axis_origin_mm
    axis = rotation.axis_direction
    for face_index, row in face_rows:
        face_force = total_force * float(row["area_mm2"]) / total_area
        node_ids = [int(node_id) for node_id in row["node_ids"]]
        if not node_ids:
            raise ValueError(
                f"selected face {face_index} maps to zero mesh nodes; "
                "refine the mesh or re-run the face-to-node mapping"
            )
        node_force = face_force / len(node_ids)

        # A bearing surface transmits the load normal to itself: the blade root
        # presses on the flank, so the force on the disc runs along the inward
        # face normal. The radial rule instead pushes every node straight out
        # from the axis, which gets the resultant right but misplaces the
        # traction on an inclined flank.
        face_direction = None
        if load.direction_rule == "flank_surface_normal":
            normal = row.get("normal_xyz")
            if normal is None:
                raise ValueError(
                    f"face {face_index} has no normal_xyz in the mapping; "
                    "re-run map_solid_faces.py to regenerate the selection"
                )
            magnitude = _norm(normal)
            if magnitude <= 1e-15:
                raise ValueError(f"face {face_index} has a degenerate normal")
            face_direction = [-value / magnitude for value in normal]

        face_vector = [0.0, 0.0, 0.0]
        for node_id in node_ids:
            if face_direction is not None:
                direction = face_direction
            else:
                rel = [
                    nodes[node_id][index] - origin[index]
                    for index in range(3)
                ]
                axial = _dot(rel, axis)
                radial = [
                    rel[index] - axial * axis[index] for index in range(3)
                ]
                magnitude = _norm(radial)
                if magnitude <= 1e-15:
                    raise ValueError(f"node {node_id} lies on rotation axis")
                direction = [value / magnitude for value in radial]
            vector = [node_force * value for value in direction]
            # A node shared by two selected faces receives force from both;
            # accumulate instead of overwriting, otherwise the share carried
            # by the earlier face is silently dropped.
            accumulated = vectors.get(node_id)
            if accumulated is None:
                vectors[node_id] = vector
            else:
                for index in range(3):
                    accumulated[index] += vector[index]
            for index in range(3):
                face_vector[index] += vector[index]
        force_by_face[face_index] = {
            "allocated_force_n": face_force,
            "node_count": len(node_ids),
            "vector_n": face_vector,
        }

    resultant = [
        sum(vector[index] for vector in vectors.values()) for index in range(3)
    ]
    resultant_magnitude = _norm(resultant)
    if resultant_magnitude <= 1e-15:
        raise ValueError("nodal force resultant is zero")
    scale = total_force / resultant_magnitude
    vectors = {
        node_id: [value * scale for value in vector]
        for node_id, vector in vectors.items()
    }
    resultant = [
        sum(vector[index] for vector in vectors.values()) for index in range(3)
    ]

    # A bearing-surface load must resolve to an outward radial pull. A
    # mis-signed face normal would flip the resultant inward and still pass
    # every magnitude check, because the rescale below pins |resultant|.
    if load.direction_rule == "flank_surface_normal":
        mean_radial = [0.0, 0.0, 0.0]
        for node_id in vectors:
            rel = [nodes[node_id][i] - origin[i] for i in range(3)]
            axial = _dot(rel, axis)
            for i in range(3):
                mean_radial[i] += rel[i] - axial * axis[i]
        mean_norm = _norm(mean_radial)
        if mean_norm > 0:
            mean_radial = [value / mean_norm for value in mean_radial]
            if _dot(resultant, mean_radial) <= 0:
                raise ValueError(
                    "flank_surface_normal load resolves to an inward "
                    "resultant; the selected face normals point the wrong way"
                )

    moment = [0.0, 0.0, 0.0]
    for node_id, vector in vectors.items():
        rel = [nodes[node_id][index] - origin[index] for index in range(3)]
        moment[0] += rel[1] * vector[2] - rel[2] * vector[1]
        moment[1] += rel[2] * vector[0] - rel[0] * vector[2]
        moment[2] += rel[0] * vector[1] - rel[1] * vector[0]

    rows = []
    for node_id, vector in sorted(vectors.items()):
        rows.append((node_id, vector))
    twist_moment = _dot(moment, axis)
    audit = {
        "schema_version": "structural_load_audit_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": intent.case_id,
        "source": load.source,
        "model": load.model,
        "direction_rule": load.direction_rule,
        "distribution": load.distribution,
        "target_force_n_per_slot": total_force,
        "applied_node_count": len(rows),
        "applied_resultant_n": resultant,
        "applied_resultant_magnitude_n": _norm(resultant),
        "resultant_relative_error": abs(_norm(resultant) - total_force)
        / total_force,
        "applied_moment_vector_about_origin_nmm": moment,
        "applied_twist_moment_about_axis_nmm": twist_moment,
        "force_by_face": force_by_face,
        "coordinate_system": "local cylindrical nodal coordinates",
    }
    return rows, audit


def _format(value: float) -> str:
    return f"{float(value):.12g}"


def materialize_intent(
    intent: StructuralIntent,
    mesh_inp: Path,
    selected_face_nodes: Path,
    job_dir: Path,
    mesh_config: dict,
) -> dict:
    job_dir.mkdir(parents=True, exist_ok=True)
    local_mesh = job_dir / "mesh.inp"
    if mesh_inp.resolve() != local_mesh.resolve():
        shutil.copyfile(mesh_inp, local_mesh)
    nodes = _read_nodes(mesh_inp)
    if not nodes:
        raise ValueError("mesh contains no nodes")

    # The field is built once and evaluated once, here. The values it produces
    # are also written to node_temperature.csv, so the postprocessor can look
    # up the temperature the solver actually saw instead of recomputing it and
    # hoping the two agree.
    temperature_field = build_temperature_field(
        intent.temperature, intent.rotation, source_root=job_dir
    )
    temperature_values, temperature_coverage = temperature_field.evaluate(
        sorted(nodes.items())
    )
    temperature_rows = sorted(temperature_values.items())
    node_temperature_path = job_dir / "node_temperature.csv"
    with node_temperature_path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("nid,temperature_c\n")
        for node_id, value in temperature_rows:
            stream.write("%d,%s\n" % (node_id, _format(value)))

    mode = emission_mode(intent)
    force_rows, load_audit = _build_force_rows(
        intent, selected_face_nodes, nodes, mesh_inp
    )

    # Resolve each node's force into the cylindrical frame the deck rotates
    # into (CSYS,1 + NROTAT): FX radial, FY tangential, FZ axial. A radial
    # rule only ever needs FX, but a bearing-surface load is tilted, and
    # dropping its tangential part would quietly change the traction.
    axis = intent.rotation.axis_direction
    origin = intent.rotation.axis_origin_mm
    nodal_forces: list[tuple[int, float, float, float]] = []
    for node_id, vector in force_rows:
        rel = [nodes[node_id][index] - origin[index] for index in range(3)]
        axial = _dot(rel, axis)
        radial_direction = [rel[i] - axial * axis[i] for i in range(3)]
        magnitude = _norm(radial_direction)
        if magnitude <= 1e-15:
            raise ValueError(f"node {node_id} lies on rotation axis")
        radial_direction = [value / magnitude for value in radial_direction]
        tangential_direction = [
            axis[1] * radial_direction[2] - axis[2] * radial_direction[1],
            axis[2] * radial_direction[0] - axis[0] * radial_direction[2],
            axis[0] * radial_direction[1] - axis[1] * radial_direction[0],
        ]
        nodal_forces.append(
            (
                node_id,
                _dot(vector, radial_direction),
                _dot(vector, tangential_direction),
                _dot(vector, axis),
            )
        )

    has_tangential = any(abs(fy) > 1e-12 for _, _, fy, _ in nodal_forces)
    has_axial = any(abs(fz) > 1e-12 for _, _, _, fz in nodal_forces)

    load_path = job_dir / "load_table.inp"
    with load_path.open("w", encoding="ascii", newline="\n") as stream:
        if mode == "surface_pressure":
            emission = load_audit["emission"]
            stream.write(
                "! Agent-selected bearing faces, loaded as a uniform pressure\n"
            )
            stream.write(
                "! A positive PRES pushes into the element, so the applied\n"
                "! traction is the inward face normal - the same direction the\n"
                "! nodal path used to build by hand.\n"
            )
            for face in emission["element_faces"]:
                stream.write(
                    "SFE,%d,%d,PRES,0,%s\n"
                    % (face["elem"], face["lkey"],
                       _format(emission["pressure_mpa"]))
                )
            # Components naming the loaded surface, so POST1 can measure the
            # force crossing it - the only ANSYS-side number that scales with
            # the blade load. ESEL takes ranges, so element ids are written as
            # their contiguous runs.
            elements = sorted({f["elem"] for f in emission["element_faces"]})
            stream.write("ESEL,NONE\n")
            for start, end in _contiguous_runs(elements):
                stream.write("ESEL,A,ELEM,%d,%d\n" % (start, end))
            stream.write("CM,LOADELM,ELEM\n")
            stream.write("NSLE,S\n")
            stream.write("CM,LOADNOD,NODE\n")
            stream.write("ALLSEL\n")
        else:
            stream.write("! Agent-selected load surface nodes\n")
            stream.write(
                "! Nodal CS is cylindrical after NROTAT: FX radial, FY tangential.\n"
            )
            for node_id, radial_n, tangential_n, axial_n in nodal_forces:
                stream.write(f"F,{node_id},FX,{_format(radial_n)}\n")
                if has_tangential:
                    stream.write(f"F,{node_id},FY,{_format(tangential_n)}\n")
                if has_axial:
                    stream.write(f"F,{node_id},FZ,{_format(axial_n)}\n")
        stream.write(
            f"! Agent-selected {temperature_coverage.kind} temperature field\n"
        )
        for node_id, temperature_c in temperature_rows:
            stream.write(f"BF,{node_id},TEMP,{_format(temperature_c)}\n")

    temperature_values = [value for _, value in temperature_rows]
    audit = {
        **load_audit,
        "mesh_inp": str(mesh_inp.resolve()),
        "selected_face_nodes": str(selected_face_nodes.resolve()),
        "mesh_config": mesh_config,
        "node_count": len(nodes),
        "selected_force_node_count": len(force_rows),
        "temperature_min_c": min(temperature_values),
        "temperature_max_c": max(temperature_values),
        # The field's own description of itself, and of where it had no
        # support. The postprocessor compares its independent evaluation
        # against this fingerprint, so a drift between the two shows up as a
        # mismatch rather than as a quietly different safety factor.
        "temperature_field": {
            **summary_block(temperature_field, temperature_coverage),
            "node_temperature_file": node_temperature_path.name,
        },
    }
    audit_path = job_dir / "load_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "load_table": str(load_path.resolve()),
        "load_audit": str(audit_path.resolve()),
        "load_table_rows": len(nodal_forces) + len(temperature_rows),
    }


def render_apdl(
    intent: StructuralIntent,
    mesh_inp: Path,
    job_dir: Path,
    load_table: Path,
    mesh_config: dict,
) -> Path:
    rotation = intent.rotation
    temperature = intent.temperature
    material = intent.material
    constraints = intent.constraints
    if None in (rotation, temperature, material, constraints):
        raise ValueError("ready intent is missing a required section")
    # The deck writes CSYS,1 and NROTAT, which are cylindrical about global Z,
    # so the axis it is handed has to be +Z through the origin. That used to be
    # a statement about which parts this chain could analyse at all: a disc
    # modelled in an assembly frame, with its axis through (100, 50, 0), was
    # refused even though its own axis was perfectly parallel to Z.
    #
    # It is now a statement about the caller. The pipeline rotates the model so
    # the axis it chose *becomes* +Z before writing the deck, so by the time
    # this runs the axis is +Z by construction - and a failure here means the
    # normalisation step was skipped, not that the part is unsupported.
    if abs(rotation.axis_direction[0]) > 1e-10 or abs(
        rotation.axis_direction[1]
    ) > 1e-10:
        raise ValueError(
            "the deck is cylindrical about global Z, so it must be written in "
            "the normalised frame. Normalise the model onto the chosen axis "
            "before materialising - do not hand this the part's own axis."
        )
    if rotation.axis_direction[2] < 0:
        raise ValueError(
            "the normalised axis must point toward positive global Z"
        )
    if any(abs(value) > 1e-10 for value in rotation.axis_origin_mm[:2]):
        raise ValueError(
            "the normalised axis must pass through the global Z axis; the "
            "transform has not been applied to the mesh"
        )
    if not constraints.cyclic_symmetry:
        raise ValueError(
            "this sector solve requires cyclic symmetry, and the domain has "
            "not been expressed as a full revolution"
        )
    if not constraints.axial_symmetry_z0:
        raise ValueError(
            "this half-sector solve requires z=0 symmetry, and the domain "
            "does not declare it"
        )

    sector_deg = float(mesh_config["geometry"]["sector_deg"])
    theta_low_deg = float(mesh_config["geometry"]["theta_low_deg"])
    theta_high_deg = theta_low_deg + sector_deg
    bore_radius_mm = float(mesh_config["geometry"]["r_bore_mm"])
    omega = rotation.omega_rad_s
    reference_c = float(temperature.reference_temperature_c)

    material_temps = [point.temperature_c for point in material.points]
    young = [point.young_mpa for point in material.points]
    alpha = [point.alpha_per_c for point in material.points]

    lines = [
        "/BATCH",
        "/FILNAME,structural",
        "/TITLE,Agent-defined rotating thermal blade-load structural case",
        "/PREP7",
        "ET,1,187",
        "MPTEMP",
        "MPTEMP,1," + ",".join(_format(value) for value in material_temps),
        "MPDATA,EX,1,1," + ",".join(_format(value) for value in young),
        "MPDATA,ALPX,1,1," + ",".join(_format(value) for value in alpha),
        f"MP,PRXY,1,{_format(material.poisson_ratio)}",
        f"MP,DENS,1,{_format(material.density_t_mm3)}",
        f"TREF,{_format(reference_c)}",
        f"/INPUT,{mesh_inp.name}",
        "CSYS,1",
        "NROTAT,ALL",
        "! Cyclic symmetry from mesh geometry",
        f"NSEL,S,LOC,Y,{_format(theta_low_deg - 0.01)},"
        f"{_format(theta_low_deg + 0.01)}",
        f"NSEL,A,LOC,Y,{_format(theta_high_deg - 0.01)},"
        f"{_format(theta_high_deg + 0.01)}",
        f"CPCYC,ALL,0.05,1,,{_format(sector_deg)},,0",
        "ALLSEL",
        "! Axial mirror symmetry",
        "NSEL,S,LOC,Z,-1E-3,1E-3",
        "D,ALL,UZ,0",
        "ALLSEL",
    ]
    if constraints.tangential_anchor:
        lines.extend(
            [
                "! Remove unsupported rigid tangential motion",
                "CSYS,1",
                f"NSEL,S,LOC,X,{_format(bore_radius_mm - 0.5)},"
                f"{_format(bore_radius_mm + 0.5)}",
                "NSEL,R,LOC,Z,0,2.0",
                "*GET,NANCH,NODE,0,NUM,MIN",
                "ALLSEL",
                "D,NANCH,UY,0",
            ]
        )
    lines.extend(
        [
            "! Agent-defined nodal temperature and blade-load table",
            f"/INPUT,{load_table.name}",
            "OMEGA,,," + _format(omega),
            "FINISH",
            "/SOLU",
            "ANTYPE,STATIC",
            "EQSLV,SPARSE",
            "SOLVE",
            "FINISH",
            "/POST1",
            "SET,LAST",
            "RSYS,1",
            "*GET,NMAX,NODE,0,NUM,MAX",
            "*DIM,NID,ARRAY,NMAX",
            "*VFILL,NID(1),RAMP,1,1",
            "*DIM,MSK,ARRAY,NMAX",
            "*DIM,XX,ARRAY,NMAX",
            "*DIM,YY,ARRAY,NMAX",
            "*DIM,ZZ,ARRAY,NMAX",
            "*DIM,DISPX,ARRAY,NMAX",
            "*DIM,DISPY,ARRAY,NMAX",
            "*DIM,DISPZ,ARRAY,NMAX",
            "*DIM,SR,ARRAY,NMAX",
            "*DIM,SH,ARRAY,NMAX",
            "*DIM,SA,ARRAY,NMAX",
            "*DIM,SV,ARRAY,NMAX",
            "*VGET,MSK(1),NODE,1,NSEL",
            "CSYS,0",
            "*VGET,XX(1),NODE,1,LOC,X",
            "*VGET,YY(1),NODE,1,LOC,Y",
            "*VGET,ZZ(1),NODE,1,LOC,Z",
            "RSYS,0",
            "*VGET,DISPX(1),NODE,1,U,X",
            "*VGET,DISPY(1),NODE,1,U,Y",
            "*VGET,DISPZ(1),NODE,1,U,Z",
            "RSYS,1",
            "*VGET,SR(1),NODE,1,S,X",
            "*VGET,SH(1),NODE,1,S,Y",
            "*VGET,SA(1),NODE,1,S,Z",
            "*VGET,SV(1),NODE,1,S,EQV",
            "*CFOPEN,nodal_stress_3d,csv",
            "*VWRITE",
            "('nid,x,y,z,ux,uy,uz,s_radial,s_hoop,s_axial,s_eqv,sel')",
            "*VWRITE,NID(1),XX(1),YY(1),ZZ(1),DISPX(1),DISPY(1),DISPZ(1),"
            "SR(1),SH(1),SA(1),SV(1),MSK(1)",
            "(F9.0,',',F12.5,',',F12.5,',',F12.5,',',F12.5,',',"
            "F12.5,',',F12.5,',',F11.3,',',F11.3,',',F11.3,',',"
            "F11.3,',',F4.0)",
            "*CFCLOS",
            "NSORT,U,SUM",
            "*GET,UMAX,SORT,,MAX",
            "NSORT,S,EQV",
            "*GET,VMMAX,SORT,,MAX",
            # What FSUM sums was measured rather than assumed, because the
            # number it produces is easy to read as something it is not (see
            # probes/fsum_semantics). It adds the element equivalent nodal
            # loads from surface and body loads. It does NOT include nodal
            # forces, and it does NOT include reactions. On a disc that means
            # it is dominated by the centrifugal body load - hundreds of kN
            # against a blade load of tens - so it is a scale check, not a
            # load check.
            "ALLSEL",
            "FSUM",
            "*GET,FXSUM,FSUM,0,ITEM,FX",
            "*GET,FYSUM,FSUM,0,ITEM,FY",
            "*GET,FZSUM,FSUM,0,ITEM,FZ",
            # The reactions, summed from the arrays rather than through FSUM,
            # so the answer does not depend on FSUM's semantics at all.
            # Unconstrained nodes contribute their (zero) reaction.
            "*DIM,RFX,ARRAY,NMAX",
            "*DIM,RFY,ARRAY,NMAX",
            "*DIM,RFZ,ARRAY,NMAX",
            "*VGET,RFX(1),NODE,1,RF,FX",
            "*VGET,RFY(1),NODE,1,RF,FY",
            "*VGET,RFZ(1),NODE,1,RF,FZ",
            "*VSCFUN,SXR,SUM,RFX",
            "*VSCFUN,SYR,SUM,RFY",
            "*VSCFUN,SZR,SUM,RFZ",
        ]
    )

    if emission_mode(intent) == "surface_pressure":
        # The force crossing the loaded surface. On the pressure path this is
        # the blade traction plus the centrifugal load of those elements, and
        # it is the only ANSYS-side number that scales with the blade load -
        # so it is what the Python side compares against the target.
        lines += [
            "ESEL,S,ELEM,LOADELM",
            "NSLE,S",
            "FSUM",
            "*GET,LFXSUM,FSUM,0,ITEM,FX",
            "*GET,LFYSUM,FSUM,0,ITEM,FY",
            "*GET,LFZSUM,FSUM,0,ITEM,FZ",
            "ALLSEL",
        ]

    lines += [
        "*CFOPEN,result_summary,txt",
        "*VWRITE,UMAX",
        "('MAX_DISPLACEMENT_MM = ',E16.8)",
        "*VWRITE,VMMAX",
        "('MAX_VON_MISES_MPA = ',E16.8)",
        "*VWRITE,FXSUM,FYSUM,FZSUM",
        "('APPLIED_LOAD_SUM_N = ',3E16.8)",
        "*VWRITE,SXR,SYR,SZR",
        "('REACTION_SUM_N = ',3E16.8)",
        "*CFCLOS",
    ]
    if emission_mode(intent) == "surface_pressure":
        lines += [
            "*CFOPEN,result_summary,txt,,APPEND",
            "*VWRITE,LFXSUM,LFYSUM,LFZSUM",
            "('LOAD_SURFACE_SUM_N = ',3E16.8)",
            "*CFCLOS",
        ]
    lines += [
        "FINISH",
    ]
    solve_inp = job_dir / "solve.inp"
    solve_inp.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return solve_inp
