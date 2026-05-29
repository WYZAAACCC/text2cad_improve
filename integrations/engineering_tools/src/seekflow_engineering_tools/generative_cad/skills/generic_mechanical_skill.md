# Generic Mechanical Skill v0.1

Use this skill to guide selection and construction of generic mechanical reference geometry.

## Base selection guidance
- Use `axisymmetric_base` for rotational parts: rings, disks, shafts, hubs, flanges, pulleys.
- Use `sketch_extrude_base` for prismatic machined parts: plates, brackets, blocks, lugs, mounting adapters.
- Do not choose a base that is not in the catalog.
- If no base can express the requested geometry, report missing capabilities.

## General modelling rules
- Prefer stable mechanical features: extrudes, cuts, bores, pockets, hole patterns, ribs, bosses, chamfers.
- Avoid unsupported organic freeform geometry.
- Do not invent operations.
- All units are mm.

## Safety
- Generative output is reference geometry only.
- Never claim production-ready, certified, or manufacturing-ready status.
