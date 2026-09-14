"""Do the two radial bands differ in provenance?

The question this answers: is there a discrete, nameable property - which
feature and which face_role a face descends from - that separates the six
faces the verified reference used from the 472 the agent also selected?
Geometry could not separate them. Provenance might.
"""
import sys, pathlib
from collections import Counter
sys.path.insert(0, "integrations/structural/src")
from seekflow_structural.core import pattern_solids as ps
from seekflow_structural.tools import geometry

bundle = pathlib.Path("_cfd_experiment/input/lineage/D27")
session = geometry.open_bundle(bundle)
try:
    # What role entries exist at all, and under which namespaces?
    entries = [
        e for e in session.label_index.entries()
        if e.retired_revision is None and e.key.object_kind == "face_role"
    ]
    print(f"face_role entries in D27: {len(entries)}")
    print("namespaces:", dict(Counter(e.key.namespace for e in entries)))
    print("sample keys:", [f"{e.key.namespace}|{e.key.object_id}" for e in entries[:8]])
    print()

    rows = geometry.face_rows(session, "n_final_cut", 0)
    faces = geometry.faces_of(session, "n_final_cut", 0)

    f = {n: None for n in geometry.CYLINDRICAL_FILTERS}
    f["normal_radial"] = (-1.0, -0.5)
    sel = geometry.query(rows, f, surface_type="plane")
    inner = [i for i in sel if 200 <= rows[i]["centroid_cyl_mm_deg"][0] <= 235]
    outer = [i for i in sel if rows[i]["centroid_cyl_mm_deg"][0] > 270]
    print(f"inner (r 210-220): {len(inner)}   outer (r 280-300): {len(outer)}")
    print()

    for tag, idx in (("REFERENCE 6", [9, 10, 11, 12, 13, 15]),
                     ("INNER band sample", inner[:8]),
                     ("OUTER band sample", outer[:8])):
        mapping = ps._role_face_map(session, [faces[i] for i in idx])
        keys = [mapping.get(k, "<no role>") for k in range(len(idx))]
        print(f"{tag}:")
        for i, k in zip(idx, keys):
            print(f"   face {i:5d}  r={rows[i]['centroid_cyl_mm_deg'][0]:7.2f}  -> {k}")
    print()

    # Does the role key partition the two bands?
    def key_of(i):
        m = ps._role_face_map(session, [faces[i]])
        return m.get(0, "<no role>")
    inner_keys = Counter(key_of(i).split("|")[-1] for i in inner)
    outer_keys = Counter(key_of(i).split("|")[-1] for i in outer)
    print("distinct role object_ids -- inner:", len(inner_keys), " outer:", len(outer_keys))
    print("inner ids:", sorted(inner_keys)[:12])
    print("outer ids:", sorted(outer_keys)[:12])
    print("overlap:", sorted(set(inner_keys) & set(outer_keys))[:12])
finally:
    session.close()
