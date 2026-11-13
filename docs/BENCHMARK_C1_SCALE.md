# Benchmark C1 — demand-to-option *generation* (not a timetable)

This builds directly on the supplied-witness-only [C0 baseline](BENCHMARK_C0_SCOPE.md) and distinguishes the first real O1 generation from a contract representation test.

| Milestone | Actual test | Capability status |
|---|---|---|
| C0 supplied witness | 1,500 learner identities, 9,000 requests, 450 sections given in advance | Input / independent validation only |
| O1 C0 generated | Same 9,000 requests, **zero sections supplied**, output six blocks, 360 algorithm-created sections and 9,000 allocations | **Executed** with one-block-per-family restriction |
| O1 C1 crossed requests | Four families, 16 learners choosing three each; 3 permitted blocks; no prebuilt sections | **Executed** with multi-block family sections |
| C2 academic integration | Chosen blocks and class sizes checked against actual lesson durations, teachers, contracts, room eligibility and timetable conflicts | **NOT IMPLEMENTED** |
| C3 full institution | Variable electives, options, lesson placement and staff/room supply at 1,000–1,500 learners in the same solve/feedback loop | **NOT IMPLEMENTED** |
| C4 vendor feature/UI study | Licenced, de-identified reference datasets and completed user tasks vs ACTion / aSc | **NOT IMPLEMENTED** |

The generated 360-section C0 result uses a favourable synthetic structure (six partitions, a valid subject-colouring exists). It is not evidence that arbitrary 1,500-learner combinations are easy. A slower flexible profile is available for small and medium conflict cases but has a conservative default 2,500-request guard.

**Hard requirement for subsequent C2:** derive a feasibility certificate of staffing and room use for each section plan and maintain a lossless handoff to the C1 lesson-placement model. Section allocation, teaching timetable and separate examination/invigilation remain independently runnable modules; any joint solve is an explicit selection.
