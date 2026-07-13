"""SketchProfile dialect — 2D sketch geometry with extrude/cut.

This is a GRAMMAR for arbitrary 2D profiles, NOT a part template.
It supports lines, arcs, circles, polylines, slots — the LLM composes
these to describe non-rectangular shapes like L-brackets, flanges with
complex contours, and profiled plates.
"""

from __future__ import annotations

from typing import Any

from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
from seekflow_engineering_tools.generative_cad.ir.canonical import (
    CanonicalComponent,
    CanonicalNode,
)
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.validation.reports import (
    ValidationIssue,
    ValidationReport,
)

from seekflow_engineering_tools.generative_cad.dialects.sketch_profile.handlers import (
    handle_add_arc_segment,
    handle_add_circle,
    handle_add_line_segment,
    handle_add_polyline,
    handle_close_profile,
    handle_create_2d_sketch,
    handle_cut_profile,
    handle_extrude_profile,
    handle_fillet_sketch,
    handle_fillet_sketch_v2,
    handle_mirror_profile,
    handle_revolve_profile,
)
from seekflow_engineering_tools.generative_cad.dialects.sketch_profile.params import (
    AddArcSegmentParams,
    AddCircleParams,
    AddLineSegmentParams,
    AddPolylineParams,
    AddSlotParams,
    CloseProfileParams,
    Create2dSketchParams,
    CutProfileParams,
    ExtrudeProfileParams,
    FilletSketchParams,
    FilletSketchV2Params,
    LinearPatternParams,
    MirrorFeatureParams,
    RevolveProfileParams,
)


