# Veni Grid — Q2 quality optimisation v0.1.0 (review candidate)

**Experimental engine:** CP-SAT lexicographic optimisation for the precise Q1 policy sidecar; C1 hard-feasibility code unchanged. Q2 solves one standalone scheduling problem on demand. It **does not** publish a schedule or alter other timetables.

## Semantics and proof boundary

- The existing C1 `CoreProblem 1.0.0-rc1` retains `solve_config.mode=FEASIBILITY`; Q2 is an **additive separate service** called with the same problem and a `QualityPolicy`, not a change to C1's enum or runtime.
- Compile all C1 hard constraints before adding policy objectives. Q2 refuses unsupported/invalid hard input, any enabled SOFT C1 constraint or legacy objective outside the Q1 sidecar, stale policy/model hashes and any unscored soft learner requests. It does not quietly reinterpret or drop them.
- Q1 independent `score()` is authoritative for output checking; Q2's objective expressions are separate implementations of the six known Q1 metric definitions. For each solved tier, the compiled CP-SAT objective must **exactly equal** the independently rescored result. Any mismatch withholds the candidate and records an error.
- Minimise the three tiers sequentially: **Tier 2 critical → Tier 3 general → Tier 4 aesthetic**. A tier is locked at its returned objective only if CP-SAT proves that stage `OPTIMAL`. If it finds a good incumbent without proof, return `FEASIBLE` + `NOT_PROVEN` and stop rather than pretend the lower tiers have been optimised. If a later stage times out unresolved, preserve the last independently validated candidate. An unsolved first stage returns UNKNOWN, never INFEASIBLE.
- No weighted scalar can allow a lower-tier improvement to compensate for worsening a higher tier. All penalties are nonnegative integers and checked against safe prototype bounds.
- User-facing `quality_optimality=PROVEN` is reserved for all three tiers proved optimal. It is not implied by a raw CP-SAT status of OPTIMAL in a satisfaction-only model.

## Supported Q1 metrics: exact objective constructions

1. `ACTIVITY_DAY_PAIRS`: count scheduled event occurrences per activity/day; use a CP-SAT table of `n(n-1)/2`.
2. `RESOURCE_IDLE_MINUTES`: for each person/day, objective `last occupied end - first occupied start - sum(selected event interval lengths)`; hard exclusivity makes this exactly equal to Q1's sum of gaps between consecutive engagements. Includes breaks and excludes gaps *inside* a multi-window event, exactly as Q1 measures.
3. `RESOURCE_DAILY_LOAD_SPREAD`: sum actual work durations per person/day, including zero days; minimise max load minus min load.
4. `TAGGED_PLACEMENTS`: penalise selected event placements overlapping tagged windows *of the chosen bell regime*; count each event once.
5. `RESOURCE_LOCATION_CHANGES`: derive the actual chronological successor of each person's selected event via a CP-SAT circuit, penalise successor edges whose selected room locations differ. The initial exact compiler requires one room allocation per event, complete room locations and at most 80 potential daily events/person; unsupported shapes **fail closed**.
6. `UNMET_SOFT_REQUESTS`: minimise `max(0,min_select-actual_selected_offerings)` per explicitly covered SOFT request.

## Important policy caveats

The six metrics have not been universally calibrated for school use. The current idle-time definition includes lunch breaks; part-time staff may legitimately need unequal day loads. An institution-specific policy should introduce explicit break exclusions, desired teacher teaching blocks, day scopes and room-movement weighting. Q2 honours the approved **current Q1 definitions exactly**; it does not stealthily change them. A later policy revision requires new tests and a matching objective implementation.

## Synthetic Benchmark B result

Ten-cycle-day, partial-curriculum benchmark: 120 fictitious learners, 24 synthetic teachers, 12 rooms, 70 windows, 240 events, 40 HARD distribution rules, eight Science doubles, and two locks.

- Known-valid: Q1 `[0, 2720, 40]` (tiers 2/3/4).
- C1-generated: `[0, 2900, 50]`.
- First Q2 search: `[0, 2380, 40]` within a twelve-second configuration on one local environment; all 240 assignments independently validated. That is a 12.5% lower general-quality penalty than the known-valid reference and ~17.9% lower than the C1-generated baseline *for this configured test policy*.
- Tier 2 proven OPTIMAL at 0; tier 3 reported FEASIBLE **without** a proof. Tier 4 remains a measured number, **not a proved minimum**. The result is `quality_optimality=NOT_PROVEN`.

The timing, status and score are evidence for one synthetic input and seed, not claims of general large-school capability. The original `C1/FEASIBILITY` remains available and unaffected.

## Quality tests and acceptance

The regression suite includes hand-computed single-metric test oracles, multi-tier lexicographic priority, soft-request optimisation, stale-policy refusal, a zero-budget UNKNOWN case, a restricted room-location refusal, protection against baseline repair requests, independent-score mismatch withholding, C1 unchanged operation and Benchmark B real search. Run:

```bash
python -m pytest tests tests_solver quality_tests q2_tests -q
python -m scripts.run_q2_probe --seconds 25
```

`q2-output/` contains JSON and Markdown scorecards and the independently validated generated synthetic candidate. These files are local evidence and are never authorised timetable publications. CI tests install pinned OR-Tools and reproduce the check from a clean GitHub checkout.

## Next after independent review

1. Allow legitimate non-teaching breaks to be exempted from idle-time penalties through a **new versioned policy**, and test part-time staff scoring policy templates.
2. Candidate diversification with explicit comparison (not randomized multiple copies), and optional warm starts after validated prior results.
3. Realistic Benchmark C: ~1,500 synthetic learners with section choice/block construction, scarce teachers/rooms, variable staffing, full horizon and performance evidence. This is a different, harder mathematical challenge.
4. Dedicated invigilation coverage optimiser and scoped least-disruption repair remain separate run modes; their present contracts are preserved.
5. UX Lab: instrument actual usability against ACTion/aSc before claims of UI superiority.
