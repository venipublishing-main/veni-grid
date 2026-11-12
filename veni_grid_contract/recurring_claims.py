"""Cycle placement -> dated occurrences -> complete claims, with explicit exceptions.

Does not change the source timetable. A finite, version-pinned projection is a
view of the accepted cycle. Unknown local clock instants and missing bell mappings
fail closed. Source demand is not changed when a dated occurrence is cancelled.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta, timezone
from typing import Literal
from pydantic import Field

from .models import ID, ResourceKind, MaxDailyMinutes, RuleStrength, ResourceBlackout
from .primitives import ContractModel, Positive, NonNegative, Interval, ResourceClaim, CapacityResource, Finding, usage_errors
from .calendar_projection import BellSet, CalendarException, resolve_local
from .handoff_common import fingerprint, stable_id, HandoffError
from .placement_v04 import SameStart
from .models import EventNotTogether, EventOrdering
from .core_v1 import CoreProblem, CoreWitness, ResolvedUse, core_witness_errors, resolved_use, operational_errors, expand_resources


class DayCycle(ContractModel):
    day_id: ID
    cycle_day: Positive


class WindowPeriod(ContractModel):
    window_id: ID
    period_key: ID


class EventCancellation(ContractModel):
    event_id: ID
    on_date: date
    reason: str = Field(min_length=1)
    authorised_by: str = Field(min_length=1)


class RecurrenceConfig(ContractModel):
    schema_version: Literal["1.0.0-rc1"] = "1.0.0-rc1"
    calendar_id: ID
    revision: Positive
    problem_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    witness_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_date: date
    anchor_cycle_day: Positive = 1
    cycle_length: Positive
    horizon_start: date
    horizon_end: date
    weekdays: list[NonNegative] = Field(min_length=1)
    day_cycle: list[DayCycle]
    window_periods: list[WindowPeriod]
    default_bell_id: ID
    bell_sets: list[BellSet] = Field(min_length=1)
    exceptions: list[CalendarException] = Field(default_factory=list)
    cancellations: list[EventCancellation] = Field(default_factory=list)


class ProjectionResult(ContractModel):
    schema_version: Literal["1.0.0-rc1"] = "1.0.0-rc1"
    problem_sha256: str
    witness_sha256: str
    config_sha256: str
    occurrences: list[ResolvedUse]
    claims: list[ResourceClaim]
    cancelled: list[EventCancellation]
    validity: Literal["VALIDATED_PROJECTION_NOT_PUBLISHED"] = "VALIDATED_PROJECTION_NOT_PUBLISHED"
    coverage_scope: Literal["SUPPLIED_HORIZON_AND_COMMITMENTS_ONLY"] = "SUPPLIED_HORIZON_AND_COMMITMENTS_ONLY"


def _require(condition, code, detail):
    if not condition: raise HandoffError(code, detail)


def project_claims(problem: CoreProblem, witness: CoreWitness, config: RecurrenceConfig,
                   external_claims: list[ResourceClaim] | None = None) -> ProjectionResult:
    p = CoreProblem.model_validate(problem.model_dump(mode="json"))
    w = CoreWitness.model_validate(witness.model_dump(mode="json"))
    c = RecurrenceConfig.model_validate(config.model_dump(mode="json"))
    _require(c.problem_sha256 == fingerprint(p) and c.witness_sha256 == fingerprint(w), "STALE_PROJECTION_INPUT", "Cycle model or candidate changed")
    errors = core_witness_errors(p, w, defer_dated_credentials=True)
    _require(not errors, "INVALID_CYCLE_WITNESS", "; ".join(x.code for x in errors))
    _require(all(d.date is None for d in p.days), "NOT_ABSTRACT_CYCLE", "Already dated data must not be projected again")
    _require(c.anchor_date <= c.horizon_start <= c.horizon_end and (c.horizon_end-c.anchor_date).days <= 3660,
             "INVALID_PROJECTION_HORIZON", "Ordered finite horizon, at most ten years")
    _require(c.anchor_cycle_day <= c.cycle_length, "INVALID_CYCLE_ANCHOR", "Out of range")
    _require(len(set(c.weekdays)) == len(c.weekdays) and all(type(x) is int and 0 <= x <= 6 for x in c.weekdays), "INVALID_WEEKDAYS", "Unique weekday integers required")
    dc = {d.day_id: d.cycle_day for d in c.day_cycle}
    _require(len(dc) == len(c.day_cycle) and set(dc) == {d.id for d in p.days} and set(dc.values()) == set(range(1, c.cycle_length+1)) and len(dc) == c.cycle_length,
             "INCOMPLETE_CYCLE_MAP", "Exactly one source day for each cycle day")
    wm = {x.window_id: x.period_key for x in c.window_periods}; wins = {x.id: x for x in p.windows}
    _require(len(wm) == len(c.window_periods) and set(wm) == set(wins), "INCOMPLETE_WINDOW_MAP", "Every source window must be mapped")
    for day in dc:
        keys = [wm[x.id] for x in p.windows if x.day_id == day]
        _require(len(keys) == len(set(keys)), "ALIASED_BELL_MAPPING", "Distinct source periods on one day require distinct keys")
    bells = {b.id: b for b in c.bell_sets}
    _require(len(bells) == len(c.bell_sets) and c.default_bell_id in bells, "INVALID_BELL_CATALOG", "Unique bell IDs and known default")
    for bell in c.bell_sets:
        _require(len({x.key for x in bell.periods}) == len(bell.periods), "DUPLICATE_PERIOD_KEY", bell.id)
    exceptions = {e.date: e for e in c.exceptions}
    _require(len(exceptions) == len(c.exceptions), "DUPLICATE_CALENDAR_EXCEPTION", "One date policy required")
    for e in c.exceptions:
        _require(c.anchor_date <= e.date <= c.horizon_end, "EXCEPTION_OUTSIDE_HORIZON", str(e.date))
        _require(e.replacement_bell_id is None or e.replacement_bell_id in bells, "UNKNOWN_REPLACEMENT_BELLS", str(e.date))
    cancels = {(x.event_id, x.on_date): x for x in c.cancellations}
    _require(len(cancels) == len(c.cancellations), "DUPLICATE_CANCELLATION", "Duplicate event/date")
    es = {e.id: e for e in p.events}; assignments = {a.event_id: a for a in w.event_assignments}
    _require(all(eid in assignments and c.horizon_start <= d <= c.horizon_end for eid, d in cancels), "INVALID_CANCELLATION_TARGET", "Only active occurrences inside the horizon")
    used_cancels = set(); uses = []; claims = []; iterations = {}
    catalogs = {r.id: CapacityResource(id=r.id, kind=r.kind.value, sharing=r.sharing_mode, capacity=r.capacity or 1,
                                      unit="SEATS" if r.kind == ResourceKind.SPACE else "USE") for r in p.resources}
    day = c.anchor_date; cycle = c.anchor_cycle_day; iteration = 0
    while day <= c.horizon_end:
        ex = exceptions.get(day); normal = day.weekday() in c.weekdays
        opened = (ex.kind == "REPLACE_BELLS") if ex else normal
        advance = ex.advance_cycle if ex else normal
        if opened and day >= c.horizon_start:
            bid = ex.replacement_bell_id if ex and ex.kind == "REPLACE_BELLS" else c.default_bell_id
            periods = {x.key: x for x in bells[bid].periods}
            current_day = next(did for did, number in dc.items() if number == cycle)
            def period(wid):
                key = wm[wid]
                _require(key in periods, "MISSING_DATED_PERIOD", f"{day}/{bid}/{key}")
                return periods[key]
            def interval_for(wid):
                b = period(wid)
                return Interval(start=resolve_local(day, b.start_minute, p.timezone), end=resolve_local(day, b.end_minute, p.timezone))
            # Blackout rules are actual-time obstacles on every occurrence of the source cycle day.
            for r in p.resources:
                blocked = set(r.unavailable_window_ids)
                for rule in p.constraints:
                    if isinstance(rule, ResourceBlackout) and rule.enabled and rule.strength == RuleStrength.HARD and rule.resource_id == r.id:
                        blocked |= set(rule.window_ids)
                for wid in sorted(blocked):
                    if wins[wid].day_id == current_day: catalogs[r.id].unavailable.append(interval_for(wid))
            for a in w.event_assignments:
                first = wins[a.start_window_id]
                if first.day_id != current_day: continue
                if (a.event_id, day) in cancels:
                    used_cancels.add((a.event_id, day)); continue
                event = es[a.event_id]; first_period = period(first.id)
                start = first_period.start_minute
                if event.duration.unit == "MINUTES":
                    end = start+event.duration.count
                    _require(end <= first_period.end_minute, "MINUTE_LESSON_NO_LONGER_FITS", f"{event.id}/{day}")
                    teaching_minutes = event.duration.count
                else:
                    chain = sorted([x for x in p.windows if x.day_id == current_day and x.bell_id == first.bell_id and first.sequence <= x.sequence < first.sequence+event.duration.count], key=lambda x: x.sequence)
                    _require(len(chain) == event.duration.count, "MISSING_DOUBLE_PERIOD", event.id)
                    actual = [period(x.id) for x in chain]
                    for left, right in zip(actual, actual[1:]):
                        _require(0 <= right.start_minute-left.end_minute <= event.duration.max_gap_minutes,
                                 "DATED_ADJACENCY_BROKEN", f"{event.id}/{day}")
                    end = actual[-1].end_minute
                    teaching_minutes = sum(x.end_minute-x.start_minute for x in actual)
                iv = Interval(start=resolve_local(day, start, p.timezone), end=resolve_local(day, end, p.timezone))
                oid = stable_id("occurrence", p.problem_id, event.id, day.isoformat())
                use = resolved_use(p, w, a, occurrence_id=oid, day_key=day.isoformat(), start=start, end=end, interval=iv, work_minutes=teaching_minutes)
                uses.append(use); iterations[oid] = iteration
                reqs = {q.id: q for q in event.requirements}; amounts = {rid: 1 for rid in use.resource_ids}
                for alloc in a.resource_allocations:
                    q = reqs[alloc.requirement_id]
                    for rid in alloc.resource_ids:
                        if catalogs[rid].sharing == "CUMULATIVE":
                            _require(q.usage_units is not None, "MISSING_USAGE_UNITS", rid)
                            amounts[rid] = q.usage_units
                for rid, units in sorted(amounts.items()):
                    claims.append(ResourceClaim(id=stable_id("claim", oid, rid), schedule_id=p.problem_id, entity_id=oid,
                                                resource_id=rid, interval=iv, units=units))
            # Daily rules count actual teaching minutes; resource occupancy includes permitted gaps.
            todays = [u for u in uses if u.day_key == day.isoformat()]
            for rule in p.constraints:
                if isinstance(rule, MaxDailyMinutes) and rule.enabled and rule.strength == RuleStrength.HARD:
                    for rid in rule.resource_ids:
                        total = sum(u.work_minutes for u in todays if rid in u.resource_ids)
                        _require(total <= rule.limit_minutes, "DATED_DAILY_LOAD_EXCEEDED", f"{rid}/{day}: {total}")
        if advance:
            if cycle == c.cycle_length: iteration += 1
            cycle = cycle % c.cycle_length+1
        day += timedelta(days=1)
    _require(set(cancels) == used_cancels, "CANCELLATION_NOT_AN_OCCURRENCE", "Cancellation must identify an actual source occurrence")
    errors = usage_errors(list(catalogs.values()), claims + (external_claims or []))
    errors += operational_errors(p, uses)
    # Re-evaluate relations on actual dates; changed bell regimes may invalidate alignment.
    for cycle_number in set(iterations.values()):
        edition = {u.event_id: u for u in uses if iterations[u.occurrence_id] == cycle_number}
        for rule in p.constraints:
            if not rule.enabled or rule.strength != RuleStrength.HARD: continue
            if isinstance(rule, SameStart):
                starts = {edition[e].interval.start.astimezone(timezone.utc) for e in rule.event_ids if e in edition}
                if len(starts) > 1: errors.append(Finding(code="DATED_SYNCHRONISATION_BROKEN", detail=rule.id))
            if isinstance(rule, EventNotTogether):
                active = [edition[e] for e in rule.event_ids if e in edition]
                if any(a.interval.overlaps(b.interval) for i,a in enumerate(active) for b in active[i+1:]):
                    errors.append(Finding(code="DATED_ANTI_ALIGNMENT_BROKEN", detail=rule.id))
            if isinstance(rule, EventOrdering):
                a,b = edition.get(rule.earlier_event_id),edition.get(rule.later_event_id)
                if a is not None and b is not None:
                    gap = (b.interval.start.astimezone(timezone.utc)-a.interval.end.astimezone(timezone.utc)).total_seconds()/60
                    if gap < rule.minimum_gap_minutes: errors.append(Finding(code="DATED_ORDER_GAP_BROKEN", detail=rule.id))
    _require(not errors, "PROJECTED_CONFLICT", "; ".join(f"{e.code}:{e.detail}" for e in errors))
    return ProjectionResult(problem_sha256=fingerprint(p), witness_sha256=fingerprint(w), config_sha256=fingerprint(c),
                            occurrences=uses, claims=claims, cancelled=list(c.cancellations))
