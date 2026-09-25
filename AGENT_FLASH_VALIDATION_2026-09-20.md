# Agent Flash Validation - 2026-09-20

## Model policy

All structural simulation agents (domain, setup, facefind, mesh, feedback,
revise) and the CFD expert-review utility now default to:

`deepseek-v4-flash`

The target scope contains no remaining `deepseek-v4-pro` default.

## Face selection benchmark

Frozen D27 reference: exact 24-face working-flank set.

| Batch | Runs | Exact | Wrong accepted | Not submitted | Median calls |
|---|---:|---:|---:|---:|---:|
| batch 3 | 13 | 13 | 0 | 0 | 6 |
| batch 4 | 12 | 12 | 0 | 0 | 6 |
| **combined** | **25** | **25** | **0** | **0** | **6** |

Combined submission rate: 100% (25/25). Combined exact accuracy: 100%.
Calls ranged from 6 to 8.

OOD check on D19 (different geometry, 6-degree sector, exact 8-face set):

| Runs | Exact | Wrong accepted | Not submitted | Median calls |
|---:|---:|---:|---:|---:|
| 3 | 3 | 0 | 0 | 14 |

Combined D27 + D19 validation: 28/28 exact, 0 wrong accepted.

Artifacts:

- `_structural_experiment/output/sweep_gate_flash_final/`
- `_structural_experiment/output/sweep_gate_flash_final_summary.json`
- `_structural_experiment/output/sweep_facefind_d19_flash/`
- `_structural_experiment/output/sweep_facefind_d19_flash_summary.json`

## Feedback agent replay

Real stored jobs, Flash model, revision document supplied explicitly.

| Job | Calls | Accepted | Finding outcome |
|---|---:|---:|---|
| run3 rev1 | 14 | yes | no-change diagnosis |
| run4 rev1 | 25 | yes | executable document parameter |
| run5 rev1 | 17 | yes | executable document parameter |
| run6 rev1 | 15 | yes | two diagnoses, no geometry change |

All evidence was re-read successfully. Four of four runs submitted.

Artifacts:

- `_structural_experiment/output/feedback_flash_replay/`

## Revise agent replay

| Job | Result | Document edits |
|---|---|---|
| run4 rev1 | applied F1 | exact `feat_holes_poly.points[4].x_mm` patch |
| run5 rev1 | applied F1 | exact `feat_holes_poly.points[12].y_mm` patch |
| run3 rev1 | skipped F1 | none; attempted unauthorized edit blocked |
| run6 rev1 | skipped F1/F2 | none; attempted unauthorized edit blocked |

The no-change failures were detected before writing: `set_parameter` now
requires a structured change on the named finding. Submission also rejects any
change recorded for a finding not listed as applied.

Artifacts:

- `_structural_experiment/output/revise_flash_replay_guard/`

## Real paired-change experiment

A real ANSYS experiment was recovered after the live loop exposed two
harness defects. Both defects were fixed and the paired revision was rerun.

- Change: bore profile pair `points[0].x_mm` and `points[11].x_mm`, 60 → 66 mm.
- Before solve: 1709.359 MPa maximum von Mises.
- After solve: 1688.457 MPa maximum von Mises.
- Relative move: −1.2228%.
- Measured re-mesh noise floor: 3.8119%.
- Verdict: `unmoved`, because the measured move is below the measured noise.
- Side effects: none reported.
- Master templates: unchanged.

Artifacts:

- `_structural_experiment/output/structural_pair_experiment_summary.json`
- `flash_loop_correct24_v3/jobs/jobs/D27CF3-rev-000001`
- `flash_loop_pair_rev2/jobs/jobs/D27PAIR-rev-000001`

This is a conservative success: the system did not falsely confirm a small
change as a design improvement.

## Completed clean v4 run

The clean two-revision run using all fixes in one process completed:

- root: `F:\text_to_cad_improve\auto_detection_process\_loop_test\flash_loop_correct24_v4`
- result: `...\flash_loop_correct24_v4\loop_result.json`
- rev1 maximum von Mises: 1709.359 MPa
- rev2 maximum von Mises: 1691.862 MPa
- measured relative move: −1.0236%
- measured re-mesh noise floor: 3.81%
- verdict: `unmoved`
- rev1 paired vertex edit: points[0]/points[11] `60 -> 63 mm`
- rev2 diagnostic: one applied F1 and one skipped F2

The system again declined to call a change below its measured noise a confirmed
improvement.

## Regression status

- `integrations/structural`: `556 passed`
- Changed files: `ruff check` passed
- Master templates: unchanged in all revise replays
- Full-tree ruff still has older unrelated lint debt outside the changed files

## Main harness changes added during validation

- Measured outer-radial load band and strong normal family for
  `flank_surface_normal`; exact signed query bounds are returned to the agent.
- Repeated tool calls force the next turn into the terminal decision schema.
- Feedback evidence is re-read and must re-match at submission.
- One revision may contain at most one executable design change.
- Stored feedback is revalidated against the revision document before reuse.
- Revise requires exact finding/parameter/magnitude attribution.
- No-change diagnoses cannot authorize document or script writes.
- Mirrored meridian vertices must move together; one-sided edits are refused.
- The tangential anchor is selected inside the solved sector, not on a CPCYC slave boundary.
- Opposite knowledge directions are stored as separate rules.
- Non-global-Z axes are normalised through profile, Gmsh, face mapping, APDL and postprocess; the synthetic X-axis cylinder probe passed.
- The loop now compares final STEP profile facts between revisions before scoring a change.
- Profile-vertex edits must change their case-frame r/z position, not only their scalar value.
- Aggregate evidence sources (`agg:<quantity>:<reducer>:<bounds>`) are replayable from the solved field.
- `paper_metrics.py` aggregates selection, feedback, revise and loop outcomes into one report.
- A profile-vertex edit must change its case-frame r/z position, not only its scalar value.

## Multi-family follow-up

Added 23 Flash runs across D15-D19, D23-D27 and D29. After the radial-load direction gate was tightened, the new batch was 23/23 exact with zero wrong accepted. Combined with existing D27 25/25 and D19 3/3, the frozen evidence is 51/51 exact, 0 wrong accepted, Wilson 95 percent exact accuracy [0.930, 1.0].

## Cross-family loop and revise follow-up

D19 real solves: bore 60, 63, 66 mm gave peaks 1149.708, 1150.936 and 1152.771 MPa. Both bore-opening predictions were refuted; load-surface stress rose about 5-6%. The clean cross-family revise replay now writes the mirrored bore pair 63 -> 66 mm exactly and leaves the master untouched.

Artifacts: d19_cross_family_loop_reconstructed.json, paper_metrics_v10.json, paper_tables_v5.md.
