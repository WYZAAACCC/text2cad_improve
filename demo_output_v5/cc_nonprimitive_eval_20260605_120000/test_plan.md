# Test Plan — cc_nonprimitive_eval_20260605
## test_plan.md

### Test Objective
Evaluate the current v6.3 text-to-CAD non-primitive pipeline across 15 cases covering:
- Single-body basic parts (flange, valve block, shaft)
- Hole & pattern semantics (cross-holes, dual PCD, side patterns)
- Feature ordering & scope (ribbed base, shell enclosure)
- Advanced geometry (variable duct, 3D pipe)
- Multi-component assembly (support frame, double flange)
- Boundary/pressure tests (perforated plate, thin bushing, large ring)

### Test Configuration
- **Pipeline**: builder.py → validation → runtime → STEP
- **LLM**: DeepSeek V3 (via deepseek_client.py)
- **Runtime**: CadQuery + OCP
- **SolidWorks**: TBD (check COM availability)
- **Spatial Frontend**: auto_spatial mode
- **Repair Loop**: enabled, max 2 attempts
- **Autofix**: enabled (SYNTACTIC_ALIAS + SCHEMA_DEFAULT + CONTEXT_SAFE)

### Success Criteria
1. STEP file generated and > 10KB
2. Volume > 0
3. Solid count = expected
4. BBox dimensions match prompt (±20% tolerance)
5. No MULTI_SOLID unless assembly
6. No negative volume
7. Validation pipeline passes

### Case Categories
| Category | Count | Case IDs |
|----------|-------|----------|
| A. Single-body basic | 3 | 001-003 |
| B. Hole & pattern semantics | 3 | 004-006 |
| C. Feature order & scope | 2 | 007-008 |
| D. Advanced geometry | 2 | 009-010 |
| E. Multi-component | 2 | 011-012 |
| F. Pressure/boundary | 3 | 013-015 |

### Pass/Fail Criteria Per Case
- **PASS**: STEP generated, volume>0, solid count expected, bbox reasonable
- **PARTIAL**: STEP generated but geometry has warnings (multi-solid, volume deviation)
- **FAIL**: No STEP, negative volume, or validation error