class SketchProfileDialect:
    dialect_id = "sketch_profile"
    version = "0.2.0"
    phase_order = (
        "sketch",
        "profile",
        "feature",
        "pattern",
        "edge_treatment",
        "cleanup",
    )

    def __init__(self):
        self._op_version_map: dict[str, str] = {
            "create_2d_sketch": "1.0.0",
            "add_line_segment": "1.0.0",
            "add_arc_segment": "1.0.0",
            "add_circle": "1.0.0",
            "add_polyline": "1.0.0",
            "add_slot": "1.0.0",
            "close_profile": "1.0.0",
            "fillet_sketch": "2.0.0",  # default upgraded to semantic V2
            "fillet_sketch@1": "1.0.0",  # deprecated legacy
            "mirror_profile": "1.0.0",
            "extrude_profile": "1.0.0",
            "revolve_profile": "1.0.0",
            "cut_profile": "1.0.0",
        }

        self._specs: dict[tuple[str, str], OperationSpec] = {
            ("create_2d_sketch", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="create_2d_sketch", op_version="1.0.0",
                phase="sketch", input_types=[], output_types=["sketch"],
                params_model=Create2dSketchParams, effects=["creates_frame"],
                handler=handle_create_2d_sketch,
                summary="Create a 2D sketch plane for subsequent profile operations.",
                usage_notes=["Must be the first node in a sketch_profile component."],
            ),
            ("add_line_segment", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="add_line_segment", op_version="1.0.0",
                phase="profile", input_types=["sketch"], output_types=["profile"],
                params_model=AddLineSegmentParams, effects=["modifies_solid"],
                handler=handle_add_line_segment,
                summary="Add a straight line segment to the current sketch profile.",
            ),
            ("add_arc_segment", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="add_arc_segment", op_version="1.0.0",
                phase="profile", input_types=["profile"], output_types=["profile"],
                params_model=AddArcSegmentParams, effects=["modifies_solid"],
                handler=handle_add_arc_segment,
                summary="Add a circular arc segment to the sketch profile.",
            ),
            ("add_circle", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="add_circle", op_version="1.0.0",
                phase="profile", input_types=["profile"], output_types=["profile"],
                params_model=AddCircleParams, effects=["cuts_material"],
                handler=handle_add_circle,
                summary="Add a circular hole/sketch element at a specified center and radius.",
            ),
            ("add_polyline", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="add_polyline", op_version="1.0.0",
                phase="profile", input_types=["sketch"], output_types=["profile"],
                params_model=AddPolylineParams, effects=["modifies_solid"],
                handler=handle_add_polyline,
                summary="Add a connected polyline (multiple line segments) to the sketch.",
            ),
            ("add_slot", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="add_slot", op_version="1.0.0",
                phase="profile", input_types=["profile"], output_types=["profile"],
                params_model=AddSlotParams, effects=["cuts_material"],
                handler=lambda ctx, nid, p: {"profile": f"profile:{nid}"},
                summary="Add a slot (racetrack shape) to the sketch profile. Currently a placeholder.",
            ),
            ("close_profile", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="close_profile", op_version="1.0.0",
                phase="profile", input_types=["profile"], output_types=["profile"],
                params_model=CloseProfileParams, effects=["modifies_solid"],
                handler=handle_close_profile,
                summary="Close the current sketch profile (connect last point back to first).",
            ),
            ("extrude_profile", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="extrude_profile", op_version="1.0.0",
                phase="feature", input_types=["profile"], output_types=["solid"],
                params_model=ExtrudeProfileParams, effects=["creates_solid"],
                handler=handle_extrude_profile,
                summary="Extrude the closed profile to create a 3D solid body.",
            ),
            ("cut_profile", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="cut_profile", op_version="1.0.0",
                phase="feature", input_types=["solid", "profile"], output_types=["solid"],
                params_model=CutProfileParams, effects=["cuts_material"],
                handler=handle_cut_profile,
                summary="Cut material from an existing solid using the profile.",
            ),
            ("fillet_sketch", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="fillet_sketch", op_version="1.0.0",
                phase="profile", input_types=["profile"], output_types=["profile"],
                params_model=FilletSketchParams, effects=["modifies_solid"],
                handler=handle_fillet_sketch,
                summary="DEPRECATED. Apply fillet via vertex indices (unstable). Use fillet_sketch@2.0.0 instead.",
            ),
            ("fillet_sketch", "2.0.0"): OperationSpec(
                dialect="sketch_profile", op="fillet_sketch", op_version="2.0.0",
                phase="edge_treatment", input_types=["profile"], output_types=["profile"],
                params_model=FilletSketchV2Params, effects=["modifies_solid"],
                handler=handle_fillet_sketch_v2,
                summary="Semantic fillet via corner_id + between_segments (stable). Each target has independent radius, feasibility pre-check, and fail-closed enforcement.",
                usage_notes=[
                    "Use between_segments (edge IDs from ProfileGraph) to identify corners, NOT at_vertex_index.",
                    "Each target can have a different radius — do NOT apply a single radius to all corners.",
                    "Feasibility pre-check validates edge length budget before OCC call.",
                    "required=True corners that fail will abort the build (fail-closed).",
                ],
                common_mistakes=[
                    "Using at_vertex_index instead of between_segments.",
                    "Applying same radius to all corners regardless of edge length.",
                    "Assuming OCC vertex ordering is stable across rebuilds.",
                ],
            ),
            ("mirror_profile", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="mirror_profile", op_version="1.0.0",
                phase="profile", input_types=["profile"], output_types=["profile"],
                params_model=MirrorFeatureParams, effects=["modifies_solid"],
                handler=handle_mirror_profile,
                summary="Mirror the sketch profile and union with original (e.g. half fir-tree slot → full).",
            ),
            ("revolve_profile", "1.0.0"): OperationSpec(
                dialect="sketch_profile", op="revolve_profile", op_version="1.0.0",
                phase="feature", input_types=["profile"], output_types=["solid"],
                params_model=RevolveProfileParams, effects=["creates_solid"],
                handler=handle_revolve_profile,
                summary="Revolve a closed 2D profile around Z axis — for axisymmetric parts with varying thickness (turbine discs, wheels, pulleys).",
                usage_notes=[
                    "Must follow create_2d_sketch(plane=XZ) → add_polyline/line/arc → close_profile.",
                    "The polyline defines an ordered R-Z polygon on the XZ plane: X=R(radius), Y=Z(axial).",
                    "Points are NOT Z-sorted — the LLM controls exact polygon vertex order.",
                    "Unlike axisymmetric.revolve_profile which uses profile_stations sorted by Z, "
                    "sketch_profile.revolve_profile preserves the original point order for arbitrary "
                    "cross-sections including hub(厚)→web(薄)→rim(厚) varying-thickness profiles.",
                    "For complex parts (turbine discs, blisks): use sketch_profile for the disk body, "
                    "sketch_profile for slot cutter sketch→extrude, then composition dialect for "
                    "circular_pattern(rotate_copies=True) + boolean_cut.",
                ],
                common_mistakes=[
                    "Using axisymmetric.revolve_profile instead of sketch_profile.revolve_profile "
                    "for thickness-by-radius profiles — axisymmetric only supports z(r) single-valued profiles.",
                    "Forgetting to call close_profile before revolve_profile — the profile must be closed.",
                    "Creating the sketch on XY plane instead of XZ — R-Z profiles must be on XZ plane.",
                    "Drawing the slot cutter sketch at rim radius instead of origin — "
                    "composition.circular_pattern handles the radial positioning.",
                ],
                llm_param_hints={
                    "angle_deg": "Always 360.0 for full axisymmetric revolution.",
                },
            ),
        }

    # ── Protocol methods ──────────────────────────────────────────────────

    def manifest(self) -> dict[str, Any]:
        return {
            "dialect_id": self.dialect_id,
            "version": self.version,
            "summary": "2D sketch-based profile grammar for non-rectangular extruded/cut geometry.",
            "phase_order": list(self.phase_order),
            "op_count": len(self._specs),
        }

    def contract(self) -> dict[str, Any]:
        return {
            "dialect_id": self.dialect_id,
            "version": self.version,
            "phase_order": list(self.phase_order),
            "allowed_ops": {
                op_name: {
                    "phase": spec.phase,
                    "op_version": spec.op_version,
                    "input_types": spec.input_types,
                    "output_types": spec.output_types,
                    "description": spec.summary or "",
                }
                for (op_name, _), spec in self._specs.items()
            },
        }

    def op_specs(self) -> dict[tuple[str, str], OperationSpec]:
        return dict(self._specs)

    def default_op_version(self, op: str) -> str:
        return self._op_version_map.get(op, "1.0.0")

    def get_op_spec(self, op: str, op_version: str | None = None) -> OperationSpec:
        version = op_version or self.default_op_version(op)
        key = (op, version)
        if key not in self._specs:
            raise KeyError(f"Unknown op/version: {op} v{version}")
        return self._specs[key]

    def validate_component(
        self, component: CanonicalComponent, nodes: list[CanonicalNode]
    ) -> ValidationReport:
        issues = []
        has_sketch = any(n.op == "create_2d_sketch" for n in nodes)
        if not has_sketch:
            issues.append(ValidationIssue(
                stage="dialect_semantics", code="sp_no_sketch",
                message="SketchProfile component must have a create_2d_sketch node",
                severity="error",
            ))
        has_extrude = any(n.op in ("extrude_profile", "cut_profile", "revolve_profile") for n in nodes)
        if not has_extrude:
            issues.append(ValidationIssue(
                stage="dialect_semantics", code="sp_no_extrude",
                message="SketchProfile component must have at least one extrude_profile, cut_profile, or revolve_profile",
                severity="error",
            ))
        return ValidationReport(ok=len(issues) == 0, stage="dialect_semantics", issues=issues)

    def preflight_component(
        self, component: CanonicalComponent, nodes: list[CanonicalNode]
    ) -> ValidationReport:
        issues = []
        for node in nodes:
            if node.op == "extrude_profile":
                depth = node.params.get("depth_mm", 0)
                if depth <= 0:
                    issues.append(ValidationIssue(
                        stage="geometry_preflight", code="sp_depth_non_positive",
                        message=f"extrude_profile depth_mm must be > 0, got {depth}",
                        severity="error", path=f"/nodes/{node.id}/params/depth_mm",
                    ))
            if node.op == "add_polyline":
                pts = node.params.get("points", [])
                if len(pts) < 2:
                    issues.append(ValidationIssue(
                        stage="geometry_preflight", code="sp_polyline_too_short",
                        message=f"add_polyline requires at least 2 points, got {len(pts)}",
                        severity="error", path=f"/nodes/{node.id}/params/points",
                    ))
        return ValidationReport(ok=len(issues) == 0, stage="geometry_preflight", issues=issues)

    def run_component(
        self,
        component: CanonicalComponent,
        nodes: list[CanonicalNode],
        ctx: RuntimeContext,
    ) -> dict[str, str]:
        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation

        # Kahn topological sort (same as axisymmetric — respects input→output edges)
        phase_rank = {p: i for i, p in enumerate(self.phase_order)}
        node_map = {n.id: n for n in nodes}
        in_degree = {n.id: sum(1 for i in n.inputs if i.producer_node and i.producer_node in node_map) for n in nodes}
        sorted_nodes = []; queue = [n for n in nodes if in_degree[n.id] == 0]
        while queue:
            queue.sort(key=lambda n: (phase_rank.get(n.phase, 999), n.id))
            n = queue.pop(0); sorted_nodes.append(n)
            for other in nodes:
                for inp in other.inputs:
                    if inp.producer_node == n.id:
                        in_degree[other.id] -= 1
                        if in_degree[other.id] == 0 and other not in sorted_nodes and other not in queue:
                            queue.append(other)
        if len(sorted_nodes) != len(nodes):
            unscheduled = [n.id for n in nodes if n not in sorted_nodes]
            raise RuntimeError(f"sketch_profile: unscheduled nodes: {unscheduled}")

        outputs: dict[str, str] = {}
        for node in sorted_nodes:
            op_spec = self.get_op_spec(node.op, node.op_version)
            try:
                executed = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
                for name, hid in executed.outputs.items():
                    outputs[name] = hid
            except Exception:
                if node.degradation_policy == "may_skip_with_warning":
                    continue
                raise

        # Bind root node outputs
        root = next((n for n in sorted_nodes if n.id == component.root_node), sorted_nodes[-1] if sorted_nodes else None)
        if root:
            for o in root.outputs:
                try:
                    ctx.bind_component_output(component.id, o.name, ctx.resolve_node_output(root.id, o.name))
                except KeyError:
                    pass

        return outputs


SKETCH_PROFILE_DIALECT = SketchProfileDialect()
