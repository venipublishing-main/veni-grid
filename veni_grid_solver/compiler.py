"""Independent compilation of C1 to OR-Tools CP-SAT.

This module shares input *types* with the contract, but never calls the witness
checker, its placement helper, or its rule evaluation routines. Candidate start
choices, enrollments and role selections are genuine decision variables.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import combinations
from zoneinfo import ZoneInfo
from ortools.sat.python import cp_model
from veni_grid_contract.core_v1 import CoreProblem

HARD_RULES = frozenset({
    'RESOURCE_BLACKOUT', 'EXCLUDE_RESOURCE_FROM_EVENT', 'MAX_DAILY_MINUTES',
    'WORKLOAD_BALANCE', 'ACTIVITY_SPREAD', 'EVENT_BEFORE', 'EVENT_NOT_SAME_TIME',
    'EVENT_SAME_START', 'QUALIFICATION', 'RESOURCE_CONTINUITY', 'TRAVEL_TIME',
})


class UnsupportedInput(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail); self.code = code; self.detail = detail


@dataclass(frozen=True)
class Placement:
    window_id: str
    day: str
    start: int
    end: int
    work: int
    absolute_start: int
    absolute_end: int


def _utc_minute(day, minute: int, zone: str) -> int:
    """Independent local-clock resolution; ambiguous/nonexistent times refuse."""
    naive = datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute)
    tz = ZoneInfo(zone)
    values = set()
    for fold in (0, 1):
        instant = naive.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)
        if instant.astimezone(tz).replace(tzinfo=None) == naive:
            values.add(instant)
    if len(values) != 1:
        raise UnsupportedInput('UNRESOLVED_LOCAL_TIME', f'{day}/{minute}/{zone}')
    instant = values.pop()
    seconds = int((instant - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds())
    if seconds % 60:
        raise UnsupportedInput('SUBMINUTE_TIMEZONE', 'C1 runtime uses whole elapsed minutes')
    return seconds // 60


def placements(p: CoreProblem, event) -> list[Placement]:
    """Independently derive the legal time-domain shape, without a witness."""
    wins = {w.id: w for w in p.windows}
    days = {d.id: d for d in p.days}
    by_key = {(w.day_id, w.bell_id, w.sequence): w for w in p.windows}
    out = []
    for wid in sorted(set(event.placement.start_window_ids)):
        w = wins[wid]
        if event.duration.unit == 'MINUTES':
            end = w.start_minute + event.duration.count
            if end > w.end_minute:
                continue
            work = event.duration.count
        else:
            if event.duration.count > len(p.windows):
                continue
            chain = [by_key.get((w.day_id, w.bell_id, w.sequence + n))
                     for n in range(event.duration.count)]
            if any(c is None for c in chain):
                continue
            if any(not 0 <= b.start_minute - a.end_minute <= event.duration.max_gap_minutes
                   for a, b in zip(chain, chain[1:])):
                continue
            end = chain[-1].end_minute
            work = sum(c.end_minute - c.start_minute for c in chain)
        d = days[w.day_id]
        if d.date is None:
            start_abs = d.ordinal * 1440 + w.start_minute
            end_abs = d.ordinal * 1440 + end
        else:
            start_abs = _utc_minute(d.date, w.start_minute, p.timezone)
            end_abs = _utc_minute(d.date, end, p.timezone)
        if end_abs <= start_abs:
            raise UnsupportedInput('NONPOSITIVE_ELAPSED_INTERVAL', f'{event.id}/{wid}')
        out.append(Placement(wid, w.day_id, w.start_minute, end, work, start_abs, end_abs))
    return out


class Compiler:
    """Finite placement/profile compiler; deliberately bounded before allocation."""
    def __init__(self, p: CoreProblem):
        self.p = p
        self.m = cp_model.CpModel()
        self.rs = {r.id: r for r in p.resources}
        self.es = {e.id: e for e in p.events}
        self.ws = {w.id: w for w in p.windows}
        self.ds = {d.id: d for d in p.days}
        self.expanded = {}
        for rid in self.rs:
            self._expand(rid)
        self.domains = {e.id: placements(p, e) for e in p.events}
        self.a = {}                  # event active
        self.x = {}                  # event/start chosen
        self.y = {}                  # event/requirement/resource chosen
        self.en = {}                 # request/offering selection
        self.members = {}            # distinct person memberships in offering
        self.offer_active = {}
        self.direct = {}             # direct fixed/role occupancy (RC1 balance semantics)
        self.used = {}               # fully expanded occupancy, incl enrolled people
        self.attendance = {}         # fixed + enrolled PERSON attendance, not staff
        self.on_day = {}
        self.at_location = {}
        self.starts = {}; self.ends = {}
        self.presence = {}           # event/resource/start occupancy
        self.notes = []
        self.serial = 0
        self._bounds()
        self._readiness()

    def _expand(self, rid):
        if rid not in self.expanded:
            result = {rid}
            r = self.rs[rid]
            if r.kind == 'GROUP':
                for member in r.member_ids:
                    result |= self._expand(member)
            self.expanded[rid] = result
        return self.expanded[rid]

    def _bounds(self):
        places = sum(map(len, self.domains.values()))
        roles = sum(len(q.eligible_resource_ids) for e in self.p.events for q in e.requirements)
        if places > 50000 or roles > 50000 or len(self.p.events) > 2000:
            raise UnsupportedInput('COMPILATION_SIZE_LIMIT', 'Prototype limit: 2,000 events, 50,000 starts or role edges')
        expanded_intervals = sum(len(self.domains[e.id]) * len(self._possible_users(e)) for e in self.p.events)
        if expanded_intervals > 250000:
            raise UnsupportedInput('OCCUPANCY_EXPANSION_LIMIT', 'Prototype limit: 250,000 expanded resource/start intervals')
        values = [d.ordinal for d in self.p.days]
        values += [e.duration.count for e in self.p.events]
        values += [r.capacity or 0 for r in self.p.resources]
        values += [q.usage_units or 0 for e in self.p.events for q in e.requirements]
        if any(abs(n) > 10**8 for n in values):
            raise UnsupportedInput('INTEGER_RANGE_LIMIT', 'Prototype scalar bound is 100,000,000')

    def _possible_direct(self, e):
        return set(e.fixed_participant_ids) | {r for q in e.requirements for r in q.eligible_resource_ids}

    def _possible_users(self, e):
        out = set().union(*(self.expanded[r] for r in self._possible_direct(e))) if self._possible_direct(e) else set()
        if e.offering_id:
            out |= {q.participant_id for q in self.p.participation_requests
                    if e.offering_id in q.eligible_offering_ids}
        return out

    def _readiness(self):
        # A refusal is not infeasibility: missing operating facts cannot be guessed.
        cyclic = self.p.days[0].date is None
        for e in self.p.events:
            for q in e.requirements:
                if any(self.rs[r].sharing_mode == 'CUMULATIVE' for r in q.eligible_resource_ids) and q.usage_units is None:
                    raise UnsupportedInput('MISSING_USAGE_UNITS', f'{e.id}/{q.id}')
            for rid in e.fixed_participant_ids:
                if self.rs[rid].sharing_mode == 'CUMULATIVE' and not any(
                        rid in q.eligible_resource_ids and q.usage_units is not None for q in e.requirements):
                    raise UnsupportedInput('MISSING_FIXED_RESOURCE_CONSUMPTION', f'{e.id}/{rid}')
            # Physical members inside groups have no independently defined consumption.
            for rid in sorted(self._possible_direct(e)):
                if self.rs[rid].kind == 'GROUP' and any(self.rs[c].kind not in ('PERSON', 'GROUP') for c in self.expanded[rid]):
                    raise UnsupportedInput('NONPERSON_GROUP_MEMBERSHIP', 'C1 runtime expands nested people/groups, not physical-capacity bundles')
        for rule in self.p.constraints:
            if not rule.enabled or rule.strength != 'HARD':
                continue
            if rule.kind not in HARD_RULES:
                raise UnsupportedInput('UNSUPPORTED_HARD_RULE', rule.kind)
            if rule.kind == 'QUALIFICATION' and cyclic:
                for ref in rule.allocations:
                    q = next(q for q in self.es[ref.event_id].requirements if q.id == ref.requirement_id)
                    for rid in q.eligible_resource_ids:
                        for code in rule.all_of:
                            creds = [c for c in self.p.credentials if c.resource_id == rid and c.competency == code]
                            if creds and all(c.valid_during is not None for c in creds):
                                raise UnsupportedInput('QUALIFICATION_NEEDS_DATES', f'{ref.event_id}/{rid}/{code}')
            if rule.kind == 'TRAVEL_TIME':
                arcs = {(a.profile, a.from_location, a.to_location) for a in self.p.travel_arcs}
                for rid in rule.resource_ids:
                    by_day = defaultdict(list)
                    for e in self.p.events:
                        if rid not in self._possible_users(e):
                            continue
                        for day in {d.day for d in self.domains[e.id]}:
                            by_day[day].append(e)
                    for day, events in by_day.items():
                        if len(events) < 2:
                            continue
                        if len(events) > 100:
                            raise UnsupportedInput('TRAVEL_SEQUENCE_SIZE_LIMIT', 'At most 100 possible events per traveler/day in prototype')
                        locations = set()
                        for e in events:
                            spaces = [self.rs[r] for r in self._possible_direct(e) if self.rs[r].kind == 'SPACE']
                            if not spaces or any(r.location_id is None for r in spaces):
                                raise UnsupportedInput('TRAVEL_LOCATION_UNRESOLVED', f'{rid}/{e.id}/{day}')
                            locations.update(r.location_id for r in spaces)
                        for a in locations:
                            for b in locations:
                                if a != b and (self.rs[rid].travel_profile, a, b) not in arcs:
                                    raise UnsupportedInput('TRAVEL_ROUTE_UNRESOLVED', f'{rid}/{a}->{b}: supply complete possible-route matrix')

    def b(self, prefix):
        self.serial += 1
        return self.m.new_bool_var(f'{prefix}:{self.serial}')

    def OR(self, terms, name):
        terms = list(terms)
        if not terms: return self.m.new_constant(0)
        if len(terms) == 1: return terms[0]
        b = self.b(name)
        self.m.add_max_equality(b, terms)
        return b

    def AND(self, terms, name):
        terms = list(terms)
        if not terms: return self.m.new_constant(1)
        if len(terms) == 1: return terms[0]
        b = self.b(name)
        self.m.add_bool_and(terms).only_enforce_if(b)
        self.m.add_bool_or([t.Not() for t in terms]).only_enforce_if(b.Not())
        return b

    def compile(self):
        self._enrollments()
        self._events()
        self._occupancy()
        self._locks()
        self._rules()
        return self

    def _enrollments(self):
        for req in self.p.participation_requests:
            choices = []
            for oid in req.eligible_offering_ids:
                z = self.b(f'enroll:{req.id}:{oid}')
                self.en[req.id, oid] = z; choices.append(z)
            minimum = req.min_select if req.strength == 'HARD' else 0
            self.m.add(sum(choices) >= minimum)
            self.m.add(sum(choices) <= req.max_select)
        for o in self.p.offerings:
            by_person = defaultdict(list)
            for req in self.p.participation_requests:
                if (req.id, o.id) in self.en:
                    by_person[req.participant_id].append(self.en[req.id, o.id])
            ms = []
            for pid, terms in by_person.items():
                m = self.OR(terms, f'member:{o.id}:{pid}')
                self.members[o.id, pid] = m; ms.append(m)
            self.m.add(sum(ms) <= o.capacity)
            active = self.OR(ms, f'offer:{o.id}')
            self.offer_active[o.id] = active
            act = next(a for a in self.p.activities if a.id == o.activity_id)
            es = [self.es[eid] for eid in o.event_ids]
            if act.demand.basis == 'PER_ENROLLED' and (any(e.duration.unit != act.demand.unit for e in es)
                    or sum(e.duration.count for e in es) != act.demand.amount):
                self.m.add(active == 0)
                self.notes.append(f'Offering {o.id} cannot activate: declared events do not supply its demand')

    def _events(self):
        max_tick = max((d.absolute_end for ds in self.domains.values() for d in ds), default=1)
        min_tick = min(0, min((d.absolute_start for ds in self.domains.values() for d in ds), default=0))
        for e in self.p.events:
            a = self.b(f'active:{e.id}'); self.a[e.id] = a
            self.m.add(a == (1 if e.required else self.offer_active[e.offering_id]))
            xs = []
            for d in self.domains[e.id]:
                x = self.b(f'start:{e.id}:{d.window_id}')
                self.x[e.id, d.window_id] = x; xs.append(x)
            self.m.add(sum(xs) == a)
            st = self.m.new_int_var(min_tick, max_tick, f'start_tick:{e.id}')
            en = self.m.new_int_var(min_tick, max_tick, f'end_tick:{e.id}')
            self.m.add(st == sum(d.absolute_start * self.x[e.id,d.window_id] for d in self.domains[e.id]))
            self.m.add(en == sum(d.absolute_end * self.x[e.id,d.window_id] for d in self.domains[e.id]))
            self.starts[e.id] = st; self.ends[e.id] = en
            for day in self.ds:
                self.on_day[e.id, day] = self.OR([self.x[e.id,d.window_id] for d in self.domains[e.id] if d.day == day], 'day')
            selected = defaultdict(list)
            for q in e.requirements:
                ys = []
                for rid in q.eligible_resource_ids:
                    y = self.b(f'role:{e.id}:{q.id}:{rid}')
                    self.y[e.id,q.id,rid] = y; ys.append(y); selected[rid].append(y)
                    self.m.add(y <= a)
                    if q.minimum_capacity is not None and (self.rs[rid].capacity or 0) < q.minimum_capacity:
                        self.m.add(y == 0)
                self.m.add(sum(ys) == q.quantity * a)
            for rid, terms in selected.items():
                self.m.add(sum(terms) <= 1)  # one resource, one explicit role in this event
            direct_terms = defaultdict(list)
            for rid in e.fixed_participant_ids: direct_terms[rid].append(a)
            for rid, terms in selected.items(): direct_terms[rid].extend(terms)
            for rid, terms in direct_terms.items(): self.direct[e.id,rid] = self.OR(terms, 'direct')
            use_terms = defaultdict(list)
            for rid, terms in direct_terms.items():
                for child in sorted(self.expanded[rid]): use_terms[child].extend(terms)
            attendance_terms = defaultdict(list)
            for rid in e.fixed_participant_ids:
                for pid in sorted(self.expanded[rid]):
                    if self.rs[pid].kind == 'PERSON': attendance_terms[pid].append(a)
            if e.offering_id:
                for (oid,pid), member in self.members.items():
                    if oid == e.offering_id:
                        use_terms[pid].append(member); attendance_terms[pid].append(member)
            for rid, terms in use_terms.items(): self.used[e.id,rid] = self.OR(terms, 'used')
            persons = [self.OR(terms, 'attends') for terms in attendance_terms.values()]
            attendance = sum(persons); self.attendance[e.id] = attendance
            loc_terms = defaultdict(list)
            for rid in sorted(self._possible_direct(e)):
                rr = self.rs[rid]
                if rr.kind == 'SPACE':
                    used = self.direct[e.id,rid]
                    if rr.capacity is not None: self.m.add(attendance <= rr.capacity).only_enforce_if(used)
                    if rr.location_id: loc_terms[rr.location_id].append(used)
                    if rr.sharing_mode == 'CUMULATIVE':
                        cons = sum(q.usage_units * self.y[e.id,q.id,rid] for q in e.requirements
                                   if rid in q.eligible_resource_ids and q.usage_units is not None)
                        self.m.add(cons >= attendance).only_enforce_if(used)
            for loc, terms in loc_terms.items(): self.at_location[e.id,loc] = self.OR(terms, 'location')
            for rid in e.fixed_participant_ids:
                if self.rs[rid].sharing_mode == 'CUMULATIVE':
                    self.m.add(sum(selected[rid]) >= a)

    def _occupancy(self):
        intervals = defaultdict(list); demands = defaultdict(list)
        for e in self.p.events:
            for rid in sorted(self._possible_users(e)):
                used = self.used.get((e.id,rid))
                if used is None: continue
                rr = self.rs[rid]
                consumption = 1
                if rr.sharing_mode == 'CUMULATIVE':
                    terms = [q.usage_units * self.y[e.id,q.id,rid] for q in e.requirements
                             if rid in q.eligible_resource_ids and q.usage_units is not None]
                    upper = sum(q.usage_units for q in e.requirements
                                if rid in q.eligible_resource_ids and q.usage_units is not None)
                    consumption = self.m.new_int_var(0, upper, f'consumption:{e.id}:{rid}')
                    self.m.add(consumption == sum(terms))
                for d in self.domains[e.id]:
                    x = self.x[e.id,d.window_id]
                    on = self.AND([x,used], 'occupies'); self.presence[e.id,rid,d.window_id] = on
                    iv = self.m.new_optional_fixed_size_interval_var(d.absolute_start,
                        d.absolute_end-d.absolute_start, on, f'interval:{e.id}:{rid}:{d.window_id}')
                    intervals[rid].append(iv); demands[rid].append(consumption)
                    if any(self.overlaps_window(d, self.ws[w]) for w in rr.unavailable_window_ids):
                        self.m.add(on == 0)
        for rid, ivs in intervals.items():
            r = self.rs[rid]
            if r.sharing_mode == 'EXCLUSIVE': self.m.add_no_overlap(ivs)
            else: self.m.add_cumulative(ivs, demands[rid], r.capacity)

    @staticmethod
    def overlaps_window(d, w):
        return d.day == w.day_id and d.start < w.end_minute and w.start_minute < d.end

    def _locks(self):
        for lock in self.p.locks:
            if lock.start_window_id is not None:
                x = self.x.get((lock.event_id,lock.start_window_id))
                if x is None: self.m.add(self.a[lock.event_id] == 0)
                else: self.m.add(x == self.a[lock.event_id])
            if lock.requirement_id:
                q = next(q for q in self.es[lock.event_id].requirements if q.id == lock.requirement_id)
                wanted = set(lock.resource_ids)
                for rid in q.eligible_resource_ids:
                    self.m.add(self.y[lock.event_id,q.id,rid] == (self.a[lock.event_id] if rid in wanted else 0))

    def _rules(self):
        for r in self.p.constraints:
            if not r.enabled or r.strength != 'HARD': continue
            if r.kind == 'RESOURCE_BLACKOUT':
                for e in self.p.events:
                    for d in self.domains[e.id]:
                        on = self.presence.get((e.id,r.resource_id,d.window_id))
                        if on is not None and any(self.overlaps_window(d,self.ws[w]) for w in r.window_ids):
                            self.m.add(on == 0)
            elif r.kind == 'EXCLUDE_RESOURCE_FROM_EVENT':
                for eid in r.event_ids:
                    for rid in r.resource_ids:
                        if r.role is None:
                            v = self.direct.get((eid,rid))
                            if v is not None: self.m.add(v == 0)
                        else:
                            for q in self.es[eid].requirements:
                                if q.role == r.role and (eid,q.id,rid) in self.y:
                                    self.m.add(self.y[eid,q.id,rid] == 0)
            elif r.kind == 'MAX_DAILY_MINUTES':
                for rid in r.resource_ids:
                    for day in self.ds:
                        terms = [d.work * self.presence[e.id,rid,d.window_id]
                                 for e in self.p.events for d in self.domains[e.id]
                                 if d.day == day and (e.id,rid,d.window_id) in self.presence]
                        self.m.add(sum(terms) <= r.limit_minutes)
            elif r.kind == 'WORKLOAD_BALANCE':
                totals = []
                for rid in r.resource_ids:
                    terms = []
                    for e in self.p.events:
                        v = self.direct.get((e.id,rid))
                        if v is None: continue
                        if r.metric == 'ASSIGNMENT_COUNT': terms.append(v)
                        else:
                            for d in self.domains[e.id]:
                                terms.append(d.work * self.AND([v,self.x[e.id,d.window_id]], 'direct_work'))
                    totals.append(sum(terms))
                for a,b in combinations(totals,2):
                    self.m.add(a-b <= r.target_spread); self.m.add(b-a <= r.target_spread)
            elif r.kind == 'ACTIVITY_SPREAD':
                for aid in r.activity_ids:
                    day_used = [self.OR([self.on_day[e.id,day] for e in self.p.events if e.activity_id == aid], 'activity_day')
                                for day in self.ds]
                    self.m.add(sum(day_used) >= r.minimum_distinct_days)
            elif r.kind == 'EVENT_BEFORE':
                self.m.add(self.starts[r.later_event_id] >= self.ends[r.earlier_event_id] + r.minimum_gap_minutes).only_enforce_if(
                    [self.a[r.earlier_event_id],self.a[r.later_event_id]])
            elif r.kind == 'EVENT_NOT_SAME_TIME':
                for a,b in combinations(r.event_ids,2):
                    order = self.b('pair_order')
                    self.m.add(self.ends[a] <= self.starts[b]).only_enforce_if([self.a[a],self.a[b],order])
                    self.m.add(self.ends[b] <= self.starts[a]).only_enforce_if([self.a[a],self.a[b],order.Not()])
            elif r.kind == 'EVENT_SAME_START':
                for a,b in combinations(r.event_ids,2):
                    self.m.add(self.starts[a] == self.starts[b]).only_enforce_if([self.a[a],self.a[b]])
            elif r.kind == 'QUALIFICATION':
                self._qualifications(r)
            elif r.kind == 'RESOURCE_CONTINUITY':
                for a,b in combinations(r.allocations,2):
                    qa = next(q for q in self.es[a.event_id].requirements if q.id == a.requirement_id)
                    qb = next(q for q in self.es[b.event_id].requirements if q.id == b.requirement_id)
                    for rid in sorted(set(qa.eligible_resource_ids)|set(qb.eligible_resource_ids)):
                        va=self.y.get((a.event_id,a.requirement_id,rid),0)
                        vb=self.y.get((b.event_id,b.requirement_id,rid),0)
                        self.m.add(va == vb).only_enforce_if([self.a[a.event_id],self.a[b.event_id]])
            elif r.kind == 'TRAVEL_TIME':
                self._travel(r)
            else:
                raise UnsupportedInput('UNSUPPORTED_HARD_RULE', r.kind)

    def _qualifications(self, rule):
        for ref in rule.allocations:
            q = next(q for q in self.es[ref.event_id].requirements if q.id == ref.requirement_id)
            for rid in q.eligible_resource_ids:
                for d in self.domains[ref.event_id]:
                    valid = True
                    for code in rule.all_of:
                        matches = [c for c in self.p.credentials if c.resource_id == rid and c.competency == code]
                        def covers(c):
                            if c.valid_during is None: return True
                            if self.ds[d.day].date is None: return False  # readiness has already refused uncertain dates
                            start_sec = c.valid_during.start.astimezone(timezone.utc).timestamp()
                            end_sec = c.valid_during.end.astimezone(timezone.utc).timestamp()
                            return start_sec <= d.absolute_start*60 and d.absolute_end*60 <= end_sec
                        if not any(covers(c) for c in matches): valid=False; break
                    if not valid:
                        self.m.add(self.y[ref.event_id,q.id,rid]+self.x[ref.event_id,d.window_id] <= 1)

    def _travel(self, rule):
        arcs_by_loc = {(a.profile,a.from_location,a.to_location):a.minutes for a in self.p.travel_arcs}
        for rid in rule.resource_ids:
            for day in self.ds:
                ids = [e.id for e in self.p.events if (e.id,rid) in self.used and any(d.day==day for d in self.domains[e.id])]
                if len(ids) < 2: continue
                present={eid:self.AND([self.used[eid,rid],self.on_day[eid,day]],'traveler_day') for eid in ids}
                any_present=self.OR(present.values(),'traveler_present')
                edges=[(0,0,any_present.Not())]
                for i,eid in enumerate(ids,1):
                    edges.append((i,i,present[eid].Not()))
                    first=self.b('route_first');last=self.b('route_last')
                    self.m.add(first<=present[eid]);self.m.add(last<=present[eid])
                    edges.extend([(0,i,first),(i,0,last)])
                for i,a in enumerate(ids,1):
                    for j,b in enumerate(ids,1):
                        if i==j:continue
                        # A circuit, cut at node 0, selects only actual consecutive events.
                        nxt=self.b('route_next');edges.append((i,j,nxt))
                        self.m.add(nxt<=present[a]);self.m.add(nxt<=present[b])
                        self.m.add(self.ends[a]<=self.starts[b]).only_enforce_if(nxt)
                        la={loc:v for (eid,loc),v in self.at_location.items() if eid==a}
                        lb={loc:v for (eid,loc),v in self.at_location.items() if eid==b}
                        self.m.add(sum(la.values())==1).only_enforce_if(nxt)
                        self.m.add(sum(lb.values())==1).only_enforce_if(nxt)
                        for left,lv in la.items():
                            for right,rv in lb.items():
                                gap=0 if left==right else arcs_by_loc[self.rs[rid].travel_profile,left,right]
                                self.m.add(self.starts[b]>=self.ends[a]+gap).only_enforce_if([nxt,lv,rv])
                self.m.add_circuit(edges)

    def extract(self, solver, model_hash: str):
        from veni_grid_contract.core_v1 import CoreWitness
        import hashlib, json
        events=[]; enroll=[]
        for e in self.p.events:
            if not solver.boolean_value(self.a[e.id]):continue
            d=next(d for d in self.domains[e.id] if solver.boolean_value(self.x[e.id,d.window_id]))
            allocations=[{'requirement_id':q.id,'resource_ids':sorted(rid for rid in q.eligible_resource_ids
                          if solver.boolean_value(self.y[e.id,q.id,rid]))} for q in e.requirements]
            events.append({'event_id':e.id,'start_window_id':d.window_id,'resource_allocations':allocations})
        for req in self.p.participation_requests:
            enroll.append({'request_id':req.id,'offering_ids':sorted(oid for oid in req.eligible_offering_ids
                            if solver.boolean_value(self.en[req.id,oid]))})
        output_hash = hashlib.sha256(json.dumps({'events': events, 'enrollments': enroll}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return CoreWitness(solution_id=f'solution:c1:{model_hash[:12]}:{output_hash[:12]}',problem_id=self.p.problem_id,
            model_version=self.p.model_version,status='FEASIBLE',event_assignments=events,
            enrollment_assignments=enroll,validation='UNVALIDATED')
