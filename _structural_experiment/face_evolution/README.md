# Face Evolution Index

This module turns OCAF face roles and relation metadata into a paged SQLite
index. It keeps final faces and history roles separate so an agent never has to
read all role labels in one prompt.

## Data Layers

- `canonical_faces`: current final TopoDS faces with geometry facts.
- `face_roles`: persistent `namespace|role_key` records, relation kind,
  resolved current face, and geometry facts.
- `evolution_relations`: relation metadata parsed from relation keys.

The index is revision-specific. `canonical_face_id` is current-revision
identity. `role_id` is the candidate persistent identity.

## Build

```powershell
.\.conda\python.exe _structural_experiment\face_evolution\build_canonical_faces.py `
  "_cfd_experiment\input\lineage\D19" `
  "_structural_experiment\work\D19_face_evolution.sqlite"

.\.conda\python.exe _structural_experiment\face_evolution\build_face_evolution_index.py `
  "_cfd_experiment\input\lineage\D19" `
  "_structural_experiment\work\D19_face_evolution.sqlite" `
  --namespace feature:n_final_cut `
  --final-feature n_final_cut `
  --workers 12 --range-size 500
```

The range worker is isolated. A crash splits the range and retries. A single
role that still crashes is quarantined and never silently mapped through its
temporary face index.

## Search

```powershell
.\.conda\python.exe _structural_experiment\face_evolution\face_search.py `
  "_structural_experiment\work\D19_face_evolution.sqlite" scopes

.\.conda\python.exe _structural_experiment\face_evolution\face_search.py `
  "_structural_experiment\work\D19_face_evolution.sqlite" faces `
  --surface-type plane --radial-min 220 --radial-max 250 `
  --theta-min 3 --theta-max 9 --limit 20
```

Search returns `total`, `returned`, `offset`, `truncated`, compact facts, and
facets. Full `face_role` sets are never returned in one call.

## D19 Result

- final canonical faces: 3,910
- inserted `n_final_cut` face roles: 19,473
- quarantined single-role crashes: 13
- face roles that resolve to final faces: 3,897
- generated role records that are actually edge/vertex history: 15,576
- relation metadata: 23,620

The generated edge/vertex records are retained as history but are not offered
as final face candidates. Final face selection uses only resolved face-level
roles.

## Agent

```powershell
.\.conda\python.exe _structural_experiment\face_evolution\agent_evolution_face_intent.py `
  "_structural_experiment\work\D19_face_evolution.sqlite" `
  "_structural_experiment\output\D19_evolution_face_selection.json" `
  --api-key-file "E:\auto_detection_process\_archive\apikey.txt"
```

The agent searches, requests candidate faces with their resolved roles, then
submits symmetry-pair indices. The deterministic validator checks that the
selected role resolves to the submitted face, rejects mixed working sides, and
requires symmetric pairs.

Current-revision D19 selection:

```text
faces:  17, 25, 33, 41, 53, 61, 69, 77
roles:  tool_face_134/mod/0, tool_face_73/mod/0,
        tool_face_126/mod/0, tool_face_82/mod/0,
        tool_face_118/mod/0, tool_face_90/mod/0,
        tool_face_110/mod/0, tool_face_98/mod/0
```

This is not yet a cross-revision proof. The next step is to rebuild the same
index for a perturbed revision and resolve the same role IDs.

The role selection can also be exported and transferred to the real Fluent
domain without returning to temporary face indices:

```powershell
.\.conda\python.exe _structural_experiment\face_evolution\verify_role_selection.py `
  "_cfd_experiment\input\lineage\D19" `
  "_structural_experiment\work\D19_face_evolution_v1.sqlite" `
  "_structural_experiment\output\D19_evolution_face_selection.json" `
  "_structural_experiment\output\D19_role_selection_verification.json"

.\.conda\python.exe _structural_experiment\face_evolution\export_role_selection_faces.py `
  "_cfd_experiment\input\lineage\D19" `
  "_structural_experiment\output\D19_evolution_face_selection.json" `
  "_structural_experiment\work\D19_persistent_role_brep"
```

The live verifier opens one OCAF session, re-resolves every role, and checks
`IsSame` plus zero area/centroid error against the selected final face. The
exported BRep bindings are then accepted by the Fluent worker as normal
`selection` boundaries.

Current-revision integration result:

- 8 selected role IDs verified live;
- 8 distinct Fluent boundary entities;
- 3,902 remaining faces assigned to `remaining_disc_wall`;
- 0 uncovered exterior faces;
- transfer proof `exact_brep_transfer`;
- persistent identity status `persistent_role_resolved`.

## Recovered Carry Roles

The first full build quarantined 13 `target_face_i/carry` roles because their
TNaming primitive attributes caused an OCC access violation. Recovery uses the
unchanged previous-body face:

1. load `n_disc_revolve`, whose 16 faces are the final-cut target faces;
2. load final `n_final_cut` faces;
3. match the same carried face by `IsSame`, then by strict area/centroid;
4. insert the recovered role with method `target_carry_shape_match`.

All 13 roles were recovered and all 3,910 final faces now have a resolved
face-level role.

## Complete Source-Face Index

`n_pattern_cutters` face-role results contain many malformed primitive edge and
vertex records, so they are not suitable as the source index. The source index
instead enumerates the real result shape:

- 60 solids;
- 4,080 actual faces used as `tool_face_N` inputs by `n_final_cut`;
- 4,012 pattern relation metadata records.

`trace-role` follows `tool_face_N/mod/0` to the actual pattern source face N.
For example, `tool_face_134/mod/0` resolves to final face 17 and source face
134, whose area and normal match the selected working flank before the final
cut operation.

## Cross-Revision Verification

A two-revision lineage was rebuilt with the real `run_lineage_revisions`
pipeline. Revision 2 changes the fir-tree cutter cross-section by a 2% width
perturbation while preserving topology.

Location:

```text
_structural_experiment/work/D19_cross_revision/lineage/D19_cross_revision/revisions/rev-000001
_structural_experiment/work/D19_cross_revision/lineage/D19_cross_revision/revisions/rev-000002
```

The same eight persistent role IDs were resolved in both revisions. All eight
remained planar working flanks:

- area change: 0.795%-1.648%;
- centroid movement: at most 0.130 mm;
- normal absolute dot: at least 0.99995;
- accepted roles: 8/8.

Evidence:

- `_structural_experiment/output/D19_carry_role_recovery.json`
- `_structural_experiment/output/D19_cross_revision_verification.json`
- `_structural_experiment/work/D19_cross_revision/revision_build_summary.json`
