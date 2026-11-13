# Veni Grid — Q1 quality measurement, v0.1.0 (candidate)

**Scope:** independent evaluation and *comparison* of already hard-validated C1
solutions. Q1 **does not search**, optimize, repair, publish, prove quality
optimality or override any hard constraint. The existing C1 input schema
`1.0.0-rc1` remains unchanged. A separate Pydantic `QualityPolicy` sidecar
preserves that boundary.

## Steps

1. Provide an immutable `CoreProblem` snapshot and a complete `CoreWitness`.
2. Pin `QualityPolicy.model_sha256` to the SHA-256 of the canonical JSON model.
3. Independently recheck all hard constraints using `review_core()`.
4. For each explicitly configured metric, compute its **raw nonnegative integer
   penalty**, multiply by its integer weight, and retain a reproducible
   per-resource/day/event breakdown.
5. Aggregate separately into tier 2 (critical), tier 3 (general) and tier 4
   (aesthetic). Compare ordered vectors lexicographically; never let any amount
   in a lower tier outweigh a higher tier.
6. Refuse comparison across differing model snapshots, policies, or incomplete
   coverage. Neither evaluation nor comparison asserts OPTIMAL.

**Tier 0 hard feasibility is a precondition, not a tradeable penalty.** Tier 1
stability/repair remains not assessed. Q1 reports only tiers `[2, 3, 4]`.

## Supported explicit metrics

| Kind | Exact raw penalty | Unit / caution |
| --- | --- | --- |
| `ACTIVITY_DAY_PAIRS` | For each scoped activity and day with `n` **events**, `n(n-1)/2` | Pairs of occurrences on one day. A duration-two event counts as one occurrence. |
| `RESOURCE_IDLE_MINUTES` | Sum of positive gaps between chronological consecutive occupied events for each scoped PERSON/day | **Elapsed minutes**, including lunch/legitimate breaks. Not automatically "wasted periods". For dated events, use UTC elapsed time. |
| `RESOURCE_DAILY_LOAD_SPREAD` | For each scoped PERSON, `max(work_minutes per scoped day) - min(...)` | Minutes; includes zero-load days intentionally. A part-time teacher may rightly need a different scope. |
| `TAGGED_PLACEMENTS` | One per scoped event whose occupied interval overlaps at least one window with one of the nominated tags | Event count; e.g. `FINAL` or `P8`; double lessons are counted once. |
| `RESOURCE_LOCATION_CHANGES` | One per change of building/location between consecutive scoped PERSON assignments on the same day | Count. Requires explicit locations on *all* relevant uses. Missing data means `UNRESOLVED_CONTEXT`, not 0. |
| `UNMET_SOFT_REQUESTS` | Sum `max(0, requested min_select - selected offering count)` | Missing selection count for explicit SOFT requests only. Non-enrolled requests must be explicitly represented in the witness. |

Weights are *policy* decisions, not claimed universal best-practice values.
Missing/unknown metric IDs, resource references, invalid strengths or wrong
model fingerprints fail closed. Existing SOFT rules, legacy objective declarations
or soft requests that are outside the explicit Q1 policy are reported as
`INCOMPLETE_SCORING`; partial scores cannot be compared as complete results.

## Counterexamples and honesty

- A candidate reporting `validation=PASSED` does not certify itself. A C1
  witness must not self-attest validity; the independent checker is invoked.
- A teacher overlap, invalid lock, moved examination or stale model version
  produces `INVALID_CANDIDATE` and **no quality score**.
- `FEASIBLE` from C1 is sufficient to measure quality, but a raw CP-SAT
  `OPTIMAL` from a *satisfaction* search is **not** a proof of the best Q1 score.
- Two score vectors are only comparable when the exact model, version and
  quality policy are identical, neither has unscored requirements and both
  passed independent hard validation.
- The metric set is deliberately small. Preferences for student workload,
  room moves, equity, subject spread, teaching blocks and break exclusions
  will require reviewed additional policy types. No such requirement is
  silently satisfied just because Q1 outputs a number.

## Reproduction

`python -m pytest -q quality_tests` validates the transparent hand-worked
metric examples, invalid data and the synthetic scale probe.

`python -m scripts.run_quality_probe` builds an **independently validated known
witness** for Benchmark B, actually runs C1 CP-SAT on the same model, scores
both candidates and writes a comparison to `quality-output/`. It performs no
optimization or writes outside the local working directory.

## Benchmark B profile

8 groups of 15 invented learners (120 total), 24 educators, 12 rooms
(including four labs), 10 cycle days, seven period windows/day, 240 discrete
lesson events representing 248 period units, 40 hard subject-spread rules,
2 fixed double-period locks. Educators teach paired groups; some have explicit
limited availability. Candidate starts include a valid reference placement and
at least one alternative per event. No real pupil information.

Benchmark B is a **medium-sized constrained synthetic fixture**, not a complete
secondary-school model. It does not yet include 1,500 learners, arbitrary
subject-choice optimisation, complete parallel forms or institution-specific
lesson requirements. Report solver runtimes with machine environment and never
market them as universal performance claims.

## Implementation boundaries

- `C1_PLACEMENT/FEASIBILITY` remains the only actual solver mode.
- Q1 is **quality evaluation only**. Its tier vector must be recomputable
  independently before we add CP-SAT preferences/objective terms.
- `I1_COVERAGE`, `O1_OPTION_DESIGN` and all published schedules remain separate.
- The C1 source import provenance guard is kept intact; Q1 adds separate files.
- All fixtures must remain synthetic in the public repo. No private Drive links,
  identifiable school records, deploy keys or user credentials.
