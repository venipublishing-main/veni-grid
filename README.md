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

## Experimental Q1 quality measurement (review candidate)

The additive `veni_grid_quality` package can independently score and compare
hard-valid C1 candidates using an explicit, version-pinned tier-2/3/4 policy.
It **does not** optimise or publish a timetable, and cannot outrank hard feasibility.
Six transparent metrics are defined in [the quality contract](docs/Q1_QUALITY_CONTRACT.md).

A 10-day synthetic Benchmark B has 240 lesson events, 120 invented learners,
24 educators, 12 rooms and 40 hard rules. The original C1 solver can generate
all 240 assignments, but the resulting *feasible* schedule is not always
as convenient as a separate known-valid timetable under the Q1 test policy.
Do not confuse this test dataset with a real 1,500-learner school-scale claim.

Run the original 423-test suite with `python -m scripts.run_ci`; additionally run
`python -m pytest -q quality_tests` and `python -m scripts.run_quality_probe`.
An independent Q1 GitHub Actions workflow performs the latter checks on PRs.
The C1 contract and solver source are unchanged by this addition.

## Q2 lexicographic quality optimisation (review candidate)

Q2 is a separate experimental CP-SAT service with an external Q1 QualityPolicy.
It compiles the six existing Q1 penalty semantics and minimises tier 2, then tier 3,
then tier 4. Only proved tier optima are locked; any returned incumbent is
independently checked and rescored. A valid improvement is **not** labelled
optimal unless all tiers have proofs. C1 feasibility is unchanged.

The tested synthetic 240-event Benchmark B improved the general-quality penalty
from 2,720 (known-valid reference) and 2,900 (C1 generated) to 2,380. The
critical tier was proved optimal; the general tier was not proved optimal.
These are deliberately configured test-policy values, not complete-school
performance or marketing claims.

Run `python -m pytest q2_tests -q` and
`python -m scripts.run_q2_probe --seconds 25`. See
[Q2 optimisation boundaries](docs/Q2_OPTIMISATION.md).

The [interactive UX Lab](ux_lab/grid-workbench.html) is standalone HTML using
synthetic illustrative placements; it has no solver, persistence or access to
real school data. See [UX Lab brief](docs/UX_LAB_01.md).

## Q3: break-aware and part-time-aware quality (review)

The optional **Q3 policy 0.2.0** adds explicit protected nonteaching intervals and per-person/day targeted workload penalties without changing the C1 input contract or historical Q1/Q2 definitions. It independently scores and can optimise the new metrics. See [Q3 policy](docs/Q3_QUALITY_POLICY.md).

A **1,500-learner C0 synthetic dataset** exercises the subject-choice input and supplied-section validator (9,000 requests, 450 constructed section offerings); **no automatic option-block planning or school-scale solve is claimed**. See [Benchmark C0 scope](docs/BENCHMARK_C0_SCOPE.md).

On a fresh checkout, run `python -m scripts.prepare_workspace`, then `python -m pytest -q tests tests_solver quality_tests q2_tests q3_tests`, `python -m scripts.run_q3_probe --seconds 20` and `python -m scripts.build_benchmark_c0`. Only synthetic data; no deployment or publication.

## O1 option-block generation (review candidate)

The **O1 demand-first option solver** accepts learner requests without any
preconstructed blocks or sections and constructs a conflict-free plan using
OR-Tools CP-SAT. An independent options validator checks every output.
The fast profile colours whole subject families; an exact flexible profile
may place sections of the same subject in different blocks. Single-family
impossibility is explicitly scoped and does **not** prove the general model
impossible. Staffing, rooms, curriculum lesson times and publication remain
separate later gates; no other timetable is changed.

The C0 synthetic run generates **six blocks and 360 sections** for 1,500 invented
learners (9,000 requests), rather than copying the previously supplied 450-section
witness. A crossed-choice C1 case exercises the true flexible profile and its
infeasible counterpart. This is not ACTion/aSc functionality parity.

Run `python -m pytest -q o1_tests` and `python -m scripts.run_o1_benchmarks`.
See [O1 solver contract](docs/O1_OPTION_DESIGN.md) and
[Benchmark progression](docs/BENCHMARK_C1_SCALE.md).

