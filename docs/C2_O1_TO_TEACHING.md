# Veni Grid — C2.0 O1-to-teaching feasibility (review candidate)

**Capability:** For an **accepted, unchanged O1 learner option plan**, generate
actual curriculum lesson placements and select suitably declared teachers and
classrooms using C1 CP-SAT. Preserve all original O1 learners, blocks and
sections. Return a checkable result and explicit constraint failures.

**Not included:** construction of a *different* O1 plan to repair staffing
shortfalls; complete 1,500-learner academic placement; school-wide conflict
certification; real qualification verification; duty/exam/invigilation edits;
quality optimisation, UI backend, persistence or publication.

## 1. Entry contract and non-negotiable boundaries

`C2Input` consists of a versioned accepted `AcceptedOptions` snapshot (`source`)
and explicit `SnapshotRef`; plus `C2Target`, which supplies the new academic
schedule ID/version, days and bell windows, independently declared learner,
teacher and room resources, institution-provided competency assertions,
per-subject teaching requirements, and per-block/per-occurrence start domains.
The input accepts **only `STANDALONE`** in this first profile. It does not load
other timetables automatically. A caller-provided `SnapshotRef` is a change
detection mechanism, **not a cryptographic approval or trusted authority
record**. Production acceptance, authorisation, a current-snapshot registry,
concurrent edits and publication require a later server-side implementation.

The original O1 plan is independently checked using `option_errors()`. The
existing `FlexibleOptionsRequest` / `build_flexible_handoff()` adapter
constructs forced learner-section enrollment requests and aligned block lessons.
Its independent `flexible_handoff_errors()` reverse checker must also pass.
C2 adds explicit teacher/room requirements and competency/continuity hard rules
on top of this **same** C1 input, not a second inferred enrollment plan.

All learners must be declared `PERSON` resources tagged `LEARNER`; all eligible
teachers `PERSON` tagged `TEACHER`; all eligible rooms `SPACE`, with explicit
capacities, location where known and relevant room-type tags (e.g. `LAB`).
Teacher credentials must explicitly assert the required subject competency and
include source provenance. These are **school-supplied assertions**, not checks
against SACE or any external professional registry. Dated credentials require an
actual dated calendar, so a cyclic timetable cannot silently certify expiry.

## 2. Teacher and classroom feasibility

For each section the curriculum specification declares its required occurrence
pattern, candidate teacher IDs, required competency, suitable room IDs and
required room tags. One qualified teacher and one exclusive suitable room are
chosen for each lesson. The room's numerical capacity must be at least the
number of learners allocated to that **specific O1 section**. The true room
capacity is enforced at **every** lesson event, not approximated by family size.

For the synchronous first profile, all sections sharing the same `(block,
occurrence_key)` must start together. Start domains explicitly name allowed day
IDs; they may not silently migrate to another calendar day. `SAME_START`
implements that synchronisation. `QUALIFICATION` requires the selected teacher
hold the required credential for the entire applicable lesson interval.
`RESOURCE_CONTINUITY` can require the same teacher across all occurrences of a
section; room continuity is separately optional. Teacher unavailability and
room double-booking are enforced by the existing C1 compiler/checker.

Before invoking expensive CP-SAT lesson placement, C2 independently computes
**maximum bipartite matching** among simultaneously required sections and
available qualified teachers, then among sections and suitable exclusive rooms.
If the maximum matching size is too small, `BLOCK_TEACHER_SHORTAGE` or
`BLOCK_CLASSROOM_SHORTAGE` identifies the actual section count and maximum
matchable count. This is stronger than a crude total room or teacher count: it
catches a bottleneck where several specialist sections all need the same small
subset of apparently available resources.

The matching proof concerns the **supplied fixed O1 sections under explicit
synchronous-block and exclusive-room requirements**. A different O1 section
plan may avoid the bottleneck. C2 currently refuses `CUMULATIVE` shared rooms
rather than falsely treating halls as exclusive; an explicit shared-venue C2
profile with seat-unit/room-use accounting will be a later extension.

If static matching passes, C1 CP-SAT places events in time and chooses actual
teachers and rooms. A returned candidate is rechecked using `review_core()`.
Only `FEASIBLE` plus `independent_hard_validation=PASSED` returns assignments.
A solver-proved contradiction is `INFEASIBLE` under `FIXED_O1_C2`; exhausted
search remains `UNKNOWN` and cannot become a general school-wide impossibility.

## 3. Supported and unsupported patterns

