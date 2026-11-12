"""Contract-level independent structural and witness validation.

NOT a feasibility solver. A successful witness shows the proposed contract can
express a legal example. It does not prove modelling completeness or optimality.
Unsupported HARD rules fail closed; no hard rule is silently ignored.
"""
from __future__ import annotations

from collections import defaultdict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from .primitives import CapacityResource, ResourceClaim, Interval, usage_errors

from .models import (
    SchedulingProblem, SchedulingSolution, RuleStrength, ResourceKind,
    WindowDuration, WorkloadBalance, ActivitySpread, EventOrdering,
    EventNotTogether, MaxDailyMinutes, ResourceBlackout, ExcludeFromEvent,
)


@dataclass(frozen=True)
class ContractIssue:
    code: str
    message: str

    def __str__(self):
        return f"{self.code}: {self.message}"


def problem_issues(p: SchedulingProblem) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    def bad(code, message):
        issues.append(ContractIssue(code, message))

    collections = {
        "days": p.days, "windows": p.windows, "resources": p.resources,
        "activities": p.activities, "events": p.events, "offerings": p.offerings,
        "participation_requests": p.participation_requests, "constraints": p.constraints,
        "objectives": p.objectives, "locks": p.locks,
    }
    for title, items in collections.items():
        ids = [x.id for x in items]
        if len(ids) != len(set(ids)):
            bad("DUPLICATE_ID", f"Duplicate ID in {title}")
    global_ids = [x.id for items in collections.values() for x in items]
    if len(global_ids) != len(set(global_ids)):
        bad("DUPLICATE_GLOBAL_ID", "IDs must be unique across all entity types")

    try:
        ZoneInfo(p.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        bad("BAD_TIMEZONE", f"Not an IANA timezone: {p.timezone}")
    dates = [d.date for d in p.days if d.date is not None]
    if len(dates) != len(set(dates)):
        bad("DUPLICATE_DATED_DAY", "Each real date must have one canonical day; bell variants share it")
    days = {x.id: x for x in p.days}
    windows = {x.id: x for x in p.windows}
    resources = {x.id: x for x in p.resources}
    activities = {x.id: x for x in p.activities}
    events = {x.id: x for x in p.events}
    offerings = {x.id: x for x in p.offerings}
    for w in p.windows:
        if w.day_id not in days:
            bad("UNKNOWN_DAY", f"{w.id} -> {w.day_id}")
    bell_seq = [(w.day_id, w.bell_id, w.sequence) for w in p.windows]
    if len(bell_seq) != len(set(bell_seq)):
        bad("DUPLICATE_BELL_SEQUENCE", "Same day/bell/sequence cannot occur twice")
    for res in p.resources:
        if res.member_ids and res.kind != ResourceKind.GROUP:
            bad("MEMBERS_ONLY_GROUP", f"{res.id} has members but kind is {res.kind}")
        for m in res.member_ids:
            if m not in resources:
                bad("UNKNOWN_MEMBER", f"{res.id} -> {m}")
            if m == res.id:
                bad("GROUP_SELF_MEMBER", f"{res.id} includes itself")
        for w in res.unavailable_window_ids:
            if w not in windows:
                bad("UNKNOWN_WINDOW", f"Resource {res.id} blackout -> {w}")
    def group_cycle(rid, ancestors):
        if rid in ancestors:
            return True
        res = resources.get(rid)
        return res is not None and res.kind == ResourceKind.GROUP and any(
            group_cycle(m, ancestors | {rid}) for m in res.member_ids
        )
    for res in p.resources:
        if res.kind == ResourceKind.GROUP and group_cycle(res.id, set()):
            bad("GROUP_CYCLE", f"Cyclic group membership involving {res.id}")

    for e in p.events:
        if e.activity_id not in activities:
            bad("UNKNOWN_ACTIVITY", f"{e.id} -> {e.activity_id}")
        if e.offering_id is not None:
            offer = offerings.get(e.offering_id)
            if not offer:
                bad("UNKNOWN_OFFERING", f"{e.id} -> {e.offering_id}")
            elif offer.activity_id != e.activity_id or e.id not in offer.event_ids:
                bad("OFFERING_EVENT_MISMATCH", f"{e.id} is not consistently linked")
            if e.required:
                bad("OPTIONAL_EVENT_REQUIRED", f"{e.id} is offering-activated, so required must be false")
        elif not e.required:
            bad("UNOWNED_OPTIONAL_EVENT", f"Optional event {e.id} lacks an offering")
        for part in e.fixed_participant_ids:
            if part not in resources:
                bad("UNKNOWN_PARTICIPANT", f"{e.id} -> {part}")
        for win in e.placement.start_window_ids:
            if win not in windows:
                bad("UNKNOWN_WINDOW", f"{e.id} placement -> {win}")
        req_ids = [x.id for x in e.requirements]
        if len(req_ids) != len(set(req_ids)):
            bad("DUPLICATE_REQUIREMENT", f"{e.id} duplicated requirements")
        for req in e.requirements:
            if len(req.eligible_resource_ids) != len(set(req.eligible_resource_ids)):
                bad("DUPLICATE_ELIGIBLE_RESOURCE", f"{req.id}")
            if req.quantity > len(req.eligible_resource_ids):
                bad("IMPOSSIBLE_QUANTITY", f"{e.id}/{req.id}")
            for r in req.eligible_resource_ids:
                if r not in resources:
                    bad("UNKNOWN_RESOURCE", f"{e.id}/{req.id} -> {r}")
                elif resources[r].kind != req.kind:
                    bad("RESOURCE_KIND_MISMATCH", f"{e.id}/{req.id} -> {r}")

    for o in p.offerings:
        if o.activity_id not in activities:
            bad("UNKNOWN_ACTIVITY", f"Offering {o.id} -> {o.activity_id}")
        for e in o.event_ids:
            if e not in events or events[e].offering_id != o.id:
                bad("OFFERING_EVENT_MISMATCH", f"{o.id} -> {e}")

    for req in p.participation_requests:
        if req.participant_id not in resources or resources[req.participant_id].kind != ResourceKind.PERSON:
            bad("REQUEST_PARTICIPANT_KIND", f"{req.id} must point to a PERSON")
        if req.activity_id not in activities:
            bad("UNKNOWN_ACTIVITY", f"{req.id} -> {req.activity_id}")
        if len(req.eligible_offering_ids) != len(set(req.eligible_offering_ids)):
            bad("DUPLICATE_OPTION", req.id)
        for oid in req.eligible_offering_ids:
            if oid not in offerings:
                bad("UNKNOWN_OFFERING", f"{req.id} -> {oid}")
            elif offerings[oid].activity_id != req.activity_id:
                bad("REQUEST_ACTIVITY_MISMATCH", f"{req.id} -> {oid}")
    for act in p.activities:
        if act.demand.basis == "GLOBAL":
            act_events = [e for e in p.events if e.activity_id == act.id]
            if any(e.offering_id for e in act_events):
                bad("GLOBAL_WITH_OFFERING", f"{act.id} cannot be global and offering-activated")
            if any(e.duration.unit != act.demand.unit for e in act_events):
                bad("MIXED_DURATION_UNITS", act.id)
            elif sum(e.duration.count for e in act_events) != act.demand.amount:
                bad("GLOBAL_DEMAND_MISMATCH", f"{act.id} demands {act.demand.amount} but declared {sum(e.duration.count for e in act_events)}")
        elif not any(o.activity_id == act.id for o in p.offerings):
            bad("PARTICIPANT_DEMAND_NO_OFFERING", act.id)

    for lock in p.locks:
        if lock.event_id not in events:
            bad("UNKNOWN_EVENT", f"Lock {lock.id} -> {lock.event_id}")
            continue
        e = events[lock.event_id]
        if lock.start_window_id is not None and lock.start_window_id not in e.placement.start_window_ids:
            bad("INVALID_LOCK_START", lock.id)
        if lock.requirement_id:
            rqs = {q.id: q for q in e.requirements}
            if lock.requirement_id not in rqs:
                bad("UNKNOWN_REQUIREMENT", f"Lock {lock.id}")
            elif set(lock.resource_ids) - set(rqs[lock.requirement_id].eligible_resource_ids):
                bad("INVALID_LOCK_RESOURCE", lock.id)

    for c in p.constraints:
        if isinstance(c, ResourceBlackout):
            if c.resource_id not in resources: bad("UNKNOWN_RESOURCE", c.id)
            for w in c.window_ids:
                if w not in windows: bad("UNKNOWN_WINDOW", c.id)
        elif isinstance(c, ExcludeFromEvent):
            for e in c.event_ids:
                if e not in events: bad("UNKNOWN_EVENT", c.id)
            for r in c.resource_ids:
                if r not in resources: bad("UNKNOWN_RESOURCE", c.id)
        elif isinstance(c, (MaxDailyMinutes, WorkloadBalance)):
            for r in c.resource_ids:
                if r not in resources: bad("UNKNOWN_RESOURCE", c.id)
        elif isinstance(c, ActivitySpread):
            for a in c.activity_ids:
                if a not in activities: bad("UNKNOWN_ACTIVITY", c.id)
        elif isinstance(c, EventOrdering):
            if c.earlier_event_id not in events or c.later_event_id not in events:
                bad("UNKNOWN_EVENT", c.id)
        elif isinstance(c, EventNotTogether):
            for e in c.event_ids:
                if e not in events: bad("UNKNOWN_EVENT", c.id)
    return issues


def window_placement(p: SchedulingProblem, event, start_id: str):
    """Return (day_id, absolute local-minute start, end, *teaching/duty minutes*).

    Raises ValueError on broken adjacency or too-short fixed session. Source window IDs
    identify candidate STARTS; the occupied actual-time interval is authoritative.
    """
    wins = {w.id: w for w in p.windows}
    if start_id not in wins or start_id not in event.placement.start_window_ids:
        raise ValueError(f"invalid start window {start_id} for {event.id}")
    first = wins[start_id]
    if event.duration.unit == "MINUTES":
        end = first.start_minute + event.duration.count
        if end > first.end_minute:
            raise ValueError(f"{event.id} runs past the allowed session window")
        return first.day_id, first.start_minute, end, event.duration.count
    gap_max = event.duration.max_gap_minutes
    chain = sorted(
        [w for w in p.windows if w.day_id == first.day_id and w.bell_id == first.bell_id
         and first.sequence <= w.sequence < first.sequence + event.duration.count],
        key=lambda w: w.sequence,
    )
    if len(chain) != event.duration.count or [w.sequence for w in chain] != list(range(first.sequence, first.sequence + event.duration.count)):
        raise ValueError(f"{event.id} does not have {event.duration.count} consecutive windows")
    for left, right in zip(chain, chain[1:]):
        if not (0 <= right.start_minute - left.end_minute <= gap_max):
            raise ValueError(f"{event.id} crosses a disallowed bell gap")
    return first.day_id, first.start_minute, chain[-1].end_minute, sum(w.end_minute - w.start_minute for w in chain)


def _overlap(a, b):
    return a[0] == b[0] and a[1] < b[2] and b[1] < a[2]


def witness_issues(p: SchedulingProblem, s: SchedulingSolution) -> list[ContractIssue]:
    issues = problem_issues(p)
    def bad(code, message):
        issues.append(ContractIssue(code, message))
    if issues: return issues
    if s.problem_id != p.problem_id or s.model_version != p.model_version:
        bad("STALE_SOLUTION", "Solution must repeat problem_id and model_version")
    if s.status not in ("FEASIBLE", "OPTIMAL"):
        bad("NOT_A_WITNESS", "Only FEASIBLE/OPTIMAL candidate solutions have witness semantics")
        return issues
    if s.validation == "PASSED":
        bad("UNTRUSTED_SELF_VALIDATION", "Input solution must not self-certify validation PASSED")
    resources = {r.id:r for r in p.resources}
    events = {e.id:e for e in p.events}
    offerings = {o.id:o for o in p.offerings}
    requests = {r.id:r for r in p.participation_requests}
    wins = {w.id:w for w in p.windows}
    ea = {a.event_id:a for a in s.event_assignments}
    en = {a.request_id:a for a in s.enrollment_assignments}
    if len(ea) != len(s.event_assignments): bad("DUPLICATE_EVENT_ASSIGNMENT", "One event cannot be assigned twice")
    if len(en) != len(s.enrollment_assignments): bad("DUPLICATE_ENROLLMENT", "One request cannot be assigned twice")
    for eid in ea:
        if eid not in events: bad("UNKNOWN_EVENT", eid)
    for rid in en:
        if rid not in requests: bad("UNKNOWN_REQUEST", rid)
    for rid in requests:
        if rid not in en: bad("MISSING_ENROLLMENT", rid)
    enrollment_by_offering: dict[str, set[str]] = defaultdict(set)
    for rid, response in en.items():
        if rid not in requests: continue
        req = requests[rid]
        choices = response.offering_ids
        # A soft request may go unfulfilled; the unmet demand is a scoring term.
        required_min = req.min_select if req.strength == RuleStrength.HARD else 0
        if len(set(choices)) != len(choices) or not (required_min <= len(choices) <= req.max_select):
            bad("BAD_REQUEST_COUNT", rid)
        if not set(choices) <= set(req.eligible_offering_ids):
            bad("INVALID_OFFERING_SELECTION", rid)
        for oid in choices:
            if oid in offerings: enrollment_by_offering[oid].add(req.participant_id)
    for oid, participants in enrollment_by_offering.items():
        if len(participants) > offerings[oid].capacity:
            bad("OFFERING_OVER_CAPACITY", f"{oid}: {len(participants)} > {offerings[oid].capacity}")

    active_offerings = {oid for oid, people in enrollment_by_offering.items() if people}
    for event in p.events:
        should_assign = event.required or event.offering_id in active_offerings
        if should_assign and event.id not in ea:
            bad("MISSING_EVENT", event.id)
        if not should_assign and event.id in ea:
            bad("INACTIVE_EVENT_ASSIGNED", event.id)

    def people_from(resource_id, visited=None):
        visited = visited or set()
        if resource_id in visited: return set()
        visited.add(resource_id)
        r = resources.get(resource_id)
        if not r: return set()
        if r.kind == ResourceKind.PERSON: return {resource_id}
        if r.kind == ResourceKind.GROUP:
            out=set()
            for member in r.member_ids: out |= people_from(member, set(visited))
            return out
        return set()

    shared_units = {}
    event_usage = {}   # eid -> (day, start, end, duty_minutes, resource_ids, participant_ids, role_allocs)
    occupied: dict[str, list[tuple[str,int,int,str]]] = defaultdict(list)
    # Every specific resource is exclusive by default. Person membership is expanded independently.
    for eid, assignment in ea.items():
        e = events.get(eid)
        if not e: continue
        try:
            day_id, start, end, duty_minutes = window_placement(p, e, assignment.start_window_id)
        except ValueError as exc:
            bad("INVALID_PLACEMENT", str(exc)); continue
        reqs={q.id:q for q in e.requirements}
        allocs={a.requirement_id:a.resource_ids for a in assignment.resource_allocations}
        if len(allocs) != len(assignment.resource_allocations): bad("DUPLICATE_ROLE_ALLOCATION", eid)
        if set(allocs) != set(reqs):
            bad("REQUIREMENTS_NOT_SATISFIED", eid)
        assigned_resources=set()
        for req_id, ids in allocs.items():
            if req_id not in reqs:
                bad("UNKNOWN_REQUIREMENT", f"{eid}/{req_id}");continue
            q=reqs[req_id]
            if len(ids)!=q.quantity or len(set(ids))!=len(ids) or not set(ids)<=set(q.eligible_resource_ids):
                bad("INVALID_RESOURCE_SELECTION", f"{eid}/{req_id}")
            for res_id in ids:
                if res_id in assigned_resources:
                    bad("DUPLICATE_RESOURCE_ROLE", f"{eid}/{res_id}")
                assigned_resources.add(res_id)
                if res_id in resources and resources[res_id].sharing_mode == "CUMULATIVE":
                    if q.usage_units is None:
                        bad("MISSING_USAGE_UNITS", f"{eid}/{req_id}/{res_id}")
                    else:
                        shared_units[(eid,res_id)] = q.usage_units
                if res_id in resources and q.minimum_capacity is not None:
                    if (resources[res_id].capacity or 0)<q.minimum_capacity:
                        bad("MIN_CAPACITY", f"{eid}/{req_id}/{res_id}")
        participants=set()
        for fixed in e.fixed_participant_ids:
            participants |= people_from(fixed)
        if e.offering_id:
            participants |= enrollment_by_offering[e.offering_id]
        for fixed in e.fixed_participant_ids:
            assigned_resources.add(fixed)
        # Add enrolled participants as occupied participants.
        entity_occupiers=set(assigned_resources)|participants
        for fixed in e.fixed_participant_ids:
            entity_occupiers |= people_from(fixed)
        for r in list(assigned_resources):
            entity_occupiers |= people_from(r)
        for r in entity_occupiers:
            occupied[r].append((day_id,start,end,eid))
            resource=resources.get(r)
            if resource:
                for unavailable_id in resource.unavailable_window_ids:
                    w=wins[unavailable_id]
                    if _overlap((day_id,start,end),(w.day_id,w.start_minute,w.end_minute)):
                        bad("RESOURCE_UNAVAILABLE", f"{eid}/{r} overlaps {unavailable_id}")
        for res_id in assigned_resources:
            rr=resources.get(res_id)
            if rr and rr.sharing_mode == "CUMULATIVE" and (eid,res_id) not in shared_units:
                bad("MISSING_USAGE_UNITS", f"{eid}/{res_id}")
            if rr and rr.sharing_mode == "CUMULATIVE" and rr.kind == ResourceKind.SPACE and shared_units.get((eid,res_id),0) < len(participants):
                bad("UNDERCOUNTED_ATTENDANCE", f"{eid}/{res_id}")
            if rr and rr.kind == ResourceKind.SPACE and rr.capacity is not None and len(participants)>rr.capacity:
                bad("ROOM_OVER_CAPACITY", f"{eid}/{res_id}: {len(participants)} > {rr.capacity}")
        event_usage[eid]=(day_id,start,end,duty_minutes,assigned_resources,participants,allocs)
    # Reuse the same neutral occupancy checker as linked jobs and segmented duties.
    # Synthetic UTC day positions are only for this existing abstract-day dialect.
    # Linked dated schedules must first pass explicit cycle/calendar projection.
    day_positions={day.id:i for i,day in enumerate(p.days)}
    epoch=datetime(2000,1,1,tzinfo=timezone.utc)
    catalog=[CapacityResource(id=r.id,kind=r.kind.value,sharing=r.sharing_mode,
                              capacity=r.capacity or 1) for r in p.resources]
    claims=[]
    for rid,entries in occupied.items():
        for day,start,end,eid in entries:
            units=shared_units.get((eid,rid),1)
            claims.append(ResourceClaim(id=f"claim:{eid}:{rid}",schedule_id=p.problem_id,entity_id=eid,
                resource_id=rid,units=units,interval=Interval(
                    start=epoch+timedelta(days=day_positions[day],minutes=start),
                    end=epoch+timedelta(days=day_positions[day],minutes=end))))
    for finding in usage_errors(catalog,claims):
        bad(finding.code,finding.detail)
    for lock in p.locks:
        a=ea.get(lock.event_id)
        if not a: continue
        if lock.start_window_id and a.start_window_id!=lock.start_window_id:
            bad("LOCK_START_VIOLATED", lock.id)
        if lock.requirement_id:
            actual={r.requirement_id:r.resource_ids for r in a.resource_allocations}
            if set(actual.get(lock.requirement_id,[])) != set(lock.resource_ids):
                bad("LOCK_ALLOCATION_VIOLATED", lock.id)

    # Validate enrolled demand independently of how the optimiser builds sessions.
    for request in p.participation_requests:
        if request.id not in en: continue
        act=next((a for a in p.activities if a.id==request.activity_id),None)
        if act and act.demand.basis=="PER_ENROLLED":
            chosen=en[request.id].offering_ids
            for oid in chosen:
                offer=offerings.get(oid)
                if not offer: continue
                ses=[events[eid] for eid in offer.event_ids if eid in events]
                if not all(e.duration.unit == act.demand.unit for e in ses):
                    bad("MIXED_DURATION_UNITS", oid)
                elif sum(e.duration.count for e in ses)!=act.demand.amount:
                    bad("PER_ENROLLED_DEMAND_MISMATCH", f"{request.id}/{oid}")

    # Explicit subset; all unknown mandatory rules are rejected, never ignored.
    for c in p.constraints:
        if not c.enabled or c.strength == RuleStrength.SOFT: continue
        if isinstance(c, ResourceBlackout):
            for e,usage in event_usage.items():
                for r in (usage[4] | usage[5]):
                    expanded = people_from(r)
                    if c.resource_id != r and c.resource_id not in expanded: continue
                    for wid in c.window_ids:
                        w=wins[wid]
                        if _overlap(usage[:3],(w.day_id,w.start_minute,w.end_minute)):
                            bad("BLACKOUT_VIOLATED", f"{c.id}/{e}/{r}")
        elif isinstance(c, ExcludeFromEvent):
            for eid in c.event_ids:
                if eid not in event_usage: continue
                usage=event_usage[eid]
                if c.role:
                    e=events[eid]
                    match={req.id for req in e.requirements if req.role == c.role}
                    allocated=set().union(*(set(usage[6].get(reqid,[])) for reqid in match)) if match else set()
                else:
                    allocated=usage[4]
                for resource_id in c.resource_ids:
                    if resource_id in allocated:
                        bad("EXCLUSION_VIOLATED", f"{c.id}/{eid}/{resource_id}")
        elif isinstance(c,(MaxDailyMinutes,WorkloadBalance)):
            mins=defaultdict(int)
            counts=defaultdict(int)
            daily=defaultdict(int)
            for eid,usage in event_usage.items():
                for r in usage[4]:
                    mins[r]+=usage[3]; counts[r]+=1; daily[(r,usage[0])]+=usage[3]
            if isinstance(c,MaxDailyMinutes):
                for r in c.resource_ids:
                    for day in {d for (_,d) in daily}:
                        if daily.get((r,day),0)>c.limit_minutes:
                            bad("DAILY_LOAD_VIOLATED", f"{c.id}/{r}/{day}")
            else:
                series=[(counts if c.metric=="ASSIGNMENT_COUNT" else mins).get(r,0) for r in c.resource_ids]
                if max(series)-min(series)>c.target_spread:
                    bad("WORKLOAD_BALANCE_VIOLATED", c.id)
        elif isinstance(c,ActivitySpread):
            for a in c.activity_ids:
                days={event_usage[e.id][0] for e in p.events if e.activity_id==a and e.id in event_usage}
                if len(days)<c.minimum_distinct_days:
                    bad("ACTIVITY_SPREAD_VIOLATED", f"{c.id}/{a}")
        elif isinstance(c,EventOrdering):
            a,b=event_usage.get(c.earlier_event_id),event_usage.get(c.later_event_id)
            if a and b:
                day_index={d.id:d.ordinal for d in p.days}
                if (day_index[a[0]],a[2]+c.minimum_gap_minutes)>(day_index[b[0]],b[1]):
                    bad("EVENT_ORDER_VIOLATED", c.id)
        elif isinstance(c,EventNotTogether):
            for i,eid in enumerate(c.event_ids):
                for eid2 in c.event_ids[i+1:]:
                    a,b=event_usage.get(eid),event_usage.get(eid2)
                    if a and b and _overlap(a[:3],b[:3]):
                        bad("EVENT_SAME_TIME_VIOLATED", c.id)
        else:
            bad("UNSUPPORTED_HARD_RULE", f"Rule type {c.kind} has no certified independent check")
    return issues
