"""Derive complete occupancy for a *fully dated* placement witness.

Abstract cycle days fail closed. The general recurring calendar-to-claims bridge
remains a separate gate: no synthetic epoch is used for inter-schedule clashes.
"""
from __future__ import annotations
from .models import ResourceKind
from .primitives import CapacityResource, Interval, ResourceClaim, usage_errors
from .handoff_common import HandoffError, stable_id
from .placement_v04 import PlacementProblem, PlacementWitness, placement_witness_errors
from .validation import window_placement
from .calendar_projection import resolve_local


def dated_placement_resources(p: PlacementProblem) -> list[CapacityResource]:
    if any(d.date is None for d in p.days):
        raise HandoffError("UNRESOLVED_CALENDAR", "Cross-schedule claims require concrete dated occurrences")
    days={d.id:d for d in p.days};windows={w.id:w for w in p.windows}
    out=[]
    for r in p.resources:
        unavailable=[]
        for wid in r.unavailable_window_ids:
            w=windows[wid];day=days[w.day_id].date
            unavailable.append(Interval(start=resolve_local(day,w.start_minute,p.timezone),
                                        end=resolve_local(day,w.end_minute,p.timezone)))
        out.append(CapacityResource(id=r.id,kind=r.kind.value,sharing=r.sharing_mode,
                   capacity=r.capacity or 1,unit="SEATS" if r.kind==ResourceKind.SPACE else "USE",
                   unavailable=unavailable))
    return out


def derive_dated_placement_claims(p: PlacementProblem,w: PlacementWitness) -> list[ResourceClaim]:
    """Verify first, then derive *all* event, role and membership occupancy."""
    errors=placement_witness_errors(p,w)
    if errors: raise HandoffError("INVALID_PLACEMENT_WITNESS","; ".join(e.code for e in errors))
    catalog=dated_placement_resources(p)
    resources={r.id:r for r in p.resources};events={e.id:e for e in p.events}
    days={d.id:d for d in p.days};requests={r.id:r for r in p.participation_requests}
    members={o.id:set() for o in p.offerings}
    for a in w.enrollment_assignments:
        for oid in a.offering_ids: members[oid].add(requests[a.request_id].participant_id)
    def expand(rid):
        r=resources[rid]
        if r.kind==ResourceKind.GROUP:
            # Structural validation above already rules out membership cycles.
            result={rid}
            for child in r.member_ids: result |= expand(child)
            return result
        return {rid}
    claims=[]
    for a in sorted(w.event_assignments,key=lambda x:x.event_id):
        e=events[a.event_id];dayid,start,end,_=window_placement(p,e,a.start_window_id)
        day=days[dayid].date
        interval=Interval(start=resolve_local(day,start,p.timezone),end=resolve_local(day,end,p.timezone))
        reqs={q.id:q for q in e.requirements};units={}
        for rid in e.fixed_participant_ids:
            for member in expand(rid): units[member]=1
        for rid in members.get(e.offering_id,set()): units[rid]=1
        for alloc in a.resource_allocations:
            q=reqs[alloc.requirement_id]
            for rid in alloc.resource_ids:
                for member in expand(rid):
                    r=resources[member]
                    if r.sharing_mode=="CUMULATIVE":
                        if q.usage_units is None: raise HandoffError("MISSING_USAGE_UNITS",rid)
                        units[member]=q.usage_units
                    else: units[member]=1
        for rid,amount in sorted(units.items()):
            claims.append(ResourceClaim(id=stable_id("claim",p.problem_id,e.id,rid,str(day)),
                schedule_id=p.problem_id,entity_id=e.id,resource_id=rid,units=amount,interval=interval))
    checks=usage_errors(catalog,claims)
    if checks: raise HandoffError("DERIVED_PLACEMENT_CONFLICT","; ".join(e.code for e in checks))
    return claims
