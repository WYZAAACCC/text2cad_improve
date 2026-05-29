# Turbomachinery Reference Domain Skill (Level-1)

## Overview
Turbomachinery reference geometry — non-flight, non-certified, non-manufacturing.

## Applicable Dialects
- **axisymmetric**: disks, hubs, rings, flanges, shafts, seal runners
- **sketch_extrude**: brackets, mounts, support structures
- **composition**: rotor assembly reference, multistage disk stacks

## Routing Rules
1. Rotating disks/hubs/rings → axisymmetric
2. Blades/vanes/nozzles → unsupported (requires loft_sweep dialect)
3. Casings/housings → unsupported (requires shell_housing dialect)
4. Assemblies → composition if all components can be expressed

## Critical Safety Constraints
- ALL generative turbomachinery output is NON-FLIGHT REFERENCE GEOMETRY ONLY
- NOT airworthy
- NOT certified
- NOT for manufacturing
- NOT for installation
- NO structural validation
- NO life prediction
- If user requires airworthy/certified/manufacturing status → route to unsupported
