"""Deterministic cycle-to-date projection, not rescheduling or optimisation.

A closed date explicitly advances or freezes the cycle. Bells may be replaced for
a date. Cancelling a specific dated occurrence needs an explicit recorded override.
Ambiguous/nonexistent local times fail closed in this draft; no guessed DST fold.
"""
from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import Field, model_validator
from .models import ID
from .primitives import ContractModel, Positive, NonNegative, Interval

class BellPeriod(ContractModel):
    key: ID
    start_minute: NonNegative = Field(lt=1440)
    end_minute: Positive = Field(le=1440)
    @model_validator(mode="after")
    def order(self):
        if self.end_minute<=self.start_minute: raise ValueError("Overnight bell templates unsupported in this draft")
        return self

class BellSet(ContractModel):
    id: ID
    periods: list[BellPeriod] = Field(min_length=1)

class CalendarException(ContractModel):
    date: date
    kind: Literal["CLOSED","REPLACE_BELLS"]
    advance_cycle: bool
    reason: str = Field(min_length=1)
    replacement_bell_id: ID | None = None
    @model_validator(mode="after")
    def consistency(self):
        if (self.kind=="REPLACE_BELLS") != (self.replacement_bell_id is not None):
            raise ValueError("Only a bell replacement requires replacement_bell_id")
        return self

class CyclePattern(ContractModel):
    id: ID
    event_id: ID
    cycle_day: Positive
    period_key: ID

class OccurrenceCancellation(ContractModel):
    pattern_id: ID
    date: date
    reason: str = Field(min_length=1)
    authorised_by: str = Field(min_length=1)

class CalendarProjection(ContractModel):
    schema_version: Literal["0.3.0-draft"] = "0.3.0-draft"
    problem_id: ID
    timezone: str
    anchor_date: date
    anchor_cycle_day: Positive = 1
    cycle_length: Positive
    weekdays: list[NonNegative] = Field(min_length=1)
    horizon_start: date
    horizon_end: date
    default_bell_id: ID
    bell_sets: list[BellSet]
    patterns: list[CyclePattern]
    exceptions: list[CalendarException] = Field(default_factory=list)
    cancellations: list[OccurrenceCancellation] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistency(self):
        ZoneInfo(self.timezone)
        if not self.anchor_date<=self.horizon_start<=self.horizon_end: raise ValueError("Invalid horizon/anchor")
        if (self.horizon_end-self.anchor_date).days>3660: raise ValueError("Draft projection horizon exceeds 10 years")
        if self.anchor_cycle_day>self.cycle_length or any(w>6 for w in self.weekdays): raise ValueError("Cycle/weekday out of range")
        if len(set(self.weekdays))!=len(self.weekdays): raise ValueError("Duplicate weekdays")
        for items in [self.bell_sets,self.patterns]:
            if len({x.id for x in items})!=len(items): raise ValueError("Duplicate ID")
        bells={b.id:b for b in self.bell_sets}
        if self.default_bell_id not in bells: raise ValueError("Unknown default bells")
        for b in self.bell_sets:
            if len({p.key for p in b.periods})!=len(b.periods): raise ValueError("Duplicate bell period")
        if len({e.date for e in self.exceptions})!=len(self.exceptions): raise ValueError("Conflicting date exceptions")
        for e in self.exceptions:
            if not self.anchor_date<=e.date<=self.horizon_end: raise ValueError("Exception outside projection")
            if e.replacement_bell_id and e.replacement_bell_id not in bells: raise ValueError("Unknown replacement bells")
        if any(p.cycle_day>self.cycle_length for p in self.patterns): raise ValueError("Pattern cycle out of range")
        if len({(c.pattern_id,c.date) for c in self.cancellations})!=len(self.cancellations): raise ValueError("Duplicate cancellation")
        for c in self.cancellations:
            if c.pattern_id not in {p.id for p in self.patterns} or not self.horizon_start<=c.date<=self.horizon_end:
                raise ValueError("Invalid cancellation target")
        return self

class ProjectedOccurrence(ContractModel):
    id: ID
    pattern_id: ID
    event_id: ID
    date: date
    cycle_day: Positive
    bell_id: ID
    interval: Interval

def resolve_local(day: date,minute: int,zone: str) -> datetime:
    naive=datetime.combine(day,datetime.min.time())+timedelta(minutes=minute)
    tz=ZoneInfo(zone)
    candidates=[]
    for fold in (0,1):
        aware=naive.replace(tzinfo=tz,fold=fold)
        if aware.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)==naive:
            candidates.append(aware)
    instants={x.astimezone(timezone.utc) for x in candidates}
    if len(instants)!=1: raise ValueError("Ambiguous or nonexistent local time; explicit resolution required")
    return candidates[0]

def project_calendar(p: CalendarProjection) -> list[ProjectedOccurrence]:
    bells={b.id:b for b in p.bell_sets};exceptions={e.date:e for e in p.exceptions}
    cancellations={(c.pattern_id,c.date) for c in p.cancellations};used=set()
    day=p.anchor_date;cycle=p.anchor_cycle_day;out=[]
    while day<=p.horizon_end:
        exception=exceptions.get(day)
        normal=day.weekday() in p.weekdays
        is_open=(exception.kind=="REPLACE_BELLS") if exception else normal
        if exception and exception.kind=="CLOSED": is_open=False
        advance=exception.advance_cycle if exception else normal
        if is_open and day>=p.horizon_start:
            bid=(exception.replacement_bell_id if exception and exception.kind=="REPLACE_BELLS" else p.default_bell_id)
            periods={x.key:x for x in bells[bid].periods}
            for pattern in p.patterns:
                if pattern.cycle_day!=cycle: continue
                if (pattern.id,day) in cancellations:
                    used.add((pattern.id,day));continue
                period=periods.get(pattern.period_key)
                if period is None: raise ValueError(f"Missing period {pattern.period_key} in {bid}; explicit cancellation required")
                out.append(ProjectedOccurrence(id=f"{pattern.id}:{day.isoformat()}",pattern_id=pattern.id,event_id=pattern.event_id,
                    date=day,cycle_day=cycle,bell_id=bid,interval=Interval(start=resolve_local(day,period.start_minute,p.timezone),
                                                                         end=resolve_local(day,period.end_minute,p.timezone))))
        if advance: cycle=cycle%p.cycle_length+1
        day+=timedelta(days=1)
    if cancellations-used: raise ValueError("Cancellation does not match an actual occurrence")
    return out
