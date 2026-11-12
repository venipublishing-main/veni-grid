"""Consolidated candidate placement profile, version 1.0.0-rc1.

This module checks supplied assignments. It does NOT solve, prove infeasibility,
certify optimality, publish, or authenticate any resource qualification.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from .models import (
    ID, Resource, ResourceKind, RuleBase, RuleStrength, ResourceBlackout,
    ExcludeFromEvent, MaxDailyMinutes, WorkloadBalance, ActivitySpread,
    EventOrdering, EventNotTogether, SchedulingSolution,
)
from .placement_v04 import (
    PlacementProblem, PlacementWitness, SameStart,
    placement_problem_errors, placement_witness_errors,
)
from .primitives import ContractModel, Positive, NonNegative, Interval, Finding
from .calendar_projection import resolve_local
from .validation import window_placement

VERSION = "1.0.0-rc1"


class LocatedResource(Resource):
    location_id: ID | None = None
    travel_profile: str = Field(default="STANDARD", min_length=1)


class Location(ContractModel):
    id: ID
    label: str


class Credential(ContractModel):
    """A supplied competency assertion, not a verified professional registration."""
    id: ID
    resource_id: ID
    competency: ID
    valid_during: Interval | None = None
    source_ref: str = Field(min_length=1)


class TravelArc(ContractModel):
    from_location: ID
    to_location: ID
    profile: str = Field(default="STANDARD", min_length=1)
    minutes: NonNegative


class AllocationRef(ContractModel):
    event_id: ID
    requirement_id: ID


class QualificationRule(RuleBase):
    kind: Literal["QUALIFICATION"] = "QUALIFICATION"
    strength: Literal[RuleStrength.HARD] = RuleStrength.HARD
    allocations: list[AllocationRef] = Field(min_length=1)
    all_of: list[ID] = Field(min_length=1)


class ContinuityRule(RuleBase):
    kind: Literal["RESOURCE_CONTINUITY"] = "RESOURCE_CONTINUITY"
    strength: Literal[RuleStrength.HARD] = RuleStrength.HARD
    allocations: list[AllocationRef] = Field(min_length=2)
    semantics: Literal["SAME_SET_WHEN_ACTIVE"] = "SAME_SET_WHEN_ACTIVE"


class TravelRule(RuleBase):
    kind: Literal["TRAVEL_TIME"] = "TRAVEL_TIME"
    strength: Literal[RuleStrength.HARD] = RuleStrength.HARD
    resource_ids: list[ID] = Field(min_length=1)
    scope: Literal["WITHIN_LOCAL_DAY"] = "WITHIN_LOCAL_DAY"


CoreRule = Annotated[
    ResourceBlackout | ExcludeFromEvent | MaxDailyMinutes | WorkloadBalance |
    ActivitySpread | EventOrdering | EventNotTogether | SameStart |
    QualificationRule | ContinuityRule | TravelRule,
    Field(discriminator="kind"),
]


class CoreProblem(PlacementProblem):
    schema_version: Literal["1.0.0-rc1"] = VERSION
    resources: list[LocatedResource] = Field(min_length=1)
    constraints: list[CoreRule] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    credentials: list[Credential] = Field(default_factory=list)
    travel_arcs: list[TravelArc] = Field(default_factory=list)


class CoreWitness(SchedulingSolution):
    schema_version: Literal["1.0.0-rc1"] = VERSION


def legacy_problem(p: CoreProblem) -> PlacementProblem:
    raw = p.model_dump(mode="json")
    for key in ("locations", "credentials", "travel_arcs"):
        raw.pop(key)
    for r in raw["resources"]:
        r.pop("location_id"); r.pop("travel_profile")
    raw["constraints"] = [r for r in raw["constraints"] if r["kind"] not in
                          {"QUALIFICATION", "RESOURCE_CONTINUITY", "TRAVEL_TIME"}]
    raw["schema_version"] = "0.4.0-draft"
    return PlacementProblem.model_validate(raw)


def legacy_witness(w: CoreWitness) -> PlacementWitness:
    raw = w.model_dump(mode="json"); raw["schema_version"] = "0.4.0-draft"
    return PlacementWitness.model_validate(raw)


def promote_placement(p: PlacementProblem, w: PlacementWitness | None = None):
    """Explicit, lossless additive migration; no qualification or route is guessed."""
    raw = p.model_dump(mode="json"); raw["schema_version"] = VERSION
    out = CoreProblem.model_validate(raw)
    if w is None:
        return out
    wr = w.model_dump(mode="json"); wr["schema_version"] = VERSION
    return out, CoreWitness.model_validate(wr)


def core_problem_errors(p: CoreProblem) -> list[Finding]:
    # Re-parse to catch in-process mutations that bypassed Pydantic assignment checks.
    p = CoreProblem.model_validate(p.model_dump(mode="json"))
    errors = [Finding(code=e.code, detail=e.message) for e in placement_problem_errors(legacy_problem(p))]
    def bad(code: str, detail: str): errors.append(Finding(code=code, detail=detail))
    rs = {r.id: r for r in p.resources}; es = {e.id: e for e in p.events}
    locs = {x.id for x in p.locations}
    all_ids = [x.id for xs in (p.days, p.windows, p.resources, p.activities, p.events,
               p.offerings, p.participation_requests, p.constraints, p.objectives, p.locks,
               p.locations, p.credentials) for x in xs]
    if len(all_ids) != len(set(all_ids)): bad("DUPLICATE_GLOBAL_ID", "Core entity IDs")
    if len({d.ordinal for d in p.days}) != len(p.days): bad("DUPLICATE_DAY_ORDINAL", "Days")
    if any(d.date is None for d in p.days) and any(d.date is not None for d in p.days):
        bad("MIXED_CALENDAR_KIND", "A placement horizon must be fully cyclic or fully dated")
    dated = sorted(p.days, key=lambda d: d.ordinal)
    if all(d.date is not None for d in dated) and [d.date for d in dated] != sorted(d.date for d in dated):
        bad("DATE_ORDER_MISMATCH", "Day ordinals must follow real dates")
    for r in p.resources:
        if r.location_id is not None and (r.kind != ResourceKind.SPACE or r.location_id not in locs):
            bad("INVALID_SPACE_LOCATION", r.id)
    arcs = [(a.profile, a.from_location, a.to_location) for a in p.travel_arcs]
    if len(arcs) != len(set(arcs)): bad("DUPLICATE_TRAVEL_ARC", "Travel table")
    for a in p.travel_arcs:
        if a.from_location not in locs or a.to_location not in locs:
            bad("UNKNOWN_TRAVEL_LOCATION", str(a))
        if a.from_location == a.to_location and a.minutes != 0:
            bad("INVALID_SELF_TRAVEL", "Same location travel is zero; setup is a separate future rule")
    for c in p.credentials:
        if c.resource_id not in rs: bad("UNKNOWN_CREDENTIAL_RESOURCE", c.id)
    for rule in p.constraints:
        if isinstance(rule, (QualificationRule, ContinuityRule)):
            refs = [(a.event_id, a.requirement_id) for a in rule.allocations]
            if len(refs) != len(set(refs)): bad("DUPLICATE_ALLOCATION_REF", rule.id)
            found = []
            for eid, qid in refs:
                e = es.get(eid)
                q = next((q for q in e.requirements if q.id == qid), None) if e else None
                if q is None: bad("UNKNOWN_ALLOCATION_REF", f"{rule.id}: {eid}/{qid}")
                else: found.append(q)
            if isinstance(rule, QualificationRule) and len(set(rule.all_of)) != len(rule.all_of):
                bad("DUPLICATE_COMPETENCY", rule.id)
            if isinstance(rule, ContinuityRule) and len({(q.quantity, q.kind) for q in found}) > 1:
                bad("INCOMPATIBLE_CONTINUITY", rule.id)
        if isinstance(rule, TravelRule):
            if len(rule.resource_ids) != len(set(rule.resource_ids)): bad("DUPLICATE_TRAVELLER", rule.id)
            for rid in rule.resource_ids:
                if rid not in rs or rs[rid].kind != ResourceKind.PERSON: bad("INVALID_TRAVELLER", rid)
    return errors


def expand_resources(p: CoreProblem, rid: str) -> set[str]:
    rs = {r.id: r for r in p.resources}
    # Only call after structural validation (including membership-cycle checks).
    r = rs[rid]
    result = {rid}
    if r.kind == ResourceKind.GROUP:
        for child in r.member_ids: result |= expand_resources(p, child)
    return result


class ResolvedUse(ContractModel):
    occurrence_id: ID
    event_id: ID
    day_key: str
    start_minute: int
    end_minute: int
    interval: Interval | None = None
    work_minutes: NonNegative
    resource_ids: list[ID]
    allocations: dict[str, list[ID]]
    location_id: ID | None = None


def resolved_use(p: CoreProblem, w: CoreWitness, assignment, *, occurrence_id=None,
                 day_key=None, start=None, end=None, interval=None, work_minutes=None) -> ResolvedUse:
    """Derive participants and role use from a full validated candidate, never claims supplied by a caller."""
    e = next(x for x in p.events if x.id == assignment.event_id)
    day, s, t, work = window_placement(p, e, assignment.start_window_id)
    requests = {q.id: q for q in p.participation_requests}
    users = set()
    for rid in e.fixed_participant_ids: users |= expand_resources(p, rid)
    for a in w.enrollment_assignments:
        if e.offering_id in a.offering_ids: users |= expand_resources(p, requests[a.request_id].participant_id)
    allocs = {a.requirement_id: list(a.resource_ids) for a in assignment.resource_allocations}
    for ids in allocs.values():
        for rid in ids: users |= expand_resources(p, rid)
    spaces = [r for r in p.resources if r.id in users and r.kind == ResourceKind.SPACE]
    location = spaces[0].location_id if spaces and all(r.location_id == spaces[0].location_id for r in spaces) else None
    if interval is None:
        d = next(d for d in p.days if d.id == day)
        if d.date:
            interval = Interval(start=resolve_local(d.date, s, p.timezone), end=resolve_local(d.date, t, p.timezone))
    return ResolvedUse(occurrence_id=occurrence_id or e.id, event_id=e.id,
                       day_key=day_key or day, start_minute=s if start is None else start,
                       end_minute=t if end is None else end, interval=interval,
                       resource_ids=sorted(users), work_minutes=work if work_minutes is None else work_minutes, allocations=allocs, location_id=location)


def operational_errors(p: CoreProblem, uses: list[ResolvedUse]) -> list[Finding]:
    """Internal evaluation of new rules; uses must come from the checked adapters."""
    errors = []; rs = {r.id: r for r in p.resources}
    def bad(code, detail): errors.append(Finding(code=code, detail=detail))
    arcs = {(a.profile, a.from_location, a.to_location): a.minutes for a in p.travel_arcs}
    for rule in p.constraints:
        if not rule.enabled: continue
        if isinstance(rule, QualificationRule):
            for ref in rule.allocations:
                for use in [u for u in uses if u.event_id == ref.event_id]:
                    for rid in use.allocations.get(ref.requirement_id, []):
                        for code in rule.all_of:
                            creds = [c for c in p.credentials if c.resource_id == rid and c.competency == code]
                            valid = False; needs_date = False
                            for c in creds:
                                if c.valid_during is None: valid = True; break
                                if use.interval is None: needs_date = True; continue
                                iv, cv = use.interval, c.valid_during
                                if cv.start.astimezone(timezone.utc) <= iv.start.astimezone(timezone.utc) and iv.end.astimezone(timezone.utc) <= cv.end.astimezone(timezone.utc):
                                    valid = True; break
                            if not valid:
                                bad("QUALIFICATION_NEEDS_DATES" if needs_date and use.interval is None else "QUALIFICATION_MISSING_OR_EXPIRED",
                                    f"{rule.id}/{use.occurrence_id}/{rid}/{code}")
        elif isinstance(rule, ContinuityRule):
            selections = []
            for ref in rule.allocations:
                selections += [frozenset(u.allocations[ref.requirement_id]) for u in uses
                               if u.event_id == ref.event_id and ref.requirement_id in u.allocations]
            if len(set(selections)) > 1: bad("RESOURCE_CONTINUITY_BROKEN", rule.id)
        elif isinstance(rule, TravelRule):
            for rid in rule.resource_ids:
                by_day = defaultdict(list)
                for use in uses:
                    if rid in use.resource_ids: by_day[use.day_key].append(use)
                for day, group in by_day.items():
                    group.sort(key=lambda u: (u.interval.start.astimezone(timezone.utc) if u.interval else u.start_minute, u.occurrence_id))
                    for left, right in zip(group, group[1:]):
                        if left.location_id is None or right.location_id is None:
                            bad("TRAVEL_LOCATION_UNRESOLVED", f"{rid}/{left.occurrence_id}/{right.occurrence_id}"); continue
                        if left.interval and right.interval:
                            gap = (right.interval.start.astimezone(timezone.utc)-left.interval.end.astimezone(timezone.utc)).total_seconds()/60
                        else: gap = right.start_minute-left.end_minute
                        edge = (rs[rid].travel_profile, left.location_id, right.location_id)
                        required = 0 if left.location_id == right.location_id else arcs.get(edge)
                        if required is None: bad("TRAVEL_ROUTE_UNRESOLVED", f"{rid}/{edge}")
                        elif gap < required: bad("TRAVEL_GAP_TOO_SHORT", f"{rid}: {gap:g} available, {required} required ({left.occurrence_id}->{right.occurrence_id})")
    return errors


def core_witness_errors(p: CoreProblem, w: CoreWitness, *, defer_dated_credentials=False) -> list[Finding]:
    p = CoreProblem.model_validate(p.model_dump(mode="json"))
    w = CoreWitness.model_validate(w.model_dump(mode="json"))
    errors = core_problem_errors(p)
    if errors: return errors
    errors += [Finding(code=e.code, detail=e.message) for e in placement_witness_errors(legacy_problem(p), legacy_witness(w))]
    if errors: return errors
    uses = [resolved_use(p, w, a) for a in w.event_assignments]
    # Expand nested groups and learners for all resource workloads, not only role holders.
    for rule in p.constraints:
        if isinstance(rule, MaxDailyMinutes) and rule.enabled and rule.strength == RuleStrength.HARD:
            for rid in rule.resource_ids:
                for day in {u.day_key for u in uses}:
                    minutes = sum(u.work_minutes for u in uses if u.day_key == day and rid in u.resource_ids)
                    if minutes > rule.limit_minutes:
                        errors.append(Finding(code="DAILY_LOAD_VIOLATED", detail=f"{rule.id}/{rid}/{day}"))
    # Runtime conformance regression (2026-11-12): intermediate nested groups
    # are occupied resources too. The legacy checker expanded only PERSONs for
    # availability; do not let a parent group conceal its subgroup's blackout.
    windows = {win.id: win for win in p.windows}
    for use in uses:
        for resource in p.resources:
            if resource.id not in use.resource_ids:
                continue
            for wid in resource.unavailable_window_ids:
                win = windows[wid]
                if use.day_key == win.day_id and use.start_minute < win.end_minute and win.start_minute < use.end_minute:
                    errors.append(Finding(code="RESOURCE_UNAVAILABLE", detail=f"{use.event_id}/{resource.id}/{wid}"))
        for rule in p.constraints:
            if isinstance(rule, ResourceBlackout) and rule.enabled and rule.strength == RuleStrength.HARD and rule.resource_id in use.resource_ids:
                for wid in rule.window_ids:
                    win = windows[wid]
                    if use.day_key == win.day_id and use.start_minute < win.end_minute and win.start_minute < use.end_minute:
                        errors.append(Finding(code="BLACKOUT_VIOLATED", detail=f"{rule.id}/{use.event_id}/{rule.resource_id}"))
    for resource in p.resources:
        if resource.sharing_mode != "EXCLUSIVE": continue
        group = [u for u in uses if resource.id in u.resource_ids]
        for i, left in enumerate(group):
            for right in group[i+1:]:
                if left.day_key == right.day_key and left.start_minute < right.end_minute and right.start_minute < left.end_minute:
                    errors.append(Finding(code="EXPANDED_RESOURCE_OVERLAP", detail=f"{resource.id}/{left.event_id}/{right.event_id}"))
    if defer_dated_credentials:
        # Only the recurring bridge may defer; it MUST check each resulting dated occurrence.
        errors += [e for e in operational_errors(p, uses) if e.code != "QUALIFICATION_NEEDS_DATES"]
    else: errors += operational_errors(p, uses)
    # Old tuple-day comparison did not enforce a gap spanning a day boundary.
    by_id = {u.event_id: u for u in uses}; ords = {d.id: d.ordinal for d in p.days}
    for r in p.constraints:
        if isinstance(r, EventOrdering) and r.enabled and r.strength == RuleStrength.HARD:
            a, b = by_id.get(r.earlier_event_id), by_id.get(r.later_event_id)
            if a is not None and b is not None:
                gap = ((b.interval.start.astimezone(timezone.utc)-a.interval.end.astimezone(timezone.utc)).total_seconds()/60
                       if a.interval and b.interval else ords[b.day_key]*1440+b.start_minute-ords[a.day_key]*1440-a.end_minute)
                if gap < r.minimum_gap_minutes: errors.append(Finding(code="ORDER_GAP_TOO_SHORT", detail=r.id))
    return errors
