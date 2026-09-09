# Main Experiment

This directory contains the isolated benchmark and data collection module.

It must not modify:

- `app/text-to-cad/server/main.py`
- `integrations/engineering_tools/src`
- `_param_experiment`

All experiment outputs are written below `_main_experiment/output/`.

## Sub-experiment suites

Run each suite through the CLI (real LLM calls happen only with `--run`):

- `regen` — 800 parameter perturbations (single/double/3-5/cross-feature + boundary-margin groups).
  `python -m _main_experiment.cli regen` then `... regen --run`.
- `infeasible` — 120 infeasible designs (5 categories) with/without explicit constraints.
  `python -m _main_experiment.cli infeasible [--run] [--without-constraints]`.
- `semantics` — 320 semantically-equivalent instructions (8 categories).
  `python -m _main_experiment.cli semantics [--run]`.
- `tools` — 160 tool-planning tasks x fixed/MCP/llm-code interfaces x 5 seeds (800 flows per interface).
  `python -m _main_experiment.cli tools [--run]`.
- `methods` — print model-comparison method registry (swap API by changing model/base_url/key env).
- `direct` — Direct-Base code-generation baseline (CadQuery, no IR harness).

Generated task lists are written to `output/suites/<suite>/tasks.json`; run results and
aggregates go to `output/suites/<suite>/results.json` and `aggregate.json`.