**Supported first slice:** accepted O1 choice allocations (including subject
families split across different option blocks); synchronous sections per
block/occurrence; multiple explicit occurrences per subject, including doubles;
compulsory teacher competency assertions, appropriate lab/classroom tags and
seat counts; availability; same teacher across a section; optional room
continuity; hard C1 constraints; a standalone academic horizon of abstract
cycle days or explicit dated days.

**Requires a later profile:** O1 re-sectioning or block re-colouring on resource
failure; generating lesson occurrence patterns from DBE/CAPS data; multi-site
travel requirements from unknown locations; shared cumulative halls; mixed
bell/calendar exceptions beyond the supplied validated windows; cancellation
and substitution; qualification lookup against an external authoritative
registry; teacher employment allocations/contract load balancing; quality
optimisation; production role permissions and publication; binding other live
schedules as read-only commitments. Such features must **fail closed** if
requested where unsupported, not quietly disappear from a feasibility claim.

## 4. Executed synthetic examples (13 November 2026)

### C2 positive: crossed choices, real teacher/room placement

Starting from actual O1-generated C1 crossed-choice input with 16 invented
learners, 48 requests and 9 sections across 3 blocks, C2 created 18 curriculum
lesson occurrences over two cycle days. `SAME_START` bound sections in each
block, `QUALIFICATION` enforced one appropriate teacher per subject and
`RESOURCE_CONTINUITY` required that teacher across both days. A named lab-only
Physical Sciences analogue used two consecutive windows per occurrence.
C1 CP-SAT generated all **18 lesson assignments**, choosing **four qualified
teachers** and **three rooms** (two classrooms and one lab). Independent hard
validation passed. The source O1 allocation fingerprint was unchanged.
See `c2-output/c2-generated-teaching-grid.md`, which is extracted from the
actual CP-SAT output, not an illustrative UI mockup.

### C2 intentionally impossible tests

- Remove the Science teacher's verified competency assertion: static qualified
  teacher matching proves the section cannot be staffed.
- Declare an unqualified candidate teacher: still refused as no suitable
  qualified assignment exists.
- Remove or undersize the Science laboratory, or supply too few classrooms:
  maximum matching proves a specialist/seat/exclusive-room shortage.
- Make the Science teacher unavailable for every candidate time window on day 2:
  static matching passes but **real C1 CP-SAT proves** the full time-placement
  problem infeasible.
- Require teacher continuity across two days, with no one person available both
  days: infeasible. Removing that *optional explicit continuity requirement*
  permits two correctly qualified teachers on different days.
- Expire a dated qualification before day two: C1 refuses any assignment that
  uses that teacher outside the credential interval.
- Tamper with the accepted O1 fingerprint, accepted state or day bindings:
  invalid input. Use shared cumulative rooms: unsupported, not falsely
  marked impossible.

### C2 large-plan resource feedback (preflight only)

O1's **generated** 1,500-learner / 9,000-request / 360-section plan needs
**60 simultaneous sections** in each of its six synchronous blocks under the
first C2 occurrence profile. Even with adequate teacher credentials, a
hypothetical school with 30 suitable exclusive rooms can place at most 30 of
60 sections: `BLOCK_CLASSROOM_SHORTAGE`, scoped `FIXED_O1_C2`.
A second controlled fixture provides 60 rooms but only 30 qualified teachers
for each 60-section block: `BLOCK_TEACHER_SHORTAGE`. These are conclusive
simple supply bottlenecks for the provided fixed plan, **not a full 1,500-learner
lesson-optimisation run or proof that alternate option layouts are impossible**.

## 5. Reproduction and CI

From the checked-out GitHub branch on Python 3.13 with reviewed dependencies:

```bash
python -m scripts.prepare_workspace
python -m pytest -q tests tests_solver quality_tests q2_tests q3_tests o1_tests c2_tests
python -m scripts.run_c2_probes
```

The first C2 local increment passed **531 tests**: 508 retained + 23 new.
C2 output includes machine-readable positive and negative results, the actual
teaching timetable JSON, C1 input JSON, and a readable 18-event table. CI
asserts these values again from a **fresh checkout**, without accessing a school
system or using personal/sensitive data. A successful test never grants
publication permission.

## 6. Next mathematical gate — feedback, not overclaiming

Once C2 identifies a teacher or venue shortage, a future constrained O1
rerunner must decide whether to add, shrink, split, re-block or reject sections
and then **retest all relevant learner choices and lesson placements**. It must
not alter an accepted/published plan without a separate approval and scoped
before/after review. Only then can we claim a closed joint options/staff/rooms
academic scheduling loop.
