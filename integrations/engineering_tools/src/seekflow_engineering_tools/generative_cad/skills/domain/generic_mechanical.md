# Generic Mechanical Domain Skill (Level-1)

## Overview
Generic mechanical parts that can be expressed through standard CAD grammar dialects.

## Applicable Dialects
- **axisymmetric**: rotational bodies (flanges, hubs, rings, end caps, pulleys)
- **sketch_extrude**: prismatic parts (brackets, plates, blocks, mounting fixtures)
- **composition**: multi-component assemblies

## Routing Rules
1. If the part is primarily rotational → axisymmetric
2. If the part is primarily prismatic/extruded → sketch_extrude
3. If multiple bodies/parts → composition
4. Never select a dialect for a part that requires freeform/surface modeling

## Safety
- All generative output is reference geometry only
- Never claim manufacturing-ready or certified status
