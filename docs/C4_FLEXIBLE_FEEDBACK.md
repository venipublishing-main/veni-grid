# Veni Grid — C4 flexible multi-occurrence teaching-feedback review

**Status:** Experimental, additive C4 v0.1.0. No real school data, authoritative approval, persistence or publication. The previously accepted **C1 → Q1/Q2/Q3 → O1 → C2 → C3** development baseline is left untouched.

## Why this extension is different

O1 can generate subject options where one subject family has sections in multiple blocks. C2 can independently schedule that plan using explicit teacher competency assertions, classroom capacities, room types, timetabled lessons and teacher continuity. C3 demonstrated a repair but only for **one block per entire subject family** and **one occurrence**. C4 genuinely searches **request-to-block choices** and **section counts per subject per block** and can verify **several supplied lesson occurrences per section**, including doubles.

## Exact algorithm and contracts

`C4Input(current: C2Input, proposed_block_windows: [C2BlockWindow], options: C4Options)` receives the original **versioned claimed-accepted O1 source** with explicit C2 supply, and a complete, user-supplied catalogue of permissible proposed block/occurrence windows. No times, teacher credentials, classroom inventories or new learner requests are invented. The original C2 source is independently checked first.

1. If the existing fixed plan is **FEASIBLE**, report `ALREADY_FEASIBLE` without an unnecessary proposal. If original C2 is `UNKNOWN`/`UNSUPPORTED`/`INVALID_INPUT`, do not infer impossibility or cut a candidate. Only a proved `INFEASIBLE` with `FIXED_O1_C2` scope triggers the search.
2. A CP-SAT variable `x[request,block]` gives each compulsory learner request exactly one option block, with at most one request per learner and block. Integer `section[family,block]` creates **zero or more** sections subject to minimum/maximum class size and the family's maximum section count. The effective maximum size is constrained by actual suitable exclusive classroom capacities. A family can have sections in multiple blocks; no artificial family-wide common block is required.
3. For each block and occurrence key, mathematical Hall-subset **necessary** teacher and exclusive-room capacity bounds restrict obviously impossible simultaneous sections. These constraints **cannot prove full lesson feasibility**; a teacher may still be unavailable on a particular day, share another timetable, or need continuity across days. Real C2 is authoritative for those hard constraints.
4. Minimise the number of learner-subject requests that change block versus the original, then the total number of sections, **within this restricted candidate model**. All original compulsory choices remain compulsory. Do not claim global optimality of the complete school timetable, even if the candidate CP-SAT search proves its local objective.
5. Convert to an `OptionDesignWitness` retaining exact explicitly chosen block IDs. The existing independent `option_errors` checker must accept every section and learner allocation. Run **real C2 CP-SAT** on the candidate with the complete original curriculum occurrence pattern for each subject; it must independently validate all lesson assignments, qualified staff, room suitability, capacity, continuity and exact times.
6. If C2 **proves** a particular candidate unteachable, exclude only that **exact pair of request-to-block assignments and section counts**. Do not exclude other possible resectioning with the same learner allocation. If C2 is `UNKNOWN` or unsupported, stop honestly; no proof-based elimination may occur. Bounded candidate loops can return `UNKNOWN` without implying general failure.
7. Return a cryptographically fingerprinted, **in-memory `C4Review`** with exact source and draft hashes, section before/after totals, requests moved, and validated teaching-event count. `review_errors` independently checks the hashes, original source, full O1 witness, C2 candidate and review diff. There is **no authenticated approval or write action**. Every result has `acceptance=NOT_GRANTED` and `publication=NOT_GRANTED`.

**Important trust boundary:** The existing C2 adapter requires a `SnapshotRef(state='ACCEPTED')`. C4 creates that reference **only transiently for a simulation**. It does *not* represent human consent, secure authorisation, an actual accepted revision or a database transaction. Production acceptance will require a trusted source registry, authenticated permissions, atomic compare-and-swap, audit entries and safe rollback.

