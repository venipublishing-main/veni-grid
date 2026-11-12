"""Piecewise staff coverage over fixed sessions, using the common resource checker.

Venue/time facts are read-only inputs. Staff assignments do not acquire the exam's
venue again: the examination schedule owns that reservation.
"""
from __future__ import annotations
from datetime import timezone
from typing import Literal
from pydantic import Field
from .models import ID
from .primitives import (ContractModel, Positive, Interval, CapacityResource,
                         ResourceClaim, Finding, usage_errors, unique_errors)

class FixedSession(ContractModel):
    id: ID
    venue_id: ID
    interval: Interval

class CoverageDemand(ContractModel):
    id: ID
    session_id: ID
    role: str
    interval: Interval
    minimum_staff: Positive
    eligible_staff_ids: list[ID] = Field(min_length=1)

class CoverageProblem(ContractModel):
    schema_version: Literal["0.3.0-draft"] = "0.3.0-draft"
    problem_id: ID
    model_version: Positive
    schedule_id: ID
    resources: list[CapacityResource] = Field(min_length=1)
    sessions: list[FixedSession] = Field(min_length=1)
    demands: list[CoverageDemand] = Field(min_length=1)

class StaffDuty(ContractModel):
    id: ID
    session_id: ID
    resource_id: ID
    role: str
    interval: Interval

class CoverageWitness(ContractModel):
    schema_version: Literal["0.3.0-draft"] = "0.3.0-draft"
    problem_id: ID
    model_version: Positive
    duties: list[StaffDuty]


def coverage_errors(p: CoverageProblem,w: CoverageWitness) -> list[Finding]:
    errors=(unique_errors(p.sessions,"sessions")+unique_errors(p.demands,"demands")
            +unique_errors(w.duties,"duties"))
    def bad(code,detail): errors.append(Finding(code=code,detail=detail))
    def utc(t): return t.astimezone(timezone.utc)
    def contains(outer,inner): return utc(outer.start)<=utc(inner.start) and utc(inner.end)<=utc(outer.end)
    if (p.problem_id,p.model_version)!=(w.problem_id,w.model_version): bad("STALE_COVERAGE",p.problem_id)
    sessions={s.id:s for s in p.sessions};resources={r.id:r for r in p.resources}
    for session in p.sessions:
        if session.venue_id not in resources or resources[session.venue_id].kind!="SPACE": bad("UNKNOWN_VENUE",session.id)
    for d in p.demands:
        if d.session_id not in sessions or not contains(sessions[d.session_id].interval,d.interval): bad("INVALID_DEMAND_INTERVAL",d.id)
        if len(set(d.eligible_staff_ids))!=len(d.eligible_staff_ids): bad("DUPLICATE_ELIGIBILITY",d.id)
        for rid in d.eligible_staff_ids:
            if rid not in resources or resources[rid].kind!="PERSON": bad("INVALID_ELIGIBLE_STAFF",rid)
    # Coverage requirements themselves must not leave an unmodelled part of a session.
    for session in p.sessions:
        demands=[d for d in p.demands if d.session_id==session.id]
        points=sorted({utc(session.interval.start),utc(session.interval.end)} | {
            utc(t) for d in demands for t in (d.interval.start,d.interval.end)
            if utc(session.interval.start)<utc(t)<utc(session.interval.end)})
        for start,end in zip(points,points[1:]):
            if not any(utc(d.interval.start)<=start and end<=utc(d.interval.end) for d in demands):
                bad("DEMAND_COVERAGE_GAP",session.id)
    # Ambiguous overlapping definitions for the same role/session fail closed.
    for i,d in enumerate(p.demands):
        for e in p.demands[i+1:]:
            if (d.session_id,d.role)==(e.session_id,e.role) and d.interval.overlaps(e.interval): bad("OVERLAPPING_COVERAGE_DEMANDS",d.id)
    claims=[]
    for duty in w.duties:
        session=sessions.get(duty.session_id);resource=resources.get(duty.resource_id)
        if not session or not resource or resource.kind!="PERSON": bad("INVALID_STAFF_DUTY",duty.id);continue
        if not contains(session.interval,duty.interval): bad("DUTY_OUTSIDE_SESSION",duty.id)
        matching=[d for d in p.demands if (d.session_id,d.role)==(duty.session_id,duty.role)]
        points=sorted({utc(duty.interval.start),utc(duty.interval.end)} | {
            utc(t) for d in matching for t in (d.interval.start,d.interval.end)
            if utc(duty.interval.start)<utc(t)<utc(duty.interval.end)})
        for start,end in zip(points,points[1:]):
            active=[d for d in matching if utc(d.interval.start)<=start and end<=utc(d.interval.end)]
            if not active: bad("DUTY_WITHOUT_DEMAND",duty.id)
            elif any(duty.resource_id not in d.eligible_staff_ids for d in active): bad("STAFF_INELIGIBLE",duty.id)
        claims.append(ResourceClaim(id=duty.id,schedule_id=p.schedule_id,entity_id=duty.session_id,
                                    resource_id=duty.resource_id,interval=duty.interval))
    errors.extend(usage_errors(p.resources,claims))
    for d in p.demands:
        matching=[a for a in w.duties if (a.session_id,a.role)==(d.session_id,d.role)
                  and a.resource_id in d.eligible_staff_ids]
        points=sorted({utc(d.interval.start),utc(d.interval.end)} | {
            utc(t) for a in matching for t in (a.interval.start,a.interval.end)
            if utc(d.interval.start)<utc(t)<utc(d.interval.end)})
        for start,end in zip(points,points[1:]):
            staff={a.resource_id for a in matching if utc(a.interval.start)<=start and end<=utc(a.interval.end)}
            if len(staff)<d.minimum_staff: bad("COVERAGE_GAP",f"{d.id}: {len(staff)}/{d.minimum_staff} from {start.isoformat()} to {end.isoformat()}")
    return errors


def duty_minutes(w: CoverageWitness) -> dict[str,float]:
    """Use only after coverage_errors passes: overlapping allocations are invalid."""
    totals={}
    for a in w.duties: totals[a.resource_id]=totals.get(a.resource_id,0)+a.interval.minutes
    return totals