## C2 qualified teachers and classrooms (review candidate)

The standalone `veni_grid_integration` module accepts an **unchanged,
accepted O1 section plan**, explicitly supplied curriculum requirements,
qualified teachers, classroom capacities/type tags and calendar windows.
It uses the existing independently checked O1-to-C1 handoff and real CP-SAT
lesson placement. A maximum-matching preflight rejects impossible simultaneous
staff/room assignments before expensive search. This **does not automatically
rebuild O1 choices**, certify official teacher registrations or publish a timetable.

The small crossed-choice benchmark generated 18 actual lessons across nine
sections using four subject-qualified synthetic teachers and three suitable
rooms (including a specialist lab), with independent hard validation. The
1,500-learner **resource-preflight-only** examples identify 60 simultaneous
sections against only 30 suitable rooms or qualified staff—without running a
full 1,500-learner school timetable search.

Run `python -m scripts.prepare_workspace`, then
`python -m pytest -q tests tests_solver quality_tests q2_tests q3_tests o1_tests c2_tests`
and `python -m scripts.run_c2_probes`. See
[C2 exact boundary](docs/C2_O1_TO_TEACHING.md) and
[C2 benchmark gates](docs/BENCHMARK_C2_RESOURCE_GATES.md).
Only invented data is used; no calendar, staffing records or other independent
Grid timetable is loaded without explicit input. C1/Q1/Q2/Q3/O1 source is unchanged.

## C3 resource-aware option-replanning preview (review)

A **C3 experimental preview** can generate a new learner-valid subject-block
layout after the fixed accepted O1 plan is proved impossible to teach by C2.
It uses a restricted one-block-per-subject, one-occurrence, exclusive-room,
qualified-teacher CP-SAT model and explicitly supplied candidate block times.
A proposal is independently checked by O1 and real C2 timetable placement.
**It does not change the accepted plan or publish anything.**

The user-facing example displays an *actual independently validated* two-day
C2 timetable as clear Subject / Class / Teacher / Room cards, with filters, and
a separate C3 before/after preview explaining a one-laboratory conflict.
Run `python -m scripts.run_c2_probes`,
`python -m scripts.render_c2_for_people`, and
`python -m scripts.run_c3_probes`. Open
`readable/c2-teaching-timetable-explained.html` and
`c3-output/c3-feedback-before-after.html`.
Read [C3 exact boundaries](docs/C3_RESOURCE_FEEDBACK.md). No real school data.

## C4 flexible multi-occurrence teaching feedback (review candidate)

C4 is a small, **additive** resource-aware replanner that can place a subject's
sections in *different* option blocks, rebuild section counts from learner
requests, and verify **multiple actual teaching occurrences** per section using
C2's real qualified-teacher, room-capacity and time-placement checks. It starts
only from a proved **fixed-plan** C2 contradiction and never edits a source.

A controlled synthetic demonstration uses **16 learners with 48 compulsory
requests**. The original ten-section option plan could not be staffed. C4
reassigned 18 subject-choice blocks and generated nine sections; all 48 choices
remained fulfilled and C2 independently validated 18 teaching events across
two cycle days, including laboratory doubles. C4's conservative default
prototype supports at most 120 requests; this is **not** a 1,500-learner
joint timetabling claim.

The [human review preview](docs/C4_FLEXIBLE_FEEDBACK.md) and
[security/approval boundary](docs/C4_REVIEW_BOUNDARY.md) are review-only. No
real acceptance, persistence or publication is implemented. A simulated
ACCEPTED adapter reference is never an authority record. C1–C3 and all other
independent Grid timetable jobs remain unchanged.

Reproduce from a fresh clone with `python -m scripts.prepare_workspace`,
`python -m scripts.run_c2_probes`,
`python -m pytest -q tests tests_solver quality_tests q2_tests q3_tests o1_tests c2_tests c3_tests c4_tests`,
and `python -m scripts.run_c4_probes`. The actual readable review is then at
`c4-output/c4-review-before-after.html`.
