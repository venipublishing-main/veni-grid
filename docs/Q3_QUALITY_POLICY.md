# Veni Grid Q3: versioned break-aware and part-time-aware scheduling quality

**Status:** `0.2.0` quality-policy *review candidate*. Additive modules only. No change to C1 placement JSON schema, C1 feasibility solver, Q1 `0.1.0` scorer, or Q2 `0.1.0` optimiser. The historical Q1/Q2 comparisons remain reproducible under their originally pinned policies.

## Why a new policy?

The earlier `RESOURCE_IDLE_MINUTES` definition charges every elapsed minute between lessons, including a school-authorised interval such as a 20-minute morning break. `RESOURCE_DAILY_LOAD_SPREAD` compares the busiest and lightest days, including zero-load days: this can unfairly penalise a part-time teacher whose contract specifies two working days. Neither is universally a good penalty.

Q3 does **not** silently reinterpret those definitions. A model-fingerprint-pinned, version `0.2.0` `QualityPolicyV2` explicitly selects new metrics and their scopes.

## New metrics

### `RESOURCE_UNPROTECTED_IDLE_MINUTES`

- For each scoped PERSON/day, identify every positive gap between consecutive independently validated occupied event intervals.
- Subtract only the **union of explicitly supplied, non-overlapping protected breaks** that fall inside those gaps. Breaks overlapping a lesson do not erase occupied time.
- One day/person may have no protected intervals: all gaps then count, by design.
- Numeric penalty = unprotected elapsed minutes × policy weight. Break locations/lengths are supplied as data; this policy does not invent a school's bell times.
- **Supported now:** abstract cycle days using integer local clock minutes 0–1440. Real dated, cross-midnight and DST-specific protected-break policies are rejected as `UNRESOLVED_CONTEXT`/`UNSUPPORTED`, not guessed.

### `RESOURCE_TARGET_DAILY_LOAD_DEVIATION`

- A `target` explicitly names a PERSON, cycle/dated day, and expected teaching duty **minutes**.
- Raw penalty for each named person/day = `abs(actual_work_minutes - target_minutes)`; sum over targets, then multiply by policy weight.
- Days not listed are **not scored** by this metric; a zero-minute target is scored, but it is a soft preference, **not a prohibition**. Hard time-off/availability remains a separate C1 requirement.
- Consecutive or double lessons use **work minutes**, not any nonteaching gap inside the overall occupied interval.

### Old metrics remain available unchanged

The original six Q1 kinds may be included in a Q3 policy; the Q3 independent evaluator delegates those original components to the unchanged Q1 scorer, then computes the new ones independently. Comparison is allowed only for **fully scored, independently hard-valid candidates with identical model and complete 0.2 policy fingerprints**. Cross-version comparison is not implied.

## Exact Q3 CP-SAT optimisation

`optimise_v2(problem,policy,options)` runs a separate Q3 solver using the same C1 hard compiler and a new objective compiler subclass.

The protected-break objective measures gross gap time as `last_occupied_end − first_occupied_start − total_occupied_interval_length`, then subtracts `protected_break_overlap_with_occupied_span − occupied_event_overlap_with_break`. This is algebraically equivalent to excluding only the protected minutes that fall inside gaps, given enforced resource exclusivity. It does **not** count breaks twice.

The target-load objective uses per-person/day work-minute sums and exact CP-SAT absolute-value constraints. The independent Q3 scorer computes gaps and target deviations from the returned timetable. Q3 withholds any candidate when a compiled objective tier differs from independent scoring, or when hard validation fails.

Tier 2, then 3, then 4 are solved lexicographically. Only a **proved** optimum locks a tier. A feasible incumbent without proof is `NOT_PROVEN`. Unsupported constraints, unscored soft requests, stale hashes, mixed policies, and missing location facts fail closed. Publication permission is never granted.

## Benchmark B executed synthetic results (13 November 2026)

- 240 events, 120 invented learners, 24 invented teachers, 12 rooms, ten-day abstract cycle, 40 hard rules, eight Science doubles, two hard locks.
- Q3 test policy exempts 10:00–10:20 for all teachers on all cycle days, assigns explicit expected teaching minutes to eight part-time LIFE teachers, and scores subject spread and last-period placements.
- On one local real CP-SAT run, original supplied witness: `[0,0,40]`, C1 feasibility-only generated: `[0,160,50]`, Q3 generated: `[0,0,40]`.
- All 240 event placements independently validated. CP-SAT **proved** all three Q3 policy tiers optimal for this particular synthetic input and sidecar; Q3 tied the supplied known-valid reference while improving C1's measured penalty.
- **Do not compare these numbers to Q2's `[0,2380,40]`**: the policies differ. No school-wide, curriculum-complete or real timetable performance claim is made.

## Next hard requirements and safeguards

1. General dated/calendrical and DST break handling needs a separate typed profile and test matrix, not silent 24-hour assumptions.
2. Adopt qualified school-approved treatment of lunch, prep periods and half-days. Some gaps can be beneficial; a zero score isn't automatically pedagogically good.
3. Part-time targets must originate from an authorised staffing policy; score templates cannot infer contractual hours from unrelated staff records.
4. Model other soft priorities (learners, room moves, preference weighting, subject spacing), with exact external score/solver agreement.
5. Preserve independent schedules, scoped change permissions, publication boundaries, and POPIA-safe synthetic GitHub examples.

Reproduction: `python -m pytest -q tests tests_solver quality_tests q2_tests q3_tests`, then `python -m scripts.run_q3_probe --seconds 20`. This is a prototype, not a production app, not a full-school benchmark, and not yet ACTion/aSc capability parity.
