# Veni Grid

**Veni Flow · C1 Solver v0.1.0 · implementation baseline for review**

A bounded constraint-based timetabling engine built with Python and OR-Tools CP-SAT, with a separately implemented candidate validator.

This repository contains the reviewed solver and contract source, all 423 original regression tests, synthetic fixture generators, and full-suite GitHub Actions verification. It is **not a production school application** and does not yet claim ACTion/aSc parity or school-scale search performance.

## Current capabilities

The `veni_grid_solver` package implements **C1_PLACEMENT / FEASIBILITY** against input schema `1.0.0-rc1`: discrete start domains, resource selection, learner enrollment in supplied offerings, nested groups, exclusive/shared-capacity resources, single/double/minute-duration events, locks and eleven typed hard-rule families.

The `veni_grid_contract` package also contains independently usable invigilation-coverage and option-design contracts, handoff adapters, scoped-change checkers and calendar projection. Those components are **not** segmented-coverage or automatic option-design optimisers. Its historical `CONFORMANCE_PROFILES` and `execution_gate()` describe the contract-only package; invoke `veni_grid_solver.solve()` for the actual C1 runtime.

A timetable can run separately and only when needed. Shared information does not authorise changes to another timetable. Nothing here publishes or modifies live timetables.

See [architecture and supported boundaries](docs/ARCHITECTURE.md) and [repository verification](docs/REPOSITORY_VERIFICATION.md).

## Start from a clean clone

The reviewed CI environment is Python 3.13 on Ubuntu 24.04. Other environments have not been certified by this repository's initial CI run.

```bash
git clone https://github.com/venipublishing-main/veni-grid.git
cd veni-grid
git switch feat/c1-solver-v0.1.0
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -c requirements-solver-reviewed.txt -e ".[solver,test]"
python -m scripts.run_ci
```

`run_ci` verifies the imported source, regenerates all synthetic fixtures/schemas, runs the 423 tests, checks 18 contract scenarios and executes 12 real CP-SAT benchmark cases. It fails if tests are skipped, counts unexpectedly fall, generated candidates fail independent validation, or a benchmark status differs from its expectation.

For an individual example after preparation:

```bash
python -m scripts.prepare_workspace
python -m veni_grid_solver fixtures_solver/school-benchmark-a.json --output workspace/result.json
```

Expected school result: `FEASIBLE`, 24 generated events, independent validation `PASSED`. This small example declares only 13 periods per class; it is not a full school curriculum or a quality-optimised timetable.

CLI exit codes: 0 feasible; 3 proved infeasible; 4 unresolved; 2 input/unsupported/runtime failure. JSON contains the detailed status and findings.

## Reproducible evidence

Full CI writes `ci-output/verification.json`, JUnit and text logs, contract-scenario results and `evidence_solver/` benchmark results. The workflow uploads these as a seven-day artifact. Inspect the run and commit: an older green smoke test is **not** full-suite evidence.

The expected benchmark status distribution is eight feasible, three proved infeasible and one unknown under zero search budget. Every feasible case must pass the independent checker. Quality optimality is not assessed.

Fixture JSON and JSON Schemas are generated from versioned Python definitions, not manually maintained duplicate copies. `prepare_workspace` overwrites only these disposable development outputs. Keep real school data elsewhere.

## Source provenance and privacy

`source-provenance.json` pins 42 original Python files plus the preserved nested-subgroup regression to SHA-256 hashes from `veni-grid-c1-solver-v0.1.0.zip`. The original archive SHA-256 is recorded there. Bootstrap scripts, CI and public-facing documentation are new repository packaging, not solver changes. Fingerprints establish content identity, not security or authorship.

This public repository contains synthetic examples only. Never commit learner/staff records, real exam allocations, credentials, `.env` files, private project-document links or workstation paths. Private design archives and historical machine-generated logs are not imported into the public tree. No binary dependencies are vendored.

No new open-source licence has been selected in this import. Third-party dependency licences remain separate; do not infer distribution permission from the repository being public.

## Next engineering work

Preserve the hard-feasibility baseline while adding independently recomputable quality scoring and realistic school-scale benchmarks. Repair remains a distinct, explicitly scoped operation. Segmented invigilation optimisation, automatic option/section construction, integrations, publication and the UI remain later work, not completed features.
