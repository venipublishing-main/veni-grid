# C1 implementation boundaries

## Scope and authority

C1 runtime version 0.1.0 consumes schema `1.0.0-rc1`. The reviewed input schema and solver behaviour are unchanged by this repository import. The current goal is reliable hard-feasibility generation and independent validation, not a production application.

An Activity declares demand. An Event is one schedulable occurrence. An Offering is a selectable bundle of events. ParticipationRequests express learner choices; enrollment assignments are separate from event placements. Requirements select exact quantities of eligible resources. Resource groups can contain nested people/groups. Capacity consumption and participant counts are distinct.

C1 solves one supplied model. The independent-job contracts distinguish STANDALONE, RESPECT_EXISTING and explicitly authorised JOINT declarations, but those declarations are not a production job executor or a joint solver. A combined display is not permission to change multiple schedules.

## Hard rules compiled

`RESOURCE_BLACKOUT`, `EXCLUDE_RESOURCE_FROM_EVENT`, `MAX_DAILY_MINUTES`, `WORKLOAD_BALANCE`, `ACTIVITY_SPREAD`, `EVENT_BEFORE`, `EVENT_NOT_SAME_TIME`, `EVENT_SAME_START`, `QUALIFICATION`, `RESOURCE_CONTINUITY`, `TRAVEL_TIME`.

Demand, active-offering rules, placement domains, resource eligibility, membership, exclusivity/capacity and locks also constrain every generated result. Rule strengths are HARD/SOFT; enabled is separate; locks are explicit hard restrictions.

Actual start/end intervals are authoritative across bell schedules. Window-duration doubles require an allowed consecutive chain; elapsed occupancy can include an allowed break while teaching minutes exclude it. Directed travel applies between actual consecutive events within a local day. Missing required routes/locations are refused rather than assumed zero. Date-limited credentials require the relevant actual dates and must cover the whole occurrence.

Continuity compares resource sets, not order, across active events. Eligibility does not imply continuity. Known learners count individually for clashes and room attendance; an unspecified cohort's size must not be invented.

## Status contract

- `FEASIBLE`: a generated candidate passed independent hard-rule validation for the supplied supported model.
- `INFEASIBLE`: CP-SAT proved the compiled supported model contradictory. The current runtime does not extract minimal conflict sets.
- `UNKNOWN`: search reached no conclusion, including a zero-time budget.
- `INVALID_INPUT`: canonical parsing/reference/structural errors.
- `UNSUPPORTED`: a requested mode, scope or required operating fact is outside this backend profile.
- `ERROR`: compilation/backend failure or solver/checker disagreement; a disagreeing candidate is withheld.

A raw CP-SAT `OPTIMAL` status for a satisfaction problem is retained for audit, not advertised as a quality-optimal school timetable. Every result records soft scoring `NOT_PERFORMED`, quality optimality `NOT_ASSESSED` and publication permission `NOT_GRANTED`.

Only FEASIBILITY is implemented. Enabled soft rules, objective IDs and soft requests are reported as unscored; they are not quietly presented as optimised. OPTIMISE, REPAIR, DIAGNOSE and COMPARE modes are refused. A baseline solution identifier does not authorise implicit repair.

## Independent checks and handoffs

`veni_grid_solver/compiler.py` compiles the typed input; it does not load a saved witness or use the independent placement/rule checker to search. The runtime validates the returned candidate via the contract review boundary before returning success. Small exhaustive-oracle comparisons and deliberately corrupt extraction tests guard this separation.

Options-to-lessons adapters preserve accepted section membership and curriculum demand. Equal-pattern blocks and explicitly mapped unequal-frequency occurrences remain separate supported handoff profiles. These adapters do not automatically discover option blocks.

Fixed-exam handoffs preserve dates, venues and source-owned room reservations. Invigilation contributes staff claims, not duplicate room bookings. Coverage contracts represent relief and extra-time supervision, but a segmented coverage optimiser is not implemented. Manual/normalised source facts are supported contracts, not native vendor-file importers.

The recurrence bridge projects a complete candidate onto explicit dates, handles configured closures/changed bells/cancellations, derives complete claims and rechecks them. A changed source calls for revalidation, not automatic upstream edits or publication. Fingerprints and pure scope checks are not authentication or atomic database transactions.

## Explicit prototype limits

The compiler guards at 2,000 events, 50,000 candidate starts, 50,000 role edges, 250,000 expanded resource/start intervals and 100 possible events per traveller/day. These are refusal thresholds, not demonstrated school-scale capacity or service guarantees.

Overnight lesson windows, arbitrary recurrence, effective-dated memberships, automatic option/section construction with staffing/rooms, advanced scoring/repair, transactional linked-job publication, native ACTion/aSc/Excel/PDF importers and the UI remain outside the delivered runtime. The synthetic 1,500-learner option example is representation/validation evidence, not a 1,500-learner solver benchmark.
