# Benchmark C2 — turning option requests into a teachable timetable

| Stage | Source and result | Evidence status |
|---|---|---|
| C0 / O1 | Generate 6 option blocks, 360 sections, 9,000 satisfied requests from 1,500 invented learners; no pre-created plan | O1 CP-SAT + independent option checker, PASS |
| C2-small positive | Take a flexible 9-section / 48-request O1-generated plan and assign 18 actual lesson events using subject-qualified teachers and fitting rooms, including doubles and block synchronisation | Real C1 CP-SAT + independent hard checker, PASS |
| C2-small hard negatives | No qualified staff, lab absent/too small, room shortage, teacher unavailable, dated qualification expired, teacher-continuity conflict | Matching certificates or C1 infeasibility proofs, PASS |
| C2-1500/rooms | 60 synchronous sections per block but only 30 suitable exclusive rooms; no C1 search attempted | Preflight maximum matching, 30/60, FIXED_O1_C2 |
| C2-1500/teachers | 60 synchronous sections per block and 60 suitable rooms, but only 30 qualified teachers | Preflight maximum matching, 30/60, FIXED_O1_C2 |
| C2 revised O1 feedback | Automatically revise option layout with teacher/room/section constraints, preserving all learner choices or explaining losses | **NOT IMPLEMENTED** |
| C3 complete school | Real-shaped 1,500-learner lesson-frequency, teacher/room/subject allocation over full 10-day cycle and quality optimisation | **NOT IMPLEMENTED** |
| C4 vendor / UI evaluation | Licensed and de-identified import comparison plus human-timetabler workflow studies | **NOT IMPLEMENTED** |

The positive example is a partial two-day timetable and the 1,500-learner cases
are **static resource-capacity feasibility checks**, not a large joint
optimisation run. All data and names are invented.

C2 does not load examinations, invigilation or duties. Those schedules remain
independent and require explicit, read-only or joint user selection before
being included as constraints. The first C2 profile accepts `STANDALONE` only.
