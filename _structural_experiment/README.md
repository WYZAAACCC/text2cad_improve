# Agent-Driven Structural Experiment

This directory is isolated from the CAD and CFD main pipelines. It holds the
probes, configurations and artifacts for an agent-driven rotating thermal
structural analysis.

The code itself now lives in a proper package, `integrations/structural/`,
because an isolated directory of argparse scripts is exactly why this chain
had no entry point that could run two stages. See "The chain" below.

## Scope

The implemented physics are:

- steady rotation of the complete disc represented by one cyclic sector;
- a temperature-dependent linear elastic material model;
- an Agent-specified nodal temperature field;
- an Agent-selected set of real TopoDS fir-tree slot faces;
- an Agent-specified blade centrifugal load distributed over those faces;
- cyclic symmetry, axial symmetry, and rigid-body tangential restraint;
- nodal displacement and stress output from ANSYS 18.1.

The result is a linear elastic equivalent-load analysis. It is not a
friction/contact nonlinear blade-root analysis, a plastic analysis, or a
fatigue-life calculation.

## Anti-Template Boundary

No golden face list, golden load vector, or geometrical force formula is used
in the production path.

- The face-finding sub-agent (`agents/facefind.py`) calls `list_features`
  first. It discovers the repeated feature and selects a real disconnected
  TopoDS solid. It does not receive a prewritten face list.
- It states the **criterion** its selection is meant to satisfy, and the
  harness checks the submitted faces against *that*. The harness no longer
  has its own idea of what a load face is - the validator that demanded
  "planar, radial normal at least 0.2, no axial component, an even count,
  every face mirrored" has been moved into a criterion the agent writes.
  Load faces, constraint faces, symmetry faces and post-processing sections
  are the same tools with a different criterion.
- The assembly stage (`agents/assembly.py`) copies physical values from the
  parameter file and nothing else. A missing rotation, temperature or
  material is a missing input rather than something filled in from a similar
  part.
- `core/structural_apdl.py` is a neutral materializer. It consumes the intent
  and does not contain a D19 or fir-tree solver template.

The six standalone agent scripts this replaced have been deleted. Their
behaviour lives in `agents/`, their duplicated boilerplate in `runtime/`, and
their tool implementations in `tools/`.

## Hard Inputs

A physically meaningful run requires explicit sources for:

- rotation speed and axis;
- temperature profile or nodal field;
- temperature-dependent elastic, thermal-expansion, density, and yield data;
- blade load per slot, or effective mass and center-of-mass radius;
- confirmation status of the case.

The `ready_for_confirmation` status is deliberately non-executable unless the
operator uses `--allow-unconfirmed-reference`. The override is only a smoke
test switch and marks all result files as
`synthetic_or_unconfirmed_pipeline_validation`.

### Temperature field sources

`TemperatureIntent.model` selects where the field comes from. Five sources:

| model | what it is |
|---|---|
| `isothermal` | one value everywhere |
| `radial_power_law` | bore-to-rim power law; **axisymmetric**, and **clamped** outside the stated radii |
| `node_profile_file` | exact `nid,temperature_c` rows, no interpolation |
| `coordinate_samples` | scattered `x,y,z,value`; the shape a CFD export arrives in |
| `analytic_expression` | a formula over `x, y, z, r, theta_deg, params`, evaluated per node |

All five are evaluated by `temperature_field.py`, which is the *only* place the
field is defined. The deck writer and the postprocessor both call it, so the
temperature used for the thermal strain and the temperature used to look up the
yield stress cannot drift apart. The deck additionally writes
`node_temperature.csv`, and the postprocessor compares its own independent
evaluation against that table, reporting `max_abs_delta_c`. On D27 the
disagreement is 0.

Two things to know about `coordinate_samples`:

- Support is the **convex hull** of the samples. Outside it there is no data,
  and `outside_support_policy` says what happens: `nearest_sample` (flattens to
  the nearest reading), `reference_temperature` (drops the thermal load
  there), or `fail`. Whichever is chosen, the number of nodes that fell
  outside is measured and reported in the metrics and the report.
- `source_spacing_mm` reports the cloud's own median sample spacing. A cloud
  coarser than the mesh cannot carry detail finer than that, and no
  interpolation error estimate would reveal it.

`analytic_expression` does **not** clamp: a formula written to reproduce
`radial_power_law` will extrapolate past the bore unless it clamps too. On D27
that difference shows up at 139 nodes inside the bore, by up to 0.028 C.

### How the blade load is applied

`blade_load.distribution` selects the mechanism:

| direction rule | distribution | mechanism |
|---|---|---|
| `flank_surface_normal` | `area_weighted_uniform_pressure` | `SFE,elem,lkey,PRES,0,p` |
| `flank_surface_normal` | `area_weighted_equal_nodes` | nodal `F`, kept as the control |
| `radial_outward_from_rotation_axis` | `area_weighted_equal_nodes` | nodal `F` |

