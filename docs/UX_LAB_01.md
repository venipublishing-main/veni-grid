# Veni Grid — UX Lab 01: Timetable Workbench

**Status:** interaction prototype only; no real scheduling actions, accounts, persistence or school information. The sample uses synthetic labels and the Q1/Q2 Benchmark B penalty figures to explore design hierarchy.

## Product boundary

One shared scheduling core, **separate optional timetables**. A school can open academic, examinations, invigilation, duties, sport or room scheduling independently. A link to a published timetable supplies read-only constraints by default. Joint changes are explicit, scoped and reviewed; a combined view never silently enables a combined solve.

## Primary screens

1. **Timetable Home** — recent independently versioned drafts, organisation, module chooser, import/update warning, quick new timetable, working state.
2. **Setup and Imports** — human-first teacher/subject/class/room tables, capacity and frequency checks, source-column mapping, unmatched rows, provenance and undoable staged import. Never expose canonical JSON as the primary teacher-facing interaction.
3. **Options and Sections** — teacher/course supply, learner choice demand, option blocks, capacity bands, unallocated requests, proposed class sizes, no-override summaries. Deliberately separate section creation from actual lesson placement.
4. **Rules** — plain-language searchable constraint catalogue, HARD/SOFT/LOCK source and scope, impact preview, templates with advanced fields. AI only interprets typed rules; deterministic validation owns truth.
5. **Generate** — distinguish parsing, preflight, FEASIBILITY, optimisation tiers, independent validation and publication. Label INFEASIBLE only for proof and UNKNOWN for budget exhaustion. Show an independently validated incumbent even when a quality tier is unproved.
6. **Workbench** — perspectives by class, teacher, room and learner; zoom and pan inside its aperture; search, keyboard focus, contextual reason panel, live move validation, explicit locks, candidate A/B comparison and safe undo/redo. No solver logic in UI.
7. **Review / Publish / Repair** — compare Q1/Q2 policy fingerprints, precise constraints and score contributions; versioned publish approval; source stale alerts; scoped repair whose before/after diff is reviewable. Publication is a separate permissioned operation.

## Current interactive prototype

Open `ux_lab/grid-workbench.html` in any browser. It is **standalone HTML**: module navigation, new local draft, class/teacher/room perspectives, candidate A/B selection, search, cell selection, inspect panel, local lock button, optional change highlighting and timetable-aperture zoom are working demonstrations. All data is invented and the grid placements are illustrative, **not the real C1/Q2 benchmark candidate JSON**. The numeric 2,900→2,380 example is anchored to tested synthetic Q2 scoring.

### Human-factors and responsiveness

- The timetable itself scrolls independently; navigation and inspector are not dragged with it.
- A clearly visible prototype warning separates UI simulation from live scheduling.
- Keyboard focus is visible; relevant controls have labels and interact with a mouse or keyboard. Selected lesson inspector remains intelligible without a timetable colour legend.
- Mobile collapses navigation and moves inspector below the timetable; staff will usually review large master schedules on desktop.
- The most useful actionable item is shown near the selected lesson rather than forcing a deep menu or opaque constraint code.

## Testing against ACTion and aSc

Run timed real-user tasks on comparable *synthetic or authorised* data: import and map a school dataset; reconcile a learner option conflict; set a nuanced teacher rule; diagnose a genuinely impossible schedule; and repair one published invigilation duty without modifying examinations. Measure completion time, mistakes, reliance on training, discoverability, explanation correctness, undo/recovery and confidence. Avoid unverified claims that Grid is already easier or better.

## Before using a production UI

Connect only to explicitly versioned API and independently validated result objects. Never present mock penalty values, a simulated lock or a local draft as a committed timetable. Add accessible keyboard move alternatives, honest ARIA state, server-side authorisation, model hash/stale checks, audit events, safe concurrent editing and protected-person-data handling before real school data is accepted.
