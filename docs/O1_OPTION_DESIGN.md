# Veni Grid O1 — Demand-first option-block and section construction v0.1.0

**Status:** experimental executable solver, not a timetable publisher and not ACTion/aSc parity. This is the first **actually generating** learner-choice solution; earlier Benchmark C0 provided its answer as a witness. Input is the unchanged `OptionDesignProblem` schema `0.3.0-draft` with **no proposed blocks, offerings or allocations**. Output is the existing `OptionDesignWitness`, verified independently with `option_errors()`.

## Mathematical problem solved

For every learner request `(learner, family)`, assign the learner to exactly one section of the required subject family. Each section belongs to exactly one option block. A learner must not be assigned two requested subjects in the same block. Every populated section has between the family-specific minimum and maximum number of learners, and the total number of sections for that family cannot exceed `max_sections`. The overall number of option blocks cannot exceed `max_blocks`. All requests are compulsory under the current contract.

### Supported profiles (important distinction)

**`SINGLE_FAMILY_BLOCK` — fast graph-colouring profile.** For each family `f`, choose one block `b(f)`; learners who request both `f` and `g` create a cannot-share-block edge. CP-SAT selects a legal colouring and minimises the number of used blocks. For each family, sections are then created at the **minimum count compatible with its stated maximum section capacity**, and individual requests are allocated deterministically and evenly. The independent witness checker checks every learner and section. A proof of single-family-block impossibility is **not** a proof that multi-block sections cannot solve the problem. Accordingly, `proof_scope=SINGLE_BLOCK_ONLY` and `block_optimality_scope=SINGLE_BLOCK_ONLY` are mandatory.

**`FLEXIBLE_SECTIONS` — multi-block family profile.** Each learner-request `r` chooses a block `b`, with one chosen block per request and no duplicate block per learner. CP-SAT decides the number of sections for each family/block using integer `s(f,b)` satisfying `min_members * s(f,b) <= assigned(f,b) <= max_members * s(f,b)`, with `sum_b s(f,b) <= max_sections(f)`. Families can appear in multiple blocks. CP-SAT first minimises used blocks and, **only if that tier is proved optimal**, fixes the block count and minimises section count. The selected requests are divided evenly into the decided sections, with the entire witness then checked. If optimality is not proved, it returns a hard-valid incumbent without claiming a global optimum. This profile currently has an explicit configurable request-count guard (default 2,500) to prevent untested large variable explosions. Exceeding the guard returns `UNSUPPORTED`, not fake `INFEASIBLE`.

**`AUTO` (default)** attempts the fast profile first; upon a **proved** single-family graph contradiction, it tries the flexible profile with the remaining time. A feasible fast-profile result is not claimed globally optimal for the wider multi-block design space.

## Proof / scope status contract

- `FEASIBLE`: the actual CP-SAT-generated witness has passed `option_errors()`; no teacher/room/lesson placement claim.
- `INFEASIBLE + FULL_O1`: the flexible assignment-and-section model was proved impossible **under the current O1 contract and given all-compulsory requests**; this is not evidence that a future richer contract allowing optional courses or special alternatives is impossible.
- `INFEASIBLE + SINGLE_BLOCK_ONLY`: the restricted family graph was proved uncolourable within `max_blocks`, but multi-block sections may work. Do not show this as school-wide infeasibility.
- `UNKNOWN`: time budget expired before a feasible solution/proof. Not infeasible.
- `INVALID_INPUT`: broken foreign keys, duplicate person/family demands, malformed model or parameters.
- `UNSUPPORTED`: request shape exceeds the explicit flexible variable guard; no silent cut-off.
- `ERROR`: internal extraction/validator disagreement; **withhold** the witness.

A proof of minimum **block count** is explicitly scoped as `block_optimality_scope=FULL_O1` or `SINGLE_BLOCK_ONLY`. The independent checker proves **validity** of a supplied witness; the solver's proof status is separately reported. A fully satisfied learner-choice plan is not necessarily a good or fair sectioning distribution. No soft preferences or priority ranking are supported in this O1 contract.

## Executed synthetic cases

- **C0 (scale; fast profile):** 1,500 invented learners, six compulsory requests each, 9,000 requests, 18 subject families. The input has **zero** sections or blocks. CP-SAT selected six blocks and the code constructed **360 balanced sections** (20 per family, 25 members each), allocated all 9,000 requests and passed independent validation. The old *supplied* witness had 450 sections; this result is not copied. These portfolios are deliberately easy and the single-block scheme is a restriction; this is **not general 1,500-learner arbitrary sectioning performance**.
- **C1 (genuinely crossed choices):** Four subject families, 16 invented learners with three choices each, three blocks permitted. The family conflict graph has a four-clique and is not three-colourable. A multi-block family plan is generated successfully and independently validated. In the companion three-family triangle, restricting each family to only one section yields a CP-SAT proof of genuine flexible-profile infeasibility.
- **Negative tests:** zero search budget, impossible member bounds, too many distinct requests per learner, missing identifiers, duplicate requests, incompatible single-block graph and flexible request-limit refusal.

## Integration gates deliberately not included

The O1 `OptionDesignProblem` input currently does **not** include teachers, subject qualifications, teacher contracts, room sizes/availability, actual lesson counts, paired lessons, dated bell schedules or movement. O1 therefore cannot yet certify that a valid option plan can be *taught*. The next C2 handoff must add explicit curriculum/teacher/room feasibility and either reject or feed back invalid section layouts. Do not quietly claim a timetable is buildable merely because learner blocks are conflict-free.

School-scale multi-block strategies, subject families present in multiple keys, non-compulsory choices, class balancing, priority requests and realistic imports are further milestones. No real learner records belong in this public repository. Independent Grid schedules remain a non-negotiable user requirement; O1 is callable without running academic placement, exams or invigilation.

## Reproduction

```bash
python -m scripts.prepare_workspace
python -m pytest -q o1_tests
python -m scripts.run_o1_benchmarks
```

`o1-output/` contains synthetic request-only inputs, machine-readable validated results, a human-readable scorecard and the generated 1,500-learner options witness. No publication or external account is involved. Do not compare runtimes across environments without preserving CPU, Python/OR-Tools versions, seeds and explicit budgets.