A uniform pressure cannot express the radial rule - pressure acts along the
face normal and that rule does not - so the combination is refused rather than
approximated.

Everything about `SFE` here was measured, not taken from documentation
(`probes/solid187_face_probe`, `probes/fsum_semantics`, `probes/patch_test`):

- **The local face numbering** is in `element_face_map.SOLID187_FACE_LKEY`, and
  a unit test pins it against the probe output. Changing the table without
  re-running the probe fails CI.
- **A positive `PRES` pushes into the element**, confirmed on all four faces.
  The load direction therefore needs no arithmetic of its own, and the path is
  immune to the normal-orientation mistakes the nodal path had to guard
  against.
- **A uniform pressure is a consistent load**: the constant-stress patch test
  recovers `sigma_xx = -p` to solver precision, while the equal-force-per-node
  scheme misses it by up to 183% on the same mesh. That is the whole reason
  for the change.
- **`FSUM` sums element surface and body loads only.** It does *not* include
  nodal forces and does *not* include reactions. On D27 the reported
  `MODEL_FSUM_N` of ~480 kN was the centrifugal body load alone; the 10 kN
  blade load was applied as nodal forces and never appeared in it.

**The pressure is the target divided by the magnitude of the resultant
direction, not by the sum of the areas.** A fir-tree slot's faces do not all
point the same way, so the resultant is `|sum of area x normal|`, which is
smaller than `sum of area` - on D27 by 21%. Dividing by the area alone gives a
pressure that looks perfectly reasonable and under-applies the load. The audit
carries both numbers (`resultant_direction_mm2`, `area_sum_mm2`) so the
difference is visible.

Two consequences worth stating plainly:

- On the pressure path `applied_resultant_n` is **an identity by
  construction** - the pressure is defined from the target, so integrating it
  returns the target. `resultant_relative_error` therefore has no diagnostic
  power there, and the audit carries a `limits` entry saying so. The evidence
  is in the same `emission` block: `mapped_area_total_mm2` against
  `occ_area_total_mm2` (how much of each selected CAD face the mesh covers),
  `resultant_direction_mm2` against `area_sum_mm2` (how much the faces' normals
  cancel), `normal_agreement_min`, and `ambiguous_element_face_count`.
- **ANSYS stores results at corner nodes only for SOLID187.** Mid-side stress
  is interpolated in POST1 and is not retrievable, so every reported stress is
  a corner-node quantity. A load applied to a quadratic face lands on the
  mid-side nodes - exactly where stress cannot be read. Every metrics file
  carries a `stress_sampling` block saying this.

`area_accounting.mapped_area_fraction` is not expected to be 1. When the
analysis domain clips a selected face - D27's half-sector cuts every fir-tree
flank exactly in half - the fraction is 0.5, and that is correct. The previous
nodal scheme divided the target force by the **unclipped** CAD area, which is
an error D27 hid because every face was clipped identically.

## The chain

The stages run as one pipeline. Everything below is invoked by a single
command:

```powershell
.\.conda\python.exe -m seekflow_structural.cli run `
  --bundle _cfd_experiment\input\lineage\D27 `
  --params _structural_experiment\input\d27_synthetic_smoke_case.json `
  --job d27 --allow-unconfirmed --memory-mb 12000
```

`run`, `resume`, `summary` and `schema` are the whole CLI. The stages are:

```
preflight -> frame -> domain -> assembly -> mesh
          -> materialize -> solve -> postprocess -> verify -> complete
