"""v0.4 placement extension: option-block synchronisation is a typed HARD rule.

The existing 0.3 dialect is deliberately preserved. Explicit conversion below
passes its supported rules to the retained checker, and checks SAME_START here.
No scheduling or optimisation is performed.
"""
from __future__ import annotations
from typing import Annotated, Literal
from pydantic import Field
from .models import (ID, SchedulingProblem, SchedulingSolution, RuleBase, RuleStrength,
    ResourceBlackout, ExcludeFromEvent, MaxDailyMinutes, WorkloadBalance,
    ActivitySpread, EventOrdering, EventNotTogether)
from .validation import problem_issues, witness_issues, window_placement, ContractIssue


class SameStart(RuleBase):
    kind: Literal["EVENT_SAME_START"] = "EVENT_SAME_START"
    event_ids: list[ID] = Field(min_length=2)


RuleV04 = Annotated[ResourceBlackout | ExcludeFromEvent | MaxDailyMinutes | WorkloadBalance
    | ActivitySpread | EventOrdering | EventNotTogether | SameStart, Field(discriminator="kind")]


class PlacementProblem(SchedulingProblem):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    constraints: list[RuleV04] = Field(default_factory=list)


class PlacementWitness(SchedulingSolution):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"


def _base(p: PlacementProblem) -> SchedulingProblem:
    raw = p.model_dump(mode="json")
    raw["schema_version"] = "0.3.0-draft"
    raw["constraints"] = [c for c in raw["constraints"] if c["kind"] != "EVENT_SAME_START"]
    return SchedulingProblem.model_validate(raw)


def placement_problem_errors(p: PlacementProblem) -> list[ContractIssue]:
    errors = problem_issues(_base(p))
    events = {e.id for e in p.events}
    all_entities = (p.days + p.windows + p.resources + p.activities + p.events + p.offerings
                    + p.participation_requests + p.constraints + p.objectives + p.locks)
    if len({x.id for x in all_entities}) != len(all_entities):
        errors.append(ContractIssue("DUPLICATE_GLOBAL_ID", "All v0.4 rule IDs must also be unique"))
    for c in p.constraints:
        if isinstance(c, SameStart):
            if len(set(c.event_ids)) != len(c.event_ids) or not set(c.event_ids) <= events:
                errors.append(ContractIssue("INVALID_SYNCHRONISATION", c.id))
            if c.strength != RuleStrength.HARD:
                errors.append(ContractIssue("UNSUPPORTED_SOFT_SYNCHRONISATION", c.id))
    return errors


def placement_witness_errors(p: PlacementProblem, w: PlacementWitness) -> list[ContractIssue]:
    errors = placement_problem_errors(p)
    if errors: return errors
    base_p = _base(p)
    raw_w = w.model_dump(mode="json"); raw_w["schema_version"] = "0.3.0-draft"
    errors.extend(witness_issues(base_p, SchedulingSolution.model_validate(raw_w)))
    assignments = {a.event_id: a for a in w.event_assignments}
    events = {e.id: e for e in p.events}
    for c in p.constraints:
        if not isinstance(c, SameStart) or not c.enabled: continue
        actual = []
        for eid in c.event_ids:
            if eid not in assignments: continue  # optional-event activation checked by base validator
            try:
                day, start, _, _ = window_placement(base_p, events[eid], assignments[eid].start_window_id)
                actual.append((day, start))
            except ValueError:
                continue  # invalid placement already reported above
        if len(set(actual)) > 1:
            errors.append(ContractIssue("BLOCK_SYNCHRONISATION_BROKEN", c.id))
    return errors
