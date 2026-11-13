# Veni Grid C3.0 — Resource-aware replanning preview (v0.1.0)

**Status: review candidate, no publishing or acceptance.** One scheduling foundation, independently runnable jobs. The already merged C1/Q1/Q2/Q3/O1/C2 engines remain unchanged. This module uses only synthetic O1 demand, accepted option choices, and explicitly supplied academic-staff/room/calendar inputs.

## The problem being addressed

A learner-option plan can satisfy every learner request yet be impossible to teach in the available specialist rooms. A fixed O1 plan's C2 `INFEASIBLE` result is *only* a proof against that fixed plan, not evidence that the school has no alternative. C3 experiments with a **new, unapproved design**, keeping the original plan intact, and validates it end-to-end.

**Crucial proof scope:** C3 is a deliberately restricted **resource-aware SINGLE_FAMILY_BLOCK, SINGLE_OCCURRENCE, exclusive-room preview**. It does **not** optimise arbitrary flexible sections, multiple dates, timetables jointly, contractual employment, published schedules or 1,500-learner placement.

## Inputs and authority

`C3Input` contains the original `C2Input` with the existing *claimed* accepted O1 snapshot and a **separate complete, explicitly supplied candidate time-domain table** (`proposed_block_windows`). Candidate blocks must have known windows and allowed days. No new times are invented by the solver. Snapshot fingerprints are change detectors, not cryptographic approval. The preview temporarily constructs an in-memory `SnapshotRef(state='ACCEPTED')` only because the older C2 adapter requires that form; it **does not** record an actual accepted replacement in any store and does not grant any user authority. Production preview states and a trusted approvals service need a separate contract.

## Exact first-profile algorithm

1. Independently call C2 on the current accepted O1 plan. If it is teachable, return `ALREADY_FEASIBLE`. If the existing result is UNKNOWN, INVALID_INPUT or UNSUPPORTED, do not replan or guess.
2. Require a single original block per subject, one identical occurrence key across families, and explicitly supplied future block-time windows. Determine minimum feasible balanced sections from the unchanged learner requests and configured class-size bounds.
3. Create a CP-SAT model with `x[subject, block]`. Prevent a learner's selected subjects sharing an option block. For every section in each block, choose a **distinct** explicitly credentialled teacher and a **distinct** suitable exclusive room with adequate capacity. Enforce staff/room exclusivity within each synchronised block. Minimise moved subject-family blocks first, then used blocks, within this restricted model.
4. Convert the new block mapping using O1's deterministic section constructor, then independently run `option_errors()` to verify **every learner** and section. Nothing is copied from a preconstructed witness.
5. **Preview only:** create a transient C2 input using a newly fingerprinted proposal and explicit block windows; run real C1 CP-SAT lesson placement through C2 and independently validate every teacher, room, learner choice and time.
6. If a candidate is **proved** impossible in C2, forbid that *specific* assignment and try another candidate (bounded attempts/time). If a C2 preview is UNKNOWN/unsupported or has invalid inputs, **do not discard it as mathematically impossible**.
7. Return the independently validated alternate witness and a human-readable before/after. No accepted O1 source is modified; no other schedule is loaded; no publish or approve action exists.

## What the solver genuinely demonstrated

### Small executable example: one lab, two subjects

- Six **invented** learners, three requesting Subject A and three requesting Subject B, plus two explicitly qualified teachers.
- O1 correctly produces **one** learner-valid option block; both subjects are at 08:00 but need the **same sole laboratory**. C2 proves that fixed plan unteachable by maximum matching.
- C3's resource-aware CP-SAT model chooses **two** blocks. Subject B remains at 08:00; Subject A is proposed at **09:20** using the same laboratory later. The example times are supplied beforehand, not invented by C3.
- All six requests remain allocated, both O1 sections pass the independent option validator, and **both actual lessons** receive independent C2 hard validation with correct teachers and room.
- The old source remains byte-identical; response is `PROPOSED_VALIDATED`, `acceptance=NOT_GRANTED`, `publication=NOT_GRANTED`.

### Necessary aggregate bound: 1,500 synthetic learners

In the **restrictive** synchronous-six-block profile, a previously generated 360-section O1 plan requires at least 360/30 = **12 blocks** if only 30 exclusive classrooms can be used per block. The configured maximum is six. This is a restricted-profile capacity contradiction, **not** a global institution proof: additional resources, smaller groups, more block slots, non-synchronous scheduling or other resectioning could change the result.

### Other tests

- One explicitly competent teacher serving two subjects can be reused on separate blocks.
- One-block-only scope produces a narrowly-labelled `RESOURCE_RESTRICTED_INFEASIBLE`, **not** full O1 or whole-school infeasibility.
- If two proposed blocks share the same only time, the full C2 placement rejects that candidate.
- A time-limited C2 UNKNOWN result is never used as a no-good proof.
- Missing additional block domains, invalid window IDs, stale O1 sources, unsupported flexible original plans and model-size guards all fail closed.
- Both timetable displays are built from real solver outputs, with zero pretend placement or school identities.

## User interface: correct meaning, not just prettier codes

`readable/c2-teaching-timetable-explained.html` is a **self-contained interaction** generated from the real 18-event C2 problem and candidate. It translates each synthetic subject, qualified teacher and room into clear labels. Periods/time windows, class sizes, single/double duration and allocations are taken from the validated witness. Filters for day, teacher, room and class are functional; print is available. It remains labelled synthetic, two-day and partial curriculum.

`c3-output/c3-feedback-before-after.html` is an independently derived **review comparison**. It uses source and proposed block time domains, not hard-coded A/B movement; the actual result moves Subject A to 09:20, leaving Subject B at 08:00. It explicitly says the plan is **not accepted**.

## What remains (C4 and beyond)

- Full O1 multi-block, flexible sectioning, more than one occurrence, multiple bells/dates and resource continuity across days.
- A trusted acceptance/authorisation server, protected versioned schedule storage, before/after audit, explicit user-approved modification and rollback.
- Actual joint feedback on a complete 1,000–1,500-learner teaching timetable (not just demand generation or a capacity floor).
- First-class explanations of why a class/teacher/room constraint failed, and multiple alternative proposals ranked with independent score policies.
- Linked read-only commitments from exams/invigilation/duties and optional joint planning **only when explicitly requested**.
- Accessible connected UX and legitimate teacher-friendly subject names from authorised institution data; a real school must never appear in the public synthetic repository.

## Reproduction

```bash
python -m scripts.prepare_workspace
python -m pytest -q tests tests_solver quality_tests q2_tests q3_tests o1_tests c2_tests c3_tests
python -m scripts.run_c2_probes
python -m scripts.render_c2_for_people
python -m scripts.run_c3_probes
```

Neither script alters GitHub, Drive, a database, a published schedule, or any user account. CI also verifies that everything runs from a fresh checkout. All source and generated examples are synthetic.