```

| stage | what it decides, and on what evidence |
|---|---|
| `frame` | measures the part: radii, axial extent, the axis, and symmetry-plane candidates with a matched-area score each |
| `domain` | which piece to analyse — periodicity probe, volume ratio, cut-plane coherence |
| `assembly` | the physics, from the parameter file, checked against itself; and the load faces, found by a sub-agent that states a criterion the harness then checks |
| `mesh` | where resolution goes — measured element count, quality, and the size achieved per region |
| `materialize` `solve` `postprocess` | deterministic: the deck, ANSYS, and the results |
| `verify` | which reported numbers may be quoted, from pairs of independent measurements |

### One case, and no restated numbers

Every stage takes one case object and returns it. No stage is handed a scalar
describing what an earlier stage measured — a stage that needs the load radius
reads `load_surface.load_radius_mm`, and there is no argument that could carry
a stale copy of it.

That is not tidiness. Two silent failures were caused by restating a number:
the domain agent chose an 18 degree sector while the face selector still
worked to a hard-coded 3-9 degrees, and the mesh agent was told the load sat
at radius 288 when the faces it was refining for sat at 212.67. In both cases
an upstream decision had changed and a downstream *input* had not.

### What the run leaves behind

`jobs/<job_id>/` holds `case.json` (rewritten at every stage boundary with its
digest), `events.jsonl` (append-only, hash-chained), `calls/` (one artifact
per tool call), `agent/` (one per agent run, with its whole transcript),
`state.json`, `record.json` and `manifest.json` (a SHA-256 per artifact).

`resume` re-reads the arguments to confirm the job is being continued against
the same model — the bundle's STEP and XBF are both hashed — and then proceeds
from the stored case. A changed upstream decision invalidates exactly the
downstream stages that consumed it.

### Bootstrap path

`--seed-dir` builds the case from artifacts an earlier run left behind instead
of from the agents. It exists to prove the deterministic half on a real result
before any agent was rebuilt, and it is removed when the last one lands.

## Current D19 Verification

The synthetic 10 kN per-slot smoke test completed with:

- 28,239 mesh nodes and 2,024 nodes on the Agent-selected slot faces;
- 4,588 nodes with defined POST1 stress results;
- maximum displacement 2.53882527 mm;
- maximum von Mises stress 1119.882 MPa;
- maximum stress on the selected load surface 107.083 MPa;
- applied resultant force magnitude 10000.000000000113 N;
- resultant relative error 1.13e-14;
- twist moment about the rotation axis 1.21e-12 N*mm.

These values are a pipeline and numerical-consistency check only. The blade
load and confirmation status are explicitly synthetic.

## Independent Regression Check

The Agent-defined solver was isolated with a near-zero blade load and compared
against the pre-existing non-Agent APDL baseline on the same mesh:

- new neutral pipeline maximum von Mises: 1124.595 MPa;
- old baseline maximum von Mises: 1123.468 MPa;
- relative difference: 0.1003%.

With the explicitly synthetic 10 kN blade load enabled, the new maximum rises
to 1151.076 MPa and the selected slot surface reaches 142.055 MPa. This confirms
that the implementation difference is explained by the added load rather than a
change in rotation, temperature, material, or boundary constraint behavior.

## Final-Body Selection and CFD Boundary Transfer

The initial D19 selection used faces from the `n_pattern_cutters` tool result.
Those faces extend to `z=+/-40 mm`, while the final disc is `z=+/-38 mm`, so
they cannot be treated as final CFD boundary faces. The selector was upgraded
to inspect `n_final_cut`, the single final body with 3,910 faces.

The Agent now uses a two-stage process:

1. generic feature/solid discovery and geometric candidate queries;
2. a constrained final decision over the returned candidate indices.

Deterministic validation requires planar faces, zero axial normal, one common
radial-normal sign, and a symmetric partner for every selected face. The final
D19 selection is:

```text
17, 25, 33, 41, 53, 61, 69, 77
```

It forms four symmetric working-flank pairs and excludes the opposing
non-working flanks.

`export_selected_faces.py` exports these exact final-body faces as BRep and
records their current revision hashes and geometric fingerprints. The real
Fluent worker now consumes selected native BRep faces through a strict
unique-match transfer:

- 3,910 exterior fluid-boundary faces;
- eight selected faces mapped to eight distinct solver boundaries;
- 3,902 remaining faces mapped to `remaining_disc_wall`;
- zero uncovered faces;
- proof class `exact_brep_transfer`, not native OCAF history.

The current limitation is explicit: these are index-only faces for the current
revision. Cross-revision persistent role mapping remains pending.

## Evolution Role Index

The `face_evolution/` package builds a revision-specific SQLite index from
canonical final faces, persistent face roles, and evolution-relation metadata.
It keeps history separate from current topology:

- 3,910 canonical final faces;
- 19,473 indexed `n_final_cut` face-role records;
- 3,897 face-level roles resolved to final faces;
- 15,576 generated role records identified as edge/vertex history, not faces;
- 23,620 relation metadata records.

The Agent uses paged search and trace tools instead of receiving the full role
set. It submits a canonical face and resolved role ID for each selected working
face. Deterministic validation verifies identity and symmetric-pair structure.

For the current D19 revision, all eight selected roles were re-resolved in one
live OCAF session and matched their final faces with zero area and centroid
error. Their exported BReps were accepted as eight distinct Fluent boundaries,
with 3,902 remaining faces assigned to `remaining_disc_wall` and zero uncovered
faces. The resulting identity status is `persistent_role_resolved`; only
cross-revision stability remains to be demonstrated.

The final gaps were subsequently closed:

- all 13 quarantined carry roles were recovered from the unchanged
  `n_disc_revolve` target faces;
- the complete `n_pattern_cutters` source index contains 4,080 real faces and
  4,012 relation records;
- a real two-revision lineage was generated with a 2% cutter-width perturbation;
- the same eight role IDs resolved in both revisions with at most 1.65% area
  change, 0.130 mm centroid movement, and normal dot 0.99995 or higher.

## Verification

```powershell
.\.conda\python.exe -m pytest _structural_experiment\tests -q
```