## Generated synthetic result, 13 November 2026

- 16 fictional learners and **48 compulsory subject-choice requests** spanning four invented subjects A–D.
- The supplied original plan has **10 sections**. Because two sections of the same subject appear in one simultaneous option block, the available subject-qualified staff are insufficient; the original C2 maximum-matching preflight **proves that fixed plan unteachable**.
- C4 searches flexible request/block assignments and selects **9 sections**, including **Subject D present across multiple blocks**, rather than forcing one block for all its sections.
- **18 requests change option block, while all 48 remain fulfilled**. This is a measurable change, not a universal judgement of educational quality. Human review must decide whether the changed student experience is acceptable.
- Every section has **two teaching occurrences on distinct cycle days**; Subject D's laboratory lesson is a two-period double on each day. C2 CP-SAT generates and independently validates **18 total teaching events, 18 staff allocations and 18 classroom allocations**. The solution uses four qualified synthetic teachers and three suitable rooms, including one laboratory.
- The original source fingerprint is unchanged; no external timetables were read; no approval or publication was performed.

## Defensible status scopes

- `PROPOSED_VALIDATED`: both full option and teaching candidates independently checked; **not approved**.
- `ALREADY_FEASIBLE`: original fixed plan is independently feasible; no need to replan.
- `RESOURCE_RESTRICTED_INFEASIBLE`: a proved contradiction **only within C4's selected resources, supplied candidate windows, compulsory requests, exclusive rooms, explicit section sizes and its bounded flexible profile**. Does not imply school-wide infeasibility or impossibility after adding resources or changing curriculum.
- `UNKNOWN`: candidate budget or teaching solve unresolved; no infeasibility assertion.
- `UNSUPPORTED`: outside reviewed size/dated credential/shared-hall or comparable unsupported profile; do not quietly guess missing evidence.
- `INVALID_INPUT`/`ERROR`: bad inputs or code/validator disagreement. Withhold the candidate.

## Explicit gaps and next engineering gates

- **No arbitrary school scale:** this reviewed flexible prototype defaults to at most 120 requests, eight subject families, 32 generated sections and a finite number of CP-SAT candidates. The earlier *9,000-request* O1 fast-profile benchmark is **not** a 9,000-request C4 joint solve. A future scale program must profile the graph, variable count, teacher matching and multi-constraint explosion under realistic ten-day school input.
- **No dated credential/profile:** C4 rejects dated credentials while using its abstract cycle profile; the existing C2 dated solver is not extended with guessed epoch timestamps.
- **No source state authority:** SnapshotRef hashes detect changes, not who authorised a draft. An authenticated persistent service is required before enabling Approve/Publish.
- **No schedule linking by default:** only standalone academic O1/C2 target inputs are used; examinations, invigilation, duties, sport and room schedules remain independently runnable. Any shared read-only commitments need explicit user instruction and typed sources; joint planning needs separate approval.
- **No UI overclaims:** generated review HTML and teaching timetable use only actual independently validated candidate records. Their familiar labels are synthetic Subject A–D, Teacher A–D, Room 1/2/Lab, not real school classes. Code IDs remain available only in JSON audit receipts.
- **No preference policy used:** C4 first minimises moved learner options and number of sections; it does not incorporate the Q3 teaching-quality policy or grade/learner curriculum preferences beyond the compulsory requests. It does not imply a pedagogically best schedule.

## Run on a clean checkout

```bash
python -m scripts.prepare_workspace
python -m scripts.run_c2_probes
python -m pytest -q tests tests_solver quality_tests q2_tests q3_tests o1_tests c2_tests c3_tests c4_tests
python -m scripts.run_c4_probes
```

Review outputs are created under ignored `c4-output/`. The preview UI is `c4-output/c4-review-before-after.html` and links to `c4-output/c4-proposed-teaching-timetable.html`. No code writes a live school database or publishes a schedule.
